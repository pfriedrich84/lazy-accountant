"""Synthetic list projections: predicates precede pages and never cross firms."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from accounting import reconciliation as bank
from accounting.auth import DomainError, issue_token, token_actor
from accounting.models import Account, BankTransaction, Document, PaymentAllocation

pytestmark = pytest.mark.django_db


def invoices(actor, company, count=65):
    return Document.objects.bulk_create(
        [
            Document(
                id=UUID(int=n + 1),
                company=company,
                inbox_owner_id=actor.user_id,
                original_name=f"synthetic-{n}.pdf",
                original_path=f"synthetic/{n}.pdf",
                sha256=f"{n:064x}",
                size=1,
                media_type="application/pdf",
                status="ready",
                kind="outgoing_invoice",
                period="2026-10",
                metadata={
                    "number": f"FILTER-{n}",
                    "recipient": "Synthetic Customer",
                    "gross": "120.00",
                    "currency": "EUR",
                    "due_date": "2026-12-01" if n < 60 else "2026-10-01",
                },
            )
            for n in range(count)
        ]
    )


def test_invoice_predicates_precede_pagination_and_use_one_stichtag(
    actor, companies, django_assert_max_num_queries
):
    docs = invoices(actor, companies[0])
    docs[-1].metadata.pop("gross")
    docs[-1].save()
    with django_assert_max_num_queries(8):
        first = bank.list_invoice_statuses(
            actor, companies[0].id, limit=2, state="overdue", as_of="2026-11-01"
        )
    assert [r["document_id"] for r in first["items"]] == [str(d.id) for d in docs[60:62]]
    assert first["next_cursor"] == 2 and first["as_of"] == "2026-11-01"
    second = bank.list_invoice_statuses(
        actor, companies[0].id, cursor=2, limit=2, state="overdue", as_of="2026-11-01"
    )
    assert [r["document_id"] for r in second["items"]] == [str(d.id) for d in docs[62:64]]
    assert second["next_cursor"] is None
    unresolved = bank.list_invoice_statuses(actor, companies[0].id, state="unresolved")
    assert [r["document_id"] for r in unresolved["items"]] == [str(docs[-1].id)]
    assert unresolved["items"][0]["review_reasons"] == ["Rechnungsbetrag oder Währung ungeklärt"]
    assert not bank.list_invoice_statuses(actor, companies[0].id, state="overdue", as_of="2026-10-01")[
        "items"
    ]
    assert not bank.list_invoice_statuses(actor, companies[0].id, kind="incoming_invoice")["items"]
    assert len(bank.list_invoice_statuses(actor, companies[0].id, search="FILTER-64")["items"]) == 1


def movements(company, count=65):
    account = Account.objects.get(company=company, kind="bank")
    return BankTransaction.objects.bulk_create(
        [
            BankTransaction(
                id=UUID(int=n + 1000),
                company=company,
                account=account,
                identity=f"synthetic-filter-{n}",
                amount=Decimal("120"),
                currency="EUR",
                direction="CRDT",
                booked=n < 60,
                party_name="Synthetic Customer",
                remittance=f"FILTER-{n}",
                booking_date=date(2026, 10, 15),
            )
            for n in range(count)
        ]
    )


def test_bank_filters_query_budget_and_allocation_remainder(actor, companies, django_assert_max_num_queries):
    docs = invoices(actor, companies[0], 1)
    txs = movements(companies[0])
    PaymentAllocation.objects.create(
        transaction=txs[0],
        document=docs[0],
        amount=120,
        decision="manual_confirmed",
        actor_id=actor.user_id,
        reason="Synthetic",
    )
    with django_assert_max_num_queries(8):
        result = bank.list_transactions(actor, companies[0].id, state="pending", limit=2)
    assert [r["id"] for r in result["items"]] == [str(t.id) for t in txs[60:62]]
    assert result["next_cursor"] == 2
    assert result["items"][0]["review_reasons"] == ["Buchungsstatus ausstehend oder ungeklärt"]
    assert len(bank.list_transactions(actor, companies[0].id, state="review")["items"]) == 5
    available = bank.list_transactions(actor, companies[0].id, state="unallocated", limit=100)
    assert len(available["items"]) == 64
    assert str(txs[0].id) not in [r["id"] for r in available["items"]]
    assert not bank.list_transactions(actor, companies[0].id, direction="DBIT")["items"]
    assert len(bank.list_transactions(actor, companies[0].id, search="FILTER-64")["items"]) == 1
    foreign = Account.objects.get(company=companies[1], kind="bank")
    with pytest.raises(DomainError) as exc:
        bank.list_transactions(actor, companies[0].id, account_id=foreign.id)
    assert exc.value.status == 404


def test_paid_partial_and_reversal_projections_remain_consistent(
    actor, companies, django_assert_max_num_queries
):
    docs = invoices(actor, companies[0])
    txs = movements(companies[0])
    PaymentAllocation.objects.bulk_create(
        [
            PaymentAllocation(
                transaction=txs[n],
                document=docs[n],
                amount=120 if n < 60 else 40,
                decision="manual_confirmed",
                actor_id=actor.user_id,
                reason="Synthetic",
            )
            for n in range(61)
        ]
    )
    with django_assert_max_num_queries(8):
        result = bank.list_invoice_statuses(actor, companies[0].id, state="open", as_of="2026-11-01")
    assert len(result["items"]) == 5
    partial = result["items"][0]
    assert partial["status"] == "partially_paid" and partial["overdue"]
    assert Decimal(partial["remaining"]) == 80
    assert partial["bank_evidence"] == "partial"
    txs[-1].reversal = True
    txs[-1].reversal_of = txs[-2]
    txs[-1].save()
    returned = bank.list_transactions(actor, companies[0].id, state="reversed")
    assert [r["id"] for r in returned["items"]] == [str(txs[-2].id)]
    assert Decimal(returned["items"][0]["available"]) == 0


def test_rest_filters_same_projection_scope_and_invalid_options(client, actor, companies):
    invoices(actor, companies[0])
    movements(companies[0])
    url = "/api/reconciliation/invoices/"
    options = {"company_id": companies[0].id, "state": "overdue", "as_of": "2026-11-01", "limit": 2}
    assert client.get(url, options).json() == bank.list_invoice_statuses(
        actor, companies[0].id, state="overdue", as_of="2026-11-01", limit=2
    )
    for options in (
        {"state": "invented"},
        {"cursor": "nan"},
        {"limit": 101},
        {"as_of": "yesterday"},
        {"kind": "bank_camt"},
        {"search": "x" * 201},
    ):
        assert client.get(url, {"company_id": companies[0].id, **options}).status_code == 400
    for options in ({"state": "overdue"}, {"direction": "in"}, {"account_id": "nan"}):
        assert (
            client.get(
                "/api/reconciliation/transactions/", {"company_id": companies[0].id, **options}
            ).status_code
            == 400
        )
    restricted = token_actor(issue_token(actor, "filters", [companies[1].id], ["read"])["token"])
    with pytest.raises(DomainError):
        bank.list_invoice_statuses(restricted, companies[0].id, search="FILTER")
    assert bank.list_invoice_statuses(restricted, companies[1].id, search="FILTER")["items"] == []
