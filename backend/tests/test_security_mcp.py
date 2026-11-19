"""Actual MCP transport plus real ClamAV, using only the harmless EICAR string."""

import asyncio
import os

import httpx2
import pytest
from asgiref.sync import sync_to_async
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from accounting import mail, security, storage
from accounting.auth import issue_token
from accounting.models import Document, Mailbox
from test_mcp import mcp_url  # noqa: F401
from test_security import EICAR
from email.message import EmailMessage


@pytest.mark.security
@pytest.mark.clamav
@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(os.environ.get("RUN_CLAMAV_TESTS") != "1", reason="requires real clamd")
def test_real_clamav_rest_mcp_imap(mcp_url, client, actor, companies, monkeypatch):  # noqa: F811
    from django.core.files.uploadedfile import SimpleUploadedFile

    monkeypatch.setattr(security, "publish", lambda identifier: None)
    company = companies[0]
    response = client.post(
        "/api/documents/",
        {
            "company_id": company.id,
            "file": SimpleUploadedFile("rest.txt", EICAR),
        },
    )
    identifier = response.json()["results"][0]["document"]["id"]
    assert client.get(f"/api/documents/{identifier}/original/").status_code == 423
    security.run_scan(identifier)
    assert Document.objects.get(id=identifier).security_status == "infected"
    # Separate tenant prevents dedup from skipping the second actual scan.
    token = issue_token(actor, "security-test", [companies[1].id], ["read", "process"])["token"]

    async def scenario():
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=30) as http:
            async with Client(streamable_http_client(mcp_url + "/mcp/", http_client=http)) as mcp:

                async def call(name, arguments):
                    value = await mcp.call_tool(name, arguments)
                    assert not value.is_error, value
                    data = value.structured_content
                    return data["result"] if data and set(data) == {"result"} else data

                ticket = await call(
                    "prepare_upload",
                    {
                        "filename": "mcp.txt",
                        "size": len(EICAR),
                        "sha256": storage.checksum(EICAR),
                        "company_id": companies[1].id,
                    },
                )
                response = await http.put(mcp_url + ticket["url"], content=EICAR)
                assert response.status_code == 200
                doc = await call("complete_upload", {"upload_id": ticket["upload_id"]})
                assert doc["security_status"] == "pending"
                await sync_to_async(security.run_scan)(doc["id"])
                detail = await call("get_document", {"document_id": doc["id"]})
                assert detail["security_status"] == "infected"
                for tool in ("read_document", "read_page_image", "claim_document"):
                    arguments = {"document_id": doc["id"]}
                    if tool == "claim_document":
                        arguments.update(run_id="test", base_version=1)
                    assert (await mcp.call_tool(tool, arguments)).is_error
                access = await call("get_file_access", {"document_id": doc["id"]})
                assert "original_url" not in access
                for representation in ("original", "text", "page"):
                    assert (
                        await http.get(mcp_url + f"/api/documents/{doc['id']}/{representation}/")
                    ).status_code == 423

    asyncio.run(scenario())
    # Unassigned inbox creates a third independent import and scan.
    mailbox = Mailbox.objects.create(company=company, aliases=["unmatched@example.test"])
    message = EmailMessage()
    message.set_content("Harmless antivirus test")
    message.add_attachment(EICAR, maintype="application", subtype="octet-stream", filename="imap.txt")
    mail.import_message(actor, mailbox, "1", "1", message.as_bytes())
    source = mailbox.importsource_set.get()
    security.run_scan(source.document_id)
    source.document.refresh_from_db()
    assert source.document.security_status == "infected"
    mail.import_message(actor, mailbox, "1", "1", message.as_bytes())
    assert mailbox.importsource_set.count() == 1
