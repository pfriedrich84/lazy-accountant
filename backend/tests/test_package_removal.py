from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from accounting import jobs, mail, package_removal as removal, packages, services, storage
from accounting.auth import Actor, DomainError, issue_token
from accounting.demo import seed_month
from accounting.models import (
    BankTransaction,
    Document,
    Revision,
    ImportSource,
    Job,
    Membership,
    Package,
    PackageRemoval,
    PaymentAllocation,
)
from test_packages_mail import configured_mailbox

pytestmark = pytest.mark.django_db


def make_package(user, actor, companies):
    company = companies[0]
    seed_month(user, company, classified=True)
    return company, packages.create_package(actor, company.id, ["2026-10"], "old")


def remove(actor, company, package, **kwargs):
    return removal.remove(
        actor,
        company.id,
        package["id"],
        kwargs.get("version", package["version"]),
        kwargs.get("reason", "Explicit user request"),
        kwargs.get("key", "remove"),
    )


def source_state():
    return [
        list(model.objects.order_by("pk").values())
        for model in (Document, Revision, BankTransaction, PaymentAllocation, ImportSource)
    ]


def test_remove_preserves_sources_and_recreates_current_snapshot(user, actor, companies, client):
    company, package = make_package(user, actor, companies)
    before = source_state()
    snapshot = package["snapshot"]
    assert removal.preview(actor, company.id, package["id"])["can_remove"]
    assert remove(actor, company, package)["status"] == "completed"
    assert source_state() == before
    old = Package.objects.get(id=package["id"])
    assert old.snapshot == snapshot and old.items.count() == 8
    assert not storage.path(old.path).exists()
    assert remove(actor, company, package)["status"] == "completed"
    assert packages.create_package(actor, company.id, ["2026-10"], "old")["removed"]
    with pytest.raises(DomainError) as error:
        packages.package_bytes(old)
    assert error.value.status == 410
    with pytest.raises(DomainError):
        mail.queue_dispatch(actor, old.id, "no-send")
    with pytest.raises(DomainError):
        packages.package_preview(actor, company.id, ["2026-10"], old.id)
    client.force_login(user)
    assert client.get(f"/api/packages/{old.id}/download/").status_code == 410
    assert client.get(f"/api/packages/?company_id={company.id}").json() == []
    document = Document.objects.filter(company=company).first()
    services.change_document_exclusion(
        actor,
        str(document.id),
        {"base_version": document.version, "reason": "Synthetic cleanup", "idempotency_key": "exclude"},
        excluded=True,
    )
    job = jobs.enqueue_job(actor, company.id, "package", "fresh", {"periods": ["2026-10"]})
    result = jobs.run_job(job["id"])
    assert result["status"] == "done", result
    fresh = result["result"]
    assert fresh["version"] > package["version"] and fresh["id"] != package["id"]
    assert len(fresh["items"]) == 7
    assert str(document.id) not in {item["document_id"] for item in fresh["snapshot"]["payments"]}
    assert (
        jobs.enqueue_job(actor, company.id, "package", "fresh", {"periods": ["2026-10"]})["id"] == job["id"]
    )
    assert not old.dispatches.exists()


def test_rights_versions_payload_and_replay(user, actor, companies):
    company, package = make_package(user, actor, companies)
    with pytest.raises(DomainError):
        removal.preview(actor, companies[1].id, package["id"])
    with pytest.raises(DomainError):
        remove(actor, company, package, version=99)
    token = issue_token(actor, "read-only", [company.id], ["read"])
    from accounting.auth import token_actor

    with pytest.raises(DomainError):
        remove(token_actor(token["token"]), company, package)
    foreign = issue_token(actor, "other-company", [companies[1].id], ["read", "process"])
    with pytest.raises(DomainError):
        removal.preview(token_actor(foreign["token"]), company.id, package["id"])
    with pytest.raises(DomainError):
        remove(token_actor(foreign["token"]), company, package)
    remove(actor, company, package)
    with pytest.raises(DomainError, match="anderen Löschauftrag"):
        remove(actor, company, package, reason="Different request")
    Membership.objects.filter(user=user, company=company).update(can_process=False)
    with pytest.raises(DomainError):
        remove(Actor(user.id), company, package)
    assert PackageRemoval.objects.count() == 1


@pytest.mark.parametrize("status", ["queued", "sending", "accepted", "unknown", "partial", "failed"])
def test_every_smtp_order_is_protected(user, actor, companies, status):
    company, package = make_package(user, actor, companies)
    configured_mailbox(company)
    dispatch = mail.queue_dispatch(actor, package["id"], "send")
    from accounting.models import Dispatch

    Dispatch.objects.filter(id=dispatch["id"]).update(status=status)
    assert removal.preview(actor, company.id, package["id"])["dispatches"][0]["status"] == status
    with pytest.raises(DomainError):
        remove(actor, company, package)
    assert PackageRemoval.objects.count() == 0


@pytest.mark.parametrize("status", ["queued", "running", "failed", "interrupted"])
def test_references_and_resumable_builds_protected(user, actor, companies, status):
    company, package = make_package(user, actor, companies)
    Job.objects.create(
        company=company,
        actor=user,
        kind="package",
        status=status,
        idempotency_key="supplement",
        payload={"parent_id": package["id"]},
    )
    with pytest.raises(DomainError):
        remove(actor, company, package)


def test_parent_reference_never_cascades(user, actor, companies):
    company, package = make_package(user, actor, companies)
    child = packages.create_package(actor, company.id, ["2026-10"], "child", package["id"])
    with pytest.raises(DomainError):
        remove(actor, company, package)
    remove(actor, company, child)
    # Even a removed child retains its immutable parent reference/audit.
    with pytest.raises(DomainError):
        remove(actor, company, package)
    assert Package.objects.count() == 2


def test_fresh_snapshot_uses_changed_payment_state(actor, companies):
    from test_reconciliation import assign, invoice, normalize, statement

    company = companies[0]
    inv = invoice(actor, company)
    normalize(actor, statement(actor, company), auto=False)
    tx = BankTransaction.objects.get(company=company)
    assign(actor, tx, inv, amount="40.00", key="partial")
    package = packages.create_package(actor, company.id, ["2026-10"], "old-payment")
    assert Decimal(package["snapshot"]["payments"][0]["paid"]) == Decimal("40.00")
    before = source_state()
    remove(actor, company, package)
    assert source_state() == before
    assign(actor, tx, inv, amount="80.00", key="remainder")
    fresh = packages.create_package(actor, company.id, ["2026-10"], "new-payment")
    assert Decimal(fresh["snapshot"]["payments"][0]["paid"]) == Decimal("120.00")
    assert fresh["snapshot"]["payments"][0]["status"] == "paid"
    assert Decimal(Package.objects.get(id=package["id"]).snapshot["payments"][0]["paid"]) == Decimal("40.00")


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize(
    "state", ["completed", "pending", "pending_missing", "active_missing", "pending_corrupt"]
)
def test_integrity_supports_removed_archives(user, actor, companies, state, repair):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    company, package = make_package(user, actor, companies)
    archive = storage.path(Package.objects.get(id=package["id"]).path)
    if state == "completed":
        remove(actor, company, package)
    elif state.startswith("pending"):
        with patch.object(Path, "unlink", side_effect=PermissionError("synthetic")):
            assert remove(actor, company, package)["status"] == "cleanup_pending"
        if state == "pending_missing":
            archive.unlink()
        elif state == "pending_corrupt":
            archive.write_bytes(b"corrupt")
    else:
        archive.unlink()
    if state in {"active_missing", "pending_corrupt"}:
        with pytest.raises(CommandError):
            call_command("verify_integrity", repair=repair)
    else:
        call_command("verify_integrity", repair=repair)


def test_cleanup_failure_is_pending_and_retryable(user, actor, companies):
    company, package = make_package(user, actor, companies)
    with patch.object(Path, "unlink", side_effect=PermissionError("synthetic")):
        result = remove(actor, company, package)
    assert result["status"] == "cleanup_pending" and result["cleanup_error"]
    old = Package.objects.get(id=package["id"])
    assert storage.path(old.path).exists()
    with pytest.raises(DomainError):
        packages.package_bytes(old)
    jobs.maintenance()
    assert remove(actor, company, package)["status"] == "completed"
    assert not storage.path(old.path).exists()
