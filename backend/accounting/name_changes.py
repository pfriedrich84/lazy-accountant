"""Explicit, audited name-only operations shared by REST and MCP."""

import uuid

from django.contrib.auth import get_user_model
from django.db import transaction

from . import naming, services, storage
from .auth import DomainError
from .models import Company, Revision
from .security import require_clean


def validate_ids(document_ids):
    if not isinstance(document_ids, list) or not 1 <= len(document_ids) <= 100:
        raise DomainError("Ein bis 100 Dokument-IDs auswählen; weitere Seiten separat vorschauen.")
    try:
        canonical = [uuid.UUID(identifier) for identifier in document_ids]
    except (ValueError, TypeError, AttributeError) as e:
        raise DomainError("Ungültige Dokument-ID.") from e
    if len(set(canonical)) != len(document_ids):
        raise DomainError("Dokument-IDs dürfen nicht doppelt vorkommen.")


def preview(actor, document_ids):
    validate_ids(document_ids)
    docs = [services.get_document(actor, identifier) for identifier in document_ids]
    for doc in docs:
        require_clean(doc)
    peers = naming.context_many(docs)
    proposed = naming.resolve(peers, [str(d.id) for d in docs])
    old = naming.resolve(peers)
    return [
        {
            "document_id": str(d.id),
            "base_version": d.version,
            "original_name": d.original_name,
            "old_name": old[str(d.id)]["name"],
            "new_name": proposed[str(d.id)]["name"],
            "name_source": proposed[str(d.id)]["source"],
            "warning": proposed[str(d.id)]["warning"],
            "conflict": proposed[str(d.id)]["conflict"],
            "manual_protected": d.name_source == "manual",
        }
        for d in docs
    ]


def change(actor, entries, *, manual=False):
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        raise DomainError("Versionierte Dokumentliste erforderlich.")
    identifiers = [e.get("document_id") for e in entries]
    validate_ids(identifiers)
    initial = [services.get_document(actor, identifier, "process") for identifier in identifiers]
    changed = []
    with transaction.atomic():
        # Same lock order as save_result and package creation; all-or-nothing batch.
        get_user_model().objects.select_for_update().get(id=actor.user_id)
        list(
            Company.objects.filter(id__in={d.company_id for d in initial if d.company_id})
            .order_by("id")
            .select_for_update()
        )
        docs = {
            str(d.id): services.get_document(actor, d.id, "process", lock=True)
            for d in sorted(initial, key=lambda d: str(d.id))
        }
        for entry, initial_doc in zip(entries, initial, strict=True):
            doc = docs[str(initial_doc.id)]
            require_clean(doc)
            if type(entry.get("base_version")) is not int or entry["base_version"] != doc.version:
                raise DomainError(
                    "Dokument wurde inzwischen geändert. Vorschau neu laden.",
                    409,
                    {"document_id": str(doc.id), "current_version": doc.version},
                )
            if not manual and doc.name_source == "manual":
                continue
            if manual and entry.get("name") is not None:
                name = naming.validate_manual(doc, entry["name"])
                source = "manual"
            else:
                proposed = naming.proposal(doc)
                name, source = proposed["name"], proposed["source"]
            if (name, source) == (doc.handover_name, doc.name_source):
                continue
            doc.handover_name, doc.name_source = name, source
            doc.version += 1
            doc.save(update_fields=["handover_name", "name_source", "version", "updated_at"])
            changed.append(doc)
        for doc in changed:
            Revision.objects.create(
                document=doc,
                version=doc.version,
                base_version=doc.version - 1,
                actor_id=actor.user_id,
                source="name:manual" if manual else "name:backfill",
                snapshot=services.document_data(doc),
            )
            # Keep any pending internal filing operation alive at this revision.
            storage.journal(doc)
    for doc in changed:
        storage.reconcile(doc.id)
    return [services.document_data(services.get_document(actor, d.id), True) for d in initial]


def set_name(actor, document_id, base_version, name):
    return change(
        actor, [{"document_id": document_id, "base_version": base_version, "name": name}], manual=True
    )[0]
