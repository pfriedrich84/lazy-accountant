"""Durable quarantine state machine shared by every import and access path."""

import json
import logging
import os
import subprocess
import sys
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_q.tasks import async_task

from . import scanner, storage
from .auth import DomainError
from .models import Document, Package, ScanAttempt

logger = logging.getLogger(__name__)


def require_clean(doc):
    # Reload: a previously fetched object must not bypass a subsequent rescan.
    current = Document.objects.get(id=doc.id)
    if current.security_status != "clean" or current.scanned_sha256 != current.sha256:
        raise DomainError(
            "Datei sicherheitsgesperrt: " + current.security_status + ". " + current.security_error, 423
        )
    return current


def affected(doc):
    packages = Package.objects.filter(items__document=doc).distinct()
    return {
        "package_ids": [str(p) for p in packages.values_list("id", flat=True)],
        "dispatch_ids": [str(p) for p in packages.values_list("dispatches__id", flat=True) if p],
    }


def publish(document_id):
    try:
        async_task("accounting.security.run_scan", str(document_id))
    except Exception:
        logger.error("Scan publication failed for document %s; maintenance will recover", document_id)


def invalidate(doc, reason):
    """Called on integrity failures; no stale clean result can authorize access."""
    Document.objects.filter(id=doc.id).update(
        security_status="error",
        security_error=reason,
        scanned_sha256="",
        scan_due_at=None,
    )


def inspect_bytes(data, media, page=None, image=False):
    # Parsers do not inherit mail, database or Django secrets.
    env = {"PYTHONPATH": str(settings.BASE_DIR), "PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}
    arguments = [sys.executable, "-m", "accounting.inspect_document", media]
    if page is not None:
        arguments += ["image" if image else "text", str(page)]
    try:
        result = subprocess.run(
            arguments,
            input=data,
            capture_output=True,
            timeout=30,
            env=env,
            check=True,
        )
        return result.stdout if image else json.loads(result.stdout)
    except subprocess.SubprocessError, ValueError:
        raise DomainError("Dokumentparser abgebrochen oder Inhalt nicht vollständig prüfbar.") from None


def run_scan(document_id):
    with transaction.atomic():
        doc = Document.objects.select_for_update().get(id=document_id)
        if doc.security_status != "pending":
            return
        doc.security_status = "scanning"
        doc.scan_attempts += 1
        doc.scan_due_at = timezone.now() + timedelta(seconds=settings.CLAMAV_LEASE_SECONDS)
        doc.save(update_fields=["security_status", "scan_attempts", "scan_due_at"])
        attempt = ScanAttempt.objects.create(document=doc, sha256=doc.sha256)
    verdict = scanner.Verdict("error", "", reason="Quarantäne-/Integritätsprüfung fehlgeschlagen.")
    data = None
    media, ext, parsed = "application/octet-stream", ".bin", {}
    try:
        data = storage.path(doc.quarantine_path or doc.original_path).read_bytes()
        if len(data) != doc.size or storage.checksum(data) != doc.sha256:
            raise DomainError("Quarantäne-Prüfsumme stimmt nicht.")
        verdict = scanner.scan(data)
        if verdict.result == "clean":
            from .services import detect_media

            try:
                media, ext = detect_media(data, doc.original_name)
                parsed = inspect_bytes(data, media)
            except DomainError as exc:
                verdict.result, verdict.reason = "error", str(exc)[:500]
    except OSError, DomainError:
        verdict = scanner.Verdict(
            "error", verdict.engine, reason="Quarantäne-/Integritätsprüfung fehlgeschlagen."
        )
    except Exception:
        verdict = scanner.Verdict("error", verdict.engine, reason="Scanner-Verarbeitung fehlgeschlagen.")
    with transaction.atomic():
        current = Document.objects.select_for_update().get(id=document_id)
        attempt.refresh_from_db()
        if current.security_status != "scanning" or attempt.result != "scanning":
            return  # Lease recovered; a stale worker can never release bytes.
        if verdict.result == "clean" and (current.sha256 != attempt.sha256 or current.size != doc.size):
            verdict.result, verdict.reason = "error", "Importidentität während des Scans verändert."
        if verdict.result == "clean":
            try:
                # Scan the in-memory snapshot, publish that same snapshot, and
                # recheck durable quarantine before committing. Never move a
                # path which could have been swapped while clamd was scanning.
                if (
                    storage.checksum(storage.path(doc.quarantine_path or doc.original_path).read_bytes())
                    != doc.sha256
                ):
                    raise DomainError("Quarantäne während der Prüfung verändert.")
                relative = f"_originals/{doc.id}{ext}"
                storage.atomic_write(relative, data, doc.sha256)
                os.chmod(storage.path(relative), 0o400)
                current.original_path = relative
                current.media_type = media
                if current.name_source == "fallback" or not current.handover_name:
                    from . import naming

                    current.handover_name = naming.fallback(current)
                    current.name_source = "fallback"
                current.parser_result = parsed
                current.parser_error = ""
                if media == "application/xml":
                    current.kind = "bank_camt"
                current.scanned_sha256 = doc.sha256
            except OSError, DomainError:
                verdict.result, verdict.reason = (
                    "error",
                    "Atomare Freigabe/Integritätsprüfung fehlgeschlagen.",
                )
        current.security_status = verdict.result
        current.security_error = verdict.reason
        current.scanned_at = timezone.now()
        current.scan_due_at = (
            timezone.now() + timedelta(seconds=settings.CLAMAV_RETRY_SECONDS)
            if verdict.result == "error" and current.scan_attempts < settings.CLAMAV_MAX_ATTEMPTS
            else None
        )
        current.save()
        attempt.engine, attempt.signature = verdict.engine, verdict.signature
        attempt.result, attempt.reason = verdict.result, verdict.reason
        attempt.finished_at = current.scanned_at
        attempt.save()
        if verdict.result == "clean":
            storage.journal(current)
            transaction.on_commit(lambda: storage.reconcile(current.id))
        logger.info(
            "Scan document=%s sha256=%s attempt=%s result=%s engine=%s signature=%s",
            doc.id,
            doc.sha256,
            attempt.id,
            verdict.result,
            verdict.engine,
            verdict.signature,
        )


def request_scan(actor, document_id):
    from .services import document_data, get_document

    with transaction.atomic():
        doc = get_document(actor, document_id, "process", lock=True)
        if doc.security_status in {"pending", "scanning"}:
            return document_data(doc)
        if doc.filed_path:
            storage.path(doc.filed_path).unlink(missing_ok=True)
            doc.filed_path = ""
        # Return known-identical copies to physical quarantine as well. Never
        # discard the only intact copy, or silently overwrite a tampered one.
        if doc.original_path.startswith("_originals/") and doc.quarantine_path:
            try:
                original = storage.path(doc.original_path).read_bytes()
                quarantined = storage.path(doc.quarantine_path).read_bytes()
                if storage.checksum(original) == storage.checksum(quarantined) == doc.sha256:
                    storage.path(doc.original_path).unlink()
                    doc.original_path = doc.quarantine_path
            except OSError:
                pass  # The actual scan records the durable integrity error.
        doc.security_status, doc.security_error = "pending", ""
        doc.scanned_sha256, doc.scan_attempts, doc.scan_due_at = "", 0, timezone.now()
        doc.save(
            update_fields=[
                "filed_path",
                "original_path",
                "security_status",
                "security_error",
                "scanned_sha256",
                "scan_attempts",
                "scan_due_at",
            ]
        )
        transaction.on_commit(lambda: publish(doc.id))
    doc.refresh_from_db()
    return document_data(doc)


def maintenance():
    now = timezone.now()
    for doc_id in Document.objects.filter(security_status="scanning", scan_due_at__lt=now).values_list(
        "id", flat=True
    ):
        with transaction.atomic():
            doc = Document.objects.select_for_update().get(id=doc_id)
            if doc.security_status != "scanning" or doc.scan_due_at >= now:
                continue
            ScanAttempt.objects.filter(document=doc, result="scanning").update(
                result="error",
                reason="Worker unterbrochen / Scan-Lease abgelaufen.",
                finished_at=now,
            )
            doc.security_status, doc.security_error = (
                "error",
                "Scan unterbrochen; erneute Prüfung erforderlich.",
            )
            doc.scan_due_at = now if doc.scan_attempts < settings.CLAMAV_MAX_ATTEMPTS else None
            doc.save(update_fields=["security_status", "security_error", "scan_due_at"])
    Document.objects.filter(security_status="error", scan_due_at__lte=now).update(security_status="pending")
    for doc_id in Document.objects.filter(security_status="pending").values_list("id", flat=True):
        publish(doc_id)
