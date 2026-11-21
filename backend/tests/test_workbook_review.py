"""Regression coverage for export completeness and review-state preservation."""

import io

import pytest
from openpyxl import load_workbook

from accounting import packages
from accounting.models import Document
from accounting.workbook import build_workbook
from test_reconciliation import invoice
from test_workbook_details import base_snapshot, rows, synthetic_document

pytestmark = pytest.mark.django_db


def render(snapshot):
    return load_workbook(io.BytesIO(build_workbook(snapshot, "synthetic-review", 1)))


def test_standalone_receipt_keeps_financial_values_but_supplement_does_not():
    expense = synthetic_document("standalone", kind="receipt", subtype="Kassenbeleg")
    supplement = synthetic_document("supplement", kind="receipt", subtype="supplementary_payment_receipt")
    wb = render(base_snapshot([expense, supplement]))
    financial = rows(wb["Eingangsrechnungen"])
    assert len(financial) == 1 and financial[0]["Rechnungsnummer"] == "standalone"
    assert financial[0]["Netto"] == 10 and financial[0]["Steuer"] == 2 and financial[0]["Brutto"] == 12
    assert len(rows(wb["Inhaltsliste"])) == 2


@pytest.mark.parametrize("state", ["review", "issues"])
def test_unapproved_invoice_is_only_a_clarification_not_a_financial_row(actor, companies, state):
    doc = invoice(actor, companies[0])
    Document.objects.filter(id=doc["id"]).update(
        status="review" if state == "review" else "ready",
        issues=["Synthetic unconfirmed extraction"],
    )
    preview = packages.package_preview(actor, companies[0].id, ["2026-10"])
    assert preview["documents"] == []
    assert preview["workbook_documents"] == []
    wb = render(preview)
    assert not rows(wb["Ausgangsrechnungen"])
    assert "Synthetic unconfirmed extraction" in str(rows(wb["Klärfälle"]))


def test_disputed_paid_historical_bank_coverage_remains_actionable():
    doc = synthetic_document("paid-but-disputed")
    snapshot = base_snapshot([doc])
    snapshot["payments"] = [
        {
            "document_id": doc["id"],
            "period": "2026-10",
            "status": "paid",
            "paid": "12",
            "remaining": "0",
            "bank_evidence": "disputed",
            "allocations": [],
            "assessment_notes": ["Synthetic bank identity disputed"],
        }
    ]
    wb = render(snapshot)
    assert rows(wb["Eingangsrechnungen"])[0]["Bankdeckung"] == "Strittig"
    cases = rows(wb["Klärfälle"])
    assert len(cases) == 1 and "Synthetic bank identity disputed" in str(cases)


def test_identically_named_accounts_have_distinct_totals():
    snapshot = base_snapshot([])
    snapshot["bank_transactions"] = [
        {
            "id": "one",
            "account_id": 1,
            "account_name": "Bank",
            "account_identifier": "SYNTHETIC-A",
            "currency": "EUR",
            "amount": "12",
            "available": "12",
            "direction": "CRDT",
            "booked": True,
        },
        {
            "id": "two",
            "account_id": 2,
            "account_name": "Bank",
            "account_identifier": "SYNTHETIC-B",
            "currency": "EUR",
            "amount": "24",
            "available": "24",
            "direction": "CRDT",
            "booked": True,
        },
    ]
    overview = rows(render(snapshot)["Übersicht"])
    credits = [r for r in overview if r["Thema"].startswith("Gutschriften")]
    assert len(credits) == 2
    assert {r["Information"] for r in credits} == {12, 24}
    assert "SYNTHETIC-A" in str(credits) and "SYNTHETIC-B" in str(credits)


def test_pdf_only_statement_keeps_account_currency_and_coverage():
    doc = synthetic_document(
        "pdf-statement", kind="bank_pdf", period_start="2026-10-01", period_end="2026-10-31"
    )
    doc.update(account_name="Synthetic operating account", account_identifier="SYNTHETIC-ACCOUNT")
    wb = render(base_snapshot([doc]))
    assert not rows(wb["Bankbewegungen"])
    entry = rows(wb["Inhaltsliste"])[0]
    assert entry["Konto / Depot"] == "Synthetic operating account"
    assert entry["Kennung Konto / Depot"] == "SYNTHETIC-ACCOUNT"
    assert entry["Währung"] == "EUR"
    assert entry["Leistungs-/Auszugsbeginn"].day == 1
    assert entry["Leistungs-/Auszugsende"].day == 31


@pytest.mark.parametrize("kind", ["incoming_credit", "outgoing_cancellation", "receipt", "incoming_invoice"])
def test_explicit_followup_does_not_require_invoice_payment_status(kind):
    doc = synthetic_document(
        "followup",
        kind=kind,
        settlement={
            "review_note": "Synthetic credit clarification",
            "next_step": "Wait for correction",
            "follow_up": "Next month",
        },
    )
    snapshot = base_snapshot([doc])
    if kind == "incoming_invoice":
        snapshot["payments"] = [
            {"document_id": doc["id"], "period": "2026-10", "status": "unpaid", "allocations": []}
        ]
    cases = rows(render(snapshot)["Klärfälle"])
    assert len(cases) == 1
    assert cases[0]["Hinweise"] == "Synthetic credit clarification"
    assert cases[0]["Nächster Schritt"] == "Wait for correction"
    assert cases[0]["Zuständig"] == "Next month"


def test_manually_assigned_categories_survive_in_the_workbook():
    doc = synthetic_document("categorized")
    doc["category_name"] = "Synthetic business category"
    wb = render(base_snapshot([doc]))
    assert rows(wb["Inhaltsliste"])[0]["Kategorie"] == "Synthetic business category"
