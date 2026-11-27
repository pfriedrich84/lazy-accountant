# Release- und Kompatibilitätsprüfung

Prüfzeitpunkt: **2026-11-18, ab 20:27 UTC**. Ausschließlich stabile Releases. Kein LTS-Vorzug, keine Prereleases. Paketauflösung mit `uv` unter Python 3.15.2 erfolgreich; Frontendauflösung/Build werden separat im Implementierungsprotokoll nachgewiesen.

| Komponente | Ausgewählt |
| --- | --- |
| Python | 3.15.2 |
| Django / DRF | 6.1.3 / 3.18.3 |
| Django-Q2 | 1.11.1 |
| MCP Python SDK | 2.3.0 (offizielles SDK, neue `MCPServer`-/`Client`-API) |
| PostgreSQL | 18.7 |
| psycopg | 3.3.9 (Binary-Wheel für CPython 3.15 verfügbar) |
| Uvicorn / Starlette | 0.54.0 / 1.10.0 |
| Node | 26.13.1 |
| React / React DOM | 19.3.1 |
| React Router / Framework-Plugin | 8.5.2 |
| Vite / TypeScript | 8.3.8 / 7.0.2 |
| Material UI | 9.5.0 |
| TanStack Query | 5.108.0 |
| Vitest / Playwright | 5.1.1 / 1.65.1 |
| uv (Lockfile/Containerinstallation) | 0.13.9 |
| ISO-4217-Währungsdaten | iso4217 1.16.20260101 |
| Kontrollierter Mailtest | GreenMail 2.1.15 |
| Lokaler Malware-Scanner | ClamAV 1.5.5 (GPL-2.0, Basisimage-Digest in `docker/clamav/Dockerfile`, Python-Standardbibliothek für das private On-Demand-Gateway) |

Alle direkten Python-Abhängigkeiten stehen exakt in `pyproject.toml`, alle transitiven Auflösungen einschließlich Hashes in `uv.lock`. Frontend: exakte Versionen in `frontend/package.json`, transitive Auflösung/Integritäten in `frontend/package-lock.json`. Container-Basisimages erhalten Versions- und Digest-Pins.

## Geprüfte offizielle Quellen

- [Python Downloads](https://www.python.org/downloads/): 3.15.2 als neuester stabiler Download.
- [Django Downloads](https://www.djangoproject.com/download/): 6.1.3 als neueste offizielle Version.
- [Django 6.1 Release Notes](https://docs.djangoproject.com/en/6.1/releases/6.1/): Python 3.15 ab 6.1.3 unterstützt. Neue `MAILERS`-Konfiguration wird verwendet; keine neue Implementierung auf deprecated `get_connection`/`EMAIL_BACKEND`.
- [DRF](https://www.django-rest-framework.org/) und [offizielle PyPI-Metadaten](https://pypi.org/pypi/djangorestframework/json): Django >= 5.2, Python >= 3.10.
- [Django-Q2 ORM-Konfiguration](https://django-q2.readthedocs.io/en/master/configure.html#orm) und [Paketmetadaten](https://pypi.org/pypi/django-q2/json): Django >= 5.2.
- [MCP SDK](https://github.com/modelcontextprotocol/python-sdk), [API-Dokumentation](https://py.sdk.modelcontextprotocol.io/), [Paketmetadaten](https://pypi.org/pypi/mcp/json): stabile v2.3.0, Python >= 3.10, Pydantic >= 2.12.0. Keine veralteten FastMCP-v1-Beispiele übernommen.
- [Node Release Index](https://nodejs.org/dist/index.json): v26.13.1. Vorinstallierte v26.13.0 wird für den reproduzierbaren Build nicht als Pin übernommen.
- [React Router SPA Mode](https://reactrouter.com/how-to/spa) sowie offizielle npm-Paketmetadaten: Router 8.5.2 verlangt Node >= 22.22.0; Framework-Plugin akzeptiert Vite 8 und TypeScript 7.
- [Material UI Installation](https://mui.com/material-ui/getting-started/installation/), offizielle npm-Peers: React 19 und Emotion 11 unterstützt.
- [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview), offizielle npm-Paketmetadaten.
- [PostgreSQL Version Policy](https://www.postgresql.org/support/versioning/) und [Versions-JSON](https://www.postgresql.org/versions.json): neueste stabile Hauptreihe 18, Patch 7.
- Docker Official Images, Tag-Metadaten über Docker Hub API: `python:3.15.2-slim-trixie`, `node:26.13.1-trixie-slim`, `postgres:18.7-trixie` vorhanden; Digests werden im Dockerfile/Compose festgehalten.

[ISO-4217-Paketmetadaten](https://pypi.org/pypi/iso4217/json) am selben Tag nachgeprüft: stabile 1.16.20260101, Python >= 3.6. Validiert Währungscodes und währungsspezifische Minor Units; Geld-/Steuerprüfung verwendet kaufmännisches `ROUND_HALF_UP` statt zufälliger Binärfloat-/Banker's-Rundung.

Weitere Bibliotheken (Pydantic, pypdf/pdfium, Pillow, openpyxl, defusedxml, Cryptography, pytest, Ruff) wurden anhand ihrer offiziellen PyPI-Release-Metadaten gewählt. Siehe exakte Pins und Lockfile.

## ClamAV-Ergänzung (Issue #12)

Offizielles stabiles [Release 1.5.5](https://github.com/Cisco-Talos/clamav/releases/tag/clamav-1.5.5) und Docker-Hub-Tag am 2026-11-19 geprüft, Index-Digest `sha256:12177441d1b40cef3c47b44c4090d59d4babc4c67bedd5af0fa315e603aa6dd8`. Produktionskonfiguration gegen `etc/clamd.conf.sample` dieses Releases geprüft; native 1.5.5 mit frischen offiziellen Signaturen für echte INSTREAM-/EICAR-/Format-/MCP-/REST-/IMAP-Tests ausgeführt. Details: [SECURITY.md](SECURITY.md). Keine zusätzlichen Python-Scanner-Abhängigkeiten: explizit begrenztes clamd-Protokoll über die Standardbibliothek.

## Kompatibilitätsabweichungen

Bislang keine ältere stabile Release-Reihe als Ausweichlösung nötig. Laufzeitprüfungen können weitere Erkenntnisse liefern; konkrete Konflikte werden hier ergänzt, nicht durch stilles Downgrade verdeckt.
