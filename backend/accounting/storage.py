"""Immutable originals plus a durable journal for materialized business folders.

The database commits desired state first. Reconciliation can be repeated after any
interruption; the immutable original remains the source of truth throughout.
"""

import hashlib
import os
import re
import tempfile

from django.conf import settings
from django.db import transaction

from .auth import DomainError
from .models import Document, FileOperation

FOLDERS = ("ER", "AR", "Bankkonto", "Wertpapiere")
KIND_FOLDER = {
    "incoming_invoice": "ER",
    "incoming_credit": "ER",
    "receipt": "ER",
    "outgoing_invoice": "AR",
    "outgoing_cancellation": "AR",
    "bank_pdf": "Bankkonto",
    "bank_camt": "Bankkonto",
    "security_pdf": "Wertpapiere",
}


def path(relative):
    root = settings.DATA_ROOT.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise DomainError("Ungültiger Dateipfad.")
    return candidate


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def safe_filename(name):
    name = str(name).replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w. -]", "_", name, flags=re.UNICODE).strip(" .")[:160]
    return name or "dokument"


def atomic_write(relative, data, expected_hash=None):
    destination = path(relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if expected_hash and checksum(data) != expected_hash:
        raise DomainError("Original-Prüfsumme stimmt nicht.", 409)
    if destination.exists():
        if checksum(destination.read_bytes()) != checksum(data):
            raise DomainError("Zieldatei existiert mit abweichendem Inhalt.", 409)
        return
    fd, tmp = tempfile.mkstemp(prefix=".pending-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, destination)
        directory_fd = os.open(destination.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ensure_month(company, period):
    year, month = period.split("-")
    for folder in FOLDERS:
        path(f"{company.folder}/{year}/{month}/{folder}").mkdir(parents=True, exist_ok=True)


def desired_path(doc):
    filename = f"{doc.id}_{safe_filename(doc.original_name)}"
    if doc.company_id and doc.period and doc.kind in KIND_FOLDER:
        year, month = doc.period.split("-")
        return f"{doc.company.folder}/{year}/{month}/{KIND_FOLDER[doc.kind]}/{filename}"
    return f"_inbox/{doc.inbox_owner_id}/{filename}"


def journal(doc):
    return FileOperation.objects.create(
        document=doc, version=doc.version, old_path=doc.filed_path, new_path=desired_path(doc)
    )


def reconcile(document_id=None):
    ids = FileOperation.objects.filter(status="pending")
    if document_id:
        ids = ids.filter(document_id=document_id)
    for op_id in list(ids.order_by("id").values_list("id", flat=True)):
        try:
            with transaction.atomic():
                op = FileOperation.objects.get(id=op_id)
                doc = (
                    Document.objects.select_for_update(of=("self",))
                    .select_related("company")
                    .get(id=op.document_id)
                )
                if op.status != "pending":
                    continue
                if op.version != doc.version:
                    op.status = "superseded"
                    op.save(update_fields=["status"])
                    continue
                if doc.company_id and doc.period:
                    ensure_month(doc.company, doc.period)
                data = path(doc.original_path).read_bytes()
                atomic_write(op.new_path, data, doc.sha256)
                # Clean obsolete journal targets too: a crash may have published an earlier target
                # before its transaction was committed.
                old_paths = set(
                    FileOperation.objects.filter(document=doc)
                    .exclude(new_path=op.new_path)
                    .values_list("new_path", flat=True)
                )
                old_paths.add(doc.filed_path)
                for old in old_paths:
                    if old and old not in {op.new_path, doc.original_path}:
                        path(old).unlink(missing_ok=True)
                doc.filed_path = op.new_path
                doc.save(update_fields=["filed_path"])
                op.status = "done"
                op.error = ""
                op.save(update_fields=["status", "error"])
        except Exception as e:
            FileOperation.objects.filter(id=op_id).update(error=str(e)[:2000])


def read_original(doc):
    data = path(doc.original_path).read_bytes()
    if checksum(data) != doc.sha256:
        raise DomainError("Integritätsprüfung des Originals fehlgeschlagen.", 409)
    return data
