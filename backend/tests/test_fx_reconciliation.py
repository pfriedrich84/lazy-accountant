"""Only synthetic FX evidence; never real invoice or bank data."""

from decimal import Decimal
from uuid import uuid4

import pytest

from accounting import fx, reconciliation as bank
from accounting.auth import DomainError
from accounting.models import BankTransaction, Document, PaymentAllocation
from test_reconciliation import camt, invoice, normalize, statement

pytestmark = pytest.mark.django_db
TEXT = "ORIGINAL 60.00 USD; RATE 0.916666666666667 USD/EUR; FEE 1.00 EUR; CARD DATE 2026-10-01"
STRUCTURED = """<AmtDtls><InstdAmt><Amt Ccy="USD">60.00</Amt><CcyXchg>
<SrcCcy>USD</SrcCcy><TrgtCcy>EUR</TrgtCcy><XchgRate>0.916666666666667</XchgRate>
</CcyXchg></InstdAmt></AmtDtls><Chrgs><Rcrd><Amt Ccy="EUR">1.00</Amt></Rcrd></Chrgs>"""


ECOMM_A = "E-COMM       84,00 USD K7   16.04. 09:42FABLEX, LAB. NEW CLOUDPORT 58243 840SPESEN: 1,75  KURS: 1,200000  VOM:14.04.2031"
ECOMM_B = "E-COMM       96,00 USD K7   08.04. 17:36CLOUDLOOMS, LAB NOV VALE 58342 840SPESEN: 2,25  KURS: 1,280000  VOM:07.04.2031"


def ecomm_setup(actor, company, text=ECOMM_A, amount="71.75", fields=None):
    if fields is None:
        fields = (
            f'<AmtDtls><InstdAmt><Amt Ccy="EUR">{amount}</Amt></InstdAmt>'
            f'<TxAmt><Amt Ccy="EUR">{amount}</Amt></TxAmt></AmtDtls>'
        )
    data = camt(amount=amount, direction="DBIT", number=text).replace(b"<Refs>", fields.encode() + b"<Refs>")
    data = data.replace(b"camt.053.001.08", b"camt.053.001.02")
    result = normalize(actor, statement(actor, company, data))
    assert not result["confirmed"]
    return BankTransaction.objects.get(id=result["transaction_ids"][0])


@pytest.mark.parametrize(
    "text,amount,original,principal,fee,rate",
    [
        (ECOMM_A, "71.75", "84.00", "70.00", "1.75", "1.200000"),
        (ECOMM_B, "77.25", "96.00", "75.00", "2.25", "1.280000"),
    ],
)
def test_ecomm_neutral_structures_full_confirmation_and_undo(
    actor, companies, text, amount, original, principal, fee, rate
):
    inv = usd_invoice(actor, companies[0], gross=original)
    tx = ecomm_setup(actor, companies[0], text, amount)
    result = fx.get_evidence(actor, tx.id)
    assert not result["issues"]
    ev = result["items"][0]
    assert ev["method"] == "bank-ecomm-v1"
    assert ev["quote"] == text
    assert text[ev["text_start"] : ev["text_end"]] == text
    assert ev["original_amount"] == original and ev["rate"] == rate
    assert ev["rate_direction"] == "original currency per bank currency"
    assert ev["fee"] == fee and ev["card_date"] == ""
    assert ev["direction_basis"] == "unique rounded amount consistency"
    assert ev["fee_basis"] == "bank currency, included; amount consistency"
    request, preview = plan(actor, tx, [leg(inv, original, principal, fee)])
    assert preview["review_required"]
    assert any("datum" in reason.lower() for reason in preview["legs"][0]["review_reasons"])
    key = str(uuid4())
    saved = confirm(actor, request, preview, key)
    assert confirm(actor, request, preview, key) == saved
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"
    tx.refresh_from_db()
    assert Decimal(bank.transaction_data(tx)["available"]) == 0
    bank.reverse_allocation(actor, saved["allocation_ids"][0], tx.version, "Synthetic undo", str(uuid4()))
    tx.refresh_from_db()
    assert Decimal(bank.transaction_data(tx)["available"]) == Decimal(amount)
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"


def test_ecomm_duplicate_unstructured_nodes_are_ambiguous(actor, companies):
    fields = f"<RmtInf><Ustrd>{TEXT}</Ustrd></RmtInf>"
    tx = ecomm_setup(actor, companies[0], fields=fields)
    result = fx.get_evidence(actor, tx.id)
    assert not result["items"] and result["issues"]


def test_ecomm_rounded_direction_ambiguity_is_rejected(actor, companies):
    text = ECOMM_A.replace("84,00", "0,01").replace("1,75", "0,00").replace("1,200000", "1,000001")
    tx = ecomm_setup(actor, companies[0], text=text, amount="0.01")
    result = fx.get_evidence(actor, tx.id)
    assert not result["items"]
    assert "Mehrdeutige Kursrichtung" in result["issues"][0]["reason"]


def test_ecomm_inverse_cumulative_rounding(actor, companies):
    inv = usd_invoice(actor, companies[0], gross="84.00")
    tx = ecomm_setup(actor, companies[0])
    request, preview = plan(actor, tx, [leg(inv, "1.00", "0.83", "0.00")])
    confirm(actor, request, preview)
    request, preview = plan(actor, tx, [leg(inv, "83.00", "69.17", "1.75")])
    confirm(actor, request, preview)
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"


@pytest.mark.parametrize("fields", ["", '<AmtDtls><InstdAmt><Amt Ccy="EUR">71.75</Amt></InstdAmt></AmtDtls>'])
def test_ecomm_absent_or_neutral_instructed_amount(actor, companies, fields):
    tx = ecomm_setup(actor, companies[0], fields=fields)
    assert fx.get_evidence(actor, tx.id)["items"]


@pytest.mark.parametrize(
    "text,amount",
    [
        (ECOMM_A.replace("SPESEN: 1,75", "SPESEN: 2,75"), "71.75"),
        (ECOMM_A.replace("SPESEN:", "GEBUEHR:"), "71.75"),
        (ECOMM_A.replace("KURS:", "RATE:"), "71.75"),
        (ECOMM_A.replace("1,200000", "0,000000"), "71.75"),
        (ECOMM_A.replace("1,200000", "1,000000"), "85.75"),
        (ECOMM_A.replace("1,200000", "0,500000"), "43.75"),
        (ECOMM_A.replace("16.04.", "31.02."), "71.75"),
        (ECOMM_A.replace("09:42", "25:42"), "71.75"),
        (ECOMM_A.replace("14.04.2031", "31.02.2031"), "71.75"),
        (ECOMM_A.replace("84,00", "84.00"), "71.75"),
        (ECOMM_A.replace("K7   ", "K7  "), "71.75"),
        (ECOMM_A + " " + ECOMM_A, "71.75"),
        (ECOMM_A + " " + TEXT, "71.75"),
        (ECOMM_A + " KURS: 1,300000", "71.75"),
    ],
)
def test_ecomm_invalid_or_ambiguous_text(actor, companies, text, amount):
    tx = ecomm_setup(actor, companies[0], text=text, amount=amount)
    result = fx.get_evidence(actor, tx.id)
    assert not result["items"] and result["issues"]


@pytest.mark.parametrize(
    "fields",
    [
        '<AmtDtls><InstdAmt><Amt Ccy="USD">84.00</Amt></InstdAmt></AmtDtls>',
        '<AmtDtls><InstdAmt><Amt Ccy="EUR">70.00</Amt></InstdAmt></AmtDtls>',
        '<AmtDtls><TxAmt><Amt Ccy="EUR">70.00</Amt></TxAmt></AmtDtls>',
        "<AmtDtls><TxAmt><CcyXchg><SrcCcy>USD</SrcCcy></CcyXchg></TxAmt></AmtDtls>",
        '<AmtDtls><CntrValAmt><Amt Ccy="USD">85.00</Amt></CntrValAmt></AmtDtls>',
        '<Chrgs><Rcrd><Amt Ccy="EUR">9.00</Amt></Rcrd></Chrgs>',
    ],
)
def test_ecomm_cannot_override_structural_fx_or_conflicts(actor, companies, fields):
    tx = ecomm_setup(actor, companies[0], fields=fields)
    result = fx.get_evidence(actor, tx.id)
    assert not result["items"] and result["issues"]


def usd_invoice(actor, company, gross="60.00", number="SYNTHETIC-FX-1", kind="incoming_invoice"):
    inv = invoice(actor, company, kind=kind, gross=gross, number=number)
    doc = Document.objects.get(id=inv["id"])
    doc.metadata["currency"] = "USD"
    doc.save(update_fields=["metadata"])
    return inv


def setup(actor, company, structured=False, text=TEXT, direction="DBIT"):
    inv = usd_invoice(actor, company)
    data = camt(amount="56.00", direction=direction, number=text)
    if structured:
        data = data.replace(b"<Refs>", STRUCTURED.encode() + b"<Refs>")
    result = normalize(actor, statement(actor, company, data))
    assert result["confirmed"] == []
    tx = BankTransaction.objects.get(id=result["transaction_ids"][0])
    return inv, tx


def leg(inv, amount="60.00", principal="55.00", fee="1.00"):
    return {
        "document_id": inv["id"],
        "document_version": inv["version"],
        "amount": amount,
        "bank_principal": principal,
        "fee": fee,
    }


def plan(actor, tx, legs):
    tx.refresh_from_db()
    evidence = fx.get_evidence(actor, tx.id)["items"][0]
    request = {
        "transaction_id": str(tx.id),
        "bank_version": tx.version,
        "evidence_id": evidence["id"],
        "legs": legs,
    }
    return request, fx.preview(actor, **request)


def confirm(actor, request, preview, key=None):
    return fx.confirm(
        actor,
        **request,
        preview_revision=preview["revision"],
        reason="Synthetic merchant, dates, reference, rate, fees and original checked",
        idempotency_key=key or str(uuid4()),
    )


@pytest.mark.parametrize("structured", [False, True])
def test_full_fx_fee_idempotency_and_exact_undo(actor, companies, structured):
    inv, tx = setup(actor, companies[0], structured)
    evidence = fx.get_evidence(actor, tx.id)
    assert not evidence["issues"]
    assert evidence["items"][0]["method"] == ("camt-structured-v1" if structured else "bank-text-v1")
    candidates = bank.candidates(actor, tx.id)["items"]
    assert candidates[0]["document_id"] == inv["id"]
    assert candidates[0]["requires_fx_confirmation"]
    request, preview = plan(actor, tx, [leg(inv)])
    key = str(uuid4())
    result = confirm(actor, request, preview, key)
    assert confirm(actor, request, preview, key) == result
    status = bank.payment_status(actor, inv["id"])
    assert status["status"] == "paid" and status["bank_evidence"] == "complete"
    assert Decimal(status["paid"]) == 60
    assert Decimal(status["allocations"][0]["bank_amount"]) == 56
    assert status["allocations"][0]["evidence"]["fx"]["fee"] == "1.00"
    assert status["allocations"][0]["bank_sources"]
    tx.refresh_from_db()
    assert Decimal(bank.transaction_data(tx)["available"]) == 0
    listed = bank.list_transactions(actor, companies[0].id)["items"]
    assert Decimal(next(t for t in listed if t["id"] == str(tx.id))["available"]) == 0
    bank.reverse_allocation(actor, result["allocation_ids"][0], tx.version, "Synthetic undo", str(uuid4()))
    tx.refresh_from_db()
    assert Decimal(bank.transaction_data(tx)["available"]) == 56
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"
    allocation = PaymentAllocation.objects.get(id=result["allocation_ids"][0])
    assert allocation.amount == 60 and allocation.bank_amount == 56


def test_partial_collective_and_remaining_fee(actor, companies):
    inv, tx = setup(actor, companies[0])
    second = usd_invoice(actor, companies[0], gross="30.00", number="SYNTHETIC-FX-2")
    request, preview = plan(
        actor, tx, [leg(inv, "30.00", "27.50", "0.00"), leg(second, "30.00", "27.50", "1.00")]
    )
    confirm(actor, request, preview)
    assert bank.payment_status(actor, inv["id"])["status"] == "partially_paid"
    assert bank.payment_status(actor, second["id"])["status"] == "paid"
    assert Decimal(preview["remaining_after"]["original_amount"]) == 0
    assert Decimal(preview["remaining_after"]["bank_amount"]) == 0
    tx.refresh_from_db()
    assert Decimal(bank.transaction_data(tx)["available"]) == 0


def test_cumulative_rounding(actor, companies):
    inv, tx = setup(actor, companies[0])
    first, preview = plan(actor, tx, [leg(inv, "1.00", "0.92", "0.00")])
    confirm(actor, first, preview)
    second, preview = plan(actor, tx, [leg(inv, "59.00", "54.08", "1.00")])
    confirm(actor, second, preview)
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"


@pytest.mark.parametrize(
    "text",
    [
        "60 USD merchant only",
        TEXT + " " + TEXT,
        TEXT.replace("FEE 1.00", "FEE 2.00"),
        TEXT.replace("USD/EUR", "EUR/USD"),
        TEXT.replace("2026-10-01", "2026-99-99"),
        TEXT.replace("FEE 1.00 EUR", "FEE 1.00 USD"),
    ],
)
def test_missing_ambiguous_and_inconsistent_evidence(actor, companies, text):
    inv, tx = setup(actor, companies[0], text=text)
    evidence = fx.get_evidence(actor, tx.id)
    assert not evidence["items"] and evidence["issues"]
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"


@pytest.mark.parametrize("text", [TEXT.replace("FEE 1.00", "FEE 9.00"), ECOMM_A])
def test_structured_preferred_over_text(actor, companies, text):
    _, tx = setup(actor, companies[0], structured=True, text=text)
    assert fx.get_evidence(actor, tx.id)["items"][0]["fee"] == "1.00"


@pytest.mark.parametrize(
    "case", ["direction", "company", "version", "fee", "rounding", "overpayment", "security"]
)
def test_preview_rejects_invalid_assignments(actor, companies, case):
    inv, tx = setup(actor, companies[0])
    if case == "direction":
        Document.objects.filter(id=inv["id"]).update(kind="outgoing_invoice")
    row = leg(inv)
    if case == "company":
        row = leg(usd_invoice(actor, companies[1], number="SYNTHETIC-OTHER"))
    if case == "version":
        row["document_version"] += 1
    if case == "fee":
        row["fee"] = "1.01"
    if case == "rounding":
        row["bank_principal"] = "54.99"
    if case == "overpayment":
        Document.objects.filter(id=inv["id"]).update(metadata={"gross": "50.00", "currency": "USD"})
    if case == "security":
        Document.objects.filter(id=inv["id"]).update(security_status="pending")
    with pytest.raises(DomainError):
        plan(actor, tx, [row])
    assert not PaymentAllocation.objects.exists()


def test_ambiguous_merchant_candidates_and_late_invoice_stay_review_required(actor, companies):
    inv, tx = setup(actor, companies[0])
    usd_invoice(actor, companies[0], number="SYNTHETIC-AMBIGUOUS")
    doc = Document.objects.get(id=inv["id"])
    doc.metadata["date"] = "2026-10-20"
    doc.save(update_fields=["metadata"])
    candidates = bank.candidates(actor, tx.id)["items"]
    assert len(candidates) == 2 and all(c["reasons"] for c in candidates)
    request, preview = plan(actor, tx, [leg(inv)])
    assert any("Widerspruch" in reason for reason in preview["legs"][0]["review_reasons"])
    assert not PaymentAllocation.objects.exists()
    assert request["evidence_id"]


def test_text_cannot_override_unexplained_structural_detail_difference(actor, companies):
    inv = usd_invoice(actor, companies[0])
    fields = '<AmtDtls><TxAmt><Amt Ccy="EUR">55.00</Amt></TxAmt></AmtDtls>'
    data = camt(amount="56.00", direction="DBIT", number=TEXT).replace(b"<Refs>", fields.encode() + b"<Refs>")
    result = normalize(actor, statement(actor, companies[0], data))
    tx = BankTransaction.objects.get(id=result["transaction_ids"][0])
    evidence = fx.get_evidence(actor, tx.id)
    assert not evidence["items"] and evidence["issues"]
    with pytest.raises(DomainError, match="FX-Belege fehlen"):
        fx.preview(actor, tx.id, tx.version, "0" * 64, [leg(inv)])


def test_stale_preview_double_consumption_and_idempotency_conflict(actor, companies):
    inv, tx = setup(actor, companies[0])
    request, preview = plan(actor, tx, [leg(inv)])
    key = str(uuid4())
    confirm(actor, request, preview, key)
    with pytest.raises(DomainError):
        confirm(actor, request, preview)
    with pytest.raises(DomainError):
        confirm(actor, {**request, "bank_version": tx.version + 1}, preview, key)
    assert PaymentAllocation.objects.count() == 1


def test_atomic_batch_rollback(actor, companies, monkeypatch):
    inv, tx = setup(actor, companies[0])
    other = usd_invoice(actor, companies[0], "30.00", "SYNTHETIC-FX-2")
    request, preview = plan(
        actor, tx, [leg(inv, "30.00", "27.50", "0.00"), leg(other, "30.00", "27.50", "1.00")]
    )
    original = bank._allocate

    def fail_second(*args, **kwargs):
        if PaymentAllocation.objects.exists():
            raise DomainError("Synthetic conflict", 409)
        return original(*args, **kwargs)

    monkeypatch.setattr(bank, "_allocate", fail_second)
    with pytest.raises(DomainError):
        confirm(actor, request, preview)
    assert not PaymentAllocation.objects.exists()
    tx.refresh_from_db()
    assert tx.version == request["bank_version"]


def test_bank_reversal_retains_both_currency_amounts(actor, companies):
    inv, tx = setup(actor, companies[0])
    request, preview = plan(actor, tx, [leg(inv)])
    result = confirm(actor, request, preview)
    normalize(actor, statement(actor, companies[0], camt(amount="56.00", direction="CRDT", reversal=True)))
    status = bank.payment_status(actor, inv["id"])
    assert status["status"] == "unpaid"
    allocation = PaymentAllocation.objects.get(id=result["allocation_ids"][0])
    assert allocation.reversed_by_bank_transaction_id
    assert allocation.amount == 60 and allocation.bank_amount == 56


def test_fx_snapshot_supplement_is_frozen_and_exports_evidence(actor, companies):
    import io
    import zipfile
    from openpyxl import load_workbook
    from accounting import packages

    company = companies[0]
    inv, tx = setup(actor, company)
    before = packages.create_package(actor, company.id, ["2026-10"], "fx-before")
    frozen = packages.package_bytes(packages.get_package(actor, before["id"]))
    request, preview = plan(actor, tx, [leg(inv)])
    confirm(actor, request, preview)
    after = packages.create_package(actor, company.id, ["2026-10"], "fx-after", before["id"])
    assert inv["id"] in after["snapshot"]["payment_changes"]
    assert after["snapshot"]["payment_schema_version"] == 2
    with zipfile.ZipFile(
        io.BytesIO(packages.package_bytes(packages.get_package(actor, after["id"])))
    ) as archive:
        wb = load_workbook(io.BytesIO(archive.read(f"{company.folder}/Monatsuebersicht_2026-10.xlsx")))
        rows = list(wb["Zahlungszuordnungen"].iter_rows(min_row=5, values_only=True))
        assert rows[1][6] == 60  # invoice USD
        assert rows[1][8] == 55  # EUR principal
        assert rows[1][9] == 1  # separate fee
        assert rows[1][10] == 56  # entire EUR bank debit
        assert rows[1][13] == "Bestätigt"
        assert rows[1][17] == TEXT
        payment = after["snapshot"]["payments"][0]
        assert payment["revision"] == bank.payment_status(actor, inv["id"])["revision"]
    assert packages.package_bytes(packages.get_package(actor, before["id"])) == frozen


@pytest.mark.parametrize("ecomm", [False, True])
def test_rest_fx_preview_confirmation_and_schema(client, actor, companies, ecomm):
    if ecomm:
        inv = usd_invoice(actor, companies[0], gross="84.00")
        tx = ecomm_setup(actor, companies[0])
        row = leg(inv, "84.00", "70.00", "1.75")
    else:
        inv, tx = setup(actor, companies[0])
        row = leg(inv)
    response = client.get("/api/reconciliation/fx-evidence/", {"transaction_id": str(tx.id)})
    assert response.status_code == 200
    request = {
        "transaction_id": str(tx.id),
        "bank_version": tx.version,
        "evidence_id": response.json()["items"][0]["id"],
        "legs": [row],
    }
    response = client.post("/api/reconciliation/fx-preview/", request, format="json")
    assert response.status_code == 200
    payload = {
        **request,
        "preview_revision": response.json()["revision"],
        "reason": "Synthetic sources explicitly checked",
        "idempotency_key": "fx-rest",
    }
    assert (
        client.post("/api/reconciliation/fx-confirm/", {**payload, "paid": True}, format="json").status_code
        == 400
    )
    assert (
        client.post(
            "/api/reconciliation/fx-confirm/", {**payload, "preview_revision": "0" * 64}, format="json"
        ).status_code
        == 409
    )
    result = client.post("/api/reconciliation/fx-confirm/", payload, format="json")
    assert result.status_code == 200
    assert client.post("/api/reconciliation/fx-confirm/", payload, format="json").json() == result.json()


def test_structured_original_transaction_amount_stays_review_required(actor, companies):
    inv = usd_invoice(actor, companies[0])
    # Some CAMT writers use TxAmt in original currency, not settlement currency.
    fields = STRUCTURED.replace("InstdAmt", "TxAmt")
    data = camt(amount="56.00", direction="DBIT", number="no invoice reference").replace(
        b"<Refs>", fields.encode() + b"<Refs>"
    )
    result = normalize(actor, statement(actor, companies[0], data))
    assert not result["confirmed"]
    tx = BankTransaction.objects.get(id=result["transaction_ids"][0])
    assert tx.issues
    request, preview = plan(actor, tx, [leg(inv)])
    confirm(actor, request, preview)
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"


@pytest.mark.django_db(transaction=True)
def test_postgres_parallel_fx_confirmation_cannot_double_consume(actor, companies):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks; SQLite does not prove concurrency safety")
    inv, tx = setup(actor, companies[0])
    second = usd_invoice(actor, companies[0], number="SYNTHETIC-PARALLEL")
    plans = [plan(actor, tx, [leg(doc)]) for doc in (inv, second)]
    barrier = Barrier(2)

    def consume(args):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                confirm(actor, *args)
                return "ok"
            except DomainError as exc:
                return exc.status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(consume, plans))
    assert outcomes.count("ok") == 1 and outcomes.count(409) == 1
    assert PaymentAllocation.objects.count() == 1
    assert PaymentAllocation.objects.get().bank_amount == 56
