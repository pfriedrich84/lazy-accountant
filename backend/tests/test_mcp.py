import asyncio
import re
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import httpx2
import pytest
import uvicorn
from asgiref.sync import sync_to_async
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from accounting import jobs, storage
from accounting.auth import issue_token
from accounting.demo import sample_camt, sample_image, sample_pdf
from accounting.models import Account, Document, Job, Mailbox


@pytest.fixture(scope="module")
def mcp_url(django_db_setup):
    from config.asgi import application

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive()


@pytest.mark.django_db(transaction=True)
def test_real_streamable_http_month_and_skill_contract(mcp_url, actor, companies):
    company = companies[0]
    token = issue_token(actor, "mcp-test", [company.id], ["read", "process", "inbox"])["token"]
    readonly = issue_token(actor, "mcp-readonly", [company.id], ["read"])["token"]
    accounts = {a.kind: a.id for a in Account.objects.filter(company=company)}
    identifiers = []

    async def scenario():
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=30) as http:
            assert (await http.get(mcp_url + "/mcp/", headers={"Host": "evil.example"})).status_code in {
                400,
                403,
                421,
            }
            async with Client(streamable_http_client(mcp_url + "/mcp/", http_client=http)) as client:
                tools = await client.list_tools()
                names = {t.name for t in tools.tools}
                for skill in Path("skills").glob("*/SKILL.md"):
                    text = skill.read_text()
                    invoked = set(re.findall(r"`([a-z][a-z_]+)\(", text))
                    assert invoked <= names, (skill, invoked - names)
                schema = next(t.input_schema for t in tools.tools if t.name == "save_document_result")
                assert "result" in schema["properties"]

                async def call(name, arguments):
                    response = await client.call_tool(name, arguments)
                    assert not response.is_error, response
                    data = response.structured_content
                    return data["result"] if data and set(data) == {"result"} else data

                assigned = await call("list_assignments", {"company_id": company.id})
                assert len(assigned["accounts"]) == 2
                run = await call(
                    "start_agent_run",
                    {"company_id": company.id, "period": "2026-10", "idempotency_key": "mcp-month"},
                )
                fixtures = [
                    "outgoing_invoice",
                    "incoming_invoice",
                    "incoming_credit",
                    "bank_camt",
                    "bank_pdf",
                    "security_pdf",
                    "receipt",
                ]
                for index, kind in enumerate(fixtures):
                    data = (
                        sample_camt()
                        if kind == "bank_camt"
                        else sample_image()
                        if kind == "receipt"
                        else sample_pdf(["MCP synthetic", kind, "EUR 120.00"])
                    )
                    filename = kind + (
                        ".xml" if kind == "bank_camt" else ".png" if kind == "receipt" else ".pdf"
                    )
                    ticket = await call(
                        "prepare_upload",
                        {
                            "filename": filename,
                            "size": len(data),
                            "sha256": storage.checksum(data),
                            "company_id": company.id,
                        },
                    )
                    r = await http.put(
                        mcp_url + ticket["url"],
                        content=data,
                        headers={"Content-Type": "application/octet-stream"},
                    )
                    assert r.status_code == 200, r.text
                    doc = await call("complete_upload", {"upload_id": ticket["upload_id"]})
                    assert (await call("complete_upload", {"upload_id": ticket["upload_id"]}))["id"] == doc[
                        "id"
                    ]
                    identifiers.append(doc["id"])
                    await call(
                        "claim_document",
                        {"document_id": doc["id"], "run_id": run["id"], "base_version": doc["version"]},
                    )
                    readable = await call("read_document", {"document_id": doc["id"]})
                    if kind == "bank_camt":
                        assert readable["structured"]["statements"][0]["entries"][0]["amount"] == "120.00"
                    elif kind == "receipt":
                        response = await client.call_tool("read_page_image", {"document_id": doc["id"]})
                        assert not response.is_error
                        assert any(c.type == "image" for c in response.content)
                    else:
                        assert "MCP synthetic" in readable["text"]
                    access = await call("get_file_access", {"document_id": doc["id"]})
                    original = await http.get(mcp_url + access["original_url"])
                    assert original.content == data
                    bank = kind in {"bank_camt", "bank_pdf", "security_pdf"}
                    metadata = (
                        {"period_start": "2026-10-01", "period_end": "2026-10-28"}
                        if bank
                        else {}
                        if kind == "receipt"
                        else {
                            "issuer": "Lieferant",
                            "recipient": company.name,
                            "number": f"MCP-{index}",
                            "date": "2026-10-15",
                            "net": "100.00",
                            "tax": "20.00",
                            "gross": "120.00",
                            "currency": "EUR",
                        }
                    )
                    result = {
                        "document_id": doc["id"],
                        "base_version": doc["version"],
                        "company_id": company.id,
                        "kind": kind,
                        "period": "2026-10",
                        "metadata": metadata,
                        "category_id": assigned["categories"][0]["id"] if index == 0 else None,
                        "account_id": accounts["depot" if kind == "security_pdf" else "bank"]
                        if bank
                        else None,
                        "approve": True,
                    }
                    saved = await call("save_document_result", {"result": result, "run_id": run["id"]})
                    assert saved["status"] == "ready"
                    conflict = await client.call_tool(
                        "save_document_result", {"result": result, "run_id": run["id"]}
                    )
                    assert conflict.is_error
                # Names use the same versioned service as REST; manual overrides survive backfill.
                doc = await call("get_document", {"document_id": identifiers[1]})
                assert doc["name_source"] == "generated" and doc["proposed_name"] == doc["effective_name"]
                renamed = await call(
                    "set_document_name",
                    {
                        "document_id": doc["id"],
                        "base_version": doc["version"],
                        "name": "MCP Übergabe.pdf",
                    },
                )
                assert renamed["status"] == "ready" and renamed["original_name"] == doc["original_name"]
                conflict = await client.call_tool(
                    "set_document_name",
                    {
                        "document_id": doc["id"],
                        "base_version": doc["version"],
                        "name": "Stale.pdf",
                    },
                )
                assert conflict.is_error
                names_preview = await call("preview_document_names", {"document_ids": [doc["id"]]})
                assert (
                    names_preview[0]["manual_protected"]
                    and names_preview[0]["new_name"] == "MCP Übergabe.pdf"
                )
                backfilled = await call(
                    "backfill_document_names",
                    {
                        "entries": [
                            {
                                "document_id": doc["id"],
                                "base_version": renamed["version"],
                            }
                        ]
                    },
                )
                assert backfilled[0]["effective_name"] == "MCP Übergabe.pdf"
                assert backfilled[0]["version"] == renamed["version"]
                # Paginates the complete month without skipping any UUID, including during repeat runs.
                cursor, found = None, []
                while True:
                    page = await call(
                        "list_documents",
                        {
                            "company_id": company.id,
                            "period": "2026-10",
                            "status": None,
                            "limit": 2,
                            "cursor": cursor,
                        },
                    )
                    found.extend(d["id"] for d in page["results"])
                    cursor = page["next_cursor"]
                    if not cursor:
                        break
                assert set(found) == set(identifiers)
                assert (await call("list_documents", {"company_id": company.id, "status": "open"}))[
                    "total"
                ] == 0
                folders = await call("list_month_folders", {"company_id": company.id, "period": "2026-10"})
                assert {f["name"] for f in folders["folders"]} == set(storage.FOLDERS)
                preview = await call("preview_package", {"company_id": company.id, "periods": ["2026-10"]})
                assert preview["count"] == 7 and not preview["excluded"]
                package_job = await call(
                    "create_package",
                    {"company_id": company.id, "periods": ["2026-10"], "idempotency_key": "mcp-package"},
                )

                def run_and_close():
                    from django.db import connections

                    try:
                        return jobs.run_job(package_job["id"])
                    finally:
                        connections.close_all()

                await sync_to_async(run_and_close)()
                completed = await call("get_job", {"job_id": package_job["id"]})
                assert completed["status"] == "done", completed
                package = await call("get_package", {"package_id": completed["result"]["id"]})
                archive = await http.get(mcp_url + package["download_url"])
                assert storage.checksum(archive.content) == package["sha256"]
                again = await call(
                    "create_package",
                    {"company_id": company.id, "periods": ["2026-10"], "idempotency_key": "mcp-package"},
                )
                assert again["id"] == package_job["id"]
                await call(
                    "report_agent_run",
                    {"job_id": run["id"], "result": {"package_id": package["id"], "documents": identifiers}},
                )
                assert (await call("get_job", {"job_id": run["id"]}))["status"] == "done"
                # Proposal-only reporting needs process, not admin; it must not
                # create categories or recategorize already approved documents.
                assert not assigned["permissions"]["admin"]
                before = {id: await call("get_document", {"document_id": id}) for id in identifiers}
                category_run = await call(
                    "start_agent_run",
                    {"company_id": company.id, "period": "2026-10", "idempotency_key": "category-analysis"},
                )
                suggestions = [
                    {
                        "company_id": company.id,
                        "name": "Synthetische Testbelege",
                        "existing_category_id": None,
                        "reason": "Die gelesenen Beispieldokumente enthalten die Kennzeichnung MCP synthetic.",
                        "document_ids": identifiers[:2],
                    }
                ]
                report = {
                    "analysis_only": True,
                    "documents": identifiers,
                    "category_suggestions": suggestions,
                }
                await call(
                    "report_agent_run", {"job_id": category_run["id"], "status": "running", "result": report}
                )
                progress = await call("get_job", {"job_id": category_run["id"]})
                assert progress["result"] == report
                await call(
                    "report_agent_run",
                    {"job_id": category_run["id"], "status": "done", "result": progress["result"]},
                )
                finished = await call("get_job", {"job_id": category_run["id"]})
                assert finished["status"] == "done" and finished["result"] == report
                assert (await call("list_assignments", {"company_id": company.id}))["categories"] == assigned[
                    "categories"
                ]
                for id in identifiers:
                    after = await call("get_document", {"document_id": id})
                    assert after == before[id]
                assert before[identifiers[0]]["category_id"] == assigned["categories"][0]["id"]
                assert (await call("get_package", {"package_id": package["id"]}))["sha256"] == package[
                    "sha256"
                ]
                # Token has no permission on the other company or on SMTP.
                forbidden = await client.call_tool("list_assignments", {"company_id": companies[1].id})
                assert forbidden.is_error
                forbidden = await client.call_tool(
                    "send_package", {"package_id": package["id"], "idempotency_key": "no-send-right"}
                )
                assert forbidden.is_error
        async with httpx2.AsyncClient() as http:
            assert (await http.get(mcp_url + "/mcp/")).status_code == 401
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + readonly}) as http:
            async with Client(streamable_http_client(mcp_url + "/mcp/", http_client=http)) as client:
                denied = await client.call_tool(
                    "prepare_upload",
                    {"filename": "x.pdf", "size": 1, "sha256": "a" * 64, "company_id": company.id},
                )
                assert denied.is_error
                preview = await client.call_tool("preview_document_names", {"document_ids": [identifiers[1]]})
                assert not preview.is_error
                denied = await client.call_tool(
                    "set_document_name",
                    {
                        "document_id": identifiers[1],
                        "base_version": 3,
                        "name": "Forbidden.pdf",
                    },
                )
                assert denied.is_error
                denied = await client.call_tool(
                    "backfill_document_names",
                    {
                        "entries": [
                            {
                                "document_id": identifiers[1],
                                "base_version": 3,
                            }
                        ]
                    },
                )
                assert denied.is_error

    with patch("accounting.jobs._publish"):
        asyncio.run(scenario())
    assert Document.objects.count() == 7


@pytest.mark.django_db(transaction=True)
def test_explicit_mcp_imap_works_with_checkbox_off_but_requires_process_scope(mcp_url, actor, companies):
    company = companies[0]
    mailbox = Mailbox.objects.create(company=company, enabled=False)
    token = issue_token(actor, "manual-imap", [company.id], ["read", "process"])["token"]
    readonly = issue_token(actor, "no-imap", [company.id], ["read"])["token"]

    async def scenario():
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
            async with Client(streamable_http_client(mcp_url + "/mcp/", http_client=http)) as client:
                response = await client.call_tool(
                    "start_imap_import", {"company_id": company.id, "idempotency_key": "explicit-mcp"}
                )
                assert not response.is_error
                job_id = response.structured_content["id"]
                result = await sync_to_async(jobs.run_job)(job_id)
                assert result["status"] == "done" and result["result"]["messages"] == 0
                await sync_to_async(Job.objects.filter(id=job_id).update)(status="failed")
                response = await client.call_tool("resume_job", {"job_id": job_id})
                assert not response.is_error
                result = await sync_to_async(jobs.run_job)(job_id)
                assert result["status"] == "done"
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + readonly}) as http:
            async with Client(streamable_http_client(mcp_url + "/mcp/", http_client=http)) as client:
                denied = await client.call_tool(
                    "start_imap_import", {"company_id": company.id, "idempotency_key": "forbidden-mcp"}
                )
                assert denied.is_error

    with (
        patch("accounting.jobs._publish"),
        patch("accounting.mail.scan_mailbox", return_value={"messages": 0, "remaining": 0}) as scan,
    ):
        asyncio.run(scenario())
    assert scan.call_count == 2 and Job.objects.filter(kind="imap").count() == 1
    mailbox.refresh_from_db()
    assert not mailbox.enabled
