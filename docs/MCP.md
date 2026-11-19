# MCP-Vertrag und Orca-Anbindung

## IMAP-Abruf und Automatik

Die Postfach-Checkbox `enabled` steuert **nur die automatische nächtliche Abholung**. Ohne Haken startet kein Nachtabruf; wartende automatische Aufträge werden beim Ausführen übersprungen. Ein ausdrücklicher `start_imap_import`-Aufruf mit `process`-Berechtigung ist auch bei ausgeschalteter Automatik erlaubt, ebenso der UI-Knopf „IMAP jetzt abrufen“. Manuelle Abrufe und das Fortsetzen manueller Aufträge setzen den Haken nicht. IMAP-Zugang und Importbeginn müssen weiterhin korrekt eingerichtet sein.

## Transport und Authentifizierung

Offizielles `modelcontextprotocol/python-sdk` **2.3.0**, `MCPServer`, Streamable HTTP, ASGI-Mount **`/mcp/`**. Der übergeordnete ASGI-Lifecycle startet/beendet `server.session_manager.run()`. Stateless HTTP mit JSON-Antworten; kein zweiter Datenbestand und keine eigenen JSON-RPC-Implementierungen.

Weboberfläche, API und MCP liegen auf derselben internen HTTP-Origin. Der abschließende Slash vermeidet einen Redirect. SDK-Clients unterstützen den Same-Origin-Redirect von `/mcp` ebenfalls. Interne Hosts/Origins stehen ausdrücklich in `ALLOWED_HOSTS`, `MCP_ALLOWED_HOSTS` und `MCP_ALLOWED_ORIGINS`. DNS-Rebinding-Schutz bleibt aktiviert. Keine pauschale `*`-Freigabe für alle Hosts verwenden.

- UI: Django-Session, SameSite Strict, CSRF-Schutz einschließlich Login.
- MCP/Dateitransfer: `Authorization: Bearer <Token>`.
- Token wird einmal angezeigt, serverseitig nur SHA256/Präfix gespeichert; Widerruf in Einstellungen. Zugriff erfordert zusätzlich aktive Django-Benutzer-/Firmenmitgliedschaft.
- Effektive Rechte sind die **Schnittmenge** von Firmenmitgliedschaft, Token-Firmen und Token-Scopes: `read`, `process`, `send`, `admin`; `inbox` erlaubt zusätzlich den eigenen, noch firmenlosen Eingang.
- Downloads und Paketstände verwenden dieselben Rechte. Ein Datei-Hash bewirkt keine firmenübergreifende Zuordnung.
- HTTP ist ausschließlich die vereinbarte interne Transportkonfiguration. Bearer/Passwörter wären in einem ungeschützten fremden Netz lesbar; für öffentlichen Betrieb TLS und eine gesonderte Sicherheitsabnahme ergänzen.

Der ASGI-Zugang authentifiziert jeden HTTP-Aufruf. Tools prüfen Token, Mitgliedschaft und Funktionsrechte erneut über denselben Service-Layer wie REST. Django-Datenbankverbindungen werden auch außerhalb des Request-Handlers am Ende der MCP-Aufrufe geschlossen.

## Bankabgleich (CAMT-Ausbau zu #10)

Die zusätzlichen Werkzeuge für CAMT-Normalisierung, erklärbare Kandidaten, Bank-/Rechnungslisten, Zuordnung, Aufhebung und explizite Bankdatenfreigabe sind mit Schemas, Rechten und Grenzen im [Bankabgleich-Vertrag](BANK_RECONCILIATION.md#rest-und-mcp) dokumentiert. Schreibaufträge verwenden `request` als Schemaobjekt, Beträge als Dezimalstrings und für finanzwirksame Änderungen Versionsprüfung/Idempotenz. Keine Überweisung oder Mahnung auslösen. `reconcile_bank_document` darf auf autorisierten Auftrag eindeutige Treffer bestätigen; mehrdeutige oder ungeklärte Quellen bleiben offen. Eindeutig referenzierte gebuchte Vollrückbuchungen berichtigen bestehende Deckung auch bei `auto_confirm=false`; dieses Flag betrifft nur neue automatische Rechnungszuordnungen. Teil-/unklare Rückbuchungen werden nicht geraten.

## Tatsächliche Werkzeuge

Die aktuellen JSON-Schemas werden durch die offiziellen SDK-Dekoratoren aus Typannotationen/Pydantic erstellt und über `tools/list` veröffentlicht, nicht nur in Markdown beschrieben.

| Tool | Aufgabe |
| --- | --- |
| `list_companies` | Berechtigte Firmen |
| `list_assignments` | Firmendaten, Kategorien, Bankkonten, Depots, effektive Rechte |
| `list_documents` | Stabile UUID-Cursor-Paginierung, Status/Art/Firma/Periode/Suche |
| `get_document` | Metadaten, Revision, Prüfpunkte, CAMT-Ergebnis, Herkunft/Revisionen |
| `read_document` | PDF-Text pro Seite bzw. XML und deterministische CAMT-Daten |
| `read_page_image` | Tatsächlicher MCP-Bildinhalt einer PDF-Seite / eines Bildbelegs |
| `get_file_access` | Relative authentifizierte Original-/Seiten-URLs samt SHA256 |
| `prepare_upload` / `complete_upload` | Prüfsummen- und größengeprüfter authentifizierter Binärtransfer |
| `claim_document` | 20-Minuten-Bearbeitungslease, ohne manuelle Korrekturen zu blockieren |
| `save_document_result` | Strukturiertes Ergebnis mit Ausgangsversion, Validierung, Revision und Ablage |
| `find_duplicates` | Firmeninterne Hash-/Aussteller-/Nummernhinweise, keine Löschung |
| `start_imap_import` / `get_job` / `resume_job` | Persistenter Import/Paketstatus und explizite sichere Fortsetzung |
| `list_import_errors` | Sichtbare Importfehler/erhaltene abgelehnte Anhänge |
| `list_month_folders` | Echte Ordnerstruktur samt paginiertem Dokumentinhalt |
| `preview_package` / `create_package` | Vollständigkeitsprüfung und asynchrone Snapshot-Erzeugung |
| `list_packages` / `get_package` | Paketversionen, Nachtragsbezug, eingefrorene Inhaltsliste/Download |
| `send_package` / `get_dispatch` / `list_dispatches` | Ausdrücklicher, berechtigter Snapshot-Versand und nachvollziehbare Versuche |
| `start_agent_run` / `report_agent_run` | Externe Orca-Auftrags-/Ergebnis-IDs und Zwischen-/Abschlussberichte |

`list_documents`: `status="open"` liefert `new` und `review`; `status=null` liefert alle. Cursor bis `next_cursor=null` weiterreichen. Nicht ausschließlich auf den Zielmonat filtern, solange neue Dokumente noch keine Periode haben. UUID-Cursor statt Offset verhindert Überspringen, wenn vorherige Dokumente im selben Lauf auf `ready` wechseln.

`get_file_access`: URLs relativ zur **MCP-Origin** auflösen, denselben Bearer-Header verwenden. Keine URL aus einem Beleg mit Zugangsdaten aufrufen. Originale sind bytegleich und SHA256-geprüft. Scans brauchen keinen serverseitigen OCR-/LLM-Schlüssel: `read_page_image` liefert visuell auslesbare Seiten.

## Strukturierte Ergebnisübernahme

Vollständiges Eingabeschema: `DocumentResult` in `backend/accounting/schemas.py`; zusätzlich authentifiziert unter `GET /api/schema/`. MCP veröffentlicht dasselbe Pydantic-Schema im Tool `save_document_result`.

- `document_id`, `base_version` sind verbindlich.
- `company_id`, `kind`, `period`, `account_id`, `category_id` sind die vollständige gewünschte Zuordnung. Fehlendes bleibt `null`.
- `metadata` enthält Rechnungspartner/-nummer/-daten, Originalwährung, Dezimalbeträge/Steueraufteilungen oder Konto-/Depotzeitraum; `note`, `open_points`, feldbezogene `evidence` sind getrennt korrigierbar.
- Geld und Steuersätze als Strings, **keine Float-Arithmetik**. Fehlendes nicht als `0` erfinden.
- Mehrmonatige Konto-/Depotzeiträume bleiben zunächst offen. Nur bei ausdrücklicher Zuordnungsregel/-bestätigung `metadata.period_assignment_confirmed=true` **und** nachvollziehbare `period_assignment_reason` setzen. Die Originaldaten `period_start`/`period_end` bleiben unverändert; die Begründung erscheint im Snapshot und CSV/XLSX.
- `approve=false` speichert einen überprüfbaren Zwischenstand. `approve=true` erfordert keine offenen Server-/Agenten-Prüfpunkte.
- `related_ids` sind gerichtete, revisionsgeschützte Verweise **dieses Quelldokuments**, etwa vom CAMT auf das PDF. Beide Originale bleiben enthalten. Eingehende Verweise erscheinen nur lesend unter `referenced_by_ids`; ein älterer Lauf am Zieldokument kann damit keine manuelle Verknüpfung am Quelldokument entfernen. Änderung/Entfernung erfolgt mit der Ausgangsversion des jeweiligen Quelldokuments. Vor einem Firmenwechsel eingehende Verweise/Dubletten ausdrücklich in der bisherigen Firma lösen. `duplicate_of` markiert eine bestätigte firmeninterne Dublette, ohne sie zu löschen.
- Ausgangsversion wird unter Zeilensperre verglichen; bei Konflikt HTTP 409 bzw. MCP-Toolfehler. Neuere manuelle Korrekturen niemals durch bloßes Erhöhen der Versionsnummer umgehen.

REST und MCP schreiben dieselben Revisionen mit Benutzer, Quelle (`manual` / `agent:<run_id>`), Zeitpunkt, Ausgangs- und Ergebnisversion.

## Kategorienvorschläge über den Agenten

Der Belegskill (1.3), Bank-/Depotskill (1.3) und Monatsskill (1.1) berücksichtigen Kategorien im regulären Lauf. `list_assignments` liefert die vorhandenen IDs/Namen pro Firma. Eindeutig passende bestehende Kategorien können bei normaler Aufarbeitung verwendet werden; vorhandene manuelle Zuordnungen bleiben erhalten. Neue Kategorien werden **nur vorgeschlagen**, nicht ungefragt angelegt. Keine erfundenen IDs, keine Kategorie je Lieferant/Monat und keine automatische steuerliche Kontierung. Ein Kontoauszug mit gemischten Bewegungen ist nicht insgesamt „Bankspesen“.

Vorschläge werden mit Name, Begründung und berechtigten Beispieldokument-IDs pro Firma gebündelt. Der bestehende MCP-Weg reicht dafür aus: `start_agent_run` → `report_agent_run(result={"category_suggestions": [...]}, status=...)` → `get_job`. Ein Vorschlag enthält `company_id`, `name`, `existing_category_id` (bei neuen Namen `null`), `reason` und `document_ids`. Es handelt sich um eine **Konvention im Agentenbericht**, nicht um neue Felder in `DocumentResult` oder einen eingebauten LLM-/Vorschlagsdienst. Lesen erfordert `read`, Berichte speichern `process`; zum Vorschlagen sind keine Adminrechte nötig. Der aktuelle MCP stellt kein Werkzeug zum Anlegen neuer Kategorien bereit.

Bei Wiederaufnahme laufende Zwischenberichte lesen und nach Firma/normalisiertem Namen zusammenführen; andere Ergebnisfelder bewahren. Fertige Berichte nicht überschreiben. Ein reiner Vorschlagsauftrag analysiert auch bereits freigegebene Belege innerhalb des beauftragten Firmen-/Zeitraumumfangs, ändert aber weder Dokumentrevisionen/Kategorien noch Paketstände. Eine nicht bestätigte bzw. fehlende Kategorie ist allein kein Freigabeblocker.

## Aufträge, Idempotenz und Versand

Externe Auftrags-ID als stabilen `idempotency_key` verwenden, beispielsweise `orca:<job>:imap`, `orca:<job>:paket`, `orca:<job>:versand`. Derselbe Schlüssel bei anderen Parametern erzeugt einen Konflikt. Job-/Paket-/Dispatch-IDs im Agentenbericht speichern und nach Unterbrechung weiterverwenden.

Paketerstellung liefert zunächst eine Job-ID. `get_job` mit angemessener Pause abfragen; Ergebnis enthält die Paket-ID. Ein fertiges Paket ist ein unveränderlicher Snapshot einschließlich Empfängern, Versandregel, Ausschlüssen und Metadatenrevisionen. Für Änderungen eine neue Version oder einen Nachtrag mit `parent_id` erzeugen.

Versand nur auf vertrauenswürdigen ausdrücklichen Auftrag und mit `send`-Recht. Gleicher Schlüssel ergibt denselben Auftrag. Für einen weiteren Versand derselben Version ist ein **neuer Schlüssel plus `resend_of` auf den letzten Dispatch** notwendig. Laufenden Versand nicht überholen. Status `unknown` nach Abbruch/Neustart wird nie automatisch erneut gesendet. `accepted` bedeutet SMTP-Annahme, nicht bestätigte Zustellung. `partial` zeigt einen unvollständigen Teile-/Empfängerversand.

## Offizieller Client

`uv sync --locked` installiert den offiziellen Client einschließlich HTTP-Transport. Keine Token als CLI-Argumente verwenden.

```python
import asyncio
import os
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer " + os.environ["LA_MCP_TOKEN"]}
    ) as http:
        transport = streamable_http_client("http://localhost:8000/mcp/", http_client=http)
        async with Client(transport) as client:
            tools = await client.list_tools()
            result = await client.call_tool("list_companies", {})
            print([t.name for t in tools.tools])
            print(result.structured_content)

asyncio.run(main())
```

SDK v2 verwendet hier `httpx2` (transitiv im Lockfile), nicht den v1-Client mit einem dreiteiligen Stream-Tupel. Listen können im strukturierten Ergebnis unter `result` gewrappt sein; `scripts/mcp_client.py` behandelt dies.

`uv run python scripts/mcp_client.py --exercise --mail --report var/smoke-report.json` ist ein reproduzierbarer echter Ende-zu-Ende-Test mit neuer synthetischer Firma und kontrolliertem GreenMail. Ohne `--exercise`/`--verify-report` führt der Client nur Discovery/Firmenabfrage aus.

Nach Neustart oder gemeinsamem Restore lässt sich **derselbe bestehende** synthetische Ablauf ohne neue Dokumente/Neuversand prüfen:

```sh
uv run python scripts/mcp_client.py --verify-report var/smoke-report.json --mail \
  --report var/replay-report.json
```

Dies prüft die ursprünglichen Original-/Paketprüfsummen, wiederverwendet denselben Paketjob/Versandschlüssel, führt einen neuen IMAP-Abruf vom wiederhergestellten Checkpoint aus und weist null neue Anhänge sowie unveränderte Empfängerpostfach-Mailanzahl nach. Beide Modi widerrufen ihren temporären Token im `finally`-Block und prüfen auch den Widerrufsstatus. Die Reports enthalten IDs/Prüfsummen/Idempotenzpräfixe, keine Zugangstoken oder Mailpasswörter.

## Orca-Live-Einrichtung

Die drei Skills aus `skills/` im externen Agenten verfügbar machen. Den internen MCP-Endpunkt samt geheimem Token in dessen MCP-Konfiguration eintragen. Firma, Monat, stabile Auftrags-ID und Versandautorisierung aus dem Orca-Auftrag übergeben. `start_agent_run`/`report_agent_run` dokumentieren den Ablauf.

Die Anwendung legt **keinen tatsächlichen Orca-Termin/Job** an. Erreichbarkeit, Seiten-/Originalzugriff, Modellauslese und Berechtigungen mit dem tatsächlich dort verwendeten Agenten gehören zur späteren Live-Abnahme. Der synthetische SDK-Test ist ein Protokoll-/Anwendungstest, kein behaupteter produktiver Orca-Lauf.
