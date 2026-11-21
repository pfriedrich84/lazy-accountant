"""Human-readable, formula-free package export, built exclusively from a frozen snapshot."""

import io
import posixpath
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

from .auth import DomainError

KINDS = {
    "incoming_invoice": "Eingangsrechnung",
    "incoming_credit": "Gutschrift Lieferant",
    "receipt": "Beleg",
    "outgoing_invoice": "Ausgangsrechnung",
    "outgoing_cancellation": "Storno Ausgangsrechnung",
    "bank_pdf": "Kontoauszug PDF",
    "bank_camt": "Kontoauszug CAMT",
    "security_pdf": "Wertpapierbeleg",
}
STATUS = {
    "paid": "Vollständig zugeordnet",
    "partially_paid": "Teilweise zugeordnet",
    "unpaid": "Keine Zuordnung vorhanden",
    "unresolved": "Zahlungsstand nicht beurteilbar",
}
ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def number(value):
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def day(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError, TypeError:
        return None


def table(wb, title, headers, rows):
    ws = wb.create_sheet(title)
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = "167D8D"
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws.cell(1, 1, title).font = Font(name="Calibri", size=20, bold=True, color="173B50")
    ws.row_dimensions[1].height = 34
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
    cell = ws.cell(2, 1, wb.properties.description or "Eingefrorener Paketdatenstand")
    cell.data_type = "s"
    cell.font = Font(name="Calibri", size=11, color="526570")
    ws.row_dimensions[2].height = 24
    for col, header in enumerate(headers, 1):
        cell = ws.cell(5, col, header)
        cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
        cell.fill = PatternFill("solid", fgColor="173B50")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[5].height = 38
    for row in rows:
        if ws.max_row >= 1048576:
            raise DomainError("Zu viele Zeilen für Excel; weniger Monate auswählen.")
        ws.append([ILLEGAL.sub("", value)[:32767] if isinstance(value, str) else value for value in row])
    ws.freeze_panes = "D6" if len(headers) > 5 else "A6"
    ws.auto_filter.ref = f"A5:{ws.cell(ws.max_row, len(headers)).coordinate}"
    # Untrusted text is always literal, including formula-looking references.
    for row in ws.iter_rows(min_row=6):
        ws.row_dimensions[row[0].row].height = 44
        for cell in row:
            if isinstance(cell.value, str):
                cell.value = ILLEGAL.sub("", cell.value)[:32767]
                cell.data_type = "s"
            elif isinstance(cell.value, date):
                cell.number_format = "dd.mm.yyyy"
            elif isinstance(cell.value, Decimal):
                cell.number_format = "#,##0.00####;[Red]-#,##0.00####"
            cell.font = Font(name="Calibri", size=11, color="233746")
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col, header in enumerate(headers, 1):
        values = [str(ws.cell(i, col).value or "") for i in range(5, ws.max_row + 1)]
        width = min(max(max(map(len, values), default=12) + 2, 14), 55)
        if header in {"Hinweise", "Begründung", "FX-Originaltext", "Verwendungszweck"}:
            width = 90
        if title == "Übersicht" and col == 2:
            width = 115
        ws.column_dimensions[ws.cell(5, col).column_letter].width = width
    if ws.max_row > 5:
        item = Table(displayName=f"Tabelle{len(wb.worksheets)}", ref=ws.auto_filter.ref)
        item.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(item)
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3 if len(headers) > 10 else ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "1:5"
    ws.oddFooter.center.text = "Seite &P von &N"
    return ws


def workbook_name(snapshot):
    periods = snapshot["periods"]
    suffix = periods[0] if len(periods) == 1 else f"{periods[0]}_bis_{periods[-1]}"
    return f"{snapshot['company']['folder']}/Monatsuebersicht_{suffix}.xlsx"


def settlement_status(metadata):
    settlement = metadata.get("settlement") or {}
    if settlement.get("review_note"):
        return "Wiedervorlage – keine Zahlungsaufforderung"
    if (
        number(settlement.get("amount_due")) == 0
        and number(settlement.get("covered_by_third_party")) is not None
        and number(settlement.get("covered_by_third_party")) == number(metadata.get("gross"))
    ):
        return "Durch Dritte gedeckt – kein eigener Zahlbetrag"
    if number(metadata.get("gross")) == 0:
        return "Nullbetrag – kein Bankzahlungsnachweis erforderlich"
    return None


def supplementary_receipt(document):
    """Only explicitly classified payment confirmations are non-expense companions."""
    return document["kind"] == "receipt" and (
        document["metadata"].get("subtype") or ""
    ).strip().casefold() in {"supplementary_payment_receipt", "payment_receipt", "zahlungsbeleg"}


def build_workbook(snapshot, package_id, version):
    """No queries here: snapshots and payment-only supplements must stay reproducible."""
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.title = "Monatsübersicht"
    wb.properties.creator = "lazy-accountant"
    wb.properties.description = ILLEGAL.sub(
        "",
        f"{snapshot['company']['name']} · "
        f"{', '.join(snapshot['periods'])} · "
        f"Datenstand {snapshot.get('exported_at', 'eingefroren')}",
    )[:32767]
    docs = snapshot.get("workbook_documents", snapshot["documents"])
    documents = {d["id"]: d for d in docs}
    payments = {p["document_id"]: p for p in snapshot.get("payments", []) if p["document_id"] in documents}
    transactions = {t["id"]: t for t in snapshot.get("allocation_transactions", [])}
    contained = {d["id"]: d for d in snapshot["documents"]}
    folder = snapshot["company"]["folder"]

    def original(d):
        included = contained.get(d["id"])
        if included:
            return posixpath.relpath(included["archive_path"], folder)
        if d["id"] in snapshot.get("unchanged", []):
            return "Original im Vorgängerpaket (unverändert)"
        return "Original nicht enthalten"

    def links(ws, column, rows):
        for index, d in enumerate(rows, start=6):
            if d["id"] in contained:
                cell = ws.cell(index, column)
                cell.hyperlink = quote(original(d), safe="/")
                cell.style = "Hyperlink"

    overview = [
        ["Firma", snapshot["company"]["name"]],
        ["Monate", ", ".join(snapshot["periods"])],
        ["Paketversion", version],
        ["Paketkennung (technisch)", str(package_id)],
        ["Datenstand", snapshot.get("exported_at", "Im Paket eingefrorener Datenstand")],
        ["Nachtrag zu", snapshot.get("parent_id") or "Kein Vorgänger"],
        ["Empfänger", ", ".join(snapshot.get("recipients", []))],
        ["Enthaltene Originale", len(contained)],
        ["Unveränderte Originale im Vorgänger", len(snapshot.get("unchanged", []))],
        ["Einordnung", "Unterlagensammlung, keine bestätigte Buchhaltung und kein Buchungsjournalabgleich."],
        [
            "Zahlungsstatus",
            "Keine Zuordnung bedeutet nicht nachgewiesenes Nichtbezahltsein. "
            "Restbeträge beziehen sich ausschließlich auf dokumentierte Bankzuordnungen.",
        ],
        [
            "Währungen",
            "Beträge verschiedener Währungen nicht addieren; Gebühren sind keine Rechnungszahlung.",
        ],
        [
            "Zeitraum",
            "Klärfälle betreffen nur die ausgewählten Übergabemonate. "
            "Historische Bankbewegungen können als Nachweis einer aktuellen Rechnung dienen.",
        ],
        [
            "Bankdaten",
            "Das Blatt zeigt normalisierte Bankbewegungen nach Buchungsmonat. "
            "Fehlende Bewegungen sind kein Beweis für einen vollständigen oder leeren Bankmonat.",
        ],
        [
            "Beleglinks",
            "Gesamtes ZIP entpacken. Links öffnen nur Originale dieses Pakets; "
            "unveränderte Originale eines Nachtrags liegen im Vorgängerpaket.",
        ],
        [
            "Integrität",
            "Inhaltsliste enthält SHA-256 der Originale. Die Arbeitsmappe kann keine "
            "eigene Prüfsumme enthalten; die ZIP-Prüfsumme steht am gespeicherten Paket.",
        ],
        ["Nicht zugeordneter Eingang", len(snapshot.get("unassigned_inbox", []))],
        ["Ergänzende Zahlungsbelege", sum(supplementary_receipt(d) for d in docs)],
        [
            "Keine Doppelerfassung",
            "Ergänzende Zahlungsbelege stehen nur in der Inhaltsliste, nicht als zweite Rechnung.",
        ],
        [
            "Hinweise",
            "Bei historischen Prüfschritten in Belegnotizen ist der eingefrorene Zuordnungsstatus maßgeblich. "
            "Unbekannte Werte bleiben leer; Null und unbekannt werden nicht gleichgesetzt.",
        ],
    ]
    totals = {}
    for tx in snapshot.get("bank_transactions", []):
        account = f"{tx.get('account_name', '')} [{tx.get('account_identifier') or tx.get('account_id', '')}]"
        key = (tx.get("account_id"), tx.get("currency", ""))
        counts = totals.setdefault(
            key, {"CRDT": Decimal(0), "DBIT": Decimal(0), "count": 0, "label": account}
        )
        counts[tx["direction"]] += number(tx["amount"]) or Decimal(0)
        counts["count"] += 1
    for (_, currency), total in totals.items():
        account = total["label"]
        overview.extend(
            [
                [f"Bankbewegungen {account} ({currency})", total["count"]],
                [f"Gutschriften {account} ({currency})", total["CRDT"]],
                [f"Belastungen {account} ({currency})", total["DBIT"]],
            ]
        )
    for entry in snapshot.get("intentional_exclusions", []):
        d = entry["document"]
        overview.append(
            [
                "Bewusst ausgeschlossener Nichtbeleg",
                f"{d['original_name']} ({d.get('period') or 'ohne Monatszuordnung'}): {entry['reason']}",
            ]
        )
    for note in snapshot.get("bank_export_notes", []):
        overview.append(["Bankexport-Hinweis", note])
    for entry in snapshot.get("exclusion_changes", []):
        overview.append(
            [
                "Ausschluss-/Wiederherstellungsänderung",
                f"{entry['original_name']}: {entry['action']}; {entry['reason']}",
            ]
        )
    table(wb, "Übersicht", ["Thema", "Information"], overview)

    invoice_headers = [
        "Monat",
        "Belegart",
        "Geschäftspartner",
        "Rechnungsnummer",
        "Rechnungsdatum",
        "Leistungsdatum",
        "Leistungsbeginn",
        "Leistungsende",
        "Fällig am",
        "Währung",
        "Netto",
        "Steuer",
        "Brutto",
        "Zugeordnet (Rechnungswährung)",
        "Rechnungsbetrag ohne Bankzuordnung",
        "Zuordnungsstatus",
        "Bankdeckung",
        "Originalbeleg",
        "Hinweise",
        "Zahlbetrag laut Original",
        "Kostenübernahme Dritte",
        "Kategorie",
    ]
    for title, kinds, partner in [
        ("Eingangsrechnungen", {"incoming_invoice", "incoming_credit", "receipt"}, "issuer"),
        ("Ausgangsrechnungen", {"outgoing_invoice", "outgoing_cancellation"}, "recipient"),
    ]:
        selected = sorted(
            [d for d in docs if d["kind"] in kinds and not supplementary_receipt(d)],
            key=lambda d: (d["metadata"].get("date") or "", d["metadata"].get("number") or ""),
        )
        rows = []
        for d in selected:
            m, p = d["metadata"], payments.get(d["id"], {})
            status = STATUS.get(p.get("status"), "Keine eigenständige Rechnung / kein Zahlungsstatus")
            status = settlement_status(m) or status
            settlement = m.get("settlement") or {}
            rows.append(
                [
                    d["period"],
                    KINDS.get(d["kind"], d["kind"]),
                    m.get(partner),
                    m.get("number"),
                    day(m.get("date")),
                    day(m.get("service_date")),
                    day(m.get("period_start")),
                    day(m.get("period_end")),
                    day(m.get("due_date")),
                    m.get("currency"),
                    number(m.get("net")),
                    number(m.get("tax")),
                    number(m.get("gross")),
                    number(p.get("paid")),
                    number(p.get("remaining")),
                    status,
                    {
                        "complete": "Vollständig",
                        "partial": "Teilweise",
                        "none": "Keine",
                        "disputed": "Strittig",
                        "unknown": "Ungeklärt",
                    }.get(p.get("bank_evidence"), "Nicht beurteilt"),
                    original(d),
                    m.get("note", ""),
                    number(settlement.get("amount_due")),
                    number(settlement.get("covered_by_third_party")),
                    d.get("category_name"),
                ]
            )
        ws = table(wb, title, invoice_headers, rows)
        links(ws, 18, selected)
        for index, d in enumerate(selected, 6):
            if (d["metadata"].get("settlement") or {}).get("review_note"):
                for cell in ws[index]:
                    cell.fill = PatternFill("solid", fgColor="FFF2CC")

    allocation_rows = []
    for p in payments.values():
        d = documents.get(p["document_id"], {})
        m = d.get("metadata", {})
        for allocation in p.get("allocations", []):
            tx = transactions.get(allocation["transaction_id"], {})
            fx = (allocation.get("evidence") or {}).get("fx") or {}
            evidence = fx.get("evidence") or {}
            principal = fx.get("bank_principal")
            if principal is None and allocation.get("invoice_currency") == allocation.get("bank_currency"):
                principal = allocation.get("bank_amount")
            allocation_rows.append(
                [
                    p["period"],
                    m.get("number"),
                    m.get("issuer") if d.get("kind") == "incoming_invoice" else m.get("recipient"),
                    day(tx.get("booking_date")),
                    day(tx.get("value_date")),
                    allocation.get("invoice_currency"),
                    number(allocation.get("amount")),
                    allocation.get("bank_currency"),
                    number(principal),
                    number(fx.get("fee")),
                    number(allocation.get("bank_amount")),
                    number(evidence.get("rate")),
                    evidence.get("rate_direction", ""),
                    "Aufgehoben" if allocation.get("reversed_at") else "Bestätigt",
                    allocation.get("reason", ""),
                    allocation.get("reversal_reason", ""),
                    tx.get("bank_reference", ""),
                    evidence.get("quote", ""),
                    allocation.get("transaction_id"),
                    allocation.get("id"),
                ]
            )
    table(
        wb,
        "Zahlungszuordnungen",
        [
            "Rechnungsmonat",
            "Rechnungsnummer",
            "Geschäftspartner",
            "Buchungsdatum",
            "Valutadatum",
            "Rechnungswährung",
            "Rechnungsbetrag zugeordnet",
            "Bankwährung",
            "Bankgegenwert ohne Gebühr",
            "Separate FX-Gebühr",
            "Bankbetrag einschließlich Gebühr",
            "Belegter Kurs",
            "Kursrichtung",
            "Zuordnung",
            "Begründung",
            "Aufhebungsgrund",
            "Bankreferenz",
            "FX-Originaltext",
            "Bankkennung (technisch)",
            "Zuordnungskennung (technisch)",
        ],
        allocation_rows,
    )

    bank_rows = []
    for t in snapshot.get("bank_transactions", []):
        reversed_tx = t.get("reversal") or t.get("reversed_by_id")
        bank_rows.append(
            [
                (t.get("booking_date") or "")[:7],
                t.get("account_name"),
                t.get("account_identifier"),
                day(t.get("booking_date")),
                day(t.get("value_date")),
                "Eingang" if t["direction"] == "CRDT" else "Ausgang",
                t.get("currency"),
                number(t["amount"]),
                t.get("party_name"),
                t.get("party_iban"),
                t.get("remittance"),
                t.get("bank_reference"),
                "Gebucht" if t.get("booked") else "Buchungsstatus offen",
                "Rückbuchung / rückgebuchte Bewegung" if reversed_tx else "Reguläre Bewegung",
                ", ".join(t.get("invoice_references", [])),
                number(t.get("available")),
                "; ".join(t.get("issues", [])),
                t["id"],
            ]
        )
    table(
        wb,
        "Bankbewegungen",
        [
            "Monat",
            "Konto",
            "Kontokennung",
            "Buchungsdatum",
            "Valutadatum",
            "Richtung",
            "Währung",
            "Betrag",
            "Gegenpartei",
            "Gegenkonto",
            "Verwendungszweck",
            "Bankreferenz",
            "Buchungsstatus",
            "Bewegungsart",
            "Zugeordnete Rechnungen",
            "Für Zuordnung verfügbar",
            "Quellenhinweise",
            "Bankkennung (technisch)",
        ],
        bank_rows,
    )

    securities = [d for d in docs if d["kind"] == "security_pdf"]
    ws = table(
        wb,
        "Wertpapiere",
        [
            "Monat",
            "Datum",
            "Valutadatum",
            "Depot",
            "Depotkennung",
            "Belegart",
            "ISIN",
            "Originalwährung",
            "Brutto Originalwährung",
            "Quellensteuer Originalwährung",
            "Netto Originalwährung",
            "Originalbeleg",
            "Hinweise",
            "Stück",
            "Bankwährung",
            "Netto Bankwährung vor Spesen",
            "Separate Spesen Bankwährung",
            "Kontogutschrift Bankwährung",
            "Kurs Originalwährung je Bankwährung",
        ],
        [
            [
                d["period"],
                day(d["metadata"].get("date")),
                day(d["metadata"].get("valuation_date")),
                d.get("account_name"),
                d.get("account_identifier"),
                d["metadata"].get("subtype"),
                d["metadata"].get("isin"),
                (d["metadata"].get("security_income") or {}).get("original_currency"),
                number((d["metadata"].get("security_income") or {}).get("gross")),
                number((d["metadata"].get("security_income") or {}).get("withholding_tax")),
                number((d["metadata"].get("security_income") or {}).get("net")),
                original(d),
                d["metadata"].get("note", ""),
                number((d["metadata"].get("security_income") or {}).get("quantity")),
                (d["metadata"].get("security_income") or {}).get("bank_currency"),
                number((d["metadata"].get("security_income") or {}).get("bank_net")),
                number((d["metadata"].get("security_income") or {}).get("bank_fee")),
                number((d["metadata"].get("security_income") or {}).get("bank_credit")),
                number((d["metadata"].get("security_income") or {}).get("rate_original_per_bank")),
            ]
            for d in securities
        ],
    )
    links(ws, 12, securities)

    cases = []
    for entry in snapshot.get("excluded", []):
        d = entry["document"]
        if d.get("period") in snapshot["periods"] or not d.get("period"):
            cases.append(
                [
                    d.get("period") or "Ungeklärt",
                    d.get("original_name"),
                    entry["reason"],
                    "Dokumentprüfung / Zuordnung klären",
                    "Bearbeitung",
                    "Nicht im Paket enthalten",
                ]
            )
    # Explicit follow-ups also apply to credits, cancellations and standalone receipts,
    # which intentionally have no invoice-payment status.
    for d in docs:
        m = d["metadata"]
        settlement = m.get("settlement") or {}
        if settlement.get("review_note"):
            cases.append(
                [
                    d["period"],
                    m.get("number"),
                    "Wiedervorlage – keine Zahlungsaufforderung",
                    settlement.get("next_step") or "Weitere Abrechnung / Nachweis abwarten",
                    settlement.get("follow_up") or "Bearbeitung bei neuen Unterlagen",
                    settlement["review_note"],
                ]
            )
    for p in payments.values():
        d = documents[p["document_id"]]
        m = d["metadata"]
        if p.get("bank_evidence") == "disputed":
            cases.append(
                [
                    p["period"],
                    m.get("number"),
                    "Bankdeckung strittig – Zuordnungsbetrag unverändert",
                    "Bankidentität / Zahlungsnachweis prüfen; keine erneute Zahlung ableiten.",
                    "Bearbeitung",
                    "; ".join(p.get("assessment_notes") or []) or "Bankdeckung ist strittig.",
                ]
            )
        elif p.get("status") != "paid" and not settlement_status(m):
            cases.append(
                [
                    p["period"],
                    m.get("number"),
                    STATUS.get(p.get("status"), "Ungeklärt"),
                    "Zahlungsnachweis prüfen; fehlende Zuordnung beweist keine Nichtzahlung.",
                    "Bearbeitung",
                    m.get("note", ""),
                ]
            )
    for item in snapshot.get("blocked_imports", []):
        cases.append(
            [
                "Import",
                item.get("original_name", "Importfall"),
                item.get("error") or item.get("security_error") or "Import technisch prüfen",
                "Importursache prüfen; keine Sicherheitsfreigabe ableiten",
                "Technik",
                "",
            ]
        )
    table(
        wb, "Klärfälle", ["Monat", "Bezug", "Sachstand", "Nächster Schritt", "Zuständig", "Hinweise"], cases
    )

    inventory = sorted(snapshot["documents"], key=lambda d: d["archive_path"])
    ws = table(
        wb,
        "Inhaltsliste",
        [
            "Monat",
            "Belegart",
            "Geschäftspartner",
            "Belegnummer",
            "Datei",
            "SHA-256",
            "Bytes",
            "Revision",
            "Dokumentkennung (technisch)",
            "Kategorie",
            "Konto / Depot",
            "Kennung Konto / Depot",
            "Währung",
            "Datum",
            "Leistungs-/Auszugsbeginn",
            "Leistungs-/Auszugsende",
            "Monatszuordnung / Begründung",
        ],
        [
            [
                d["period"],
                KINDS.get(d["kind"], d["kind"]),
                d["metadata"].get("issuer"),
                d["metadata"].get("number"),
                original(d),
                d["sha256"],
                d["size"],
                d["version"],
                d["id"],
                d.get("category_name"),
                d.get("account_name"),
                d.get("account_identifier"),
                d["metadata"].get("currency"),
                day(d["metadata"].get("date")),
                day(d["metadata"].get("period_start")),
                day(d["metadata"].get("period_end")),
                d["metadata"].get("period_assignment_reason"),
            ]
            for d in inventory
        ],
    )
    links(ws, 5, inventory)
    stream = io.BytesIO()
    wb.save(stream)
    return stream.getvalue()
