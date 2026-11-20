"""Evidence-only FX reconciliation. No external rates, no automatic confirmation."""

import re
from datetime import date
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext

from defusedxml import ElementTree
from django.db import transaction
from iso4217 import Currency

from . import reconciliation as bank, services, storage
from .auth import DomainError
from .bank_parser import FX_DETAIL_DIFFERENCE
from .models import BankTransaction

VERSION = "bank-fx-v1"
# Deliberately narrow, versioned grammar. Other bank prose remains unresolved.
TEXT = re.compile(
    r"(?<!\w)ORIGINAL (?P<original>[0-9]+\.[0-9]+) (?P<currency>[A-Z]{3}); "
    r"RATE (?P<rate>[0-9]+\.[0-9]+) (?P<src>[A-Z]{3})/(?P<target>[A-Z]{3}); "
    r"FEE (?P<fee>[0-9]+\.[0-9]+) (?P<fee_currency>[A-Z]{3}); "
    r"CARD DATE (?P<card_date>[0-9]{4}-[0-9]{2}-[0-9]{2})(?![\w-])"
)


def rounded(value, currency):
    exponent = Currency(currency).exponent
    if exponent is None:
        raise ValueError("Keine definierte Minor Unit")
    return value.quantize(Decimal(1).scaleb(-exponent), rounding=ROUND_HALF_UP)


def converted(amount, rate, currency):
    # Up to 20 invoice digits and 40 rate digits; no implicit context rounding.
    with localcontext() as context:
        context.prec = 64
        return rounded(amount * rate, currency)


def evidence(tx):
    """Re-read checked originals, with exact XML paths or verbatim text spans."""
    bank._require_clean_sources(tx)
    result, issues = [], []
    for source in bank._all_bank_sources(tx):
        try:
            root = ElementTree.fromstring(
                storage.read_original(source.document),
                forbid_dtd=True,
                forbid_entities=True,
                forbid_external=True,
            )
            ns = {"c": root.tag.split("}")[0].lstrip("{")}
            si, ei, ti = [int(n) for n in re.findall(r":([0-9]+)", source.locator)]
            statements = (
                root.findall(".//c:Stmt", ns) + root.findall(".//c:Rpt", ns) + root.findall(".//c:Ntfctn", ns)
            )
            entry = statements[si].findall("c:Ntry", ns)[ei]
            details = entry.findall("c:NtryDtls/c:TxDtls", ns)
            if len(details) != 1:
                raise ValueError("FX nur für eindeutig einzelne CAMT-Transaktion unterstützt")
            detail = details[ti]

            def node(path):
                return detail.find("/".join("c:" + p for p in path.split("/")), ns)

            def text(path):
                n = node(path)
                return (n.text or "").strip() if n is not None else ""

            original = node("AmtDtls/InstdAmt/Amt")
            original_path = "AmtDtls/InstdAmt/Amt"
            exchange = node("AmtDtls/InstdAmt/CcyXchg")
            exchange_path = "AmtDtls/InstdAmt/CcyXchg"
            if exchange is None:
                exchange = node("AmtDtls/TxAmt/CcyXchg")
                exchange_path = "AmtDtls/TxAmt/CcyXchg"
            if original is None and exchange is not None:
                original = node("AmtDtls/TxAmt/Amt")
                original_path = "AmtDtls/TxAmt/Amt"
            structured = original is not None or exchange is not None
            base = {
                "source_id": source.id,
                "document_id": str(source.document_id),
                "document_version": source.document.version,
                "sha256": source.document.sha256,
                "locator": source.locator,
                "version": VERSION,
            }
            if structured:
                if original is None or exchange is None:
                    raise ValueError("Unvollständige strukturierte FX-Angaben")
                if len(detail.findall("c:AmtDtls/*/c:CcyXchg", ns)) != 1:
                    raise ValueError("Mehrdeutige strukturierte Kurse")
                fees = detail.findall("c:Chrgs/c:Rcrd/c:Amt", ns)
                if not fees:
                    raise ValueError("Gebühren (auch null) nicht separat belegt")
                if any(not Decimal(f.text).is_finite() or Decimal(f.text) < 0 for f in fees):
                    raise ValueError("Ungültige einzelne Gebühr")
                if any(f.get("Ccy") != tx.currency for f in fees):
                    raise ValueError("Gebührenwährung widersprüchlich")
                if text(exchange_path + "/UnitCcy") not in {"", original.get("Ccy")}:
                    raise ValueError("Abweichende Kurseinheit")
                for record in detail.findall("c:Chrgs/c:Rcrd", ns):
                    direction = record.find("c:CdtDbtInd", ns)
                    if direction is not None and direction.text != "DBIT":
                        raise ValueError("Gebühr ist keine Belastung")
                data = {
                    "original": original.text,
                    "currency": original.get("Ccy"),
                    "rate": text(exchange_path + "/XchgRate"),
                    "src": text(exchange_path + "/SrcCcy"),
                    "target": text(exchange_path + "/TrgtCcy"),
                    "fee": str(sum((Decimal(f.text) for f in fees), Decimal(0))),
                    "fee_currency": tx.currency,
                    "card_date": text("RltdDts/TxDtTm")[:10],
                }
                base.update(
                    method="camt-structured-v1",
                    paths=[original_path, exchange_path, "Chrgs/Rcrd/Amt"],
                )
            else:
                spans = []
                for index, n in enumerate(detail.findall("c:RmtInf/c:Ustrd", ns)):
                    spans.extend((index, match) for match in TEXT.finditer(n.text or ""))
                if len(spans) != 1:
                    raise ValueError("Keine eindeutige FX-Textbelegstelle nach bank-fx-v1")
                index, match = spans[0]
                data = match.groupdict()
                base.update(
                    method="bank-text-v1",
                    paths=[f"RmtInf/Ustrd[{index}]"],
                    quote=match.group(0),
                    text_start=match.start(),
                    text_end=match.end(),
                )
            if data["card_date"]:
                date.fromisoformat(data["card_date"])
            original_amount = bank.money(data["original"], data["currency"])
            fee = Decimal(data["fee"])
            rate = Decimal(data["rate"])
            if (
                data["src"] != data["currency"]
                or data["target"] != tx.currency
                or data["fee_currency"] != tx.currency
                or data["currency"] == tx.currency
                or not rate.is_finite()
                or rate <= 0
                or rate >= Decimal("1e14")
                or len(rate.as_tuple().digits) > 40
                or rate.as_tuple().exponent < -40
                or not fee.is_finite()
                or fee < 0
                or fee >= Decimal("1e14")
                or fee != rounded(fee, tx.currency)
            ):
                raise ValueError("Widersprüchliche FX-Währungen/Kurs/Gebühren")
            if tx.direction != "DBIT" and fee:
                raise ValueError("FX-Gebühren auf Gutschriften erfordern ein separates Verfahren")
            if structured:
                detail_amount = node("AmtDtls/TxAmt/Amt")
                if detail_amount is None:
                    detail_amount = node("Amt")
                if detail_amount is not None:
                    observed = (Decimal(detail_amount.text), detail_amount.get("Ccy"))
                    if observed not in {
                        (original_amount, data["currency"]),
                        (tx.amount, tx.currency),
                        (tx.amount - fee, tx.currency),
                    }:
                        raise ValueError("Strukturierter Detailbetrag widerspricht FX-Beleg")
            if converted(original_amount, rate, tx.currency) + fee != tx.amount:
                raise ValueError("Original × belegter Kurs + Gebühren stimmt nicht mit Bankbetrag überein")
            base.update(
                original_amount=str(original_amount),
                original_currency=data["currency"],
                bank_amount=str(tx.amount),
                bank_currency=tx.currency,
                rate=str(rate),
                rate_direction="bank currency per original currency",
                fee=str(fee),
                card_date=data["card_date"],
                rounding="ROUND_HALF_UP to ISO minor unit",
            )
            base["id"] = bank.digest(base)
            result.append(base)
        except (ValueError, DecimalException, TypeError, IndexError, DomainError) as exc:
            issues.append({"source_id": source.id, "locator": source.locator, "reason": str(exc)})
    return {"items": result, "issues": issues}


def _load(actor, transaction_id, permission="read"):
    tx = BankTransaction.objects.filter(id=transaction_id, company__in=actor.companies(permission)).first()
    if not tx:
        raise DomainError("Bankbewegung nicht gefunden.", 404)
    return tx


def _preview(actor, tx, bank_version, evidence_id, legs):
    if tx.version != bank_version:
        raise DomainError("Veraltete Bankversion.", 409)
    bank._require_clean_sources(tx)
    if (
        tx.merged_into_id
        or not tx.booked
        or tx.reversal
        or any(issue != FX_DETAIL_DIFFERENCE for issue in tx.issues)
        or bank._bank_notes(tx)
        or BankTransaction.objects.filter(reversal_of=tx).exists()
        or any(s.document.is_excluded for s in bank._all_bank_sources(tx))
    ):
        raise DomainError("Bankbewegung gesperrt/ungeklärt oder nicht verfügbar.", 409)
    sources = evidence(tx)
    selected = next((e for e in sources["items"] if e["id"] == evidence_id), None)
    if not selected or sources["issues"]:
        raise DomainError("FX-Belege fehlen, sind widersprüchlich oder wurden geändert.", 409)
    if FX_DETAIL_DIFFERENCE in tx.issues and selected["method"] != "camt-structured-v1":
        raise DomainError("Abweichender Detailbetrag benötigt strukturierte FX-Belege.", 409)
    # Differing observations of the same movement must never be silently preferred.
    facts = {(e["original_amount"], e["original_currency"], e["rate"], e["fee"]) for e in sources["items"]}
    if len(facts) != 1:
        raise DomainError("Mehrdeutige FX-Belege.", 409)
    active = list(tx.allocations.filter(reversed_at__isnull=True))
    if any(not a.evidence.get("fx") or a.evidence["fx"]["evidence"]["id"] != evidence_id for a in active):
        raise DomainError("Vorhandene Deckung nutzt andere Belege; zuerst aufheben.", 409)
    original_used = sum((a.amount for a in active), Decimal(0))
    principal_used = sum((Decimal(a.evidence["fx"]["bank_principal"]) for a in active), Decimal(0))
    fee_used = sum((Decimal(a.evidence["fx"]["fee"]) for a in active), Decimal(0))
    rows, seen = [], set()
    for leg in legs:
        doc = services.get_document(actor, leg["document_id"], "process")
        if str(doc.id) in seen:
            raise DomainError("Rechnung in Sammelzuordnung doppelt.")
        seen.add(str(doc.id))
        gross, currency = bank._invoice(doc)
        if doc.company_id != tx.company_id:
            raise DomainError("Rechnung gehört nicht zur Firma.", 404)
        if doc.version != leg["document_version"]:
            raise DomainError("Veraltete Dokumentversion.", 409)
        if tx.direction != ("CRDT" if doc.kind == "outgoing_invoice" else "DBIT"):
            raise DomainError("Richtung passt nicht zur Rechnung.")
        if currency != selected["original_currency"]:
            raise DomainError("Original-Kartenwährung passt nicht zur Rechnung.")
        amount = bank.money(leg["amount"], currency)
        principal = bank.money(leg["bank_principal"], tx.currency)
        fee = Decimal(str(leg["fee"]))
        if not fee.is_finite() or fee < 0 or fee != rounded(fee, tx.currency):
            raise DomainError("Ungültige Gebühr.")
        # Cumulative rounding keeps splits exact, including the final minor unit.
        expected = converted(original_used + amount, Decimal(selected["rate"]), tx.currency) - principal_used
        if principal != expected:
            raise DomainError("Bankdeckung entspricht nicht dem belegten Kurs/Rundungsverfahren.")
        original_used += amount
        principal_used += principal
        fee_used += fee
        if original_used > Decimal(selected["original_amount"]) or fee_used > Decimal(selected["fee"]):
            raise DomainError("Originalbetrag oder belegte Gebühren bereits verbraucht.", 409)
        if amount > gross - bank._allocated(doc.payment_allocations):
            raise DomainError("Rechnungsrest überschritten.", 409)
        party = doc.metadata.get("issuer" if doc.kind == "incoming_invoice" else "recipient")
        invoice_date = doc.metadata.get("date")
        review_reasons = []
        if bank.normalized_name(party) != bank.normalized_name(tx.party_name):
            review_reasons.append("Händlername weicht ab oder fehlt")
        if not invoice_date or not selected["card_date"]:
            review_reasons.append("Rechnungs-/Kartendatum nicht vollständig belegt")
        elif invoice_date > selected["card_date"]:
            review_reasons.append("Rechnung nach Kartenumsatz: zeitlicher Widerspruch prüfen")
        if tx.booking_date and invoice_date and invoice_date > str(tx.booking_date):
            review_reasons.append("Rechnung nach Bankbuchung: zeitlicher Widerspruch prüfen")
        rows.append(
            {
                "document_id": str(doc.id),
                "document_version": doc.version,
                "payment_revision": bank.status_for_document(doc)["revision"],
                "amount": str(amount),
                "invoice_currency": currency,
                "bank_principal": str(principal),
                "fee": str(fee),
                "bank_amount": str(principal + fee),
                "bank_currency": tx.currency,
                "invoice_date": invoice_date,
                "reference": doc.metadata.get("number"),
                "party": party,
                "review_reasons": review_reasons,
            }
        )
    if not rows:
        raise DomainError("Mindestens eine Zuordnung erforderlich.")
    if principal_used + fee_used > tx.amount:
        raise DomainError("Verfügbare Bankdeckung überschritten.", 409)
    result = {
        "version": VERSION,
        "transaction": bank.transaction_data(tx),
        "evidence": selected,
        "legs": rows,
        "remaining_after": {
            "original_amount": str(Decimal(selected["original_amount"]) - original_used),
            "original_currency": selected["original_currency"],
            "bank_principal": str(tx.amount - Decimal(selected["fee"]) - principal_used),
            "fee": str(Decimal(selected["fee"]) - fee_used),
            "bank_amount": str(tx.amount - principal_used - fee_used),
            "bank_currency": tx.currency,
        },
        "review_required": True,
        "review_notes": [
            "Händler, Referenzen, Rechnungs-/Kartendatum und abweichende Chronologie einzeln prüfen.",
            "Textauslese und Gebühren ausdrücklich bestätigen; kein Zahlungsauftrag.",
        ],
    }
    result["revision"] = bank.digest(result)
    return result


def preview(actor, transaction_id, bank_version, evidence_id, legs):
    return _preview(actor, _load(actor, transaction_id, "process"), bank_version, evidence_id, legs)


def confirm(
    actor, transaction_id, bank_version, evidence_id, legs, preview_revision, reason, idempotency_key
):
    initial = _load(actor, transaction_id, "process")
    with transaction.atomic():
        bank._lock_company(actor, initial.company_id)
        op, fp, replay = bank._replay(
            actor,
            initial.company_id,
            "fx-allocate",
            idempotency_key,
            [str(transaction_id), bank_version, evidence_id, legs, preview_revision, reason],
        )
        if replay is not None:
            return replay
        tx = BankTransaction.objects.select_for_update().get(id=initial.id)
        plan = _preview(actor, tx, bank_version, evidence_id, legs)
        if plan["revision"] != preview_revision:
            raise DomainError("FX-Vorschau veraltet. Neu prüfen.", 409)
        ids = []
        for row in plan["legs"]:
            doc = services.get_document(actor, row["document_id"], "process", lock=True)
            allocation = bank._allocate(
                actor,
                tx,
                doc,
                Decimal(row["amount"]),
                "fx_manual_confirmed",
                reason,
                bank_amount=Decimal(row["bank_amount"]),
                fx={
                    "version": VERSION,
                    "evidence": plan["evidence"],
                    "preview_revision": preview_revision,
                    "bank_principal": row["bank_principal"],
                    "fee": row["fee"],
                },
            )
            ids.append(str(allocation.id))
        return bank._record(
            actor, op, idempotency_key, fp, {"allocation_ids": ids, "bank_version": tx.version}
        )


def get_evidence(actor, transaction_id):
    return evidence(_load(actor, transaction_id))
