import base64
import hashlib
import imaplib
import json
import math
import smtplib
import socket
import ssl
import time
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, make_msgid

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend
from django.utils.module_loading import import_string
from django.db import transaction
from django.utils import timezone

from . import storage
from .auth import Actor, DomainError
from .models import Dispatch, ImportSource, Job, Mailbox, SendAttempt
from .packages import get_package, package_bytes
from .services import ingest

SECRET_FIELDS = {"imap_password", "smtp_password"}
CONFIG_FIELDS = {
    "imap_host",
    "imap_port",
    "imap_tls",
    "imap_user",
    "imap_folder",
    "import_since",
    "enabled",
    "aliases",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_security",
    "sender",
    "reply_to",
    "max_message_bytes",
    "subject_template",
    "body_template",
} | SECRET_FIELDS


def cipher():
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value):
    return cipher().encrypt(value.encode()).decode() if value else ""


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode() if value else ""
    except InvalidToken as e:
        raise DomainError("Mailgeheimnis nicht entschlüsselbar. Sicherung des SECRET_KEY prüfen.") from e


def mail_config(actor, company_id, payload=None):
    company = actor.require(company_id, "admin")
    mailbox, _ = Mailbox.objects.get_or_create(company=company)
    if payload is not None:
        unknown = set(payload) - CONFIG_FIELDS
        if unknown:
            raise DomainError("Unbekannte Mail-Einstellungen: " + ", ".join(sorted(unknown)))
        for key, value in payload.items():
            if key in SECRET_FIELDS:
                # null leaves a secret unchanged; empty string explicitly removes it.
                if value is not None:
                    setattr(mailbox, key, encrypt(value))
            else:
                setattr(mailbox, key, value)
        if mailbox.enabled and (not mailbox.imap_host or not mailbox.imap_user or not mailbox.import_since):
            raise DomainError("IMAP benötigt Host, Benutzer und expliziten Importbeginn.")
        if not 4096 <= mailbox.max_message_bytes <= 100 * 1024 * 1024:
            raise DomainError("Mailgrößenlimit muss zwischen 4096 Bytes und 100 MiB liegen.")
        for template in (mailbox.subject_template, mailbox.body_template):
            try:
                template.format(company="Firma", period="2026-01", version=1, notes="")
            except KeyError, ValueError, IndexError, AttributeError:
                raise DomainError(
                    "Erlaubte Vorlagenfelder: {company}, {period}, {version}, {notes}."
                ) from None
        if mailbox.imap_host and mailbox.imap_user:
            shared = Mailbox.objects.filter(
                imap_host=mailbox.imap_host, imap_user=mailbox.imap_user, imap_folder=mailbox.imap_folder
            ).exclude(company=company)
            for other in shared:
                if (
                    not mailbox.aliases
                    or not other.aliases
                    or set(a.lower() for a in mailbox.aliases).intersection(a.lower() for a in other.aliases)
                ):
                    raise DomainError(
                        "Geteiltes Postfach benötigt getrennte, eindeutige Empfänger-/Aliasregeln je Firma."
                    )
        from .services import validate_recipients

        validate_recipients(mailbox.aliases)
        from django.core.exceptions import ValidationError

        try:
            mailbox.full_clean()
        except ValidationError as e:
            raise DomainError("Mailkonfiguration ungültig.", details=e.message_dict) from e
        mailbox.save()
    result = {k: getattr(mailbox, k) for k in CONFIG_FIELDS - SECRET_FIELDS}
    result.update({k + "_set": bool(getattr(mailbox, k)) for k in SECRET_FIELDS})
    result.update(
        {
            "id": mailbox.id,
            "last_uid": mailbox.last_uid,
            "uidvalidity": mailbox.uidvalidity,
            "last_scan_at": mailbox.last_scan_at,
        }
    )
    return result


def safe_mail_text(value):
    # PostgreSQL JSONB cannot contain NUL or unpaired surrogate characters.
    # Keep malformed header values visibly escaped rather than blocking the
    # entire mailbox; the unchanged attachment and source message hash remain.
    return str(value).replace("\x00", r"\u0000").encode("utf-8", errors="backslashreplace").decode("utf-8")


def source_key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def import_message(actor, mailbox, uidvalidity, uid, raw):
    """Each attachment gets a durable provenance record before a message is checkpointed."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    raw_hash = storage.checksum(raw)
    recipients = [
        a.lower()
        for _, a in getaddresses(
            message.get_all("to", []) + message.get_all("cc", []) + message.get_all("delivered-to", [])
        )
    ]
    company_id = mailbox.company_id
    if mailbox.aliases:
        matching_companies = {
            m.company_id
            for m in Mailbox.objects.filter(
                imap_host=mailbox.imap_host, imap_user=mailbox.imap_user, imap_folder=mailbox.imap_folder
            )
            if set(a.lower() for a in m.aliases).intersection(recipients)
        }
        if matching_companies != {mailbox.company_id}:
            company_id = None
    count = 0
    for index, part in enumerate(message.walk()):
        filename = part.get_filename()
        if part.is_multipart() or (not filename and part.get_content_disposition() != "attachment"):
            continue
        count += 1
        identity = source_key(mailbox.id, str(uidvalidity), str(uid), index)
        if ImportSource.objects.filter(identity=identity).exists():
            continue
        data = part.get_payload(decode=True) or b""
        stable = source_key(mailbox.id, raw_hash, index, storage.checksum(data))
        provenance = {
            "sender": safe_mail_text(message.get("from", "")),
            "recipients": [safe_mail_text(r) for r in recipients],
            "subject": safe_mail_text(message.get("subject", "")),
            "date": safe_mail_text(message.get("date", "")),
            "message_id": safe_mail_text(message.get("message-id", "")),
            "mailbox_id": mailbox.id,
            "folder": mailbox.imap_folder,
            "uidvalidity": str(uidvalidity),
            "uid": str(uid),
            "part": index,
            "filename": safe_mail_text(filename or "anhang"),
            "raw_message_sha256": raw_hash,
        }
        with transaction.atomic():
            # Mailbox row protects attachment idempotency across manual and scheduled scans.
            Mailbox.objects.select_for_update().get(id=mailbox.id)
            if ImportSource.objects.filter(identity=identity).exists():
                continue
            existing = ImportSource.objects.filter(mailbox=mailbox, stable_identity=stable).first()
            if existing:
                ImportSource.objects.create(
                    mailbox=mailbox,
                    identity=identity,
                    stable_identity=stable,
                    document=existing.document,
                    provenance=provenance,
                    error=existing.error,
                )
                continue
            try:
                if count > 50:
                    raise DomainError("Mehr als 50 Anhänge in einer Nachricht.")
                result = ingest(actor, filename or "anhang", data, company_id=company_id)
                ImportSource.objects.create(
                    mailbox=mailbox,
                    identity=identity,
                    stable_identity=stable,
                    document_id=result["document"]["id"],
                    provenance=provenance,
                )
            except DomainError as e:
                # Unsupported attachments are not silently discarded. Preserve bounded original bytes.
                relative = f"_rejected/{mailbox.id}/{identity}.bin"
                storage.atomic_write(relative, data)
                provenance.update(
                    {"preserved_path": relative, "sha256": storage.checksum(data), "bytes": len(data)}
                )
                ImportSource.objects.create(
                    mailbox=mailbox,
                    identity=identity,
                    stable_identity=stable,
                    provenance=provenance,
                    error=str(e),
                )
    return count


def scan_mailbox(job, connector=None):
    mailbox = Mailbox.objects.get(company_id=job.company_id)
    if not mailbox.imap_host or not mailbox.import_since:
        raise DomainError("IMAP-Host und Importbeginn fehlen.")
    actor = Actor(job.actor_id)
    actor.require(mailbox.company_id, "process")
    factory = connector or (imaplib.IMAP4_SSL if mailbox.imap_tls else imaplib.IMAP4)
    options = {"timeout": 20}
    if mailbox.imap_tls:
        # imaplib's default stdlib context does not verify certificates. Never
        # send credentials over "TLS" without validating the server identity.
        options["ssl_context"] = ssl.create_default_context()
    client = factory(mailbox.imap_host, mailbox.imap_port, **options)
    processed = attachments = 0
    started = time.monotonic()
    try:
        client.login(mailbox.imap_user, decrypt(mailbox.imap_password))
        status, _ = client.select(mailbox.imap_folder, readonly=True)
        if status != "OK":
            raise DomainError("IMAP-Ordner konnte nicht geöffnet werden.")
        _, validity_data = client.response("UIDVALIDITY")
        validity = validity_data[0].decode() if validity_data and validity_data[0] else ""
        if not validity:
            raise DomainError("IMAP liefert keine UIDVALIDITY; sicherer Import nicht möglich.")
        with transaction.atomic():
            mailbox = Mailbox.objects.select_for_update().get(id=mailbox.id)
            if mailbox.uidvalidity != validity:
                mailbox.uidvalidity, mailbox.last_uid = validity, 0
                mailbox.save(update_fields=["uidvalidity", "last_uid"])
        months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        since = f"{mailbox.import_since.day:02d}-{months[mailbox.import_since.month - 1]}-{mailbox.import_since.year:04d}"
        status, found = client.uid("search", None, "SINCE", since, "UID", f"{mailbox.last_uid + 1}:*")
        if status != "OK":
            raise DomainError("IMAP-Suche fehlgeschlagen.")
        uids = sorted(int(x) for x in (found[0] or b"").split() if int(x) > mailbox.last_uid)
        for uid in uids[:20]:
            if time.monotonic() - started > 180:
                break
            Job.objects.filter(id=job.id).update(heartbeat=timezone.now())
            status, size_data = client.uid("fetch", str(uid), "(RFC822.SIZE)")
            import re

            sizes = re.findall(
                rb"RFC822.SIZE\s+(\d+)", b" ".join(x for x in size_data if isinstance(x, bytes))
            )
            if status != "OK" or not sizes:
                raise DomainError("IMAP-Größenabfrage fehlgeschlagen.")
            if int(sizes[0]) > settings.MAX_MAIL_BYTES:
                identity = source_key(mailbox.id, validity, str(uid), "oversize")
                ImportSource.objects.get_or_create(
                    identity=identity,
                    defaults={
                        "mailbox": mailbox,
                        "stable_identity": identity,
                        "provenance": {"uid": str(uid), "uidvalidity": validity, "bytes": int(sizes[0])},
                        "error": "Nachricht überschreitet das Abruflimit; verbleibt unverändert im Postfach.",
                    },
                )
            else:
                status, fetched = client.uid("fetch", str(uid), "(BODY.PEEK[])")
                raw = next((x[1] for x in fetched if isinstance(x, tuple)), None)
                if status != "OK" or raw is None:
                    raise DomainError("IMAP-Nachricht konnte nicht gelesen werden.")
                attachments += import_message(actor, mailbox, validity, uid, raw)
            # Only after every attachment/provenance/error record is committed.
            with transaction.atomic():
                current = Mailbox.objects.select_for_update().get(id=mailbox.id)
                if current.uidvalidity != validity:
                    raise DomainError(
                        "UIDVALIDITY hat sich während des Abrufs geändert; Originale erhalten, erneut abrufen."
                    )
                current.last_uid = max(current.last_uid, uid)
                current.save(update_fields=["last_uid"])
                mailbox.last_uid = current.last_uid
            processed += 1
        mailbox.last_scan_at = timezone.now()
        mailbox.save(update_fields=["last_scan_at"])
        return {
            "messages": processed,
            "attachments": attachments,
            "remaining": max(0, len(uids) - processed),
            "last_uid": mailbox.last_uid,
            "uidvalidity": validity,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def dispatch_data(d):
    return {
        "id": str(d.id),
        "package_id": str(d.package_id),
        "recipients": d.recipients,
        "status": d.status,
        "resend_of": str(d.resend_of_id) if d.resend_of_id else None,
        "parts": [{k: v for k, v in p.items() if k != "path"} for p in d.parts],
        "attempts": list(
            d.attempts.values("id", "part", "message_id", "status", "detail", "started_at", "finished_at")
        ),
        "created_at": d.created_at.isoformat(),
    }


def queue_dispatch(actor, package_id, idempotency_key, resend_of=None):
    package = get_package(actor, package_id, "send")
    if not idempotency_key or len(idempotency_key) > 120:
        raise DomainError("Idempotenzschlüssel erforderlich.")
    with transaction.atomic():
        package = type(package).objects.select_for_update().get(id=package.id)
        previous = Dispatch.objects.filter(package=package, idempotency_key=idempotency_key).first()
        if previous:
            if str(previous.resend_of_id or "") != str(resend_of or ""):
                raise DomainError("Idempotenzschlüssel wurde anders verwendet.", 409)
            return dispatch_data(previous)
        existing = Dispatch.objects.filter(package=package).order_by("-created_at").first()
        if existing and not resend_of:
            raise DomainError(
                "Für dieses Paket existiert bereits ein Versandauftrag. Erneut senden muss ausdrücklich auf diesen verweisen.",
                409,
            )
        if resend_of and (not existing or str(existing.id) != str(resend_of)):
            raise DomainError("Erneuter Versand muss auf den letzten Auftrag dieses Pakets verweisen.")
        if existing and existing.status in {"queued", "sending"}:
            raise DomainError("Vorheriger Versand läuft noch.", 409)
        snapshot = package.snapshot
        if not snapshot["recipients"]:
            raise DomainError(
                "Paket hat keine Empfänger; Einstellungen korrigieren und neue Paketversion erzeugen."
            )
        if (snapshot["excluded"] or snapshot["unassigned_inbox"]) and not snapshot["allow_open_issues"]:
            raise DomainError("Paket enthält offene Punkte. Versandregel erlaubt dies nicht.")
        mailbox = Mailbox.objects.filter(company=package.company).first()
        if not mailbox or not mailbox.smtp_host or not mailbox.sender:
            raise DomainError("SMTP-Host und Absender fehlen.")
        d = Dispatch.objects.create(
            package=package,
            actor_id=actor.user_id,
            idempotency_key=idempotency_key,
            recipients=snapshot["recipients"],
            resend_of_id=resend_of,
        )
        prepare_dispatch(d, mailbox)
        from .jobs import enqueue_job

        enqueue_job(
            actor, package.company_id, "dispatch", "dispatch:" + str(d.id), {"dispatch_id": str(d.id)}
        )
    return dispatch_data(d)


def make_message(dispatch, mailbox, part, manifest, message_id):
    package = dispatch.package
    snapshot = package.snapshot
    substitutions = {
        "company": snapshot["company"]["name"],
        "period": ", ".join(package.periods),
        "version": package.version,
        "notes": "Offene Punkte siehe Begleitschreiben und Inhaltsliste.",
    }
    subject = mailbox.subject_template.format(**substitutions) + f" [{part['number']}/{part['total']}]"
    body = mailbox.body_template.format(**substitutions)
    if part["total"] > 1:
        body += (
            "\nMehrteilige ZIP-Datei: Alle Teile in dasselbe Verzeichnis laden und in aufsteigender Reihenfolge binär zusammenfügen.\n"
            "Linux/macOS: cat paket.zip.part* > paket.zip\nPowerShell: siehe README der Anwendung.\n"
            f"Prüfsumme ZIP (SHA256): {package.sha256}\n"
        )
    msg = EmailMessage(
        subject,
        body,
        mailbox.sender,
        dispatch.recipients,
        reply_to=[mailbox.reply_to] if mailbox.reply_to else None,
        headers={"Message-ID": message_id},
    )
    part_bytes = storage.path(part["path"]).read_bytes()
    if storage.checksum(part_bytes) != part["sha256"] or len(part_bytes) != part["bytes"]:
        raise DomainError("Vorbereiteter Mailteil hat eine abweichende Prüfsumme.", 409)
    msg.attach(
        part["filename"], part_bytes, "application/zip" if part["total"] == 1 else "application/octet-stream"
    )
    msg.attach(
        "Gesamtinhaltsliste.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode(),
        "application/json",
    )
    return msg


def prepare_dispatch(dispatch, mailbox):
    data = package_bytes(dispatch.package)
    # Leave room for MIME encoding, headers and the complete multipart manifest.
    chunk_size = (
        len(data)
        if len(data) < mailbox.max_message_bytes * 3 // 4
        else max(256, int(mailbox.max_message_bytes * 0.55) - 2048)
    )
    while True:
        total = math.ceil(len(data) / chunk_size) or 1
        if total > 1000:
            raise DomainError("Paket benötigt zu viele Mailteile. Größenlimit erhöhen.")
        parts = []
        for n in range(total):
            chunk = data[n * chunk_size : (n + 1) * chunk_size]
            filename = "paket.zip" if total == 1 else f"paket.zip.part{n + 1:04d}"
            relative = f"_dispatches/{dispatch.id}/{chunk_size}-{filename}"
            storage.atomic_write(relative, chunk)
            parts.append(
                {
                    "number": n + 1,
                    "total": total,
                    "filename": filename,
                    "path": relative,
                    "sha256": storage.checksum(chunk),
                    "bytes": len(chunk),
                }
            )
        manifest = {
            "package_id": str(dispatch.package_id),
            "package_sha256": dispatch.package.sha256,
            "parts": [{k: v for k, v in p.items() if k != "path"} for p in parts],
            "documents": [
                {"id": d["id"], "file": d["archive_path"], "sha256": d["sha256"]}
                for d in dispatch.package.snapshot["documents"]
            ],
        }
        messages = [make_message(dispatch, mailbox, p, manifest, make_msgid()) for p in parts]
        if all(len(m.message(policy=policy.SMTP).as_bytes()) <= mailbox.max_message_bytes for m in messages):
            break
        chunk_size = int(chunk_size * 0.75)
        if chunk_size < 128:
            raise DomainError("Mailgrößenlimit zu klein für Inhaltsliste und Kopfzeilen.")
    dispatch.parts = parts
    dispatch.save(update_fields=["parts"])
    for part in parts:
        SendAttempt.objects.create(
            dispatch=dispatch, part=part["number"], message_id=make_msgid(domain="lazy-accountant.local")
        )


def send_dispatch(job):
    dispatch = Dispatch.objects.select_related("package", "package__company").get(
        id=job.payload["dispatch_id"]
    )
    Actor(job.actor_id).require(dispatch.package.company_id, "send")
    mailbox = Mailbox.objects.get(company_id=dispatch.package.company_id)
    manifest = {
        "package_id": str(dispatch.package_id),
        "package_sha256": dispatch.package.sha256,
        "parts": [{k: v for k, v in p.items() if k != "path"} for p in dispatch.parts],
        "documents": [
            {"id": d["id"], "file": d["archive_path"], "sha256": d["sha256"]}
            for d in dispatch.package.snapshot["documents"]
        ],
    }
    for part in dispatch.parts:
        with transaction.atomic():
            attempt = SendAttempt.objects.select_for_update().get(dispatch=dispatch, part=part["number"])
            if attempt.status == "accepted":
                continue
            if attempt.status in {"sending", "unknown", "failed", "partial"}:
                # No implicit side-effect retry, not even after a worker crash.
                break
            attempt.status, attempt.started_at = "sending", timezone.now()
            attempt.save(update_fields=["status", "started_at"])
            dispatch.status = "sending"
            dispatch.save(update_fields=["status", "updated_at"])
        connection = None
        try:
            msg = make_message(dispatch, mailbox, part, manifest, attempt.message_id)
            if len(msg.message(policy=policy.SMTP).as_bytes()) > mailbox.max_message_bytes:
                raise DomainError(
                    "Aktuelles Mailgrößenlimit unterschritten: neuer Versandauftrag erforderlich."
                )
            backend = import_string(settings.MAILERS["default"]["BACKEND"])
            options = (
                {
                    "host": mailbox.smtp_host,
                    "port": mailbox.smtp_port,
                    "username": mailbox.smtp_user,
                    "password": decrypt(mailbox.smtp_password),
                    "use_tls": mailbox.smtp_security == "starttls",
                    "use_ssl": mailbox.smtp_security == "ssl",
                    "timeout": 30,
                }
                if issubclass(backend, DjangoSMTPBackend)
                else {}
            )
            connection = backend(alias=f"company-{mailbox.company_id}", **options)
            # A failure opening the connection is known not to have sent DATA.
            connection.open()
        except Exception as e:
            attempt.status, attempt.detail = (
                "failed",
                "Verbindungsaufbau/Vorbereitung fehlgeschlagen: " + type(e).__name__,
            )
        else:
            try:
                accepted = connection.send_messages([msg])
                refused = getattr(connection, "refused_recipients", None)
                attempt.status = "partial" if refused else "accepted" if accepted == 1 else "failed"
                attempt.detail = (
                    ("Einzelne Empfänger abgelehnt: " + ", ".join(refused))
                    if refused
                    else "Vom SMTP-Server angenommen; Zustellung nicht bestätigt."
                    if accepted == 1
                    else "SMTP nahm keine Nachricht an."
                )
            except (
                smtplib.SMTPRecipientsRefused,
                smtplib.SMTPSenderRefused,
                smtplib.SMTPDataError,
                smtplib.SMTPAuthenticationError,
            ) as e:
                attempt.status, attempt.detail = "failed", "SMTP-Ablehnung: " + type(e).__name__
            except OSError, smtplib.SMTPException, socket.timeout:
                attempt.status, attempt.detail = (
                    "unknown",
                    "Verbindung unterbrochen; Annahme unbekannt. Kein automatischer Neuversand.",
                )
            except Exception:
                attempt.status, attempt.detail = (
                    "unknown",
                    "Unbekannter Ausgang nach Versandbeginn. Kein automatischer Neuversand.",
                )
        finally:
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=["status", "detail", "finished_at"])
        if attempt.status != "accepted":
            break
    statuses = list(dispatch.attempts.values_list("status", flat=True))
    dispatch.status = (
        "accepted"
        if all(s == "accepted" for s in statuses)
        else "unknown"
        if any(s in {"unknown", "sending"} for s in statuses)
        else "partial"
        if "accepted" in statuses or "partial" in statuses
        else "failed"
    )
    dispatch.save(update_fields=["status", "updated_at"])
    return dispatch_data(dispatch)
