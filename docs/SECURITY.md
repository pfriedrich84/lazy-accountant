# Lokale Malwareprüfung und Quarantäne (Issue #12)

## Sicherheitsgrenze

Alle Web-/REST-Uploads, MCP-Dateitransfers und IMAP-Anhänge verwenden `services.ingest`. Empfangene, nicht leere Dateien bis 25 MiB werden mit SHA-256 atomar und synchronisiert unter `_quarantine/<Dokument-ID>.bin` gespeichert. Transfer-Zwischenstände liegen unter `_quarantine/transfers/`. Nicht unterstützte Formate werden **nicht freigegeben**, sondern bleiben als sichtbarer Importfall erhalten. Die erlaubten Formate bleiben PDF, JPG, PNG und unterstütztes CAMT-XML; ZIP/Archive werden nicht hinzugefügt. Größenüberschreitungen werden abgelehnt; bei IMAP verbleibt die Nachricht unverändert auf dem Server, Herkunft und Fehler bleiben gespeichert.

`security_status` ist unabhängig von fachlichem `status`, Dubletten und Zuordnungen:

- `pending`: dauerhaft übernommen, Scan wartet auf Worker;
- `scanning`: Scanversuch mit begrenztem Lease;
- `clean`: ausschließlich vollständig erfolgreich geprüfte, unveränderte Bytes mit passendem `scanned_sha256` und erfolgreicher Format-/Parserprüfung;
- `infected`: Fund mit Signaturname, Zeitpunkt und Engine-/Datenbankstand;
- `error`: Scanner-/Signatur-/Limit-/Integritäts-/Format-/Parserfehler, **keine Freigabe**.

Q2 transportiert Jobs; Dokument und `ScanAttempt` sind die dauerhafte Scan-Queue und das Audit. Queueverlust ist durch minütliche Wartung rekonstruierbar. Drei automatische Versuche, frühestens nach 300 Sekunden; Scan-Lease 240 Sekunden, danach sichtbarer Abbruch und begrenzte Wiederaufnahme. Ein verspäteter alter Worker darf keinen neueren Versuch freigeben. Bei ausgeschöpften Versuchen: im Dokument **Erneute Prüfung anfordern**, REST `POST /api/documents/<id>/scan/` oder MCP `rescan_document(document_id)`, jeweils mit Verarbeitungsberechtigung. Auch das ist **kein Override**: bis zum tatsächlichen erneuten Erfolg bleibt alles gesperrt. Funde werden nie automatisch gelöscht oder fachlich freigeschaltet.

Die Scannerantwort `stream: OK` ist die einzige akzeptierte unauffällige Antwort. Fehler, unbekannte/abgeschnittene Antworten und Streamlimits bleiben gesperrt. `AlertExceedsMax` und `AlertEncrypted*` liefern für unvollständige Prüfung `Heuristics.Limits.*` bzw. `Heuristics.Encrypted.* FOUND`; diese werden als `error` behandelt. Andere Funde sind `infected`. Signaturen werden vor und nach INSTREAM auf ihr **von clamd geladenes** Datum geprüft, nicht nur auf die Existenz einer heruntergeladenen Datei.

## Freigabe und Zugriffe

Der Scanner bekommt nur INSTREAM-Bytes, keine Dateipfade und kein Dokumentvolume. Der Worker scannt einen Byte-Snapshot im Speicher. Er prüft dessen Quarantäne-Hash nach dem Scan erneut und veröffentlicht exakt denselben Snapshot atomar nach `_originals/`. Freigegebene Originale haben Modus `0400`; Quarantänedateien `0600`, private Verzeichnisse `0700`. Der gesamte Datenbaum bleibt ausschließlich für den App-Benutzer zugänglich. Jede Originalausgabe und jede Weiterverarbeitung prüft Sicherheitsstatus und Hash erneut. Kein statischer Webserver darf `/data` oder Teilbäume ausliefern. Kein externes Tool darf Dateien dort austauschen. Ein kompromittierter App-/Hostbenutzer mit DB- und Dateisystemschreibrecht liegt außerhalb dieser Schutzgrenze.

Parser, Agenten-Claims, fachliches Speichern, Textextraktion, Rendering und Materialisierung der Monats-/Eingangsablage sind vor der Freigabe gesperrt. Extraktion und Rendering laufen in separaten Prozessen mit 768 MiB Adressraum, 20 CPU-Sekunden, 30 Sekunden Walltime, ohne Core-Dumps; maximal 500 PDF-Seiten und 25 Megapixel. XML bleibt `defusedxml` mit verbotenen DTDs, Entitäten und externen Referenzen. Das ist **kein vollständiger OS-Sandbox-Ersatz**: nicht privilegiert betreiben, keine unnötigen Hostmounts/Geheimnisse, Container-/Parserupdates weiter pflegen.

Nicht freigegebene Dokumente liefern über REST/MCP nur sichere Metadaten, Sicherheitsstatus, Fehler, Herkunft und Scan-Audit; alte Ausleseergebnisse und Revisionen werden verborgen. Direkte Original-, Text- und Seitenendpunkte antworten mit HTTP 423. Identische Uploads führen auf den bestehenden, gegebenenfalls gesperrten Datensatz zurück. IMAP verbucht UID-Fortschritt erst nach dauerhafter Datei **und** Herkunft/Importidentität; Wiederabruf/UIDVALIDITY-Wechsel erzeugt keine neuen Dokumentkopien und verliert keine Funde.

Paketvorschau weist Sicherheitsfälle vor fachlichen Ausschlüssen/Nachtragsvergleichen aus. IMAP-Fehler erscheinen zusätzlich unter `blocked_imports`. Neue Pakete enthalten nur freigegebene Originale. Bereits gebaute ZIPs und Mailteile werden nie umgeschrieben. Sobald ein enthaltenes Dokument nicht mehr freigegeben ist, sperren dynamische Gates Paketdownload, Versandvorbereitung und jeden weiteren SMTP-Teil. Die Prüfung erfolgt auch unmittelbar vor der SMTP-Übergabe. Bereits an SMTP übergebene Bytes können selbstverständlich nicht zurückgerufen werden. Dokumentdetails nennen betroffene Paket-/Versand-IDs (`security_impact`), Paketdetails `security_blocked`.

## ClamAV betreiben

ClamAV **1.5.5**, GPL-2.0, stabiles offizielles Release, Image mit Digest in `compose.yaml` gepinnt. Quellen: [Cisco-Talos Release](https://github.com/Cisco-Talos/clamav/releases/tag/clamav-1.5.5), [Docker Hub Tag](https://hub.docker.com/r/clamav/clamav/tags?name=1.5.5), [offizielle Konfigurationsvorlage](https://github.com/Cisco-Talos/clamav/blob/clamav-1.5.5/etc/clamd.conf.sample). Bei Versionsupdates Scanlimits, Heuristikantworten und echte Integrationstests erneut prüfen.

- Separater Compose-Service `clamav`, kein veröffentlichter Scanner-Port, kein Dokumentmount; ausschließlich interne App-Verbindung zu Port 3310.
- Persistentes Volume `clamav-signatures`; `freshclam` prüft 24-mal täglich. Nur Signatur-/Softwareupdates gehen nach außen, **keine Dokumentinhalte**. DNS/HTTPS zu den ClamAV-Updatequellen zulassen.
- Maximal zulässiges Signaturalter: **48 Stunden** (`CLAMAV_MAX_SIGNATURE_AGE=172800`, Sekunden). Gleicher Wert für App und Healthcheck. Systemuhren müssen stimmen, Scanner läuft in UTC.
- Containerlimit **3 GiB RAM / 2 CPUs**. Für den Gesamtstack mindestens etwa **6 GiB RAM**, CPU und ausreichend Platz für Daten, Backups und Signaturen vorsehen. Signaturreloads können vorübergehend deutlich mehr RAM als der Ruhezustand brauchen. OOM/Reload-Ausfälle bleiben geschlossen; Logs/Healthcheck überwachen.
- `StreamMaxLength`/`MaxFileSize`: **25 MiB**, Uploadlimit höchstens 25 MiB; `MaxScanSize`: 100 MiB, Rekursion 16, höchstens 1000 enthaltene Dateien. `MaxScanTime`: 45 Sekunden, Clienttimeout standardmäßig 60 Sekunden. Uploadlimit kann verkleinert, aber nicht ohne Code-/Konfigurationsprüfung vergrößert werden.
- Zwei Scannerthreads, Queue vier; zwei App-Worker. Keine zufälligen separaten Scanprozesse pro Upload. Bei Last warten weitere dauerhafte Importfälle sicher auf Verarbeitung.
- Healthcheck prüft clamd-Bereitschaft und geladenes Signaturalter, Initialisierung bis zehn Minuten. App bleibt bei Scannerstörungen für Metadaten/Fehlerbehebung erreichbar; **keine Fallback-Freigabe**, auch wenn App-Health grün ist.

```sh
docker compose ps
docker compose logs --tail=100 clamav worker
docker compose exec -T app python scripts/clamav_smoke.py
```

Der Smoke sendet ausschließlich eine harmlose Zeichenfolge und den ungefährlichen EICAR-Antivirustest per INSTREAM, ohne EICAR-Datei auf Disk. Nicht mit echter Malware testen. Der Scanner übermittelt keine Rohdateien, Dateinamen oder Zugangsdaten in App-Logs; Scan-Audit speichert Dokument-ID, Hash, Engine-/Signaturstand, Signaturname, Ergebnis und Zeitpunkte.

## Update, Backup, Restore, Aufbewahrung

Vor erstmaligem Upgrade von einem Stand ohne Scans: konsistent sichern und **App/Worker stoppen**, Migrationen offline ausführen und `prepare_security` ausführen, erst dann beide Dienste starten. Der normale Webstart führt dies ebenfalls idempotent aus; bei laufendem alten Worker nicht im Rolling-Update migrieren. Bestehende Dokumente erhalten `pending`, werden in Quarantäne kopiert, aus materialisierten Fachordnern entfernt und neu geprüft. Bestehende Pakete bleiben bytegleich, aber bis zur erfolgreichen Prüfung ihrer Originale gesperrt.

Backup sichert Datenbank samt Audit und **gesamtes** Dokumentvolume einschließlich Quarantäne/Transferzuständen. Das Signaturvolume ist ein Cache und darf über freshclam neu aufgebaut werden. `restore.sh` migriert, stellt Quarantänetrennung/Rechte her, prüft Hashes und übernimmt `clean` nur mit passendem Hash und passendem abgeschlossenen Scan-Audit. Bei fehlendem vertrauenswürdigem Status erfolgt eine erneute Prüfung; Parser/Downloads bleiben bis dahin gesperrt. Abgebrochene Scans werden nach Lease-Ablauf wiederaufgenommen. Backups dürfen keine Quarantäne auslassen und gehören verschlüsselt außerhalb des Servers aufbewahrt.

**Aufbewahrungsregel dieser Version:** keine automatische Quarantänelöschung, auch nicht nach Fund. Originale und Quarantänekopie werden solange wie der fachliche Datensatz bzw. ein zugehöriger Snapshot benötigt wird aufbewahrt. Technische Transferreste können nach sieben Tagen und nach Prüfung auf unvollständige Importtickets offline entfernt werden. Für Funde/Fehler legt der Betreiber eine dokumentierte, datenschutzkonforme Frist und einen berechtigten Verantwortlichen fest (empfohlene Fallprüfung spätestens nach 30 Tagen). Löschen nur als explizite administrative Datenbereinigung nach Backup-/Nachweisprüfung, niemals durch Öffnen oder Ausführen; Dokument-/Import-ID, Hash, Grund und Zeitpunkt im Betriebsprotokoll festhalten. Auch Sicherungen und vorbereitete Mailteile unterliegen der beschlossenen Löschfrist. Das Entfernen einer Datei darf **keinen** Sicherheitsstatus auf `clean` setzen; fehlende Bytes bleiben ein sichtbarer Integritätsfehler. Es gibt in dieser Version bewusst keinen Benutzer-„Freigeben trotz Fund“- oder automatischen Bereinigungsendpunkt.

## Tests

```sh
uv run pytest -q                         # simulierte Scannerantworten + Regression
# Separates echtes clamd mit docker/clamav/clamd.conf, frischen Signaturen:
RUN_CLAMAV_TESTS=1 CLAMAV_HOST=127.0.0.1 CLAMAV_PORT=13310 uv run pytest -q -m clamav
```

Echte Tests prüfen INSTREAM, PDF/Bild/CAMT, EICAR über REST, den tatsächlichen MCP-Transport und IMAP, verschlüsselte PDF sowie überschrittene Streamlimits. Service-Tests ergänzen Ausfall, Timeout, veraltete Signaturen, Heuristiklimits, nicht eindeutige Antworten, Zustands-/Zugriffssperren, Wiederaufnahme, identische Reimporte, Manipulation während/nach Scan und spätere Paketsperren ohne Snapshotänderung. CI startet den gepinnten Scanner mit Produktionskonfiguration; Compose-Smoke prüft außerdem, dass weder Scanner-Port noch Dokumentvolume öffentlich/mit dem Scanner geteilt werden. Browser-Smoke prüft die Quarantäneanzeige mit EICAR.

Malwareprüfung ist eine zusätzliche Schutzschicht, **keine Garantie ungefährlicher Dokumente** und kein Ersatz für Typ-/Größenlimits, sichere XML-Konfiguration und isolierte, ressourcenbegrenzte Parser.
