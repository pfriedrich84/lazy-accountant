from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from pydantic import ValidationError

from accounting import services, storage, transfers
from accounting.auth import DomainError, issue_token, token_actor
from accounting.demo import sample_camt, sample_image, sample_pdf
from accounting.models import Document, FileOperation
from accounting.schemas import Metadata

pytestmark = pytest.mark.django_db


def result(doc, company_id, **overrides):
    return {
        "document_id": doc["id"],
        "base_version": doc["version"],
        "company_id": company_id,
        "kind": "incoming_invoice",
        "period": "2026-10",
        "metadata": {
            "issuer": "Lieferant",
            "recipient": "Beispiel GmbH",
            "number": "RE-1",
            "date": "2026-10-14",
            "net": "100.00",
            "tax": "20.00",
            "gross": "120.00",
            "currency": "EUR",
        },
        **overrides,
    }


def test_exact_original_and_folders(actor, companies):
    data = sample_pdf(["invoice"])
    d = services.ingest(actor, "../../bad.pdf", data, companies[0].id)["document"]
    d = services.save_result(actor, result(d, companies[0].id, approve=True))
    assert d["filed_path"].startswith("Beispiel-GmbH/2026/10/ER/")
    assert ".." not in storage.safe_filename("../../bad.pdf")
    assert storage.path(d["filed_path"]).read_bytes() == data
    for folder in storage.FOLDERS:
        assert storage.path(f"Beispiel-GmbH/2026/10/{folder}").is_dir()
    assert storage.read_original(Document.objects.get(id=d["id"])) == data


def test_same_name_and_company_scoped_dedup(actor, companies):
    a, b = companies
    data = sample_pdf(["same"])
    d1 = services.ingest(actor, "same.pdf", data, a.id)
    assert services.ingest(actor, "same.pdf", data, a.id)["duplicate"]
    d2 = services.ingest(actor, "same.pdf", data, b.id)
    assert d1["document"]["id"] != d2["document"]["id"]
    d3 = services.ingest(actor, "same.pdf", sample_pdf(["different"]), a.id)
    assert d1["document"]["filed_path"] != d3["document"]["filed_path"]


def test_unknown_company_and_missing_values(actor):
    d = services.ingest(actor, "scan.png", sample_image())["document"]
    assert d["company_id"] is None
    assert "Firma ungeklärt" in d["issues"]
    assert d["filed_path"].startswith("_inbox/")


def test_sums_and_optimistic_concurrency(actor, companies):
    d = services.ingest(actor, "a.pdf", sample_pdf(["x"]), companies[0].id)["document"]
    p = result(d, companies[0].id)
    p["metadata"]["gross"] = "121.00"
    updated = services.save_result(actor, p)
    assert any("Brutto" in i for i in updated["issues"])
    with pytest.raises(DomainError, match="inzwischen"):
        services.save_result(actor, p)
    p = result(updated, companies[0].id)
    p["metadata"]["taxes"] = [{"net": "100", "tax": "19", "rate": "20"}]
    p["approve"] = True
    with pytest.raises(DomainError, match="Prüfpunkte"):
        services.save_result(actor, p)
    with pytest.raises(ValidationError):
        Metadata(net=0.1)
    with pytest.raises(ValidationError):
        Metadata(net="NaN")


def test_authorization_including_files(client, actor, companies):
    d = services.ingest(actor, "a.pdf", sample_pdf(["private"]), companies[0].id)["document"]
    outsider = get_user_model().objects.create_user("outsider")
    client.force_login(outsider)
    for suffix in ("", "original/", "page/", "text/", "duplicates/"):
        assert client.get(f"/api/documents/{d['id']}/{suffix}").status_code == 404
    token = issue_token(actor, "readonly", [companies[1].id], ["read"])["token"]
    scoped = token_actor(token)
    with pytest.raises(DomainError):
        services.get_document(scoped, d["id"])
    with pytest.raises(DomainError):
        services.ingest(scoped, "x.pdf", sample_pdf(["x"]), companies[1].id)


def test_reconciliation_after_interruption(actor, companies):
    d = services.ingest(actor, "a.pdf", sample_pdf(["recover"]), companies[0].id)["document"]
    old = d["filed_path"]
    with patch("accounting.storage.atomic_write", side_effect=OSError("disk")):
        updated = services.save_result(actor, result(d, companies[0].id))
    assert FileOperation.objects.filter(document_id=d["id"], status="pending").exists()
    assert storage.path(old).exists()
    storage.reconcile()
    doc = Document.objects.get(id=d["id"])
    assert doc.version == updated["version"]
    assert doc.filed_path != old
    assert not storage.path(old).exists()
    assert storage.path(doc.filed_path).exists()
    storage.reconcile()


def test_camt_errors_preserve_original(actor, companies):
    good = sample_camt()
    d = services.ingest(actor, "camt.xml", good, companies[0].id)["document"]
    doc = Document.objects.get(id=d["id"])
    assert doc.parser_result["statements"][0]["entries"][0]["amount"] == "120.00"
    unsupported = good.replace(b"camt.053.001.08", b"camt.053.001.99")
    r = services.ingest(actor, "unsupported.xml", unsupported, companies[0].id)["document"]
    doc = Document.objects.get(id=r["id"])
    assert "Nicht unterstützter" in doc.parser_error
    assert storage.read_original(doc) == unsupported
    malicious = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Document>&e;</Document>'
    )
    r = services.ingest(actor, "evil.xml", malicious, companies[0].id)["document"]
    assert Document.objects.get(id=r["id"]).parser_error


def test_upload_transfer_and_idempotency(actor, companies, client):
    data = sample_pdf(["MCP Transfer"])
    t = transfers.prepare_upload(actor, "mcp.pdf", len(data), storage.checksum(data), companies[0].id)
    with pytest.raises(DomainError):
        transfers.put_upload(actor, t["upload_id"], b"bad")
    assert client.put(t["url"], data, content_type="application/octet-stream").status_code == 200
    d = transfers.complete_upload(actor, t["upload_id"])
    assert transfers.complete_upload(actor, t["upload_id"])["id"] == d["id"]
    assert services.ingest(actor, "mcp.pdf", data, companies[0].id, "same-key")["duplicate"]
    with pytest.raises(DomainError, match="Idempotenz"):
        services.ingest(actor, "changed.pdf", sample_pdf(["changed"]), companies[0].id, "same-key")


def test_pages_text_and_image(actor, companies):
    d = services.ingest(actor, "text.pdf", sample_pdf(["Known PDF text"]), companies[0].id)["document"]
    assert "Known PDF text" in services.readable_document(actor, d["id"])["text"]
    assert services.readable_document(actor, d["id"], image=True).startswith(b"\x89PNG")
    d = services.ingest(actor, "scan.png", sample_image(), companies[0].id)["document"]
    assert services.readable_document(actor, d["id"])["text"] == ""
    assert services.readable_document(actor, d["id"], image=True).startswith(b"\x89PNG")


def test_rest_upload_and_login_csrf(client, companies):
    f = SimpleUploadedFile("a.pdf", sample_pdf(["REST"]), content_type="application/pdf")
    response = client.post(
        "/api/documents/", {"files": [f], "company_id": companies[0].id}, format="multipart"
    )
    assert response.status_code == 201
    from django.test import Client

    anonymous = Client(enforce_csrf_checks=True)
    assert (
        anonymous.post(
            "/api/auth/login/",
            '{"username":"test","password":"test-password-12345"}',
            content_type="application/json",
        ).status_code
        == 403
    )
    token = anonymous.get("/api/auth/csrf/").json()["csrfToken"]
    assert (
        anonymous.post(
            "/api/auth/login/",
            '{"username":"test","password":"test-password-12345"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        ).status_code
        == 200
    )
