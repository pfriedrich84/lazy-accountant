import copy
import io
import json
import uuid
import zipfile
from collections import Counter
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max, OuterRef, Prefetch, Q, Subquery, Sum, TextField
from django.db.models.functions import Cast, Length
from django.utils import timezone

from . import naming, storage, workbook
from .auth import DomainError
from .models import (
    BankTransaction,
    BankTransactionSource,
    Document,
    FileOperation,
    Package,
    PackageContextSource,
    PackageItem,
    PackageRemoval,
    PaymentAllocation,
)
from .services import document_data, valid_period


def package_data(p, detailed=False):
    data = {
        "id": str(p.id),
        "company_id": p.company_id,
        "periods": p.periods,
        "version": p.version,
        "parent_id": str(p.parent_id) if p.parent_id else None,
        "sha256": p.sha256,
        "size": p.size,
        "created_at": p.created_at.isoformat(),
        "security_blocked": package_blockers(p),
        "removed": PackageRemoval.objects.filter(package=p).exists(),
    }
    if detailed:
        data["snapshot"] = copy.deepcopy(p.snapshot)
        data["items"] = list(p.items.values("document_id", "revision", "archive_path", "sha256", "metadata"))
        exclusions = data["snapshot"]["excluded"] + data["snapshot"].get("intentional_exclusions", [])
        documents = (
            data["snapshot"]["documents"]
            + [e["document"] for e in exclusions]
            + data["snapshot"].get("workbook_documents", [])
        )
        blocked_ids = {
            str(identifier)
            for identifier in Document.objects.filter(
                id__in=[d["id"] for d in documents],
            )
            .exclude(security_status="clean")
            .values_list("id", flat=True)
        }
        blocked_ids.update(entry["document_id"] for entry in data["security_blocked"])
        if blocked_ids:
            # New workbook context may include historical bank sources not shipped as originals.
            # Fail closed rather than expose their remittance/FX text through snapshot metadata.
            for key in ("bank_transactions", "allocation_transactions", "payments"):
                data["snapshot"][key] = []
        for document in documents:
            if document["id"] in blocked_ids:
                document.update(
                    metadata={},
                    issues=[],
                    parser_result={},
                    revisions=[],
                    proposed_name="",
                    handover_name="",
                    effective_name=storage.safe_filename(document["original_name"]),
                )
        for excluded in exclusions:
            if excluded["document"]["id"] in blocked_ids:
                excluded["reason"] = "Sicherheitssperre"
        for item in data["items"]:
            if str(item["document_id"]) in blocked_ids:
                item["metadata"] = {}
    return data


def get_package(actor, package_id, permission="read"):
    try:
        p = Package.objects.get(id=package_id)
    except Package.DoesNotExist, ValueError:
        raise DomainError("Paket nicht gefunden.", 404) from None
    actor.require(p.company_id, permission)
    return p


def package_preview(actor, company_id, periods, parent_id=None, lock=False):
    company = actor.require(company_id)
    if not isinstance(periods, list) or not periods or len(periods) > 24:
        raise DomainError("Ein bis 24 Monate auswählen.")
    periods = sorted(set(valid_period(p) for p in periods))
    parent = get_package(actor, parent_id) if parent_id else None
    if parent:
        require_package_available(parent)
    if parent and (parent.company_id != company.id or parent.periods != periods):
        raise DomainError("Nachtrag muss dieselbe Firma und dieselben Monate betreffen.")
    # Latest observed states win across the complete supplement chain. v1 only
    # recorded included items; v2 also records exclusions/restores without files.
    known, prior = {}, {}
    ancestor = parent
    while ancestor:
        states = ancestor.snapshot.get("document_states", [])
        for state in states:
            known.setdefault(state["document_id"], {**state, "package_id": str(ancestor.id)})
        for item in ancestor.items.all():
            prior.setdefault(str(item.document_id), item.revision)
            known.setdefault(
                str(item.document_id),
                {
                    "document_id": str(item.document_id),
                    "revision": item.revision,
                    "is_excluded": False,
                    "package_id": str(ancestor.id),
                },
            )
        ancestor = ancestor.parent
    docs = (
        Document.objects.filter(company=company)
        .filter(Q(period__in=periods) | Q(period=""))
        .order_by("period", "id")
        .select_related("company", "account", "category")
        .prefetch_related("related")
    )
    if lock:
        docs = docs.select_for_update(of=("self",))
    docs = list(docs)
    names = naming.resolve(naming.context_many(docs))
    included, excluded, unchanged, blocked = [], [], [], []
    workbook_documents = []
    intentional_exclusions, exclusion_changes, document_states = [], [], []
    for doc in docs:
        data = document_data(doc, names=names)
        if (
            doc.period in periods
            and doc.status == "ready"
            and not doc.issues
            and data["filing_status"] == "done"
            and not doc.is_excluded
            and not doc.duplicate_of_id
            and doc.security_status == "clean"
            and doc.scanned_sha256 == doc.sha256
        ):
            workbook_documents.append(
                {
                    **data,
                    "account_name": doc.account.name if doc.account_id else "",
                    "account_identifier": doc.account.identifier if doc.account_id else "",
                    "category_name": doc.category.name if doc.category_id else "",
                }
            )
        previous = known.get(str(doc.id))
        document_states.append(
            {
                "document_id": str(doc.id),
                "revision": doc.version,
                "is_excluded": doc.is_excluded,
            }
        )
        if previous and previous["is_excluded"] != doc.is_excluded:
            revision = (
                doc.revisions.filter(source="exclude" if doc.is_excluded else "restore")
                .order_by("-version")
                .first()
            )
            exclusion_changes.append(
                {
                    "document_id": str(doc.id),
                    "original_name": doc.original_name,
                    "old_revision": previous["revision"],
                    "new_revision": doc.version,
                    "action": "exclude" if doc.is_excluded else "restore",
                    "reason": revision.reason if revision else doc.exclusion_reason,
                    "previous_package_id": previous["package_id"],
                }
            )
        if doc.is_excluded:
            # Never include these bytes. Exclusion is not a security clearance;
            # unsafe originals and existing snapshots remain access-blocked.
            intentional_exclusions.append({"document": data, "reason": doc.exclusion_reason})
        elif doc.security_status != "clean" or doc.scanned_sha256 != doc.sha256:
            blocked.append({"document": data, "reason": doc.security_error or doc.security_status})
            excluded.append(
                {
                    "document": data,
                    "reason": "Sicherheitssperre: " + (doc.security_error or doc.security_status),
                }
            )
        elif doc.period not in periods:
            excluded.append({"document": data, "reason": "Übergabemonat ungeklärt"})
        elif doc.duplicate_of_id:
            excluded.append({"document": data, "reason": "Als Dublette markiert"})
        elif doc.status != "ready" or doc.issues:
            excluded.append({"document": data, "reason": "; ".join(doc.issues) or "Noch nicht bestätigt"})
        elif data["filing_status"] != "done":
            excluded.append(
                {"document": data, "reason": "Physische Dateiablage noch ausstehend: " + data["filing_error"]}
            )
        elif prior.get(str(doc.id)) == doc.version:
            unchanged.append(str(doc.id))
        else:
            year, month = doc.period.split("-")
            data["archive_path"] = (
                f"{company.folder}/{year}/{month}/{storage.KIND_FOLDER[doc.kind]}/{data['effective_name']}"
            )
            data["account_name"] = doc.account.name if doc.account_id else ""
            data["account_identifier"] = doc.account.identifier if doc.account_id else ""
            data["category_name"] = doc.category.name if doc.category_id else ""
            included.append(data)
    from .reconciliation import INVOICE_KINDS, digest, status_for_document

    payments = []
    previous_payments = {p["document_id"]: p for p in parent.snapshot.get("payments", [])} if parent else {}
    for doc in docs:
        if (
            doc.kind in INVOICE_KINDS
            and doc.period in periods
            and not doc.duplicate_of_id
            and not doc.is_excluded
            and doc.security_status == "clean"
            and doc.scanned_sha256 == doc.sha256
        ):
            payment = {**status_for_document(doc), "period": doc.period}
            payment["snapshot_revision"] = digest({k: v for k, v in payment.items() if k != "as_of"})
            payments.append(payment)
    payment_changes = [
        p["document_id"]
        for p in payments
        if previous_payments.get(p["document_id"], {}).get("snapshot_revision") != p["snapshot_revision"]
    ]
    inbox, excluded_inbox = [], []
    try:
        actor.require_inbox(actor.user_id)
        personal = Document.objects.filter(company__isnull=True, inbox_owner_id=actor.user_id)
        inbox = [str(x) for x in personal.filter(is_excluded=False).values_list("id", flat=True)]
        # Preview-only: never copy personal inbox exclusions into a company export.
        excluded_inbox = [str(x) for x in personal.filter(is_excluded=True).values_list("id", flat=True)]
    except DomainError:
        pass
    from .mail import import_errors

    bank_export = freeze_bank_export(company.id, periods, payments)
    sources = {s["document_id"]: s for s in bank_export.pop("export_sources")}
    for doc in workbook_documents:
        sources[doc["id"]] = {"document_id": doc["id"], "sha256": doc["sha256"]}
    return {
        "export_sources": list(sources.values()),
        "blocked_imports": import_errors(actor, company_id, include_excluded=False),
        "schema_version": 2,
        "company": {"id": company.id, "name": company.name, "folder": company.folder},
        "periods": periods,
        "parent_id": str(parent.id) if parent else None,
        "recipients": company.recipients,
        "allow_open_issues": company.allow_open_issues,
        "documents": included,
        "payment_schema_version": 2,
        "export_schema_version": 1,
        "workbook_documents": workbook_documents,
        **bank_export,
        "payments": payments,
        "payment_changes": payment_changes,
        "excluded": excluded,
        "security_blocked": blocked,
        "intentional_exclusions": intentional_exclusions,
        "exclusion_changes": exclusion_changes,
        "document_states": document_states,
        "excluded_inbox": excluded_inbox,
        "unassigned_inbox": inbox,
        "unchanged": unchanged,
        "count": len(included),
        "bytes": sum(d["size"] for d in included),
        "max_package_bytes": settings.MAX_PACKAGE_BYTES,
        "by_kind": dict(Counter(d["kind"] for d in included)),
    }


def bank_export_limit():
    return DomainError(
        "Bankexport überschreitet das Zeilen-/Datenlimit. Weniger Monate auswählen oder "
        "MAX_WORKBOOK_BANK_ROWS/MAX_WORKBOOK_BANK_BYTES bewusst mit dem Arbeitsspeicher anpassen; "
        "es werden keine Bewegungen abgeschnitten.",
        413,
    )


def check_bank_export_budget(query):
    """Bound row fan-out and variable text in SQL before materializing any bank objects."""
    rows = query.count()
    if rows > settings.MAX_WORKBOOK_BANK_ROWS:
        raise bank_export_limit()
    if not rows:
        return
    ids = query.values("id")
    rows += PaymentAllocation.objects.filter(transaction_id__in=ids).count()
    rows += BankTransaction.objects.filter(merged_into_id__in=ids).count()
    rows += BankTransactionSource.objects.filter(
        Q(transaction_id__in=ids) | Q(transaction__merged_into_id__in=ids)
    ).count()
    if rows > settings.MAX_WORKBOOK_BANK_ROWS:
        raise bank_export_limit()
    text = sum(
        Length(Cast(field, TextField()))
        for field in (
            "remittance",
            "references",
            "issues",
            "review_points",
            "identity_review_points",
            "bank_reference",
            "party_name",
            "party_iban",
        )
    )
    # Four UTF-8 bytes per character is a conservative bound before fetching text.
    if query.aggregate(characters=Sum(text, default=0))["characters"] * 4 > settings.MAX_WORKBOOK_BANK_BYTES:
        raise bank_export_limit()


def freeze_bank_export(company_id, periods, payments):
    """Capture both month movements and historical evidence for current invoice allocations.

    Called under the package writer's company lock. No live bank reads in the renderer.
    Security guards are shared with reconciliation, including merged observations.
    """
    from .reconciliation import _all_bank_sources, _require_clean_document, transaction_data

    context_ids = {
        identifier
        for p in payments
        for a in p.get("allocations", [])
        for identifier in (a["transaction_id"], a.get("reversed_by_bank_transaction_id"))
        if identifier
    }
    selected = Q(id__in=context_ids)
    for period in periods:
        year, month = map(int, period.split("-"))
        selected |= Q(booking_date__year=year, booking_date__month=month)
    selected_transactions = BankTransaction.objects.filter(
        company_id=company_id, merged_into__isnull=True
    ).filter(selected)
    check_bank_export_budget(selected_transactions)
    source_documents = Document.objects.only(
        "id", "company_id", "account_id", "security_status", "sha256", "scanned_sha256", "is_excluded"
    )
    allocation_documents = (
        PaymentAllocation.objects.select_related("document")
        .only(
            "transaction_id",
            "document_id",
            "reversed_at",
            "document__id",
            "document__company_id",
            "document__security_status",
            "document__sha256",
            "document__scanned_sha256",
            "document__is_excluded",
        )
        .annotate(_export_number=F("document__metadata__number"))
    )
    transactions = (
        selected_transactions.annotate(
            _active_amount=Sum(
                "allocations__bank_amount",
                filter=Q(allocations__reversed_at__isnull=True),
                default=Decimal(0),
            ),
            _bank_reversal_id=Subquery(
                BankTransaction.objects.filter(reversal_of=OuterRef("pk")).values("id")[:1]
            ),
        )
        .select_related("account", "merged_into", "identity_resolution")
        .defer("identity_resolution__evidence")
        .prefetch_related(
            Prefetch("sources__document", queryset=source_documents),
            Prefetch(
                "merged_duplicates",
                queryset=BankTransaction.objects.only(
                    "id", "merged_into_id", "company_id", "account_id"
                ).prefetch_related(Prefetch("sources__document", queryset=source_documents)),
            ),
            Prefetch("allocations", queryset=allocation_documents),
        )
        .order_by("booking_date", "id")
    )
    monthly, allocated, notes, sources = [], [], [], {}
    serialized_bytes = 0
    for tx in transactions.iterator(chunk_size=100):
        if tx.account.company_id != company_id:
            raise DomainError("Firmenfremdes Bankkonto; Export gesperrt.", 409)
        # A stored source exclusion is not undone by generating a workbook.
        if any(source.document.is_excluded for source in _all_bank_sources(tx)):
            if str(tx.id) in context_ids:
                raise DomainError("Zahlungsquelle ist ausgeschlossen; Zuordnung vor Export prüfen.", 409)
            notes.append("Eine Bankbewegung mit ausgeschlossener Quelle wurde nicht exportiert.")
            continue
        data = transaction_data(tx)
        for source in _all_bank_sources(tx):
            sources[str(source.document_id)] = {
                "document_id": str(source.document_id),
                "sha256": source.document.sha256,
            }
        data.update(
            value_date=tx.value_date.isoformat() if tx.value_date else None,
            account_name=tx.account.name,
            account_identifier=tx.account.identifier,
            invoice_references=[],
        )
        for allocation in tx.allocations.all():
            doc = allocation.document
            if doc.company_id != company_id:
                raise DomainError("Firmenfremde Zahlungszuordnung; Export gesperrt.", 409)
            _require_clean_document(doc)
            sources[str(doc.id)] = {"document_id": str(doc.id), "sha256": doc.sha256}
            if not allocation.reversed_at and not doc.is_excluded:
                data["invoice_references"].append(allocation._export_number or "Rechnung ohne Nummer")
        # transaction_data contains UUID source IDs; snapshots are JSON-serializable.
        encoded = json.dumps(data, default=str)
        data = json.loads(encoded)
        in_month = bool(data["booking_date"] and data["booking_date"][:7] in periods)
        in_context = str(tx.id) in context_ids
        serialized_bytes += len(encoded.encode("utf-8")) * (int(in_month) + int(in_context))
        if serialized_bytes > settings.MAX_WORKBOOK_BANK_BYTES:
            raise bank_export_limit()
        if in_month:
            monthly.append(data)
        if in_context:
            allocated.append(data)
    return {
        "bank_transactions": monthly,
        "allocation_transactions": allocated,
        "bank_export_notes": notes,
        "export_sources": list(sources.values()),
    }


def build_archive(snapshot, package_id, version):
    # Context-only sources are still protected financial data, including in supplements.
    for source in snapshot.get("export_sources", []):
        doc = Document.objects.get(id=source["document_id"])
        if doc.sha256 != source["sha256"]:
            raise DomainError("Exportquelle wurde verändert.", 409)
        storage.read_original(doc)
    files = {}
    for d in snapshot["documents"]:
        doc = Document.objects.get(id=d["id"])
        data = storage.read_original(doc)
        if d["archive_path"] in files:
            raise DomainError("Doppelter Übergabepfad im Snapshot; kein Überschreiben erlaubt.", 409)
        files[d["archive_path"]] = data
    folder = snapshot["company"]["folder"]
    for period in snapshot["periods"]:
        year, month = period.split("-")
        base = f"{folder}/{year}/{month}"
        for category in storage.FOLDERS:
            files[f"{base}/{category}/"] = b""
    files[workbook.workbook_name(snapshot)] = workbook.build_workbook(snapshot, package_id, version)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return stream.getvalue()


def create_package(actor, company_id, periods, idempotency_key, parent_id=None):
    actor.require(company_id, "process")
    if not idempotency_key or len(idempotency_key) > 120:
        raise DomainError("Idempotenzschlüssel erforderlich (max. 120 Zeichen).")
    with transaction.atomic():
        # Match document writers' actor -> company -> document lock order.
        # Package.actor's FK otherwise acquires a user KEY SHARE after holding
        # the company, deadlocking with an exclusion waiting for that company.
        from django.contrib.auth import get_user_model

        get_user_model().objects.select_for_update().get(id=actor.user_id)
        company = actor.companies("process").select_for_update().get(id=company_id)
        prior = Package.objects.filter(company=company, idempotency_key=idempotency_key).first()
        if prior:
            if prior.periods != sorted(set(periods)) or str(prior.parent_id or "") != str(parent_id or ""):
                raise DomainError("Idempotenzschlüssel gehört zu einem anderen Paketauftrag.", 409)
            return package_data(prior, True)
        for document_id in (
            FileOperation.objects.filter(document__company=company, status="pending")
            .values_list("document_id", flat=True)
            .distinct()
        ):
            storage.reconcile(document_id)
        snapshot = package_preview(actor, company_id, periods, parent_id, lock=True)
        snapshot.pop("excluded_inbox", None)
        snapshot["exported_at"] = timezone.now().isoformat()
        if snapshot["bytes"] > settings.MAX_PACKAGE_BYTES:
            raise DomainError(
                "Paket überschreitet das konfigurierte Verarbeitungsgrößenlimit. Weniger Monate auswählen oder das Betriebslimit bewusst anpassen.",
                413,
            )
        version = (Package.objects.filter(company=company).aggregate(n=Max("version"))["n"] or 0) + 1
        pid = uuid.uuid4()
        data = build_archive(snapshot, pid, version)
        relative = f"_packages/{pid}.zip"
        storage.atomic_write(relative, data)
        p = Package.objects.create(
            id=pid,
            company=company,
            periods=snapshot["periods"],
            version=version,
            parent_id=parent_id,
            snapshot=snapshot,
            path=relative,
            sha256=storage.checksum(data),
            size=len(data),
            actor_id=actor.user_id,
            idempotency_key=idempotency_key,
        )
        PackageItem.objects.bulk_create(
            [
                PackageItem(
                    package=p,
                    document_id=d["id"],
                    revision=d["version"],
                    archive_path=d["archive_path"],
                    sha256=d["sha256"],
                    metadata=d,
                )
                for d in snapshot["documents"]
            ]
        )
        included_ids = {d["id"] for d in snapshot["documents"]}
        PackageContextSource.objects.bulk_create(
            [
                PackageContextSource(package=p, document_id=source["document_id"])
                for source in snapshot.get("export_sources", [])
                if source["document_id"] not in included_ids
            ]
        )
        for period in p.periods:
            storage.ensure_month(company, period)
    return package_data(p, True)


def package_sources(package):
    expected = {str(item.document_id): item.sha256 for item in package.items.all()}
    expected.update({s["document_id"]: s["sha256"] for s in package.snapshot.get("export_sources", [])})
    return expected


def package_blockers(package):
    expected = package_sources(package)
    documents = {str(d.id): d for d in Document.objects.filter(id__in=expected)}
    blockers = []
    for identifier, sha256 in expected.items():
        doc = documents.get(identifier)
        if doc is None:
            blockers.append({"document_id": identifier, "reason": "Exportquelle fehlt"})
        elif doc.security_status != "clean" or doc.scanned_sha256 != sha256 or doc.sha256 != sha256:
            blockers.append(
                {
                    "document_id": identifier,
                    "reason": doc.security_error
                    or (
                        doc.security_status
                        if doc.security_status != "clean"
                        else "Freigegebener Hash stimmt nicht mit Paket überein"
                    ),
                }
            )
    return blockers


def require_package_available(package):
    if PackageRemoval.objects.filter(package_id=package.id).exists():
        raise DomainError("Paket wurde entfernt; Download, Nachtrag und Versand sind gesperrt.", 410)


def require_package_safe(package):
    require_package_available(package)
    blockers = package_blockers(package)
    if blockers:
        raise DomainError(
            "Paket wegen Sicherheitsprüfung gesperrt.",
            423,
            {
                "package_id": str(package.id),
                "blocked": blockers,
                "dispatch_ids": [str(x) for x in package.dispatches.values_list("id", flat=True)],
            },
        )
    # Includes later on-disk tampering, not just recorded scanner findings.
    for doc in Document.objects.filter(id__in=package_sources(package)):
        storage.read_original(doc)


def package_bytes(package):
    # Materialize the complete response under the same lock used by removal.
    # A download authorized before removal may finish; later requests get 410.
    with transaction.atomic():
        # NO KEY UPDATE also serializes removal, but permits the KEY SHARE
        # needed by a concurrent supplement's parent FK check. A full UPDATE
        # lock deadlocks if that builder already holds our document locks.
        package = Package.objects.select_for_update(no_key=True).get(id=package.id)
        require_package_safe(package)
        data = storage.path(package.path).read_bytes()
        if storage.checksum(data) != package.sha256:
            raise DomainError("Paket-Prüfsumme stimmt nicht.", 409)
        return data
