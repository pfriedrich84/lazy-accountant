# Betrieb, Wartung, Backup und Wiederherstellung

## Dienste und Persistenz

- `app`: Django/DRF, gebautes React-SPA, Django Admin, offizieller MCP-ASGI-Mount. Ein Uvicorn-Prozess; kein Node-Server im Betrieb.
- `worker`: dieselbe Codebasis, separater Django-Q2-Cluster mit zwei Workern; ORM-Broker in PostgreSQL.
- `db`: PostgreSQL 18.7, nur im Compose-Netz, benanntes Volume unter `/var/lib/postgresql` (Layout von PostgreSQL 18).
- `mail-test`: ausschließlich optionales Profil `test-mail`, GreenMail 2.1.15 mit **synthetischen** Testzugängen und loopbackgebundenen Ports. Nicht für echte Firmenpost verwenden.

### Dokumentvolume und späterer Netzwerkspeicher

Die Dokumentablage ist das **benannte Docker-Volume `documents`**, gemeinsam an `/data` in App und Worker eingebunden. Docker legt es automatisch mit dem Stack-Projektpräfix an (standardmäßig `lazy-accountant_documents`). Das Image liefert das leere Verzeichnis mit Eigentümer `1000:1000` und Modus `0700`; beim erstmaligen Befüllen des lokalen Volumes übernimmt Docker diese Rechte. App und Worker laufen fest als `1000:1000`, unabhängig vom Hostbenutzer. Keine Hostordneranlage und kein privilegierter Init-Container nötig; der App-Einstieg verweigert UID 0. `init-env.py` erzeugt ausschließlich die private Konfiguration. Alte Variablen `DOCUMENTS_ROOT`, `APP_UID` und `APP_GID` werden von Compose nicht mehr verwendet.

Der Host-Port `HTTP_PORT` (Standard `8000`) wird standardmäßig über `HTTP_BIND=0.0.0.0` veröffentlicht. Zugriff nur aus dem vorgesehenen privaten Netz zulassen und tatsächliche Server-IP/Hostnamen in den Host-/Origin-Allowlisten konfigurieren. Für ausschließlich lokalen Zugriff `HTTP_BIND=127.0.0.1` setzen. PostgreSQL bleibt unveröffentlicht.

```text
/data/  (Dokumentvolume)
  <eindeutiger-Firmenordner>/YYYY/MM/{ER,AR,Bankkonto,Wertpapiere}/
  _originals/    unveränderliche führende Originaldateien
  _inbox/       noch nicht vollständig zugeordnete Eingänge
  _packages/    unveränderliche ZIP-Snapshots
  _dispatches/  vorbereitete, prüfsummenbehaftete Mailteile
  _uploads/     noch nicht abgeschlossene authentifizierte Transfers
  _rejected/    erhaltene nicht unterstützte Mailanhänge
```

Das Volume bleibt bei Container-Neubau, Neustart und normalem `docker compose down` erhalten. **`docker compose down -v` oder das Löschen des Volumes entfernt die gespeicherten Daten.** Kein Backupersatz.

Für einen späteren Netzwerk-Mount ein geeignetes Docker-Volume mit NFS-/CIFS-Treiberoptionen auf dem Docker-Host/Dockhand vorbereiten. Beispielsweise kann die bestehende Definition durch ein bereits eingerichtetes externes Volume ersetzt werden:

```yaml
volumes:
  documents:
    external: true
    name: lazy-accountant-documents-netzwerk
```

App und Worker behalten `documents:/data`. Der Netzwerkpfad muss für UID/GID `1000:1000` mit privaten Rechten nutzbar sein; Schreib-/Rename-/Sync-Verhalten und Ausfälle mit dem konkreten NAS gesondert prüfen. Dies ist keine behauptete NFS-/CIFS-Live-Abnahme. PostgreSQL bleibt auf seinem separaten lokalen Volume.

**Bestehende Ablage nicht einfach umhängen:** Vor dem Wechsel vom früheren Host-Bind-Mount oder auf ein neues Netzwerkvolume mit der alten Konfiguration ein gemeinsames Backup erstellen, App/Worker stoppen und erst dann Konfiguration wechseln. Das neue Volume ist zunächst leer; der frühere Hostordner wird nicht automatisch importiert. Neues Image nur bauen (`docker compose build app`), dann über `scripts/restore.sh` den gesicherten Datenbank-/Dateistand gemeinsam in die neue Konfiguration zurückspielen und Integrität prüfen, bevor normal gearbeitet wird. Alten Speicher und Notfallbackup bis zur erfolgreichen Prüfung behalten. Bei bestehenden `.env` für LAN-Zugriff zusätzlich den bisherigen Loopback-Wert von `HTTP_BIND` bewusst anpassen.

Keine dieser Dateien wird direkt als öffentlicher Webpfad freigegeben. Downloads laufen nur über berechtigte Dokument-/Paket-IDs. Pfade werden serverseitig aus validierten Zuordnungen erzeugt; Originaldateinamen bleiben zusätzlich in den Metadaten erhalten. Niemals Originale oder Paketdateien extern umbenennen/überschreiben.

Datenbank- und Dokumentvolume sind **ein gemeinsamer Datenbestand**. Dateien allein sind kein vollständiges Backup, ein Datenbankdump allein ebenfalls nicht. Die `.env`/der `DJANGO_SECRET_KEY` sind zusätzlich erforderlich, insbesondere zum Entschlüsseln der Mailpasswörter. Schlüsselrotation erfordert zuvor einen kontrollierten Neuverschlüsselungsablauf oder erneute Eingabe der Mailzugänge.

## Queue, Wiederanlauf und Status

Django-Q2: Jobtimeout **300 s**, Broker-Retry **420 s**, eine automatische Ausführung bei fachlich fehlgeschlagenen Jobs (`max_attempts=1`, `ack_failures=true`), kleine Fetch-Batches. Fachliche `Job`-/`Dispatch`-/`SendAttempt`-Datensätze und Zeilensperren schützen zusätzliche Side Effects. Eine doppelte Queuezustellung ist kein Anlass, einen bereits laufenden/erledigten fachlichen Auftrag doppelt auszuführen.

Nicht abgeschlossene physische Ablagen erscheinen mit Status/Fehler direkt im Dokument. Sie werden nicht als erfolgreich abgelegt behauptet; die Paketvorschau schließt sie bis zur journalisierten Reparatur ausdrücklich aus.

Eine technische Wartung läuft minütlich über den Q2-Scheduler. Sie repariert ausstehende Dateiablageoperationen, veröffentlicht dauerhaft gespeicherte, noch nicht in den Broker gelangte Aufträge und behandelt verwaiste Aufträge. **Das Postfach wird nicht minütlich abgefragt:** ausdrücklich aktivierte IMAP-Postfächer werden einmal pro Nacht ab **03:00 Uhr Europe/Vienna** gestartet. Ein eindeutiger Schlüssel pro Firma/lokalem Datum verhindert weitere Starts derselben Nacht, auch nach Neustart oder bei mehreren Wartungsläufen. Das Startfenster reicht bis 03:59 Uhr; ist der Dienst in dieser ganzen Stunde aus, wartet der automatische Start bis zur nächsten Nacht. Sommer-/Winterzeit richtet sich nach der Wiener Ortszeit. Ein aktiver IMAP-Auftrag wird nicht parallel erneut gestartet. Manueller Abruf bleibt jederzeit möglich. **Kein Monats-/KI-Lauf wird dadurch terminiert**; der Monatsstart kommt von Orca/dem Agenten.

- IMAP-TLS prüft System-Vertrauensanker und den konfigurierten Serverhostnamen ausdrücklich. Ungültige/unbekannte Zertifikate werden nicht stillschweigend akzeptiert; für interne eigene CAs den System-Truststore kontrolliert erweitern. SMTP-STARTTLS/TLS verwendet den verifizierenden Kontext des Django-Mail-Backends.
- IMAP: Abruf maximal 20 Nachrichten pro Job, Sockettimeout 20 s, readonly, kein Löschen/Verschieben. Postfach/Ordner/UIDVALIDITY/UID/Anhang sowie stabile Nachrichten-/Anhangshashes schützen Wiederholungen. Cursor erst nach allen dauerhaften Dateien/Herkunfts-/Fehlerdatensätzen einer Nachricht erhöhen. Verbleibende Nachrichten werden im Ergebnis ausgewiesen. Beim nächtlichen Import werden nach erfolgreichem Fortschritt weitere begrenzte Teilaufträge dauerhaft eingeplant, bis der Rückstand des ersten erfolgreichen Teilabrufs abgearbeitet ist. Dessen höchste UID begrenzt die Folgeaufträge: später eintreffende Mails warten bis zum nächsten Nachtlauf. Ein Wechsel der UIDVALIDITY während der Teilaufträge stoppt den Lauf sichtbar statt die alte UID-Grenze auf einen anderen Nachrichtenbestand anzuwenden. Ein bereits begonnener Nachtlauf darf dabei über das Startfenster hinauslaufen. Es ist ein zusammenhängender Nachtimport, kein regelmäßiges Polling tagsüber. Abschalten des Postfachs verhindert weitere automatische Teilaufträge. Bei Fehler oder fehlendem Fortschritt stoppt die Kette mit sichtbarem Jobstatus/Restbestand statt einer Endlosschleife. Manuelle Abrufe bleiben einzelne Teilabrufe mit explizitem Fortsetzen.
- Unterbrochene IMAP-/Paketaufträge werden sicher fortsetzbar. Explizites Fortsetzen in UI/MCP; stale technische Jobs nach 480 s wieder aufnehmen.
- SMTP: Vor I/O Status `sending` dauerhaft speichern. Verbindungsvorbereitung/Ablehnung ist `failed`; ein Abbruch nach Versandbeginn ist konservativ `unknown`. Ein Worker-Neustart kann keine unkontrollierte Wiederholung auslösen. `unknown` manuell mit Mailserver/Gesendet-Protokoll abgleichen. **Kein blindes Retry**. Ein weiterer Versand derselben Paketversion braucht expliziten neuen Dispatch mit `resend_of`.
- Einzelne abgelehnte Empfänger und unvollständige Mailteile sind `partial`. `accepted` ist lediglich SMTP-Annahme, **keine Zustellbestätigung**.

Healthchecks: App prüft Datenbankzugriff; Worker prüft aktuellen Q2-Clusterstatus desselben Containers über einen prozessübergreifenden Django-Dateicache unter `/tmp`. Dieser Cache ist keine Queue und muss nicht gesichert werden.

```sh
docker compose ps
docker compose logs --tail=100 app worker
docker compose exec app python backend/manage.py verify_integrity --repair
```

Die Integritätsprüfung kontrolliert führende Originale, physische Zuordnung, alle vier Monatsordner, ZIP-/Snapshot-Prüfsummen, Mailteile und erhaltene Fehleranhänge. `--repair` führt ausschließlich das bestehende Dateioperationsjournal erneut aus; keine heuristischen Metadatenänderungen und kein Versand.

## Ressourcenlimits

Standardmäßig 25 MiB pro Original (`MAX_FILE_BYTES`) und 256 MiB summierte Originalbytes pro Paket (`MAX_PACKAGE_BYTES`). Die Paketvorschau nennt das Verarbeitungsgrößenlimit; eine Überschreitung bricht vor dem Erzeugen eines Snapshot-Datensatzes mit sichtbarem Fehler ab, ohne Originale zu verlieren. Bei Bedarf weniger Monate wählen oder das Paketlimit bewusst zusammen mit Arbeitsspeicher/Jobtimeout anpassen: Der ZIP-Bau hält Originale und Ausgabebytes aktuell im Worker-Speicher. Bilder über 25 Megapixel bleiben als Original erhalten, werden aber nicht automatisch decodiert/freigegeben; Bild-/PDF-Vorschauen haben maximal 2000 Pixel Kantenlänge. MIME-Größen werden mit echten SMTP-CRLF-Bytes gemessen, Mailteile vor dem Versand erneut gehasht.

## Große E-Mails

Das konfigurierte Limit bezieht sich auf die **vollständige MIME-Nachricht** einschließlich Base64, Kopfzeilen und Gesamtinhaltsliste. Die Vorbereitung misst die tatsächlich erzeugten Nachrichten. Ein zu kleines Limit erzeugt einen sichtbaren Fehler statt eines abgeschnittenen Pakets.

Ein kleines Paket wird als `paket.zip` angehängt. Große Pakete werden als `paket.zip.part0001`, `…0002`, … binär aufgeteilt; jede Nachricht enthält eine `Gesamtinhaltsliste.json` mit Gesamt-/Teilprüfsummen und Dokumentdateiverweisen. Ein einzelner Teil ist kein eigenständiges ZIP.

Linux/macOS:

```sh
cat paket.zip.part* > paket.zip
sha256sum paket.zip
```

PowerShell (Teile nur einmal und im richtigen Verzeichnis ablegen):

```powershell
$out = [System.IO.File]::Create((Join-Path $PWD 'paket.zip'))
try {
  Get-ChildItem 'paket.zip.part*' | Sort-Object Name | ForEach-Object {
    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
    $out.Write($bytes, 0, $bytes.Length)
  }
} finally { $out.Dispose() }
Get-FileHash paket.zip -Algorithm SHA256
```

Gesamt-SHA256 mit der Inhaltsliste vergleichen, danach ZIP entpacken. Bei fehlenden Teilen nicht mit einem unvollständigen Paket weiterarbeiten.

## Konsistente Offline-Sicherung

Vor produktiver Nutzung Speicherplatz, externe verschlüsselte Sicherung und regelmäßigen Restore-Test einrichten. Die Skripte benötigen Docker Compose und laufen aus dem Repository. Keine Zugangsdaten als Parameter übergeben.

```sh
sh scripts/backup.sh backups/2026-11-18
```

Das Skript stoppt **beide schreibenden Dienste**, wartet deren geordnetes Ende ab (`stop_grace_period: 6m`), führt Journalreparatur/Integritätsprüfung aus und sichert:

1. PostgreSQL als Custom-Dump (`database.dump`).
2. Das gesamte Dokumentvolume einschließlich Eingang, Originalen, Ordnern, Paketständen und Mailteilen (`documents.tar`); die Sicherung arbeitet innerhalb von `/data` und hängt nicht von einem Hostpfad ab.
3. `.env` mit benötigtem Schlüssel (`environment.env`, private Rechte).
4. Formatbeschreibung und SHA256-Dateiliste.

Danach startet es App/Worker wieder. Ein währenddessen fehlschlagender Backup-Lauf darf nicht als vollständige Sicherung archiviert werden. Die Sicherung enthält vertrauliche Firmendaten **und Geheimnisse**; nicht in Git oder CI-Artefakte aufnehmen, extern verschlüsseln und getrennt vom Server aufbewahren. Das optionale Test-Mailpostfach ist bewusst nicht Teil des Anwendungsbackups.

## Gemeinsame Wiederherstellung

**Ersetzt die aktuelle Datenbank und die gesamte aktuelle Dokumentablage.** Zuerst deren zusätzlichen Notfall-Backupstand sichern. Für einen neuen Host den gleichen Code-/Containerstand bereitstellen, `.env` aus sicherer Quelle wiederherstellen und gegebenenfalls Volume-Definition und interne Adresse anpassen. `DJANGO_SECRET_KEY` muss zum Backup passen; das Skript prüft dies vor Änderungen.

```sh
sh scripts/restore.sh backups/2026-11-18 --yes-replace
```

Ablauf: SHA256 prüfen → App/Worker stoppen → Datenbank wiederherstellen → sicheren Dateibaum wiederherstellen → Journal/Integrität prüfen → verwaiste Aufträge sicher behandeln → App/Worker starten und Healthchecks abwarten. Archive mit Pfadausbruch, Symlinks oder Spezialdateien werden abgelehnt. Bei Fehler bleibt die Anwendung bewusst offline, statt mit halb wiederhergestellten Daten zu starten.

Laufende Aufträge des alten Prozesses können keinen gültigen Lease behalten. SMTP-Aufträge mit unbekanntem Ausgang bleiben ungeklärt; Wiederherstellung ist **kein autorisierter Neuversand**. Nach Restore Paket- und Versandstände vergleichen und die tatsächliche Orca-Verbindung/Mailzugänge gesondert prüfen.

## Einrichtungs-/Live-Abnahme

Noch kundenspezifisch: private Serveradresse und gegebenenfalls späteres Netzwerkvolume, reale Firmen/Konten/Depots/Kategorien, IMAP-/SMTP-Anbieter/Ordner/Importbeginn/TLS, Absender/Empfänger/Größenlimits, Versandregel bei offenen Punkten, repräsentative anonymisierte Originale und Orca-MCP-Konfiguration/Termin. Keine echten Geheimnisse in Issues oder Git ablegen. Synthetische Tests ersetzen diese Live-Abnahme nicht.
