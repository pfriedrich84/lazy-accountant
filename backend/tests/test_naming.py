"""Synthetic metadata/bytes only; no production documents are used."""

import io
import unicodedata
import uuid
import zipfile
from urllib.parse import unquote

import pytest
from openpyxl import load_workbook

from accounting import name_changes, naming, packages, services, storage
from accounting.auth import DomainError
from accounting.demo import sample_pdf
from accounting.models import Account, Document, Membership, Package
from accounting.schemas import Metadata


def synthetic(kind="incoming_invoice", original="Rechnung_1.pdf", account=None, **metadata):
    doc = Document(
        id=uuid.uuid4(),
        original_name=original,
        original_path="_originals/test.pdf",
        company_id=1,
        inbox_owner_id=1,
        kind=kind,
        period="2026-10",
        account=account,
        metadata=Metadata.model_validate(metadata).model_dump(mode="json"),
    )
    if kind == "bank_camt":
        doc.original_path = "_originals/test.xml"
    return doc


@pytest.mark.parametrize(
    "date,issuer,number,original",
    [
        (
            "2026-10-31",
            "HoT Telekom und Service GmbH",
            "1008622969853",
            "2026-10-31 HoT Telekom und Service GmbH Rechnung 1008622969853.pdf",
        ),
        ("2026-08-31", "HoT Telekom und Service GmbH", "1008410720292", "Rechnung_1.pdf"),
        ("2026-09-25", "GitHub, Inc.", "INV157622896", "INV157622896.pdf"),
        ("2026-10-25", "GitHub, Inc.", "INV163069444", "INV163069444 (1).pdf"),
        ("2026-08-31", "Digital Charging Solutions GmbH", "KAT00079059", "INV_KAT00079059.pdf"),
        (
            "2026-08-26",
            "Plachetka & Partner Steuerberatungsgesellschaft m.b.H.",
            "20261478",
            "Ausdruck_Rechnung.pdf",
        ),
        (
            "2026-11-05",
            "Denzel Grünzweig GmbH",
            "37-106229",
            "2005-11-26 Denzel Grünzweig GmbH Rechnung Denzel Grünzweig GmbH.pdf",
        ),
        (
            "2026-08-29",
            "Neue Medien Münnich",
            "2261526863",
            "2026-08-29 Neue Medien Münnich Rechnung Neue Medien Münnich.pdf",
        ),
        ("2026-09-01", "X1F Austria GmbH", "0040", "Rechnung_0040.pdf"),
        ("2026-08-18", "X1F Austria GmbH", "0039", "auto service august.pdf"),
        ("2026-08-18", "X1F Austria GmbH", "0039", "Rechnung_0039 (1).pdf"),
        ("2026-11-06", "X1F Austria GmbH", "INV-2026-00002", "Rechnung_INV202600002.pdf"),
    ],
)
def test_issue_invoice_examples(date, issuer, number, original):
    doc = synthetic(date=date, issuer=issuer, number=number, original=original)
    result = naming.proposal(doc)
    assert result == {"name": f"{date} {issuer} Rechnung {number}.pdf", "source": "generated", "warning": ""}
    assert doc.original_name == original and doc.metadata["number"] == number
    assert doc.period == "2026-10"  # Handover period is independent of the document date.


def test_bank_and_securities_examples():
    account = Account(id=1, company_id=1, name="Konto 6600", kind="bank", identifier="AT022011184817806600")
    for kind, number, label, date in [
        ("bank_pdf", "011-2026", "Kontoauszug", "2026-10-30"),
        ("bank_camt", "202609302359000", "CAMT", "2026-09-30"),
    ]:
        doc = synthetic(
            kind,
            account=account,
            date="2026-11-01",
            period_end=date,
            bank_short_name="Erste Bank",
            number=number,
        )
        ext = ".xml" if kind == "bank_camt" else ".pdf"
        assert naming.proposal(doc)["name"] == f"{date} Erste Bank Konto 6600 {label} {number}{ext}"
    account.kind, account.name = "depot", "Depot 848-178-066-01 A"
    statement = synthetic(
        "security_pdf",
        account=account,
        bank_short_name="Erste Bank",
        date="2026-10-05",
        valuation_date="2026-09-30",
        subtype="Depotaufstellung",
    )
    assert (
        naming.proposal(statement)["name"]
        == "2026-09-30 Erste Bank Depot 848-178-066-01 A Depotaufstellung.pdf"
    )
    statement.metadata["valuation_date"] = None
    assert naming.proposal(statement)["source"] == "fallback"  # Never use creation date instead.
    income = synthetic(
        "security_pdf",
        account=account,
        bank_short_name="Erste Bank",
        date="2026-10-15",
        subtype="Ausschüttung",
        isin="DE000A0F5UH1",
    )
    assert naming.proposal(income)["name"] == "2026-10-15 Erste Bank Ausschüttung DE000A0F5UH1.pdf"
    income.metadata["bank_short_name"] = None
    income.original_name = "Erste Bank DE000A0F5UH1.pdf"
    assert naming.proposal(income)["source"] == "fallback"  # No facts inferred from filenames.


@pytest.mark.parametrize("kind", ["bank_pdf", "bank_camt", "security_pdf"])
@pytest.mark.parametrize("short_name", [None, "", "   "])
def test_bank_name_uses_issuer_without_requiring_abbreviation(kind, short_name):
    account = Account(id=1, company_id=1, name="Settlement account", kind="bank")
    doc = synthetic(
        kind,
        account=account,
        issuer="Synthetic Financial Institution",
        bank_short_name=short_name,
        period_end="2026-04-29",
        date="2026-04-30",
        subtype="Ausschüttung",
        number="123",
    )
    before = dict(doc.metadata)
    result = naming.proposal(doc)
    assert result["source"] == "generated"
    assert result["warning"] == ""
    assert "Synthetic Financial Institution" in result["name"]
    assert doc.metadata == before  # Naming neither edits facts nor verifies bank parties.
    doc.metadata["evidence"] = {"issuer": {"uncertain": True}}
    assert naming.proposal(doc)["source"] == "fallback"
    doc.metadata["issuer"] = None
    doc.original_name = "Synthetic Financial Institution.xml"
    assert naming.proposal(doc)["source"] == "fallback"


def test_explicit_bank_short_name_takes_precedence_without_uncertainty_bypass():
    doc = synthetic(
        "bank_camt",
        account=Account(id=1, company_id=1, name="Settlement account", kind="bank"),
        issuer="Synthetic Financial Institution",
        bank_short_name="Synthetic FI",
        period_end="2026-04-29",
    )
    assert "Synthetic FI Settlement account" in naming.proposal(doc)["name"]
    doc.metadata["evidence"] = {"bank_short_name": {"uncertain": True}}
    assert naming.proposal(doc)["source"] == "fallback"
    # Even an uncertain, empty short name must not silently fall through to issuer.
    doc.metadata["bank_short_name"] = ""
    assert naming.proposal(doc)["source"] == "fallback"


def test_roles_receipts_credits_and_confirmed_partner():
    m = dict(
        date="2026-09-25",
        issuer="GitHub, Inc.",
        recipient="Eigene Firma",
        number="ch_3UJdTDJFr6CCHwIi1PFcNOkQ",
    )
    doc = synthetic("receipt", subtype="Zahlungsbeleg", **m)
    assert (
        naming.proposal(doc)["name"]
        == "2026-09-25 GitHub, Inc. Zahlungsbeleg ch_3UJdTDJFr6CCHwIi1PFcNOkQ.pdf"
    )
    for kind, partner, label in [
        ("outgoing_invoice", "Eigene Firma", "Rechnung"),
        ("outgoing_cancellation", "Eigene Firma", "Storno"),
        ("incoming_credit", "GitHub, Inc.", "Gutschrift"),
    ]:
        doc = synthetic(kind, **m)
        assert f"{partner} {label}" in naming.proposal(doc)["name"]
    doc.metadata["confirmed_partner_name"] = "Bestätigter Geschäftspartner"
    assert "Bestätigter Geschäftspartner" in naming.proposal(doc)["name"]
    assert doc.metadata["issuer"] == "GitHub, Inc."


def test_missing_and_uncertain_fields_and_real_format():
    doc = synthetic(original="../../unbekannt.exe")
    p = naming.proposal(doc)
    assert p["source"] == "fallback" and p["warning"]
    assert p["name"] == f"unbekannt-{doc.id.hex[:12]}.pdf"
    assert "2026-10" not in p["name"]  # No invented day from period.
    doc.metadata.update(date="2026-10-31", issuer="HoT", number=None)
    assert naming.proposal(doc)["name"] == "2026-10-31 HoT Rechnung.pdf"
    doc.metadata["evidence"] = {"date": {"uncertain": True}}
    assert naming.proposal(doc)["source"] == "fallback"
    doc.metadata["evidence"] = {"gross": {"uncertain": True}}
    assert naming.proposal(doc)["source"] == "generated"  # Amounts never enter names.


@pytest.mark.parametrize("stem", ["CON", "con.txt", "PRN", "AUX", "NUL", "COM1", "LPT9", "COM¹"])
def test_reserved_names(stem):
    assert naming.filename(stem, ".pdf").startswith("_")


def test_normalization_limits_and_paths():
    value = naming.filename("  Münnich & Co. / Beleg 12/34:..\\A\x00\r\n?*<>|   . ", ".pdf")
    assert "Münnich & Co." in value and "12-34" in value
    assert not any(c in value for c in '/\\:*?"<>|\r\n\x00') and ".." not in value
    long = naming.filename("資ä" * 300, ".pdf", "-12345678")
    assert len(long.encode()) <= naming.MAX_BYTES and long.endswith("-12345678.pdf")
    assert unicodedata.is_normalized("NFC", naming.filename("Mu\u0308nnich", ".pdf"))
    doc = synthetic()
    for invalid in ["../a.pdf", "/tmp/a.pdf", "C:\\temp\\a.pdf", "a.xml", "", "~a.pdf"]:
        with pytest.raises(DomainError):
            naming.validate_manual(doc, invalid)
    assert naming.validate_manual(doc, "CON.pdf") == "_CON.pdf"
    doc = synthetic(date="2026-10-31", issuer="Münnich", number="12/34")
    assert naming.proposal(doc)["name"].endswith("Rechnung 12-34.pdf")
    assert doc.metadata["number"] == "12/34"
    doc.original_name, doc.original_path, doc.media_type = "scan.jpeg", "_originals/test.jpg", "image/jpeg"
    assert naming.proposal(doc)["name"].endswith(".jpeg")
    doc.original_name = "scan.pdf"
    assert naming.proposal(doc)["name"].endswith(".jpg")  # Never trust a misleading extension.


def test_collision_resolution_is_stable_and_extends_prefixes():
    docs = [synthetic(), synthetic(), synthetic()]
    docs[0].id = uuid.UUID("12345678-1111-1111-1111-111111111111")
    docs[1].id = uuid.UUID("12345678-2222-2222-2222-222222222222")
    docs[2].id = uuid.UUID("aaaaaaaa-2222-2222-2222-222222222222")
    for d, name in zip(docs, ["Münnich.pdf", "MU\u0308NNICH.pdf", "Münnich-123456781111.pdf"], strict=True):
        d.handover_name, d.name_source = naming.validate_manual(d, name), "manual"
    result = naming.resolve(docs)
    assert result == naming.resolve(list(reversed(docs)))
    names = [v["name"] for v in result.values()]
    assert len({naming.collision_key(n) for n in names}) == 3
    assert all(len(n.encode()) <= naming.MAX_BYTES for n in names)
    assert result[str(docs[0].id)]["conflict"]
    assert not result[str(docs[0].id)]["name"].endswith("-12345678.pdf")
    # Truncation and separator replacement can also create collisions.
    for d, tail in zip(docs[:2], ["12/34", "12\\34"], strict=True):
        d.handover_name = naming.filename("資" * 100 + tail, ".pdf")
    shortened = naming.resolve(docs[:2])
    assert len({v["name"] for v in shortened.values()}) == 2
    assert all(v["conflict"] and len(v["name"].encode()) <= naming.MAX_BYTES for v in shortened.values())


def ready(actor, company, text="one", number="1008622969853"):
    result = services.ingest(actor, "Rechnung_1.pdf", sample_pdf([text]), company.id)["document"]
    return services.save_result(
        actor,
        {
            "document_id": result["id"],
            "base_version": result["version"],
            "company_id": company.id,
            "kind": "incoming_invoice",
            "period": "2026-10",
            "approve": True,
            "metadata": {
                "date": "2026-10-31",
                "issuer": "HoT Telekom und Service GmbH",
                "recipient": company.name,
                "number": number,
                "currency": "EUR",
                "net": "10",
                "tax": "2",
                "gross": "12",
            },
        },
    )


@pytest.mark.django_db
def test_rest_names_validate_paths_versions_and_explicit_reset(actor, companies, client):
    doc = ready(actor, companies[0])
    url = f"/api/documents/{doc['id']}/name/"
    assert (
        client.patch(url, {"base_version": doc["version"], "name": "C:escape.pdf"}, format="json").status_code
        == 400
    )
    assert (
        client.patch(url, {"base_version": doc["version"], "name": "x.xml"}, format="json").status_code == 400
    )
    response = client.patch(url, {"base_version": doc["version"], "name": "CON.pdf"}, format="json")
    assert response.status_code == 200
    manual = response.json()
    assert manual["effective_name"] == "_CON.pdf" and manual["name_source"] == "manual"
    assert manual["metadata"] == doc["metadata"] and manual["status"] == doc["status"]
    assert (
        client.patch(url, {"base_version": doc["version"], "name": "stale.pdf"}, format="json").status_code
        == 409
    )
    response = client.post(
        "/api/document-names/backfill/",
        {
            "entries": [
                {
                    "document_id": doc["id"],
                    "base_version": manual["version"],
                }
            ]
        },
        format="json",
    )
    assert response.status_code == 200 and response.json()[0]["version"] == manual["version"]
    response = client.patch(url, {"base_version": manual["version"], "name": None}, format="json")
    assert response.status_code == 200 and response.json()["effective_name"] == doc["effective_name"]
    for ids in [[], ["bad"], [doc["id"], doc["id"].upper()], [None]]:
        assert (
            client.post("/api/document-names/preview/", {"document_ids": ids}, format="json").status_code
            == 400
        )


@pytest.mark.django_db
def test_download_zip_csv_xlsx_manifest_and_immutable_snapshot(actor, companies, client):
    c = companies[0]
    d = ready(actor, c)
    expected = "2026-10-31 HoT Telekom und Service GmbH Rechnung 1008622969853.pdf"
    assert d["effective_name"] == expected and d["name_source"] == "generated"
    response = client.get(f"/api/documents/{d['id']}/download/")
    assert response["Content-Disposition"].startswith("attachment;")
    assert expected in unquote(response["Content-Disposition"])
    assert storage.checksum(response.content) == d["sha256"]
    package = packages.create_package(actor, c.id, ["2026-10"], "names-v1")
    stored = Package.objects.get(id=package["id"])
    before = packages.package_bytes(stored)
    archive_path = f"{c.folder}/2026/10/ER/{expected}"
    with zipfile.ZipFile(io.BytesIO(before)) as z:
        assert archive_path in z.namelist()
        assert z.read(archive_path) == response.content
        wb = load_workbook(io.BytesIO(z.read(f"{c.folder}/Monatsuebersicht_2026-10.xlsx")))
        cells = list(wb["Eingangsrechnungen"].iter_rows(min_row=5, values_only=True))
        relative = f"2026/10/ER/{expected}"
        assert cells[1][cells[0].index("Originalbeleg")] == relative
        assert unquote(wb["Eingangsrechnungen"].cell(6, 18).hyperlink.target) == relative
        inventory = list(wb["Inhaltsliste"].iter_rows(min_row=5, values_only=True))
        assert next(row for row in inventory[1:] if row[4] == relative)[5] == d["sha256"]
    changed = name_changes.set_name(actor, d["id"], d["version"], "Manuelle Übergabe.pdf")
    assert changed["status"] == "ready" and changed["issues"] == []
    for field in ["original_name", "sha256", "filed_path", "related_ids", "metadata"]:
        assert changed[field] == d[field]
    assert packages.package_bytes(stored) == before
    assert stored.snapshot["documents"][0]["effective_name"] == expected
    supplement = packages.package_preview(actor, c.id, ["2026-10"], package["id"])
    assert len(supplement["documents"]) == 1
    assert supplement["documents"][0]["archive_path"].endswith("/Manuelle Übergabe.pdf")
    with pytest.raises(DomainError) as error:
        name_changes.set_name(actor, d["id"], d["version"], "Concurrent.pdf")
    assert error.value.status == 409
    # Re-processing cannot overwrite the manual name.
    again = services.save_result(
        actor,
        {
            "document_id": d["id"],
            "base_version": changed["version"],
            "company_id": c.id,
            "kind": d["kind"],
            "period": "2026-10",
            "metadata": d["metadata"],
            "approve": True,
        },
        "agent:test",
    )
    assert again["effective_name"] == "Manuelle Übergabe.pdf" and again["name_source"] == "manual"
    reset = name_changes.set_name(actor, d["id"], again["version"], None)
    assert reset["effective_name"] == expected


@pytest.mark.django_db
@pytest.mark.parametrize("number", ["0039", "0041"])
def test_separate_collision_documents_stay_ready_and_reproducible(actor, companies, number):
    c = companies[0]
    first, second = ready(actor, c, "first", number), ready(actor, c, "second", number)
    preview = packages.package_preview(actor, c.id, ["2026-10"])
    assert preview == packages.package_preview(actor, c.id, ["2026-10"])
    assert preview["count"] == 2 and not preview["excluded"]
    paths = [d["archive_path"] for d in preview["documents"]]
    assert len(set(paths)) == 2 and all(f"Rechnung {number}-" in p for p in paths)
    for result in [first, second]:
        doc = services.get_document(actor, result["id"])
        assert doc.status == "ready" and doc.version == 2 and not doc.duplicate_of_id
        assert naming.data(doc)["effective_name"] in [p.rsplit("/", 1)[1] for p in paths]
    package = packages.create_package(actor, c.id, ["2026-10"], "collision")
    with zipfile.ZipFile(io.BytesIO(packages.package_bytes(Package.objects.get(id=package["id"])))) as z:
        assert all(path in z.namelist() for path in paths)


@pytest.mark.django_db
def test_explicit_preview_backfill_atomicity_and_permissions(actor, companies, client):
    first, second = ready(actor, companies[0], "legacy1"), ready(actor, companies[0], "legacy2", "other")
    # Simulate pre-migration rows; the schema migration itself never backfills names.
    Document.objects.filter(id__in=[first["id"], second["id"]]).update(handover_name="", name_source="")
    preview = name_changes.preview(actor, [first["id"], second["id"]])
    assert all(p["old_name"] != p["new_name"] for p in preview)
    assert not Document.objects.get(id=first["id"]).handover_name
    entries = [{"document_id": p["document_id"], "base_version": p["base_version"]} for p in preview]
    invalid = [entries[0], {**entries[1], "base_version": 1}]
    with pytest.raises(DomainError):
        name_changes.change(actor, invalid)
    assert not Document.objects.get(id=first["id"]).handover_name
    changed = name_changes.change(actor, entries)
    assert all(d["name_source"] == "generated" and d["status"] == "ready" for d in changed)
    assert Document.objects.get(id=first["id"]).revisions.last().source == "name:backfill"
    manual = name_changes.set_name(actor, changed[0]["id"], changed[0]["version"], "Geschützt.pdf")
    p = name_changes.preview(actor, [manual["id"]])[0]
    assert p["manual_protected"] and p["new_name"] == "Geschützt.pdf"
    assert (
        name_changes.change(actor, [{"document_id": manual["id"], "base_version": manual["version"]}])[0][
            "version"
        ]
        == manual["version"]
    )
    # Read permission suffices for preview, process permission is mandatory for writes.
    Membership.objects.filter(user_id=actor.user_id, company=companies[0]).update(can_process=False)
    assert (
        client.post(
            "/api/document-names/preview/", {"document_ids": [manual["id"]]}, format="json"
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/documents/{manual['id']}/name/",
            {"base_version": manual["version"], "name": "x.pdf"},
            format="json",
        ).status_code
        == 404
    )
    Membership.objects.filter(user_id=actor.user_id, company=companies[0]).delete()
    assert (
        client.post(
            "/api/document-names/preview/", {"document_ids": [manual["id"]]}, format="json"
        ).status_code
        == 404
    )
