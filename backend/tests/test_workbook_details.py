"""Synthetic workbook examples: no live data, customer names, or production IDs."""

import io
import zipfile
from datetime import datetime
from decimal import Decimal
from urllib.parse import unquote

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from accounting import packages, services
from accounting.auth import DomainError
from accounting.models import BankTransaction, Document
from accounting.schemas import Metadata
from accounting.workbook import build_workbook
from test_reconciliation import assign, camt, invoice, normalize, statement

pytestmark = pytest.mark.django_db


def workbook(snapshot):
    return load_workbook(io.BytesIO(build_workbook(snapshot, "synthetic-package", 1)))


def rows(sheet):
    values = list(sheet.iter_rows(min_row=5, values_only=True))
    return [dict(zip(values[0], row)) for row in values[1:]]


def synthetic_document(identifier, kind="incoming_invoice", **metadata):
    return {
        "id": identifier,
        "kind": kind,
        "period": "2026-10",
        "version": 2,
        "archive_path": f"Firma/2026/10/ER/{identifier} # ä.pdf",
        "size": 100,
        "sha256": "a" * 64,
        "account_name": "Depot",
        "account_identifier": "SYNTHETIC-DEPOT",
        "metadata": {
            "date": "2026-10-15",
            "number": identifier,
            "issuer": "Supplier",
            "recipient": "Firma",
            "currency": "EUR",
            "net": "10",
            "tax": "2",
            "gross": "12",
            **metadata,
        },
    }


def base_snapshot(documents):
    return {
        "company": {"name": "Firma", "folder": "Firma"},
        "periods": ["2026-10"],
        "documents": documents,
        "workbook_documents": documents,
        "payments": [],
        "excluded": [],
        "exported_at": "2026-11-21T10:00:00+00:00",
    }


def test_explicit_settlement_facts_not_fake_bank_payments_or_duplicate_receipts():
    third = synthetic_document("third", settlement={"amount_due": "0", "covered_by_third_party": "12"})
    pending = synthetic_document(
        "pending",
        settlement={
            "amount_due": "12",
            "review_note": "Advance review",
            "next_step": "Wait for final statement",
            "follow_up": "Next statement",
        },
    )
    zero = synthetic_document("zero", gross="0", net="0", tax="0")
    receipt = synthetic_document("payment-receipt", kind="receipt", subtype="supplementary_payment_receipt")
    snapshot = base_snapshot([third, pending, zero, receipt])
    snapshot["payments"] = [
        {
            "document_id": d["id"],
            "period": "2026-10",
            "status": "unpaid",
            "paid": "0",
            "remaining": d["metadata"]["gross"],
            "bank_evidence": "none",
            "allocations": [],
        }
        for d in [third, pending, zero]
    ]
    wb = workbook(snapshot)
    invoices = {r["Rechnungsnummer"]: r for r in rows(wb["Eingangsrechnungen"])}
    assert len(invoices) == 3  # supplementary receipt is not a second expense
    assert invoices["third"]["Brutto"] == 12
    assert invoices["third"]["Kostenübernahme Dritte"] == 12
    assert invoices["third"]["Zahlbetrag laut Original"] == 0
    assert invoices["third"]["Zugeordnet (Rechnungswährung)"] == 0
    assert "Durch Dritte" in invoices["third"]["Zuordnungsstatus"]
    assert "Wiedervorlage" in invoices["pending"]["Zuordnungsstatus"]
    assert "Nullbetrag" in invoices["zero"]["Zuordnungsstatus"]
    cases = rows(wb["Klärfälle"])
    assert len(cases) == 1 and cases[0]["Nächster Schritt"] == "Wait for final statement"
    assert len(rows(wb["Inhaltsliste"])) == 4
    assert not rows(wb["Zahlungszuordnungen"])
    for row in wb["Eingangsrechnungen"].iter_rows(min_row=6):
        assert row[4].is_date and isinstance(row[4].value, datetime)
        assert row[12].data_type == "n"
        assert unquote(row[17].hyperlink.target).startswith("2026/10/ER/")
        assert "#" not in row[17].hyperlink.target


def test_security_original_currency_and_withholding_are_not_vat():
    doc = synthetic_document(
        "security",
        kind="security_pdf",
        isin="US04010L1035",
        valuation_date="2026-10-16",
        security_income={
            "quantity": "100",
            "original_currency": "USD",
            "gross": "110",
            "withholding_tax": "11",
            "net": "99",
            "bank_currency": "EUR",
            "bank_net": "90",
            "bank_fee": "1",
            "bank_credit": "89",
            "rate_original_per_bank": "1.1",
        },
    )
    wb = workbook(base_snapshot([doc]))
    row = rows(wb["Wertpapiere"])[0]
    assert row["Brutto Originalwährung"] == 110
    assert row["Quellensteuer Originalwährung"] == 11
    assert row["Netto Originalwährung"] == 99
    assert row["Separate Spesen Bankwährung"] == 1
    assert row["Kontogutschrift Bankwährung"] == 89
    assert row["Originalwährung"] == "USD" and row["Bankwährung"] == "EUR"
    assert row["Kurs Originalwährung je Bankwährung"] == 1.1
    assert not rows(wb["Eingangsrechnungen"])


@pytest.mark.parametrize("field,value", [("amount_due", float("nan")), ("covered_by_third_party", "-1")])
def test_settlement_input_rejects_unsafe_amounts(field, value):
    with pytest.raises(ValidationError):
        Metadata.model_validate({"settlement": {field: value}})


def test_untrusted_text_is_literal_and_zero_is_not_unknown():
    doc = synthetic_document(
        "=HYPERLINK(1)", issuer="=WEBSERVICE(1)", note="@SUM(A1)\x00", settlement={"amount_due": "0"}
    )
    wb = workbook(base_snapshot([doc]))
    row = rows(wb["Eingangsrechnungen"])[0]
    assert row["Zahlbetrag laut Original"] == 0 and row["Kostenübernahme Dritte"] is None
    for sheet in wb:
        assert not any(cell.data_type == "f" for line in sheet for cell in line)
    assert row["Geschäftspartner"] == "=WEBSERVICE(1)"


def test_bank_snapshot_month_filter_company_isolation_and_immutable_context(actor, companies):
    company = companies[0]
    inv = invoice(actor, company)
    source = statement(actor, company)
    normalize(actor, source, auto=False)
    assign(actor, BankTransaction.objects.get(), inv)
    foreign = invoice(actor, companies[1], number="FOREIGN-DO-NOT-EXPORT")
    result = packages.create_package(actor, company.id, ["2026-10", "2026-11"], "multi-workbook")
    p = packages.get_package(actor, result["id"])
    assert len(p.snapshot["bank_transactions"]) == 1
    assert p.snapshot["bank_transactions"][0]["booking_date"] == "2026-10-15"
    assert str(foreign["id"]) not in str(p.snapshot)
    frozen = packages.package_bytes(p)
    with zipfile.ZipFile(io.BytesIO(frozen)) as archive:
        names = [n for n in archive.namelist() if n.endswith(".xlsx")]
        assert names == [f"{company.folder}/Monatsuebersicht_2026-10_bis_2026-11.xlsx"]
        wb = load_workbook(io.BytesIO(archive.read(names[0])))
        assert rows(wb["Bankbewegungen"])[0]["Betrag"] == 120
    BankTransaction.objects.update(remittance="CHANGED AFTER SNAPSHOT")
    assert packages.package_bytes(p) == frozen
    # Even context-only sources must remain protected when a later scan fails.
    Document.objects.filter(id=source["id"]).update(security_status="infected", security_error="test")
    with pytest.raises(DomainError, match="Sicherheitsprüfung"):
        packages.package_bytes(p)
    data = packages.package_data(p, True)
    assert data["snapshot"]["bank_transactions"] == []
    assert data["snapshot"]["payments"] == []


def test_historical_bank_source_in_payment_only_supplement_is_security_protected(actor, companies):
    inv = invoice(actor, companies[0])
    source = statement(actor, companies[0], camt().replace(b"2026-10-15", b"2026-09-15"))
    normalize(actor, source, auto=False)
    before = packages.create_package(actor, companies[0].id, ["2026-10"], "before-historical")
    assign(actor, BankTransaction.objects.get(), inv)
    after = packages.create_package(actor, companies[0].id, ["2026-10"], "after-historical", before["id"])
    p = packages.get_package(actor, after["id"])
    assert not p.items.exists() and p.snapshot["bank_transactions"] == []
    assert len(p.snapshot["allocation_transactions"]) == 1
    assert p.snapshot["allocation_transactions"][0]["booking_date"] == "2026-09-15"
    assert source["id"] in {s["document_id"] for s in p.snapshot["export_sources"]}
    Document.objects.filter(id=source["id"]).update(scanned_sha256="0" * 64)
    with pytest.raises(DomainError, match="Sicherheitsprüfung"):
        packages.package_bytes(p)


def test_new_metadata_is_additive_and_does_not_change_bank_status(actor, companies):
    inv = invoice(actor, companies[0], kind="incoming_invoice")
    saved = services.save_result(
        actor,
        {
            "document_id": inv["id"],
            "base_version": inv["version"],
            "company_id": companies[0].id,
            "period": "2026-10",
            "kind": "incoming_invoice",
            "approve": True,
            "metadata": {
                **inv["metadata"],
                "settlement": {"amount_due": "0", "covered_by_third_party": "120"},
            },
        },
    )
    assert saved["status"] == "ready" and saved["metadata"]["gross"] == "120.00"
    from accounting.reconciliation import payment_status

    assert payment_status(actor, inv["id"])["paid"] == "0"
    assert payment_status(actor, inv["id"])["status"] == "unpaid"
    assert Decimal(saved["metadata"]["settlement"]["covered_by_third_party"]) == 120
