# Lazy Accountant – Funktionskatalog und Umsetzungsplan

Stand: 18. November 2026. Status: vereinbarte Anforderungen und Umsetzungsvorschlag; noch keine Implementierung.

## 1. Ziel und Ausgangslage

Eine schlanke, selbst betriebene Webanwendung sammelt Rechnungen, Bank- und Depotunterlagen je Firma, strukturiert sie und verschickt ein vollständiges Paket an die Steuerberatung. Alle wesentlichen Abläufe sollen auch über einen eigenen MCP-Server automatisierbar sein. Deployment erfolgt mit Docker Compose.

Heute entstehen einmalige und wiederkehrende Rechnungen in Invoice Ninja. Für den ersten nutzbaren Stand werden diese Rechnungen einfach als endgültige PDFs hochgeladen oder per E-Mail eingelesen. Eine Invoice-Ninja-Integration ist dafür nicht erforderlich. Eigene Rechnungserstellung und wiederkehrende Rechnungen sind der nächste Ausbau; Projektzeiterfassung und monatliche Leistungsabrechnung folgen später.

Die erste Version bereitet Unterlagen vor. Sie benötigt weder eine vollständige Finanzbuchhaltung noch einen BMD-Buchungsimport. Die Steuerberatung erhält zunächst Originaldateien und strukturierte Übersichten.

## 2. Funktionskatalog

| ID | Funktion | Erste Version / später |
| --- | --- | --- |
| F01 | Mehrere Firmen mit getrennten Dokumenten, Konto-/Depotzuordnungen, Mailkonfiguration und Steuerberater-Empfängern | Erste Version |
| F02 | Ausgangsrechnungen und Stornos als bereits ausgestellte PDFs importieren; Rechnungsnummer und Original erhalten | Erste Version |
| F03 | Eingangsrechnungen und sonstige Belege als PDF, JPG und PNG einzeln oder gesammelt hochladen | Erste Version |
| F04 | Belege auslesen und strukturieren; Lieferant/Kunde, Nummer, Datum, Beträge, Währung und Kategorie korrigierbar erfassen | Erste Version |
| F05 | Kontoauszüge als CAMT-XML und PDF importieren, Konto und Auszugszeitraum zuordnen; beide Originalformate erhalten | Erste Version |
| F06 | Wertpapierbewegungen als PDF importieren und Firma, Depot und Zeitraum zuordnen | Erste Version |
| F07 | Dokumente suchen, filtern, kommentieren, prüfen und umklassifizieren; Dubletten erkennen | Erste Version |
| F08 | Anhänge aus konfigurierten E-Mail-Postfächern über IMAP einlesen und in eine Eingangsablage übernehmen | Erste Version |
| F09 | Vollständiges Übergabepaket je Firma und Zeitraum mit Vorschau, Übersicht und Originaldateien erzeugen | Erste Version |
| F10 | Übergabepaket per SMTP versenden; Paketinhalt und Versandversuche nachvollziehbar speichern | Erste Version |
| F11 | Eigener MCP-Server für Dokumente, Mailimport, Prüfung, Paketerstellung und Versand | Erste Version |
| F12 | Nachgereichte oder korrigierte Unterlagen als nachvollziehbaren Nachtrag zu einer früheren Übergabe behandeln | Erste Version |
| F13 | CAMT-Bewegungen mit Rechnungen/Belegen abgleichen und fehlende Belege anzeigen | Nächster Ausbau |
| F14 | Kunden und Leistungen verwalten; eigene Rechnungsentwürfe, endgültige PDFs, Stornos und SMTP-Rechnungsversand | Nächster Ausbau |
| F15 | Wiederkehrende Rechnungen mit Intervall, Zeitraum, Vorlagen und konfigurierbarem Versand | Nächster Ausbau |
| F16 | Projekte, Tätigkeiten, Zeiten und Verrechnungssätze erfassen | Später |
| F17 | Monatlich noch nicht verrechnete Projektleistungen zu Rechnungsentwürfen zusammenfassen; Abrechnungsstand führen | Später |
| F18 | BMD-/RZL-Export und strukturierte E-Rechnungen nach konkretem Bedarf | Später |

## 3. Dokumente und Verarbeitung

Dokumentarten: Ausgangsrechnung, Ausgangsstorno, Eingangsrechnung, Eingangsgutschrift, sonstiger Beleg, Kontoauszug PDF, Kontoauszug CAMT und Wertpapierbewegung PDF.

Gemeinsame Angaben: Firma, Dokumentart, Originaldateiname, interne ID, Herkunft, Importzeitpunkt, Beleg-/Auszugsdatum, zugeordneter Übergabezeitraum, Prüfstatus, Kategorie und Notiz. Konto- und Depotunterlagen tragen zusätzlich ein Konto bzw. Depot und einen Zeitraum. Rechnungsfelder bleiben für andere Dokumentarten optional.

- Originaldateien werden unverändert und mit Prüfsumme gespeichert. Metadaten und Ausleseergebnisse sind davon getrennt.
- Dokumentdatum und Übergabezeitraum sind getrennte Felder. Importierte Ausgangsrechnungen werden nicht neu nummeriert oder neu aufgebaut.
- CAMT und PDF desselben Auszugs können verknüpft werden; beide bleiben im Paket. Der reine CAMT-Import setzt keinen automatischen Bankabgleich voraus.
- Wertpapierbewegungen benötigen zunächst PDF-Ablage und Zuordnung. Automatische Transaktionsauswertung oder Steuerberechnung ist kein Abnahmekriterium.
- Automatische Auslese liefert korrigierbare Vorschläge. Unsichere Felder bleiben sichtbar offen; ein Auslesefehler verhindert nicht die sichere Originalablage.
- Dateigleiche Uploads werden per Hash erkannt; ähnliche Rechnungsnummern/Beträge erzeugen einen Dublettenhinweis. Gleiche Beträge allein sind kein Löschgrund.
- Ungeklärte Firma, Dokumentart oder Periode führt in eine Prüfliste. Der Import rät keine endgültige Zuordnung.
- Dokumente sind nach Firma, Zeitraum, Art, Geschäftspartner, Status und Kategorie filterbar.

## 4. E-Mail: IMAP für Eingang, SMTP für Versand

### Eingang über IMAP

Pro Firma werden Postfach, Ordner, Zugang und ein expliziter Importbeginn konfiguriert. Ein dediziertes Belegpostfach oder ein gezielt ausgewählter Ordner ist der Standard. Mehrere Firmen können getrennte Postfächer oder eindeutig konfigurierte Empfänger-/Aliasregeln verwenden.

Anhänge werden in dieselbe Verarbeitung wie manuelle Uploads übernommen. Gespeichert werden Absender, Empfänger, Betreff, Maildatum und technische Herkunft; mehrdeutige Zuordnungen sind prüfbar. Automatische Regeln können Dokumentarten vorschlagen.

Der Abruf läuft regelmäßig im Hintergrund und kann über Oberfläche oder MCP angestoßen werden. Postfach/Ordner, UIDVALIDITY, UID und Anhangsidentität sowie Datei-Hashes verhindern doppelte Verarbeitung. Der Importfortschritt wird erst nach dauerhafter Ablage gespeichert. Ein Neustart oder erneuter Abruf verliert keine Anhänge. Nachrichten werden standardmäßig nicht gelöscht; ein Verschieben nach erfolgreichem Import ist optional konfigurierbar.

Nicht unterstützte oder fehlerhafte Anhänge erscheinen mit Fehlergrund. HTML-Inhalte und Dokumenttexte werden als Daten behandelt, nicht als Anweisungen für Automatisierungen. Datei-, Mengen- und Größenlimits sowie sichere XML-Verarbeitung gehören zum Import.

### Versand über SMTP

Absender, Antwortadresse, SMTP-Zugang, TLS-Einstellungen, Empfänger und Mailvorlagen werden je Firma konfiguriert. In der ersten Version dient SMTP dem Paketversand; später auch Ausgangsrechnungen und Erinnerungen.

Das ZIP wird als Anhang verschickt. Überschreitet das Paket die konfigurierte Mailgröße, wird es in nummerierte Teile mit Gesamtinhaltsliste aufgeteilt; ein unvollständiger Versand wird sichtbar gemeldet. Eine spätere Downloadlink-Variante ist optional.

Eine Versandwarteschlange speichert Empfänger, Paketversion, Message-ID, Versuche und Ergebnis. „Vom SMTP-Server angenommen“ wird von einer bestätigten Zustellung unterschieden. Bei unklarem Ausgang nach Verbindungsabbruch wird kein blinder Neuversand ausgelöst. Erneutes Senden ist eine ausdrückliche Aktion und bleibt protokolliert. Ein optionaler IMAP-Gesendet-Ordner kann eine Kopie erhalten.

## 5. Übergabepaket und Nachträge

| Bestandteil | Inhalt |
| --- | --- |
| Ausgangsrechnungen | Endgültige Original-PDFs einschließlich importierter Stornos |
| Eingangsbelege | Hochgeladene Originaldateien einschließlich Gutschriften |
| Kontoauszüge | CAMT-Originaldateien und PDFs, nach Konto geordnet |
| Wertpapierbewegungen | PDFs, nach Depot geordnet |
| Übersicht | CSV und XLSX mit IDs, Dokumentart, Datum/Zeitraum, Nummer, Geschäftspartner, relevanten Beträgen/Währung und Dateiverweisen |
| Begleitschreiben | Firma, Übergabezeitraum, Hinweise und offene Punkte |
| Inhaltsliste | Alle enthaltenen Dateien mit ID und Prüfsumme; gegebenenfalls Zuordnung zu Mailteilen |

Vor dem Versand zeigt eine Vorschau Dokumentanzahl, Umfang, Zeitraum, Empfänger und ungeklärte bzw. ausgeschlossene Unterlagen mit Grund. Offene Punkte dürfen nicht stillschweigend verschwinden. Ob ein Paket trotz offener Punkte versendet werden darf, ist je Firma bzw. Versandregel festzulegen.

Jede erzeugte Paketversion ist ein unveränderlicher Snapshot. Spätere Metadatenänderungen verändern bereits versendete Pakete nicht. Nachträge verweisen auf das vorherige Paket und benennen neue oder korrigierte Dokumente. Ein Dokument kann in mehreren Paketversionen referenziert werden, ohne dass sein Original dupliziert werden muss.

## 6. MCP und gemeinsame Anwendungsfunktionen

Oberfläche und MCP verwenden dieselben fachlichen Funktionen, Validierungen und Firmenberechtigungen. Der MCP-Server ist ein regulärer Zugangsweg, kein separater Datenbestand. Ziel ist ein authentifizierter Remote-MCP-Zugang über Streamable HTTP; Verbindungen erhalten explizite Firmen- und Funktionsrechte.

Geplante Werkzeuge für die erste Version:

| Werkzeuggruppe | Aktionen |
| --- | --- |
| Firmen und Zuordnungen | Berechtigte Firmen, Konten, Depots und Kategorien auflisten |
| Dokumente | Upload vorbereiten/abschließen, Dokumente auflisten/abrufen, Metadaten und Zuordnungen ändern |
| Verarbeitung | Auslese anstoßen, Vorschläge prüfen/bestätigen, offene Punkte und Dubletten anzeigen |
| Mailimport | Konfigurierten IMAP-Abruf starten und Importstatus abfragen |
| Übergabe | Paketvorschau erstellen, Paket erzeugen, Status und Inhaltsliste abrufen |
| Versand | Bestehende Paketversion an konfigurierte Empfänger senden und Versandstatus abfragen |

Große Originaldateien werden über einen authentifizierten Datei-Transfer übergeben; MCP liefert bzw. verwendet Dokument-IDs. Lesezugriff, Verarbeitung und Versand sind getrennt berechtigbar. Idempotenzschlüssel schützen schreibende Automatisierungen vor doppelten Importen, Paketen und Versandaufträgen.

Später kommen Werkzeuge für Rechnungsentwurf, Finalisierung, Versand, wiederkehrende Rechnungen, Projekte, Zeiten und monatliche Abrechnung hinzu. Deterministische Fachlogik berechnet Rechnungsbeträge; KI dient der Auslese und Vorbereitung.

## 7. Oberfläche und Betrieb mit Docker Compose

Die erste Oberfläche umfasst Firmenwechsel, Dokumenteingang/Upload, Dokumentliste mit Detailprüfung, Monats-/Periodenübersicht, Pakete/Versandhistorie und Einstellungen für Firmen, Konten, Depots und E-Mail.

Vorgeschlagener einfacher Betriebsaufbau:

- App-Service für Weboberfläche, API und MCP.
- Worker aus derselben Codebasis für IMAP-Abruf, Auslese, Paketerstellung und SMTP-Warteschlange.
- PostgreSQL für Metadaten, Aufträge und Protokolle.
- Persistentes Volume für Originaldateien und Paket-Snapshots.
- Optionale OCR-/Modellanbindung hinter einer austauschbaren Schnittstelle; fehlende Anbindung blockiert die manuelle Ablage nicht.

Docker Compose soll den gesamten Kernbetrieb starten. Kein Kubernetes und keine zusätzlichen Queue-/Objektspeicherdienste als Voraussetzung für die erste Version. Datenbankgestützte Jobs müssen Neustarts, Sperren und Wiederaufnahme beherrschen.

Lieferumfang der Implementierung: Dockerfile, compose.yaml, .env.example ohne echte Zugangsdaten, dokumentierte Konfiguration, Healthchecks, Migrationen sowie Backup-/Restore-Anleitung. Datenbank und Dokumentdateien werden konsistent gesichert und gemeinsam wiederherstellbar gehalten. Interne Dienste sind nicht öffentlich exponiert; externer Zugriff erfolgt über einen TLS-Reverse-Proxy. Zugangsdaten werden nicht in Git oder Protokollen abgelegt. Konkrete Sprach-/Frameworkwahl und Ressourcenwerte werden vor der Implementierung festgelegt.

## 8. Reihenfolge und Abnahmekriterien

### Etappe 1 – Dokumente, IMAP, Paket und MCP

1. Firmen, Konten/Depots, Originalablage und manuelle Metadaten.
2. Upload, automatische Auslese, Prüfung und Dublettenerkennung.
3. IMAP-Eingang und wiederaufnehmbare Hintergrundaufträge.
4. Paketvorschau, ZIP/Übersichten, SMTP-Versand und Nachträge.
5. MCP für dieselben Abläufe; Docker-Compose-Betrieb und Wiederherstellung.

Abnahme anhand eines vollständigen Testmonats mit zwei Firmen: Invoice-Ninja-Ausgangsrechnung als PDF, Eingangsrechnung, Gutschrift, CAMT samt passendem PDF-Auszug und Wertpapierbewegung als PDF. Alle Originale erscheinen unter der richtigen Firma und Periode im Paket. Eine E-Mail mit mehreren Anhängen wird bei wiederholtem Abruf und nach Neustart nur einmal importiert. Fehlerhafte Auslese verliert keine Datei. Wiederholte MCP-Aufträge erzeugen keinen Doppelversand. Ein Nachtrag ist vom ursprünglichen Paket unterscheidbar. Versandfehler und unbekannter Versandausgang bleiben sichtbar. Backup und Restore stellen Dokumente, Zuordnungen und Paketstände wieder her.

### Etappe 2 – Eigene Rechnungen und Bankabgleich

Einmalige und wiederkehrende Rechnungen mit Kunden-/Leistungsvorlagen, Nummernkreisen, finalen PDFs, Stornos und SMTP-Versand. CAMT-Abgleich liefert Zuordnungsvorschläge und fehlende Belege. Importierte historische PDFs bleiben als externe Originale erhalten.

### Etappe 3 – Projekte und monatliche Abrechnung

Projektzeiten und Sätze erfassen, abrechenbare Leistungen periodisch auswählen, Rechnungsentwürfe erzeugen und doppelte Verrechnung verhindern.

### Später nach Bedarf

Native Buchhaltungsimporte für die Kanzlei, strukturierte E-Rechnungen, weitergehende Wertpapierauswertung und zusätzliche Integrationen. Ein Bank-Livezugriff ist für den beschriebenen Dateiablauf nicht erforderlich.

## 9. Vor Implementierungsstart zu konkretisieren

- Technikstack und Authentifizierung für Oberfläche sowie MCP.
- Benötigte CAMT-Versionen anhand echter, anonymisierter Beispieldateien.
- Gewünschte Konten-/Depotbezeichnungen, Kategorien und Übersichtsspalten mit der Steuerberatung.
- Mailanbieter, Authentifizierungsverfahren, Importordner, Absender und maximale Anhangsgröße.
- OCR-/KI-Anbieter oder lokale Verarbeitung sowie Betriebskosten.
- Automatisierungsregeln: manueller Paketversand oder explizit eingerichteter Monatslauf; Verhalten bei offenen Punkten.

Diese Punkte betreffen die Umsetzungskonfiguration. Die fachliche erste Version bleibt PDF-/Dateiimport, E-Mail-Eingang, strukturierte Übergabe, SMTP-Versand, MCP und Docker Compose.
