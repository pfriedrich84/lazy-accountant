# Produkt-Screenshots

Die Bilder `demo-*.png` zeigen die **unveränderte React-Oberfläche** von Lazy Accountant mit ausschließlich fiktiven Daten. Aufgenommen mit **agent-browser 0.39.4**, Chrome for Testing **158.0.8127.36**, Browser-Sprache **de-AT** und Node **26.13.0** (Repository-Pin: 26.13.1). Desktop-Viewports: **1440 × 1000** für Übersicht, Eingang und Prüfung, **1440 × 1600** für die Monatsablage und **1440 × 900** für die Übergabevorschau. Alle Bilder zeigen den jeweiligen Viewport. Die Bilder sind nicht retuschiert und enthalten keine produktiven Firmen, Zugangsdaten oder Mailzugänge.

## Galerie

| Datei | Ansicht | Zustand |
| --- | --- | --- |
| [demo-uebersicht.png](demo-uebersicht.png) | Monatsübersicht | 8 Dokumente, 2 offen, noch keine Pakete oder laufenden Aufträge |
| [demo-dokumenteingang.png](demo-dokumenteingang.png) | Eingang | 6 geprüfte und 2 offene Dokumente verschiedener Arten |
| [demo-belegpruefung.png](demo-belegpruefung.png) | Original neben Prüfdaten | Fiktive Software-Rechnung über 120 EUR, Kategorie noch offen |
| [demo-monatsablage.png](demo-monatsablage.png) | Monatsablage | ER, AR, Bankkonto und Wertpapiere, einschließlich offener Prüfungen |
| [demo-uebergabevorschau.png](demo-uebergabevorschau.png) | Paketvorschau | 6 enthaltene Originale, 2 offene Prüffälle; Versand nach Demo-Regel gesperrt |

Der separate ältere Screenshot `uebergabe-desktop.png` bleibt unverändert. Seine bisherige Einordnung als Compose-Testaufnahme steht in der [technischen Einstieg](../GETTING_STARTED.md); er gehört **nicht** zu dieser neu erzeugten Demo-Serie.

## Herkunft und Grenzen

Die Daten stammen aus [`scripts/readme-demo.mjs`](../../scripts/readme-demo.mjs): eine fiktive Firma, Oktober 2026, acht Dokumente. Firmen-/Lieferantennamen tragen „Demo“, Empfänger verwenden die reservierte Domain `example.test`. Die Originalvorschau ist ein synthetisches SVG, **kein aus einer echten PDF-Datei gerendertes Bild**.

Der lokale Demo-Server liefert feste API-Antworten und den echten Frontend-Build. Er verbindet sich weder mit Django/Datenbank noch mit IMAP, SMTP, MCP oder einem Virenscanner. `clean`, Freigabestände, Dateigrößen und Revisionen sind erfundene UI-Fixtures. Die Bilder sind **Produktillustrationen, kein End-to-End-Testnachweis**, keine Bestätigung einer Malwareprüfung und keine Sicherheits- oder Vollständigkeitszusage.

Nur GET und die lesende Paketvorschau werden unterstützt. Upload, Speichern/Freigeben, Paketbildung, Download, Versand und andere Schreibaktionen werden nicht ausgeführt. Die Buttons stammen aus der echten UI; nicht jeder sichtbare Button ist in dieser read-only Demo funktionsfähig. Die Demo ist ausschließlich an `127.0.0.1` gebunden und darf nicht als öffentlicher oder produktiver Dienst verwendet werden. Es gibt keine echte Authentifizierung.

## Reproduzieren

Voraussetzungen: Node gemäß `.node-version`, installierter `agent-browser` mit Chromium (`agent-browser install`, falls noch nicht vorhanden). Keine neuen Projektabhängigkeiten. Die Demo benötigt weder Backend noch Docker/ClamAV.

```sh
cd frontend
npm ci
npm run build
cd ..
node scripts/readme-demo.mjs
# Läuft im Vordergrund; zum Beenden Strg+C.
# Optional: DEMO_PORT=<freier Port> node scripts/readme-demo.mjs
```

In einem zweiten Terminal aus der Repository-Wurzel:

```sh
export AGENT_BROWSER_SESSION="$(agent-browser session id --scope worktree --prefix readme-demo)"
# Neue Session verwenden; Startargumente ändern keinen bereits laufenden Browser.
export LANG=de_AT.UTF-8 LANGUAGE=de_AT:de
export AGENT_BROWSER_ARGS='--lang=de-AT,--accept-lang=de-AT'
agent-browser set viewport 1440 1000
agent-browser open http://127.0.0.1:18000/
agent-browser eval 'localStorage.setItem("company", "1"); localStorage.setItem("period", "2026-10")'
agent-browser reload
agent-browser wait --text 'Bereit für den Monatsabschluss?'
agent-browser screenshot docs/screenshots/demo-uebersicht.png

agent-browser open http://127.0.0.1:18000/documents
agent-browser wait --text 'Wolkenpost IT (Demo)'
agent-browser screenshot docs/screenshots/demo-dokumenteingang.png

agent-browser open http://127.0.0.1:18000/documents/demo-7
agent-browser wait --text 'Prüfen & freigeben'
agent-browser wait --fn 'document.querySelector("img.preview-page")?.complete && document.querySelector("img.preview-page")?.naturalWidth > 0'
agent-browser screenshot docs/screenshots/demo-belegpruefung.png

agent-browser set viewport 1440 1600
agent-browser open http://127.0.0.1:18000/months
agent-browser wait --text '8 Dokumente · 6 geprüft · 2 zu prüfen'
agent-browser screenshot docs/screenshots/demo-monatsablage.png

agent-browser set viewport 1440 900
agent-browser open http://127.0.0.1:18000/packages
agent-browser wait --text 'Vorschau erstellen'
agent-browser find role button click --name 'Vorschau erstellen'
agent-browser wait --text 'Offene Punkte bleiben sichtbar.'
agent-browser screenshot docs/screenshots/demo-uebergabevorschau.png
agent-browser errors
agent-browser close
```

`agent-browser errors` muss leer sein; zusätzlich die UI auf sichtbare API-Fehler prüfen (nicht jeder HTTP-Fehler ist ein JavaScript-Fehler).

Vor Übernahme alle Bilder visuell prüfen: keine Ladezustände, Fehlermeldungen, Cursor-/Hover-Artefakte oder unerwarteten echten Daten. Browser-Locale und Schriftumgebung können native Datumsfelder und Umbrüche verändern; pixelidentische Reproduktion ist nicht zugesichert.
