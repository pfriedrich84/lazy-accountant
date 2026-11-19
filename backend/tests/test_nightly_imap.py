from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from accounting import jobs, mail
from accounting.auth import DomainError
from accounting.models import Job, Mailbox, Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def enabled_mailbox(companies):
    return Mailbox.objects.create(company=companies[0], enabled=True)


@pytest.mark.parametrize(
    "instant,scheduled",
    [
        ("2026-07-01T00:59:00+00:00", False),  # 02:59 Vienna
        ("2026-07-01T01:00:00+00:00", True),
        ("2026-07-01T01:59:00+00:00", True),
        ("2026-07-01T02:00:00+00:00", False),  # no daytime catch-up
        ("2026-07-01T12:00:00+00:00", False),
        ("2026-01-15T02:00:00+00:00", True),  # winter time
        ("2026-03-29T01:00:00+00:00", True),  # spring DST transition
        ("2026-10-25T01:00:00+00:00", False),  # repeated 02:00 is not 03:00
        ("2026-10-25T02:00:00+00:00", True),
    ],
)
@override_settings(TIME_ZONE="Europe/Vienna")
def test_nightly_start_window_uses_vienna_not_active_timezone(enabled_mailbox, instant, scheduled):
    with (
        timezone.override("UTC"),
        patch("accounting.jobs.timezone.now", return_value=datetime.fromisoformat(instant)),
        patch("accounting.jobs._publish"),
        patch("accounting.mail.scan_mailbox") as scan,
    ):
        jobs.maintenance()
        scan.assert_not_called()  # maintenance only queues; no network access itself
    assert Job.objects.filter(kind="imap").count() == int(scheduled)
    if scheduled:
        job = Job.objects.get(kind="imap")
        local_date = instant[:10]
        assert job.idempotency_key == "nightly:" + local_date
        assert job.payload == {"nightly_date": local_date}


def test_one_start_per_night_even_after_failure_and_restart(enabled_mailbox):
    with (
        patch(
            "accounting.jobs.timezone.now", return_value=datetime.fromisoformat("2026-07-01T01:00:00+00:00")
        ),
        patch("accounting.jobs._publish"),
    ):
        jobs.maintenance()
        Job.objects.update(status="failed")
        jobs.maintenance()
        jobs.install_schedule()  # worker/bootstrap restart must not reset the daily guard
        jobs.maintenance()
        assert Job.objects.filter(kind="imap").count() == 1
    with (
        patch(
            "accounting.jobs.timezone.now", return_value=datetime.fromisoformat("2026-07-02T01:00:00+00:00")
        ),
        patch("accounting.jobs._publish"),
    ):
        jobs.maintenance()
    assert Job.objects.filter(kind="imap").count() == 2


@pytest.mark.parametrize("disabled,no_permission", [(True, False), (False, True)])
def test_nightly_requires_enabled_mailbox_and_active_processor(enabled_mailbox, disabled, no_permission):
    if disabled:
        enabled_mailbox.enabled = False
        enabled_mailbox.save()
    if no_permission:
        Membership.objects.filter(company=enabled_mailbox.company).update(can_process=False)
    with (
        patch(
            "accounting.jobs.timezone.now", return_value=datetime.fromisoformat("2026-07-01T01:00:00+00:00")
        ),
        patch("accounting.jobs._publish"),
    ):
        jobs.maintenance()
    assert not Job.objects.filter(kind="imap").exists()


def test_nightly_backlog_uses_durable_bounded_batches(actor, enabled_mailbox):
    first = jobs.enqueue_job(
        actor, enabled_mailbox.company_id, "imap", "nightly:2026-07-01", {"nightly_date": "2026-07-01"}
    )
    with patch(
        "accounting.mail.scan_mailbox",
        side_effect=[
            {"messages": 20, "remaining": 5, "last_uid": 20, "uidvalidity": "1", "snapshot_uid": 25},
            {"messages": 5, "remaining": 0, "last_uid": 25, "uidvalidity": "1", "snapshot_uid": 25},
        ],
    ) as scan:
        assert jobs.run_job(first["id"])["status"] == "done"
        second = Job.objects.exclude(id=first["id"]).get()
        assert second.status == "queued" and second.payload == {
            "nightly_date": "2026-07-01",
            "until_uid": 25,
            "snapshot_uidvalidity": "1",
        }
        jobs.run_job(first["id"])  # duplicate queue delivery does not spawn another batch
        assert Job.objects.count() == 2
        assert jobs.run_job(second.id)["status"] == "done"
        assert scan.call_count == 2
    assert Job.objects.count() == 2


@pytest.mark.parametrize("case", ["manual", "disabled", "no_progress", "failed"])
def test_no_automatic_continuation_for_manual_disabled_stuck_or_failed_jobs(actor, enabled_mailbox, case):
    payload = {} if case == "manual" else {"nightly_date": "2026-07-01"}
    first = jobs.enqueue_job(actor, enabled_mailbox.company_id, "imap", "test-" + case, payload)
    if case == "disabled":
        enabled_mailbox.enabled = False
        enabled_mailbox.save()
    result = {
        "messages": 0 if case == "no_progress" else 20,
        "remaining": 5,
        "last_uid": 20,
        "uidvalidity": "1",
    }
    with patch(
        "accounting.mail.scan_mailbox",
        side_effect=OSError("offline") if case == "failed" else None,
        return_value=result,
    ):
        outcome = jobs.run_job(first["id"])
    assert outcome["status"] == ("failed" if case == "failed" else "done")
    assert Job.objects.count() == 1


@pytest.mark.parametrize("nightly", [True, False])
def test_disabling_cancels_queued_automatic_but_not_explicit_manual_import(actor, enabled_mailbox, nightly):
    first = jobs.enqueue_job(
        actor,
        enabled_mailbox.company_id,
        "imap",
        "queued-disable",
        {"nightly_date": "2026-07-01"} if nightly else {},
    )
    enabled_mailbox.enabled = False
    enabled_mailbox.save()
    with patch("accounting.mail.scan_mailbox", return_value={"messages": 0, "remaining": 0}) as scan:
        result = jobs.run_job(first["id"])
    assert result["status"] == "done"
    assert scan.call_count == (0 if nightly else 1)
    assert ("skipped" in result["result"]) == nightly


@pytest.mark.parametrize("validity", ["100", "200"])
def test_nightly_snapshot_excludes_later_mail_and_rejects_uidvalidity_changes(
    actor, enabled_mailbox, validity
):
    mailbox = enabled_mailbox
    mailbox.imap_host, mailbox.imap_user = "test-imap", "test"
    mailbox.import_since = date(2026, 7, 1)
    mailbox.uidvalidity, mailbox.last_uid = "100", 20
    mailbox.save()
    job = Job.objects.create(
        company_id=mailbox.company_id,
        actor_id=actor.user_id,
        kind="imap",
        idempotency_key="snapshot",
        payload={"nightly_date": "2026-07-01", "until_uid": 25, "snapshot_uidvalidity": "100"},
    )
    client = MagicMock()
    client.select.return_value = ("OK", [])
    client.response.return_value = ("UIDVALIDITY", [validity.encode()])
    raw = b"From: supplier@example.test\r\nSubject: synthetic\r\n\r\nNo attachments."

    def uid(command, *args):
        if command == "search":
            return "OK", [b"21 22 23 24 25 26"]  # UID 26 arrived after the first nightly scan
        if args[-1] == "(RFC822.SIZE)":
            return "OK", [f"{args[0]} (RFC822.SIZE {len(raw)})".encode()]
        assert args[-1] == "(BODY.PEEK[])"
        return "OK", [(args[0].encode(), raw)]

    client.uid.side_effect = uid
    if validity == "200":
        with pytest.raises(DomainError, match="UIDVALIDITY"):
            mail.scan_mailbox(job, connector=lambda *a, **kw: client)
        client.uid.assert_not_called()
    else:
        result = mail.scan_mailbox(job, connector=lambda *a, **kw: client)
        assert result["messages"] == 5 and result["remaining"] == 0
        assert result["last_uid"] == result["snapshot_uid"] == 25
        fetched = {c.args[1] for c in client.uid.call_args_list if c.args[0] == "fetch"}
        assert fetched == {"21", "22", "23", "24", "25"}
    mailbox.refresh_from_db()
    assert mailbox.last_uid == (20 if validity == "200" else 25)
    client.logout.assert_called_once()
