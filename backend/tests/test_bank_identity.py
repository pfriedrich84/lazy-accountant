"""Synthetic originals only: explicit identity links, never a payment merge."""

import json
from uuid import uuid4

import pytest
from django.utils import timezone

from accounting import bank_identity as identity, bank_state, packages, reconciliation as bank, services
from accounting.auth import DomainError, issue_token, token_actor
from accounting.models import (
    BankControlEvent,
    BankIdentityResolution,
    BankTransaction,
    BankTransactionSource,
    Document,
    PaymentAllocation,
)
from test_reconciliation import assign, camt, invoice, normalize, statement

pytestmark = pytest.mark.django_db


def pair(actor, company, source_changes=None, canonical_changes=None):
    source = statement(
        actor, company, camt(**{"reference": "", "txid": "SYNTH-TX-1", **(source_changes or {})})
    )
    duplicate_id = normalize(actor, source, auto=False)["transaction_ids"][0]
    target = statement(
        actor,
        company,
        camt(**{"reference": "SYNTH-BANK-1", "txid": "SYNTH-TX-1", **(canonical_changes or {})}),
    )
    canonical_id = normalize(actor, target, auto=False)["transaction_ids"][0]
    return source, target, duplicate_id, canonical_id


def command(actor, duplicate_id, canonical_id):
    preview = identity.preview(actor, duplicate_id, canonical_id)
    return {
        k: preview[k]
        for k in [
            "duplicate_id",
            "canonical_id",
            "duplicate_version",
            "canonical_version",
            "document_versions",
        ]
    } | {
        "reason": "Originale und Bank-TxId/Gegenkonto explizit gegengeprüft",
        "idempotency_key": str(uuid4()),
    }


def test_link_preserves_sources_payments_originals_and_blocks_double_use(actor, companies):
    company = companies[0]
    source, target, duplicate_id, canonical_id = pair(actor, company)
    inv = invoice(actor, company)
    canonical = BankTransaction.objects.get(id=canonical_id)
    assign(actor, canonical, inv, amount="40")
    old_allocations = list(PaymentAllocation.objects.values())
    old_sources = list(BankTransactionSource.objects.order_by("id").values())
    old_doc = services.document_data(services.get_document(actor, source["id"]))
    preview = identity.preview(actor, duplicate_id, canonical_id)
    assert preview["can_merge"] and not preview["blockers"]
    assert identity.candidates(actor, duplicate_id)["items"][0]["canonical_id"] == canonical_id
    payload = command(actor, duplicate_id, canonical_id)
    result = identity.merge(actor, **payload)
    assert result["state"] == "merged" and result["payment_effect"] == "none"
    assert identity.merge(actor, **payload) == result
    assert list(PaymentAllocation.objects.values()) == old_allocations
    assert list(BankTransactionSource.objects.order_by("id").values()) == old_sources
    assert services.document_data(services.get_document(actor, source["id"])) == old_doc
    duplicate = BankTransaction.objects.get(id=duplicate_id)
    assert bank.transaction_data(duplicate)["available"] == "0"
    assert bank.transaction_data(duplicate)["issues"] == []
    assert bank.transaction_data(duplicate)["original_issues"] == [identity.MISSING_IDENTITY]
    with pytest.raises(DomainError):
        identity.merge(actor, **command(actor, duplicate_id, canonical_id))
    assert bank.candidates(actor, duplicate_id)["items"] == []
    with pytest.raises(DomainError) as error:
        assign(actor, duplicate, inv, amount="40")
    assert error.value.status == 409
    canonical.refresh_from_db()
    assert len(bank.transaction_data(canonical)["sources"]) == 2
    assert len(identity.history(actor, canonical_id)["items"]) == 1
    evidence = BankIdentityResolution.objects.get().evidence
    assert evidence["transaction_id"] == "SYNTH-TX-1" and len(evidence["sources"]) == 2
    assert all(e["sha256"] and e["locator"] for e in evidence["sources"])
    # Re-normalization never recreates a spendable copy or another payment.
    normalize(actor, source)
    normalize(actor, target)
    assert PaymentAllocation.objects.count() == 1
    assert BankTransaction.objects.get(id=duplicate_id).merged_into_id == canonical.id
    state = bank_state.account_overview(actor, company.id, "2026-10")["items"][0]
    assert state["transaction_count"] == 1 and state["merged_observation_count"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"amount": "80.00"},
        {"direction": "DBIT"},
        {"party": ""},
        {"number": "OTHER-REF"},
        {"status": "PDNG"},
        {"reference": "SECOND-BANK-ID"},
        {"txid": "OTHER-TX"},
        {"txid": "", "end_to_end_id": "SAME-E2E"},
    ],
)
def test_uncertain_or_conflicting_facts_never_merge(actor, companies, change):
    _, _, duplicate_id, canonical_id = pair(actor, companies[0], source_changes=change)
    preview = identity.preview(actor, duplicate_id, canonical_id)
    assert not preview["can_merge"] and preview["blockers"]
    with pytest.raises(DomainError) as error:
        identity.merge(actor, **command(actor, duplicate_id, canonical_id))
    assert error.value.status == 409
    assert not BankIdentityResolution.objects.exists()


def test_end_to_end_and_amount_alone_have_no_identity_candidates(actor, companies):
    _, _, duplicate_id, canonical_id = pair(
        actor,
        companies[0],
        source_changes={"txid": "", "end_to_end_id": "SAME"},
        canonical_changes={"txid": "", "end_to_end_id": "SAME"},
    )
    assert identity.candidates(actor, duplicate_id)["items"] == []
    assert not identity.preview(actor, duplicate_id, canonical_id)["can_merge"]


def test_reused_txid_is_not_arbitrarily_resolved(actor, companies):
    _, _, duplicate_id, canonical_id = pair(actor, companies[0])
    normalize(actor, statement(actor, companies[0], camt(reference="THIRD", txid="SYNTH-TX-1")), auto=False)
    assert not identity.preview(actor, duplicate_id, canonical_id)["can_merge"]
    assert all(not row["can_merge"] for row in identity.candidates(actor, duplicate_id)["items"])


def test_financially_referenced_observation_even_reversed_remains_protected(actor, companies):
    _, _, duplicate_id, canonical_id = pair(actor, companies[0])
    inv = invoice(actor, companies[0])
    PaymentAllocation.objects.create(
        transaction_id=duplicate_id,
        document_id=inv["id"],
        amount="40",
        bank_amount="40",
        decision="manual_confirmed",
        actor_id=actor.user_id,
        reason="Synthetischer Legacy-Konflikt",
        reversed_at=timezone.now(),
    )
    assert not identity.preview(actor, duplicate_id, canonical_id)["can_merge"]
    with pytest.raises(DomainError):
        identity.merge(actor, **command(actor, duplicate_id, canonical_id))
    assert PaymentAllocation.objects.count() == 1


def test_versions_idempotency_and_reparsed_originals_protect_the_link(actor, companies):
    source, _, duplicate_id, canonical_id = pair(actor, companies[0])
    payload = command(actor, duplicate_id, canonical_id)
    Document.objects.filter(id=source["id"]).update(version=source["version"] + 1)
    with pytest.raises(DomainError) as stale:
        identity.merge(actor, **payload)
    assert stale.value.status == 409 and not BankIdentityResolution.objects.exists()
    # Equal DB values do not suffice: bank facts must still be in the original bytes.
    BankTransaction.objects.filter(id__in=[duplicate_id, canonical_id]).update(
        party_name="Manipulierte Projektion"
    )
    refreshed = command(actor, duplicate_id, canonical_id)
    with pytest.raises(DomainError) as original:
        identity.merge(actor, **refreshed)
    assert original.value.status == 409
    assert (
        not BankIdentityResolution.objects.exists()
        and not BankControlEvent.objects.filter(operation="identity.merge").exists()
    )


def test_dispute_keeps_funds_closed_and_survives_reimport_with_frozen_packages(actor, companies):
    company = companies[0]
    source, target, duplicate_id, canonical_id = pair(actor, company)
    inv = invoice(actor, company)
    assign(actor, BankTransaction.objects.get(id=canonical_id), inv)
    before = packages.create_package(actor, company.id, ["2026-10"], "before-identity")
    old = packages.package_bytes(packages.get_package(actor, before["id"]))
    result = identity.merge(actor, **command(actor, duplicate_id, canonical_id))
    merged = packages.create_package(actor, company.id, ["2026-10"], "identity-link", before["id"])
    assert inv["id"] in merged["snapshot"]["payment_changes"]
    disputed = identity.dispute(
        actor,
        duplicate_id,
        result["duplicate_version"],
        result["canonical_version"],
        "Bezug nachträglich bestritten",
        "dispute",
    )
    assert (
        identity.dispute(
            actor,
            duplicate_id,
            result["duplicate_version"],
            result["canonical_version"],
            "Bezug nachträglich bestritten",
            "dispute",
        )
        == disputed
    )
    normalize(actor, source)
    normalize(actor, target)
    status = bank.payment_status(actor, inv["id"])
    assert status["status"] == "paid" and status["bank_evidence"] == "disputed"
    assert PaymentAllocation.objects.count() == 1 and not PaymentAllocation.objects.get().reversed_at
    assert bank.transaction_data(BankTransaction.objects.get(id=duplicate_id))["available"] == "0"
    assert len(identity.history(actor, canonical_id)["items"]) == 2
    assert packages.package_bytes(packages.get_package(actor, before["id"])) == old
    supplement = packages.create_package(actor, company.id, ["2026-10"], "identity-dispute", merged["id"])
    assert supplement["snapshot"]["payments"][0]["bank_evidence"] == "disputed"


def test_linked_observation_is_not_a_second_original_for_bank_return(actor, companies):
    company = companies[0]
    _, _, duplicate_id, canonical_id = pair(actor, company)
    inv = invoice(actor, company)
    assign(actor, BankTransaction.objects.get(id=canonical_id), inv)
    identity.merge(actor, **command(actor, duplicate_id, canonical_id))
    returned = statement(
        actor, company, camt(reference="RETURN", txid="SYNTH-TX-1", direction="DBIT", reversal=True)
    )
    assert normalize(actor, returned, auto=False)["applied_reversals"]
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"
    assert PaymentAllocation.objects.get().reversed_at
    assert bank.transaction_data(BankTransaction.objects.get(id=duplicate_id))["available"] == "0"


def test_alias_source_quarantine_blocks_canonical_evidence_and_audit(actor, companies):
    source, _, duplicate_id, canonical_id = pair(actor, companies[0])
    inv = invoice(actor, companies[0])
    assign(actor, BankTransaction.objects.get(id=canonical_id), inv)
    result = identity.merge(actor, **command(actor, duplicate_id, canonical_id))
    Document.objects.filter(id=source["id"]).update(security_status="infected")
    for operation in [
        lambda: bank.payment_status(actor, inv["id"]),
        lambda: identity.history(actor, canonical_id),
        lambda: identity.history(actor, duplicate_id),
    ]:
        with pytest.raises(DomainError) as error:
            operation()
        assert error.value.status == 423
    # A safety dispute may still be recorded without reading quarantined original data.
    identity.dispute(
        actor,
        duplicate_id,
        result["duplicate_version"],
        result["canonical_version"],
        "Quelle gesperrt",
        "blocked-dispute",
    )
    assert BankIdentityResolution.objects.get().disputed_at


def test_original_reparse_has_explicit_work_budget(monkeypatch, actor, companies, settings):
    source, target, duplicate_id, canonical_id = pair(actor, companies[0])
    settings.MAX_FILE_BYTES = source["size"] + target["size"] - 1
    assert not identity.preview(actor, duplicate_id, canonical_id)["can_merge"]
    settings.MAX_FILE_BYTES = 25 * 1024 * 1024
    monkeypatch.setattr(identity, "MAX_PROOF_ROWS", 1)
    with pytest.raises(DomainError) as error:
        identity.merge(actor, **command(actor, duplicate_id, canonical_id))
    assert error.value.status == 409 and not BankIdentityResolution.objects.exists()


def test_identity_write_and_audit_rollback_together(monkeypatch, actor, companies):
    _, _, duplicate_id, canonical_id = pair(actor, companies[0])
    payload = command(actor, duplicate_id, canonical_id)

    def fail(**kwargs):
        raise RuntimeError("Synthetischer Auditfehler")

    monkeypatch.setattr(BankControlEvent.objects, "create", fail)
    with pytest.raises(RuntimeError):
        identity.merge(actor, **payload)
    assert BankTransaction.objects.get(id=duplicate_id).merged_into_id is None
    assert BankTransaction.objects.get(id=canonical_id).version == payload["canonical_version"]
    assert not BankIdentityResolution.objects.exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("other", ["merge", "allocate"])
def test_postgres_identity_merge_racing_other_writers_is_atomic(actor, companies, other):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    _, _, duplicate_id, canonical_id = pair(actor, companies[0])
    inv = invoice(actor, companies[0])
    payload = command(actor, duplicate_id, canonical_id)
    barrier = Barrier(2)

    def run(operation):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                if operation == "merge":
                    identity.merge(actor, **{**payload, "idempotency_key": str(uuid4())})
                else:
                    bank.allocate(
                        actor,
                        canonical_id,
                        inv["id"],
                        "120",
                        payload["canonical_version"],
                        inv["version"],
                        "Original geprüft",
                        str(uuid4()),
                    )
                return "ok"
            except DomainError as exc:
                return exc.status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, ["merge", other]))
    assert outcomes.count("ok") == 1 and outcomes.count(409) == 1
    assert PaymentAllocation.objects.count() <= 1 and BankIdentityResolution.objects.count() <= 1
    assert not PaymentAllocation.objects.filter(transaction_id=duplicate_id).exists()


def test_complete_rest_upload_review_normalize_merge_dispute_flow(client, companies):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from accounting.models import Account

    company = companies[0]
    account = Account.objects.get(company=company, kind="bank")
    ids = []
    for reference in ["", "SYNTH-REST-BANK"]:
        uploaded = client.post(
            "/api/documents/",
            {
                "company_id": company.id,
                "files": SimpleUploadedFile("synthetic.xml", camt(reference=reference, txid="SYNTH-REST-TX")),
            },
            format="multipart",
        )
        assert uploaded.status_code == 201
        doc = client.get(f"/api/documents/{uploaded.json()['results'][0]['document']['id']}/").json()
        assert doc["security_status"] == "clean"
        approved = client.put(
            f"/api/documents/{doc['id']}/",
            {
                "document_id": doc["id"],
                "base_version": doc["version"],
                "company_id": company.id,
                "kind": "bank_camt",
                "period": "2026-10",
                "account_id": account.id,
                "metadata": {**doc["metadata"], "period_start": "2026-10-01", "period_end": "2026-10-31"},
                "approve": True,
            },
            format="json",
        )
        assert approved.status_code == 200, approved.json()
        normalized = client.post(
            "/api/reconciliation/normalize/",
            {
                "document_id": doc["id"],
                "base_version": approved.json()["version"],
                "auto_confirm": False,
                "idempotency_key": str(uuid4()),
            },
            format="json",
        )
        assert normalized.status_code == 200, normalized.json()
        ids.append(normalized.json()["transaction_ids"][0])
    preview = client.get(
        "/api/reconciliation/identity-preview/", {"duplicate_id": ids[0], "canonical_id": ids[1]}
    ).json()
    assert preview["can_merge"], preview
    payload = {
        k: preview[k]
        for k in [
            "duplicate_id",
            "canonical_id",
            "duplicate_version",
            "canonical_version",
            "document_versions",
        ]
    }
    merged = client.post(
        "/api/reconciliation/identity-merge/",
        {**payload, "reason": "Originale geprüft", "idempotency_key": "rest-merge"},
        format="json",
    )
    assert merged.status_code == 200, merged.json()
    disputed = client.post(
        "/api/reconciliation/identity-dispute/",
        {
            "duplicate_id": ids[0],
            "duplicate_version": merged.json()["duplicate_version"],
            "canonical_version": merged.json()["canonical_version"],
            "reason": "Bezug bestritten",
            "idempotency_key": "rest-dispute",
        },
        format="json",
    )
    assert disputed.status_code == 200, disputed.json()
    assert disputed.json()["payment_effect"] == "none" and not PaymentAllocation.objects.exists()


def test_rest_mcp_contract_scopes_and_strict_schema(client, actor, companies):
    _, _, duplicate_id, canonical_id = pair(actor, companies[0])
    preview = client.get(
        "/api/reconciliation/identity-preview/", {"duplicate_id": duplicate_id, "canonical_id": canonical_id}
    )
    assert preview.status_code == 200 and preview.json()["can_merge"]
    payload = command(actor, duplicate_id, canonical_id)
    for invalid in [
        {"duplicate_version": True},
        {"canonical_version": "1"},
        {"reason": "  "},
        {"bank_reference": "fake"},
        {"reason": "\x00"},
        {"idempotency_key": "\x00"},
        {"reason": "\ud800"},
    ]:
        assert (
            client.post(
                "/api/reconciliation/identity-merge/",
                json.dumps({**payload, **invalid}),
                content_type="application/json",
            ).status_code
            == 400
        )
    readonly = token_actor(issue_token(actor, "identity-read", [companies[0].id], ["read"])["token"])
    assert identity.preview(readonly, duplicate_id, canonical_id)["can_merge"]
    with pytest.raises(DomainError):
        identity.merge(readonly, **payload)
    foreign = token_actor(
        issue_token(actor, "identity-foreign", [companies[1].id], ["read", "process"])["token"]
    )
    with pytest.raises(DomainError):
        identity.preview(foreign, duplicate_id, canonical_id)
    response = client.post("/api/reconciliation/identity-merge/", payload, format="json")
    assert response.status_code == 200
    assert (
        client.post("/api/reconciliation/identity-merge/", payload, format="json").json() == response.json()
    )
    assert (
        client.post(
            "/api/reconciliation/identity-merge/", {**payload, "reason": "anderer Payload"}, format="json"
        ).status_code
        == 409
    )
    assert client.get("/api/reconciliation/identity-history/", {"transaction_id": canonical_id}).json()[
        "items"
    ]
    assert (
        client.get(
            "/api/reconciliation/identity-preview/", {"duplicate_id": "bad", "canonical_id": canonical_id}
        ).status_code
        == 400
    )
