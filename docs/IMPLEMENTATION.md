# Implementierungsprotokoll – Issue #1

Beginn: 2026-11-18 (UTC). Branch: `pfriedrich84/mvp-implementieren-dokumentablage-imap-smtp-mcp`.

## Auftrag und Arbeitsweise

Etappe 1 aus `PLAN.md` vollständig implementieren; spätere Etappen nicht vorziehen. Keine produktiven Zugangsdaten erforderlich. Technische Entscheidungen autonom im vereinbarten Stack. Kleine nachvollziehbare Commits nach Meilensteinen, bei längeren Schritten ungefähr stündlich; Push auf den Arbeitsbranch.

## Meilensteine

- [ ] M1: Reproduzierbarer Stack, Modelle/Migrationen, Auth, gemeinsame Services.
- [ ] M2: Sichere Originalablage, Revisionen, CAMT, REST und nutzerorientierte Oberfläche.
- [ ] M3: IMAP, persistente Jobs, unveränderliche Pakete/Nachträge, SMTP.
- [ ] M4: Authentifiziertes MCP, echter Client-Durchlauf, drei ausführbare Skills.
- [ ] M5: Beispielmonat, automatisierte Prüfungen, Browser/Compose, Backup/Restore, CI und Betriebsdokumentation.

## Bekannte Umgebungseinschränkungen

- Zu Beginn kein Docker/Compose installiert; kein passwortloses sudo. Compose-Laufzeittest ist noch **nicht** nachgewiesen. Alternativen werden geprüft; ein verbleibendes Hindernis wird nicht als erfolgreicher Test dargestellt.
- Python 3.13.5 und Node 26.13.0 vorinstalliert. Aktuelle stabile Laufzeiten werden gesondert installiert.
- Repository enthielt zu Beginn ausschließlich `README.md` und `docs/PLAN.md`.

## Abnahme

Hier werden tatsächliche Kommandos und Ergebnisse ergänzt. Entwicklung, lokale synthetische Abnahme und produktive Live-Einrichtung bleiben getrennt. Live-Orca, echte IMAP-/SMTP-Zugänge und repräsentative Kundendokumente sind spätere Einrichtungsschritte.
