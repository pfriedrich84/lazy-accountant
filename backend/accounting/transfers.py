import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import services, storage
from .auth import DomainError
from .models import ProcessingClaim, UploadTicket


def prepare_upload(actor, filename, size, sha256, company_id=None):
    filename = services.validate_original_filename(filename)
    if company_id:
        actor.require(company_id, "process")
    else:
        actor.require_inbox(actor.user_id, "process")
    if not 0 < size <= settings.MAX_FILE_BYTES or not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise DomainError("Ungültige Dateigröße oder SHA256.")
    ticket = UploadTicket.objects.create(
        actor_id=actor.user_id,
        company_id=company_id,
        filename=filename,
        expected_size=size,
        expected_sha256=sha256,
    )
    return {
        "upload_id": str(ticket.id),
        "url": f"/api/uploads/{ticket.id}/",
        "method": "PUT",
        "content_type": "application/octet-stream",
        "authentication": "Authorization: Bearer <token>",
        "max_bytes": settings.MAX_FILE_BYTES,
    }


def get_ticket(actor, upload_id, lock=False):
    qs = UploadTicket.objects.select_for_update() if lock else UploadTicket.objects
    ticket = qs.filter(id=upload_id, actor_id=actor.user_id).first()
    if not ticket:
        raise DomainError("Upload nicht gefunden.", 404)
    if ticket.company_id:
        actor.require(ticket.company_id, "process")
    else:
        actor.require_inbox(actor.user_id, "process")
    return ticket


def put_upload(actor, upload_id, data):
    with transaction.atomic():
        t = get_ticket(actor, upload_id, lock=True)
        if len(data) != t.expected_size or storage.checksum(data) != t.expected_sha256:
            raise DomainError("Upload stimmt nicht mit angekündigter Größe/Prüfsumme überein.", 409)
        if t.document_id:
            return {"upload_id": str(t.id), "document_id": str(t.document_id)}
        storage.atomic_write(f"_quarantine/transfers/{t.id}.bin", data, t.expected_sha256)
        t.uploaded = True
        t.save(update_fields=["uploaded"])
    return {"upload_id": str(t.id), "uploaded": True}


def complete_upload(actor, upload_id):
    with transaction.atomic():
        t = get_ticket(actor, upload_id, lock=True)
        if t.document_id:
            return services.document_data(services.get_document(actor, t.document_id))
        if not t.uploaded:
            raise DomainError("Dateitransfer noch nicht abgeschlossen.", 409)
        data = storage.path(f"_quarantine/transfers/{t.id}.bin").read_bytes()
        if storage.checksum(data) != t.expected_sha256:
            raise DomainError("Upload-Prüfsumme stimmt nicht.", 409)
        result = services.ingest(actor, t.filename, data, t.company_id, "ticket:" + str(t.id))
        t.document_id = result["document"]["id"]
        t.save(update_fields=["document"])
    storage.path(f"_quarantine/transfers/{t.id}.bin").unlink(missing_ok=True)
    return result["document"]


def claim_document(actor, document_id, run_id, base_version):
    with transaction.atomic():
        d = services.get_document(actor, document_id, "process", lock=True)
        from .security import require_clean

        require_clean(d)
        if d.version != base_version:
            raise DomainError("Ausgangsversion ist nicht mehr aktuell.", 409)
        prior = ProcessingClaim.objects.filter(document=d).first()
        if (
            prior
            and prior.expires_at > timezone.now()
            and (prior.actor_id != actor.user_id or prior.run_id != run_id)
        ):
            raise DomainError("Dokument ist bereits für einen anderen Lauf reserviert.", 409)
        claim, _ = ProcessingClaim.objects.update_or_create(
            document=d,
            defaults={
                "actor_id": actor.user_id,
                "run_id": run_id[:120],
                "base_version": d.version,
                "expires_at": timezone.now() + timedelta(minutes=20),
            },
        )
    return {
        "document_id": str(d.id),
        "base_version": d.version,
        "run_id": claim.run_id,
        "expires_at": claim.expires_at.isoformat(),
        "note": "Manuelle Korrekturen bleiben erlaubt; Ergebnisübernahme prüft die Ausgangsversion erneut.",
    }
