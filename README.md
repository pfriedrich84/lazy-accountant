# lazy-accountant

Schlanke, selbst betriebene Dokumentensammlung und Übergabe an die Steuerberatung.

## Plan

Der [Funktionskatalog und Umsetzungsplan](docs/PLAN.md) beschreibt den vereinbarten Umfang. Aktuell enthält dieses Repository die Planung; die Anwendung und die Skills sind noch zu implementieren.

Die erste Version umfasst:

- Mehrere getrennte Firmen.
- Upload bestehender Ausgangsrechnungen als PDF, zunächst beispielsweise aus Invoice Ninja.
- Eingangsrechnungen, CAMT- und PDF-Kontoauszüge sowie Wertpapierbewegungen als PDF.
- Dokumenteingang über IMAP und Paketversand über SMTP.
- Einen eigenen MCP-Server, über den der vorhandene externe Agent Dokumente liest, Rechnungsdaten ermittelt und Unterlagen sortiert.
- Versionierte Skills für Dokumentverarbeitung, Konto-/Depotzuordnung und Monatsübergabe.
- Übergabepakete mit Originaldateien, CSV-/XLSX-Übersichten, Inhaltsliste und nachvollziehbaren Nachträgen.
- Deployment mit Docker Compose; zunächst keine eigene serverseitige KI-Anbindung.

Eigene einmalige und wiederkehrende Rechnungen sowie Bankabgleich folgen im nächsten Ausbau. Projekte, Zeiterfassung und monatliche Leistungsabrechnung kommen danach.
