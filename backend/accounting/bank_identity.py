"""Explicit CAMT identity links, never a merge of payments or editable bank facts.

Only an unused missing-reference observation can join an already bank-identified
movement. TxId + identical counteraccount and immutable facts + raw source proofs
are required. Amount or EndToEndId alone never establish identity.
"""

from decimal import Decimal
from uuid import UUID
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import reconciliation as bank, storage
from .auth import DomainError
from .bank_parser import MISSING_IDENTITY, reconciliation_entries
from .models import BankControlEvent, BankIdentityResolution, BankTransaction, Document
from .payment_schemas import BankIdentityRequest

RULE = "explicit-camt-txid-counteraccount-identity-v1"
DISPUTED = "Identitätszusammenführung bestritten; Korrekturprüfung erforderlich"
MAX_PROOF_ROWS = 10_000
FACTS = (
    "amount",
    "currency",
    "direction",
    "booking_date",
    "value_date",
    "party_name",
    "party_iban",
    "remittance",
)


def _validate_text(reason, idempotency_key):
    try:
        BankIdentityRequest(reason=reason, idempotency_key=idempotency_key)
    except ValueError:
        raise DomainError(
            "Gültige Begründung (max. 1000 Zeichen) und Idempotenzschlüssel erforderlich."
        ) from None


def _get(actor, transaction_id, permission="read", company_id=None):
    try:
        transaction_id = UUID(str(transaction_id))
    except ValueError, TypeError:
        raise DomainError("Gültige Bankbewegungs-ID erforderlich.") from None
    qs = BankTransaction.objects.filter(id=transaction_id, company__in=actor.companies(permission))
    if company_id is not None:
        qs = qs.filter(company_id=company_id)
    tx = (
        qs.select_related("account")
        .prefetch_related("sources__document", "merged_duplicates__sources__document")
        .first()
    )
    if not tx:
        raise DomainError("Bankbewegung nicht gefunden.", 404)
    return tx


def _equal(left, right, field):
    if field == "amount":
        return Decimal(left) == Decimal(right)
    return str(left) == str(right)


def _blockers(duplicate, canonical):
    blockers = []
    if duplicate.id == canonical.id or duplicate.account_id != canonical.account_id:
        blockers.append("Verschiedene Bewegungen im selben Bankkonto erforderlich")
    if duplicate.merged_into_id or canonical.merged_into_id or duplicate.merged_duplicates.exists():
        blockers.append("Keine Ketten, Zyklen oder erneute Zusammenführung bereits verknüpfter Beobachtungen")
    if duplicate.allocations.exists():
        blockers.append("Beobachtung besitzt Zahlungshistorie; finanzieller Korrekturworkflow erforderlich")
    if (
        duplicate.reversal
        or canonical.reversal
        or duplicate.reversal_of_id
        or canonical.reversal_of_id
        or BankTransaction.objects.filter(reversal_of_id__in=[duplicate.id, canonical.id]).exists()
    ):
        blockers.append("Rückbuchungen oder rückgebuchte Originale werden hier nicht zusammengeführt")
    if not duplicate.booked or not canonical.booked:
        blockers.append("Beide Bewegungen müssen gebucht sein")
    if (
        duplicate.bank_reference
        or set(duplicate.issues) != {MISSING_IDENTITY}
        or canonical.issues
        or not canonical.bank_reference
    ):
        blockers.append(
            "Nur fehlende Bankkennung auf eine bereits bankidentifizierte, ungeklärtheitsfreie Bewegung auflösen"
        )
    if bank._bank_notes(duplicate) or bank._bank_notes(canonical):
        blockers.append("Bestehende Bank-/Identitätswidersprüche zuerst klären")
    token = duplicate.references.get("transaction_id")
    if (
        not token
        or token != canonical.references.get("transaction_id")
        or not duplicate.party_iban
        or duplicate.party_iban != canonical.party_iban
    ):
        blockers.append(
            "Übereinstimmende bankseitige TxId und identisches Gegenkonto erforderlich; EndToEndId/Betrag reichen nicht"
        )
    if any(not _equal(getattr(duplicate, k), getattr(canonical, k), k) for k in FACTS):
        blockers.append("Buchungsdaten widersprechen sich; keine Änderung oder tolerante Zusammenführung")
    if (
        token
        and BankTransaction.objects.filter(
            company_id=duplicate.company_id, account_id=duplicate.account_id, references__transaction_id=token
        )
        .exclude(id__in=[duplicate.id, canonical.id])
        .exclude(merged_into=canonical)
        .exists()
    ):
        blockers.append("Weitere Bewegung mit derselben TxId; keine eindeutige Paarauflösung")
    for movement in [duplicate, canonical]:
        bank._require_clean_sources(movement)
        if not movement.sources.exists():
            blockers.append("Originalquellen für beide Bewegungen erforderlich")
        for source in bank._all_bank_sources(movement):
            doc = source.document
            if (
                doc.company_id != movement.company_id
                or doc.account_id != movement.account_id
                or doc.kind != "bank_camt"
                or doc.is_excluded
                or doc.duplicate_of_id
                or doc.status != "ready"
                or doc.issues
            ):
                blockers.append("Nur aktive geprüfte CAMT-Originalquellen im selben Firmenkonto")
    documents = {
        s.document_id: s.document for tx in [duplicate, canonical] for s in bank._all_bank_sources(tx)
    }
    if len(documents) > 100 or sum(d.size for d in documents.values()) > settings.MAX_FILE_BYTES:
        blockers.append(
            "Originalprüfumfang überschreitet 100 Quellen oder das konfigurierte Datei-Bytebudget"
        )
    return sorted(set(blockers))


def _documents(duplicate, canonical):
    return {
        str(s.document_id): s.document.version
        for tx in [duplicate, canonical]
        for s in bank._all_bank_sources(tx)
    }


def preview(actor, duplicate_id, canonical_id):
    duplicate = _get(actor, duplicate_id)
    canonical = _get(actor, canonical_id, company_id=duplicate.company_id)
    blockers = _blockers(duplicate, canonical)
    return {
        "duplicate_id": str(duplicate.id),
        "canonical_id": str(canonical.id),
        "duplicate_version": duplicate.version,
        "canonical_version": canonical.version,
        "document_versions": _documents(duplicate, canonical)
        if len(_documents(duplicate, canonical)) <= 100
        else {},
        "can_merge": not blockers,
        "blockers": blockers,
        "rule_version": RULE,
        "criteria": [
            "Bank-TxId und Gegenkonto stimmen überein",
            "Betrag/Währung/Richtung/Datum/Partei/Verwendungszweck unverändert",
            "Keine Zahlungshistorie der aufzulösenden Beobachtung",
            "Originalbytes werden vor dem Schreiben erneut geprüft",
        ]
        if not blockers
        else [],
        "note": "Vorschau ist keine Reservierung oder Zahlungsbestätigung. Originale und bestehende Zahlungen werden nicht verschoben.",
    }


def candidates(actor, duplicate_id):
    duplicate = _get(actor, duplicate_id)
    bank._require_clean_sources(duplicate)
    token = duplicate.references.get("transaction_id")
    rows = []
    if token and not duplicate.merged_into_id:
        matches = list(
            BankTransaction.objects.filter(
                company_id=duplicate.company_id,
                account_id=duplicate.account_id,
                references__transaction_id=token,
                merged_into__isnull=True,
            )
            .exclude(id=duplicate.id)
            .exclude(bank_reference="")
            .order_by("id")[:21]
        )
        for canonical in matches[:20]:
            value = preview(actor, duplicate.id, canonical.id)
            rows.append({**value, "bank_reference": canonical.bank_reference})
        truncated = len(matches) > 20
    else:
        truncated = False
    return {
        "duplicate_id": str(duplicate.id),
        "items": rows,
        "truncated": truncated,
        "note": "Nur belastbare TxId/Gegenkonto-Paare, keine Suche nach Betrag oder EndToEndId allein. Andere Konflikte bleiben gesperrt.",
    }


def _original_proof(duplicate, canonical):
    """Reparse locked, hash-checked originals; do not trust client-supplied bank facts."""
    parsed, evidence = {}, []
    row_count, byte_count = 0, 0
    for movement in [duplicate, canonical] + list(canonical.merged_duplicates.all()):
        proved = False
        for source in movement.sources.all():
            doc = source.document
            if doc.id not in parsed:
                try:
                    data = storage.read_original(doc)
                    byte_count += len(data)
                    if byte_count > settings.MAX_FILE_BYTES:
                        raise DomainError("Bytebudget der Identitätsprüfung überschritten.", 409)
                    parsed[doc.id] = {}
                    for row in reconciliation_entries(data):
                        row_count += 1
                        if row_count > MAX_PROOF_ROWS:
                            raise DomainError("Zeilenbudget der Identitätsprüfung überschritten.", 409)
                        parsed[doc.id][row["locator"]] = row
                except (ValueError, ArithmeticError, ParseError, DefusedXmlException) as exc:
                    raise DomainError(
                        "Originalquelle kann nicht deterministisch geprüft werden.", 409
                    ) from exc
            row = parsed[doc.id].get(source.locator)
            if not row or row["own_iban"] != movement.account.identifier.replace(" ", "").upper():
                raise DomainError("Originalbelegstelle oder Konto stimmt nicht überein.", 409)
            fields = FACTS + ("bank_reference", "reversal", "issues")
            if any(not _equal(getattr(movement, k), row[k], k) for k in fields) or any(
                movement.references.get(k) != v for k, v in row["references"].items()
            ):
                raise DomainError(
                    "Gespeicherte Bankdaten widersprechen dem Original; keine Identitätsfreigabe.", 409
                )
            if row["booked"] and row["references"].get("transaction_id") == duplicate.references.get(
                "transaction_id"
            ):
                proved = True
            evidence.append(
                {
                    "transaction_id": str(movement.id),
                    "source_id": source.id,
                    "document_id": str(doc.id),
                    "document_version": doc.version,
                    "normalized_document_version": source.document_version,
                    "sha256": doc.sha256,
                    "locator": source.locator,
                    "parser_version": source.parser_version,
                }
            )
        if not proved:
            raise DomainError("Gebuchte TxId muss in den tatsächlichen Originalquellen belegt sein.", 409)
    return {
        "rule_version": RULE,
        "transaction_id": duplicate.references["transaction_id"],
        "counteraccount": duplicate.party_iban,
        "sources": evidence,
    }


def merge(
    actor,
    duplicate_id,
    canonical_id,
    duplicate_version,
    canonical_version,
    document_versions,
    reason,
    idempotency_key,
):
    _validate_text(reason, idempotency_key)
    initial = _get(actor, duplicate_id, "process")
    versions = {str(k): v for k, v in document_versions.items()}
    with transaction.atomic():
        bank._lock_company(actor, initial.company_id)
        op, fp, replay = bank._replay(
            actor,
            initial.company_id,
            "identity.merge",
            idempotency_key,
            [str(duplicate_id), str(canonical_id), duplicate_version, canonical_version, versions, reason],
        )
        if replay is not None:
            return replay
        rows = {
            str(tx.id): tx
            for tx in BankTransaction.objects.select_for_update()
            .filter(company_id=initial.company_id, id__in=[duplicate_id, canonical_id])
            .order_by("id")
        }
        if str(duplicate_id) not in rows or str(canonical_id) not in rows:
            raise DomainError("Bankbewegung nicht gefunden.", 404)
        duplicate, canonical = rows[str(duplicate_id)], rows[str(canonical_id)]
        if duplicate.version != duplicate_version or canonical.version != canonical_version:
            raise DomainError("Bankbewegung inzwischen geändert. Neu laden.", 409)
        docs = _documents(duplicate, canonical)
        locked = {
            str(d.id): d for d in Document.objects.select_for_update().filter(id__in=docs).order_by("id")
        }
        # Re-fetch after document locks: a rescan/name/exclusion may have won meanwhile.
        duplicate, canonical = (
            _get(actor, duplicate_id, "process", initial.company_id),
            _get(actor, canonical_id, "process", initial.company_id),
        )
        if (
            versions != {key: doc.version for key, doc in locked.items()}
            or set(versions) != set(docs)
            or len(versions) > 100
        ):
            raise DomainError("Quellenversionen inzwischen geändert oder unvollständig. Neu laden.", 409)
        blockers = _blockers(duplicate, canonical)
        if blockers:
            raise DomainError("Identität nicht sicher zusammenführbar.", 409, {"blockers": blockers})
        evidence = _original_proof(duplicate, canonical)
        duplicate.merged_into = canonical
        duplicate.version += 1
        duplicate.save(update_fields=["merged_into", "version"])
        canonical.version += 1
        canonical.save(update_fields=["version"])
        resolution = BankIdentityResolution.objects.create(
            duplicate=duplicate, canonical=canonical, actor_id=actor.user_id, reason=reason, evidence=evidence
        )
        result = {
            "duplicate_id": str(duplicate.id),
            "canonical_id": str(canonical.id),
            "duplicate_version": duplicate.version,
            "canonical_version": canonical.version,
            "resolution_id": resolution.id,
            "state": "merged",
            "payment_effect": "none",
        }
        BankControlEvent.objects.create(
            company_id=initial.company_id,
            account_id=canonical.account_id,
            actor_id=actor.user_id,
            operation="identity.merge",
            version=duplicate.version,
            reason=reason,
            payload={**result, "evidence": evidence},
        )
        return bank._record(actor, op, idempotency_key, fp, result)


def dispute(actor, duplicate_id, duplicate_version, canonical_version, reason, idempotency_key):
    _validate_text(reason, idempotency_key)
    initial = _get(actor, duplicate_id, "process")
    with transaction.atomic():
        bank._lock_company(actor, initial.company_id)
        op, fp, replay = bank._replay(
            actor,
            initial.company_id,
            "identity.dispute",
            idempotency_key,
            [str(duplicate_id), duplicate_version, canonical_version, reason],
        )
        if replay is not None:
            return replay
        resolution = BankIdentityResolution.objects.filter(
            duplicate_id=duplicate_id,
            canonical__company_id=initial.company_id,
            duplicate__company_id=initial.company_id,
        ).first()
        if not resolution:
            raise DomainError("Identitätszusammenführung nicht gefunden.", 404)
        rows = {
            tx.id: tx
            for tx in BankTransaction.objects.select_for_update()
            .filter(id__in=[resolution.duplicate_id, resolution.canonical_id])
            .order_by("id")
        }
        duplicate, canonical = rows[resolution.duplicate_id], rows[resolution.canonical_id]
        if (
            duplicate.version != duplicate_version
            or canonical.version != canonical_version
            or resolution.disputed_at
            or duplicate.merged_into_id != canonical.id
        ):
            raise DomainError("Identitätsstand inzwischen geändert. Neu laden.", 409)
        resolution.disputed_at, resolution.disputed_by_id, resolution.dispute_reason = (
            timezone.now(),
            actor.user_id,
            reason,
        )
        resolution.save(update_fields=["disputed_at", "disputed_by", "dispute_reason"])
        for movement in [duplicate, canonical]:
            movement.identity_review_points = sorted(set(movement.identity_review_points + [DISPUTED]))
            movement.version += 1
            movement.save(update_fields=["identity_review_points", "version"])
        result = {
            "duplicate_id": str(duplicate.id),
            "canonical_id": str(canonical.id),
            "duplicate_version": duplicate.version,
            "canonical_version": canonical.version,
            "resolution_id": resolution.id,
            "state": "disputed",
            "payment_effect": "none",
        }
        BankControlEvent.objects.create(
            company_id=initial.company_id,
            account_id=canonical.account_id,
            actor_id=actor.user_id,
            operation="identity.dispute",
            version=duplicate.version,
            reason=reason,
            payload=result,
        )
        return bank._record(actor, op, idempotency_key, fp, result)


def history(actor, transaction_id):
    tx = _get(actor, transaction_id)
    bank._require_clean_sources(tx)
    if tx.merged_into_id:
        bank._require_clean_sources(_get(actor, tx.merged_into_id, company_id=tx.company_id))
    events = list(
        BankControlEvent.objects.filter(
            company_id=tx.company_id, operation__in=["identity.merge", "identity.dispute"]
        )
        .filter(Q(payload__duplicate_id=str(tx.id)) | Q(payload__canonical_id=str(tx.id)))
        .order_by("-id")[:101]
    )
    return {
        "transaction_id": str(tx.id),
        "truncated": len(events) > 100,
        "items": [
            {
                "id": e.id,
                "operation": e.operation,
                "actor_id": e.actor_id,
                "reason": e.reason,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
            }
            for e in reversed(events[:100])
        ],
    }
