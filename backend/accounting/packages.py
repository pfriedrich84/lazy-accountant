import csv
import io
import json
import re
import uuid
import zipfile
from collections import Counter

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from openpyxl import Workbook

from . import storage
from .auth import DomainError
from .models import Document, FileOperation, Package, PackageItem
from .services import document_data, valid_period

COLUMNS = [
    "id",
    "revision",
    "kind",
    "period",
    "date",
    "period_start",
    "period_end",
    "period_assignment_reason",
    "number",
    "issuer",
    "recipient",
    "account",
    "account_identifier",
    "category",
    "net",
    "tax",
    "gross",
    "currency",
    "file",
    "sha256",
]


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
    }
    if detailed:
        data["snapshot"] = p.snapshot
        data["items"] = list(p.items.values("document_id", "revision", "archive_path", "sha256", "metadata"))
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
    included, excluded, unchanged = [], [], []
    intentional_exclusions, exclusion_changes, document_states = [], [], []
    for doc in docs:
        data = document_data(doc)
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
            intentional_exclusions.append({"document": data, "reason": doc.exclusion_reason})
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
            data["archive_path"] = storage.desired_path(doc)
            data["account_name"] = doc.account.name if doc.account_id else ""
            data["account_identifier"] = doc.account.identifier if doc.account_id else ""
            data["category_name"] = doc.category.name if doc.category_id else ""
            included.append(data)
    inbox, excluded_inbox = [], []
    try:
        actor.require_inbox(actor.user_id)
        personal = Document.objects.filter(company__isnull=True, inbox_owner_id=actor.user_id)
        inbox = [str(x) for x in personal.filter(is_excluded=False).values_list("id", flat=True)]
        # Preview-only: never copy personal inbox exclusions into a company export.
        excluded_inbox = [str(x) for x in personal.filter(is_excluded=True).values_list("id", flat=True)]
    except DomainError:
        pass
    return {
        "schema_version": 2,
        "company": {"id": company.id, "name": company.name, "folder": company.folder},
        "periods": periods,
        "parent_id": str(parent.id) if parent else None,
        "recipients": company.recipients,
        "allow_open_issues": company.allow_open_issues,
        "documents": included,
        "excluded": excluded,
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


def spreadsheet_safe(value):
    value = "" if value is None else str(value)
    if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value):
        return value
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


def overview_row(d):
    m = d["metadata"]
    values = {
        "id": d["id"],
        "revision": d["version"],
        "kind": d["kind"],
        "period": d["period"],
        "file": d["archive_path"],
        "sha256": d["sha256"],
        "account": d["account_name"],
        "account_identifier": d["account_identifier"],
        "category": d["category_name"],
        **m,
    }
    return [spreadsheet_safe(values.get(c)) for c in COLUMNS]


def build_archive(snapshot, package_id, version):
    files = {}
    originals = {}
    for d in snapshot["documents"]:
        doc = Document.objects.get(id=d["id"])
        data = storage.read_original(doc)
        files[d["archive_path"]] = data
        originals[d["archive_path"]] = {
            "document_id": d["id"],
            "revision": d["version"],
            "sha256": d["sha256"],
        }
    folder = snapshot["company"]["folder"]
    for period in snapshot["periods"]:
        year, month = period.split("-")
        base = f"{folder}/{year}/{month}"
        for category in storage.FOLDERS:
            files[f"{base}/{category}/"] = b""
        docs = [d for d in snapshot["documents"] if d["period"] == period]
        text = io.StringIO(newline="")
        writer = csv.writer(text, delimiter=";")
        writer.writerow(COLUMNS)
        writer.writerows(overview_row(d) for d in docs)
        files[f"{base}/Uebersicht.csv"] = b"\xef\xbb\xbf" + text.getvalue().encode("utf-8")
        wb = Workbook()
        ws = wb.active
        ws.title = "Unterlagen"
        ws.append(COLUMNS)
        for d in docs:
            ws.append(overview_row(d))
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        stream = io.BytesIO()
        wb.save(stream)
        files[f"{base}/Uebersicht.xlsx"] = stream.getvalue()
        notes = "\n".join(f"- {e['document']['original_name']}: {e['reason']}" for e in snapshot["excluded"])
        intentional = "\n".join(
            f"- {e['document']['original_name']} ("
            f"{e['document']['period'] or 'ohne Monatszuordnung'}): {e['reason']}"
            for e in snapshot.get("intentional_exclusions", [])
        )
        changes = "\n".join(
            f"- {e['document_id']}: {e['action']} v{e['old_revision']} → v{e['new_revision']}; "
            f"{e['reason']} (Vorgängerpaket {e['previous_package_id']})"
            for e in snapshot.get("exclusion_changes", [])
        )
        body = (
            f"Unterlagen für {snapshot['company']['name']} – {period}\nPaket {package_id}, Version {version}\n"
            f"Nachtrag zu: {snapshot['parent_id'] or 'keinem Vorgänger'}\nEmpfänger: {', '.join(snapshot['recipients'])}\n"
            f"{len(docs)} Originale enthalten. Unveränderte Dokumente aus Vorgängern: {len(snapshot['unchanged'])}.\n"
            f"Offene/prüfbedingt ausgeschlossene Unterlagen:\n{notes or 'Keine'}\n"
            f"Bewusst ausgeschlossene Nichtbelege (nicht enthalten, nicht blockierend):\n{intentional or 'Keine'}\n"
            f"Ausschluss-/Wiederherstellungsänderungen zum Vorgänger:\n{changes or 'Keine'}\n"
            "Alte Pakete und bereits übergebene Originale bleiben unverändert.\n"
            f"Nicht zugeordnete Eingangsdokumente: {len(snapshot['unassigned_inbox'])}\n"
            "Dies ist eine Unterlagensammlung, keine bestätigte Buchhaltung.\n"
        )
        files[f"{base}/Begleitschreiben.txt"] = body.encode()
        manifest = [
            {"path": name, "sha256": storage.checksum(data), "bytes": len(data), **originals.get(name, {})}
            for name, data in sorted(files.items())
            if name.startswith(base + "/") and not name.endswith("/")
        ]
        files[f"{base}/Inhaltsliste.json"] = json.dumps(
            {"package_id": str(package_id), "version": version, "files": manifest},
            ensure_ascii=False,
            indent=2,
        ).encode()
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
        for period in p.periods:
            storage.ensure_month(company, period)
    return package_data(p, True)


def package_bytes(package):
    data = storage.path(package.path).read_bytes()
    if storage.checksum(data) != package.sha256:
        raise DomainError("Paket-Prüfsumme stimmt nicht.", 409)
    return data
