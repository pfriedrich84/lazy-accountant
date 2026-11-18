# Lazy Accountant – Funktionskatalog und Umsetzungsplan

Stand: 18. November 2026. Status: vereinbarte Anforderungen und Umsetzungsvorschlag; noch keine Implementierung.

## 1. Ziel und Ausgangslage

Eine schlanke, selbst betriebene Webanwendung sammelt Rechnungen, Bank- und Depotunterlagen je Firma, strukturiert sie und verschickt ein vollständiges Paket an die Steuerberatung. Alle wesentlichen Abläufe sollen auch über einen eigenen MCP-Server automatisierbar sein. Deployment erfolgt mit Docker Compose. Weboberfläche, API und MCP laufen zunächst ausschließlich im internen Netz über HTTP. Orca Server startet den Agentenlauf für die Monatsverarbeitung; der Agent führt die Arbeit über MCP aus. Ein eigener serverseitiger Monatszeitplaner ist für die erste Version nicht erforderlich. In der ersten Version übernimmt der vorhandene externe Agent des Nutzers die KI-Auslese und Sortierung über MCP. Versionierte Skills im Repository beschreiben diese Arbeitsabläufe; der Server braucht zunächst keine eigene LLM-Anbindung und keinen eigenen KI-API-Key.

Heute entstehen einmalige und wiederkehrende Rechnungen in Invoice Ninja. Für den ersten nutzbaren Stand werden diese Rechnungen einfach als endgültige PDFs hochgeladen oder per E-Mail eingelesen. Eine Invoice-Ninja-Integration ist dafür nicht erforderlich. Eigene Rechnungserstellung und wiederkehrende Rechnungen sind der nächste Ausbau; Projektzeiterfassung und monatliche Leistungsabrechnung folgen später.

Die erste Version bereitet Unterlagen vor. Sie benötigt weder eine vollständige Finanzbuchhaltung noch einen BMD-Buchungsimport. Die Steuerberatung erhält zunächst Originaldateien und strukturierte Übersichten.

## 2. Funktionskatalog

| ID | Funktion | Erste Version / später |
| --- | --- | --- |
| F01 | Mehrere Firmen mit getrennten Dokumenten, Konto-/Depotzuordnungen, Mailkonfiguration und Steuerberater-Empfängern | Erste Version |
| F02 | Ausgangsrechnungen und Stornos als bereits ausgestellte PDFs importieren; Rechnungsnummer und Original erhalten | Erste Version |
| F03 | Eingangsrechnungen und sonstige Belege als PDF, JPG und PNG einzeln oder gesammelt hochladen | Erste Version |
| F04 | Externem Agenten Originale über MCP zugänglich machen und strukturierte Auslese-/Sortierergebnisse validiert speichern; Lieferant/Kunde, Nummer, Datum, Beträge, Währung und Kategorie korrigierbar erfassen | Erste Version |
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
| F19 | Versionierte, agentenübergreifend nutzbare Skills für Dokumentauslese, Sortierung und Monatsübergabe mitliefern | Erste Version |
| F20 | Dokumente physisch und in der Oberfläche unter /Firma/Jahr/Monat/ mit den Unterordnern ER, AR, Bankkonto und Wertpapiere ablegen; dieselbe Struktur im Export erhalten | Erste Version |

## 3. Dokumente und Verarbeitung

Dokumentarten: Ausgangsrechnung, Ausgangsstorno, Eingangsrechnung, Eingangsgutschrift, sonstiger Beleg, Kontoauszug PDF, Kontoauszug CAMT und Wertpapierbewegung PDF.

Gemeinsame Angaben: Firma, Dokumentart, Originaldateiname, interne ID, Herkunft, Importzeitpunkt, Beleg-/Auszugsdatum, zugeordneter Übergabezeitraum, Prüfstatus, Kategorie und Notiz. Konto- und Depotunterlagen tragen zusätzlich ein Konto bzw. Depot und einen Zeitraum. Rechnungsfelder bleiben für andere Dokumentarten optional.

- Originaldateien werden unverändert und mit Prüfsumme gespeichert. Metadaten und Ausleseergebnisse sind davon getrennt.
- Dokumentdatum und Übergabezeitraum sind getrennte Felder. Importierte Ausgangsrechnungen werden nicht neu nummeriert oder neu aufgebaut.
- CAMT und PDF desselben Auszugs können verknüpft werden; beide bleiben im Paket. Der reine CAMT-Import setzt keinen automatischen Bankabgleich voraus.
- Wertpapierbewegungen benötigen zunächst PDF-Ablage und Zuordnung. Automatische Transaktionsauswertung oder Steuerberechnung ist kein Abnahmekriterium.
- Der externe Agent liest die Originale und liefert strukturierte, korrigierbare Ergebnisse über MCP. Unsichere Felder bleiben sichtbar offen; ein Auslesefehler verhindert nicht die sichere Originalablage. Der Server prüft Formate, Rechte und Rechenbeziehungen unabhängig vom Modell.
- Dateigleiche Uploads werden per Hash erkannt; ähnliche Rechnungsnummern/Beträge erzeugen einen Dublettenhinweis. Gleiche Beträge allein sind kein Löschgrund.
- Ungeklärte Firma, Dokumentart oder Periode führt in eine Prüfliste. Der Import rät keine endgültige Zuordnung.
- Dokumente sind nach Firma, Zeitraum, Art, Geschäftspartner, Status und Kategorie filterbar.

### 3.1 Verbindliche Ordnerstruktur

Die Ablage erfolgt als echte Ordnerstruktur im persistenten Dokument-Volume und ist in der Oberfläche sowie über MCP sichtbar. Sie ist keine reine Kategorie- oder Filteransicht. Der in Docker Compose gemountete Ablagestamm enthält je Firma folgende Pfade; Jahr wird vierstellig und Monat zweistellig (01–12) geschrieben:

| Pfad relativ zum Ablagestamm | Inhalt |
| --- | --- |
| /Firma/Jahr/Monat/ER/ | Eingangsrechnungen, Eingangsgutschriften und zugehörige Ausgabenbelege |
| /Firma/Jahr/Monat/AR/ | Ausgangsrechnungen und Ausgangsstornos, zunächst importierte Original-PDFs aus Invoice Ninja |
| /Firma/Jahr/Monat/Bankkonto/ | CAMT-Originaldateien und PDF-Kontoauszüge |
| /Firma/Jahr/Monat/Wertpapiere/ | PDF-Unterlagen zu Wertpapierbewegungen |

Beispiele: /Beispiel-GmbH/2026/11/ER/, /Beispiel-GmbH/2026/11/AR/, /Beispiel-GmbH/2026/11/Bankkonto/ und /Beispiel-GmbH/2026/11/Wertpapiere/. Die vier Monatsordner werden auch bei fehlenden Dokumenten angelegt und im vollständigen Paket beibehalten.

Der zugeordnete Ablage-/Übergabemonat bestimmt Jahr und Monat des Pfads. Belegdatum und Auszugszeitraum bleiben als eigenständige Angaben erhalten. Firmenordner verwenden konfigurierte, eindeutige und dateisystemsichere Namen. Dateinamen werden ebenfalls sicher und kollisionsfrei gebildet; der Originaldateiname bleibt zusätzlich gespeichert. Bei mehreren Konten oder Depots bleibt die konkrete Zuordnung in Metadaten und Übersicht nachvollziehbar.

Neue, noch nicht sicher zugeordnete Uploads und E-Mail-Anhänge liegen zunächst in einer technischen Eingangsablage. Nach der Klassifikation ordnet die Anwendung sie dem verbindlichen Firmen-/Monats-/Dokumentordner zu. Der Agent schreibt die Zuordnung über MCP; die Anwendung leitet den Pfad deterministisch daraus ab und führt die Ablage aus. Freie Dateisystempfade aus Agenten- oder Dokumenttexten werden nicht übernommen.

Umklassifizierungen und Monatskorrekturen aktualisieren Ordner und Metadaten gemeinsam, ohne die Originalbytes zu verändern. Bereits erzeugte Paket-Snapshots bleiben unverändert. Das Übergabe-ZIP enthält dieselbe Hierarchie /Firma/Jahr/Monat/ER, AR, Bankkonto und Wertpapiere. Mehrmonatige Pakete enthalten jeden Monat getrennt; Nachträge behalten ebenfalls diese Struktur. Begleitschreiben, Übersichten und Inhaltsliste werden als zusätzliche Dateien im jeweiligen Monatsordner abgelegt.

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

Oberfläche und MCP verwenden dieselben fachlichen Funktionen, Validierungen und Firmenberechtigungen. Der MCP-Server ist ein regulärer Zugangsweg, kein separater Datenbestand. Ziel ist ein authentifizierter MCP-Zugang über Streamable HTTP im internen Netz, zunächst ohne TLS; Verbindungen erhalten explizite Firmen- und Funktionsrechte. HTTP ist die festgelegte Transportkonfiguration der ersten Version, keine Freigabe für öffentlichen Betrieb.

Geplante Werkzeuge für die erste Version:

| Werkzeuggruppe | Aktionen |
| --- | --- |
| Firmen und Zuordnungen | Berechtigte Firmen, Konten, Depots und Kategorien auflisten |
| Dokumente | Upload vorbereiten/abschließen, paginiert auflisten/abrufen, Originaldatei und verfügbare Text-/Seitenansichten lesen, Metadaten und Zuordnungen ändern |
| Verarbeitung | Dokumente zur Bearbeitung übernehmen, strukturierte Auslese-/Klassifikationsergebnisse speichern, Vorschläge prüfen/bestätigen, offene Punkte und Dubletten anzeigen |
| Mailimport | Konfigurierten IMAP-Abruf starten und Importstatus abfragen |
| Übergabe | Paketvorschau erstellen, Paket erzeugen, Status und Inhaltsliste abrufen |
| Versand | Bestehende Paketversion an konfigurierte Empfänger senden und Versandstatus abfragen |

Große Originaldateien werden über einen authentifizierten Datei-Transfer übergeben; MCP liefert bzw. verwendet Dokument-IDs. Lesezugriff, Verarbeitung und Versand sind getrennt berechtigbar. Idempotenzschlüssel schützen schreibende Automatisierungen vor doppelten Importen, Paketen und Versandaufträgen.

Später kommen Werkzeuge für Rechnungsentwurf, Finalisierung, Versand, wiederkehrende Rechnungen, Projekte, Zeiten und monatliche Abrechnung hinzu. Deterministische Fachlogik berechnet Rechnungsbeträge; KI dient der Auslese und Vorbereitung.

### 6.1 Vertrag zwischen Agent und Anwendung

Der Agent entscheidet anhand des Dokumentinhalts; die Anwendung bleibt die führende Ablage. Der Server bietet dokumentierte Eingabe-/Ausgabeschemas und speichert Bearbeiter, Zeitpunkt, Ausgangsversion und Herkunft eines Ergebnisses. Gleichzeitige Bearbeitung darf neuere manuelle Korrekturen nicht überschreiben.

Rechnungsergebnisse enthalten: Dokument-ID, Ausgangsversion, Dokumentart, Firma, Aussteller, Empfänger, Rechnungsnummer, Rechnungsdatum, optional Leistungs-/Fälligkeitsdatum, Währung, Netto/Steuer/Brutto sowie Steueraufteilungen, Kategorie, Übergabezeitraum und konkrete offene Punkte. Nicht erkennbare Werte bleiben leer. Für wesentliche erkannte Felder werden verfügbare Belegstellen wie Seite/Textausschnitt mitgeliefert; Unsicherheit ist pro Feld bzw. Zuordnung sichtbar.

Bank-/Depotunterlagen verwenden eigene Ergebnisfelder wie Konto/Depot, Auszugszeitraum und Dokumentunterart. CAMT wird strukturell eingelesen, statt Beträge aus dem XML durch ein Sprachmodell neu berechnen zu lassen. Bei Wertpapier-PDFs genügt zunächst die korrekte Dokumentzuordnung; Kauf-/Verkaufsabrechnungen oder Ertragsmitteilungen dürfen als Unterart erfasst werden.

Der Server validiert Pflichtfelder je Dokumentart, Datums-/Währungsformate, erlaubte Kategorien sowie Summen mit Währungsrundung. Unplausible oder unvollständige Ergebnisse erhalten einen Prüfstatus mit Grund. Ein hoher modellseitiger Vertrauenswert ersetzt keine Prüfung. Firmenzuordnung nutzt bekannte Firmendaten und Empfänger-/Kontomerkmale; der Absender allein genügt nicht.

### 6.2 Mitgelieferte Skills

Die Implementierung liefert die Skills als versionierte Markdown-Dateien im Repository unter skills/<name>/SKILL.md. Sie sollen mit verschiedenen Agenten verwendbar sein, ohne eine bestimmte Agentenplattform vorauszusetzen. Skill-Anweisungen definieren den Ablauf, MCP stellt die Werkzeuge bereit, der Server erzwingt Daten- und Berechtigungsregeln.

| Skill | Auftrag und Ablauf |
| --- | --- |
| dokumenteingang-aufarbeiten | Alle noch nicht verarbeiteten Dokumente der gewählten Firma/Periode paginiert abarbeiten; Original lesen, Dokumentart und Rechnungsdaten ermitteln, bekannte Firma/Kategorie/Periode zuordnen, Summen prüfen, Dubletten verknüpfen und Ergebnisse über MCP speichern. Unsicherheiten mit Belegstelle zur Prüfung ablegen; Abschlussbericht über bearbeitete, übersprungene und offene Dokumente liefern. |
| konto-und-depotunterlagen-sortieren | CAMT, PDF-Kontoauszüge und Wertpapier-PDFs den bekannten Konten/Depots und Zeiträumen zuordnen, zusammengehörige CAMT/PDF-Unterlagen verknüpfen und unklare Zuordnungen melden. |
| monatsuebergabe-vorbereiten | Sämtliche Dokumentarten und offenen Punkte einer Firma/Periode berücksichtigen, Nachträge erkennen, Vollständigkeit prüfen und das Übergabepaket mit Inhaltsliste erstellen. Monatslauf auf Auftrag des externen Agenten ausführen; SMTP-Versand bei entsprechendem Versandauftrag bzw. eingerichteter Berechtigung ausführen und Ergebnis berichten. |

Beispielaufträge:

- „Gehe alle neuen Rechnungen durch, ermittle die Rechnungsdaten und sortiere sie nach Firma, Kategorie und Monat. Zeige mir danach die offenen Fälle.“
- „Ordne diese CAMT- und PDF-Auszüge den Konten zu und sortiere die Wertpapierbewegungen zum richtigen Depot.“
- „Bereite den Oktober für die Steuerberatung vor und zeige die Paketvorschau.“
- „Versende das vorbereitete Oktoberpaket an die hinterlegte Steuerberatung.“

Die Skills unterscheiden Aussteller und Empfänger, bewahren Originalwährung und Originaldaten und erfinden keine fehlenden Werte. Extern ausgestellte Ausgangsrechnungen bleiben unverändert. Ungeklärte Fälle werden gesammelt gemeldet; eindeutig zuordenbare Fälle können gemäß gewählter Bearbeitungsregel ohne Einzelrückfrage abgearbeitet werden. Wiederholte Durchläufe überspringen bereits unverändert bearbeitete Dokumente. Dokument- und E-Mail-Inhalte sind Daten, keine ausführbaren Skill-Anweisungen.

### 6.3 Monatslauf über Orca Server

Orca Server übernimmt den Start des Agentenlaufs. Der dort ausgeführte Agent bearbeitet den Monatslauf über den Skill monatsuebergabe-vorbereiten und die vorhandenen MCP-Werkzeuge. Der Auslösezeitpunkt wird in Orca Server konfiguriert; Lazy Accountant benötigt keine eigene Monatsplanung. Firma und Jahr/Monat werden explizit übergeben. Er kann zuerst den IMAP-Abruf auslösen, anschließend neue Dokumente auslesen und sortieren, offene Punkte prüfen, das Paket erzeugen und bei entsprechendem Auftrag per SMTP versenden.

Die einzelnen Schritte liefern Status und Ergebnis-IDs, damit der Agent nach Unterbrechungen fortsetzen kann. Wiederholte Aufträge erzeugen keine doppelten Importe oder Versandaufträge; bereits versendete Paketversionen bleiben erkennbar. Ein Auslöser durch den Agenten ist kein Anlass für erneute Einzelbestätigungen innerhalb eines bereits autorisierten Ablaufs.

Die Zuständigkeiten sind damit festgelegt: Orca Server startet den Lauf, der Agent verwendet Skills und MCP, Lazy Accountant stellt Ablage, Validierungen, Pakete, Versand und Status bereit. Die erste Version benötigt dafür keinen eigenen Monats-Cronjob und keinen internen KI-Agenten. Hintergrundaufträge für IMAP-Abruf, Paketerstellung und SMTP-Verarbeitung bleiben davon unabhängig. Die Orca-Verbindung verwendet den internen HTTP-MCP-Endpunkt. Im Rahmen dieser Planung wird kein tatsächlicher Orca-Job oder Termin eingerichtet.

## 7. Oberfläche und Betrieb mit Docker Compose

Die erste Oberfläche umfasst Firmenwechsel, Dokumenteingang/Upload, Dokumentliste mit Detailprüfung, Monats-/Periodenübersicht, Pakete/Versandhistorie und Einstellungen für Firmen, Konten, Depots und E-Mail.

Vorgeschlagener einfacher Betriebsaufbau:

- App-Service für Weboberfläche, API und MCP.
- Worker aus derselben Codebasis für IMAP-Abruf, technische Dokumentvorbereitung, Paketerstellung und SMTP-Warteschlange.
- PostgreSQL für Metadaten, Aufträge und Protokolle.
- Persistentes Volume für Originaldateien und Paket-Snapshots.
- Vorhandener externer Agent mit MCP-Verbindung für Auslese und Sortierung. Kein Modellservice als Voraussetzung des Compose-Stacks; lokale Textextraktion oder Seitenvorschau kann den Agenten unterstützen. Eine serverseitige OCR-/Modellanbindung ist ein späterer optionaler Ausbau.

Docker Compose soll den gesamten Kernbetrieb starten. Kein Kubernetes und keine zusätzlichen Queue-/Objektspeicherdienste als Voraussetzung für die erste Version. Datenbankgestützte Jobs müssen Neustarts, Sperren und Wiederaufnahme beherrschen.

Lieferumfang der Implementierung: Dockerfile, compose.yaml, .env.example ohne echte Zugangsdaten, dokumentierte Konfiguration, Healthchecks, Migrationen sowie Backup-/Restore-Anleitung. Datenbank und Dokumentdateien werden konsistent gesichert und gemeinsam wiederherstellbar gehalten. Weboberfläche, API und MCP werden ausschließlich intern über HTTP bereitgestellt. Ein TLS-Reverse-Proxy und eine Domain sind keine Startvoraussetzung. Die Datenbank bleibt im internen Compose-Netz. Die Anwendungsauthentifizierung und die Firmen-/Funktionsrechte gelten unabhängig vom HTTP-Transport weiter. Zugangsdaten werden nicht in Git oder Protokollen abgelegt. Die Frameworkwahl ist in Abschnitt 7.1 festgelegt; konkrete kompatible Versionen und Ressourcenwerte werden bei Implementierungsstart dokumentiert.

### 7.1 Festgelegte Frameworks und Wiederverwendung

Die Anwendung nutzt etablierte Framework-Funktionen für Infrastruktur und Standardabläufe; individuell implementiert werden die fachlichen Regeln der Dokumentzuordnung und Übergabe.

| Bereich | Festlegung |
| --- | --- |
| Python-Backend | Django 5.2 LTS mit aktuellem kompatiblem Patchstand und Django REST Framework |
| Datenbankzugriff | Django ORM, Django-Migrationen und PostgreSQL; keine zweite ORM-/Migrationsschicht |
| Benutzer und Administration | Django Auth, Sessions, Berechtigungen und Django Admin; Admin ergänzt die eigentliche Benutzeroberfläche |
| Weboberfläche | React und TypeScript; React Router im Framework Mode mit SPA-Konfiguration und Vite-Build |
| UI-Komponenten | Material UI mit frei nutzbaren Komponenten für Formulare, Tabellen, Navigation und Dialoge |
| Serverdaten im Frontend | TanStack Query für Abruf, Mutationen, Statusaktualisierung und Cache-Invalidierung |
| Hintergrundjobs | Django-Q2 mit Django-ORM-Broker in PostgreSQL; Worker als separater Compose-Service |
| E-Mail-Versand | Django-Mail-Backend für SMTP; IMAP mit bewährter Bibliothek bzw. Python-Standardbibliothek als Importadapter |
| MCP | Offizielles modelcontextprotocol/python-sdk; Streamable HTTP, eingebunden über ASGI neben Django |
| Prüfungen | Django-/pytest-django-Tests, Frontend-Typprüfung und Tests mit Vitest/Testing Library sowie Browser-Smoke und Compose-Smoke |

Django wurde wegen der integrierten Benutzerverwaltung, Administration, ORM und Migrationen gewählt. Für die datenorientierte Weboberfläche wird React mit einer fertigen Komponentenbibliothek verwendet. Eine Flutter-Oberfläche ist für diesen ersten Web-Lieferumfang nicht vorgesehen.

MCP und REST verwenden denselben fachlichen Service-Layer. Die ASGI-Integration berücksichtigt den MCP-Lifecycle, explizite erlaubte interne Hosts und Authentifizierung auch an der MCP-Route. Frontend, API und MCP werden unter einer internen HTTP-Origin bereitgestellt; ein Node-Server ist im Laufbetrieb der SPA nicht erforderlich.

Django-Q2 übernimmt die Queue-Technik. Fachliche Versand-/Paketstatus, Idempotenz und der Umgang mit unbekanntem SMTP-Ausgang bleiben ausdrücklich implementiert. Retry-/Timeout-Konfiguration muss Doppelverarbeitung berücksichtigen. Orca Server bleibt der Auslöser des Monatslaufs; der Queue-Scheduler übernimmt diese Planung nicht.

Die derzeit verfügbaren stabilen und zueinander kompatiblen Releases sind bei Umsetzung zu prüfen und in Lockfiles festzuhalten. Begründete Inkompatibilitäten werden dokumentiert und innerhalb dieses Stacks gelöst; Routineentscheidungen erfordern keine weitere Grundsatzabstimmung.

Offizielle Grundlagen:

- [Django: integrierte Funktionen](https://www.djangoproject.com/start/) und [Supportstände](https://www.djangoproject.com/download/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [React Router: SPA Mode](https://reactrouter.com/how-to/spa)
- [Material UI](https://mui.com/material-ui/getting-started/)
- [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview)
- [Django-Q2: ORM-Broker](https://django-q2.readthedocs.io/en/master/configure.html#orm)
- [Offizielles MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## 8. Reihenfolge und Abnahmekriterien

### Etappe 1 – Dokumente, IMAP, Paket und MCP

1. Firmen, Konten/Depots, Originalablage und manuelle Metadaten.
2. Upload, MCP-Dokumentzugriff, validierte Ergebnisübernahme vom externen Agenten, Prüfung und Dublettenerkennung sowie Skills.
3. IMAP-Eingang und wiederaufnehmbare Hintergrundaufträge.
4. Paketvorschau, ZIP/Übersichten, SMTP-Versand und Nachträge.
5. Vollständiger Agentendurchlauf mit den Skills; Docker-Compose-Betrieb und Wiederherstellung ohne interne KI-Anbindung.

Abnahme anhand eines vollständigen Testmonats mit zwei Firmen: Invoice-Ninja-Ausgangsrechnung als PDF, Eingangsrechnung, Gutschrift, CAMT samt passendem PDF-Auszug und Wertpapierbewegung als PDF. Alle Originale erscheinen unter der richtigen Firma und Periode im Paket und liegen sowohl im persistenten Dokument-Volume als auch im ZIP unter /Firma/Jahr/Monat/ER, AR, Bankkonto oder Wertpapiere. Die vier Monatsordner bleiben getrennt, CAMT und PDF liegen gemeinsam unter Bankkonto; Monatskorrekturen verändern keine bereits versendeten Pakete. Eine E-Mail mit mehreren Anhängen wird bei wiederholtem Abruf und nach Neustart nur einmal importiert. Fehlerhafte Auslese verliert keine Datei. Ein Agent kann über MCP alle neuen Dokumente vollständig auflisten, lesen, klassifizieren und seine Ergebnisse speichern; ein zweiter unveränderter Skill-Durchlauf legt nichts doppelt an. Unklare Firmenzuordnungen, abweichende Summen und zwischenzeitliche manuelle Korrekturen bleiben geschützt und sichtbar. Der Server startet ohne eigene LLM-Zugangsdaten, TLS-Zertifikate oder Domain; Oberfläche und MCP sind intern über HTTP erreichbar. Der Agent kann den Monatslauf für eine ausdrücklich gewählte Firma/Periode vollständig anstoßen und nach Unterbrechung fortsetzen. Wiederholte MCP-Aufträge erzeugen keinen Doppelversand. Ein Nachtrag ist vom ursprünglichen Paket unterscheidbar. Versandfehler und unbekannter Versandausgang bleiben sichtbar. Backup und Restore stellen Dokumente, Zuordnungen und Paketstände wieder her.

### Etappe 2 – Eigene Rechnungen und Bankabgleich

Einmalige und wiederkehrende Rechnungen mit Kunden-/Leistungsvorlagen, Nummernkreisen, finalen PDFs, Stornos und SMTP-Versand. CAMT-Abgleich liefert Zuordnungsvorschläge und fehlende Belege. Importierte historische PDFs bleiben als externe Originale erhalten.

### Etappe 3 – Projekte und monatliche Abrechnung

Projektzeiten und Sätze erfassen, abrechenbare Leistungen periodisch auswählen, Rechnungsentwürfe erzeugen und doppelte Verrechnung verhindern.

### Später nach Bedarf

Native Buchhaltungsimporte für die Kanzlei, strukturierte E-Rechnungen, weitergehende Wertpapierauswertung und zusätzliche Integrationen. Ein Bank-Livezugriff ist für den beschriebenen Dateiablauf nicht erforderlich.

## 9. Entwicklungsstart und spätere Betriebsparameter

Der Coding-Agent kann mit Etappe 1 beginnen. Die fachlichen Anforderungen, Ordnerstruktur, interner HTTP-Betrieb, Docker Compose sowie Orca Server als Auslöser des externen Agentenlaufs sind festgelegt.

### Technische Umsetzung ohne weitere Grundsatzentscheidung

- Festgelegter Stack: Django 5.2 LTS mit Django REST Framework, Django ORM/Migrationen/Auth/Admin, PostgreSQL, React/TypeScript mit React Router (Framework Mode, SPA über Vite), Material UI und TanStack Query. Hintergrundjobs verwenden Django-Q2 mit ORM-Broker. MCP nutzt das offizielle Python-SDK. Kompatible stabile Patch-/Paketversionen werden bei Implementierungsstart geprüft, fest gepinnt und mit Lockfiles dokumentiert.
- Ein Benutzerkonto mit mehreren getrennten Firmen genügt zunächst. Oberfläche und MCP erhalten eine einfache dokumentierte Authentifizierung und dieselben fachlichen Berechtigungen.
- Originaldateien liegen in einem konfigurierbaren Hostordner, der über einen Docker-Compose-Bind-Mount eingebunden wird. Darunter gilt die festgelegte Firmen-/Jahres-/Monatsstruktur. Paket-Snapshots und Eingangsablage haben eigene technische Bereiche.
- Vorschlag für die initiale Monatszuordnung: Rechnungen nach Belegdatum, Konto-/Depotunterlagen nach Auszugsmonat bzw. Ende des Auszugszeitraums. Unsicherheit, mehrmonatige Unterlagen und manuelle Korrekturen bleiben sichtbar und übersteuerbar; das Datum eines Imports bestimmt nicht automatisch den Belegmonat.
- Für die Entwicklung genügen synthetische Dokumente, konfigurierbare Firmen/Kategorien und ein lokaler Test-Maildienst bzw. kontrollierte Mail-Testadapter. Die Anwendung startet auch ohne produktive IMAP-/SMTP-Zugänge.
- Für CAMT werden unterstützte Namespaces/Versionen explizit dokumentiert und mit Testdateien geprüft. Nicht unterstützte Dateien bleiben als Original erhalten und erhalten einen sichtbaren Verarbeitungsstatus. Kundenspezifische Beispieldateien können später ergänzt werden.
- Die mitgelieferten Skills werden gegen die tatsächlich implementierten MCP-Werkzeuge geprüft; Werkzeugnamen, Schemas und Beispielaufträge dürfen nicht nur in der Planung existieren.

### Bei Einrichtung oder Live-Abnahme zu ergänzen

- Interne Serveradresse, Port und Speicherpfade.
- Firmen, Konten, Depots, Kategorien und gewünschte Übersichtsspalten.
- IMAP-/SMTP-Anbieter, Zugangsdaten, Ordner, Absender, Empfänger und maximale Mailgröße.
- Von Orca Server aus erreichbarer HTTP-MCP-Endpunkt und dessen Zugang; Datei-/Seitenzugriff sowie Ergebnisübernahme mit dem dort verwendeten Agenten praktisch prüfen.
- Versandberechtigung und Verhalten bei offenen Punkten für den vom Agenten gestarteten Monatslauf.
- Repräsentative anonymisierte Originaldokumente für die Live-Abnahme.

Diese Betriebsparameter blockieren die Entwicklung mit Testdaten nicht. Der erste Lieferumfang ist Etappe 1; eigene Rechnungserstellung, wiederkehrende Rechnungen, Bankabgleich, Projekte und Zeitabrechnung bleiben in den späteren Etappen.
