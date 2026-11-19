import json
import re
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from pydantic import ValidationError

from . import storage
from .auth import DomainError
from .models import (
    Account,
    Category,
    Company,
    Document,
    FileOperation,
    IdempotencyRecord,
    Membership,
    Revision,
)
from .schemas import DocumentResult, validation_issues


def validate_original_filename(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 255 or "\x00" in name:
        raise DomainError("Originaldateiname muss 1 bis 255 Zeichen ohne Nullbyte enthalten.")
    try:
        name.encode("utf-8")
    except UnicodeEncodeError as e:
        raise DomainError("Originaldateiname enthält ungültiges Unicode.") from e
    return name


def valid_period(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value)
        or int(value[:4]) < 1900
    ):
        raise DomainError("Übergabemonat muss YYYY-MM sein (ab 1900).")
    return value


def create_company(actor, payload):
    if actor.token_id:
        raise DomainError("Firmenanlage nur über eine Benutzersitzung.", 403)
    allowed = {
        k: v
        for k, v in payload.items()
        if k in {"name", "folder", "legal_name", "tax_id", "address", "recipients", "allow_open_issues"}
    }
    with transaction.atomic():
        company = Company(**allowed)
        try:
            company.full_clean()
        except DjangoValidationError as e:
            raise DomainError("Firmendaten ungültig.", details=e.message_dict) from e
        validate_recipients(company.recipients)
        company.save()
        Membership.objects.create(
            user_id=actor.user_id,
            company=company,
            can_read=True,
            can_process=True,
            can_send=True,
            can_admin=True,
        )
        return company_data(company)


def validate_recipients(values):
    from django.core.validators import validate_email

    if not isinstance(values, list) or len(values) > 30:
        raise DomainError("Empfänger müssen eine Liste mit höchstens 30 Adressen sein.")
    try:
        for value in values:
            validate_email(value)
    except DjangoValidationError, TypeError:
        raise DomainError("Ungültige Empfängeradresse.") from None


def company_data(c):
    return {
        "id": c.id,
        "name": c.name,
        "folder": c.folder,
        "legal_name": c.legal_name,
        "tax_id": c.tax_id,
        "address": c.address,
        "recipients": c.recipients,
        "allow_open_issues": c.allow_open_issues,
    }


def update_company(actor, company_id, payload):
    c = actor.require(company_id, "admin")
    if "folder" in payload and payload["folder"] != c.folder:
        raise DomainError("Der Ablageordner ist nach der Anlage unveränderlich.")
    for key in ("name", "legal_name", "tax_id", "address", "recipients", "allow_open_issues"):
        if key in payload:
            setattr(c, key, payload[key])
    validate_recipients(c.recipients)
    try:
        c.full_clean()
    except DjangoValidationError as e:
        raise DomainError("Firmendaten ungültig.", details=e.message_dict) from e
    c.save()
    return company_data(c)


def known_assignments(actor, company_id):
    c = actor.require(company_id)
    membership = Membership.objects.get(user_id=actor.user_id, company=c)
    return {
        "company": company_data(c),
        "accounts": list(Account.objects.filter(company=c).values("id", "name", "kind", "identifier")),
        "categories": list(Category.objects.filter(company=c).values("id", "name")),
        "permissions": {
            p: getattr(membership, "can_" + p) and actor.companies(p).filter(id=c.id).exists()
            for p in ("read", "process", "send", "admin")
        },
    }


def get_document(actor, document_id, permission="read", lock=False):
    try:
        qs = Document.objects.select_related("company", "account", "category")
        if lock:
            # Don't lock nullable outer-join rows on PostgreSQL.
            qs = qs.select_for_update(of=("self",))
        d = qs.get(id=document_id)
    except Document.DoesNotExist, ValueError, DjangoValidationError:
        raise DomainError("Dokument nicht gefunden.", 404) from None
    if d.company_id:
        actor.require(d.company_id, permission)
    else:
        actor.require_inbox(d.inbox_owner_id, permission)
    return d


def document_data(d, detailed=False):
    desired = storage.desired_path(d)
    pending = d.filed_path != desired
    filing_error = ""
    if pending:
        filing_error = (
            FileOperation.objects.filter(document=d, status="pending")
            .order_by("-id")
            .values_list("error", flat=True)
            .first()
            or ""
        )
    result = {
        "id": str(d.id),
        "company_id": d.company_id,
        "original_name": d.original_name,
        "sha256": d.sha256,
        "size": d.size,
        "media_type": d.media_type,
        "kind": d.kind,
        "period": d.period,
        "account_id": d.account_id,
        "category_id": d.category_id,
        "metadata": d.metadata,
        "issues": d.issues,
        "status": d.status,
        "security_status": d.security_status,
        "security_error": d.security_error,
        "scanned_sha256": d.scanned_sha256,
        "scanned_at": d.scanned_at.isoformat() if d.scanned_at else None,
        "version": d.version,
        "filed_path": d.filed_path,
        "duplicate_of": str(d.duplicate_of_id) if d.duplicate_of_id else None,
        "related_ids": [str(x.id) for x in d.related.all()],
        "filing_status": "pending" if pending else "done",
        "filing_error": filing_error,
        "desired_path": desired,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }
    if detailed:
        result.update(
            {
                "parser_result": d.parser_result,
                "parser_error": d.parser_error,
                "referenced_by_ids": [
                    str(x)
                    for x in d.referenced_by.filter(company_id=d.company_id).values_list("id", flat=True)
                ],
                "sources": list(d.sources.values("id", "provenance", "error", "created_at")),
                "revisions": list(
                    d.revisions.order_by("-version").values(
                        "version", "base_version", "actor_id", "source", "snapshot", "created_at"
                    )
                ),
            }
        )
    if d.security_status != "clean":
        # Historical extraction/revisions must not leak after a later finding.
        result.update(metadata={}, issues=[], parser_result={}, parser_error="", revisions=[], filed_path="")
    if detailed:
        from .security import affected

        result["security_impact"] = affected(d)
        result["scans"] = list(
            d.scans.order_by("-started_at").values(
                "id", "sha256", "engine", "result", "signature", "reason", "started_at", "finished_at"
            )
        )
    return result


def list_documents(
    actor,
    company_id=None,
    period=None,
    status=None,
    kind=None,
    search=None,
    category_id=None,
    cursor=None,
    limit=50,
):
    qs = Document.objects.filter(company__in=actor.companies())
    try:
        actor.require_inbox(actor.user_id)
        qs = Document.objects.filter(
            Q(company__in=actor.companies()) | Q(company__isnull=True, inbox_owner_id=actor.user_id)
        )
    except DomainError:
        pass
    if company_id == "inbox":
        qs = qs.filter(company__isnull=True)
    elif company_id:
        actor.require(company_id)
        qs = qs.filter(company_id=company_id)
    if period:
        qs = qs.filter(period=valid_period(period))
    if status:
        qs = qs.filter(status__in=["new", "review"] if status == "open" else [status])
    if kind:
        qs = qs.filter(kind=kind)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if search:
        qs = qs.filter(
            Q(original_name__icontains=search) | Q(security_status="clean", metadata__icontains=search)
        )
    # UUID cursor is stable while status changes during processing; never use offsets for a mutable open list.
    qs = qs.order_by("id")
    total = qs.count()
    if cursor:
        try:
            qs = qs.filter(id__gt=uuid.UUID(cursor))
        except ValueError:
            raise DomainError("Ungültiger Cursor.") from None
    limit = max(1, min(int(limit), 100))
    rows = list(qs.select_related("company", "account", "category").prefetch_related("related")[: limit + 1])
    return {
        "results": [document_data(d) for d in rows[:limit]],
        "total": total,
        "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None,
    }


def detect_media(data, name):
    suffix = name.lower().rsplit(".", 1)[-1]
    if data.startswith(
        (b"PK\x03\x04", b"PK\x05\x06", b"Rar!", b"7z\xbc\xaf\x27\x1c", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")
    ):
        raise DomainError("Archive sind kein erlaubtes Uploadformat.")
    # Bank exports may prepend printer/control records before the PDF header.
    # Search only the first 1024 bytes, not arbitrary embedded PDF content.
    # Keep the original bytes intact (including the prefix) for parsing/storage.
    if b"%PDF-" in data[:1024]:
        return "application/pdf", ".pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if suffix == "xml" or data.lstrip().startswith(b"<?xml") or data.lstrip().startswith(b"<Document"):
        return "application/xml", ".xml"
    raise DomainError("Unterstützt sind PDF, JPG, PNG und CAMT-XML.")


def ingest(actor, name, data, company_id=None, idempotency_key=None, provenance=None):
    name = validate_original_filename(name)
    if not data or len(data) > settings.MAX_FILE_BYTES:
        raise DomainError("Datei leer oder Größenlimit überschritten.", 413)
    if company_id:
        actor.require(company_id, "process")
    else:
        actor.require_inbox(actor.user_id, "process")
    # Type detection and all document parsing happen only after the malware scan.
    # Unsupported bytes are retained as a blocked import, never an allowed format.
    digest = storage.checksum(data)
    request_hash = storage.checksum(json.dumps([name, digest, company_id]).encode())
    if idempotency_key and len(idempotency_key) > 120:
        raise DomainError("Idempotenzschlüssel zu lang.")
    with transaction.atomic():
        # Serialize this user's uploads, including no-company inbox deduplication.
        get_user_model().objects.select_for_update().get(id=actor.user_id)
        if company_id:
            Company.objects.select_for_update().get(id=company_id)
        if idempotency_key:
            prior = IdempotencyRecord.objects.filter(
                actor_id=actor.user_id, operation="upload", key=idempotency_key
            ).first()
            if prior:
                if prior.request_hash != request_hash:
                    raise DomainError("Idempotenzschlüssel gehört zu einer anderen Anfrage.", 409)
                doc = get_document(actor, prior.result["document_id"])
                return {"document": document_data(doc), "duplicate": True}
        duplicates = Document.objects.filter(company_id=company_id, sha256=digest)
        if not company_id:
            duplicates = duplicates.filter(inbox_owner_id=actor.user_id)
        doc = duplicates.first()
        duplicate = doc is not None
        if doc:
            get_document(actor, doc.id, "process")
        else:
            doc = Document(
                id=uuid.uuid4(),
                company_id=company_id,
                inbox_owner_id=actor.user_id,
                original_name=name,
                sha256=digest,
                size=len(data),
                media_type="application/octet-stream",
            )
            doc.quarantine_path = f"_quarantine/{doc.id}.bin"
            doc.original_path = doc.quarantine_path
            storage.atomic_write(doc.quarantine_path, data, digest)
            doc.issues = validation_issues(doc.kind, company_id, "", None, {}, doc.parser_error)
            doc.save()
            Revision.objects.create(
                document=doc,
                version=1,
                base_version=0,
                actor_id=actor.user_id,
                source="upload",
                snapshot=document_data(doc),
            )
            from .security import publish

            transaction.on_commit(lambda: publish(doc.id))
        if idempotency_key:
            IdempotencyRecord.objects.create(
                actor_id=actor.user_id,
                operation="upload",
                key=idempotency_key,
                request_hash=request_hash,
                result={"document_id": str(doc.id)},
            )
    storage.reconcile(doc.id)
    doc.refresh_from_db()
    return {"document": document_data(doc), "duplicate": duplicate}


def save_result(actor, payload, source="manual"):
    try:
        result = DocumentResult.model_validate(payload)
    except ValidationError as e:
        raise DomainError("Ergebnis entspricht nicht dem Schema.", details=json.loads(e.json())) from e
    if result.period:
        valid_period(result.period)
    initial = get_document(actor, result.document_id, "process")
    with transaction.atomic():
        # Same lock order as ingestion/package creation. Serialize reference and
        # company changes, including personal-inbox documents, before row writes.
        from django.contrib.auth import get_user_model

        get_user_model().objects.select_for_update().get(id=actor.user_id)
        company_ids = {c for c in [initial.company_id, result.company_id] if c}
        list(Company.objects.filter(id__in=company_ids).order_by("id").select_for_update())
        doc = get_document(actor, result.document_id, "process", lock=True)
        from .security import require_clean

        require_clean(doc)
        if doc.version != result.base_version:
            raise DomainError(
                "Dokument wurde inzwischen geändert. Neu laden und Änderungen vergleichen.",
                409,
                {"current_version": doc.version},
            )
        if result.company_id:
            actor.require(result.company_id, "process")
        else:
            actor.require_inbox(doc.inbox_owner_id, "process")
        if doc.company_id != result.company_id and (
            doc.referenced_by.exists() or Document.objects.filter(duplicate_of=doc).exists()
        ):
            raise DomainError(
                "Andere Dokumente verweisen auf dieses Original. Verweise/Dubletten in der bisherigen Firma vor dem Firmenwechsel ausdrücklich lösen.",
                409,
            )
        for model, identifier, label in [
            (Account, result.account_id, "Konto/Depot"),
            (Category, result.category_id, "Kategorie"),
        ]:
            if identifier and not model.objects.filter(id=identifier, company_id=result.company_id).exists():
                raise DomainError(f"{label} gehört nicht zur gewählten Firma.")
        if result.account_id:
            account = Account.objects.get(id=result.account_id)
            expected = "depot" if result.kind == "security_pdf" else "bank"
            if result.kind not in {"bank_camt", "bank_pdf", "security_pdf"} or account.kind != expected:
                raise DomainError("Konto-/Depotart passt nicht zum Dokument.")
        if (
            result.kind in {"outgoing_invoice", "outgoing_cancellation", "bank_pdf", "security_pdf"}
            and doc.media_type != "application/pdf"
        ):
            raise DomainError("Diese Dokumentart erfordert ein Original-PDF.")
        if result.kind == "bank_camt" and doc.media_type != "application/xml":
            raise DomainError("CAMT erfordert ein XML-Original.")
        related = []
        for identifier in result.related_ids:
            other = get_document(actor, identifier)
            if other.id == doc.id or other.company_id != result.company_id:
                raise DomainError("Verknüpfung muss auf ein anderes Dokument derselben Firma zeigen.")
            related.append(other)
        duplicate = None
        if result.duplicate_of:
            duplicate = get_document(actor, result.duplicate_of)
            if duplicate.id == doc.id or duplicate.company_id != result.company_id:
                raise DomainError("Ungültige Dublettenverknüpfung.")
        metadata = result.metadata.model_dump(mode="json")
        issues = validation_issues(
            result.kind, result.company_id, result.period, result.account_id, metadata, doc.parser_error
        )
        if result.approve and issues:
            raise DomainError("Dokument hat offene Prüfpunkte.", details=issues)
        doc.company_id = result.company_id
        doc.kind = result.kind or ""
        doc.period = result.period or ""
        doc.account_id = result.account_id
        doc.category_id = result.category_id
        doc.metadata = metadata
        doc.issues = issues
        doc.status = "ready" if result.approve else "review"
        doc.version += 1
        doc.duplicate_of = duplicate
        doc.save()
        doc.related.set(related)
        Revision.objects.create(
            document=doc,
            version=doc.version,
            base_version=result.base_version,
            actor_id=actor.user_id,
            source=source[:100],
            snapshot=document_data(doc),
        )
        storage.journal(doc)
    storage.reconcile(doc.id)
    doc.refresh_from_db()
    return document_data(doc, True)


def duplicate_hints(actor, document_id):
    doc = get_document(actor, document_id)
    if not doc.company_id:
        return []
    qs = Document.objects.filter(company_id=doc.company_id).exclude(id=doc.id)
    number = doc.metadata.get("number")
    hints = []
    for other in qs:
        if other.sha256 == doc.sha256 or (
            number
            and number == other.metadata.get("number")
            and doc.metadata.get("issuer") == other.metadata.get("issuer")
        ):
            hints.append(
                {
                    "document_id": str(other.id),
                    "reason": "Gleiche Originalbytes"
                    if other.sha256 == doc.sha256
                    else "Gleicher Aussteller und Belegnummer",
                    "status": other.status,
                }
            )
    return hints


def month_folders(actor, company_id, period, cursor=None):
    company = actor.require(company_id)
    valid_period(period)
    storage.ensure_month(company, period)
    docs = list_documents(actor, company_id=company_id, period=period, cursor=cursor, limit=100)
    year, month = period.split("-")
    return {
        "folders": [
            {
                "name": f,
                "path": f"{company.folder}/{year}/{month}/{f}/",
                "files": [d for d in docs["results"] if storage.KIND_FOLDER.get(d["kind"]) == f],
            }
            for f in storage.FOLDERS
        ],
        "total": docs["total"],
        "next_cursor": docs["next_cursor"],
    }


def readable_document(actor, document_id, page=1, image=False):
    doc = get_document(actor, document_id)
    data = storage.read_original(doc)
    if page < 1 or page > 500:
        raise DomainError("Ungültige Seitennummer.")
    from .security import inspect_bytes

    return inspect_bytes(data, doc.media_type, page=page, image=image)
