# Impeccable für die Frontend-Entwicklung

Projektlokal unter `.pi/skills/impeccable/` installiert, nicht als Laufzeitabhängigkeit der Anwendung. Die fachlichen MCP-Skills unter `skills/` bleiben unverändert. Keine globalen Einstellungen, automatischen Hooks oder zusätzlichen CI-Jobs wurden eingerichtet.

## Quelle und Aktualisierung

- Upstream: https://github.com/pbakaus/impeccable
- Commit: `b49177d32788f2dc585c42831d845dacf1ebed2c`
- Skill-Version: `4.10.0`
- Übernommen: `.pi/skills/impeccable/`, unverändert, mit `LICENSE` und `NOTICE.md` aus dem Upstream-Repository.

Updates bewusst aus einem geprüften Upstream-Commit übernehmen und als Codeänderung reviewen. Nicht bei jedem Build die neueste Version herunterladen.

## Nutzung in Pi

Nach dem Checkout `/reload` ausführen oder Pi neu starten. Beispiele:

```text
/skill:impeccable critique die Dokumentübersicht
/skill:impeccable polish die Monatsansicht
/skill:impeccable audit frontend/app/routes/documents.tsx
```

Optional mit `/skill:impeccable init` Produktkontext erfassen und mit `/skill:impeccable document` die bestehende Gestaltung dokumentieren. Die Installation allein verändert weder Oberfläche noch Produktkontext.

## Ausführung und Datenschutz

- Der mitgelieferte Launcher kann beim ersten tatsächlichen Aufruf eine Engine aus den GitHub-Releases in den Benutzer-Cache herunterladen. Version und SHA-256-Prüfsummen sind im Skill enthalten. Für Offline-Nutzung die Engine zuvor bereitstellen.
- Projektweite Telemetrie ist in `.impeccable/config.json` deaktiviert. Das unterbindet laut Upstream nicht sämtliche Netzwerkzugriffe, etwa den Abruf visueller Richtungen.
- Live-Modus nur gegen einen lokalen Entwicklungsserver verwenden, niemals gegen die produktive Buchhaltungsinstanz mit echten Dokumenten.
- Live-Apply kann laut Upstream externe Agenten ohne Sandbox starten. Wenn Live-Modus verwendet wird, mit `IMPECCABLE_LIVE_COPY_AGENT=chat` auf die aktuelle Agentensitzung begrenzen oder mit `off` deaktivieren.
- Keine Dokumente, Zugangsdaten, Kontoauszüge oder produktiven Screenshots an externe Dienste übertragen.

Die Installation wurde strukturell geprüft; Engine und Live-Modus wurden dabei nicht ausgeführt.
