# Lazy Accountant — Logoentwurf

![Logo mit Wortmarke](lazy-accountant-logo.svg)

**Status: abgestimmtes Logo, in der Produkt-README eingebunden; App-Integration folgt separat.** Das Zeichen greift auf ausdrücklichen Nutzerwunsch ArchiBots freundlichen Roboter auf, ist aber als flaches SVG neu gezeichnet. Keine Originalbildpixel, keine Nachzeichnung der dreidimensionalen Illustration. Das Belegmotiv mit Haken steht für delegierte Belegarbeit, nicht für eine steuerliche oder sicherheitstechnische Zertifizierung.

## Dateien

- [`lazy-accountant-logo.svg`](lazy-accountant-logo.svg): transparente Wort-/Bildmarke für helle Hintergründe, 760 × 224.
- [`lazy-accountant-icon.svg`](lazy-accountant-icon.svg): transparentes Logozeichen, 256 × 256; als App-Icon ab etwa 32 px. Für ein 16-px-Favicon sollte eine reduzierte Fassung erstellt werden.
- [`logo-preview.png`](logo-preview.png): im Browser gerenderte Vorschau mit Logo, Größenvergleich und Farben.
- [`preview.html`](preview.html): lokale Vorschauseite ohne externe Ressourcen.

Die Farben stammen aus der vorhandenen App: Grün `#175b50`, Kupfer `#bf743b`, ergänzt um Mint `#e3f0eb`. Die Wortmarke enthält SVG-Text mit `Trebuchet MS` / `DejaVu Sans` / `sans-serif`; ihre genaue Form hängt daher vom verfügbaren Font ab. Vor einer endgültigen Markenfreigabe kann die gewählte Schrift in Pfade umgewandelt werden. Das Icon ist vollständig fontunabhängig. Eine Dark-Mode-Variante ist noch nicht enthalten.

## Herkunft

Referenz: [`pfriedrich84/archibot`, `app/static/logo-full.png`](https://github.com/pfriedrich84/archibot/blob/a012ae94546543b35d8c1eea93de7833f8c318bc/app/static/logo-full.png), eingesehen unter Commit `a012ae94546543b35d8c1eea93de7833f8c318bc`. Das Repository enthält eine MIT-Lizenz, Copyright © 2026 Paul Friedrich. Der zugehörige Lizenztext wird vorsorglich unter [`LICENSE.archibot`](LICENSE.archibot) mitgeführt; dies ist keine Aussage über Markenrechte.

Die SVGs wurden direkt als Vektorgeometrie erstellt, nicht mit einem Bildgenerator. Die PNG-Vorschau wurde aus `preview.html` mit agent-browser 0.39.4 / Chrome for Testing 158.0.8127.36 bei 1100 × 820 aufgenommen; im Render wurde DejaVu Sans verwendet. Visuell auf Wortmarke, unbeschnittene Darstellung und Icon-Größen geprüft.

Zum Ansehen aus der Repository-Wurzel:

```sh
python3 -m http.server 18002 --bind 127.0.0.1 --directory docs/brand
# http://127.0.0.1:18002/preview.html
```
