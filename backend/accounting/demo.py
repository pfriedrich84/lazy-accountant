"""Synthetic, non-sensitive documents for tests and the reproducible sample month."""

import io

from PIL import Image, ImageDraw

from .auth import Actor
from .models import Account, Category, Company, Membership
from .services import create_company, ingest, save_result


def sample_pdf(lines):
    """A small real PDF with a text layer; no invoice-generation feature in the application."""
    escaped = [str(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for s in lines]
    content = ("BT /F1 14 Tf 45 790 Td " + " ".join(f"({s}) Tj 0 -24 Td" for s in escaped) + " ET").encode(
        "latin1", errors="replace"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{n:010d} 00000 n \n".encode() for n in offsets[1:])
    return data + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


def sample_image():
    im = Image.new("RGB", (850, 450), "white")
    draw = ImageDraw.Draw(im)
    for i, line in enumerate(
        [
            "SYNTHETISCHER SCANBELEG",
            "Beispiel Lieferant",
            "Beispiel GmbH",
            "Rechnung SCAN-2026-10",
            "Datum 2026-10-15",
            "Netto EUR 100.00",
            "Steuer EUR 20.00",
            "Brutto EUR 120.00",
        ]
    ):
        draw.text((35, 30 + i * 40), line, fill="black", font_size=23)
    output = io.BytesIO()
    im.save(output, "PNG")
    return output.getvalue()


def sample_camt(period="2026-10"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>
<Id>SYNTH-{period}</Id><FrToDt><FrDtTm>{period}-01T00:00:00Z</FrDtTm><ToDtTm>{period}-28T23:59:59Z</ToDtTm></FrToDt>
<Acct><Id><IBAN>AT611904300234573201</IBAN></Id><Ccy>EUR</Ccy></Acct>
<Ntry><Amt Ccy="EUR">120.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>{period}-15</Dt></BookgDt><AcctSvcrRef>SYNTH-1</AcctSvcrRef><AddtlNtryInf>Testrechnung</AddtlNtryInf></Ntry>
</Stmt></BkToCstmrStmt></Document>""".encode()


def seed_companies(user):
    actor = Actor(user.id)
    result = []
    for name, folder in [("Beispiel GmbH", "Beispiel-GmbH"), ("Zweite Firma", "Zweite-Firma")]:
        company = Company.objects.filter(folder=folder).first()
        if not company:
            data = create_company(
                actor, {"name": name, "folder": folder, "recipients": ["kanzlei@example.test"]}
            )
            company = Company.objects.get(id=data["id"])
        Membership.objects.update_or_create(
            user=user,
            company=company,
            defaults={"can_read": True, "can_process": True, "can_send": True, "can_admin": True},
        )
        Account.objects.get_or_create(
            company=company,
            kind="bank",
            name="Geschäftskonto",
            defaults={"identifier": "AT611904300234573201"},
        )
        Account.objects.get_or_create(
            company=company, kind="depot", name="Geschäftsdepot", defaults={"identifier": "DEPOT-DEMO"}
        )
        for category in ["Büro", "Dienstleistung", "Bank", "Wertpapiere"]:
            Category.objects.get_or_create(company=company, name=category)
        result.append(company)
    return result


def seed_month(user, company, period="2026-10", classified=False, output=None):
    actor = Actor(user.id)
    fixtures = [
        ("ausgang.pdf", "outgoing_invoice"),
        ("eingang.pdf", "incoming_invoice"),
        ("gutschrift.pdf", "incoming_credit"),
        ("storno.pdf", "outgoing_cancellation"),
        ("konto.pdf", "bank_pdf"),
        ("konto.xml", "bank_camt"),
        ("wertpapiere.pdf", "security_pdf"),
        ("scan.png", "receipt"),
    ]
    ids = []
    for index, (name, kind) in enumerate(fixtures):
        invoice = kind in {"outgoing_invoice", "incoming_invoice", "incoming_credit", "outgoing_cancellation"}
        metadata = (
            {
                "issuer": company.name if kind.startswith("outgoing") else "Beispiel Lieferant",
                "recipient": "Beispiel Kunde" if kind.startswith("outgoing") else company.name,
                "number": f"SYNTH-{period}-{index}",
                "date": f"{period}-15",
                "currency": "EUR",
                "net": "100.00",
                "tax": "20.00",
                "gross": "120.00",
            }
            if invoice
            else {}
        )
        if kind in {"bank_pdf", "bank_camt", "security_pdf"}:
            metadata = {"period_start": f"{period}-01", "period_end": f"{period}-28", "currency": "EUR"}
        data = (
            sample_camt(period)
            if kind == "bank_camt"
            else sample_image()
            if name.endswith("png")
            else sample_pdf(
                [
                    "SYNTHETISCH – keine echte Rechnung",
                    company.name,
                    kind,
                    *[f"{k}: {v}" for k, v in metadata.items()],
                ]
            )
        )
        result = ingest(actor, name, data, company.id, f"demo:{company.id}:{period}:{name}")
        doc = result["document"]
        if classified and doc["version"] == 1:
            account_id = None
            if kind in {"bank_pdf", "bank_camt", "security_pdf"}:
                account_id = Account.objects.get(
                    company=company, kind="depot" if kind == "security_pdf" else "bank"
                ).id
            doc = save_result(
                actor,
                {
                    "document_id": doc["id"],
                    "base_version": 1,
                    "company_id": company.id,
                    "kind": kind,
                    "period": period,
                    "account_id": account_id,
                    "metadata": metadata,
                    "approve": True,
                },
            )
        if output:
            from pathlib import Path

            Path(output).mkdir(parents=True, exist_ok=True)
            Path(output, name).write_bytes(data)
        ids.append(doc["id"])
    return ids
