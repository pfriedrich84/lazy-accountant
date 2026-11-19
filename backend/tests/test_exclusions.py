"""Reversible exclusions share one contract across services, REST and MCP.

Only synthetic files/mailboxes. No real mail connections or production storage.
"""

import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from threading import Barrier
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction

from accounting import mail, packages, services, storage, transfers
from accounting.auth import Actor, DomainError, issue_token, token_actor
from accounting.demo import sample_image, sample_pdf
from accounting.models import (
    AccessToken,
    Document,
    FileOperation,
    ImportSource,
    Membership,
    Package,
    ProcessingClaim,
)
from tests.test_documents import result
from tests.test_packages_mail import configured_mailbox

pytestmark = pytest.mark.django_db


def change(actor, doc, excluded=True, key=None, reason="Signaturgrafik, kein Beleg"):
    return services.change_document_exclusion(
        actor,
        doc["id"],
        {
            "base_version": doc["version"],
            "reason": reason,
            "idempotency_key": key or f"{doc['id']}:{doc['version']}:{excluded}",
        },
        excluded=excluded,
    )


def test_roundtrip_without_fabricated_assignment_and_no_cascade(actor, companies):
    image = sample_image()
    d = services.ingest(actor, "image001.png", image)["document"]
    original_issues = d["issues"]
    excluded = change(actor, d)["document"]
    assert excluded["company_id"] is None and excluded["kind"] == excluded["period"] == ""
    assert excluded["status"] == d["status"] and excluded["issues"] == original_issues
    assert excluded["is_excluded"] and excluded["excluded_by_id"] == actor.user_id
    assert excluded["excluded_at"] and excluded["version"] == d["version"] + 1
    assert excluded["filed_path"].startswith(f"_excluded/inbox-{actor.user_id}/")
    assert services.readable_document(actor, d["id"], 1, image=True)
    restored = change(actor, excluded, False, reason="Doch ein Beleg")["document"]
    assert not restored["is_excluded"] and not restored["exclusion_reason"]
    assert restored["excluded_by_id"] is restored["excluded_at"] is None
    assert restored["status"] == "new" and restored["issues"] == original_issues
    assert restored["filed_path"] == d["filed_path"]
    doc = Document.objects.get(id=d["id"])
    assert storage.read_original(doc) == image
    assert list(doc.revisions.values_list("source", "reason")) == [
        ("upload", ""),
        ("exclude", "Signaturgrafik, kein Beleg"),
        ("restore", "Doch ein Beleg"),
    ]

    # Another image with the same name is not excluded by a filename rule.
    other = services.ingest(actor, "image001.png", sample_pdf(["real image receipt"]))["document"]
    assert not other["is_excluded"]
    c = companies[0]
    a = services.ingest(actor, "invoice.pdf", sample_pdf(["invoice"]), c.id)["document"]
    b = services.ingest(actor, "signature.png", image, c.id)["document"]
    a = services.save_result(actor, result(a, c.id, related_ids=[b["id"]], approve=True))
    change(actor, b)
    unchanged = services.document_data(services.get_document(actor, a["id"]), True)
    assert unchanged["version"] == a["version"]
    assert unchanged["related_ids"] == [b["id"]] and not unchanged["is_excluded"]


def test_materialized_month_and_restore_validation(actor, companies):
    c = companies[0]
    d = services.ingest(actor, "receipt.pdf", sample_pdf(["receipt"]), c.id)["document"]
    d = services.save_result(actor, result(d, c.id, approve=True))
    old = d["filed_path"]
    excluded = change(actor, d)["document"]
    assert not storage.path(old).exists()
    assert excluded["filed_path"].startswith(f"_excluded/company-{c.id}/")
    assert services.month_folders(actor, c.id, "2026-10")["total"] == 0
    restored = change(actor, excluded, False)["document"]
    assert restored["status"] == "ready" and restored["filed_path"] == old
    excluded = change(actor, restored)["document"]
    with patch("accounting.services.validation_issues", return_value=["Neue Fachprüfung"]):
        restored = change(actor, excluded, False)["document"]
    assert restored["status"] == "review" and restored["issues"] == ["Neue Fachprüfung"]
    call_command("verify_integrity")


def test_idempotent_retry_noop_conflict_and_historical_replay(actor):
    d = services.ingest(actor, "s.png", sample_image())["document"]
    first = change(actor, d, key="exclude-one")
    assert change(actor, d, key="exclude-one") == first
    assert Document.objects.get(id=d["id"]).revisions.count() == 2
    with pytest.raises(DomainError) as error:
        change(actor, d, key="exclude-one", reason="different")
    assert error.value.status == 409
    with pytest.raises(DomainError) as error:
        change(actor, d, key="new-key")
    assert error.value.status == 409
    noop = change(actor, first["document"], key="noop")
    assert not noop["changed"] and noop["document"]["version"] == first["document"]["version"]
    restored = change(actor, first["document"], False)["document"]
    assert change(actor, d, key="exclude-one") == first  # Not a new exclusion!
    assert not Document.objects.get(id=d["id"]).is_excluded
    assert change(actor, restored, False)["changed"] is False
    another = services.ingest(actor, "other.pdf", sample_pdf(["another"]))["document"]
    with pytest.raises(DomainError) as error:
        change(actor, another, key="exclude-one")
    assert error.value.status == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "   "},
        {"reason": "x" * 1001},
        {"reason": "bad\x00text"},
        {"reason": "bad\ud800text"},
        {"idempotency_key": "bad\x00key"},
        {"idempotency_key": ""},
        {"idempotency_key": "x" * 121},
        {"base_version": 0},
        {"base_version": True},
        {"base_version": "1"},
        {"company_id": 1},
        {"excluded_by_id": 1},
    ],
)
def test_command_validation(actor, payload):
    d = services.ingest(actor, "s.png", sample_image())["document"]
    with pytest.raises(DomainError) as error:
        services.change_document_exclusion(
            actor,
            d["id"],
            {
                "base_version": 1,
                "reason": "test",
                "idempotency_key": "key",
                **payload,
            },
            excluded=True,
        )
    assert error.value.status == 400
    assert Document.objects.get(id=d["id"]).version == 1


def test_save_cannot_bypass_exclusion_and_claim_is_version_bound(actor, companies):
    c = companies[0]
    d = services.ingest(actor, "s.png", sample_image(), c.id)["document"]
    transfers.claim_document(actor, d["id"], "agent", d["version"])
    excluded = change(actor, d)["document"]
    assert not ProcessingClaim.objects.filter(document_id=d["id"]).exists()
    with pytest.raises(DomainError, match="inzwischen"):
        services.save_result(actor, result(d, c.id))
    with pytest.raises(DomainError, match="wiederherstellen"):
        services.save_result(actor, result(excluded, c.id))
    with pytest.raises(DomainError, match="wiederherstellen"):
        transfers.claim_document(actor, d["id"], "agent", excluded["version"])
    restored = change(actor, excluded, False)["document"]
    transfers.claim_document(actor, d["id"], "new-agent", restored["version"])


def test_filters_pagination_dedupe_and_company_scope(actor, companies):
    c, other = companies
    docs = [services.ingest(actor, f"{i}.pdf", sample_pdf([str(i)]), c.id)["document"] for i in range(4)]
    change(actor, docs[0])
    assert services.list_documents(actor, company_id=c.id, status="open")["total"] == 3
    assert services.list_documents(actor, company_id=c.id, exclusion="excluded")["total"] == 1
    page = services.list_documents(actor, company_id=c.id, exclusion="all", limit=2)
    page2 = services.list_documents(
        actor, company_id=c.id, exclusion="all", limit=2, cursor=page["next_cursor"]
    )
    assert page["total"] == page2["total"] == 4
    assert {d["id"] for d in page["results"]}.isdisjoint(d["id"] for d in page2["results"])
    assert page2["next_cursor"] is None
    with pytest.raises(DomainError):
        services.list_documents(actor, exclusion="invalid")
    uploaded = services.ingest(actor, "new-name.pdf", sample_pdf(["0"]), c.id)
    assert uploaded["duplicate"] and uploaded["document"]["id"] == docs[0]["id"]
    assert uploaded["document"]["is_excluded"]
    fresh = services.ingest(actor, "new-name.pdf", sample_pdf(["0"]), other.id)
    assert not fresh["duplicate"] and not fresh["document"]["is_excluded"]
    # An explicit existing duplicate is still visible to duplicate hints.
    obj = Document.objects.get(id=docs[1]["id"])
    obj.sha256 = docs[0]["sha256"]
    obj.save()
    assert services.duplicate_hints(actor, docs[1]["id"])[0]["is_excluded"]


def test_rest_scopes_original_and_permission_revocation(actor, client, companies):
    c, other = companies
    d = services.ingest(actor, "s.png", sample_image(), c.id)["document"]
    payload = {"base_version": 1, "reason": "Signatur", "idempotency_key": "rest"}
    url = f"/api/documents/{d['id']}/"
    response = client.post(url + "exclude/", payload, format="json")
    assert response.status_code == 200 and response.json()["changed"]
    assert client.get(url + "original/").status_code == 200
    assert client.get("/api/documents/", {"exclusion": "excluded"}).json()["total"] == 1
    assert client.get("/api/documents/", {"exclusion": "all"}).json()["total"] == 1
    assert client.get("/api/documents/", {"exclusion": "bad"}).status_code == 400
    token = issue_token(actor, "read", [c.id], ["read"])["token"]
    client.logout()
    client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
    assert client.post(url + "exclude/", payload, format="json").status_code == 404
    token = issue_token(actor, "wrong", [other.id], ["read", "process"])["token"]
    client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
    assert client.post(url + "restore/", {**payload, "base_version": 2}, format="json").status_code == 404
    token = issue_token(actor, "process", [c.id], ["read", "process"])["token"]
    client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
    Membership.objects.filter(user_id=actor.user_id, company=c).update(can_process=False)
    assert client.post(url + "exclude/", payload, format="json").status_code == 404  # retry reauthorizes
    AccessToken.objects.filter(digest=hashlib.sha256(token.encode()).hexdigest()).update(revoked=True)
    assert client.post(url + "exclude/", payload, format="json").status_code in {401, 403}


@pytest.mark.parametrize("scopes", [["read", "process"], ["read", "inbox"]])
def test_inbox_requires_owner_and_both_scopes(actor, scopes):
    d = services.ingest(actor, "s.png", sample_image())["document"]
    scoped = token_actor(issue_token(actor, "inbox", [], scopes)["token"])
    with pytest.raises(DomainError):
        change(scoped, d)
    stranger = Actor(get_user_model().objects.create_user("stranger").id)
    with pytest.raises(DomainError) as error:
        change(stranger, d)
    assert error.value.status == 404
    allowed = token_actor(issue_token(actor, "ok", [], ["inbox", "process", "read"])["token"])
    assert change(allowed, d)["changed"]


def test_atomic_rollback_and_database_constraint(actor):
    d = services.ingest(actor, "s.png", sample_image())["document"]
    with patch("accounting.storage.journal", side_effect=RuntimeError("rollback")):
        with pytest.raises(RuntimeError):
            change(actor, d, key="retry")
    obj = Document.objects.get(id=d["id"])
    assert obj.version == 1 and not obj.is_excluded and obj.revisions.count() == 1
    assert change(actor, d, key="retry")["changed"]
    with pytest.raises(IntegrityError), transaction.atomic():
        Document.objects.filter(id=d["id"]).update(exclusion_reason="")


def test_receipt_keeps_committed_state_when_restore_happens_during_reconciliation(actor):
    d = services.ingest(actor, "s.png", sample_image())["document"]
    reconcile = storage.reconcile
    interleaved = False

    def restore_before_return(document_id):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            current = services.document_data(services.get_document(actor, document_id))
            change(actor, current, False, key="interleaved-restore")
        reconcile(document_id)

    with patch("accounting.storage.reconcile", side_effect=restore_before_return):
        excluded = change(actor, d, key="interleaved-exclude")
    assert excluded["document"]["version"] == 2 and excluded["document"]["is_excluded"]
    assert not Document.objects.get(id=d["id"]).is_excluded
    assert change(actor, d, key="interleaved-exclude") == excluded


def test_pending_journal_fast_roundtrip_recovers_original(actor, companies):
    c = companies[0]
    d = services.ingest(actor, "s.pdf", sample_pdf(["journal"]), c.id)["document"]
    with patch("accounting.storage.atomic_write", side_effect=OSError("disk full")):
        excluded = change(actor, d)["document"]
        restored = change(actor, excluded, False)["document"]
    assert excluded["filing_status"] == "pending"
    assert restored["filed_path"] == d["filed_path"]
    assert restored["filing_status"] == "pending" and "disk full" in restored["filing_error"]
    assert FileOperation.objects.filter(document_id=d["id"], version=3, status="pending").exists()
    storage.reconcile()
    obj = Document.objects.get(id=d["id"])
    assert obj.filed_path == storage.desired_path(obj)
    assert storage.path(obj.filed_path).read_bytes() == storage.read_original(obj)
    assert not FileOperation.objects.filter(document=obj, status="pending").exists()
    call_command("verify_integrity")


def test_imap_reimports_keep_exclusion_and_provenance(actor, companies):
    mailbox = configured_mailbox(companies[0])
    msg = EmailMessage()
    msg["From"] = "supplier@example.test"
    msg["To"] = "inbox@example.test"
    msg.set_content("Synthetic signature")
    msg.add_attachment(sample_image(), maintype="image", subtype="png", filename="image001.png")
    raw = msg.as_bytes()
    mail.import_message(actor, mailbox, "validity-1", "1", raw)
    doc = Document.objects.get()
    change(actor, services.document_data(doc))
    mail.import_message(actor, mailbox, "validity-1", "1", raw)
    mail.import_message(actor, mailbox, "validity-2", "1", raw)
    msg["Subject"] = "Different mail, same signature"
    mail.import_message(actor, mailbox, "validity-2", "2", msg.as_bytes())
    assert Document.objects.count() == 1
    assert Document.objects.get().is_excluded
    assert ImportSource.objects.filter(document=doc).count() == 3
    assert services.list_documents(actor, status="open")["total"] == 0


def test_nonblocking_package_exclusions_inbox_privacy_and_legacy(actor, companies):
    c = companies[0]
    c.allow_open_issues = False
    c.save()
    configured_mailbox(c)
    d = services.ingest(actor, "company-signature.png", sample_image(), c.id)["document"]
    personal = services.ingest(actor, "private-personal-name.png", sample_image())["document"]
    change(actor, d, reason="Company signature")
    change(actor, personal, reason="PRIVATE REASON")
    preview = packages.package_preview(actor, c.id, ["2026-10"])
    assert preview["excluded"] == preview["unassigned_inbox"] == []
    assert len(preview["intentional_exclusions"]) == 1
    assert preview["excluded_inbox"] == [personal["id"]]
    package = packages.create_package(actor, c.id, ["2026-10"], "exclusions-only")
    obj = Package.objects.get(id=package["id"])
    assert obj.snapshot["schema_version"] == 2 and "excluded_inbox" not in obj.snapshot
    assert not obj.items.exists()
    data = packages.package_bytes(obj)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert not any(name.endswith(".png") for name in archive.namelist())
        text = archive.read(f"{c.folder}/2026/10/Begleitschreiben.txt").decode()
        assert "Company signature" in text and "ohne Monatszuordnung" in text
        assert "PRIVATE" not in text and "private-personal-name" not in text
    assert mail.queue_dispatch(actor, obj.id, "send-no-block")["id"]
    # Historical v1 rules remain frozen even if the live document is excluded.
    legacy = packages.create_package(actor, c.id, ["2026-10"], "legacy")
    legacy_obj = Package.objects.get(id=legacy["id"])
    legacy_obj.snapshot = {
        k: v
        for k, v in legacy_obj.snapshot.items()
        if k
        not in {
            "schema_version",
            "intentional_exclusions",
            "exclusion_changes",
            "document_states",
        }
    }
    legacy_obj.snapshot["excluded"] = [{"document": d, "reason": "historically unresolved"}]
    legacy_obj.save()
    with pytest.raises(DomainError, match="offene Punkte"):
        mail.queue_dispatch(actor, legacy_obj.id, "legacy-still-blocked")
    active = services.ingest(actor, "real.pdf", sample_pdf(["unresolved"]), c.id)["document"]
    blocked = packages.create_package(actor, c.id, ["2026-10"], "active-blocks")
    with pytest.raises(DomainError, match="offene Punkte"):
        mail.queue_dispatch(actor, blocked["id"], "blocked")
    assert active["id"] in {x["document"]["id"] for x in blocked["snapshot"]["excluded"]}


def test_supplement_chain_reports_exclusion_once_and_restore(actor, companies):
    c = companies[0]
    d = services.ingest(actor, "receipt.pdf", sample_pdf(["chain"]), c.id)["document"]
    d = services.save_result(actor, result(d, c.id, approve=True))
    original = packages.create_package(actor, c.id, ["2026-10"], "original")
    original_obj = Package.objects.get(id=original["id"])
    data, snapshot = packages.package_bytes(original_obj), json.dumps(original_obj.snapshot, sort_keys=True)
    # Exercise a true v1 parent (only items are available as baseline).
    original_obj.snapshot = {
        k: v
        for k, v in original_obj.snapshot.items()
        if k
        not in {
            "schema_version",
            "intentional_exclusions",
            "document_states",
            "exclusion_changes",
        }
    }
    original_obj.save()
    snapshot = json.dumps(original_obj.snapshot, sort_keys=True)
    configured_mailbox(c)
    dispatch = mail.queue_dispatch(actor, original_obj.id, "existing-dispatch")
    excluded = change(actor, d)["document"]
    assert excluded["packaged_in"] == [{"id": original["id"], "version": original["version"], "revision": 2}]
    first = packages.create_package(actor, c.id, ["2026-10"], "first", original["id"])
    changes = first["snapshot"]["exclusion_changes"]
    assert len(changes) == 1 and changes[0]["action"] == "exclude"
    assert changes[0]["previous_package_id"] == original["id"]
    assert not first["items"]
    second = packages.create_package(actor, c.id, ["2026-10"], "second", first["id"])
    assert second["snapshot"]["exclusion_changes"] == []
    restored = change(actor, excluded, False, reason="Restore reason")["document"]
    third = packages.create_package(actor, c.id, ["2026-10"], "third", second["id"])
    assert len(third["items"]) == 1
    assert third["snapshot"]["exclusion_changes"][0]["reason"] == "Restore reason"
    assert third["snapshot"]["exclusion_changes"][0]["new_revision"] == restored["version"]
    fourth = packages.create_package(actor, c.id, ["2026-10"], "fourth", third["id"])
    assert fourth["snapshot"]["exclusion_changes"] == [] and fourth["items"] == []
    original_obj.refresh_from_db()
    assert packages.package_bytes(original_obj) == data
    assert json.dumps(original_obj.snapshot, sort_keys=True) == snapshot
    assert storage.checksum(data) == original_obj.sha256
    from accounting.models import Dispatch

    assert mail.dispatch_data(Dispatch.objects.get(id=dispatch["id"])) == dispatch


@pytest.mark.django_db(transaction=True)
def test_parallel_same_key_and_package_serialization(actor, companies):
    if connection.vendor != "postgresql":
        pytest.skip("Real row-lock/concurrency contract requires PostgreSQL")
    c = companies[0]
    d = services.ingest(actor, "s.png", sample_image(), c.id)["document"]
    barrier = Barrier(2)

    def exclude():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return change(actor, d, key="parallel")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = [f.result(timeout=30) for f in [pool.submit(exclude), pool.submit(exclude)]]
    assert a["document"]["version"] == b["document"]["version"] == 2
    assert Document.objects.get(id=d["id"]).revisions.count() == 2
    # Race restore against a package. The snapshot must be internally consistent.
    barrier = Barrier(2)

    def restore():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return change(actor, a["document"], False)
        finally:
            close_old_connections()

    def package():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return packages.create_package(actor, c.id, ["2026-10"], "parallel-package")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        r, p = pool.submit(restore), pool.submit(package)
        r.result(timeout=30)
        snapshot = p.result(timeout=30)["snapshot"]
    states = snapshot["document_states"]
    assert len(states) == 1
    assert bool(snapshot["intentional_exclusions"]) == states[0]["is_excluded"]
    assert bool(snapshot["excluded"]) != states[0]["is_excluded"]
