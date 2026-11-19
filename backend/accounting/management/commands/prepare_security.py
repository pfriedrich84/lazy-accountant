import os

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounting import storage
from accounting.models import Document, ImportSource, ScanAttempt, UploadTicket


class Command(BaseCommand):
    help = "Upgrade/Restore: Quarantänetrennung herstellen; fehlende vertrauenswürdige Scans sperren. Offline ausführen."

    def handle(self, *args, **options):
        for identifier in Document.objects.values_list("id", flat=True):
            with transaction.atomic():
                doc = Document.objects.select_for_update().get(id=identifier)
                trusted = (
                    doc.security_status == "clean"
                    and doc.scanned_sha256 == doc.sha256
                    and ScanAttempt.objects.filter(
                        document=doc, result="clean", sha256=doc.sha256, finished_at=doc.scanned_at
                    ).exists()
                )
                quarantine_verified = False
                try:
                    if not doc.quarantine_path:
                        data = storage.path(doc.original_path).read_bytes()
                        doc.quarantine_path = f"_quarantine/{doc.id}.bin"
                        storage.atomic_write(doc.quarantine_path, data, doc.sha256)
                    if storage.checksum(storage.path(doc.quarantine_path).read_bytes()) != doc.sha256:
                        raise ValueError("Quarantine hash mismatch")
                    quarantine_verified = True
                    os.chmod(storage.path(doc.quarantine_path).parent, 0o700)
                    os.chmod(storage.path(doc.quarantine_path), 0o600)
                except Exception as exc:
                    # No bytes/exception strings in operational output.
                    doc.security_status = "error"
                    doc.security_error = "Quarantäne fehlt oder ist beschädigt; Sicherung prüfen."
                    trusted = False
                    self.stderr.write(f"Dokument {doc.id}: {type(exc).__name__}")
                if not trusted:
                    if doc.security_status == "clean":
                        doc.security_status, doc.security_error = (
                            "pending",
                            "Vertrauenswürdiger Scannachweis fehlt.",
                        )
                    doc.scanned_sha256 = ""
                    if doc.security_status == "pending":
                        doc.scan_due_at = timezone.now()
                    if doc.filed_path:
                        storage.path(doc.filed_path).unlink(missing_ok=True)
                        doc.filed_path = ""
                    if doc.original_path.startswith("_originals/") and quarantine_verified:
                        storage.path(doc.original_path).unlink(missing_ok=True)
                        doc.original_path = doc.quarantine_path
                doc.save()
        for ticket in UploadTicket.objects.filter(uploaded=True, document__isnull=True):
            old = f"_uploads/{ticket.id}.bin"
            if storage.path(old).exists():
                storage.atomic_write(
                    f"_quarantine/transfers/{ticket.id}.bin",
                    storage.path(old).read_bytes(),
                    ticket.expected_sha256,
                )
                storage.path(old).unlink()
        for source in ImportSource.objects.exclude(error=""):
            old = source.provenance.get("preserved_path", "")
            if old.startswith("_rejected/") and storage.path(old).exists():
                new = "_quarantine/rejected/" + old.removeprefix("_rejected/")
                storage.atomic_write(new, storage.path(old).read_bytes(), source.provenance["sha256"])
                source.provenance = {**source.provenance, "preserved_path": new}
                source.save(update_fields=["provenance"])
                storage.path(old).unlink()
        self.stdout.write("Sicherheitsstatus und Quarantänetrennung geprüft.")
