"""Zero invoices and explicit third-party coverage are not bank payments."""

import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from accounting import packages, reconciliation as bank, services
from accounting.workbook import build_workbook
from test_workbook_details import rows
from accounting.auth import DomainError
from accounting.models import BankTransaction, Document, PaymentAllocation
from test_reconciliation import assign, camt, invoice, normalize, statement
from test_fx_reconciliation import ecomm_setup, leg, plan
from test_reconciliation_filters import invoices

pytestmark = pytest.mark.django_db


def reviewed(actor, company, gross, settlement=None, currency="EUR", kind="incoming_invoice"):
    result = invoice(actor, company, kind=kind, gross=gross)
    doc = Document.objects.get(id=result["id"])
    metadata = {**doc.metadata, "currency": currency, "due_date": None}
    if settlement is not None:
        metadata["settlement"] = settlement
    return services.save_result(
        actor,
        {
            "document_id": str(doc.id),
            "base_version": doc.version,
            "company_id": company.id,
            "kind": kind,
            "period": "2026-10",
            "metadata": metadata,
            "approve": True,
        },
    )


@pytest.mark.parametrize("kind", ["incoming_invoice", "outgoing_invoice"])
@pytest.mark.parametrize(
    "gross,currency,settlement,basis",
    [
        ("0.00", "USD", None, "zero_invoice"),
        (
            "9.98",
            "EUR",
            {
                "amount_due": "0.00",
                "covered_by_third_party": "9.98",
                "review_note": "Original: durch Dritte übernommen.",
            },
            "third_party_covered",
        ),
    ],
)
def test_no_payment_is_neither_unpaid_nor_paid(
    actor, companies, client, kind, gross, currency, settlement, basis
):
    doc = reviewed(actor, companies[0], gross, settlement, currency, kind)
    status = bank.payment_status(actor, doc["id"], "2026-11-23")
    assert status["status"] == "no_payment_required"
    assert status["payment_basis"] == basis
    assert status["currency"] == currency
    assert Decimal(status["gross"]) == Decimal(gross)
    assert Decimal(status["paid"]) == Decimal(status["remaining"]) == 0
    assert status["overdue"] is False
    assert status["bank_evidence"] == "not_required"
    assert status["allocations"] == []
    assert not PaymentAllocation.objects.exists()
    for state in ("open", "unmatched", "unresolved", "overdue", "review", "paid"):
        assert bank.list_invoice_statuses(actor, companies[0].id, state=state)["items"] == []
    page = bank.list_invoice_statuses(actor, companies[0].id, state="no_payment_required")
    assert len(page["items"]) == 1
    assert page["items"][0]["review_reasons"] == []
    response = client.get("/api/reconciliation/status/", {"document_id": doc["id"], "as_of": "2026-11-23"})
    assert response.status_code == 200
    assert response.json() == status
    snapshot = packages.package_preview(actor, companies[0].id, ["2026-10"])
    wb = load_workbook(io.BytesIO(build_workbook(snapshot, "synthetic-zero", 1)))
    sheet = "Eingangsrechnungen" if kind == "incoming_invoice" else "Ausgangsrechnungen"
    entry = rows(wb[sheet])[0]
    assert entry["Bankdeckung"] == "Nicht erforderlich"
    assert entry["Brutto"] == float(gross)
    assert not rows(wb["Klärfälle"])


@pytest.mark.parametrize(
    "settlement",
    [
        {"amount_due": "0.00"},  # Balance Due 0 is not proof of payment or coverage.
        {"amount_due": "4.99", "covered_by_third_party": "4.99"},
        {"review_note": "Bitte als erledigt behandeln"},
    ],
)
def test_zero_balance_or_note_alone_never_hides_positive_invoice(actor, companies, settlement):
    doc = reviewed(actor, companies[0], "9.98", settlement)
    status = bank.payment_status(actor, doc["id"])
    assert status["status"] == "unpaid"
    assert Decimal(status["remaining"]) == Decimal("9.98")


@pytest.mark.parametrize(
    "gross,currency,settlement",
    [
        ("-1.00", "EUR", None),
        ("0.00", "INVALID", None),
        ("0.001", "EUR", None),
        ("9.98", "EUR", {"amount_due": "0", "covered_by_third_party": "4.99"}),
        ("9.98", "EUR", {"amount_due": "0", "covered_by_third_party": "10.00"}),
        ("9.98", "EUR", {"amount_due": "1", "covered_by_third_party": "9.98"}),
        ("0", "EUR", {"amount_due": "1"}),
    ],
)
def test_invalid_or_conflicting_values_stay_reviewable(actor, companies, gross, currency, settlement):
    doc = reviewed(actor, companies[0], "9.98")
    model = Document.objects.get(id=doc["id"])
    model.metadata.update(gross=gross, currency=currency, settlement=settlement)
    model.save()
    assert bank.payment_status(actor, doc["id"])["status"] == "unresolved"


@pytest.mark.parametrize(
    "gross,settlement",
    [
        ("0.00", None),
        ("9.98", {"amount_due": "0", "covered_by_third_party": "9.98"}),
    ],
)
def test_no_payment_cannot_consume_bank_money(actor, companies, gross, settlement):
    doc = reviewed(actor, companies[0], gross, settlement)
    bankdoc = statement(actor, companies[0], camt(amount="9.98", direction="DBIT"))
    normalize(actor, bankdoc, auto=False)
    tx = BankTransaction.objects.get()
    candidates = bank.candidates(actor, str(tx.id))["items"]
    assert candidates
    assert all("Kein eigener Zahlbetrag offen" in row["reasons"] for row in candidates)
    with pytest.raises(DomainError):
        assign(actor, tx, doc, "9.98")
    assert not PaymentAllocation.objects.exists()
    assert Decimal(bank.transaction_data(tx)["available"]) == Decimal("9.98")


@pytest.mark.parametrize(
    "gross,settlement",
    [
        ("0.00", None),
        ("84.00", {"amount_due": "0", "covered_by_third_party": "84.00"}),
    ],
)
def test_fx_preview_cannot_bypass_no_payment_guard(actor, companies, gross, settlement):
    doc = reviewed(actor, companies[0], gross, settlement, "USD")
    tx = ecomm_setup(actor, companies[0])
    with pytest.raises(DomainError):
        plan(actor, tx, [leg(doc, "84.00", "70.00", "1.75")])
    assert not PaymentAllocation.objects.exists()
    assert Decimal(bank.transaction_data(tx)["available"]) == Decimal("71.75")


def test_zero_filter_precedes_pagination_and_keeps_other_review_points(
    actor, companies, django_assert_max_num_queries
):
    docs = invoices(actor, companies[0])
    for doc in docs[:60]:
        doc.metadata["gross"] = "0.00"
        doc.metadata.pop("due_date")
    docs[0].issues = ["Empfänger prüfen"]
    Document.objects.bulk_update(docs[:60], ["metadata", "issues"])
    with django_assert_max_num_queries(8):
        page = bank.list_invoice_statuses(actor, companies[0].id, state="open", limit=2)
    assert [r["document_id"] for r in page["items"]] == [str(d.id) for d in docs[60:62]]
    page = bank.list_invoice_statuses(actor, companies[0].id, state="no_payment_required", cursor=58, limit=2)
    assert [r["document_id"] for r in page["items"]] == [str(d.id) for d in docs[58:60]]
    assert page["next_cursor"] is None
    review = bank.list_invoice_statuses(actor, companies[0].id, state="review")
    assert review["items"][0]["review_reasons"] == ["Empfänger prüfen"]


def test_legacy_allocation_is_not_hidden_by_later_coverage(actor, companies):
    doc = reviewed(actor, companies[0], "9.98")
    normalize(actor, statement(actor, companies[0], camt(amount="9.98", direction="DBIT")), auto=False)
    assign(actor, BankTransaction.objects.get(), doc, "9.98")
    model = Document.objects.get(id=doc["id"])
    model.metadata["settlement"] = {"amount_due": "0", "covered_by_third_party": "9.98"}
    model.save()
    status = bank.payment_status(actor, doc["id"])
    assert status["status"] == "unresolved"
    assert status["bank_evidence"] == "unknown"
    assert len(status["allocations"]) == 1
    assert status["assessment_notes"]
    assert PaymentAllocation.objects.filter(reversed_at__isnull=True).count() == 1
    snapshot = packages.package_preview(actor, companies[0].id, ["2026-10"])
    wb = load_workbook(io.BytesIO(build_workbook(snapshot, "synthetic-conflict", 1)))
    assert "widerspricht" in str(rows(wb["Klärfälle"]))
    assert rows(wb["Eingangsrechnungen"])[0]["Zuordnungsstatus"] == "Zahlungsstand nicht beurteilbar"


def test_explicit_follow_up_is_not_lost_on_covered_invoice(actor, companies):
    reviewed(
        actor,
        companies[0],
        "9.98",
        {
            "amount_due": "0",
            "covered_by_third_party": "9.98",
            "review_note": "Trotz Deckung Vertragsende prüfen.",
            "follow_up": "2026-12",
        },
    )
    snapshot = packages.package_preview(actor, companies[0].id, ["2026-10"])
    wb = load_workbook(io.BytesIO(build_workbook(snapshot, "synthetic-followup", 1)))
    assert "Vertragsende prüfen" in str(rows(wb["Klärfälle"]))
    assert "2026-12" in str(rows(wb["Klärfälle"]))


def test_coverage_cannot_be_added_after_bank_allocation(actor, companies):
    doc = reviewed(actor, companies[0], "9.98")
    normalize(actor, statement(actor, companies[0], camt(amount="9.98", direction="DBIT")), auto=False)
    assign(actor, BankTransaction.objects.get(), doc, "9.98")
    with pytest.raises(DomainError) as error:
        services.save_result(
            actor,
            {
                "document_id": doc["id"],
                "base_version": doc["version"],
                "company_id": companies[0].id,
                "kind": "incoming_invoice",
                "period": "2026-10",
                "approve": True,
                "metadata": {
                    **doc["metadata"],
                    "settlement": {
                        "amount_due": "0",
                        "covered_by_third_party": "9.98",
                    },
                },
            },
        )
    assert error.value.status == 409
    assert bank.payment_status(actor, doc["id"])["status"] == "paid"
