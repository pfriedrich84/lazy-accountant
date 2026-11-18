import csv
import io
import threading
import zipfile
from email.message import EmailMessage
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from iso4217 import Currency
from openpyxl import load_workbook
from pydantic import ValidationError

from accounting import jobs, mail, packages, services, storage
from accounting.auth import DomainError
from accounting.camt import SUPPORTED_NAMESPACES, parse_camt
from accounting.demo import sample_camt, sample_pdf, seed_month
from accounting.models import Account, Dispatch, Document, FileOperation, Job, Mailbox
from accounting.schemas import Metadata, validation_issues

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("namespace", sorted(SUPPORTED_NAMESPACES))
def test_declared_camt_namespaces(namespace):
    data = sample_camt().replace(b"urn:iso:std:iso:20022:tech:xsd:camt.053.001.08", namespace.encode())
    if ".052." in namespace:
        data = (
            data.replace(b"BkToCstmrStmt", b"BkToCstmrAcctRpt")
            .replace(b"<Stmt>", b"<Rpt>")
            .replace(b"</Stmt>", b"</Rpt>")
        )
    if ".054." in namespace:
        data = (
            data.replace(b"BkToCstmrStmt", b"BkToCstmrDbtCdtNtfctn")
            .replace(b"<Stmt>", b"<Ntfctn>")
            .replace(b"</Stmt>", b"</Ntfctn>")
        )
    parsed = parse_camt(data)
    assert parsed["namespace"] == namespace
    assert parsed["statements"][0]["entries"][0]["amount"] == "120.00"


def test_currency_scale_and_decimal_rounding():
    with pytest.raises(ValidationError):
        Metadata(currency="ZZZ")
    for currency in ["EUR", "JPY", "KWD", "CLF"]:
        assert Currency(currency).exponent is not None
    issues = validation_issues(
        "receipt",
        1,
        "2026-10",
        None,
        {
            "currency": "EUR",
            "net": "0.025",
            "tax": "0.005",
            "gross": "0.03",
            "taxes": [{"rate": "20", "net": "0.025", "tax": "0.005"}],
        },
    )
    assert not issues
    issues = validation_issues(
        "receipt", 1, "2026-10", None, {"currency": "JPY", "net": "100", "tax": "10", "gross": "111"}
    )
    assert any("Brutto" in issue for issue in issues)
    assert validation_issues(
        "receipt", 1, "2026-10", None, {"currency": "XAU", "net": "1", "tax": "0", "gross": "1"}
    )


def test_account_category_period_and_missing_fields(actor, companies):
    d = services.ingest(actor, "bank.pdf", sample_pdf(["bank"]), companies[0].id)["document"]
    base = {
        "document_id": d["id"],
        "base_version": 1,
        "company_id": companies[0].id,
        "kind": "bank_pdf",
        "period": "2026-10",
        "metadata": {},
    }
    for period in ["2026-00", "2026-13", "../../etc", "2026-1", "0000-01"]:
        with pytest.raises(DomainError):
            services.save_result(actor, {**base, "period": period})
    with pytest.raises(DomainError, match="gehört nicht"):
        services.save_result(
            actor, {**base, "account_id": Account.objects.filter(company=companies[1], kind="bank").get().id}
        )
    with pytest.raises(DomainError, match="passt nicht"):
        services.save_result(
            actor, {**base, "account_id": Account.objects.filter(company=companies[0], kind="depot").get().id}
        )
    saved = services.save_result(actor, base)
    assert "Konto/Depot ungeklärt" in saved["issues"]
    assert "Auszugszeitraum unvollständig" in saved["issues"]


def test_bootstrap_two_complete_isolated_months(user, actor, companies, tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", user.username)
    call_command("bootstrap", sample_month="2026-10", classified=True, output=str(tmp_path))
    assert Document.objects.count() == 16
    for company in companies:
        assert Document.objects.filter(company=company, status="ready").count() == 8
        package = packages.create_package(actor, company.id, ["2026-10"], f"complete:{company.id}")
        snapshot = package["snapshot"]
        bank = Account.objects.get(company=company, kind="bank")
        assert {
            d["account_identifier"] for d in snapshot["documents"] if d["kind"] in {"bank_pdf", "bank_camt"}
        } == {bank.identifier}
        with zipfile.ZipFile(storage.path("_packages/" + package["id"] + ".zip")) as archive:
            assert all(name.startswith(company.folder + "/") for name in archive.namelist())
            assert all(
                f"{company.folder}/2026/10/{folder}/" in archive.namelist() for folder in storage.FOLDERS
            )
            assert len([name for name in archive.namelist() if name.endswith("konto.xml")]) == 1
    call_command("bootstrap", sample_month="2026-10", classified=True, output=str(tmp_path))
    assert Document.objects.count() == 16
    assert (tmp_path / "eingang.pdf").exists()
    assert (tmp_path / companies[1].folder / "eingang.pdf").exists()


def test_csv_xlsx_formula_safety_and_original_negative_amounts(actor, companies):
    c = companies[0]
    d = services.ingest(actor, "x.pdf", sample_pdf(["negative credit"]), c.id)["document"]
    services.save_result(
        actor,
        {
            "document_id": d["id"],
            "base_version": 1,
            "company_id": c.id,
            "kind": "incoming_credit",
            "period": "2026-10",
            "metadata": {
                "issuer": '=WEBSERVICE("https://untrusted.invalid")',
                "recipient": c.name,
                "number": "credit",
                "date": "2026-10-15",
                "net": "-100.00",
                "tax": "-20.00",
                "gross": "-120.00",
                "currency": "EUR",
            },
            "approve": True,
        },
    )
    p = packages.create_package(actor, c.id, ["2026-10"], "csv-safety")
    with zipfile.ZipFile(storage.path("_packages/" + p["id"] + ".zip")) as archive:
        csv_name = next(n for n in archive.namelist() if n.endswith("Uebersicht.csv"))
        rows = list(csv.DictReader(io.StringIO(archive.read(csv_name).decode("utf-8-sig")), delimiter=";"))
        assert rows[0]["issuer"].startswith("'=WEBSERVICE")
        assert rows[0]["gross"] == "-120.00"
        xlsx_name = next(n for n in archive.namelist() if n.endswith("Uebersicht.xlsx"))
        workbook = load_workbook(io.BytesIO(archive.read(xlsx_name)))
        assert not any(cell.data_type == "f" for row in workbook.active for cell in row)


def test_pending_filing_visible_and_integrity_repair(actor, companies):
    d = services.ingest(actor, "x.pdf", sample_pdf(["recover"]), companies[0].id)["document"]
    with patch("accounting.storage.atomic_write", side_effect=OSError("full disk")):
        saved = services.save_result(
            actor,
            {
                "document_id": d["id"],
                "base_version": 1,
                "company_id": companies[0].id,
                "kind": "receipt",
                "period": "2026-10",
                "metadata": {},
                "approve": True,
            },
        )
    assert saved["filing_status"] == "pending" and saved["filing_error"]
    preview = packages.package_preview(actor, companies[0].id, ["2026-10"])
    assert preview["count"] == 0
    assert "Dateiablage" in preview["excluded"][0]["reason"]
    call_command("verify_integrity", repair=True)
    assert not FileOperation.objects.filter(status="pending").exists()
    doc = Document.objects.get(id=d["id"])
    storage.path(doc.filed_path).write_bytes(b"tampered")
    with pytest.raises(CommandError, match="Integritätsprüfung"):
        call_command("verify_integrity")


def test_smtp_partial_recipient_rejection_is_visible(user, actor, companies, settings):
    c = companies[0]
    c.recipients = ["first@example.test", "second@example.test"]
    c.save()
    seed_month(user, c, classified=True)
    Mailbox.objects.create(company=c, smtp_host="test", sender="sender@example.test", smtp_security="none")
    p = packages.create_package(actor, c.id, ["2026-10"], "partial")
    d = mail.queue_dispatch(actor, p["id"], "send-partial")
    settings.MAILERS = {"default": {"BACKEND": "accounting.smtp.EmailBackend", "OPTIONS": {"host": "test"}}}
    from accounting.smtp import EmailBackend

    connection_mock = MagicMock()
    connection_mock.sendmail.return_value = {"second@example.test": (550, b"no mailbox")}

    def open_connection(self):
        self.connection = connection_mock
        return False

    job = Job.objects.get(kind="dispatch")
    with patch.object(EmailBackend, "open", open_connection):
        jobs.run_job(job.id)
        assert Dispatch.objects.get(id=d["id"]).status == "partial"
        assert connection_mock.sendmail.call_count == 1
        mail.send_dispatch(job)
        assert connection_mock.sendmail.call_count == 1


def test_tampered_mail_part_never_sent(user, actor, companies):
    c = companies[0]
    seed_month(user, c, classified=True)
    Mailbox.objects.create(company=c, smtp_host="test", sender="sender@example.test")
    p = packages.create_package(actor, c.id, ["2026-10"], "tampered")
    d = mail.queue_dispatch(actor, p["id"], "send-tampered")
    dispatch = Dispatch.objects.get(id=d["id"])
    storage.path(dispatch.parts[0]["path"]).write_bytes(b"tampered")
    with patch("django.core.mail.backends.locmem.EmailBackend.send_messages") as send:
        jobs.run_job(Job.objects.get(kind="dispatch").id)
        send.assert_not_called()
    assert Dispatch.objects.get(id=d["id"]).status == "failed"


def test_shared_mailbox_requires_distinct_aliases_and_ambiguous_mail_stays_unassigned(actor, companies):
    config = {"imap_host": "test", "imap_user": "shared", "imap_folder": "INBOX"}
    mail.mail_config(actor, companies[0].id, {**config, "aliases": ["a@example.test"]})
    with pytest.raises(DomainError, match="Aliasregeln"):
        mail.mail_config(actor, companies[1].id, {**config, "aliases": []})
    with pytest.raises(DomainError, match="Aliasregeln"):
        mail.mail_config(actor, companies[1].id, {**config, "aliases": ["a@example.test"]})
    mail.mail_config(actor, companies[1].id, {**config, "aliases": ["b@example.test"]})
    message = EmailMessage()
    message["From"] = "supplier@example.test"
    message["To"] = "a@example.test, b@example.test"
    message.set_content("ambiguous assignment")
    message.add_attachment(sample_pdf(["ambiguous"]), maintype="application", subtype="pdf", filename="x.pdf")
    m = Mailbox.objects.get(company=companies[0])
    assert mail.import_message(actor, m, "100", 1, message.as_bytes()) == 1
    assert Document.objects.get().company_id is None


def test_packet_size_limit_keeps_originals(user, actor, companies, settings):
    seed_month(user, companies[0], classified=True)
    settings.MAX_PACKAGE_BYTES = 1
    with pytest.raises(DomainError, match="größenlimit"):
        packages.create_package(actor, companies[0].id, ["2026-10"], "too-big")
    assert Document.objects.count() == 8


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_metadata_writers_have_one_winner(actor, companies):
    if connection.vendor != "postgresql":
        pytest.skip("Echte Zeilensperren werden in der PostgreSQL-Suite geprüft.")
    d = services.ingest(actor, "race.pdf", sample_pdf(["concurrency"]), companies[0].id)["document"]
    barrier = threading.Barrier(2)

    def writer(label):
        try:
            barrier.wait(timeout=10)
            services.save_result(
                actor,
                {
                    "document_id": d["id"],
                    "base_version": 1,
                    "company_id": companies[0].id,
                    "kind": "receipt",
                    "period": "2026-10",
                    "metadata": {"note": label},
                },
            )
            return "saved"
        except DomainError as e:
            assert e.status == 409
            return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, ["manual", "agent"]))
    assert sorted(results) == ["conflict", "saved"]
    doc = Document.objects.get(id=d["id"])
    assert doc.version == 2
    assert doc.revisions.count() == 2
    assert storage.path(doc.filed_path).exists()
