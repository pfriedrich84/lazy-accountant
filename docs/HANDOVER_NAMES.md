# Übergabenamen

Originalbytes, SHA256, Upload-/IMAP-Namen, Dokument-ID und technische Ablagepfade bleiben erhalten. `handover_name` ist ein separates Feld; der zentrale serverseitige Generator benötigt kein LLM. Neue Uploads erhalten einen sicheren Fallback, bei strukturierter Verarbeitung wird ein generierter Name gespeichert. Bestehende Zeilen werden durch die **reine Schema-Migration nicht umbenannt**. Bis zur expliziten Übernahme verwenden sie einen sicheren Originalnamen mit Kennung.

## Metadaten und Datumsregeln

- ER/Gutschrift: `date issuer Rechnung|Gutschrift number`; AR/Storno: `date recipient Rechnung|Storno number`. `confirmed_partner_name` kann eine **bestätigte** Geschäftspartnerbezeichnung anstelle der juristischen Auslesebezeichnung enthalten. Keine automatische Namenskorrektur oder Ableitung aus Uploadnamen.
- Sonstiger Beleg: `date issuer subtype number`, ohne Unterart `Beleg`. Für Zahlungsbelege ausdrücklich `subtype: Zahlungsbeleg` verwenden.
- Bank: `period_end bank_short_name <Account.name> Kontoauszug|CAMT number`. `number` bewahrt die jeweilige Original-Auszugkennung, PDF und CAMT sind getrennte Dokumente. `Account.name` ist die bekannte kontoeindeutige Kurzbezeichnung (z. B. `Konto 6600`), nicht die vollständige IBAN. `bank_short_name` muss anhand des Belegs/bestätigter Zuordnungen belegt sein; keine Ableitung aus technischen Dateinamen.
- Wertpapiere: `date bank_short_name subtype isin|number`. Bei `Depotaufstellung`, `Depotauszug` oder `Stichtagsaufstellung` wird **ausschließlich `valuation_date`**, nicht das Erstellungsdatum `date`, verwendet und die bekannte Depot-Kurzbezeichnung `Account.name` ergänzt. Bei anderen Unterarten (z. B. `Ausschüttung`) gilt `date`; ISIN hat Vorrang vor sonstiger Kennung.
- Namensfelder unterliegen dem gleichen strikten Metadata-Schema wie die restlichen Daten. Herkunft in `metadata.evidence.<feld>` dokumentieren. Für benutzte unsichere Felder, fehlendes Datum, fehlenden Partner oder fehlende nötige Kontozuordnung verwendet der Server einen sicheren Fallback mit sichtbarer Warnung. Fehlende optionale Nummern entfallen. Keine Tagesdaten aus `period` erfinden. `period` bleibt der unabhängige Übergabemonat.
- Beträge und Zahlungsstatus werden nicht in Namen aufgenommen. `metadata.number` wird durch die Normalisierung **nicht** geändert.

Unicode wird NFC-normalisiert; Umlaute, Leerzeichen und lesbare Satzzeichen bleiben erhalten. Pfadseparatoren, reservierte Windows-Zeichen/-Namen, Steuer-/Formatzeichen, `..` und abschließende Punkte/Leerzeichen werden abgefangen. Dateinamen sind inklusive Endung und Suffix auf 240 UTF-8-Bytes begrenzt. Die aus den Originalbytes erkannte Formatendung bleibt erhalten. Bei manueller Eingabe werden Pfade und andere Endungen abgewiesen, sonstige Zeichen sicher normalisiert.

Kollisionen werden innerhalb Firma/Jahr/Monat/ER|AR|Bankkonto|Wertpapiere nach NFC und unabhängig von Groß-/Kleinschreibung aufgelöst. Alle betroffenen Dokumente erhalten einen stabilen UUID-**Suffix**, zunächst acht Hexzeichen, bei Bedarf verlängert. Kein UUID-Präfix im normalen generierten Namen, keine `(1)`-Zähler, keine Dublettenentscheidung. Der vollständige Ordnerkontext wird berücksichtigt, auch bei paginierten Listen und Nachträgen. Der gespeicherte Basisname und der tatsächlich verwendete, ggf. disambiguierte Name sind getrennt. Neue Kollisionen können den effektiven Namen ändern, ohne fremde Dokumentrevisionen zu schreiben; alte Pakete bleiben davon unberührt.

## REST, Oberfläche und MCP

Alle Dokumentantworten enthalten:

- `original_name`: unveränderter Importname;
- `handover_name`: gespeicherter Übergabe-Basisname (bei Altbestand ggf. noch leer);
- `proposed_name`: aktueller Generatorvorschlag;
- `effective_name`: tatsächlich verwendeter, kollisionsfreier Name;
- `name_source`: `generated`, `manual` oder `fallback`;
- `name_warning`, `name_conflict`: Hinweise unabhängig von fachlichen `issues`/Freigabe.

Der Generatorvorschlag ist noch nicht zwingend der verwendete Name. Namensänderungen allein verändern weder Prüfstatus noch fachliche Freigabe. Manuelle Namen bleiben bei Agentenverarbeitung und Backfill erhalten. Die Oberfläche zeigt Übergabe- und Originalname separat sowie Vorschlag, Quelle und Hinweise. Der Einzelzugriff verwendet `effective_name` im RFC-konformen `Content-Disposition`.

### Vorschau und ausdrücklicher Backfill

1. Dokumente vollständig paginieren, passende IDs auswählen. Oberfläche: „Übergabenamen vorschauen“ verarbeitet bis zu 100 geladene Dokumente pro Aufruf.
2. `POST /api/document-names/preview/` mit `{"document_ids": ["<uuid>"]}` liefert Alt-/Neuname, Ausgangsversion, Konflikt und manuell geschützte Einträge. **Nur lesend**, `read`-Recht erforderlich.
3. Nach Prüfung ausdrücklich `POST /api/document-names/backfill/` mit `{"entries": [{"document_id": "<uuid>", "base_version": 2}]}` ausführen. `process`-Recht an jedem Dokument erforderlich. Der Batch ist atomar, schützt manuelle Namen und protokolliert tatsächliche Änderungen als `name:backfill`-Revisionen. Ein Versionskonflikt bricht den ganzen Batch mit 409 ab. Weitere Seiten separat auslösen. Keine produktiven Dateien vorab umbenennen.
4. Manuelle Übersteuerung: `PATCH /api/documents/<uuid>/name/` mit `{"base_version": 2, "name": "Mein Beleg.pdf"}`. `name: null` setzt **ausdrücklich** auf den Generator zurück. Gleiche Prozessrechte und Versionsprüfung; Auditquelle `name:manual`. Unveränderte Übernahmen sind No-ops.

MCP verwendet dieselben Services: `preview_document_names(document_ids)`, `backfill_document_names(entries)` und `set_document_name(document_id, base_version, name)`. `get_document`, `list_documents`, `list_month_folders` und `get_file_access` liefern Original-/Vorschlags-/effektive Namen. Token-Firmen-/Funktionsrechte werden nicht erweitert.

## Pakete und Nachträge

Neue Pakete frieren `effective_name` und `archive_path` im Snapshot/PackageItem ein. ZIP-Dateien, CSV-/XLSX-Dateiverweise und Inhaltsliste verwenden genau denselben Pfad unter `Firma/Jahr/Monat/ER|AR|Bankkonto|Wertpapiere/`. Der Archivbau weist doppelte Pfade zusätzlich ab, statt sie zu überschreiben. Bestehende Snapshots/ZIPs/Versandhistorie werden nicht migriert oder neu gebaut. Spätere Namenskorrekturen erhöhen die Dokumentrevision und werden über die bestehende Nachtragskette ausgeliefert. Unterschiedliche PDF-Originale zu derselben Rechnungsnummer bleiben separat und unverändert freigegeben.
