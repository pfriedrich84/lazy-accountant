"""Malware gates stay independent of reversible business exclusions."""

from unittest.mock import patch

import pytest

from accounting import packages, scanner, security, services, storage
from accounting.auth import DomainError
from accounting.demo import sample_pdf
from accounting.models import Document

pytestmark = [pytest.mark.django_db, pytest.mark.security]


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    monkeypatch.setattr(security, "publish", lambda identifier: None)


@pytest.mark.parametrize("state", ["pending", "infected", "error"])
def test_business_exclude_restore_never_clears_security_gate(actor, companies, state):
    identifier = services.ingest(actor, "blocked.pdf", sample_pdf(["blocked"]), companies[0].id)["document"][
        "id"
    ]
    Document.objects.filter(id=identifier).update(security_status=state)
    for excluded, version in [(True, 1), (False, 2)]:
        services.change_document_exclusion(
            actor,
            identifier,
            {
                "base_version": version,
                "reason": "Explicit business action",
                "idempotency_key": f"action-{version}",
            },
            excluded=excluded,
        )
        doc = Document.objects.get(id=identifier)
        assert doc.security_status == state
        with pytest.raises(DomainError):
            storage.read_original(doc)
        preview = packages.package_preview(actor, companies[0].id, ["2026-10"])
        assert not preview["documents"]
        if excluded:
            assert not preview["security_blocked"]
            assert identifier in {row["document"]["id"] for row in preview["intentional_exclusions"]}
        else:
            assert preview["security_blocked"]
        assert not doc.filed_path


def test_old_exclusion_receipt_cannot_replay_text_after_later_finding(actor, companies):
    identifier = services.ingest(actor, "receipt.pdf", sample_pdf(["private"]), companies[0].id)["document"][
        "id"
    ]
    with patch.object(scanner, "scan", return_value=scanner.Verdict("clean", "test-engine/1")):
        security.run_scan(identifier)
    payload = {"base_version": 1, "reason": "Explicit user decision", "idempotency_key": "receipt"}
    original = services.change_document_exclusion(actor, identifier, payload, excluded=True)
    assert original["document"]["parser_result"]["pages"] == 1
    Document.objects.filter(id=identifier).update(security_status="infected", security_error="Malware test")
    replay = services.change_document_exclusion(actor, identifier, payload, excluded=True)
    assert replay["document"]["version"] == original["document"]["version"]
    assert replay["document"]["is_excluded"]
    assert replay["document"]["security_status"] == "infected"
    assert replay["document"]["parser_result"] == {}
    assert replay["document"]["revisions"] == []
