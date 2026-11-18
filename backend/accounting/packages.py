import csv
import io
import json
import uuid
import zipfile
from collections import Counter

from django.db import transaction
from django.db.models import Max, Q
from openpyxl import Workbook

from . import storage
from .auth import DomainError
from .models import Document, Package, PackageItem
from .services import document_data, valid_period

COLUMNS = ["id", "revision", "kind", "period", "date", "period_start", "period_end", "number", "issuer", "recipient", "account", "category", "net", "tax", "gross", "currency", "file", "sha256"]


def package_data(p, detailed=False):
    data = {"id": str(p.id), "company_id": p.company_id, "periods": p.periods, "version": p.version,
            "parent_id": str(p.parent_id) if p.parent_id else None, "sha256": p.sha256, "size": p.size,
            "created_at": p.created_at.isoformat()}
    if detailed:
        data["snapshot"] = p.snapshot
        data["items"] = list(p.items.values("document_id", "revision", "archive_path", "sha256", "metadata"))
    return data


def get_package(actor, package_id, permission="read"):
    try:
        p = Package.objects.get(id=package_id)
    except (Package.DoesNotExist, ValueError):
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
    docs = Document.objects.filter(company=company).filter(Q(period__in=periods) | Q(period="")).order_by("period", "id")
    if lock:
        docs = docs.select_for_update()
    included, excluded, unchanged = [], [], []
    prior = {str(item.document_id): item.revision for item in parent.items.all()} if parent else {}
    # A chain of supplements compares against all previous delivered revisions.
    ancestor = parent.parent if parent else None
    while ancestor:
        for item in ancestor.items.all():
            prior.setdefault(str(item.document_id), item.revision)
        ancestor = ancestor.parent
    for doc in docs:
        data = document_data(doc)
        if doc.period not in periods:
            excluded.append({"document": data, "reason": "Übergabemonat ungeklärt"})
        elif doc.duplicate_of_id:
            excluded.append({"document": data, "reason": "Als Dublette markiert"})
        elif doc.status != "ready" or doc.issues:
            excluded.append({"document": data, "reason": "; ".join(doc.issues) or "Noch nicht bestätigt"})
        elif prior.get(str(doc.id)) == doc.version:
            unchanged.append(str(doc.id))
        else:
            data["archive_path"] = storage.desired_path(doc)
            data["account_name"] = doc.account.name if doc.account_id else ""
            data["category_name"] = doc.category.name if doc.category_id else ""
            included.append(data)
    inbox = []
    try:
        actor.require_inbox(actor.user_id)
        inbox = [str(x) for x in Document.objects.filter(company__isnull=True, inbox_owner_id=actor.user_id).values_list("id", flat=True)]
    except DomainError:
        pass
    return {"company": {"id": company.id, "name": company.name, "folder": company.folder}, "periods": periods,
            "parent_id": str(parent.id) if parent else None, "recipients": company.recipients,
            "allow_open_issues": company.allow_open_issues, "documents": included, "excluded": excluded,
            "unassigned_inbox": inbox, "unchanged": unchanged, "count": len(included),
            "bytes": sum(d["size"] for d in included), "by_kind": dict(Counter(d["kind"] for d in included))}


def spreadsheet_safe(value):
    value = "" if value is None else str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


def overview_row(d):
    m = d["metadata"]
    values = {"id": d["id"], "revision": d["version"], "kind": d["kind"], "period": d["period"],
              "file": d["archive_path"], "sha256": d["sha256"], "account": d["account_name"], "category": d["category_name"], **m}
    return [spreadsheet_safe(values.get(c)) for c in COLUMNS]


def build_archive(snapshot, package_id, version):
    files = {}
    originals = {}
    for d in snapshot["documents"]:
        doc = Document.objects.get(id=d["id"])
        data = storage.read_original(doc)
        files[d["archive_path"]] = data
        originals[d["archive_path"]] = {"document_id": d["id"], "revision": d["version"], "sha256": d["sha256"]}
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
        body = (f"Unterlagen für {snapshot['company']['name']} – {period}\nPaket {package_id}, Version {version}\n"
                f"Nachtrag zu: {snapshot['parent_id'] or 'keinem Vorgänger'}\nEmpfänger: {', '.join(snapshot['recipients'])}\n"
                f"{len(docs)} Originale enthalten. Unveränderte Dokumente aus Vorgängern: {len(snapshot['unchanged'])}.\n"
                f"Offene/ausgeschlossene Unterlagen:\n{notes or 'Keine'}\n"
                f"Nicht zugeordnete Eingangsdokumente: {len(snapshot['unassigned_inbox'])}\n"
                "Dies ist eine Unterlagensammlung, keine bestätigte Buchhaltung.\n")
        files[f"{base}/Begleitschreiben.txt"] = body.encode()
        manifest = [{"path": name, "sha256": storage.checksum(data), "bytes": len(data), **originals.get(name, {})}
                    for name, data in sorted(files.items()) if name.startswith(base + "/") and not name.endswith("/")]
        files[f"{base}/Inhaltsliste.json"] = json.dumps({"package_id": str(package_id), "version": version, "files": manifest}, ensure_ascii=False, indent=2).encode()
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
        company = actor.companies("process").select_for_update().get(id=company_id)
        prior = Package.objects.filter(company=company, idempotency_key=idempotency_key).first()
        if prior:
            if prior.periods != sorted(set(periods)) or str(prior.parent_id or "") != str(parent_id or ""):
                raise DomainError("Idempotenzschlüssel gehört zu einem anderen Paketauftrag.", 409)
            return package_data(prior, True)
        snapshot = package_preview(actor, company_id, periods, parent_id, lock=True)
        version = (Package.objects.filter(company=company).aggregate(n=Max("version"))["n"] or 0) + 1
        pid = uuid.uuid4()
        data = build_archive(snapshot, pid, version)
        relative = f"_packages/{pid}.zip"
        storage.atomic_write(relative, data)
        p = Package.objects.create(id=pid, company=company, periods=snapshot["periods"], version=version,
                                   parent_id=parent_id, snapshot=snapshot, path=relative, sha256=storage.checksum(data),
                                   size=len(data), actor_id=actor.user_id, idempotency_key=idempotency_key)
        PackageItem.objects.bulk_create([PackageItem(package=p, document_id=d["id"], revision=d["version"],
                                                     archive_path=d["archive_path"], sha256=d["sha256"], metadata=d) for d in snapshot["documents"]])
        for period in p.periods:
            storage.ensure_month(company, period)
    return package_data(p, True)


def package_bytes(package):
    data = storage.path(package.path).read_bytes()
    if storage.checksum(data) != package.sha256:
        raise DomainError("Paket-Prüfsumme stimmt nicht.", 409)
    return data
