"""Synthetic declarations: monthly convention, persistent policy, no invented payment."""

from uuid import uuid4

import pytest

from accounting import bank_state as controls, reconciliation as bank, services, packages
from accounting.auth import DomainError, issue_token, token_actor
from accounting.models import (
    Account,
    BankControlEvent,
    BankMonthCoverage,
    BankTransaction,
    Document,
    PaymentAllocation,
)
from test_reconciliation import PARTY, camt, invoice, normalize, statement

pytestmark = pytest.mark.django_db


def policy(actor, company, enabled, version=0, key=None):
    return controls.set_policy(
        actor, company.id, version, enabled, "Expliziter Testauftrag", key or str(uuid4())
    )


def coverage(actor, company, doc, version=0, state="confirmed", key=None):
    return controls.set_coverage(
        actor,
        company.id,
        doc["account_id"],
        doc["period"],
        version,
        state,
        [doc["id"]],
        "Originalmonat bewusst geprüft",
        key or str(uuid4()),
        document_versions={doc["id"]: doc["version"]},
    )


def test_normalize_rechecks_company_before_using_policy(monkeypatch, actor, companies):
    doc = statement(actor, companies[0])
    original_lock = bank._lock_company

    def change_company(current_actor, company_id):
        result = original_lock(current_actor, company_id)
        Document.objects.filter(id=doc["id"]).update(
            company=companies[1], account=Account.objects.get(company=companies[1], kind="bank")
        )
        return result

    monkeypatch.setattr(bank, "_lock_company", change_company)
    with pytest.raises(DomainError) as error:
        normalize(actor, doc)
    assert error.value.status == 409
    assert not BankTransaction.objects.exists()


def test_policy_preserves_default_and_blocks_request_override(actor, companies):
    company = companies[0]
    assert controls.get_policy(actor, company.id)["enabled"]
    assert controls.get_policy(actor, company.id)["version"] == 0
    saved = policy(actor, company, False, key="disable")
    assert saved["enabled"] is False and saved["version"] == 1
    assert policy(actor, company, False, key="disable") == saved
    inv = invoice(actor, company)
    bank.verify_party(actor, company.id, "Acme Customer", PARTY, "Bekannte Bankdaten")
    result = normalize(actor, statement(actor, company), auto=True)
    assert not result["auto_confirm_effective"] and result["automation_policy"]["version"] == 1
    assert not PaymentAllocation.objects.exists()
    with pytest.raises(DomainError) as error:
        policy(actor, company, True, version=0)
    assert error.value.status == 409
    with pytest.raises(DomainError):
        policy(actor, company, True, version=1, key="disable")
    policy(actor, company, True, version=1)
    # A new explicit request after enablement may match; changing policy itself never allocates.
    assert not PaymentAllocation.objects.exists()
    source = BankTransaction.objects.get().sources.get().document
    result = bank.reconcile_document(actor, str(source.id), source.version, "enabled-normalize", True)
    assert len(result["confirmed"]) == 1 and bank.payment_status(actor, inv["id"])["status"] == "paid"
    assert BankControlEvent.objects.filter(operation="policy").count() == 2


def test_disabled_policy_does_not_suppress_explicit_bank_reversal(actor, companies):
    company = companies[0]
    inv = invoice(actor, company)
    bank.verify_party(actor, company.id, "Acme Customer", PARTY, "Bekannte Bankdaten")
    normalize(actor, statement(actor, company))
    policy(actor, company, False)
    result = normalize(actor, statement(actor, company, camt(direction="DBIT", reversal=True)))
    assert result["applied_reversals"] and not result["auto_confirm_effective"]
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"


def test_monthly_convention_never_requires_calendar_boundary_reconfirmation(actor, companies):
    company = companies[0]
    doc = statement(actor, company)
    # A previously approved monthly statement may have fuzzy dates; month assignment is retained.
    Document.objects.filter(id=doc["id"]).update(
        metadata={"period_start": "2026-10-02", "period_end": "2026-10-15"}
    )
    first = controls.account_overview(actor, company.id, "2026-10")["items"][0]
    assert first["coverage"]["effective_state"] == "confirmed"
    assert first["coverage"]["basis"] == "accepted_monthly_statement_convention"
    assert not BankMonthCoverage.objects.exists() and not PaymentAllocation.objects.exists()
    confirmed = coverage(actor, company, doc, key="coverage")
    assert confirmed["effective_state"] == "confirmed" and confirmed["version"] == 1
    # Name-only revisions and fuzzy date boundaries do not invalidate the existing declaration.
    Document.objects.filter(id=doc["id"]).update(
        version=99, metadata={"period_start": "2026-10-02", "period_end": "2026-10-18"}
    )
    again = controls.account_overview(actor, company.id, "2026-10")["items"][0]
    assert again["coverage"]["effective_state"] == "confirmed"
    assert coverage(actor, company, doc, key="coverage") == confirmed
    assert not PaymentAllocation.objects.exists()
    excluded = services.change_document_exclusion(
        actor,
        doc["id"],
        {"base_version": 99, "reason": "Test: Quelle nicht relevant", "idempotency_key": "coverage-exclude"},
        excluded=True,
    )["document"]
    assert (
        controls.account_overview(actor, company.id, "2026-10")["items"][0]["coverage"]["effective_state"]
        == "disputed"
    )
    services.change_document_exclusion(
        actor,
        doc["id"],
        {
            "base_version": excluded["version"],
            "reason": "Test: Quelle wieder relevant",
            "idempotency_key": "coverage-restore",
        },
        excluded=False,
    )
    assert (
        controls.account_overview(actor, company.id, "2026-10")["items"][0]["coverage"]["effective_state"]
        == "confirmed"
    )
    assert not PaymentAllocation.objects.exists()


def test_concrete_contradictions_do_not_erase_month_declaration(actor, companies):
    company = companies[0]
    doc = statement(actor, company)
    coverage(actor, company, doc)
    Document.objects.filter(id=doc["id"]).update(issues=["Seite 2 fehlt"], status="review")
    row = controls.account_overview(actor, company.id, "2026-10")["items"][0]
    assert row["coverage"]["declared_state"] == "confirmed"
    assert row["coverage"]["effective_state"] == "disputed"
    assert row["history"][0]["version"] == 1
    with pytest.raises(DomainError) as exc:
        coverage(actor, company, doc, version=1)
    assert exc.value.status == 409
    coverage(actor, company, doc, version=1, state="disputed")
    assert BankControlEvent.objects.filter(operation="coverage").count() == 2
    assert not PaymentAllocation.objects.exists()


def test_other_contradicting_month_source_cannot_be_silently_omitted(actor, companies):
    company = companies[0]
    doc = statement(actor, company)
    coverage(actor, company, doc)
    other = statement(actor, company, camt(reference="SECOND-SOURCE"))
    Document.objects.filter(id=other["id"]).update(issues=["Konkrete Seitenlücke"])
    assert (
        controls.account_overview(actor, company.id, "2026-10")["items"][0]["coverage"]["effective_state"]
        == "disputed"
    )
    with pytest.raises(DomainError) as error:
        coverage(actor, company, doc, version=1)
    assert error.value.status == 409


def test_data_dates_are_not_coverage_and_quarantine_redacts_aggregates(actor, companies):
    company = companies[0]
    doc = statement(actor, company)
    normalize(actor, doc, auto=False)
    row = controls.account_overview(actor, company.id, "2026-11")["items"][0]
    assert row["latest_booked_date"] == "2026-10-15"
    assert row["coverage"]["effective_state"] == "unknown" and row["transaction_count"] == 1
    coverage(actor, company, doc)
    Document.objects.filter(id=doc["id"]).update(security_status="infected")
    row = controls.account_overview(actor, company.id, "2026-10")["items"][0]
    assert row["security_blocked"] and row["transaction_count"] is None and row["latest_booked_date"] is None
    assert row["coverage"]["effective_state"] == "disputed"


def test_control_changes_preserve_originals_payment_snapshots_and_old_packages(actor, companies):
    company = companies[0]
    inv = invoice(actor, company)
    doc = statement(actor, company)
    before = packages.create_package(actor, company.id, ["2026-10"], "before-controls")
    package = packages.get_package(actor, before["id"])
    old_bytes = packages.package_bytes(package)
    old_doc = services.document_data(services.get_document(actor, doc["id"]))
    policy(actor, company, False)
    coverage(actor, company, doc)
    assert packages.package_bytes(package) == old_bytes
    assert services.document_data(services.get_document(actor, doc["id"])) == old_doc
    preview = packages.package_preview(actor, company.id, ["2026-10"], before["id"])
    assert preview["payment_changes"] == []
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"
    assert not PaymentAllocation.objects.exists()


def test_scope_and_rest_validation_idempotency(client, actor, companies):
    company = companies[0]
    doc = statement(actor, company)
    readonly = token_actor(issue_token(actor, "read", [company.id], ["read"])["token"])
    process = token_actor(issue_token(actor, "process", [company.id], ["read", "process"])["token"])
    with pytest.raises(DomainError):
        policy(readonly, company, False)
    with pytest.raises(DomainError):
        policy(process, company, False)
    with pytest.raises(DomainError):
        coverage(readonly, company, doc)
    with pytest.raises(DomainError):
        controls.account_overview(readonly, companies[1].id, "2026-10")
    assert coverage(process, company, doc)["version"] == 1
    Document.objects.filter(id=doc["id"]).update(version=doc["version"] + 1)
    with pytest.raises(DomainError) as stale:
        coverage(process, company, doc, version=1)
    assert stale.value.status == 409
    for period in ("2026-00", "2026-13", "0000-01", "2026-1", None):
        assert (
            client.get(
                "/api/reconciliation/accounts/", {"company_id": company.id, "period": period or ""}
            ).status_code
            == 400
        )
    body = {
        "company_id": company.id,
        "enabled": False,
        "expected_version": 0,
        "reason": "Test",
        "idempotency_key": "rest-policy",
    }
    assert client.post("/api/reconciliation/policy/", body, format="json").status_code == 200
    for invalid in ({"enabled": "false"}, {"expected_version": True}, {"reason": "  "}, {"unknown": True}):
        assert (
            client.post("/api/reconciliation/policy/", {**body, **invalid}, format="json").status_code == 400
        )
    assert client.get(
        "/api/reconciliation/policy/", {"company_id": company.id}
    ).json() == controls.get_policy(actor, company.id)
    assert (
        client.get(
            "/api/reconciliation/accounts/", {"company_id": company.id, "period": "2026-10"}
        ).status_code
        == 200
    )
    foreign_account = Account.objects.get(company=companies[1], kind="bank")
    with pytest.raises(DomainError) as error:
        controls.set_coverage(
            actor,
            company.id,
            foreign_account.id,
            "2026-10",
            0,
            "confirmed",
            [doc["id"]],
            "Test",
            "foreign",
            document_versions={doc["id"]: doc["version"]},
        )
    assert error.value.status == 404


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["policy", "coverage"])
def test_postgres_parallel_control_versions_have_one_winner(actor, companies, operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    company = companies[0]
    doc = statement(actor, company)
    barrier = Barrier(2)

    def run(value):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                if operation == "policy":
                    policy(actor, company, value)
                else:
                    coverage(actor, company, doc, state="confirmed" if value else "unknown")
                return "ok"
            except DomainError as exc:
                return exc.status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, [True, False]))
    assert outcomes.count("ok") == 1 and outcomes.count(409) == 1
    assert BankControlEvent.objects.filter(operation=operation).count() == 1
