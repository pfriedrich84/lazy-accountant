"""Synthetic closing references: interest and fees are not duplicate payments."""

import pytest

from accounting import reconciliation as bank
from accounting.auth import DomainError
from accounting.bank_parser import reconciliation_entries
from accounting.models import BankTransaction, BankTransactionSource, Document, PaymentAllocation
from test_reconciliation import assign, camt, invoice, normalize, statement

pytestmark = pytest.mark.django_db


def closing(direction="CRDT", amount="0.31", code="ACMT/MCOP/INTR", detail=False):
    domain, family, subtype = code.split("/")
    xml = (
        f"<BkTxCd><Domn><Cd>{domain}</Cd><Fmly><Cd>{family}</Cd>"
        f"<SubFmlyCd>{subtype}</SubFmlyCd></Fmly></Domn></BkTxCd>"
    ).encode()
    data = camt(amount=amount, direction=direction, reference="CLOSING-SHARED", number="", party="")
    return (
        data.replace(b"<Refs>", xml + b"<Refs>")
        if detail
        else data.replace(b"<NtryDtls>", xml + b"<NtryDtls>")
    )


def combined(first, second):
    entry = second.split(b"<Ntry>")[1].split(b"</Ntry>")[0]
    return first.replace(b"</Stmt>", b"<Ntry>" + entry + b"</Ntry></Stmt>")


def pair():
    return combined(closing(), closing("DBIT", "42.17", "ACMT/MDOP/COMM"))


@pytest.mark.parametrize("detail", [False, True])
def test_parser_preserves_explicit_business_code(detail):
    row = next(reconciliation_entries(closing(detail=detail)))
    assert row["references"]["bank_transaction_code"] == "ACMT/MCOP/INTR"
    assert row["bank_reference"] == "CLOSING-SHARED"


def test_closing_pair_replay_overlap_and_subset_preserve_two_movements(actor, companies):
    doc = statement(actor, companies[0], pair())
    result = normalize(actor, doc, auto=False, key="closing")
    assert len(result["transaction_ids"]) == 2
    assert normalize(actor, doc, auto=False, key="closing") == result
    assert normalize(actor, doc, auto=False)["transaction_ids"] == result["transaction_ids"]
    subset = statement(actor, companies[0], closing().replace(b"<Id>S1", b"<Id>S2"))
    assert normalize(actor, subset, auto=False)["transaction_ids"] == [result["transaction_ids"][0]]
    assert BankTransaction.objects.count() == 2
    assert BankTransactionSource.objects.count() == 3
    assert set(BankTransaction.objects.values_list("bank_reference", flat=True)) == {"CLOSING-SHARED"}
    assert not PaymentAllocation.objects.exists()
    assert set(BankTransactionSource.objects.values_list("parser_version", flat=True)) == {
        "reconciliation-v2"
    }


def test_closing_pair_import_order_is_irrelevant(actor, companies):
    fee = statement(actor, companies[0], closing("DBIT", "42.17", "ACMT/MDOP/COMM"))
    first = normalize(actor, fee, auto=False)["transaction_ids"]
    both = normalize(actor, statement(actor, companies[0], pair()), auto=False)["transaction_ids"]
    assert both[1:] == first
    assert BankTransaction.objects.count() == 2


@pytest.mark.parametrize(
    "second",
    [
        closing(),  # Exact repetition is still ambiguous, not silently deduplicated.
        closing(amount="0.32"),  # Amount is never an identity discriminator.
        closing().replace(b"2026-10-15", b"2026-10-16"),
        closing("DBIT", "42.17", "PMNT/ICDT/ESCT"),
        closing("DBIT", "42.17", "ACMT/MCOP/INTR"),  # Wrong direction for interest.
        camt(reference="CLOSING-SHARED", direction="DBIT"),  # Missing business code.
    ],
)
def test_ambiguous_collisions_roll_back_entire_file(actor, companies, second):
    doc = statement(actor, companies[0], combined(closing(), second))
    with pytest.raises(DomainError) as error:
        normalize(actor, doc, auto=False)
    assert error.value.status == 409
    assert not BankTransaction.objects.exists()
    assert not BankTransactionSource.objects.exists()


@pytest.mark.parametrize(
    "changed",
    [
        closing(amount="0.32"),
        closing().replace(b"2026-10-15", b"2026-10-16"),
        camt(reference="CLOSING-SHARED"),
    ],
)
def test_changed_or_missing_code_in_overlap_does_not_create_new_movement(actor, companies, changed):
    normalize(actor, statement(actor, companies[0], closing()), auto=False)
    with pytest.raises(DomainError):
        normalize(actor, statement(actor, companies[0], changed), auto=False)
    assert BankTransaction.objects.count() == 1
    assert BankTransactionSource.objects.count() == 1


def test_legacy_identity_reused_without_moving_sources_or_allocations(actor, companies):
    doc = statement(actor, companies[0], closing())
    result = normalize(actor, doc, auto=False)
    tx = BankTransaction.objects.get()
    inv = invoice(actor, companies[0], gross="0.31")
    allocation = assign(actor, tx, inv, amount="0.31")
    # Simulate the pre-upgrade projection; the checked original already contains the code.
    BankTransaction.objects.filter(id=tx.id).update(identity=bank.digest([tx.bank_reference]), references={})
    source_id = BankTransactionSource.objects.get().id
    both = normalize(actor, statement(actor, companies[0], pair()), auto=False)
    assert both["transaction_ids"][0] == result["transaction_ids"][0]
    assert BankTransactionSource.objects.get(id=source_id).transaction_id == tx.id
    assert PaymentAllocation.objects.get(id=allocation["allocation_id"]).transaction_id == tx.id
    assert bank.payment_status(actor, inv["id"])["status"] == "paid"
    assert BankTransaction.objects.count() == 2


@pytest.mark.parametrize("security_status", ["error", "infected"])
def test_legacy_source_security_gate_is_not_bypassed(actor, companies, security_status):
    doc = statement(actor, companies[0], closing())
    normalize(actor, doc, auto=False)
    tx = BankTransaction.objects.get()
    BankTransaction.objects.filter(id=tx.id).update(identity=bank.digest([tx.bank_reference]), references={})
    Document.objects.filter(id=doc["id"]).update(security_status=security_status)
    with pytest.raises(DomainError) as error:
        normalize(actor, statement(actor, companies[0], pair()), auto=False)
    assert error.value.status == 423
    assert BankTransaction.objects.count() == 1
    assert BankTransactionSource.objects.count() == 1


@pytest.mark.parametrize("namespace", ["001.02", "001.08"])
def test_closing_pending_to_booked_keeps_identity(actor, companies, namespace):
    data = closing().replace(b"001.08", namespace.encode())
    pending = statement(actor, companies[0], data.replace(b"<Cd>BOOK</Cd>", b"<Cd>PDNG</Cd>"))
    first = normalize(actor, pending, auto=False)
    assert not BankTransaction.objects.get().booked
    booked = normalize(actor, statement(actor, companies[0], data), auto=False)
    assert first["transaction_ids"] == booked["transaction_ids"]
    assert BankTransaction.objects.get().booked


def test_legacy_payment_reference_cannot_be_reclassified_as_closing(actor, companies):
    normalize(actor, statement(actor, companies[0], camt(reference="CLOSING-SHARED")), auto=False)
    with pytest.raises(DomainError, match="Abschlussidentität"):
        normalize(actor, statement(actor, companies[0], pair()), auto=False)
    assert BankTransaction.objects.count() == 1
