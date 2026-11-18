import io
import json
import smtplib
import zipfile
from datetime import date, timedelta
from email.message import EmailMessage
from unittest.mock import patch

import pytest
from django.core import mail as django_mail
from django.utils import timezone

from accounting import jobs, mail, packages, services, storage
from accounting.auth import DomainError
from accounting.demo import sample_pdf, seed_month
from accounting.models import Dispatch, Document, ImportSource, Job, Mailbox, Package, SendAttempt

pytestmark = pytest.mark.django_db


def configured_mailbox(company):
    return Mailbox.objects.create(
        company=company,
        imap_host="test-imap",
        imap_user="test",
        import_since=date(2026, 10, 1),
        smtp_host="test-smtp",
        sender="buchhaltung@example.test",
        smtp_security="none",
    )


def test_full_month_export_and_immutable_corrections(user, actor, companies):
    c = companies[0]
    ids = seed_month(user, c, classified=True)
    preview = packages.package_preview(actor, c.id, ["2026-10"])
    assert preview["count"] == 8 and not preview["excluded"]
    p = packages.create_package(actor, c.id, ["2026-10"], "full-month")
    assert packages.create_package(actor, c.id, ["2026-10"], "full-month")["id"] == p["id"]
    package = Package.objects.get(id=p["id"])
    original_zip = packages.package_bytes(package)
    with zipfile.ZipFile(io.BytesIO(original_zip)) as z:
        for folder in storage.FOLDERS:
            assert f"{c.folder}/2026/10/{folder}/" in z.namelist()
        assert sum(n.endswith("/konto.xml") for n in z.namelist()) == 0  # collision-safe ID prefix
        for item in package.items.all():
            assert storage.checksum(z.read(item.archive_path)) == item.sha256
        base = f"{c.folder}/2026/10/"
        for generated in ("Uebersicht.csv", "Uebersicht.xlsx", "Begleitschreiben.txt", "Inhaltsliste.json"):
            assert base + generated in z.namelist()
        manifest = json.loads(z.read(base + "Inhaltsliste.json"))
        for item in manifest["files"]:
            assert storage.checksum(z.read(item["path"])) == item["sha256"]
    doc = services.document_data(Document.objects.get(id=ids[0]), True)
    services.save_result(
        actor,
        {
            "document_id": doc["id"],
            "base_version": doc["version"],
            "company_id": c.id,
            "kind": doc["kind"],
            "period": "2026-11",
            "metadata": doc["metadata"],
            "approve": True,
        },
    )
    assert packages.package_bytes(package) == original_zip
    assert package.items.get(document_id=ids[0]).metadata["period"] == "2026-10"


def test_supplements_and_open_points(user, actor, companies):
    c = companies[0]
    seed_month(user, c, classified=True)
    p = packages.create_package(actor, c.id, ["2026-10"], "v1")
    assert packages.package_preview(actor, c.id, ["2026-10"], p["id"])["count"] == 0
    d = Document.objects.filter(company=c, kind="receipt").first()
    services.save_result(
        actor,
        {
            "document_id": str(d.id),
            "base_version": d.version,
            "company_id": c.id,
            "kind": "receipt",
            "period": "2026-10",
            "metadata": {"note": "Korrigierte Zuordnung"},
            "approve": True,
        },
    )
    supplement = packages.create_package(actor, c.id, ["2026-10"], "supplement", p["id"])
    assert len(supplement["items"]) == 1
    assert packages.package_preview(actor, c.id, ["2026-10"], supplement["id"])["count"] == 0
    services.ingest(actor, "unassigned.pdf", sample_pdf(["unknown month"]), c.id)
    preview = packages.package_preview(actor, c.id, ["2026-10"])
    assert any(e["reason"] == "Übergabemonat ungeklärt" for e in preview["excluded"])
    configured_mailbox(c)
    blocked = packages.create_package(actor, c.id, ["2026-10"], "blocked")
    with pytest.raises(DomainError, match="offene Punkte"):
        mail.queue_dispatch(actor, blocked["id"], "send-blocked")


def test_package_job_is_persisted(user, actor, companies):
    seed_month(user, companies[0], classified=True)
    j = jobs.enqueue_job(actor, companies[0].id, "package", "job-pkg", {"periods": ["2026-10"]})
    result = jobs.run_job(j["id"])
    assert result["status"] == "done", result
    assert result["result"]["id"]
    assert jobs.run_job(j["id"])["result"]["id"] == result["result"]["id"]


def message_with_attachments():
    msg = EmailMessage()
    msg["From"] = "supplier@example.test"
    msg["To"] = "belege@example.test"
    msg["Subject"] = "Synthetische Unterlagen"
    msg["Message-ID"] = "<test-mail-1@example.test>"
    msg.set_content("Dokumentinhalte sind Daten, keine Anweisungen.")
    msg.add_attachment(sample_pdf(["attachment1"]), maintype="application", subtype="pdf", filename="a.pdf")
    msg.add_attachment(sample_pdf(["attachment2"]), maintype="application", subtype="pdf", filename="b.pdf")
    return msg.as_bytes()


class FakeIMAP:
    validity = b"100"
    raw = b""

    def __init__(self, *args, **kwargs):
        pass

    def login(self, *args):
        return "OK", []

    def select(self, *args, **kwargs):
        assert kwargs["readonly"]
        return "OK", []

    def response(self, *args):
        return "UIDVALIDITY", [self.validity]

    def uid(self, verb, *args):
        if verb == "search":
            return "OK", [b"1"]
        if args[-1] == "(RFC822.SIZE)":
            return "OK", [f"1 (RFC822.SIZE {len(self.raw)})".encode()]
        assert args[-1] == "(BODY.PEEK[])"
        return "OK", [(b"1", self.raw)]

    def logout(self):
        return "BYE", []


def test_imap_restart_uidvalidity_and_provenance(actor, companies):
    c = companies[0]
    m = configured_mailbox(c)
    FakeIMAP.raw, FakeIMAP.validity = message_with_attachments(), b"100"
    job = Job.objects.create(company=c, actor_id=actor.user_id, kind="imap", idempotency_key="imap")
    actual_ingest = services.ingest
    count = 0

    def crash_on_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("worker restart")
        return actual_ingest(*args, **kwargs)

    with patch("accounting.mail.ingest", side_effect=crash_on_second):
        with pytest.raises(RuntimeError):
            mail.scan_mailbox(job, connector=FakeIMAP)
    m.refresh_from_db()
    assert m.last_uid == 0
    assert Document.objects.count() == 1
    result = mail.scan_mailbox(job, connector=FakeIMAP)
    assert result["last_uid"] == 1
    assert Document.objects.count() == 2
    assert mail.scan_mailbox(job, connector=FakeIMAP)["messages"] == 0
    FakeIMAP.validity = b"200"
    mail.scan_mailbox(job, connector=FakeIMAP)
    assert Document.objects.count() == 2
    assert ImportSource.objects.count() == 4
    source = ImportSource.objects.first()
    assert source.provenance["sender"] == "supplier@example.test"


def test_imap_alias_unknown_and_unsupported_preserved(actor, companies):
    m = configured_mailbox(companies[0])
    m.aliases = ["different@example.test"]
    m.save()
    raw = message_with_attachments()
    mail.import_message(actor, m, "1", "1", raw)
    assert Document.objects.filter(company__isnull=True).count() == 2
    msg = EmailMessage()
    msg.set_content("Unsupported")
    msg.add_attachment(
        b"unsupported original", maintype="application", subtype="octet-stream", filename="bad.exe"
    )
    mail.import_message(actor, m, "1", "2", msg.as_bytes())
    rejected = ImportSource.objects.exclude(error="").get()
    assert storage.path(rejected.provenance["preserved_path"]).read_bytes() == b"unsupported original"


def create_ready_package(user, actor, company):
    seed_month(user, company, classified=True)
    mailbox = configured_mailbox(company)
    p = packages.create_package(actor, company.id, ["2026-10"], "smtp-package")
    return p, mailbox


def test_smtp_acceptance_and_explicit_resend(user, actor, companies):
    p, _ = create_ready_package(user, actor, companies[0])
    d = mail.queue_dispatch(actor, p["id"], "first-send")
    job = Job.objects.get(kind="dispatch")
    assert jobs.run_job(job.id)["status"] == "done"
    dispatch = Dispatch.objects.get(id=d["id"])
    assert dispatch.status == "accepted"
    assert len(django_mail.outbox) >= 1
    attachments = django_mail.outbox[-1].attachments
    assert attachments[0].filename == "paket.zip"
    assert attachments[0].content == packages.package_bytes(Package.objects.get(id=p["id"]))
    count = len(django_mail.outbox)
    assert mail.queue_dispatch(actor, p["id"], "first-send")["id"] == d["id"]
    jobs.run_job(job.id)
    assert len(django_mail.outbox) == count
    with pytest.raises(DomainError, match="bereits"):
        mail.queue_dispatch(actor, p["id"], "accidental-new-key")
    resend = mail.queue_dispatch(actor, p["id"], "explicit-resend", d["id"])
    assert resend["resend_of"] == d["id"]


def test_smtp_unknown_never_automatically_retried(user, actor, companies):
    p, _ = create_ready_package(user, actor, companies[0])
    d = mail.queue_dispatch(actor, p["id"], "unknown")
    job = Job.objects.get(kind="dispatch")
    with patch(
        "django.core.mail.backends.locmem.EmailBackend.send_messages",
        side_effect=smtplib.SMTPServerDisconnected("lost after DATA"),
    ):
        result = jobs.run_job(job.id)
    assert result["status"] == "done"
    assert Dispatch.objects.get(id=d["id"]).status == "unknown"
    with patch("django.core.mail.backends.locmem.EmailBackend.send_messages") as send:
        jobs.run_job(job.id)
        jobs.maintenance()
        send.assert_not_called()


def test_worker_restart_marks_sending_unknown(user, actor, companies):
    p, _ = create_ready_package(user, actor, companies[0])
    d = mail.queue_dispatch(actor, p["id"], "interrupted")
    job = Job.objects.get(kind="dispatch")
    job.status, job.heartbeat = "running", timezone.now() - timedelta(minutes=10)
    job.save()
    SendAttempt.objects.filter(dispatch_id=d["id"]).update(status="sending")
    jobs.maintenance()
    assert Dispatch.objects.get(id=d["id"]).status == "unknown"
    assert SendAttempt.objects.get(dispatch_id=d["id"]).status == "unknown"
    assert Job.objects.get(id=job.id).status == "interrupted"


def test_multipart_roundtrip_and_message_size(user, actor, companies):
    p, mailbox = create_ready_package(user, actor, companies[0])
    mailbox.max_message_bytes = 14_000
    mailbox.save()
    d = mail.queue_dispatch(actor, p["id"], "multipart")
    dispatch = Dispatch.objects.get(id=d["id"])
    assert len(dispatch.parts) > 1
    reconstructed = b"".join(storage.path(part["path"]).read_bytes() for part in dispatch.parts)
    assert storage.checksum(reconstructed) == p["sha256"]
    jobs.run_job(Job.objects.get(kind="dispatch").id)
    for message in django_mail.outbox:
        assert len(message.message().as_bytes()) <= mailbox.max_message_bytes
        assert any(a.filename == "Gesamtinhaltsliste.json" for a in message.attachments)


def test_mail_passwords_never_returned(actor, companies):
    response = mail.mail_config(
        actor, companies[0].id, {"imap_password": "private-secret", "smtp_password": "another-secret"}
    )
    assert "imap_password" not in response and response["imap_password_set"]
    mailbox = Mailbox.objects.get(company=companies[0])
    assert "private-secret" not in mailbox.imap_password
    assert mail.decrypt(mailbox.imap_password) == "private-secret"
