"""Real row-lock tests; run with POSTGRES_HOST configured, never emulate on SQLite."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection

from accounting import mail, package_removal, packages, storage
from accounting.auth import DomainError
from accounting.demo import seed_month
from accounting.models import Package
from test_packages_mail import configured_mailbox

pytestmark = pytest.mark.django_db(transaction=True)


def in_connection(function):
    close_old_connections()
    try:
        return function()
    finally:
        close_old_connections()


def backend_pid():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


def wait_for_lock(pid):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid])
            row = cursor.fetchone()
        if row and row[0] == "Lock":
            return
        sleep(0.02)
    raise AssertionError("Worker never reached a PostgreSQL lock wait")


@pytest.mark.parametrize("operation", ["download", "dispatch", "supplement"])
def test_removal_serializes_with_package_users(user, actor, companies, operation):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    company = companies[0]
    seed_month(user, company, classified=True)
    configured_mailbox(company)
    data = packages.create_package(actor, company.id, ["2026-10"], "original")
    package = Package.objects.get(pk=data["id"])
    entered, release = Event(), Event()
    removal_pid = Queue()

    if operation == "download":
        original = storage.path
        target = "accounting.packages.storage.path"

        def hold(*args, **kwargs):
            if args[0] == package.path:
                entered.set()
                assert release.wait(10)
            return original(*args, **kwargs)

        def action():
            return packages.package_bytes(package)
    elif operation == "dispatch":
        original = mail.prepare_dispatch
        target = "accounting.mail.prepare_dispatch"

        def hold(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return original(*args, **kwargs)

        def action():
            return mail.queue_dispatch(actor, package.id, "send")
    else:
        original = packages.build_archive
        target = "accounting.packages.build_archive"

        def hold(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return original(*args, **kwargs)

        def action():
            return packages.create_package(actor, company.id, ["2026-10"], "child", package.id)

    def remove():
        removal_pid.put(backend_pid())
        try:
            return package_removal.remove(
                actor, company.id, package.id, package.version, "Explicit request", "remove"
            )
        except DomainError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool, patch(target, side_effect=hold):
        active = pool.submit(in_connection, action)
        try:
            assert entered.wait(10)
            deletion = pool.submit(in_connection, remove)
            wait_for_lock(removal_pid.get(timeout=10))
            assert not deletion.done()
        finally:
            release.set()
        assert active.result(timeout=15)
        result = deletion.result(timeout=15)
    if operation == "download":
        assert result["status"] == "completed"
        with pytest.raises(DomainError) as exc:
            packages.package_bytes(package)
        assert exc.value.status == 410
    else:
        assert isinstance(result, DomainError) and result.status == 409
        assert not package_removal.PackageRemoval.objects.exists()


@pytest.mark.parametrize("historical_source", [False, True])
def test_parent_download_and_supplement_build_do_not_deadlock(user, actor, companies, historical_source):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    company = companies[0]
    if historical_source:
        from accounting.models import BankTransaction, Document
        from test_reconciliation import assign, invoice, normalize, statement

        source = statement(actor, company)
        normalize(actor, source, auto=False)
        Document.objects.filter(id=source["id"]).update(period="2026-09")
        current_invoice = invoice(actor, company)
        assign(actor, BankTransaction.objects.get(), current_invoice)
    else:
        seed_month(user, company, classified=True)
    data = packages.create_package(actor, company.id, ["2026-10"], "parent")
    package = Package.objects.get(pk=data["id"])
    entered, release = Event(), Event()
    download_pid = Queue()
    original = packages.build_archive

    def hold(*args, **kwargs):
        # package_preview has already locked the company's documents.
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    def build():
        return packages.create_package(actor, company.id, ["2026-10"], "supplement", package.id)

    def download():
        download_pid.put(backend_pid())
        return packages.package_bytes(package)

    with (
        ThreadPoolExecutor(max_workers=2) as pool,
        patch("accounting.packages.build_archive", side_effect=hold),
    ):
        builder = pool.submit(in_connection, build)
        try:
            assert entered.wait(10)
            downloading = pool.submit(in_connection, download)
            # A download must wait without inverting the builder's source locks,
            # including historical sources created before the current invoice.
            wait_for_lock(download_pid.get(timeout=10))
        finally:
            release.set()
        # The parent FK's KEY SHARE must not conflict with the download lock.
        assert builder.result(timeout=15)["parent_id"] == str(package.id)
        assert storage.checksum(downloading.result(timeout=15)) == package.sha256
