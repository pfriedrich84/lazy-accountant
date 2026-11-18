# Implementierungsprotokoll – Issue #1

Beginn: 2026-11-18 (UTC). Branch: `pfriedrich84/mvp-implementieren-dokumentablage-imap-smtp-mcp`.

## Auftrag und Arbeitsweise

Etappe 1 aus `PLAN.md` vollständig implementieren; spätere Etappen nicht vorziehen. Keine produktiven Zugangsdaten erforderlich. Technische Entscheidungen autonom im vereinbarten Stack. Kleine nachvollziehbare Commits nach Meilensteinen, bei längeren Schritten ungefähr stündlich; Push auf den Arbeitsbranch.

## Meilensteine

- [x] M1: Python-Stack gepinnt/gelockt, Modelle/Migrationen, Auth und gemeinsame Services. Compose/Frontend folgen in M2/M5.
- [ ] M2: Sichere Originalablage, Revisionen, CAMT, REST und nutzerorientierte Oberfläche.
- [ ] M3: IMAP, persistente Jobs, unveränderliche Pakete/Nachträge, SMTP.
- [ ] M4: Authentifiziertes MCP, echter Client-Durchlauf, drei ausführbare Skills.
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

Weitere tatsächliche Kommandos und Ergebnisse werden ergänzt. Entwicklung, lokale synthetische Abnahme und produktive Live-Einrichtung bleiben getrennt. Live-Orca, echte IMAP-/SMTP-Zugänge und repräsentative Kundendokumente sind spätere Einrichtungsschritte.
