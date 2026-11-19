"""Handover names only: never rename originals or infer facts from upload names."""

import re
import unicodedata
from pathlib import PurePosixPath

from .auth import DomainError

MAX_BYTES = 240
LABELS = {
    "incoming_invoice": "Rechnung",
    "incoming_credit": "Gutschrift",
    "outgoing_invoice": "Rechnung",
    "outgoing_cancellation": "Storno",
    "bank_pdf": "Kontoauszug",
    "bank_camt": "CAMT",
}
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?: *\.| *$)", re.I)


def extension(doc):
    # Preserve a compatible upload extension (including .jpeg), never a misleading one.
    uploaded = PurePosixPath(doc.original_name.replace("\\", "/")).suffix.lower()
    compatible = {
        "application/pdf": {".pdf"},
        "application/xml": {".xml"},
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
    }
    if uploaded in compatible.get(doc.media_type, set()):
        return uploaded
    # original_path records the format detected from the bytes.
    return PurePosixPath(doc.original_path).suffix.lower()


def component(value):
    value = unicodedata.normalize("NFC", str(value or ""))
    value = "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)
    value = re.sub(r'[<>:"/\\|?*]', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    while ".." in value:
        value = value.replace("..", "-")
    if RESERVED.match(value):
        value = "_" + value
    return value


def filename(stem, ext, suffix=""):
    stem = component(stem) or "Dokument"
    budget = MAX_BYTES - len((suffix + ext).encode("utf-8"))
    stem = stem.encode("utf-8")[:budget].decode("utf-8", errors="ignore").rstrip(" .")
    return (stem or "Dokument") + suffix + ext


def with_suffix(name, ext, suffix):
    return filename(name[: -len(ext)] if ext else name, ext, suffix)


def fallback(doc):
    original = doc.original_name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = original.rsplit(".", 1)[0] if "." in original else original
    return filename(stem, extension(doc), "-" + doc.id.hex[:12])


def proposal(doc):
    m = doc.metadata
    used = set()

    def field(key):
        used.add(key)
        return m.get(key)

    kind = doc.kind
    label = LABELS.get(kind)
    identifier = None
    account = None
    needs_account = kind in {"bank_pdf", "bank_camt"}
    if kind in {"bank_pdf", "bank_camt", "security_pdf"}:
        partner = field("bank_short_name")
        if kind in {"bank_pdf", "bank_camt"}:
            date = field("period_end")
        else:
            label = field("subtype")
            # A valuation statement must never silently use its creation date.
            needs_account = bool(
                label
                and component(label).casefold() in {"depotaufstellung", "depotauszug", "stichtagsaufstellung"}
            )
            date = field("valuation_date" if needs_account else "date")
            identifier = field("isin")
        if needs_account:
            account = doc.account.name if doc.account_id else None  # Known company/account mapping.
    else:
        partner_key = "recipient" if kind.startswith("outgoing_") else "issuer"
        partner = field("confirmed_partner_name") or field(partner_key)
        date = field("date")
        if kind == "receipt":
            label = field("subtype") or "Beleg"
    identifier = identifier or field("number")
    uncertain = [key for key in used if m.get("evidence", {}).get(key, {}).get("uncertain")]
    missing = not (date and component(partner) and component(label)) or (needs_account and not account)
    if missing or uncertain:
        warning = "Übergabename: unzureichende Metadaten; sicherer Originalname mit Kennung."
        if uncertain:
            warning = "Übergabename: unsichere Felder: " + ", ".join(sorted(uncertain)) + "."
        return {"name": fallback(doc), "source": "fallback", "warning": warning}
    # All dates have passed the Metadata schema. No day is invented from doc.period.
    parts = [date, partner, account, label, identifier]
    return {
        "name": filename(" ".join(str(p) for p in parts if p), extension(doc)),
        "source": "generated",
        "warning": "",
    }


def validate_manual(doc, value):
    if not isinstance(value, str) or not value.strip():
        raise DomainError("Übergabename darf nicht leer sein; null setzt auf den Vorschlag zurück.")
    if "/" in value or "\\" in value or ".." in value or re.match(r"^\s*(?:[A-Za-z]:|[.~])", value):
        raise DomainError("Übergabename muss ein Dateiname sein, kein Pfad.")
    ext = extension(doc)
    if not value.lower().endswith(ext):
        raise DomainError("Die tatsächliche Dateiendung darf nicht geändert werden.")
    try:
        result = filename(value[: -len(ext)], ext)
        result.encode("utf-8")
    except UnicodeError as e:
        raise DomainError("Ungültiges Unicode im Übergabenamen.") from e
    return result


def selected(doc):
    p = proposal(doc)
    return {
        "name": doc.handover_name or fallback(doc),
        "source": doc.name_source or "fallback",
        "warning": (
            p["warning"]
            or (
                "Übergabename noch nicht übernommen; Vorschau und expliziten Backfill verwenden."
                if not doc.handover_name
                else ""
            )
        )
        if doc.name_source != "manual"
        else "",
        "proposal": p["name"],
        "proposal_source": p["source"],
    }


def scope(doc):
    from .storage import KIND_FOLDER

    return (doc.company_id or ("inbox", doc.inbox_owner_id), doc.period, KIND_FOLDER.get(doc.kind, ""))


def collision_key(value):
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", value).casefold())


def resolve(documents, proposed_ids=()):
    """Resolve the complete folder namespace, independent of input ordering.

    Suffix every member of a collision group, extending ID prefixes as necessary.
    Include collisions against user-entered suffixes, not just initial base names.
    """
    docs = {str(d.id): d for d in documents}
    values = {key: selected(d) for key, d in docs.items()}
    for key in proposed_ids:
        if docs[key].name_source != "manual":
            p = proposal(docs[key])
            values[key].update(name=p["name"], source=p["source"], warning=p["warning"])
    lengths = {key: 0 for key in docs}
    while True:
        names = {
            key: with_suffix(v["name"], extension(docs[key]), "-" + docs[key].id.hex[: lengths[key]])
            if lengths[key]
            else v["name"]
            for key, v in values.items()
        }
        groups = {}
        for key, name in names.items():
            groups.setdefault((scope(docs[key]), collision_key(name)), []).append(key)
        conflicts = [group for group in groups.values() if len(group) > 1]
        if not conflicts:
            return {
                key: {**v, "name": names[key], "conflict": bool(lengths[key])} for key, v in values.items()
            }
        for group in conflicts:
            for key in group:
                lengths[key] = 8 if not lengths[key] else lengths[key] + 4
                if lengths[key] > 32:
                    raise DomainError("Übergabenamen können nicht eindeutig vergeben werden.", 409)


def context_many(documents):
    from django.db.models import Q

    from .models import Document

    documents = list(documents)
    query = Q(pk__in=[])
    scopes = {(d.company_id, d.period, d.inbox_owner_id if not d.company_id else None) for d in documents}
    for company_id, period, owner_id in scopes:
        group = Q(company_id=company_id, period=period)
        if not company_id:
            group &= Q(inbox_owner_id=owner_id)
        query |= group
    peers = {str(d.id): d for d in Document.objects.filter(query).select_related("account")}
    peers.update({str(d.id): d for d in documents})
    return list(peers.values())


def context(doc):
    return context_many([doc])


def data(doc, resolved=None):
    value = (resolve(context(doc)) if resolved is None else resolved)[str(doc.id)]
    return {
        "handover_name": doc.handover_name,
        "proposed_name": value["proposal"],
        "effective_name": value["name"],
        "name_source": value["source"],
        "name_warning": value["warning"],
        "name_conflict": value["conflict"],
    }
