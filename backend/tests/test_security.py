import io
import zipfile
from datetime import datetime, timedelta, timezone as dt_timezone
from email.message import EmailMessage
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from pypdf import PdfWriter
from PIL import Image

from accounting import mail, name_changes, packages, scanner, security, services, storage, transfers
from accounting.auth import DomainError
from accounting.demo import sample_camt, sample_image, sample_pdf
from accounting.models import Document, ImportSource, Mailbox, Package, ScanAttempt
from test_documents import result

pytestmark = [pytest.mark.django_db, pytest.mark.security]

# Standard harmless antivirus test string, not malware. Constructed at runtime.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
ENGINE = "ClamAV 1.5.5/12345/" + datetime.now(dt_timezone.utc).strftime("%a %b %d %H:%M:%S %Y")


def sample_jpeg():
    output = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="JPEG")
    return output.getvalue()


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    monkeypatch.setattr(security, "publish", lambda identifier: None)


def ingest(actor, companies, data=None):
    value = services.ingest(actor, "test.pdf", data or sample_pdf(["safe"]), companies[0].id)
    return Document.objects.get(id=value["document"]["id"])


def scan(doc, outcome="clean"):
    with patch.object(
        scanner,
        "scan",
        return_value=scanner.Verdict(
            outcome,
            ENGINE,
            "Eicar-Test-Signature" if outcome == "infected" else "",
            "Test failure" if outcome != "clean" else "",
        ),
    ):
        security.run_scan(doc.id)
    doc.refresh_from_db()
    return doc


def assert_blocked(client, actor, doc):
    for representation in ("original", "page", "text"):
        response = client.get(f"/api/documents/{doc.id}/{representation}/")
        assert response.status_code == 423
    with pytest.raises(DomainError) as exc:
        transfers.claim_document(actor, doc.id, "agent", doc.version)
    assert exc.value.status == 423
    with pytest.raises(DomainError):
        services.save_result(actor, result(services.document_data(doc), doc.company_id, approve=True))
    with pytest.raises(DomainError):
        name_changes.preview(actor, [str(doc.id)])
    with pytest.raises(DomainError):
        name_changes.set_name(actor, str(doc.id), doc.version, "must-stay-blocked.pdf")
    preview = packages.package_preview(actor, doc.company_id, ["2026-10"])
    assert not preview["documents"]
    assert preview["security_blocked"][0]["document"]["id"] == str(doc.id)


def test_pending_and_scanning_never_parse_or_publish(client, actor, companies):
    with patch.object(security, "inspect_bytes", side_effect=AssertionError("parser called")):
        doc = ingest(actor, companies)
        assert doc.security_status == "pending"
        assert storage.path(doc.quarantine_path).is_file()
        assert not doc.filed_path
        assert_blocked(client, actor, doc)
        doc.security_status = "scanning"
        doc.save()
        assert_blocked(client, actor, doc)


@pytest.mark.parametrize(
    "data,name,media",
    [
        (sample_pdf(["safe"]), "safe.pdf", "application/pdf"),
        (sample_image(), "safe.png", "image/png"),
        (sample_jpeg(), "safe.jpg", "image/jpeg"),
        (sample_camt(), "safe.xml", "application/xml"),
    ],
)
def test_clean_release_exact_bytes(actor, companies, data, name, media):
    value = services.ingest(actor, name, data, companies[0].id)
    doc = Document.objects.get(id=value["document"]["id"])
    scan(doc)
    assert doc.security_status == "clean"
    assert doc.media_type == media
    assert doc.handover_name.endswith(name.rsplit(".", 1)[-1])
    assert doc.scanned_sha256 == storage.checksum(data)
    assert storage.read_original(doc) == data
    storage.reconcile(doc.id)
    doc.refresh_from_db()
    assert storage.path(doc.filed_path).read_bytes() == data
    assert doc.scans.get().engine == ENGINE


@pytest.mark.parametrize("channel", ["rest", "mcp", "imap"])
def test_eicar_all_channels_and_identical_reimport(client, actor, companies, channel):
    company = companies[0]
    if channel == "rest":
        response = client.post(
            "/api/documents/",
            {
                "company_id": company.id,
                "file": SimpleUploadedFile("eicar.txt", EICAR),
            },
        )
        assert response.status_code == 201
        doc = Document.objects.get()
    elif channel == "mcp":
        ticket = transfers.prepare_upload(actor, "eicar.txt", len(EICAR), storage.checksum(EICAR), company.id)
        transfers.put_upload(actor, ticket["upload_id"], EICAR)
        value = transfers.complete_upload(actor, ticket["upload_id"])
        doc = Document.objects.get(id=value["id"])
    else:
        mailbox = Mailbox.objects.create(company=company)
        message = EmailMessage()
        message.set_content("harmless antivirus test")
        message.add_attachment(EICAR, maintype="application", subtype="octet-stream", filename="eicar.txt")
        raw = message.as_bytes()
        mail.import_message(actor, mailbox, "1", "1", raw)
        doc = Document.objects.get()
        mail.import_message(actor, mailbox, "1", "1", raw)
        mail.import_message(actor, mailbox, "2", "1", raw)
        assert Document.objects.count() == 1
        assert ImportSource.objects.count() == 2
    scan(doc, "infected")
    assert_blocked(client, actor, doc)
    assert doc.scans.get().signature == "Eicar-Test-Signature"
    again = services.ingest(actor, "again.pdf", EICAR, company.id)
    assert again["duplicate"] and again["document"]["security_status"] == "infected"
    assert Document.objects.count() == 1
    assert storage.path(doc.quarantine_path).read_bytes() == EICAR
    if channel == "imap":
        assert mail.import_errors(actor, company.id)[0]["security_status"] == "infected"


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("stream: OK", "clean"),
        ("stream: Eicar-Test-Signature FOUND", "infected"),
        ("stream: Heuristics.Limits.Exceeded.MaxScanSize FOUND", "error"),
        ("stream: Heuristics.Limits.Exceeded.MaxRecursion FOUND", "error"),
        ("stream: Heuristics.Encrypted.PDF FOUND", "error"),
        ("INSTREAM size limit exceeded. ERROR", "error"),
        ("stream: timeout ERROR", "error"),
        ("stream: OK\nstream: Eicar FOUND", "error"),
        ("OK", "error"),
        ("", "error"),
    ],
)
def test_strict_scanner_responses(answer, expected):
    with patch.object(scanner, "exchange", return_value=(ENGINE, answer, ENGINE)):
        verdict = scanner.scan(EICAR)
    assert verdict.result == expected


@pytest.mark.parametrize(
    "version",
    [
        "ClamAV 1.5.5",
        "ClamAV 1.5.5/0/Fri Nov 20 01:00:00 2026",
        "ClamAV 1.5.5/123/not-a-date",
    ],
)
def test_missing_database_or_malformed_clamd_version_is_blocked(version):
    for before, after in [(version, ENGINE), (ENGINE, version)]:
        with patch.object(scanner, "exchange", return_value=(before, "stream: OK", after)):
            assert scanner.scan(EICAR).result == "error"


@pytest.mark.parametrize("failure", [ConnectionRefusedError(), TimeoutError()])
def test_unavailable_scanner_fails_closed(failure):
    with patch.object(scanner, "exchange", side_effect=failure):
        assert scanner.scan(EICAR).result == "error"


def test_retry_lease_restart_and_explicit_resume(client, actor, companies):
    doc = ingest(actor, companies)
    for number in range(3):
        scan(doc, "error")
        assert_blocked(client, actor, doc)
        assert doc.scan_attempts == number + 1
        if number < 2:
            Document.objects.filter(id=doc.id).update(scan_due_at=timezone.now() - timedelta(seconds=1))
            security.maintenance()
            doc.refresh_from_db()
            assert doc.security_status == "pending"
    assert doc.scan_due_at is None
    security.request_scan(actor, doc.id)
    doc.refresh_from_db()
    doc.security_status, doc.scan_attempts = "scanning", 1
    doc.scan_due_at = timezone.now() - timedelta(seconds=1)
    doc.save()
    interrupted = ScanAttempt.objects.create(document=doc, sha256=doc.sha256)
    security.maintenance()
    interrupted.refresh_from_db()
    assert interrupted.result == "error"
    doc.refresh_from_db()
    scan(doc)
    assert doc.security_status == "clean"


def test_swap_during_and_after_scan(client, actor, companies):
    doc = ingest(actor, companies)

    def swap(data):
        storage.path(doc.quarantine_path).write_bytes(b"different")
        return scanner.Verdict("clean", ENGINE)

    with patch.object(scanner, "scan", side_effect=swap):
        security.run_scan(doc.id)
    doc.refresh_from_db()
    assert doc.security_status == "error"
    assert_blocked(client, actor, doc)
    other = ingest(actor, companies, sample_pdf(["other"]))
    scan(other)
    storage.path(other.original_path).chmod(0o600)
    storage.path(other.original_path).write_bytes(b"changed after scan")
    with pytest.raises(DomainError):
        storage.read_original(other)
    other.refresh_from_db()
    assert other.security_status == "error"


def test_encrypted_pdf_and_invalid_format_remain_quarantined(actor, companies):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("password")
    output = io.BytesIO()
    writer.write(output)
    for data in (output.getvalue(), b"PK\x03\x04not an allowed archive", b"<Document><broken>"):
        doc = ingest(actor, companies, data)
        scan(doc)
        assert doc.security_status == "error"
        assert not doc.filed_path
        assert storage.path(doc.quarantine_path).read_bytes() == data


def test_later_finding_blocks_snapshot_without_rewriting(client, actor, companies):
    doc = ingest(actor, companies)
    scan(doc)
    services.save_result(actor, result(services.document_data(doc), companies[0].id, approve=True))
    value = packages.create_package(actor, companies[0].id, ["2026-10"], "before-rescan")
    package = Package.objects.get(id=value["id"])
    original = storage.path(package.path).read_bytes()
    security.request_scan(actor, doc.id)
    doc.refresh_from_db()
    scan(doc, "infected")
    assert packages.package_data(package)["security_blocked"]
    assert not packages.package_data(package, True)["snapshot"]["documents"][0]["metadata"]
    package.refresh_from_db()
    assert package.snapshot["documents"][0]["metadata"]["issuer"] == "Lieferant"
    assert services.document_data(doc, True)["security_impact"]["package_ids"] == [str(package.id)]
    with pytest.raises(DomainError) as exc:
        packages.package_bytes(package)
    assert exc.value.status == 423
    with pytest.raises(DomainError):
        mail.queue_dispatch(actor, package.id, "blocked-send")
    assert client.get(f"/api/packages/{package.id}/download/").status_code == 423
    assert storage.path(package.path).read_bytes() == original
    detail = services.document_data(doc, True)
    assert not detail["metadata"] and not detail["parser_result"] and not detail["revisions"]


@pytest.mark.clamav
@pytest.mark.skipif(
    __import__("os").environ.get("RUN_CLAMAV_TESTS") != "1",
    reason="requires real clamd with fresh signatures",
)
def test_real_clamav_instream_and_formats(actor, companies):
    assert scanner.scan(EICAR).result == "infected"
    assert scanner.scan(sample_pdf(["safe"])).result == "clean"
    for data, name in [
        (sample_pdf(["real"]), "real.pdf"),
        (sample_image(), "real.png"),
        (sample_jpeg(), "real.jpg"),
        (sample_camt(), "real.xml"),
    ]:
        value = services.ingest(actor, name, data, companies[0].id)
        security.run_scan(value["document"]["id"])
        doc = Document.objects.get(id=value["document"]["id"])
        assert doc.security_status == "clean", doc.security_error
        assert storage.read_original(doc) == data
    doc = ingest(actor, companies, EICAR)
    security.run_scan(doc.id)
    doc.refresh_from_db()
    assert doc.security_status == "infected"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    output = io.BytesIO()
    writer.write(output)
    assert scanner.scan(output.getvalue()).result != "clean"
    assert scanner.scan(b"x" * (25 * 1024 * 1024 + 1)).result == "error"
    nested = b"harmless nested content"
    for _ in range(20):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("nested.zip", nested)
        nested = archive.getvalue()
    assert scanner.scan(nested).result == "error"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for number in range(1005):
            z.writestr(f"{number}.txt", b"harmless test content")
    assert scanner.scan(archive.getvalue()).result == "error"
