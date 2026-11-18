# Implementierungsprotokoll – Issue #1

Beginn: 2026-11-18 (UTC). Branch: `pfriedrich84/mvp-implementieren-dokumentablage-imap-smtp-mcp`.

## Auftrag und Arbeitsweise

Etappe 1 aus `PLAN.md` vollständig implementieren; spätere Etappen nicht vorziehen. Keine produktiven Zugangsdaten erforderlich. Technische Entscheidungen autonom im vereinbarten Stack. Kleine nachvollziehbare Commits nach Meilensteinen, bei längeren Schritten ungefähr stündlich; Push auf den Arbeitsbranch.

## Meilensteine

- [x] M1: Python-Stack gepinnt/gelockt, Modelle/Migrationen, Auth und gemeinsame Services. Compose/Frontend folgen in M2/M5.
- [x] M2: Sichere Originalablage, Revisionen, CAMT, REST und nutzerorientierte Oberfläche.
- [x] M3: IMAP, persistente Jobs, unveränderliche Pakete/Nachträge, SMTP (synthetische Adapter-Abnahme; echter lokaler SMTP-/Compose-Test folgt).
- [x] M4: Authentifiziertes MCP, echter Client-Durchlauf, drei gegen Tool-Schemas geprüfte ausführbare Skills.
- [ ] M5: Beispielmonat, automatisierte Prüfungen, Browser/Compose, Backup/Restore, CI und Betriebsdokumentation.

## Bekannte Umgebungseinschränkungen

- Zu Beginn kein Docker/Compose installiert; kein passwortloses sudo. Compose-Laufzeittest ist noch **nicht** nachgewiesen. Alternativen werden geprüft; ein verbleibendes Hindernis wird nicht als erfolgreicher Test dargestellt.
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

Weitere tatsächliche Kommandos und Ergebnisse werden ergänzt. Entwicklung, lokale synthetische Abnahme und produktive Live-Einrichtung bleiben getrennt. Live-Orca, echte IMAP-/SMTP-Zugänge und repräsentative Kundendokumente sind spätere Einrichtungsschritte.
