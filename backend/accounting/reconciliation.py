"""Bank-only ER/AR reconciliation. All writers serialize on Company, then rows.

No payment execution, FX, tolerances, write-offs, or inference from an amount alone.
Imported Document IDs are the initial obligation adapter; #9 must reuse these IDs.
"""

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, OuterRef, Prefetch, Q, Subquery, Sum
from django.utils import timezone
from iso4217 import Currency

from . import services, storage
from .auth import DomainError
from .bank_parser import MISSING_IDENTITY, reconciliation_entries
from .models import (
    Account,
    BankTransaction,
    BankTransactionSource,
    Company,
    Document,
    IdempotencyRecord,
    PaymentAllocation,
    VerifiedBankParty,
)

INVOICE_KINDS = {"incoming_invoice", "outgoing_invoice"}
RULE_VERSION = "exact-reference-known-iban-v1"
REVERSAL_RULE = "booked-explicit-full-bank-reversal-v1"


def normalized_name(value):
    return " ".join((value or "").casefold().split())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def money(value, currency):
    try:
        number = Decimal(str(value))
        exponent = Currency(currency).exponent
        if exponent is None or not number.is_finite() or number <= 0 or number >= Decimal("1e14"):
            raise ValueError()
        if number != number.quantize(Decimal(1).scaleb(-exponent)):
            raise ValueError()
        return number
    except ValueError, InvalidOperation, TypeError:
        raise DomainError("Positiver Betrag in gültiger Rechnungswährung erforderlich.") from None


def _require_clean_document(doc):
    if doc.security_status != "clean" or doc.scanned_sha256 != doc.sha256:
        raise DomainError("Finanzquelle sicherheitsgesperrt. Dokumentprüfung erforderlich.", 423)


def _all_bank_sources(tx):
    """One canonical movement may carry additional, explicitly linked observations."""
    duplicates = list(tx.merged_duplicates.all())
    if any(d.company_id != tx.company_id or d.account_id != tx.account_id for d in duplicates):
        raise DomainError("Inkonsistente Firmen-/Kontogrenze der Bankidentität.", 409)
    sources = list(tx.sources.all()) + [
        source for duplicate in duplicates for source in duplicate.sources.all()
    ]
    if any(s.document.company_id != tx.company_id or s.document.account_id != tx.account_id for s in sources):
        raise DomainError("Inkonsistente Firmen-/Kontogrenze der Bankquelle.", 409)
    return sources


def _bank_notes(tx):
    return tx.review_points + tx.identity_review_points


def _require_clean_sources(tx):
    for source in _all_bank_sources(tx):
        _require_clean_document(source.document)


def _invoice(doc):
    _require_clean_document(doc)
    if doc.kind not in INVOICE_KINDS or not doc.company_id or doc.duplicate_of_id or doc.is_excluded:
        raise DomainError("Aktive Ein- oder Ausgangsrechnung erforderlich.")
    currency = doc.metadata.get("currency")
    amount = money(doc.metadata.get("gross"), currency)
    return amount, currency


def _allocated(qs):
    return qs.filter(reversed_at__isnull=True).aggregate(total=Sum("amount"))["total"] or Decimal(0)


def payment_status(actor, document_id, as_of=None):
    doc = services.get_document(actor, document_id)
    return status_for_document(doc, as_of)


def status_for_document(doc, as_of=None):
    _require_clean_document(doc)
    day = date.fromisoformat(as_of) if as_of else timezone.localdate()
    rows = getattr(doc, "_payment_history", None)
    if rows is None:
        rows = list(
            doc.payment_allocations.select_related("transaction", "reversed_by_bank_transaction")
            .prefetch_related(
                "reversed_by_bank_transaction__sources__document",
                "transaction__sources__document",
                "reversed_by_bank_transaction__merged_duplicates__sources__document",
                "transaction__merged_duplicates__sources__document",
            )
            .order_by("created_at", "id")
        )
    for allocation in rows:
        _require_clean_sources(allocation.transaction)
        if allocation.reversed_by_bank_transaction_id:
            _require_clean_sources(allocation.reversed_by_bank_transaction)
    history = [
        {
            "id": str(a.id),
            "transaction_id": str(a.transaction_id),
            "bank_version": a.transaction.version,
            "amount": str(a.amount),
            "decision": a.decision,
            "reason": a.reason,
            "evidence": a.evidence,
            "created_at": a.created_at.isoformat(),
            "actor_id": a.actor_id,
            "reversed_at": a.reversed_at.isoformat() if a.reversed_at else None,
            "reversal_reason": a.reversal_reason,
            "reversed_by_bank_transaction_id": str(a.reversed_by_bank_transaction_id)
            if a.reversed_by_bank_transaction_id
            else None,
            "reversal_sources": [
                {"document_id": str(s.document_id), "locator": s.locator}
                for s in a.reversed_by_bank_transaction.sources.all()
            ]
            if a.reversed_by_bank_transaction_id
            else [],
        }
        for a in rows
    ]
    result = {
        "document_id": str(doc.id),
        "document_version": doc.version,
        "as_of": day.isoformat(),
        "allocations": history,
        "data_note": "Keine Zuordnung bedeutet nicht nachgewiesenes Nichtbezahltsein.",
        "revision": digest(history),
    }
    try:
        gross, currency = _invoice(doc)
    except DomainError:
        return {**result, "status": "unresolved", "overdue": None, "bank_evidence": "unknown"}
    active = [a for a in rows if not a.reversed_at]
    paid = sum((a.amount for a in active), Decimal(0))
    remaining = gross - paid
    due = doc.metadata.get("due_date")
    try:
        due_date = date.fromisoformat(due) if due else None
    except ValueError, TypeError:
        due_date = None
    disputed = any(_bank_notes(a.transaction) for a in active)
    return {
        **result,
        "assessment_notes": sorted({point for a in active for point in _bank_notes(a.transaction)}),
        "status": "paid" if remaining <= 0 else "partially_paid" if paid else "unpaid",
        "currency": currency,
        "gross": str(gross),
        "paid": str(paid),
        "remaining": str(remaining),
        "due_date": due_date.isoformat() if due_date else None,
        "overdue": remaining > 0 and due_date < day if due_date else None,
        "bank_evidence": "disputed"
        if disputed
        else "complete"
        if remaining == 0 and active
        else "partial"
        if active
        else "none",
        "assessment": "bank-backed-not-final-legal-settlement",
    }


def transaction_data(tx):
    _require_clean_sources(tx)
    used = getattr(tx, "_active_amount", None)
    if used is None:
        used = _allocated(tx.allocations)
    if hasattr(tx, "_bank_reversal_id"):
        linked_reversal_id = tx._bank_reversal_id
    else:
        linked_reversal_id = (
            BankTransaction.objects.filter(reversal_of=tx).values_list("id", flat=True).first()
        )
    resolution = getattr(tx, "identity_resolution", None)
    return {
        "id": str(tx.id),
        "version": tx.version,
        "merged_into_id": str(tx.merged_into_id) if tx.merged_into_id else None,
        "canonical_version": tx.merged_into.version if tx.merged_into_id else tx.version,
        "identity_review_points": tx.identity_review_points,
        "identity_resolution": {
            "id": resolution.id,
            "actor_id": resolution.actor_id,
            "reason": resolution.reason,
            "created_at": resolution.created_at.isoformat(),
            "disputed_at": resolution.disputed_at.isoformat() if resolution.disputed_at else None,
            "dispute_reason": resolution.dispute_reason,
        }
        if resolution
        else None,
        "account_id": tx.account_id,
        "amount": str(tx.amount),
        "available": str(
            Decimal(0) if tx.reversal or linked_reversal_id or tx.merged_into_id else tx.amount - used
        ),
        "currency": tx.currency,
        "direction": tx.direction,
        "booking_date": str(tx.booking_date) if tx.booking_date else None,
        "party_name": tx.party_name,
        "party_iban": tx.party_iban,
        "remittance": tx.remittance,
        "bank_reference": tx.bank_reference,
        "references": tx.references,
        "reversal_of_id": str(tx.reversal_of_id) if tx.reversal_of_id else None,
        "reversed_by_id": str(linked_reversal_id) if linked_reversal_id else None,
        "reversal_applied_at": tx.reversal_applied_at.isoformat() if tx.reversal_applied_at else None,
        "booked": tx.booked,
        "reversal": tx.reversal,
        "original_issues": tx.issues,
        "issues": [point for point in tx.issues if not (tx.merged_into_id and point == MISSING_IDENTITY)]
        + _bank_notes(tx),
        "sources": [
            {
                "document_id": s.document_id,
                "observation_transaction_id": str(s.transaction_id),
                "document_version": s.document_version,
                "locator": s.locator,
                "parser_version": s.parser_version,
            }
            for s in _all_bank_sources(tx)
        ],
    }


def _list_options(cursor, limit, search):
    try:
        cursor, limit = int(cursor), int(limit)
    except ValueError, TypeError:
        raise DomainError("Ungültige Seitengröße/Position.") from None
    if cursor < 0 or not 1 <= limit <= 100:
        raise DomainError("Ungültige Seitengröße/Position.")
    if not isinstance(search, str) or len(search) > 200:
        raise DomainError("Suchtext darf höchstens 200 Zeichen enthalten.")
    return cursor, limit, search.strip()


def _filtered_page(rows, matches, cursor, limit):
    # Project financial predicates before pagination. Never filter a pre-sliced page.
    # Iterator/prefetch batches bound memory even when many earlier rows do not match.
    items, skipped = [], 0
    for row in rows:
        if not matches(row):
            continue
        if skipped < cursor:
            skipped += 1
            continue
        items.append(row)
        if len(items) > limit:
            break
    return {"items": items[:limit], "next_cursor": cursor + limit if len(items) > limit else None}


def list_transactions(
    actor, company_id, cursor=0, limit=50, *, state="all", account_id=None, direction=None, search=""
):
    actor.require(company_id)
    cursor, limit, search = _list_options(cursor, limit, search)
    if state not in {"all", "open", "unallocated", "review", "pending", "reversed", "merged"}:
        raise DomainError("Unbekannter Bankbewegungsfilter.")
    if direction not in {None, "CRDT", "DBIT"}:
        raise DomainError("Richtung muss CRDT oder DBIT sein.")
    qs = BankTransaction.objects.filter(company_id=company_id)
    if account_id is not None:
        try:
            account_id = int(account_id)
        except ValueError, TypeError:
            raise DomainError("Ungültiges Bankkonto.") from None
        if not Account.objects.filter(id=account_id, company_id=company_id, kind="bank").exists():
            raise DomainError("Bankkonto nicht gefunden.", 404)
        qs = qs.filter(account_id=account_id)
    if direction:
        qs = qs.filter(direction=direction)
    if search:
        qs = qs.filter(
            Q(remittance__icontains=search)
            | Q(party_name__icontains=search)
            | Q(party_iban__icontains=search)
            | Q(bank_reference__icontains=search)
        )
    qs = (
        qs.annotate(
            _active_amount=Sum(
                "allocations__amount", filter=Q(allocations__reversed_at__isnull=True), default=Decimal(0)
            ),
            _bank_reversal_id=Subquery(
                BankTransaction.objects.filter(reversal_of=OuterRef("pk")).values("id")[:1]
            ),
        )
        .select_related("merged_into", "identity_resolution")
        .prefetch_related("sources__document", "merged_duplicates__sources__document")
        .order_by("id")
    )

    def project(tx):
        row = transaction_data(tx)
        reasons = list(row["identity_review_points"] if row["merged_into_id"] else row["issues"])
        if not row["booked"] and not row["merged_into_id"]:
            reasons.append("Buchungsstatus ausstehend oder ungeklärt")
        if row["reversal"] and not row["reversal_of_id"]:
            reasons.append("Rückbuchungsbezug ungeklärt")
        if not row["remittance"] and not row["reversal"] and not row["merged_into_id"]:
            reasons.append("Keine Rechnungsreferenz im Verwendungszweck")
        row["review_reasons"] = sorted(set(reasons))
        return row

    def matches(row):
        unallocated = Decimal(row["available"]) > 0
        return (
            state == "all"
            or (state == "open" and (unallocated or row["review_reasons"]))
            or (state == "unallocated" and unallocated)
            or (state == "review" and bool(row["review_reasons"]))
            or (state == "pending" and not row["booked"])
            or (state == "reversed" and bool(row["reversed_by_id"]))
            or (state == "merged" and bool(row["merged_into_id"]))
        )

    return {
        **_filtered_page((project(t) for t in qs.iterator(chunk_size=100)), matches, cursor, limit),
        "filters": {"state": state, "account_id": account_id, "direction": direction, "search": search},
    }


def list_invoice_statuses(
    actor, company_id, cursor=0, limit=50, *, state="all", kind=None, search="", as_of=None
):
    actor.require(company_id)
    cursor, limit, search = _list_options(cursor, limit, search)
    if state not in {"all", "open", "overdue", "unresolved", "review", "unmatched", "paid", "partially_paid"}:
        raise DomainError("Unbekannter Offene-Posten-Filter.")
    if kind is not None and kind not in INVOICE_KINDS:
        raise DomainError("Rechnungsart muss incoming_invoice oder outgoing_invoice sein.")
    try:
        day = date.fromisoformat(as_of) if as_of else timezone.localdate()
    except ValueError, TypeError:
        raise DomainError("Ungültiger Stichtag (YYYY-MM-DD erforderlich).") from None
    qs = Document.objects.filter(
        company_id=company_id,
        kind__in=INVOICE_KINDS,
        duplicate_of__isnull=True,
        is_excluded=False,
        security_status="clean",
        scanned_sha256=F("sha256"),
    )
    if kind:
        qs = qs.filter(kind=kind)
    if search:
        qs = qs.filter(
            Q(original_name__icontains=search)
            | Q(metadata__number__icontains=search)
            | Q(metadata__issuer__icontains=search)
            | Q(metadata__recipient__icontains=search)
        )
    history = (
        PaymentAllocation.objects.select_related("transaction", "reversed_by_bank_transaction")
        .prefetch_related(
            "reversed_by_bank_transaction__sources__document",
            "transaction__sources__document",
            "reversed_by_bank_transaction__merged_duplicates__sources__document",
            "transaction__merged_duplicates__sources__document",
        )
        .order_by("created_at", "id")
    )
    qs = qs.prefetch_related(
        Prefetch("payment_allocations", queryset=history, to_attr="_payment_history")
    ).order_by("id")

    def project(doc):
        row = {
            **status_for_document(doc, day.isoformat()),
            "kind": doc.kind,
            "number": doc.metadata.get("number"),
            "original_name": doc.original_name,
        }
        reasons = list(row.get("assessment_notes", [])) + list(doc.issues)
        if row["status"] == "unresolved":
            reasons.append("Rechnungsbetrag oder Währung ungeklärt")
        if doc.status != "ready":
            reasons.append("Rechnung noch nicht bestätigt")
        try:
            date.fromisoformat(doc.metadata.get("due_date") or "")
        except ValueError, TypeError:
            reasons.append("Fälligkeit ungeklärt")
        row["review_reasons"] = sorted(set(reasons))
        return row

    def matches(row):
        return (
            state == "all"
            or (state == "open" and row["status"] != "paid")
            or (state == "overdue" and row["overdue"] is True)
            or (state == "review" and bool(row["review_reasons"]))
            or (state == "unmatched" and row["status"] == "unpaid")
            or state == row["status"]
        )

    return {
        **_filtered_page((project(d) for d in qs.iterator(chunk_size=100)), matches, cursor, limit),
        "as_of": day.isoformat(),
        "filters": {"state": state, "kind": kind, "search": search},
    }


def _replay(actor, company_id, operation, key, payload):
    if not isinstance(key, str) or not key.strip() or len(key) > 120:
        raise DomainError("Idempotenzschlüssel erforderlich (max. 120 Zeichen).")
    operation = f"bank:{company_id}:{operation}"
    fingerprint = digest(payload)
    record = IdempotencyRecord.objects.filter(actor_id=actor.user_id, operation=operation, key=key).first()
    if record and record.request_hash != fingerprint:
        raise DomainError("Idempotenzschlüssel gehört zu anderer Anfrage.", 409)
    return operation, fingerprint, record.result if record else None


def _record(actor, op, key, fingerprint, result):
    IdempotencyRecord.objects.create(
        actor_id=actor.user_id, operation=op, key=key, request_hash=fingerprint, result=result
    )
    return result


def _lock_company(actor, company_id):
    actor.require(company_id, "process")
    get_user_model().objects.select_for_update().get(id=actor.user_id)
    return Company.objects.select_for_update().get(id=company_id)


def verify_party(actor, company_id, name, iban, reason):
    """Explicit trust configuration; never called automatically during extraction."""
    actor.require(company_id, "admin")
    name = normalized_name(name)
    iban = re.sub(r"\s", "", iban).upper()
    if not name or len(name) > 300 or not reason.strip() or len(reason) > 1000:
        raise DomainError("Name und Begründung erforderlich.")
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", iban):
        raise DomainError("Ungültige IBAN.")
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    if int(numeric) % 97 != 1:
        raise DomainError("IBAN-Prüfsumme ungültig.")
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(id=actor.user_id)
        Company.objects.select_for_update().get(id=company_id)
        obj, _ = VerifiedBankParty.objects.get_or_create(
            company_id=company_id,
            name=name,
            iban=iban,
            revoked_at__isnull=True,
            defaults={"actor_id": actor.user_id, "reason": reason},
        )
    return {"id": obj.id, "name": obj.name, "iban": obj.iban}


def list_verified_parties(actor, company_id):
    actor.require(company_id)
    return list(
        VerifiedBankParty.objects.filter(company_id=company_id, revoked_at__isnull=True)
        .order_by("id")
        .values("id", "name", "iban", "reason")
    )


def revoke_party(actor, company_id, party_id, reason):
    actor.require(company_id, "admin")
    if not reason.strip() or len(reason) > 1000:
        raise DomainError("Begründung erforderlich (max. 1000 Zeichen).")
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(id=actor.user_id)
        Company.objects.select_for_update().get(id=company_id)
        party = VerifiedBankParty.objects.filter(id=party_id, company_id=company_id).first()
        if not party:
            raise DomainError("Bankdatenfreigabe nicht gefunden.", 404)
        if not party.revoked_at:
            party.revoked_at = timezone.now()
            party.revoked_by_id = actor.user_id
            party.revocation_reason = reason
            party.save(update_fields=["revoked_at", "revoked_by", "revocation_reason"])
        return {"id": party.id, "revoked": True}


def _apply_bank_reversals(actor, company_id):
    """A full, explicit bank cancellation invalidates the original, never spends the return.

    Called under the Company lock. Amount/name/invoice number/EndToEndId alone
    never establish a reversal relationship. Resolve before matching new payments.
    """
    transactions = list(
        BankTransaction.objects.select_for_update()
        .filter(company_id=company_id, merged_into__isnull=True)
        .prefetch_related("sources__document", "merged_duplicates__sources__document")
        .order_by("id")
    )
    for movement in transactions:
        _require_clean_sources(movement)
    originals = [t for t in transactions if not t.reversal and not t.merged_into_id]
    reviews = {t.id: [] for t in transactions}
    applied = []
    already_reversed = {t.reversal_of_id for t in transactions if t.reversal_of_id}
    unlinked = [t for t in transactions if t.reversal and not t.reversal_of_id]

    def referenced_originals(returned):
        same_account = [t for t in originals if t.account_id == returned.account_id]
        direct = [
            t for t in same_account if returned.bank_reference and t.bank_reference == returned.bank_reference
        ]
        txid = returned.references.get("transaction_id")
        return direct, direct or [
            t for t in same_account if txid and t.references.get("transaction_id") == txid
        ]

    proposals = {t.id: referenced_originals(t) for t in unlinked}
    for returned in unlinked:
        points = reviews[returned.id]
        if not returned.booked or returned.issues:
            points.append("Rückbuchungsquelle nicht eindeutig gebucht/identifiziert")
            continue
        direct, matches = proposals[returned.id]
        if len(matches) != 1:
            points.append("Kein eindeutiger Originalbezug der Rückbuchung (Bankreferenz/TxId erforderlich)")
            for original in matches:
                reviews[original.id].append(f"Mehrdeutige mögliche Rückbuchung {returned.id}")
            continue
        original = matches[0]
        problem = None
        if (
            sum(
                any(o.id == original.id for o in proposals[t.id][1])
                for t in unlinked
                if t.booked and not t.issues
            )
            > 1
        ):
            problem = "Mehrere Rückbuchungsbewegungen mit demselben Originalbezug"
        elif original.id in already_reversed:
            problem = "Originalbewegung bereits vollständig rückgebucht"
        elif not original.booked or original.issues:
            problem = "Originalbewegung nicht eindeutig gebucht/identifiziert"
        elif returned.direction == original.direction or returned.currency != original.currency:
            problem = "Rückbuchungsrichtung oder Währung widerspricht dem Original"
        elif returned.amount != original.amount:
            problem = "Teil-/abweichender Rückbuchungsbetrag: manuelle Prüfung erforderlich"
        elif not direct and (not returned.party_iban or returned.party_iban != original.party_iban):
            problem = "TxId-Bezug ohne übereinstimmendes Gegenkonto"
        elif returned.party_iban and original.party_iban and returned.party_iban != original.party_iban:
            problem = "Widersprüchliches Gegenkonto der Rückbuchung"
        elif (
            returned.party_name
            and original.party_name
            and normalized_name(returned.party_name) != normalized_name(original.party_name)
        ):
            problem = "Widersprüchliche Gegenpartei der Rückbuchung"
        elif (
            not returned.booking_date
            or not original.booking_date
            or returned.booking_date < original.booking_date
        ):
            problem = "Rückbuchungsdatum ungeklärt oder vor Originalbuchung"
        if problem:
            points.append(problem)
            reviews[original.id].append(f"Mögliche Rückbuchung {returned.id}: {problem}")
            continue
        now = timezone.now()
        # Each allocation retains its original evidence and the exact reversing source.
        for allocation in original.allocations.filter(reversed_at__isnull=True).order_by("id"):
            allocation.reversed_at = now
            allocation.reversed_by_id = actor.user_id
            allocation.reversal_reason = REVERSAL_RULE
            allocation.reversed_by_bank_transaction = returned
            allocation.save(
                update_fields=[
                    "reversed_at",
                    "reversed_by",
                    "reversal_reason",
                    "reversed_by_bank_transaction",
                ]
            )
        original.version += 1
        original.save(update_fields=["version"])
        returned.reversal_of = original
        returned.reversal_applied_at = now
        returned.reversal_actor_id = actor.user_id
        returned.version += 1
        returned.save(update_fields=["reversal_of", "reversal_applied_at", "reversal_actor", "version"])
        already_reversed.add(original.id)
        applied.append(str(returned.id))
    for tx in transactions:
        points = sorted(set(reviews[tx.id]))
        if tx.review_points != points:
            tx.review_points = points
            tx.version += 1
            tx.save(update_fields=["review_points", "version"])
    return applied


def _candidate_rows(tx):
    _require_clean_sources(tx)
    if tx.merged_into_id or any(s.document.is_excluded for s in _all_bank_sources(tx)):
        return []
    kind = "outgoing_invoice" if tx.direction == "CRDT" else "incoming_invoice"
    docs = Document.objects.filter(
        company_id=tx.company_id,
        kind=kind,
        duplicate_of__isnull=True,
        is_excluded=False,
        security_status="clean",
        scanned_sha256=F("sha256"),
    )
    results = []
    for doc in docs.order_by("id"):
        reference = doc.metadata.get("number") or ""
        # Preserve punctuation and token boundaries; never match invoice 12 inside 123.
        if not reference or not re.search(
            r"(?<!\w)" + re.escape(reference) + r"(?!\w)", tx.remittance, re.IGNORECASE
        ):
            continue
        party = doc.metadata.get("recipient" if kind == "outgoing_invoice" else "issuer")
        known = (
            VerifiedBankParty.objects.filter(
                company_id=tx.company_id,
                name=normalized_name(party),
                iban=tx.party_iban,
                revoked_at__isnull=True,
            ).exists()
            if party and tx.party_iban
            else False
        )
        reasons = []
        try:
            gross, currency = _invoice(doc)
            remaining = gross - _allocated(doc.payment_allocations)
            if currency != tx.currency:
                reasons.append("Andere Währung")
            if remaining != tx.amount or _allocated(tx.allocations):
                reasons.append("Betrag nicht eindeutig vollständig verfügbar")
        except DomainError:
            reasons.append("Rechnungsbetrag/Währung ungeklärt")
        if not known or normalized_name(tx.party_name) != normalized_name(party):
            reasons.append("Gegenpartei/IBAN nicht widerspruchsfrei verifiziert")
        if doc.status != "ready" or doc.issues:
            reasons.append("Rechnung nicht geprüft")
        competing = BankTransaction.objects.filter(
            company_id=tx.company_id,
            direction=tx.direction,
            currency=tx.currency,
            amount=tx.amount,
            booked=True,
            reversal=False,
            merged_into__isnull=True,
        ).exclude(id=tx.id)
        if any(
            not other.issues
            and not _allocated(other.allocations)
            and re.search(r"(?<!\w)" + re.escape(reference) + r"(?!\w)", other.remittance, re.IGNORECASE)
            for other in competing
        ):
            reasons.append("Mehrere Bankbewegungen mit derselben Rechnungsreferenz")
        if (
            tx.party_iban
            and Account.objects.filter(company_id=tx.company_id, identifier=tx.party_iban).exists()
        ):
            reasons.append("Eigenkontobewegung")
        if (
            not tx.booked
            or tx.reversal
            or tx.issues
            or _bank_notes(tx)
            or BankTransaction.objects.filter(reversal_of=tx).exists()
        ):
            reasons.append("Bankquelle nicht eindeutig gebucht/identifiziert")
        # A previously revoked pair must never be silently auto-created again.
        if tx.allocations.filter(document=doc).exists():
            reasons.append("Vorherige Zuordnungsentscheidung vorhanden")
        results.append(
            {
                "document_id": str(doc.id),
                "document_version": doc.version,
                "reference": reference,
                "reasons": reasons,
            }
        )
    if len(results) != 1:
        for row in results:
            row["reasons"].append("Keine eindeutige Rechnungsreferenz im Firmenbestand")
    return results


def candidates(actor, transaction_id):
    tx = BankTransaction.objects.filter(id=transaction_id, company__in=actor.companies()).first()
    if not tx:
        raise DomainError("Bankbewegung nicht gefunden.", 404)
    return {"transaction": transaction_data(tx), "rule_version": RULE_VERSION, "items": _candidate_rows(tx)}


def _allocate(actor, tx, doc, amount, decision, reason):
    _require_clean_document(doc)
    _require_clean_sources(tx)
    if tx.merged_into_id:
        raise DomainError(
            "Beobachtung ist einer kanonischen Bewegung zugeordnet; nicht erneut verbrauchbar.", 409
        )
    if doc.is_excluded or any(s.document.is_excluded for s in _all_bank_sources(tx)):
        raise DomainError("Ausgeschlossene Rechnung/Bankquelle kann keine neue Zahlung belegen.", 409)
    gross, currency = _invoice(doc)
    if currency != tx.currency or tx.direction != ("CRDT" if doc.kind == "outgoing_invoice" else "DBIT"):
        raise DomainError("Richtung oder Währung passt nicht zur Rechnung.")
    if doc.company_id != tx.company_id:
        raise DomainError("Rechnung gehört nicht zur Firma.", 404)
    if (
        not tx.booked
        or tx.reversal
        or tx.issues
        or _bank_notes(tx)
        or BankTransaction.objects.filter(reversal_of=tx).exists()
    ):
        raise DomainError("Ungeklärte/nicht gebuchte Bankbewegung kann keine Zahlung belegen.", 409)
    if amount > tx.amount - _allocated(tx.allocations) or amount > gross - _allocated(
        doc.payment_allocations
    ):
        raise DomainError("Verfügbarer Betrag oder Rechnungsrest inzwischen überschritten.", 409)
    if not reason.strip() or len(reason) > 1000:
        raise DomainError("Begründung erforderlich (max. 1000 Zeichen).")
    allocation = PaymentAllocation.objects.create(
        transaction=tx,
        document=doc,
        amount=amount,
        decision=decision,
        actor_id=actor.user_id,
        reason=reason,
        evidence={
            "bank_version": tx.version,
            "document_version": doc.version,
            "rule_version": RULE_VERSION if decision == "rule_confirmed" else None,
            "source_ids": [s.id for s in _all_bank_sources(tx)],
            "verified_party_ids": list(
                VerifiedBankParty.objects.filter(
                    company_id=tx.company_id,
                    iban=tx.party_iban,
                    revoked_at__isnull=True,
                    name=normalized_name(
                        doc.metadata.get("recipient" if doc.kind == "outgoing_invoice" else "issuer")
                    ),
                ).values_list("id", flat=True)
            ),
        },
    )
    tx.version += 1
    tx.save(update_fields=["version"])
    return allocation


def allocate(
    actor, transaction_id, document_id, amount, bank_version, document_version, reason, idempotency_key
):
    initial = BankTransaction.objects.filter(
        id=transaction_id, company__in=actor.companies("process")
    ).first()
    if not initial:
        raise DomainError("Bankbewegung nicht gefunden.", 404)
    payload = [str(transaction_id), str(document_id), amount, bank_version, document_version, reason]
    with transaction.atomic():
        _lock_company(actor, initial.company_id)
        op, fp, replay = _replay(actor, initial.company_id, "allocate", idempotency_key, payload)
        if replay is not None:
            return replay
        tx = BankTransaction.objects.select_for_update().get(id=initial.id)
        doc = services.get_document(actor, document_id, "process", lock=True)
        if tx.version != bank_version or doc.version != document_version:
            raise DomainError("Veraltete Bank-/Dokumentversion. Neu laden.", 409)
        allocation = _allocate(actor, tx, doc, money(amount, tx.currency), "manual_confirmed", reason)
        return _record(
            actor, op, idempotency_key, fp, {"allocation_id": str(allocation.id), "bank_version": tx.version}
        )


def reverse_allocation(actor, allocation_id, bank_version, reason, idempotency_key):
    allocation = (
        PaymentAllocation.objects.select_related("transaction")
        .filter(id=allocation_id, transaction__company__in=actor.companies("process"))
        .first()
    )
    if not allocation:
        raise DomainError("Zuordnung nicht gefunden.", 404)
    with transaction.atomic():
        _lock_company(actor, allocation.transaction.company_id)
        op, fp, replay = _replay(
            actor,
            allocation.transaction.company_id,
            "reverse",
            idempotency_key,
            [str(allocation_id), bank_version, reason],
        )
        if replay is not None:
            return replay
        tx = BankTransaction.objects.select_for_update().get(id=allocation.transaction_id)
        allocation.refresh_from_db()
        if tx.version != bank_version or allocation.reversed_at:
            raise DomainError("Zuordnung inzwischen geändert.", 409)
        if not reason.strip() or len(reason) > 1000:
            raise DomainError("Begründung erforderlich (max. 1000 Zeichen).")
        allocation.reversed_at = timezone.now()
        allocation.reversed_by_id = actor.user_id
        allocation.reversal_reason = reason
        allocation.save(update_fields=["reversed_at", "reversed_by", "reversal_reason"])
        tx.version += 1
        tx.save(update_fields=["version"])
        return _record(
            actor, op, idempotency_key, fp, {"allocation_id": str(allocation.id), "bank_version": tx.version}
        )


def _closing_code(direction, reversal, references):
    """Only explicit, opposite accounting operations may share a bank reference."""
    code = references.get("bank_transaction_code")
    expected = {"ACMT/MCOP/INTR": "CRDT", "ACMT/MDOP/COMM": "DBIT"}
    return code if not reversal and expected.get(code) == direction else None


def _source_closing_code(tx):
    """Resolve legacy imports from their checked originals, without moving any source."""
    _require_clean_sources(tx)
    codes = set()
    for source in tx.sources.select_related("document"):
        rows = reconciliation_entries(storage.read_original(source.document))
        row = next((r for r in rows if r["locator"] == source.locator), None)
        if not row or any(
            str(row[key]) != str(getattr(tx, key))
            for key in ("bank_reference", "direction", "currency", "booking_date", "value_date")
        ):
            return None
        if Decimal(row["amount"]) != tx.amount:
            return None
        codes.add(_closing_code(row["direction"], row["reversal"], row["references"]))
    return next(iter(codes)) if len(codes) == 1 and None not in codes else None


def _transaction_identity(doc, row, locator):
    reference = row["bank_reference"]
    if not reference:
        return digest([doc.sha256, locator])
    base = digest(["reversal", row["direction"], reference]) if row["reversal"] else digest([reference])
    if row["reversal"]:
        return base  # Keep the separately namespaced reversal workflow unchanged.
    code = _closing_code(row["direction"], row["reversal"], row["references"])
    identity = digest(["account-closing-v1", reference, code]) if code else base
    # Check all prior observations, including overlapping files with missing codes.
    # Never turn a changed amount/date or an ordinary payment into another movement.
    for prior in BankTransaction.objects.filter(
        company_id=doc.company_id,
        account_id=doc.account_id,
        bank_reference=reference,
        reversal=row["reversal"],
    ):
        prior_code = _closing_code(prior.direction, prior.reversal, prior.references)
        if code and not prior_code and prior.identity == base:
            prior_code = _source_closing_code(prior)
        if code and prior_code:
            if prior_code == code:
                identity = prior.identity  # Preserve legacy IDs, allocations and sources.
            continue
        if prior.identity != identity:
            raise DomainError("Widersprüchliche Bankkennung; Abschlussidentität ungeklärt.", 409)
    return identity


def reconcile_document(actor, document_id, base_version, idempotency_key, auto_confirm=True):
    initial = services.get_document(actor, document_id, "process")
    if not initial.company_id:
        raise DomainError("Bankdokument zuerst einer Firma zuordnen.")
    with transaction.atomic():
        _lock_company(actor, initial.company_id)
        op, fp, replay = _replay(
            actor,
            initial.company_id,
            "normalize",
            idempotency_key,
            [str(document_id), base_version, auto_confirm],
        )
        if replay is not None:
            return replay
        doc = services.get_document(actor, document_id, "process", lock=True)
        if doc.company_id != initial.company_id:
            raise DomainError("Firmenzuordnung inzwischen geändert. Neu laden.", 409)
        if doc.version != base_version:
            raise DomainError("Veraltete Dokumentversion.", 409)
        if (
            doc.kind != "bank_camt"
            or not doc.account_id
            or doc.status != "ready"
            or doc.issues
            or doc.duplicate_of_id
            or doc.is_excluded
        ):
            raise DomainError("Geprüftes CAMT-Dokument mit Bankkonto erforderlich.")
        own = doc.account.identifier.replace(" ", "").upper()
        if not own or doc.account.kind != "bank":
            raise DomainError("Bankkonto mit IBAN-Kennung erforderlich.")
        try:
            rows = list(reconciliation_entries(storage.read_original(doc)))
        except (ValueError, ArithmeticError) as exc:
            raise DomainError("CAMT-Abgleich nicht möglich: " + str(exc)) from exc
        ids, confirmed = [], []
        seen_identities = set()
        for row in rows:
            if row.pop("own_iban") != own:
                raise DomainError("CAMT-Konto stimmt nicht mit zugeordnetem Konto überein.")
            money(row["amount"], row["currency"])
            locator = row.pop("locator")
            identity = _transaction_identity(doc, row, locator)
            if identity in seen_identities:
                raise DomainError(
                    "Bankkennung innerhalb der Datei mehrfach vorhanden; Identität ungeklärt.", 409
                )
            seen_identities.add(identity)
            existing_source = BankTransactionSource.objects.filter(document=doc, locator=locator).first()
            tx, created = BankTransaction.objects.get_or_create(
                company_id=doc.company_id,
                account_id=doc.account_id,
                identity=identity,
                defaults=row,
            )
            if not created:
                immutable = [
                    "amount",
                    "currency",
                    "direction",
                    "booking_date",
                    "value_date",
                    "bank_reference",
                    "party_name",
                    "party_iban",
                    "remittance",
                    "reversal",
                    "issues",
                ]
                if any(
                    (Decimal(getattr(tx, key)) != Decimal(row[key]))
                    if key == "amount"
                    else str(getattr(tx, key)) != str(row[key])
                    for key in immutable
                ):
                    raise DomainError(
                        "Widersprüchliche Bankkennung; keine automatische Zusammenführung.", 409
                    )
                if any(k in tx.references and tx.references[k] != v for k, v in row["references"].items()):
                    raise DomainError("Widersprüchliche strukturierte Bankreferenzen.", 409)
                references = {**tx.references, **row["references"]}
                if (row["booked"] and not tx.booked) or references != tx.references:
                    tx.booked = tx.booked or row["booked"]
                    tx.references = references
                    tx.version += 1
                    tx.save(update_fields=["booked", "references", "version"])
            if existing_source and existing_source.transaction_id != tx.id:
                raise DomainError("Bankquelle bereits anders zugeordnet.", 409)
            BankTransactionSource.objects.get_or_create(
                document=doc,
                locator=locator,
                defaults={
                    "transaction": tx,
                    "document_version": doc.version,
                    "parser_version": "reconciliation-v2",
                },
            )
            ids.append(tx.id)
        # Bank cancellations invalidate old evidence even when new invoice auto-matching is disabled.
        applied_reversals = _apply_bank_reversals(actor, doc.company_id)
        # A request may disable matching, but can never bypass a disabled company policy.
        from .bank_state import policy_data

        policy = policy_data(doc.company_id)
        effective_auto_confirm = auto_confirm and policy["enabled"]
        # After normalizing the entire file, matching sees all source conflicts and cancellations first.
        if effective_auto_confirm:
            for tx in BankTransaction.objects.filter(id__in=ids).order_by("id"):
                options = _candidate_rows(tx)
                if len(options) == 1 and not options[0]["reasons"]:
                    target = Document.objects.select_for_update().get(id=options[0]["document_id"])
                    a = _allocate(actor, tx, target, tx.amount, "rule_confirmed", RULE_VERSION)
                    confirmed.append(str(a.id))
        return _record(
            actor,
            op,
            idempotency_key,
            fp,
            {
                "transaction_ids": list(dict.fromkeys(str(i) for i in ids)),
                "confirmed": confirmed,
                "applied_reversals": applied_reversals,
                "auto_confirm_effective": effective_auto_confirm,
                "automation_policy": policy,
            },
        )


def guard_document_change(doc, result):
    """Called under the existing Company lock, before replacing metadata."""
    has_source = BankTransactionSource.objects.filter(document=doc).exists()
    has_allocation = doc.payment_allocations.exists()
    structural = (
        doc.company_id != result.company_id
        or doc.kind != (result.kind or "")
        or doc.account_id != result.account_id
        or str(doc.duplicate_of_id or "") != str(result.duplicate_of or "")
    )
    financial = any(
        str(doc.metadata.get(k)) != str(getattr(result.metadata, k))
        for k in ("gross", "currency", "number", "issuer", "recipient")
    )
    if ((has_source or has_allocation) and structural) or (has_allocation and financial):
        raise DomainError("Finanziell referenziertes Dokument: Korrekturworkflow erforderlich.", 409)
