"""Server contract for agent-verified bank interpretations, not an automatic reconciler."""

from decimal import Decimal

import pytest

from accounting import services, storage
from accounting.auth import DomainError
from accounting.demo import sample_camt, sample_pdf
from accounting.models import Account, Document

pytestmark = pytest.mark.django_db


@pytest.fixture
def bank_pair(actor, companies):
    def create(problem=None):
        controls = b"""
<Bal><Tp><CdOrPrtry><Cd>PRCD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-10-01</Dt></Dt></Bal>
<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1080.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-10-28</Dt></Dt></Bal>
<TxsSummry><TtlNtries><NbOfNtries>3</NbOfNtries><Sum>320.00</Sum></TtlNtries><TtlCdtNtries><NbOfNtries>2</NbOfNtries><Sum>200.00</Sum></TtlCdtNtries><TtlDbtNtries><NbOfNtries>1</NbOfNtries><Sum>120.00</Sum></TtlDbtNtries></TxsSummry>
"""
        credit = b'<Ntry><Amt Ccy="EUR">200.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-10-20</Dt></BookgDt></Ntry>'
        if problem == "amount":
            credit = credit.replace(b"200.00", b"201.00")
        elif problem == "missing_amount":
            credit = credit.replace(b'<Amt Ccy="EUR">200.00</Amt>', b"")
        original = (
            sample_camt().replace(b"</Acct>", b"</Acct>" + controls).replace(b"</Stmt>", credit + b"</Stmt>")
        )
        pdf_bytes = sample_pdf(
            ["SYNTH-2026-10", "Old EUR 1000.00; credits 200.00; debits 120.00; new 1080.00"]
        )
        xml = services.ingest(actor, "statement.xml", original, companies[0].id)["document"]
        pdf = services.ingest(actor, "statement.pdf", pdf_bytes, companies[0].id)["document"]
        statement = Document.objects.get(id=xml["id"]).parser_result["statements"][0]
        return {
            "xml": xml,
            "pdf": pdf,
            "original": original,
            "pdf_bytes": pdf_bytes,
            "statement": statement,
            "company_id": companies[0].id,
            "account_id": Account.objects.get(company=companies[0], kind="bank").id,
        }

    return create


def bank_result(pair, format):
    statement = pair["statement"]
    return {
        "document_id": pair[format]["id"],
        "base_version": pair[format]["version"],
        "company_id": pair["company_id"],
        "account_id": pair["account_id"],
        "kind": "bank_camt" if format == "xml" else "bank_pdf",
        "period": "2026-10",
        "metadata": {
            "currency": "EUR",
            "period_start": statement["start"].split("T")[0],
            "period_end": statement["end"].split("T")[0],
        },
        "related_ids": [pair["pdf" if format == "xml" else "xml"]["id"]],
        "approve": True,
    }


def test_verified_source_count_anomaly_and_linked_camt_period_are_not_blockers(actor, bank_pair):
    pair = bank_pair()
    entries = pair["statement"]["entries"]
    assert pair["original"].count(b"<Ntry>") == len(entries) == 2
    assert b"<NbOfNtries>3</NbOfNtries>" in pair["original"]
    credits = sum((Decimal(e["amount"]) for e in entries if e["direction"] == "CRDT"), Decimal(0))
    debits = sum((Decimal(e["amount"]) for e in entries if e["direction"] == "DBIT"), Decimal(0))
    assert credits == Decimal("200.00") and debits == Decimal("120.00")
    assert Decimal("1000.00") + credits - debits == Decimal("1080.00")

    xml_result = bank_result(pair, "xml")
    xml_result["metadata"].update(
        note="Quellenanomalie: Zähler 3, tatsächlich 2 Ntry, beide gelesen. Ursache nicht belegt. "
        "Haben 200.00 und Soll 120.00 entsprechen Kontrollsummen/PDF. 1000.00 + 200.00 - 120.00 = 1080.00.",
        evidence={
            "control_count": {
                "excerpt": "TxsSummry/TtlNtries/NbOfNtries=3; direkte Ntry=2",
                "reason": "Original und Parser vollständig verglichen; Summen/Salden und PDF stimmen.",
                "uncertain": False,
            }
        },
    )
    xml_saved = services.save_result(actor, xml_result)
    pdf_result = bank_result(pair, "pdf")
    pdf_result["metadata"]["evidence"] = {
        field: {
            "page": None,
            "excerpt": pair["statement"][key],
            "reason": f"Aus verknüpftem CAMT {pair['xml']['id']}, FrToDt/{path}; "
            "Konto, Auszugskennung, Buchungsbestand und Kontrollwerte stimmen überein. "
            "Kein eigener Zeitraumaufdruck im PDF, keine Ableitung aus Buchungsdaten.",
            "uncertain": False,
        }
        for field, key, path in [
            ("period_start", "start", "FrDtTm"),
            ("period_end", "end", "ToDtTm"),
        ]
    }
    pdf_saved = services.save_result(actor, pdf_result)
    for saved, related in [(xml_saved, pdf_saved), (pdf_saved, xml_saved)]:
        assert saved["status"] == "ready" and saved["issues"] == []
        assert saved["filing_status"] == "done"
        assert saved["related_ids"] == [related["id"]]
    assert xml_saved["metadata"]["note"] == xml_result["metadata"]["note"]
    assert pdf_saved["metadata"]["evidence"] == pdf_result["metadata"]["evidence"]
    assert storage.read_original(Document.objects.get(id=xml_saved["id"])) == pair["original"]
    assert storage.read_original(Document.objects.get(id=pdf_saved["id"])) == pair["pdf_bytes"]


@pytest.mark.parametrize("problem", ["amount", "missing_amount"])
def test_unresolved_bank_discrepancies_still_prevent_approval(actor, bank_pair, problem):
    pair = bank_pair(problem)
    entries = pair["statement"]["entries"]
    if problem == "amount":
        assert sum(
            Decimal(e["amount"]) if e["direction"] == "CRDT" else -Decimal(e["amount"]) for e in entries
        ) != Decimal("80.00")
        issue = "Betrags-/Saldoabweichung zwischen Originaleinträgen und Kontrollwerten/PDF"
    else:
        assert len(entries) < pair["original"].count(b"<Ntry>")
        issue = "Originaleintrag ohne Betrag nicht vollständig ausgelesen"
    payload = bank_result(pair, "xml")
    payload["metadata"]["open_points"] = [issue]
    with pytest.raises(DomainError, match="Prüfpunkte"):
        services.save_result(actor, payload)
    assert Document.objects.get(id=pair["xml"]["id"]).version == 1
    payload["approve"] = False
    saved = services.save_result(actor, payload)
    assert saved["status"] == "review" and issue in saved["issues"]
    assert storage.read_original(Document.objects.get(id=saved["id"])) == pair["original"]
