"""Synthetic CAMT fixtures only; no real accounts or production data."""

import io
import json
import zipfile
from decimal import Decimal
from uuid import uuid4

import pytest

from accounting import packages, reconciliation as bank, services
from accounting.auth import DomainError, issue_token, token_actor
from accounting.bank_parser import reconciliation_entries
from accounting.demo import sample_pdf
from accounting.models import (
    Account,
    BankTransaction,
    BankTransactionSource,
    Document,
    Membership,
    PaymentAllocation,
)

pytestmark = pytest.mark.django_db
OWN = "AT611904300234573201"
PARTY = "DE89370400440532013000"


def camt(
    amount="120.00",
    direction="CRDT",
    reference="BANK-1",
    number="INV-001",
    status="BOOK",
    iban=OWN,
    party=PARTY,
    extra="",
    reversal=False,
    txid="",
    end_to_end_id="",
    return_info=False,
):
    side = "Dbtr" if direction == "CRDT" else "Cdtr"
    return f"""<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
    <BkToCstmrStmt><Stmt><Id>S1</Id><Acct><Id><IBAN>{iban}</IBAN></Id><Ccy>EUR</Ccy></Acct>
    <Ntry><Amt Ccy="EUR">{amount}</Amt><CdtDbtInd>{direction}</CdtDbtInd><Sts><Cd>{status}</Cd></Sts>
    <RvslInd>{str(reversal).lower()}</RvslInd><BookgDt><Dt>2026-10-15</Dt></BookgDt>
    <AcctSvcrRef>{reference}</AcctSvcrRef><NtryDtls><TxDtls>
    <Refs><TxId>{txid}</TxId><EndToEndId>{end_to_end_id}</EndToEndId></Refs>
    {"<RtrInf><Rsn><Cd>AC04</Cd></Rsn></RtrInf>" if return_info else ""}
    <RltdPties><{side}><Nm>Acme Customer</Nm></{side}><{side}Acct><Id><IBAN>{party}</IBAN></Id></{side}Acct></RltdPties>
    <RmtInf><Ustrd>{number}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>{extra}
    </Stmt></BkToCstmrStmt></Document>""".encode()


def invoice(actor, company, kind="outgoing_invoice", number="INV-001", gross="120.00", due="2026-10-20"):
    doc = services.ingest(actor, f"{number}-{uuid4()}.pdf", sample_pdf([number, str(uuid4())]), company.id)[
        "document"
    ]
    return services.save_result(
        actor,
        {
            "document_id": doc["id"],
            "base_version": doc["version"],
            "company_id": company.id,
            "kind": kind,
            "period": "2026-10",
            "approve": True,
            "metadata": {
                "issuer": company.name if kind == "outgoing_invoice" else "Acme Customer",
                "recipient": "Acme Customer" if kind == "outgoing_invoice" else company.name,
                "number": number,
                "date": "2026-10-01",
                "due_date": due,
                "currency": "EUR",
                "net": gross,
                "tax": "0",
                "gross": gross,
            },
        },
    )


def statement(actor, company, data=None):
    doc = services.ingest(actor, "bank.xml", data or camt(), company.id)["document"]
    return services.save_result(
        actor,
        {
            "document_id": doc["id"],
            "base_version": doc["version"],
            "company_id": company.id,
            "kind": "bank_camt",
            "account_id": Account.objects.get(company=company, kind="bank").id,
            "period": "2026-10",
            "approve": True,
            "metadata": {"period_start": "2026-10-01", "period_end": "2026-10-31"},
        },
    )


def normalize(actor, doc, auto=True, key=None):
    return bank.reconcile_document(actor, doc["id"], doc["version"], key or str(uuid4()), auto)


def assign(actor, tx, inv, amount="120.00", key=None):
    tx.refresh_from_db()
    return bank.allocate(
        actor,
        str(tx.id),
        inv["id"],
        amount,
        tx.version,
        inv["version"],
        "Original und Referenz manuell geprüft",
        key or str(uuid4()),
    )


@pytest.mark.parametrize("kind,direction", [("outgoing_invoice", "CRDT"), ("incoming_invoice", "DBIT")])
def test_auto_confirm_exact_reference_known_party(actor, companies, kind, direction):
    inv = invoice(actor, companies[0], kind)
    bank.verify_party(actor, companies[0].id, "Acme Customer", PARTY, "Extern unabhängig geprüft")
    result = normalize(actor, statement(actor, companies[0], camt(direction=direction)))
    assert len(result["confirmed"]) == 1
    status = bank.payment_status(actor, inv["id"], "2026-10-21")
    assert status["status"] == "paid" and status["bank_evidence"] == "complete"
    assert status["overdue"] is False
    assert status["allocations"][0]["decision"] == "rule_confirmed"


@pytest.mark.parametrize(
    "change",
    [
        "unverified",
        "amount_only",
        "wrong_party",
        "pending",
        "reversal",
        "duplicate_invoice",
        "duplicate_bank",
    ],
)
def test_auto_refuses_uncertain_cases(actor, companies, change):
    invoice(actor, companies[0])
    if change != "unverified":
        bank.verify_party(actor, companies[0].id, "Acme Customer", PARTY, "Extern geprüft")
    if change == "duplicate_invoice":
        invoice(actor, companies[0])
    args = {}
    if change == "amount_only":
        args["number"] = "General transfer"
    elif change == "wrong_party":
        args["party"] = OWN
    elif change == "pending":
        args["status"] = "PDNG"
    elif change == "reversal":
        args["reversal"] = True
    elif change == "duplicate_bank":
        # Two true bank identities, not a duplicate file.
        second = camt(reference="BANK-2").decode().split("<Ntry>")[1].split("</Ntry>")[0]
        args["extra"] = "<Ntry>" + second + "</Ntry>"
    assert not normalize(actor, statement(actor, companies[0], camt(**args)))["confirmed"]
    assert not PaymentAllocation.objects.exists()


def test_partial_overdue_and_reversal_history(actor, companies):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0]), auto=False)
    tx = BankTransaction.objects.get()
    allocation = assign(actor, tx, inv, "40")
    status = bank.payment_status(actor, inv["id"], "2026-10-21")
    assert status["status"] == "partially_paid" and Decimal(status["remaining"]) == 80
    assert status["overdue"] is True
    assert bank.payment_status(actor, inv["id"], "2026-10-20")["overdue"] is False
    tx.refresh_from_db()
    bank.reverse_allocation(
        actor, allocation["allocation_id"], tx.version, "Rückbuchung im Original geprüft", "reverse"
    )
    status = bank.payment_status(actor, inv["id"], "2026-10-21")
    assert status["status"] == "unpaid" and status["allocations"][0]["reversed_at"]
    # Reprocessing must not undo an explicit reversal.
    bank.verify_party(actor, companies[0].id, "Acme Customer", PARTY, "geprüft")
    assert not normalize(actor, services.document_data(Document.objects.get(kind="bank_camt")))["confirmed"]


def test_no_due_date_is_unknown(actor, companies):
    inv = invoice(actor, companies[0], due=None)
    assert bank.payment_status(actor, inv["id"])["overdue"] is None


def test_overlap_and_original_reimport_do_not_double_count(actor, companies):
    inv = invoice(actor, companies[0])
    bank.verify_party(actor, companies[0].id, "Acme Customer", PARTY, "geprüft")
    doc = statement(actor, companies[0])
    result = normalize(actor, doc, key="same")
    assert normalize(actor, doc, key="same") == result
    overlap = statement(actor, companies[0], camt().replace(b"<Id>S1</Id>", b"<Id>S2</Id>"))
    normalize(actor, overlap)
    assert BankTransaction.objects.count() == 1
    assert BankTransactionSource.objects.count() == 2
    assert PaymentAllocation.objects.count() == 1
    assert Decimal(bank.payment_status(actor, inv["id"])["paid"]) == 120


def test_pending_then_booked_promotes_one_movement(actor, companies):
    pending = statement(actor, companies[0], camt(status="PDNG"))
    normalize(actor, pending)
    assert not BankTransaction.objects.get().booked
    normalize(actor, statement(actor, companies[0], camt(status="BOOK")))
    assert BankTransaction.objects.count() == 1 and BankTransaction.objects.get().booked


def test_unknown_identity_and_conflicting_bank_reference(actor, companies):
    doc = statement(actor, companies[0], camt(reference="NOTPROVIDED"))
    normalize(actor, doc)
    tx = BankTransaction.objects.get()
    assert tx.issues
    inv = invoice(actor, companies[0])
    with pytest.raises(DomainError, match="Ungeklärte"):
        assign(actor, tx, inv)
    normalize(actor, statement(actor, companies[0], camt(reference="KNOWN")))
    with pytest.raises(DomainError, match="Widersprüchliche Bankkennung"):
        normalize(actor, statement(actor, companies[0], camt(reference="KNOWN", amount="130.00")))
    assert BankTransaction.objects.count() == 2


def test_amount_not_overconsumed_and_idempotency_conflicts(actor, companies):
    inv = invoice(actor, companies[0], gross="200.00")
    normalize(actor, statement(actor, companies[0]), auto=False)
    tx = BankTransaction.objects.get()
    initial_version = tx.version
    result = assign(actor, tx, inv, "80", "same-key")
    assert (
        bank.allocate(
            actor,
            str(tx.id),
            inv["id"],
            "80",
            initial_version,
            inv["version"],
            "Original und Referenz manuell geprüft",
            "same-key",
        )
        == result
    )
    with pytest.raises(DomainError) as error:
        bank.allocate(
            actor, str(tx.id), inv["id"], "81", initial_version, inv["version"], "different", "same-key"
        )
    assert error.value.status == 409
    with pytest.raises(DomainError, match="Verfügbarer Betrag"):
        assign(actor, tx, inv, "50")
    with pytest.raises(DomainError, match="Veraltete"):
        bank.allocate(actor, str(tx.id), inv["id"], "20", initial_version, inv["version"], "stale", "stale")
    assert PaymentAllocation.objects.count() == 1


def test_split_payment_and_overpayment_stays_available(actor, companies):
    inv1 = invoice(actor, companies[0], number="A", gross="40.00")
    inv2 = invoice(actor, companies[0], number="B", gross="50.00")
    normalize(actor, statement(actor, companies[0]), auto=False)
    tx = BankTransaction.objects.get()
    assign(actor, tx, inv1, "40")
    assign(actor, tx, inv2, "50")
    tx.refresh_from_db()
    assert Decimal(bank.transaction_data(tx)["available"]) == 30
    assert bank.payment_status(actor, inv1["id"])["status"] == "paid"
    assert bank.payment_status(actor, inv2["id"])["status"] == "paid"


@pytest.mark.parametrize("kind", ["incoming_invoice", "outgoing_invoice"])
def test_manual_direction_and_currency_checks(actor, companies, kind):
    inv = invoice(actor, companies[0], kind)
    normalize(
        actor,
        statement(actor, companies[0], camt(direction="DBIT" if kind == "outgoing_invoice" else "CRDT")),
    )
    tx = BankTransaction.objects.get()
    with pytest.raises(DomainError, match="Richtung oder Währung"):
        assign(actor, tx, inv)


def test_firm_rights_tokens_and_versions(actor, companies):
    first, second = companies
    inv = invoice(actor, second)
    doc = statement(actor, first)
    normalize(actor, doc, auto=False)
    tx = BankTransaction.objects.get()
    with pytest.raises(DomainError, match="Firma"):
        assign(actor, tx, inv)
    raw = issue_token(actor, "read", [first.id], ["read"])["token"]
    read_actor = token_actor(raw)
    assert bank.list_transactions(read_actor, first.id)["items"]
    with pytest.raises(DomainError):
        normalize(read_actor, doc)
    with pytest.raises(DomainError):
        bank.list_transactions(read_actor, second.id)
    Membership.objects.filter(user_id=actor.user_id, company=first).update(can_process=False)
    with pytest.raises(DomainError):
        normalize(actor, doc, key="retry")


def test_cross_tenant_candidate_and_status_do_not_leak(actor, companies):
    first, second = companies
    inv = invoice(actor, second)
    normalize(actor, statement(actor, first), auto=False)
    assert bank.candidates(actor, BankTransaction.objects.get().id)["items"] == []
    raw = issue_token(actor, "limited", [first.id], ["read"])["token"]
    with pytest.raises(DomainError):
        bank.payment_status(token_actor(raw), inv["id"])


def test_financial_document_mutations_blocked(actor, companies):
    inv = invoice(actor, companies[0])
    doc = statement(actor, companies[0])
    normalize(actor, doc, auto=False)
    assign(actor, BankTransaction.objects.get(), inv)
    for original, changes in [
        (inv, {"metadata": {**inv["metadata"], "gross": "121", "net": "121"}}),
        (
            doc,
            {
                "company_id": companies[1].id,
                "account_id": Account.objects.get(company=companies[1], kind="bank").id,
            },
        ),
    ]:
        payload = {
            k: original[k] for k in ["company_id", "kind", "period", "account_id", "category_id", "metadata"]
        }
        payload.update(document_id=original["id"], base_version=original["version"], approve=True)
        payload.update(changes)
        with pytest.raises(DomainError, match="Finanziell referenziertes"):
            services.save_result(actor, payload)


def test_payment_only_package_supplement_and_frozen_original(actor, companies):
    company = companies[0]
    inv = invoice(actor, company)
    normalize(actor, statement(actor, company), auto=False)
    before = packages.create_package(actor, company.id, ["2026-10"], "before")
    original = packages.package_bytes(packages.get_package(actor, before["id"]))
    assign(actor, BankTransaction.objects.get(), inv)
    after = packages.create_package(actor, company.id, ["2026-10"], "after", before["id"])
    snapshot = after["snapshot"]
    assert inv["id"] in snapshot["payment_changes"]
    assert not snapshot["documents"]
    assert snapshot["payments"][0]["status"] == "paid"
    with zipfile.ZipFile(
        io.BytesIO(packages.package_bytes(packages.get_package(actor, after["id"])))
    ) as archive:
        data = json.loads(archive.read(f"{company.folder}/2026/10/Zahlungsstand.json"))
        assert data["payments"][0]["status"] == "paid"
        assert any(n.endswith("Zahlungsstand.xlsx") for n in archive.namelist())
    assert packages.package_bytes(packages.get_package(actor, before["id"])) == original


def test_rest_schema_and_service_parity(client, actor, companies):
    inv = invoice(actor, companies[0])
    doc = statement(actor, companies[0])
    response = client.post(
        "/api/reconciliation/normalize/",
        {
            "document_id": doc["id"],
            "base_version": doc["version"],
            "auto_confirm": False,
            "idempotency_key": "rest",
        },
        format="json",
    )
    assert response.status_code == 200
    tx = BankTransaction.objects.get()
    payload = {
        "transaction_id": str(tx.id),
        "document_id": inv["id"],
        "amount": "40",
        "bank_version": tx.version,
        "document_version": inv["version"],
        "reason": "Manuell geprüft",
        "idempotency_key": "rest-assign",
    }
    assert (
        client.post("/api/reconciliation/allocate/", {**payload, "paid": True}, format="json").status_code
        == 400
    )
    assert client.post("/api/reconciliation/allocate/", payload, format="json").status_code == 200
    response = client.get("/api/reconciliation/status/", {"document_id": inv["id"]})
    assert response.json() == bank.payment_status(actor, inv["id"])
    assert (
        client.post("/api/reconciliation/allocate/", {**payload, "amount": "NaN"}, format="json").status_code
        == 400
    )


def test_verify_party_requires_admin_valid_iban_and_explicit_reason(actor, companies):
    with pytest.raises(DomainError, match="Prüfsumme"):
        bank.verify_party(actor, companies[0].id, "Acme Customer", "DE00370400440532013000", "geprüft")
    Membership.objects.filter(company=companies[0], user_id=actor.user_id).update(can_admin=False)
    with pytest.raises(DomainError):
        bank.verify_party(actor, companies[0].id, "Acme Customer", PARTY, "geprüft")


def test_parser_aggregate_not_counted_twice_and_controls():
    details = "".join(
        f'<TxDtls><Refs><AcctSvcrRef>BANK-{i}</AcctSvcrRef></Refs><AmtDtls><TxAmt><Amt Ccy="EUR">{v}</Amt></TxAmt></AmtDtls></TxDtls>'
        for i, v in enumerate(["40.00", "80.00"])
    )
    original = camt().decode()
    start, end = original.index("<NtryDtls>"), original.index("</NtryDtls>") + len("</NtryDtls>")
    aggregate = (original[:start] + "<NtryDtls>" + details + "</NtryDtls>" + original[end:]).encode()
    entries = list(reconciliation_entries(aggregate))
    assert len(entries) == 2
    assert sum(Decimal(e["amount"]) for e in entries) == 120
    assert all(not e["issues"] for e in entries)
    broken = aggregate.replace(b">80.00<", b">90.00<")
    entries = list(reconciliation_entries(broken))
    assert len(entries) == 1 and entries[0]["issues"]
    assert Decimal(entries[0]["amount"]) == 120


def test_revoked_party_stops_future_automatic_confirmation_without_rewriting_history(actor, companies):
    company = companies[0]
    inv = invoice(actor, company)
    party = bank.verify_party(actor, company.id, "Acme Customer", PARTY, "Unabhängig geprüft")
    bank.revoke_party(actor, company.id, party["id"], "Bankverbindung nicht mehr gültig")
    assert not bank.list_verified_parties(actor, company.id)
    assert not normalize(actor, statement(actor, company))["confirmed"]
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"
    new_party = bank.verify_party(actor, company.id, "Acme Customer", PARTY, "Erneut unabhängig geprüft")
    assert new_party["id"] != party["id"]
    doc = services.document_data(Document.objects.get(kind="bank_camt"))
    assert len(normalize(actor, doc)["confirmed"]) == 1
    bank.revoke_party(actor, company.id, new_party["id"], "Künftige Automatik sperren")
    # Trust revocation is not a bank reversal. Keep the original financial history.
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"
    assert PaymentAllocation.objects.get().evidence["verified_party_ids"] == [new_party["id"]]


def test_replay_rechecks_rights_and_does_not_duplicate_effect(actor, companies):
    company = companies[0]
    inv = invoice(actor, company)
    normalize(actor, statement(actor, company), auto=False)
    tx = BankTransaction.objects.get()
    key = "authorized-once"
    assign(actor, tx, inv, "40", key)
    Membership.objects.filter(company=company, user_id=actor.user_id).update(can_process=False)
    with pytest.raises(DomainError):
        assign(actor, tx, inv, "40", key)
    assert PaymentAllocation.objects.count() == 1


def test_missing_own_account_or_mismatched_account_refused(actor, companies):
    doc = statement(actor, companies[0], camt(iban=PARTY))
    with pytest.raises(DomainError, match="Konto stimmt nicht"):
        normalize(actor, doc)
    assert not BankTransaction.objects.exists()


def test_invoice_version_changed_since_preview(actor, companies):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0]), auto=False)
    tx = BankTransaction.objects.get()
    Document.objects.filter(id=inv["id"]).update(version=inv["version"] + 1)
    with pytest.raises(DomainError, match="Veraltete"):
        assign(actor, tx, inv, "40")
    assert not PaymentAllocation.objects.exists()


@pytest.mark.parametrize("kind,direction", [("outgoing_invoice", "CRDT"), ("incoming_invoice", "DBIT")])
def test_explicit_full_bank_reversal_reopens_invoice(actor, companies, kind, direction):
    inv = invoice(actor, companies[0], kind)
    original_doc = statement(actor, companies[0], camt(direction=direction))
    normalize(actor, original_doc, auto=False)
    original = BankTransaction.objects.get()
    assign(actor, original, inv)
    returned_direction = "DBIT" if direction == "CRDT" else "CRDT"
    returned_doc = statement(actor, companies[0], camt(direction=returned_direction, reversal=True))
    result = normalize(actor, returned_doc, auto=False)
    assert len(result["applied_reversals"]) == 1
    status = bank.payment_status(actor, inv["id"], "2026-10-21")
    assert status["status"] == "unpaid" and status["overdue"]
    assert status["bank_evidence"] == "none"
    returned = BankTransaction.objects.get(reversal=True)
    assert returned.reversal_of_id == original.id
    assert status["allocations"][0]["reversed_by_bank_transaction_id"] == str(returned.id)
    original.refresh_from_db()
    assert Decimal(bank.transaction_data(original)["available"]) == 0
    with pytest.raises(DomainError, match="Ungeklärte"):
        assign(actor, original, inv)
    assert not normalize(actor, returned_doc)["applied_reversals"]
    assert not normalize(actor, original_doc)["confirmed"]
    assert PaymentAllocation.objects.count() == 1


@pytest.mark.parametrize("marker", ["reversal", "return_info"])
def test_transaction_id_reference_can_prove_bank_return(actor, companies, marker):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0], camt(txid="TX-UNIQUE")), auto=False)
    original = BankTransaction.objects.get()
    assign(actor, original, inv)
    result = normalize(
        actor,
        statement(
            actor,
            companies[0],
            camt(
                reference="RETURN-REF",
                direction="DBIT",
                txid="TX-UNIQUE",
                **{marker: True},
            ),
        ),
    )
    assert len(result["applied_reversals"]) == 1
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"


@pytest.mark.parametrize(
    "case", ["amount", "party", "direction", "currency", "pending", "end_to_end_only", "no_marker"]
)
def test_unclear_returns_never_revoke_a_payment(actor, companies, case):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0], camt(txid="TX-1", end_to_end_id="E2E-1")), auto=False)
    assign(actor, BankTransaction.objects.get(), inv)
    kwargs = {"reference": "RETURN-REF", "direction": "DBIT", "txid": "TX-1", "reversal": True}
    if case == "amount":
        kwargs["amount"] = "40.00"
    elif case == "party":
        kwargs["party"] = OWN
    elif case == "direction":
        kwargs["direction"] = "CRDT"
    elif case == "pending":
        kwargs["status"] = "PDNG"
    elif case == "end_to_end_only":
        kwargs.update(txid="", end_to_end_id="E2E-1")
    elif case == "no_marker":
        kwargs["reversal"] = False
    data = camt(**kwargs)
    if case == "currency":
        data = data.replace(b'Ccy="EUR"', b'Ccy="USD"')
    result = normalize(actor, statement(actor, companies[0], data))
    assert not result["applied_reversals"]
    status = bank.payment_status(actor, inv["id"])
    assert status["status"] == "paid"
    assert not PaymentAllocation.objects.get().reversed_at
    if case in {"amount", "party", "direction", "currency"}:
        assert status["bank_evidence"] == "disputed" and status["assessment_notes"]


def test_pending_return_becomes_booked_and_only_then_revokes(actor, companies):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0]), auto=False)
    assign(actor, BankTransaction.objects.get(), inv)
    args = {"direction": "DBIT", "reversal": True}
    pending = statement(actor, companies[0], camt(status="PDNG", **args))
    assert not normalize(actor, pending)["applied_reversals"]
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"
    booked = statement(actor, companies[0], camt(status="BOOK", **args))
    assert len(normalize(actor, booked)["applied_reversals"]) == 1
    assert BankTransaction.objects.count() == 2
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"


def test_return_before_original_prevents_later_payment_match(actor, companies):
    inv = invoice(actor, companies[0])
    bank.verify_party(actor, companies[0].id, "Acme Customer", PARTY, "Unabhängig geprüft")
    returned = statement(actor, companies[0], camt(direction="DBIT", reversal=True))
    assert not normalize(actor, returned)["applied_reversals"]
    original = statement(actor, companies[0])
    result = normalize(actor, original)
    assert len(result["applied_reversals"]) == 1 and not result["confirmed"]
    assert not PaymentAllocation.objects.exists()
    assert bank.payment_status(actor, inv["id"])["status"] == "unpaid"


def test_return_of_split_bank_payment_revokes_all_allocations(actor, companies):
    inv1 = invoice(actor, companies[0], number="SPLIT-1", gross="40.00")
    inv2 = invoice(actor, companies[0], number="SPLIT-2", gross="80.00")
    normalize(actor, statement(actor, companies[0]), auto=False)
    original = BankTransaction.objects.get()
    assign(actor, original, inv1, "40")
    assign(actor, original, inv2, "80")
    normalize(actor, statement(actor, companies[0], camt(direction="DBIT", reversal=True)))
    assert not PaymentAllocation.objects.filter(reversed_at__isnull=True).exists()
    assert bank.payment_status(actor, inv1["id"])["status"] == "unpaid"
    assert bank.payment_status(actor, inv2["id"])["status"] == "unpaid"


def test_reversal_of_one_installment_leaves_other_payment_active(actor, companies):
    inv = invoice(actor, companies[0])
    for ref, amount in [("INSTALLMENT-1", "40.00"), ("INSTALLMENT-2", "80.00")]:
        normalize(actor, statement(actor, companies[0], camt(reference=ref, amount=amount)), auto=False)
        assign(actor, BankTransaction.objects.get(bank_reference=ref), inv, amount)
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"
    normalize(
        actor,
        statement(
            actor,
            companies[0],
            camt(reference="INSTALLMENT-1", amount="40.00", direction="DBIT", reversal=True),
        ),
    )
    status = bank.payment_status(actor, inv["id"], "2026-10-21")
    assert status["status"] == "partially_paid" and status["overdue"]
    assert Decimal(status["paid"]) == 80 and Decimal(status["remaining"]) == 40
    assert PaymentAllocation.objects.filter(reversed_at__isnull=True).count() == 1


def test_multiple_originals_with_same_txid_remain_disputed(actor, companies):
    inv = invoice(actor, companies[0])
    for ref in ["BANK-1", "BANK-2"]:
        normalize(actor, statement(actor, companies[0], camt(reference=ref, txid="REUSED")), auto=False)
    original = BankTransaction.objects.filter(bank_reference="BANK-1").get()
    assign(actor, original, inv)
    result = normalize(
        actor,
        statement(
            actor,
            companies[0],
            camt(
                reference="RETURN",
                direction="DBIT",
                txid="REUSED",
                reversal=True,
            ),
        ),
    )
    assert not result["applied_reversals"]
    assert bank.payment_status(actor, inv["id"])["bank_evidence"] == "disputed"


def test_two_return_movements_with_same_target_do_not_arbitrarily_pick_one(actor, companies):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0], camt(txid="TX-1")), auto=False)
    assign(actor, BankTransaction.objects.get(), inv)
    second = (
        camt(reference="RETURN-2", direction="DBIT", txid="TX-1", reversal=True)
        .decode()
        .split("<Ntry>")[1]
        .split("</Ntry>")[0]
    )
    data = camt(
        reference="RETURN-1",
        direction="DBIT",
        txid="TX-1",
        reversal=True,
        extra="<Ntry>" + second + "</Ntry>",
    )
    result = normalize(actor, statement(actor, companies[0], data))
    assert not result["applied_reversals"]
    assert not PaymentAllocation.objects.get().reversed_at
    assert bank.payment_status(actor, inv["id"])["bank_evidence"] == "disputed"


def test_reversal_cannot_match_other_company_or_account(actor, companies):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0], camt(txid="SAME-ID")), auto=False)
    assign(actor, BankTransaction.objects.get(), inv)
    other = statement(
        actor, companies[1], camt(iban=PARTY, party=OWN, direction="DBIT", txid="SAME-ID", reversal=True)
    )
    assert not normalize(actor, other)["applied_reversals"]
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"


def test_reversal_generates_payment_only_supplement(actor, companies):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0]), auto=False)
    assign(actor, BankTransaction.objects.get(), inv)
    before = packages.create_package(actor, companies[0].id, ["2026-10"], "paid-before-return")
    frozen = packages.package_bytes(packages.get_package(actor, before["id"]))
    normalize(actor, statement(actor, companies[0], camt(direction="DBIT", reversal=True)))
    after = packages.create_package(actor, companies[0].id, ["2026-10"], "after-return", before["id"])
    assert inv["id"] in after["snapshot"]["payment_changes"]
    payment = next(p for p in after["snapshot"]["payments"] if p["document_id"] == inv["id"])
    assert payment["status"] == "unpaid" and payment["allocations"][0]["reversal_sources"]
    assert packages.package_bytes(packages.get_package(actor, before["id"])) == frozen


def test_prior_draft_return_identity_migration_keeps_sources(actor, companies):
    import importlib
    from types import SimpleNamespace

    from django.apps import apps
    from django.db import connection

    doc = statement(actor, companies[0], camt(reference="RETURN", direction="DBIT", reversal=True))
    normalize(actor, doc)
    observed = BankTransaction.objects.get()
    BankTransaction.objects.filter(id=observed.id).update(identity=bank.digest(["RETURN"]))
    migration = importlib.import_module("accounting.migrations.0007_explicit_bank_reversals")
    migration.rekey_existing_reversals(apps, SimpleNamespace(connection=connection))
    normalize(actor, doc)
    assert BankTransaction.objects.count() == 1
    assert BankTransactionSource.objects.get().transaction_id == observed.id


@pytest.mark.django_db(transaction=True)
def test_postgres_parallel_allocations_cannot_double_consume(actor, companies):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks; SQLite does not prove concurrency safety")
    invs = [invoice(actor, companies[0], number=f"PAR-{i}", gross="100.00") for i in range(2)]
    normalize(actor, statement(actor, companies[0]), auto=False)
    tx = BankTransaction.objects.get()
    barrier = Barrier(2)

    def consume(inv):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                bank.allocate(
                    actor, str(tx.id), inv["id"], "80", 1, inv["version"], "Parallel geprüft", str(uuid4())
                )
                return "ok"
            except DomainError as exc:
                return exc.status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(consume, invs))
    assert outcomes.count("ok") == 1 and outcomes.count(409) == 1
    assert sum(PaymentAllocation.objects.values_list("amount", flat=True)) == Decimal("80")


def test_backfill_defaults_to_dry_run_and_apply_is_idempotent(actor, companies):
    from django.core.management import call_command

    invoice(actor, companies[0])
    statement(actor, companies[0])
    args = ["--user-id", str(actor.user_id), "--company-id", str(companies[0].id)]
    output = io.StringIO()
    call_command("reconcile_bank_documents", *args, stdout=output)
    assert json.loads(output.getvalue())["dry_run"]
    assert not BankTransaction.objects.exists()
    call_command("reconcile_bank_documents", *args, "--apply", stdout=io.StringIO())
    call_command("reconcile_bank_documents", *args, "--apply", stdout=io.StringIO())
    assert BankTransaction.objects.count() == 1 and not PaymentAllocation.objects.exists()


def test_parser_keeps_legacy_output_and_rejects_nonfinite():
    from accounting.camt import parse_camt

    assert "entries" in parse_camt(camt())["statements"][0]
    with pytest.raises(ValueError):
        list(reconciliation_entries(camt(amount="NaN")))
