"""Bank projections must not bypass #18 quarantine after a later finding."""

import pytest

from accounting import reconciliation as bank
from accounting.auth import DomainError
from accounting.models import BankTransaction, Document
from test_reconciliation import assign, invoice, normalize, statement

pytestmark = pytest.mark.django_db


def test_security_blocked_invoice_not_candidate_or_search_hit(actor, companies):
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0]), auto=False)
    tx = BankTransaction.objects.get()
    Document.objects.filter(id=inv["id"]).update(security_status="infected")
    assert bank.candidates(actor, str(tx.id))["items"] == []
    assert bank.list_invoice_statuses(actor, companies[0].id, search="INV-001")["items"] == []
    for operation in (lambda: bank.payment_status(actor, inv["id"]), lambda: assign(actor, tx, inv)):
        with pytest.raises(DomainError) as exc:
            operation()
        assert exc.value.status == 423


def test_later_bank_source_block_blocks_status_lists_and_new_allocation(client, actor, companies):
    inv = invoice(actor, companies[0])
    doc = statement(actor, companies[0])
    normalize(actor, doc, auto=False)
    tx = BankTransaction.objects.get()
    assign(actor, tx, inv, amount="40")
    Document.objects.filter(id=doc["id"]).update(security_status="error", scanned_sha256="")
    for operation in (
        lambda: bank.payment_status(actor, inv["id"]),
        lambda: bank.list_invoice_statuses(actor, companies[0].id),
        lambda: bank.list_transactions(actor, companies[0].id),
        lambda: bank.candidates(actor, str(tx.id)),
        lambda: assign(actor, tx, inv, amount="40"),
    ):
        with pytest.raises(DomainError) as exc:
            operation()
        assert exc.value.status == 423
    response = client.get("/api/reconciliation/transactions/", {"company_id": companies[0].id})
    assert response.status_code == 423
    assert "Acme Customer" not in str(response.json())
