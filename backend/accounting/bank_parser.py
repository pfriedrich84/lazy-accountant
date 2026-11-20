"""Conservative reconciliation projection, separate from legacy CAMT parser output."""

from datetime import date
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree

from .camt import SUPPORTED_NAMESPACES

MISSING_IDENTITY = "Keine belastbare Bankkennung; Identität ungeklärt"


def reconciliation_entries(data):
    root = ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    namespace = root.tag.split("}")[0].lstrip("{")
    if namespace not in SUPPORTED_NAMESPACES:
        raise ValueError("Nicht unterstützter CAMT-Namespace")
    ns = {"c": namespace}

    def text(node, path):
        found = node.find("/".join("c:" + part for part in path.split("/")), ns)
        return (found.text or "").strip() if found is not None else ""

    def amount(node, path="Amt"):
        found = node.find("/".join("c:" + part for part in path.split("/")), ns)
        if found is None:
            return None, ""
        try:
            value = Decimal(found.text or "")
            if not value.is_finite() or value <= 0 or value >= Decimal("1e14"):
                raise ValueError("Ungültiger Buchungsbetrag")
            if value != value.quantize(Decimal("0.000001")):
                raise ValueError("Buchungsbetrag hat zu viele Nachkommastellen")
        except InvalidOperation as exc:
            raise ValueError("Ungültiger Buchungsbetrag") from exc
        return value, found.get("Ccy", "")

    def day(value):
        return date.fromisoformat(value[:10]).isoformat() if value else None

    for si, stmt in enumerate(
        root.findall(".//c:Stmt", ns) + root.findall(".//c:Rpt", ns) + root.findall(".//c:Ntfctn", ns)
    ):
        own_iban = text(stmt, "Acct/Id/IBAN").replace(" ", "").upper()
        for ei, entry in enumerate(stmt.findall("c:Ntry", ns)):
            total, currency = amount(entry)
            if total is None:
                raise ValueError("Buchung ohne Betrag")
            direction = text(entry, "CdtDbtInd")
            if direction not in {"CRDT", "DBIT"}:
                raise ValueError("Buchung ohne gültige Richtung")
            details = entry.findall("c:NtryDtls/c:TxDtls", ns)
            parts = [amount(d, "AmtDtls/TxAmt/Amt") for d in details]
            # Some banks put the transaction amount directly in TxDtls/Amt.
            parts = [amount(d) if part[0] is None else part for d, part in zip(details, parts)]
            split = len(details) > 1 and all(v is not None and c == currency for v, c in parts)
            split = split and sum((v for v, _ in parts), Decimal(0)) == total
            rows = (
                list(zip(details, parts))
                if split
                else [(details[0] if len(details) == 1 else None, (total, currency))]
            )
            for ti, (detail, (value, ccy)) in enumerate(rows):
                issues = []
                if len(details) > 1 and not split:
                    issues.append("Sammelbuchungsdetails nicht vollständig abstimmbar")
                if len(details) == 1 and parts[0][0] is not None and parts[0] != (total, currency):
                    issues.append("Detailbetrag weicht vom Buchungsbetrag ab")
                status = text(entry, "Sts/Cd") or text(entry, "Sts")
                reference = text(detail, "Refs/AcctSvcrRef") if detail is not None else ""
                # Aggregate references cannot identify multiple individual children.
                reference = reference or (text(entry, "AcctSvcrRef") if not split else "")
                if reference.upper() in {"", "NOTPROVIDED", "NONREF"}:
                    reference = ""
                    issues.append(MISSING_IDENTITY)
                party = "Dbtr" if direction == "CRDT" else "Cdtr"
                name = text(detail, f"RltdPties/{party}/Nm") if detail is not None else ""
                iban = text(detail, f"RltdPties/{party}Acct/Id/IBAN") if detail is not None else ""
                remittance = []
                if detail is not None:
                    remittance = [n.text or "" for n in detail.findall("c:RmtInf/c:Ustrd", ns)]
                    remittance += [
                        n.text or "" for n in detail.findall("c:RmtInf/c:Strd/c:CdtrRefInf/c:Ref", ns)
                    ]
                    detail_direction = text(detail, "CdtDbtInd")
                    if detail_direction and detail_direction != direction:
                        issues.append("Abweichende Detailrichtung")
                references = {}
                if detail is not None:
                    for key, path in {
                        "transaction_id": "Refs/TxId",
                        "end_to_end_id": "Refs/EndToEndId",
                        "instruction_id": "Refs/InstrId",
                    }.items():
                        identifier = text(detail, path)
                        if identifier and identifier.upper() not in {"NOTPROVIDED", "NONREF", "UNKNOWN"}:
                            if len(identifier) > 300:
                                raise ValueError("Überlange Bankreferenz")
                            references[key] = identifier
                # Preserve the structured business code, never a label inferred from amounts.
                code_node = detail if detail is not None else entry
                code = [
                    text(code_node, f"BkTxCd/Domn/{path}") for path in ("Cd", "Fmly/Cd", "Fmly/SubFmlyCd")
                ]
                if detail is not None and not any(code):
                    code = [
                        text(entry, f"BkTxCd/Domn/{path}") for path in ("Cd", "Fmly/Cd", "Fmly/SubFmlyCd")
                    ]
                if all(code):
                    references["bank_transaction_code"] = "/".join(code)
                return_info = detail is not None and detail.find("c:RtrInf", ns) is not None
                if len(reference) > 300 or len(iban) > 100:
                    raise ValueError("Überlange Bankkennung")
                yield {
                    "locator": f"statement:{si}/entry:{ei}/detail:{ti}",
                    "own_iban": own_iban,
                    "amount": str(value),
                    "currency": ccy,
                    "direction": direction,
                    "booking_date": day(text(entry, "BookgDt/Dt") or text(entry, "BookgDt/DtTm")),
                    "value_date": day(text(entry, "ValDt/Dt") or text(entry, "ValDt/DtTm")),
                    "bank_reference": reference,
                    "party_name": name[:300],
                    "party_iban": iban.replace(" ", "").upper(),
                    "remittance": "\n".join(remittance),
                    "booked": status == "BOOK",
                    "reversal": text(entry, "RvslInd").lower() == "true" or return_info,
                    "references": references,
                    "issues": issues,
                }
