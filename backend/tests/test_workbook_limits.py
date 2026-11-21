"""Synthetic resource budgets for tenant-triggered bank exports; no financial fixtures."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounting import packages, reconciliation
from accounting.auth import DomainError
from accounting.models import Account, BankTransaction, Package
from test_reconciliation import assign, invoice, normalize, statement

pytestmark = pytest.mark.django_db


def movements(company, count=2, remittance=""):
    account = Account.objects.filter(company=company, kind="bank").first()
    BankTransaction.objects.bulk_create(
        [
            BankTransaction(
                company=company,
                account=account,
                identity=f"synthetic-{i}",
                amount="10",
                currency="EUR",
                direction="CRDT",
                booking_date="2026-10-15",
                remittance=remittance,
            )
            for i in range(count)
        ]
    )


@pytest.mark.parametrize("create", [False, True])
def test_bank_row_limit_precedes_projection_and_persistence(actor, companies, settings, monkeypatch, create):
    movements(companies[0])
    settings.MAX_WORKBOOK_BANK_ROWS = 1
    monkeypatch.setattr(
        reconciliation, "transaction_data", lambda tx: pytest.fail("must fail before projection")
    )
    with pytest.raises(DomainError, match="Bankexport") as exc:
        if create:
            packages.create_package(actor, companies[0].id, ["2026-10"], "over-bank-budget")
        else:
            packages.package_preview(actor, companies[0].id, ["2026-10"])
    assert exc.value.status == 413 and not Package.objects.exists()


def test_bank_text_budget_precedes_projection(companies, settings, monkeypatch):
    movements(companies[0], remittance="synthetic-text" * 100)
    settings.MAX_WORKBOOK_BANK_BYTES = 100
    monkeypatch.setattr(
        reconciliation, "transaction_data", lambda tx: pytest.fail("must fail before projection")
    )
    with pytest.raises(DomainError, match="Bankexport"):
        packages.freeze_bank_export(companies[0].id, ["2026-10"], [])


def test_serialized_context_budget_is_also_checked(companies, settings, monkeypatch):
    movements(companies[0], count=1)
    settings.MAX_WORKBOOK_BANK_BYTES = 3000
    original = reconciliation.transaction_data

    def project(tx):
        return {**original(tx), "synthetic_context": "x" * 4000}

    monkeypatch.setattr(reconciliation, "transaction_data", project)
    with pytest.raises(DomainError, match="Bankexport"):
        packages.freeze_bank_export(companies[0].id, ["2026-10"], [])


@pytest.mark.parametrize("phase", ["blockers", "detail", "download", "archive"])
def test_package_safety_paths_do_not_fetch_parser_blobs(actor, companies, phase):
    from accounting.models import Document

    source = statement(actor, companies[0])
    normalize(actor, source, auto=False)
    Document.objects.filter(id=source["id"]).update(period="2026-09")
    inv = invoice(actor, companies[0])
    assign(actor, BankTransaction.objects.get(), inv)
    created = packages.create_package(actor, companies[0].id, ["2026-10"], "slim-package-safety")
    package = packages.get_package(actor, created["id"])
    assert package.context_sources.filter(document_id=source["id"]).exists()
    with CaptureQueriesContext(connection) as queries:
        if phase == "blockers":
            assert packages.package_blockers(package) == []
        elif phase == "detail":
            packages.package_data(package, True)
        elif phase == "download":
            assert packages.package_bytes(package)
        else:
            assert packages.build_archive(package.snapshot, package.id, package.version)
    assert all("parser_result" not in query["sql"] for query in queries)
    assert all('"accounting_document"."metadata"' not in query["sql"] for query in queries)
    if phase != "detail":  # Detail deliberately returns frozen included-item metadata.
        assert all('"accounting_packageitem"."metadata"' not in query["sql"] for query in queries)


def test_bank_projection_does_not_fetch_source_parser_blobs(actor, companies):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0]), auto=False)
    assign(actor, BankTransaction.objects.get(), inv)
    payment = {"allocations": [{"transaction_id": str(BankTransaction.objects.get().id)}]}
    with CaptureQueriesContext(connection) as queries:
        result = packages.freeze_bank_export(companies[0].id, ["2026-10"], [payment])
    assert len(result["bank_transactions"]) == 1
    assert all("parser_result" not in query["sql"] for query in queries)
    assert result["bank_transactions"][0]["invoice_references"] == ["INV-001"]
