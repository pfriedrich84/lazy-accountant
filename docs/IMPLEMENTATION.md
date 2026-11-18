# Implementierungsprotokoll – Issue #1

Beginn: 2026-11-18 (UTC). Branch: `pfriedrich84/mvp-implementieren-dokumentablage-imap-smtp-mcp`.

## Auftrag und Arbeitsweise

Etappe 1 aus `PLAN.md` vollständig implementieren; spätere Etappen nicht vorziehen. Keine produktiven Zugangsdaten erforderlich. Technische Entscheidungen autonom im vereinbarten Stack. Kleine nachvollziehbare Commits nach Meilensteinen, bei längeren Schritten ungefähr stündlich; Push auf den Arbeitsbranch.

## Meilensteine

- [x] M1: Python-Stack gepinnt/gelockt, Modelle/Migrationen, Auth und gemeinsame Services. Compose/Frontend folgen in M2/M5.
- [x] M2: Sichere Originalablage, Revisionen, CAMT, REST und nutzerorientierte Oberfläche.
- [x] M3: IMAP, persistente Jobs, unveränderliche Pakete/Nachträge, SMTP mit echtem kontrolliertem Mailserver geprüft.
- [x] M4: Authentifiziertes MCP, echter Client-Durchlauf, drei gegen Tool-Schemas geprüfte ausführbare Skills.
- [x] M5: Beispielmonat, automatisierte Prüfungen, tatsächlicher Browser-/Compose-Lauf, gemeinsames Backup/Restore, CI und Betriebsdokumentation.

## Bekannte Umgebungseinschränkungen

- Zu Beginn kein Docker/Compose installiert; kein passwortloses sudo. Lokaler Daemon wegen fehlendem privilegierten `newuidmap` nicht nutzbar. **Tatsächlicher Compose-Lauf inzwischen auf GitHub Actions erfolgreich nachgewiesen**, siehe M5.
- Python 3.13.5 und Node 26.13.0 vorinstalliert. Aktuelle stabile Laufzeiten werden gesondert installiert.
- Repository enthielt zu Beginn ausschließlich `README.md` und `docs/PLAN.md`.

## Abnahme

### 2026-11-18 – M1 / erster Backend-Durchstich

- `uv sync`: 52 Pakete unter Python 3.15.2 installiert, reproduzierbares Lockfile.
- `uv run python backend/manage.py migrate --noinput`: eigene und Framework-Migrationen erfolgreich (lokale SQLite-Entwicklungsdatenbank).
- `uv run python backend/manage.py check`: keine Fehler.
- `uv run pytest -q`: **10 Tests erfolgreich** (Originalbytes, echte Ordner, Firmenisolation/Downloads, sichere Dateinamen, Dubletten, Summen/Decimal, Versionskonflikte, unterbrochene Ablage, CAMT/XML-Sicherheit, binärer Upload, PDF-/Bildansicht, Login-CSRF).
- Import von `config.asgi` einschließlich offiziellem MCP-v2-Server erfolgreich. Ein echter Protokoll-Client-Test steht noch aus.
- Docker-CLI 29.10.0 testweise außerhalb des Repositorys heruntergeladen. Rootless-Daemon scheitert bisher am fehlenden privilegierten `newuidmap`; Compose-Laufzeittest weiterhin offen.

### 2026-11-18 – M2/M3 / Oberfläche und fachliche Integration

- PostgreSQL **18.7** ohne Root-Rechte aus offiziellem Release-Tarball außerhalb des Repositorys gebaut und lokal auf Port 55432 gestartet.
- Backend-Suite: **20 Tests erfolgreich auf SQLite und PostgreSQL 18.7**. Der echte PostgreSQL-Lauf deckte eine unzulässige Sperre eines nullable JOIN auf; mit `select_for_update(of=("self",))` korrigiert und erneut geprüft.
- Neue Abdeckung: vollständiger Testmonat/ZIP-Prüfsummen, Snapshot-Unveränderlichkeit, Nachtragsketten, persistente Paketerstellung, IMAP-Unterbrechung nach erstem Anhang, erneuter Abruf/UIDVALIDITY-Wechsel, Alias-Prüfliste, erhaltene abgelehnte Anhänge, SMTP-Annahme, expliziter Neuversand, unbekannter Ausgang, unterbrochener Versand, größenbegrenzte Mailteile und Rekonstruktion, verschlüsselte Mailgeheimnisse.
- Frontend: `npm run typecheck`, `npm run build`, **5 Vitest-Tests erfolgreich**. React Router Framework-SPA, MUI 9, TanStack Query; MUI-9-Systemprops auf `sx` migriert. Neueste stabile Abhängigkeiten ohne Downgrade.
- Playwright gegen den tatsächlich laufenden ASGI-Server: zentraler Ablauf **Firma anlegen → PDF hochladen → prüfen/freigeben → Paket erzeugen → ZIP herunterladen** erfolgreich auf Desktop und Mobilgerät; keine JavaScript-Laufzeitfehler, keine horizontale Seitenüberbreite. Synthetische Screenshots lokal unter dem ignorierten `frontend/test-results/` geprüft.
- Erster echter offizieller MCP-v2-HTTP-Client: Authentifizierung, Protokollverbindung, 22 Tool-Schemas und Firmenabfrage erfolgreich. Vollständiger MCP-Monat folgt.

### 2026-11-18 – M4 / echter MCP- und Mail-/Worker-Durchlauf

- Backend-Suite jetzt **21 erfolgreiche Tests**; zusätzlicher tatsächlicher Streamable-HTTP-Server im Test, offizieller SDK-Client, Uploadticket/Binärtransfer, Text-/Bildzugriff, sämtliche Dokumentarten, Cursor-Paginierung, Konflikt-/Firmen-/Funktionsrechte, echte Tool-Schemas und Skill-Werkzeugnamen.
- MCP-Monat auch gegen PostgreSQL 18.7 erfolgreich. Tool-Datenbankverbindungen werden explizit geschlossen; ASGI-Mount/Lifecycle und Hostschutz geprüft.
- Kontrolliertes **GreenMail 2.1.15** lokal außerhalb des Repositorys mit Temurin JRE 27.0.1.1 gestartet. Tatsächlicher separater Django-Q2-Worker mit PostgreSQL-ORM-Broker, keine synchrone Queue-Abkürzung.
- `MAIL_TEST_APP_HOST=127.0.0.1 uv run python scripts/mcp_client.py --url http://127.0.0.1:8001 --exercise --mail`: **erfolgreich**. Mehrere neue Mailanhänge per SMTP eingeliefert, über IMAP importiert, erneuten Abruf ohne Dubletten geprüft; 8 Originale über MCP gelesen/klassifiziert, ZIP mit vier Ordnern/Prüfsummen erzeugt; **5 SMTP-Mailteile** angenommen, aus dem Empfängerpostfach zurückgelesen, zum bytegleichen ZIP rekonstruiert und Gesamt-SHA256 verglichen. Wiederholte Paket-/Versandaufträge erzeugten keine Duplikate. Temporärer Testtoken anschließend widerrufen.
- Der echte IMAP-Test fand eine GreenMail-Inkompatibilität mit gruppierter SEARCH-Syntax. Auf standardkonforme getrennte Suchkriterien und locale-unabhängige englische Monatsnamen korrigiert, danach Gesamtlauf erfolgreich.
- Dockerfile/Compose mit Versions-/Digest-Pins, privatem Bind-Mount, Bootstrap und Healthchecks sowie optionalem GreenMail-Profil hinzugefügt. `docker compose config --quiet` (CLI 5.8.0) erfolgreich. Lokaler Daemon weiterhin nicht verfügbar; CI-Compose-Lauf wird separat nachgewiesen.
- Gemeinsame Backup-/Restore-Skripte und Integritätsprüfung hinzugefügt; Laufzeittest steht noch aus. README und Betriebs-/MCP-/CAMT-Dokumentation beschreiben tatsächlich implementierte Schnittstellen.

### 2026-11-18 – M5 / vollständige Compose-Abnahme auf GitHub Actions

**[CI-Lauf 44403271261](https://github.com/pfriedrich84/lazy-accountant/actions/runs/44403271261)**, Commit `c983c53`, abgeschlossen **21:49 UTC: alle drei Jobs erfolgreich**.

- `backend`: PostgreSQL-18.7-Dienst, exakter Python-/uv-Lock, Ruff, unveränderte Migrationen, **21 Tests bestanden**.
- `frontend`: exakter Node-/npm-Lock, Typecheck, **5 Tests bestanden**, Produktionsbuild erfolgreich.
- `compose`: Digest-gepinnte Images tatsächlich gebaut; `app`, `worker`, `db` und `mail-test` gestartet und healthy.
- Tatsächlicher SDK-/IMAP-/ORM-Worker-/SMTP-Durchlauf: **8 Dokumente, 26 Tool-Schemas, 5 angenommene Mailteile, wieder zusammengesetztes ZIP mit identischer SHA256**.
- Playwright gegen die gebaute Compose-Anwendung: **2 Browserdurchläufe erfolgreich**, Desktop und Mobil; Screenshots ausschließlich synthetischer Daten als CI-Artefakt gespeichert.
- Worker tatsächlich neugestartet. `scripts/backup.sh` und `scripts/restore.sh` tatsächlich ausgeführt, nicht nur syntaktisch geprüft. Gemeinsame Integritätsprüfung vor/nach Wiederherstellung erfolgreich: **18 Dokumente, 3 Pakete, 1 Versandauftrag**.
- Danach erneut vollständiger MCP-/IMAP-/SMTP-Monat gegen die wiederhergestellte Anwendung erfolgreich; wiederum bytegleich rekonstruiertes ZIP.
- Die lokale Docker-Einschränkung bleibt eine Eigenschaft der Entwicklungsmaschine, ist aber **kein offener Compose-Abnahmenachweis mehr**: der echte CI-Lauf belegt den Containerpfad.

### Nachhärtung

ISO-4217-Minor-Units und kaufmännische Steuerrundung, sichere begrenzte Bild-/PDF-Vorschau, Mailteil-SHA256 direkt vor Versand, SMTP-CRLF-Größenmessung, monotone IMAP-Checkpoints bei parallelem Abruf, eindeutige Aliasregeln für geteilte Postfächer, sichtbarer physischer Ablagestatus und konfigurierbares Paketgrößenlimit ergänzt. Explizite Tests für alle 18 CAMT-Namespaces, Formel-Injection, Teilablehnung, manipulierte Teile, Dateioperation-/Integritätsfehler, sichere Restorearchive und konkurrierende Metadatenübernahme.

- Nachhärtung lokal tatsächlich geprüft: **55 Tests auf PostgreSQL 18.7 bestanden**; SQLite: **54 bestanden, 1 ausdrücklich übersprungener PostgreSQL-Zeilensperrentest**. Frontend erneut Typecheck/Produktionsbuild und **5 Tests erfolgreich**; Migrationen unverändert; Compose-Konfiguration gültig.

- Beispielmonat erweitert: Bootstrap erzeugt jetzt je **8 Dokumente in beiden Firmen**, jeweils vollständig separat paketierbar; Kontokennungen und Bildbelege passen zur jeweiligen synthetischen Firma/Periode. Wiederholter Bootstrap ist getestet idempotent. CSV/XLSX frieren auch Konto-/Depotkennung ein.
- Konten-/Depotnamen, Kennungen und Kategorien sind nun auch direkt in der normalen Oberfläche bearbeitbar. Erweiterter Browserablauf inklusive Anlegen/Umbenennen und Kategoriezuordnung auf Desktop und Mobil erneut **2-mal erfolgreich**. Aktueller lokaler separater PostgreSQL-Worker und echter Mail-/MCP-Durchlauf erneut erfolgreich.

### Erweiterte Abnahme und Verweis-Schutz

- Auch [CI-Lauf 44410106920](https://github.com/pfriedrich84/lazy-accountant/actions/runs/44410106920), Commit `3abfe16`, ist vollständig grün: **55 PostgreSQL-Tests**, Frontend, tatsächlicher Compose-/Mail-/Browserlauf und gemeinsamer Restore mit **26 Dokumenten, 3 Paketen, 1 Versandauftrag**.
- Der erweiterte echte Browserlauf bearbeitet nun **beide vollständigen Beispielmonate mit allen acht Dokumentarten**: Mehrfachupload einschließlich XML/PNG, Zuordnung/Konten/Depots, Freigabe, CAMT→PDF-Verweis, Vorschau, ZIP-Download. Zusätzlich bleibt der zentrale Ablauf mit Firmen-/Konten-/Kategorien-Einstellungen auf Desktop und Mobil geprüft: **3 Browserfälle bestanden**, der redundante zweite vollständige Monatslauf auf Mobil bewusst übersprungen. Ein dabei gefundener fehlender zugänglicher Name des globalen Firmenwählers wurde durch korrektes MUI-`labelId` behoben.
- Verweise sind jetzt eindeutig der Revision ihres Quelldokuments zugeordnet. Ein älterer Lauf am Ziel kann keine manuelle Rückverknüpfung stillschweigend entfernen. Eingehende Verweise bleiben sichtbar; Firmenwechsel mit eingehenden Verweisen/Dubletten benötigt ausdrückliches vorheriges Lösen. Gemeinsame Sperrreihenfolge schützt gegen paralleles Verschieben/Verknüpfen. Die Migration verändert keine Originale oder vorhandenen Verweise.
- Aktuelle Backend-Suite: **60 PostgreSQL-Tests bestanden**, SQLite **59 bestanden/1 bewusst übersprungen**. Typecheck, Produktionsbuild und **5 Frontendtests** weiterhin erfolgreich.
- IMAP-TLS erzwingt explizit System-CA-Prüfung und Hostnamenprüfung (`ssl.create_default_context`), statt den nicht verifizierenden Python-`imaplib`-Standardkontext zu übernehmen. Regressionstest prüft `CERT_REQUIRED` und `check_hostname`; tatsächliche Anbieter-/Zertifikatsanbindung bleibt Live-Einrichtung.
- Zusätzliche Django-Admin-Sicherung: bestehende Firmenordner, Firmenzuordnung von Konten/Kategorien/Postfächern und Kontoart sind auch dort unveränderlich, statt den fachlichen Ablage-/Berechtigungsvertrag zu umgehen. Regressionstest vorhanden.
- Quartals-/Mehrmonatsauszüge sind mit unverändertem echten Zeitraum explizit bestätigbar: begründete Übergabemonatszuordnung statt künstlicher Datumsverkürzung. Checkbox/Begründung in der Oberfläche, strukturierte MCP-Felder sowie Exportbegründung und Regressionstest; unbekannte Währungen, fehlende Währung bei Beträgen und unplausible Steuersätze bleiben gesperrt.
- Der offizielle Client kann mit `--verify-report` denselben ursprünglichen synthetischen Auftrag erneut prüfen: Original-/Paket-SHA256, wiederverwendeter Paketjob/Versandauftrag, null Anhänge ab IMAP-Checkpoint, unveränderte Anzahl empfangener Teile. Lokal mit tatsächlichem GreenMail/PostgreSQL/Worker geprüft; CI führt diesen zusätzlichen Replay explizit **nach** gemeinsamem Restore aus.

### Vollständiger Restore-Replay in CI nachgewiesen

[CI-Lauf 44417598400](https://github.com/pfriedrich84/lazy-accountant/actions/runs/44417598400), Commit `1c2fd6e`, **alle Jobs erfolgreich**, einschließlich **59 PostgreSQL-Tests**, **3 Browserfälle bestanden / 1 bewusster redundanter Mobil-Skip** und tatsächlichem gemeinsamen Backup/Restore von **26 Dokumenten, 5 Paketen, 1 Versandauftrag**.

Der nachgeschaltete offizielle MCP-Client hat jetzt auch **denselben ursprünglichen Auftrag** nach Restore wirklich erneut geprüft: 8 Originale und ursprüngliche ZIP-SHA256 identisch; Paketjob und Versandauftrag wiederverwendet; wiederhergestellter IMAP-Checkpoint gültig; null neue Anhänge; weiterhin genau 5 Teile im Empfängerpostfach. Anschließend war ein zusätzlicher neuer synthetischer Monatslauf erfolgreich. Reports und synthetische Screenshots liegen im CI-Artefakt `synthetic-smoke-results`.

Letzte Eingabehärtung: UTF-8-Dateinamen werden nach Bytes statt Zeichen begrenzt und behalten ihre Erweiterung; vollständiger gültiger Originalname bleibt erhalten. Ungültige/überlange Originalnamen werden explizit abgelehnt statt still abgeschnitten; fehlerhafte Mailheader werden JSONB-sicher sichtbar escaped, abgelehnte Anhangsbytes bleiben erhalten. Regression mit langem japanischem Namen, Nullbyte/ungültigem Unicode und fehlerhaftem Mailheader auf PostgreSQL bestanden.

### Letzter vollständiger Stand

[CI-Lauf 44420245553](https://github.com/pfriedrich84/lazy-accountant/actions/runs/44420245553), Commit `c55defd`: **60 PostgreSQL-Tests, Frontend-Typprüfung/5 Tests/Build sowie der gesamte Compose-/3-Browserfälle-/Worker-/Backup-/Restore-/MCP-Replay-Lauf erfolgreich**. Der README-Screenshot stammt aus dessen tatsächlichem vollständigen Beispielmonat (ausschließlich synthetische Daten).

Die Oberfläche übernimmt eine **ungeklärte Firma nicht mehr aus dem globalen Anzeigekontext**: Das Detailformular bleibt ausdrücklich „Ungeklärt“, bis der Benutzer nach Originalprüfung selbst eine Firma wählt. Der zentrale Desktop-/Mobil-Browsertest importiert nun absichtlich in diesen persönlichen Eingang und prüft die bewusste Zuordnung; lokal erneut alle **3 Browserfälle erfolgreich**.

Noch offen ist ausschließlich die kundenspezifische Live-Einrichtung gemäß Betriebsdokumentation: realer Host/Speicher, echte Firmendaten/Mailanbieter/Empfänger, repräsentative anonymisierte Originale und tatsächlicher Orca-Agent/Termin. Der synthetische Client behauptet keinen produktiven Orca-Lauf. Weitere ausgeführte Prüfungen werden ergänzt.
