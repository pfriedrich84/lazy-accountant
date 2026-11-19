"""Synthetic integration of #7 and #10; financial history is never hidden."""

from decimal import Decimal
from uuid import uuid4

import pytest

from accounting import reconciliation as bank, services
from accounting.auth import DomainError
from accounting.models import BankTransaction, PaymentAllocation
from test_reconciliation import PARTY, assign, invoice, normalize, statement

pytestmark = pytest.mark.django_db


def change(actor, doc, excluded):
    return services.change_document_exclusion(
        actor,
        doc["id"],
        {"base_version": doc["version"], "reason": "Synthetische Prüfung", "idempotency_key": str(uuid4())},
        excluded=excluded,
    )["document"]


def test_excluded_invoice_no_candidates_allocation_or_snapshot_then_restore(actor, companies):
    company = companies[0]
    inv = change(actor, invoice(actor, company), True)
    bank.verify_party(actor, company.id, "Acme Customer", PARTY, "Explizit geprüft")
    doc = statement(actor, company)
    normalize(actor, doc)
    tx = BankTransaction.objects.get()
    assert bank.candidates(actor, str(tx.id))["items"] == []
    assert bank.list_invoice_statuses(actor, company.id)["items"] == []
    with pytest.raises(DomainError) as error:
        assign(actor, tx, inv)
    assert error.value.status == 409
    assert not PaymentAllocation.objects.exists()
    inv = change(actor, inv, False)
    assert not PaymentAllocation.objects.exists()
    assign(actor, tx, inv)
    assert Decimal(bank.payment_status(actor, inv["id"])["paid"]) == Decimal("120.00")


def test_excluded_camt_cannot_normalize(actor, companies):
    doc = change(actor, statement(actor, companies[0]), True)
    with pytest.raises(DomainError):
        normalize(actor, doc)
    assert not BankTransaction.objects.exists()
    doc = change(actor, doc, False)
    normalize(actor, doc)
    assert BankTransaction.objects.count() == 1


def test_rest_exclusion_rejects_sources_and_even_reversed_invoice_history(client, actor, companies):
    inv = invoice(actor, companies[0])
    doc = statement(actor, companies[0])
    normalize(actor, doc, auto=False)
    tx = BankTransaction.objects.get()
    assign(actor, tx, inv)
    allocation = PaymentAllocation.objects.get()
    tx.refresh_from_db()
    bank.reverse_allocation(actor, str(allocation.id), tx.version, "Prüfung", "reverse-exclusion")
    for source in (inv, doc):
        response = client.post(
            f"/api/documents/{source['id']}/exclude/",
            {"base_version": source["version"], "reason": "Nichtbeleg?", "idempotency_key": str(uuid4())},
            format="json",
        )
        assert response.status_code == 409
        assert "Korrekturworkflow" in str(response.json())
        assert not services.get_document(actor, source["id"]).is_excluded
    assert PaymentAllocation.objects.get().reversed_at
    assert bank.payment_status(actor, inv["id"])["allocations"]


@pytest.mark.django_db(transaction=True)
def test_postgres_exclusion_racing_allocation_never_hides_payment(actor, companies):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    inv = invoice(actor, companies[0])
    normalize(actor, statement(actor, companies[0]), auto=False)
    tx = BankTransaction.objects.get()
    barrier = Barrier(2)

    def run(excluded):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                if excluded:
                    change(actor, inv, True)
                else:
                    assign(actor, tx, inv)
                return "ok"
            except DomainError as exc:
                return exc.status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, [True, False]))
    assert outcomes.count("ok") == 1 and outcomes.count(409) == 1
    doc = services.get_document(actor, inv["id"])
    assert doc.is_excluded != PaymentAllocation.objects.exists()
