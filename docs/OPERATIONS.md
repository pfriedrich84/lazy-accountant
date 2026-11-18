# Betrieb, Wartung, Backup und Wiederherstellung

## Dienste und Persistenz

- `app`: Django/DRF, gebautes React-SPA, Django Admin, offizieller MCP-ASGI-Mount. Ein Uvicorn-Prozess; kein Node-Server im Betrieb.
- `worker`: dieselbe Codebasis, separater Django-Q2-Cluster mit zwei Workern; ORM-Broker in PostgreSQL.
- `db`: PostgreSQL 18.7, nur im Compose-Netz, benanntes Volume unter `/var/lib/postgresql` (Layout von PostgreSQL 18).
- `mail-test`: ausschließlich optionales Profil `test-mail`, GreenMail 2.1.15 mit **synthetischen** Testzugängen und loopbackgebundenen Ports. Nicht für echte Firmenpost verwenden.

`DOCUMENTS_ROOT` ist ein echter Host-Bind-Mount. Eigentümer `APP_UID:APP_GID` muss darin schreiben dürfen; `scripts/init-env.py` übernimmt die lokale Benutzer-/Gruppen-ID und legt den Pfad an. Ein fehlender Hostpfad wird bewusst nicht von Docker als root angelegt (`create_host_path: false`). Auf einem anderen Host UID/GID/Pfad prüfen.

```text
<DOCUMENTS_ROOT>/
  <eindeutiger-Firmenordner>/YYYY/MM/{ER,AR,Bankkonto,Wertpapiere}/
  _originals/    unveränderliche führende Originaldateien
  _inbox/       noch nicht vollständig zugeordnete Eingänge
  _packages/    unveränderliche ZIP-Snapshots
  _dispatches/  vorbereitete, prüfsummenbehaftete Mailteile
  _uploads/     noch nicht abgeschlossene authentifizierte Transfers
  _rejected/    erhaltene nicht unterstützte Mailanhänge
```

Keine dieser Dateien wird direkt als öffentlicher Webpfad freigegeben. Downloads laufen nur über berechtigte Dokument-/Paket-IDs. Pfade werden serverseitig aus validierten Zuordnungen erzeugt; Originaldateinamen bleiben zusätzlich in den Metadaten erhalten. Niemals Originale oder Paketdateien extern umbenennen/überschreiben.

Datenbank- und Dokumentvolume sind **ein gemeinsamer Datenbestand**. Dateien allein sind kein vollständiges Backup, ein Datenbankdump allein ebenfalls nicht. Die `.env`/der `DJANGO_SECRET_KEY` sind zusätzlich erforderlich, insbesondere zum Entschlüsseln der Mailpasswörter. Schlüsselrotation erfordert zuvor einen kontrollierten Neuverschlüsselungsablauf oder erneute Eingabe der Mailzugänge.

## Queue, Wiederanlauf und Status

Django-Q2: Jobtimeout **300 s**, Broker-Retry **420 s**, eine automatische Ausführung bei fachlich fehlgeschlagenen Jobs (`max_attempts=1`, `ack_failures=true`), kleine Fetch-Batches. Fachliche `Job`-/`Dispatch`-/`SendAttempt`-Datensätze und Zeilensperren schützen zusätzliche Side Effects. Eine doppelte Queuezustellung ist kein Anlass, einen bereits laufenden/erledigten fachlichen Auftrag doppelt auszuführen.

Eine technische Wartung läuft minütlich über den Q2-Scheduler. Sie repariert ausstehende Dateiablageoperationen, veröffentlicht dauerhaft gespeicherte, noch nicht in den Broker gelangte Aufträge, behandelt verwaiste Aufträge und pollt ausdrücklich aktivierte IMAP-Postfächer. **Kein Monatslauf wird dadurch terminiert**; der Monatsstart kommt von Orca/dem Agenten.

- IMAP: Abruf maximal 20 Nachrichten pro Job, Sockettimeout 20 s, readonly, kein Löschen/Verschieben. Postfach/Ordner/UIDVALIDITY/UID/Anhang sowie stabile Nachrichten-/Anhangshashes schützen Wiederholungen. Cursor erst nach allen dauerhaften Dateien/Herkunfts-/Fehlerdatensätzen einer Nachricht erhöhen. Verbleibende Nachrichten werden im Ergebnis ausgewiesen; weitere Abrufe sind möglich.
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
2. Den gesamten Bind-Mount einschließlich Eingang, Originalen, Ordnern, Paketständen und Mailteilen (`documents.tar`).
3. `.env` mit benötigtem Schlüssel (`environment.env`, private Rechte).
4. Formatbeschreibung und SHA256-Dateiliste.

Danach startet es App/Worker wieder. Ein währenddessen fehlschlagender Backup-Lauf darf nicht als vollständige Sicherung archiviert werden. Die Sicherung enthält vertrauliche Firmendaten **und Geheimnisse**; nicht in Git oder CI-Artefakte aufnehmen, extern verschlüsseln und getrennt vom Server aufbewahren. Das optionale Test-Mailpostfach ist bewusst nicht Teil des Anwendungsbackups.

## Gemeinsame Wiederherstellung

**Ersetzt die aktuelle Datenbank und die gesamte aktuelle Dokumentablage.** Zuerst deren zusätzlichen Notfall-Backupstand sichern. Für einen neuen Host den gleichen Code-/Containerstand bereitstellen, `.env` aus sicherer Quelle wiederherstellen und gegebenenfalls Hostpfad/UID/GID/interne Adresse anpassen. `DJANGO_SECRET_KEY` muss zum Backup passen; das Skript prüft dies vor Änderungen.

```sh
sh scripts/restore.sh backups/2026-11-18 --yes-replace
```

Ablauf: SHA256 prüfen → App/Worker stoppen → Datenbank wiederherstellen → sicheren Dateibaum wiederherstellen → Journal/Integrität prüfen → verwaiste Aufträge sicher behandeln → App/Worker starten und Healthchecks abwarten. Archive mit Pfadausbruch, Symlinks oder Spezialdateien werden abgelehnt. Bei Fehler bleibt die Anwendung bewusst offline, statt mit halb wiederhergestellten Daten zu starten.

Laufende Aufträge des alten Prozesses können keinen gültigen Lease behalten. SMTP-Aufträge mit unbekanntem Ausgang bleiben ungeklärt; Wiederherstellung ist **kein autorisierter Neuversand**. Nach Restore Paket- und Versandstände vergleichen und die tatsächliche Orca-Verbindung/Mailzugänge gesondert prüfen.

## Einrichtungs-/Live-Abnahme

Noch kundenspezifisch: private Serveradresse/Hostpfad, reale Firmen/Konten/Depots/Kategorien, IMAP-/SMTP-Anbieter/Ordner/Importbeginn/TLS, Absender/Empfänger/Größenlimits, Versandregel bei offenen Punkten, repräsentative anonymisierte Originale und Orca-MCP-Konfiguration/Termin. Keine echten Geheimnisse in Issues oder Git ablegen. Synthetische Tests ersetzen diese Live-Abnahme nicht.
