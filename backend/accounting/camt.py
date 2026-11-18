"""Bounded, entity-safe CAMT.052/.053/.054 parser; no LLM arithmetic."""

import re
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree

SUPPORTED_NAMESPACES = {
    f"urn:iso:std:iso:20022:tech:xsd:camt.{kind}.001.{version:02d}"
    for kind in ("052", "053", "054")
    for version in (2, 8, 10, 11, 12, 13)
}


def parse_camt(data):
    root = ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    match = re.match(r"\{([^}]+)\}", root.tag)
    namespace = match.group(1) if match else ""
    if namespace not in SUPPORTED_NAMESPACES:
        raise ValueError(f"Nicht unterstützter CAMT-Namespace: {namespace or '(fehlt)'}")
    prefix = "{" + namespace + "}"

    def text(element, parts):
        found = element.find("/".join(prefix + p for p in parts.split("/")))
        return found.text if found is not None else None

    statements = []
    for name in ("Stmt", "Rpt", "Ntfctn"):
        for element in root.iter(prefix + name):
            entries = []
            for e in element.findall(prefix + "Ntry"):
                amount = e.find(prefix + "Amt")
                if amount is None or not amount.text:
                    continue
                try:
                    number = Decimal(amount.text)
                    if not number.is_finite():
                        raise ValueError("Ungültiger CAMT-Betrag")
                except InvalidOperation as exc:
                    raise ValueError("Ungültiger CAMT-Betrag") from exc
                entries.append(
                    {
                        "amount": str(number),
                        "currency": amount.attrib.get("Ccy"),
                        "direction": text(e, "CdtDbtInd"),
                        "booking_date": text(e, "BookgDt/Dt") or text(e, "BookgDt/DtTm"),
                        "reference": text(e, "AcctSvcrRef"),
                        "description": text(e, "AddtlNtryInf"),
                    }
                )
            statements.append(
                {
                    "id": text(element, "Id"),
                    "iban": text(element, "Acct/Id/IBAN"),
                    "account_id": text(element, "Acct/Id/Othr/Id"),
                    "currency": text(element, "Acct/Ccy"),
                    "start": text(element, "FrToDt/FrDtTm"),
                    "end": text(element, "FrToDt/ToDtTm"),
                    "entries": entries,
                }
            )
    if not statements:
        raise ValueError("CAMT enthält keinen unterstützten Auszug/Bericht.")
    return {"namespace": namespace, "statements": statements}
