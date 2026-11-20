"""Persistent control declarations, not inferred payment or bank completeness proofs."""

import re
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone

from . import reconciliation as bank
from .auth import DomainError
from .models import (
    Account,
    BankAutomationPolicy,
    BankControlEvent,
    BankCoverageSource,
    BankMonthCoverage,
    BankTransaction,
    BankTransactionSource,
    Company,
    Document,
)


def _period(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise DomainError("Monat muss YYYY-MM sein.")
    try:
        date.fromisoformat(value + "-01")
    except ValueError:
        raise DomainError("Ungültiger Monat.") from None
    return value


def _lock(actor, company_id, permission):
    actor.require(company_id, permission)
    get_user_model().objects.select_for_update().get(id=actor.user_id)
    Company.objects.select_for_update().get(id=company_id)


def _history(qs):
    return [
        {
            "actor_id": event.actor_id,
            "version": event.version,
            "reason": event.reason,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        }
        for event in qs.order_by("-id")[:100]
    ]


def policy_data(company_id):
    policy = BankAutomationPolicy.objects.filter(company_id=company_id).first()
    return {
        "company_id": company_id,
        "enabled": policy.enabled if policy else True,
        "version": policy.version if policy else 0,
        "persisted": policy is not None,
        "rule_version": bank.RULE_VERSION,
        "note": "Voreinstellung erhält die bereits freigegebene konservative Automatik. Keine Zahlungsanweisung.",
    }


def get_policy(actor, company_id):
    actor.require(company_id)
    return {
        **policy_data(company_id),
        "history": _history(BankControlEvent.objects.filter(company_id=company_id, operation="policy")),
    }


def set_policy(actor, company_id, expected_version, enabled, reason, idempotency_key):
    if not isinstance(enabled, bool) or not reason.strip() or len(reason) > 1000:
        raise DomainError("Expliziter Automatikzustand und Begründung erforderlich.")
    with transaction.atomic():
        _lock(actor, company_id, "admin")
        op, fp, replay = bank._replay(
            actor, company_id, "policy", idempotency_key, [expected_version, enabled, reason]
        )
        if replay is not None:
            return replay
        current = policy_data(company_id)
        if current["version"] != expected_version:
            raise DomainError("Automatikpolicy inzwischen geändert. Neu laden.", 409)
        policy, _ = BankAutomationPolicy.objects.get_or_create(company_id=company_id)
        policy.enabled, policy.version = enabled, expected_version + 1
        policy.save()
        result = policy_data(company_id)
        BankControlEvent.objects.create(
            company_id=company_id,
            actor_id=actor.user_id,
            operation="policy",
            version=policy.version,
            reason=reason,
            payload=result,
        )
        return bank._record(actor, op, idempotency_key, fp, result)


def _source_problems(doc, account_id, period, sha256=None, company_id=None):
    problems = []
    if (
        (company_id is not None and doc.company_id != company_id)
        or doc.account_id != account_id
        or doc.period != period
        or doc.kind not in {"bank_camt", "bank_pdf"}
    ):
        problems.append("Quellkonto/Monatszuordnung oder Belegart geändert")
    if doc.is_excluded or doc.duplicate_of_id:
        problems.append("Quelle ausgeschlossen oder als Dublette markiert")
    if doc.status != "ready" or doc.issues or doc.metadata.get("open_points"):
        problems.append("Konkrete offene Prüfung oder Widerspruch an der Quelle")
    if (
        doc.security_status != "clean"
        or doc.scanned_sha256 != doc.sha256
        or (sha256 and sha256 != doc.sha256)
    ):
        problems.append("Quelle sicherheitsgesperrt oder Originalprüfsumme geändert")
    return problems


def _coverage_data(coverage):
    reasons, sources = [], []
    if coverage:
        for source in coverage.sources.all():
            doc = source.document
            reasons.extend(
                _source_problems(
                    doc, coverage.account_id, coverage.period, source.sha256, coverage.account.company_id
                )
            )
            sources.append(
                {
                    "document_id": str(doc.id),
                    "document_version": source.document_version,
                    "current_version": doc.version if doc.company_id == coverage.account.company_id else None,
                    "sha256": source.sha256,
                }
            )
        if coverage.state == "confirmed" and not sources:
            reasons.append("Bestätigung ohne Quellenbezug")
    declared = coverage.state if coverage else "unknown"
    return {
        "version": coverage.version if coverage else 0,
        "declared_state": declared,
        "effective_state": "disputed" if declared == "confirmed" and reasons else declared,
        "review_reasons": sorted(set(reasons)),
        "sources": sources,
        "updated_at": coverage.updated_at.isoformat() if coverage else None,
    }


def set_coverage(
    actor,
    company_id,
    account_id,
    period,
    expected_version,
    state,
    document_ids,
    reason,
    idempotency_key,
    document_versions=None,
):
    period = _period(period)
    if state not in {"confirmed", "disputed", "unknown"} or not reason.strip() or len(reason) > 1000:
        raise DomainError("Gültiger Abdeckungszustand und Begründung erforderlich.")
    ids = sorted({str(i) for i in document_ids})
    if len(ids) != len(document_ids) or len(ids) > 100 or (state == "confirmed" and not ids):
        raise DomainError("Eindeutige Quellen erforderlich; Bestätigung braucht mindestens einen Auszug.")
    versions = {str(k): v for k, v in (document_versions or {}).items()}
    if set(versions) != set(ids) or any(type(v) is not int or v < 1 for v in versions.values()):
        raise DomainError("Aktuelle Version für jede Auszugsquelle erforderlich.")
    with transaction.atomic():
        _lock(actor, company_id, "process")
        account = Account.objects.filter(id=account_id, company_id=company_id, kind="bank").first()
        if not account:
            raise DomainError("Bankkonto nicht gefunden.", 404)
        op, fp, replay = bank._replay(
            actor,
            company_id,
            "coverage",
            idempotency_key,
            [account_id, period, expected_version, state, ids, versions, reason],
        )
        if replay is not None:
            return replay
        current = BankMonthCoverage.objects.filter(account=account, period=period).first()
        if (current.version if current else 0) != expected_version:
            raise DomainError("Monatsabdeckung inzwischen geändert. Neu laden.", 409)
        docs = list(
            Document.objects.select_for_update().filter(id__in=ids, company_id=company_id).order_by("id")
        )
        if len(docs) != len(ids) or any(doc.account_id != account_id for doc in docs):
            raise DomainError("Auszugsquelle nicht im gewählten Firmenkonto gefunden.", 404)
        for doc in docs:
            if doc.version != versions[str(doc.id)]:
                raise DomainError("Auszugsquelle inzwischen geändert. Neu laden.", 409)
            bank._require_clean_document(doc)
            if (
                doc.kind not in {"bank_camt", "bank_pdf"}
                or doc.period != period
                or doc.is_excluded
                or doc.duplicate_of_id
            ):
                raise DomainError("Aktiver Kontoauszug im gewählten Monat erforderlich.")
            if state == "confirmed" and _source_problems(doc, account_id, period):
                raise DomainError(
                    "Konkrete Quellenwidersprüche erst auflösen; keine Vollständigkeitsbehauptung.", 409
                )
        if state == "confirmed":
            related = Document.objects.filter(
                company_id=company_id,
                account=account,
                period=period,
                kind__in=["bank_camt", "bank_pdf"],
                is_excluded=False,
                duplicate_of__isnull=True,
            )
            if any(d.issues or d.metadata.get("open_points") for d in related.iterator(chunk_size=100)):
                raise DomainError("Weitere Monatsquelle mit konkretem Widerspruch; zuerst prüfen.", 409)
        if current is None:
            current = BankMonthCoverage(account=account, period=period)
        current.state, current.version = state, expected_version + 1
        current.save()
        current.sources.all().delete()
        BankCoverageSource.objects.bulk_create(
            [
                BankCoverageSource(
                    coverage=current, document=doc, document_version=doc.version, sha256=doc.sha256
                )
                for doc in docs
            ]
        )
        result = {"account_id": account_id, "period": period, **_coverage_data(current)}
        BankControlEvent.objects.create(
            company_id=company_id,
            actor_id=actor.user_id,
            account=account,
            period=period,
            operation="coverage",
            version=current.version,
            reason=reason,
            payload=result,
        )
        return bank._record(actor, op, idempotency_key, fp, result)


def account_overview(actor, company_id, period, cursor=0, limit=50):
    actor.require(company_id)
    period = _period(period)
    cursor, limit, _ = bank._list_options(cursor, limit, "")
    accounts = list(
        Account.objects.filter(company_id=company_id, kind="bank").order_by("id")[cursor : cursor + limit + 1]
    )
    coverages = {
        c.account_id: c
        for c in BankMonthCoverage.objects.filter(
            account__company_id=company_id, account_id__in=[a.id for a in accounts[:limit]], period=period
        )
        .select_related("account")
        .prefetch_related("sources__document")
    }
    items = []
    for account in accounts[:limit]:
        coverage = coverages.get(account.id)
        docs = list(
            Document.objects.filter(
                company_id=company_id,
                account=account,
                period=period,
                kind__in=["bank_camt", "bank_pdf"],
                is_excluded=False,
                duplicate_of__isnull=True,
            ).order_by("id")[:101]
        )
        statements_truncated = len(docs) > 100
        docs = docs[:100]
        transactions = BankTransaction.objects.filter(company_id=company_id, account=account)
        # A finding on any canonical bank source blocks extracted account aggregates too.
        blocked = (
            BankTransactionSource.objects.filter(transaction__account=account)
            .exclude(document__security_status="clean", document__scanned_sha256=F("document__sha256"))
            .exists()
        )
        stats = (
            transactions.aggregate(
                total=Count("id"),
                latest_booked=Max("booking_date", filter=Q(booked=True)),
                pending=Count("id", filter=Q(booked=False)),
            )
            if not blocked
            else {}
        )
        data = _coverage_data(coverage)
        if coverage is None and docs:
            # Product decision: reviewed monthly statements are accepted as complete for
            # their assigned month, not re-questioned for fuzzy/start/end boundaries.
            # This is a declared convention, explicitly distinct from bank-proven coverage.
            problems = sorted({p for d in docs for p in _source_problems(d, account.id, period)})
            ready = [d for d in docs if not _source_problems(d, account.id, period)]
            data.update(
                basis="accepted_monthly_statement_convention",
                effective_state="disputed" if problems else "confirmed" if ready else "unknown",
                review_reasons=problems,
                sources=[
                    {
                        "document_id": str(d.id),
                        "document_version": d.version,
                        "current_version": d.version,
                        "sha256": d.sha256,
                    }
                    for d in ready
                ],
            )
        else:
            data["basis"] = "explicit_declaration" if coverage else "no_statement"
        if (
            coverage
            and data["effective_state"] == "confirmed"
            and any(d.issues or d.metadata.get("open_points") for d in docs)
        ):
            data["effective_state"] = "disputed"
            data["review_reasons"] = sorted(
                set(data["review_reasons"] + ["Monatsquelle mit konkretem Widerspruch"])
            )
        if statements_truncated:
            data["effective_state"] = "disputed"
            data["review_reasons"].append("Mehr als 100 Monatsquellen; Quellenübersicht unvollständig")
        items.append(
            {
                "account_id": account.id,
                "statements_truncated": statements_truncated,
                "account_name": account.name,
                "period": period,
                "coverage": data,
                "latest_booked_date": str(stats["latest_booked"]) if stats.get("latest_booked") else None,
                "transaction_count": stats.get("total"),
                "pending_count": stats.get("pending"),
                "security_blocked": blocked,
                "statements": [
                    {
                        "document_id": str(d.id),
                        "version": d.version,
                        "ready_for_confirmation": not _source_problems(d, account.id, period),
                        "review_reasons": _source_problems(d, account.id, period),
                    }
                    for d in docs
                ],
                "history": _history(
                    BankControlEvent.objects.filter(
                        company_id=company_id, account=account, period=period, operation="coverage"
                    )
                ),
            }
        )
    return {
        "company_id": company_id,
        "period": period,
        "as_of": timezone.now().isoformat(),
        "items": items,
        "next_cursor": cursor + limit if len(accounts) > limit else None,
        "note": "Buchungsdatenstand ist keine Monatsabdeckung. Bestätigte Monatsvollständigkeit bleibt auch bei unscharfen Datumsgrenzen erhalten; konkrete Widersprüche werden separat gemeldet.",
    }
