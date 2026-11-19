from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounting import scanner, security, services, storage
from accounting.demo import sample_pdf
from accounting.models import Document

pytestmark = [pytest.mark.django_db, pytest.mark.security]


def test_restore_trusts_matching_audit_but_missing_status_requires_scan(actor, companies, monkeypatch):
    monkeypatch.setattr(security, "publish", lambda identifier: None)
    identifier = services.ingest(actor, "restore.pdf", sample_pdf(["restore"]), companies[0].id)["document"][
        "id"
    ]
    with patch.object(scanner, "scan", return_value=scanner.Verdict("clean", "test/123")):
        security.run_scan(identifier)
    doc = Document.objects.get(id=identifier)
    assert doc.security_status == "clean"
    call_command("prepare_security")
    doc.refresh_from_db()
    assert doc.security_status == "clean"
    assert storage.read_original(doc)
    # Even a claimed clean hash is not sufficient without its corresponding
    # trusted completed scan (e.g. partially restored/old database metadata).
    doc.scanned_at = timezone.now() - timedelta(days=1)
    doc.save(update_fields=["scanned_at"])
    call_command("prepare_security")
    doc.refresh_from_db()
    assert doc.security_status == "pending"
    assert not doc.scanned_sha256 and not doc.filed_path
    assert storage.path(doc.quarantine_path).is_file()


def test_migration_legacy_original_is_quarantined_and_unfiled(actor, companies, monkeypatch):
    monkeypatch.setattr(security, "publish", lambda identifier: None)
    data = sample_pdf(["legacy"])
    identifier = services.ingest(actor, "legacy.pdf", data, companies[0].id)["document"]["id"]
    doc = Document.objects.get(id=identifier)
    legacy = f"_originals/{doc.id}.pdf"
    storage.atomic_write(legacy, data)
    filed = f"_inbox/{actor.user_id}/{doc.id}.pdf"
    storage.atomic_write(filed, data)
    Document.objects.filter(id=doc.id).update(original_path=legacy, filed_path=filed, quarantine_path="")
    call_command("prepare_security")
    doc.refresh_from_db()
    assert doc.security_status == "pending"
    assert not doc.filed_path
    assert not storage.path(filed).exists()
    assert storage.path(doc.quarantine_path).read_bytes() == data
