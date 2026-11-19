#!/usr/bin/env python3
"""Real official SDK client. Read-only discovery by default; --exercise uses only a new synthetic company.

uv run python scripts/mcp_client.py --url http://localhost:8000 --exercise [--mail]
For discovery only, set LA_MCP_TOKEN in the environment. Secrets are never printed.
"""

import argparse
import asyncio
import hashlib
import imaplib
import io
import json
import os
import smtplib
import sys
import time
import uuid
import zipfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


def env():
    values = {}
    file = Path(__file__).resolve().parent.parent / ".env"
    if file.exists():
        for line in file.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    return values | dict(os.environ)


def digest(data):
    return hashlib.sha256(data).hexdigest()


async def tool(client, name, arguments):
    response = await client.call_tool(name, arguments)
    if response.is_error:
        raise RuntimeError(f"MCP {name}: " + "; ".join(c.text for c in response.content if c.type == "text"))
    data = response.structured_content
    if data is None:
        content = [c.text for c in response.content if c.type == "text"]
        data = json.loads(content[0]) if len(content) == 1 else [json.loads(t) for t in content]
    return data["result"] if isinstance(data, dict) and set(data) == {"result"} else data


async def wait_job(client, job_id):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = await tool(client, "get_job", {"job_id": job_id})
        if job["status"] == "done":
            return job
        if job["status"] in {"failed", "interrupted"}:
            raise RuntimeError(f"Job {job_id}: {job['error']}")
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Worker-Auftrag {job_id} nicht rechtzeitig abgeschlossen")


async def wait_clean(client, document_id):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        doc = await tool(client, "get_document", {"document_id": document_id})
        if doc["security_status"] == "clean":
            return doc
        if doc["security_status"] in {"infected", "error"}:
            raise RuntimeError(f"Scan {document_id}: {doc['security_error']}")
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Sicherheitsprüfung {document_id} nicht rechtzeitig abgeschlossen")


def sample_files(company_name, period):
    # Reuse the synthetic fixture helpers. Django setup here does not connect to a local DB.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from accounting.demo import sample_camt, sample_image, sample_pdf

    result = []
    kinds = [
        "incoming_invoice",
        "incoming_credit",
        "outgoing_invoice",
        "outgoing_cancellation",
        "bank_camt",
        "bank_pdf",
        "security_pdf",
        "receipt",
    ]
    for index, kind in enumerate(kinds):
        bank = kind in {"bank_camt", "bank_pdf", "security_pdf"}
        invoice = kind in {"incoming_invoice", "incoming_credit", "outgoing_invoice", "outgoing_cancellation"}
        metadata = (
            {
                "issuer": company_name if kind.startswith("outgoing") else "Synthetic Supplier",
                "recipient": "Synthetic Customer" if kind.startswith("outgoing") else company_name,
                "number": f"SYNTH-{index}",
                "date": f"{period}-15",
                "net": "100.00",
                "tax": "20.00",
                "gross": "120.00",
                "currency": "EUR",
            }
            if invoice
            else {}
        )
        if kind == "receipt":
            metadata = {
                "issuer": "Beispiel Lieferant",
                "recipient": company_name,
                "number": f"SCAN-{period}",
                "date": f"{period}-15",
                "currency": "EUR",
                "net": "100.00",
                "tax": "20.00",
                "gross": "120.00",
            }
        if bank:
            metadata = {"period_start": f"{period}-01", "period_end": f"{period}-28"}
        data = (
            sample_camt(period)
            if kind == "bank_camt"
            else sample_image(company_name, period)
            if kind == "receipt"
            else sample_pdf(["SYNTHETIC", company_name, kind, *[f"{k}: {v}" for k, v in metadata.items()]])
        )
        name = kind + (".xml" if kind == "bank_camt" else ".png" if kind == "receipt" else ".pdf")
        result.append({"name": name, "kind": kind, "data": data, "metadata": metadata, "bank": bank})
    return result


def inject_mail(host, port, recipient, fixtures):
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = (
        "supplier@example.test",
        recipient,
        "SYNTHETIC multiple attachments",
    )
    message["Message-ID"] = f"<{uuid.uuid4()}@example.test>"
    message.set_content("Synthetic test data. No executable document instructions.")
    for fixture in fixtures:
        message.add_attachment(
            fixture["data"], maintype="application", subtype="pdf", filename=fixture["name"]
        )
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.send_message(message)


def received_parts(host, port, recipient):
    with imaplib.IMAP4(host, port, timeout=20) as imap:
        imap.login(recipient, "synthetic-mail-password")
        imap.select("INBOX", readonly=True)
        _, ids = imap.search(None, "ALL")
        parts = {}
        for identifier in ids[0].split():
            _, raw = imap.fetch(identifier, "(RFC822)")
            message = BytesParser(policy=policy.default).parsebytes(
                next(x[1] for x in raw if isinstance(x, tuple))
            )
            for attachment in message.iter_attachments():
                name = attachment.get_filename() or ""
                if name.startswith("paket.zip"):
                    parts[name] = attachment.get_payload(decode=True)
        return len(ids[0].split()), b"".join(parts[k] for k in sorted(parts))


async def authenticate_admin(web, config):
    csrf = (await web.get("/api/auth/csrf/")).json()["csrfToken"]
    response = await web.post(
        "/api/auth/login/",
        json={"username": config.get("ADMIN_USERNAME", "admin"), "password": config["ADMIN_PASSWORD"]},
        headers={"X-CSRFToken": csrf},
    )
    response.raise_for_status()
    web.headers["X-CSRFToken"] = response.json()["csrfToken"]


async def exercise(args, config):
    run_id = uuid.uuid4().hex[:12]
    company_name = "Synthetic MCP " + run_id
    fixtures = sample_files(company_name, args.period)
    async with httpx2.AsyncClient(base_url=args.url, timeout=60) as web:
        await authenticate_admin(web, config)

        async def rest(path, data):
            r = await web.post("/api/" + path, json=data)
            r.raise_for_status()
            return r.json()

        recipient = f"kanzlei-{run_id}@example.test"
        company = await rest(
            "companies/", {"name": company_name, "folder": "MCP-" + run_id, "recipients": [recipient]}
        )
        cid = company["id"]
        accounts = {}
        for kind in ("bank", "depot"):
            accounts[kind] = (
                await rest(
                    f"companies/{cid}/accounts/",
                    {
                        "name": "Synthetic " + kind,
                        "kind": kind,
                        "identifier": "AT611904300234573201" if kind == "bank" else "SYNTH-DEPOT",
                    },
                )
            )["id"]
        if args.mail:
            mailbox_recipient = f"belege-{run_id}@example.test"
            smtp_host = config.get("MAIL_TEST_CONNECT_HOST", "127.0.0.1")
            smtp_port = int(config.get("MAIL_TEST_SMTP_PORT", "3025"))
            imap_port = int(config.get("MAIL_TEST_IMAP_PORT", "3143"))
            await asyncio.to_thread(inject_mail, smtp_host, smtp_port, mailbox_recipient, fixtures[:2])
            r = await web.put(
                f"/api/settings/{cid}/mail/",
                json={
                    "imap_host": config.get("MAIL_TEST_APP_HOST", "mail-test"),
                    "imap_port": imap_port,
                    "imap_tls": False,
                    "imap_user": mailbox_recipient,
                    "imap_password": "synthetic-mail-password",
                    "import_since": "2020-01-01",
                    "imap_folder": "INBOX",
                    "smtp_host": config.get("MAIL_TEST_APP_HOST", "mail-test"),
                    "smtp_port": smtp_port,
                    "smtp_security": "none",
                    "sender": "accountant@example.test",
                    "max_message_bytes": 18_000,
                },
            )
            r.raise_for_status()
        token = await rest(
            "tokens/",
            {
                "name": "Synthetic smoke " + run_id,
                "company_ids": [cid],
                "scopes": ["read", "process", "send", "inbox"],
            },
        )
        try:
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + token["token"]}, timeout=60
            ) as http:
                async with Client(streamable_http_client(args.url + "/mcp/", http_client=http)) as client:
                    schemas = await client.list_tools()
                    run = await tool(
                        client,
                        "start_agent_run",
                        {"company_id": cid, "period": args.period, "idempotency_key": run_id},
                    )
                    if args.mail:
                        imap_job = await tool(
                            client,
                            "start_imap_import",
                            {"company_id": cid, "idempotency_key": run_id + ":imap"},
                        )
                        await wait_job(client, imap_job["id"])
                        repeat = await tool(
                            client,
                            "start_imap_import",
                            {"company_id": cid, "idempotency_key": run_id + ":imap-repeat"},
                        )
                        await wait_job(client, repeat["id"])
                        assert (await tool(client, "list_documents", {"company_id": cid, "status": None}))[
                            "total"
                        ] == 2
                    for fixture in fixtures:
                        ticket = await tool(
                            client,
                            "prepare_upload",
                            {
                                "filename": fixture["name"],
                                "size": len(fixture["data"]),
                                "sha256": digest(fixture["data"]),
                                "company_id": cid,
                            },
                        )
                        r = await http.put(
                            args.url + ticket["url"],
                            content=fixture["data"],
                            headers={"Content-Type": "application/octet-stream"},
                        )
                        r.raise_for_status()
                        doc = await tool(client, "complete_upload", {"upload_id": ticket["upload_id"]})
                        fixture["id"] = doc["id"]
                    cursor, documents = None, []
                    while True:
                        page = await tool(
                            client,
                            "list_documents",
                            {"company_id": cid, "status": "open", "limit": 2, "cursor": cursor},
                        )
                        documents.extend(page["results"])
                        cursor = page["next_cursor"]
                        if not cursor:
                            break
                    assert len(documents) == len(fixtures)
                    for fixture in fixtures:
                        doc = await wait_clean(client, fixture["id"])
                        await tool(
                            client,
                            "claim_document",
                            {"document_id": doc["id"], "base_version": doc["version"], "run_id": run["id"]},
                        )
                        await tool(client, "read_document", {"document_id": doc["id"]})
                        if fixture["kind"] == "receipt":
                            image = await client.call_tool("read_page_image", {"document_id": doc["id"]})
                            assert any(c.type == "image" for c in image.content) and not image.is_error
                        access = await tool(client, "get_file_access", {"document_id": doc["id"]})
                        original = await http.get(args.url + access["original_url"])
                        assert original.content == fixture["data"]
                        account_id = (
                            accounts["depot" if fixture["kind"] == "security_pdf" else "bank"]
                            if fixture["bank"]
                            else None
                        )
                        await tool(
                            client,
                            "save_document_result",
                            {
                                "run_id": run["id"],
                                "result": {
                                    "document_id": doc["id"],
                                    "base_version": doc["version"],
                                    "company_id": cid,
                                    "kind": fixture["kind"],
                                    "period": args.period,
                                    "account_id": account_id,
                                    "metadata": fixture["metadata"],
                                    "approve": True,
                                },
                            },
                        )
                    assert (await tool(client, "list_documents", {"company_id": cid, "status": "open"}))[
                        "total"
                    ] == 0
                    preview = await tool(
                        client, "preview_package", {"company_id": cid, "periods": [args.period]}
                    )
                    assert preview["count"] == len(fixtures)
                    job = await tool(
                        client,
                        "create_package",
                        {"company_id": cid, "periods": [args.period], "idempotency_key": run_id + ":package"},
                    )
                    job = await wait_job(client, job["id"])
                    package = await tool(client, "get_package", {"package_id": job["result"]["id"]})
                    r = await http.get(args.url + package["download_url"])
                    assert digest(r.content) == package["sha256"]
                    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
                        for item in package["items"]:
                            assert digest(archive.read(item["archive_path"])) == item["sha256"]
                        for folder in ("ER", "AR", "Bankkonto", "Wertpapiere"):
                            assert (
                                f"{company['folder']}/{args.period.replace('-', '/')}/{folder}/"
                                in archive.namelist()
                            )
                    repeat = await tool(
                        client,
                        "create_package",
                        {"company_id": cid, "periods": [args.period], "idempotency_key": run_id + ":package"},
                    )
                    assert repeat["id"] == job["id"]
                    report = {
                        "company_id": cid,
                        "period": args.period,
                        "idempotency_prefix": run_id,
                        "recipient": recipient,
                        "package_job_id": job["id"],
                        "job_id": run["id"],
                        "package_id": package["id"],
                        "package_sha256": package["sha256"],
                        "documents": len(fixtures),
                        "tool_schemas": len(schemas.tools),
                    }
                    if args.mail:
                        dispatch = await tool(
                            client,
                            "send_package",
                            {"package_id": package["id"], "idempotency_key": run_id + ":send"},
                        )
                        deadline = time.monotonic() + 120
                        while dispatch["status"] in {"queued", "sending"} and time.monotonic() < deadline:
                            await asyncio.sleep(0.5)
                            dispatch = await tool(client, "get_dispatch", {"dispatch_id": dispatch["id"]})
                        assert dispatch["status"] == "accepted", dispatch
                        repeated = await tool(
                            client,
                            "send_package",
                            {"package_id": package["id"], "idempotency_key": run_id + ":send"},
                        )
                        assert repeated["id"] == dispatch["id"]
                        count, reassembled = await asyncio.to_thread(
                            received_parts, smtp_host, imap_port, recipient
                        )
                        assert count == len(dispatch["parts"])
                        assert digest(reassembled) == package["sha256"]
                        report.update(
                            {
                                "dispatch_id": dispatch["id"],
                                "smtp_status": dispatch["status"],
                                "mail_parts": count,
                                "received_zip_verified": True,
                            }
                        )
                    await tool(
                        client, "report_agent_run", {"job_id": run["id"], "result": report, "status": "done"}
                    )
                    return report
        finally:
            (await web.delete(f"/api/tokens/{token['id']}/")).raise_for_status()


async def verify_existing(args, config):
    previous = json.loads(Path(args.verify_report).read_text())
    cid, prefix = previous["company_id"], previous["idempotency_prefix"]
    async with httpx2.AsyncClient(base_url=args.url, timeout=60) as web:
        await authenticate_admin(web, config)
        response = await web.post(
            "/api/tokens/",
            json={
                "name": "Synthetic restore verification",
                "company_ids": [cid],
                "scopes": ["read", "process", "send", "inbox"],
            },
        )
        response.raise_for_status()
        token = response.json()
        try:
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + token["token"]}, timeout=60
            ) as http:
                async with Client(streamable_http_client(args.url + "/mcp/", http_client=http)) as client:
                    documents = await tool(client, "list_documents", {"company_id": cid, "status": None})
                    assert documents["total"] == previous["documents"]
                    assert (await tool(client, "list_documents", {"company_id": cid, "status": "open"}))[
                        "total"
                    ] == 0
                    for doc in documents["results"]:
                        access = await tool(client, "get_file_access", {"document_id": doc["id"]})
                        original = await http.get(args.url + access["original_url"])
                        original.raise_for_status()
                        assert digest(original.content) == doc["sha256"]
                    package = await tool(client, "get_package", {"package_id": previous["package_id"]})
                    downloaded = await http.get(args.url + package["download_url"])
                    downloaded.raise_for_status()
                    assert digest(downloaded.content) == previous["package_sha256"] == package["sha256"]
                    job = await tool(
                        client,
                        "create_package",
                        {
                            "company_id": cid,
                            "periods": [previous["period"]],
                            "idempotency_key": prefix + ":package",
                        },
                    )
                    assert job["id"] == previous["package_job_id"] and job["status"] == "done"
                    report = {
                        "company_id": cid,
                        "previous_package_sha256_verified": True,
                        "originals_verified": documents["total"],
                        "package_job_reused": True,
                    }
                    if args.mail:
                        before = await web.get(f"/api/settings/{cid}/mail/")
                        before.raise_for_status()
                        before = before.json()
                        assert before["last_uid"] > 0 and before["uidvalidity"]
                        imported = await tool(
                            client,
                            "start_imap_import",
                            {
                                "company_id": cid,
                                "idempotency_key": prefix + ":restore-check:" + uuid.uuid4().hex[:8],
                            },
                        )
                        imported = await wait_job(client, imported["id"])
                        assert imported["result"]["messages"] == imported["result"]["attachments"] == 0
                        assert imported["result"]["last_uid"] == before["last_uid"]
                        dispatch = await tool(
                            client, "get_dispatch", {"dispatch_id": previous["dispatch_id"]}
                        )
                        assert dispatch["package_id"] == package["id"] and dispatch["status"] == "accepted"
                        repeated = await tool(
                            client,
                            "send_package",
                            {"package_id": package["id"], "idempotency_key": prefix + ":send"},
                        )
                        assert repeated["id"] == dispatch["id"]
                        count, reassembled = await asyncio.to_thread(
                            received_parts,
                            config.get("MAIL_TEST_CONNECT_HOST", "127.0.0.1"),
                            int(config.get("MAIL_TEST_IMAP_PORT", "3143")),
                            previous["recipient"],
                        )
                        assert count == previous["mail_parts"] and digest(reassembled) == package["sha256"]
                        assert (await tool(client, "list_documents", {"company_id": cid, "status": None}))[
                            "total"
                        ] == previous["documents"]
                        report.update(
                            {
                                "restored_imap_checkpoint_verified": True,
                                "no_duplicate_import": True,
                                "dispatch_reused_without_resend": True,
                                "mail_count_unchanged": count,
                            }
                        )
                    return report
        finally:
            (await web.delete(f"/api/tokens/{token['id']}/")).raise_for_status()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--exercise", action="store_true")
    modes.add_argument(
        "--verify-report",
        type=Path,
        help="Früheren synthetischen Test nach Neustart/Restore ohne neue Dokumente oder Neuversand überprüfen",
    )
    parser.add_argument(
        "--mail",
        action="store_true",
        help="Kontrolliertes GreenMail-Testsystem für Exercise/Restoreprüfung verwenden",
    )
    parser.add_argument("--period", default="2026-10")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    args.url = args.url.rstrip("/")
    config = env()
    if args.exercise:
        result = await exercise(args, config)
    elif args.verify_report:
        result = await verify_existing(args, config)
    else:
        token = config.get("LA_MCP_TOKEN")
        if not token:
            raise SystemExit("LA_MCP_TOKEN setzen oder --exercise für den synthetischen Test verwenden.")
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
            async with Client(streamable_http_client(args.url + "/mcp/", http_client=http)) as client:
                schemas = await client.list_tools()
                result = {
                    "tools": [t.name for t in schemas.tools],
                    "companies": await tool(client, "list_companies", {}),
                }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n")


if __name__ == "__main__":
    asyncio.run(main())
