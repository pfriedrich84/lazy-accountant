# Eine Arbeitsmappe für die Monatsübergabe

Neue Pakete enthalten die unveränderten Originaldateien und **eine** `Monatsuebersicht_<Monat>.xlsx` im Firmenordner. Bei mehreren Monaten heißt sie `Monatsuebersicht_<von>_bis_<bis>.xlsx`; die Monatszuordnung bleibt an den Zeilen erhalten. Separate `Uebersicht.csv`, `Zahlungsstand.csv/.xlsx/.json`, `Begleitschreiben.txt` und `Inhaltsliste.json` entfallen für neue Pakete. Die technische Inhaltsliste für nummerierte **Mailteile** bleibt ein davon unabhängiger Transportvertrag.

Bestehende ZIPs, Snapshots, Versandhistorien und deren Downloads werden nicht migriert oder neu erzeugt. Ein reiner Exportwunsch ist kein Auftrag für ein neues Paket oder einen Versand. BMD-/RZL-Import ist nicht Teil dieses Formats.

## Blätter

| Blatt | Inhalt |
| --- | --- |
| Übersicht | Firma, Monate, Empfänger, Paket-/Nachtragsbezug, eingefrorener Datenstand, Originalumfang, Bankeingänge/-ausgänge getrennt nach Konto und Währung, Hinweise und bewusste Ausschlüsse |
| Eingangsrechnungen | Rechnungen/Gutschriften mit Geschäftspartner, Nummer, echten Datumswerten, Originalwährung, Netto/Steuer/Brutto, Bankzuordnung, Zahlbetrag laut Original, Drittübernahme und Beleglink |
| Ausgangsrechnungen | Entsprechend für Ausgangsrechnungen und Stornos |
| Zahlungszuordnungen | Eine Zeile je Zuordnung, einschließlich aufgehobener Zuordnungen; getrennte Rechnungswährung, Bankgegenwert, belegte Spesen und Gesamtabfluss, Kurs, Quellenbegründung und FX-Originaltext |
| Bankbewegungen | Normalisierte kanonische Bewegungen nach Buchungsmonat, Konto, Buchungs-/Valutadatum, Richtung, Gegenpartei, Referenz, Verwendungszweck, Rechnungsbezug und Quellenhinweise |
| Wertpapiere | Depot, ISIN, Abrechnungs-/Valutadatum sowie explizit erfasste Originalbeträge, Quellensteuer, Bankwährung, Spesen und Gutschrift |
| Klärfälle | Dokumentprüfpunkte, tatsächlicher Zuordnungsprüfbedarf und ausdrücklich erfasste Wiedervorlagen der ausgewählten Perioden, getrennt von technischen Importfällen |
| Inhaltsliste | Tatsächlich enthaltene Originale mit relativem Pfad, Dokumentkennung, Revision, Größe und SHA-256; ergänzende Zahlungsbelege sind keine zweite Rechnung |

Dunkle Tabellenköpfe, Titel-/Kontextbereich, gestreifte filterbare Tabellen, fixierte Kopfzeilen, formatierte Zahlen und Datumswerte entsprechen der freigegebenen Arbeitsmappenstruktur. Technische Kennungen stehen hinten, nicht anstelle lesbarer Belegnummern. Keine Addition verschiedener Währungen. Es wird kein Buchungsjournalabgleich und keine vollständige Kontobewegungsabdeckung allein aus normalisierten Daten behauptet.

Relative Links beziehen sich auf den Firmenordner mit der Arbeitsmappe. Das gesamte ZIP entpacken; unveränderte Originale eines Nachtrags befinden sich ausdrücklich im Vorgängerpaket und erhalten keinen ins Leere laufenden Link. Sonderzeichen in Linkzielen werden URI-kodiert.

## Fachliche Grenzen und neue optionale Metadaten

Eine fehlende Bankzuordnung beweist keine Nichtzahlung. `paid`, `remaining`, Zuordnungshistorie und Bankdeckung bleiben unverändert bankbasiert. Die Arbeitsmappe erzeugt weder Zahlungen noch Zuordnungen. Ein gedrucktes `Amount due = 0` ist kein unabhängiger Banknachweis.

Um die ausdrücklich belegten Sonderfälle ohne Firmen-, Lieferanten- oder Rechnungsnummern-Hardcoding darzustellen, unterstützt `Metadata` zwei optionale Objekte. Werte müssen aus tatsächlichen Originalen bzw. ausdrücklich bestätigten Sachverhalten stammen und in `evidence` belegt werden. **Keine automatische Interpretation freier Notizen.** Fehlende Felder bleiben leer, nicht null Euro. Bereits gespeicherte Notizen werden nicht automatisch in neue Betragsfelder migriert.

### `settlement`

- `amount_due`: Zahl-/Restbetrag laut Original, nicht der aus Bankzuordnungen berechnete Rest und keine aktuelle Zahlungsaufforderung.
- `covered_by_third_party`: ausdrücklich belegte nichtnegative Kostenübernahme durch Dritte. Rechnungssumme unverändert lassen. Nur bei vollständiger Abdeckung und `amount_due=0` erscheint „Durch Dritte gedeckt – kein eigener Zahlbetrag“; keine erfundene Bankzahlung.
- `review_note`, `next_step`, `follow_up`: bestätigter Sachstand und konkrete Wiedervorlage, etwa eine spätere Akontoanrechnung. Der Excel-Hinweis lautet „Wiedervorlage – keine Zahlungsaufforderung“. Keine unbelegten Guthaben oder doppelten Vorschussabzüge berechnen.

Echte Nullbetragsrechnungen benötigen keinen Bankzahlungsnachweis. Positive Rechnungen mit ausgeglichenem Zahlrest sind keine Nullbetragsrechnung. `receipt` ist ein allgemeiner sonstiger Beleg: eigenständige Kassen-/Aufwandsbelege behalten Datum, Währung, Netto, Steuer und Brutto in der Eingangstabelle. Nur ausdrücklich mit `metadata.subtype: supplementary_payment_receipt`, `payment_receipt` oder `Zahlungsbeleg` klassifizierte ergänzende Zahlungsbestätigungen stehen ausschließlich in der Inhaltsliste, nicht erneut als Ausgabe. Die Klassifizierung muss aus dem Belegkontext hervorgehen, nicht allein aus Belegart, Betrag oder einer Verknüpfung.

Finanztabellen enthalten nur freigegebene, prüfpunktfreie, physisch abgelegte Dokumente sowie entsprechend geeignete unveränderte Vorgängerbelege. Noch zu bestätigende oder fehlerhafte Extraktionen erscheinen ausschließlich als Klärfall, nicht als normale Rechnungszeile. Manuell gepflegte Kategorien bleiben in den Rechnungstabellen und der Inhaltsliste erhalten. Strittige Bankdeckung erscheint unabhängig von einem rechnerisch bereits vollständig zugeordneten Betrag im Blatt Klärfälle mit den Beurteilungshinweisen; daraus folgt keine erneute Zahlungsaufforderung. Kontosummen werden nach Kontoidentität und Währung getrennt, auch bei identischen Anzeigenamen.

### `security_income`

Optionale Dezimalstrings: `quantity`, `gross`, `withholding_tax`, `net`, `bank_net`, `bank_fee`, `bank_credit`, `rate_original_per_bank`. Dazu `original_currency` und `bank_currency` als ISO-4217-Währungen. `metadata.isin` und `metadata.valuation_date` bleiben die bestehenden Felder. Quellensteuer wird nicht als Umsatzsteuer umgedeutet; Devisenspanne ist keine Rechnungszahlung. Ein unbekannter Kurs oder eine unbekannte Gebühr bleibt leer. Dieser Datensatz ist keine automatische Zuordnung zu einer Bankbewegung.

## Snapshot und Sicherheit

Der Renderer `accounting/workbook.py` liest ausschließlich eingefrorene Daten, keine Live-DB. `package_preview` ergänzt `workbook_documents`, `bank_transactions`, `allocation_transactions` und `export_sources`; der Erstellungszeitpunkt wird erst beim tatsächlichen Paketbau eingefroren, sodass identische Vorschauen vergleichbar bleiben. Unveränderte Rechnungskontexte bleiben in reinen Zahlungsnachträgen lesbar, ohne Originale erneut zu liefern. Historische Bankbelege können eine Rechnung aus einer ausgewählten Periode decken, ohne historische Monate in die Klärliste aufzunehmen.

Firmen- und Kontogrenzen, kanonische Identitäten, Rückbuchungshistorie und Quellensicherheit werden berücksichtigt. Auch nur als Kontext verwendete Quellen unterliegen Hash-/Scanprüfung vor Bau, Download und Versand. Bei späterer Sicherheitssperre werden die neuen finanziellen Snapshot-Kontexte nicht über die Detailantwort offengelegt. Persönliche Eingangsausschlüsse bleiben außerhalb des Firmenexports.

Alle aus Belegen stammenden Texte werden als Literalzellen geschrieben, nie als Excel-Formeln. Ungültige XML-Steuerzeichen werden vor der Zellbelegung entfernt. Die Inhaltsliste prüft Originale, nicht die Arbeitsmappe selbst; die äußere ZIP-Prüfsumme bleibt am Paket gespeichert. Keine Makros, kein BMD-Import, keine Live-Kurse.

## Datenschutz und Prüfung

Echte Arbeitsmappen, ZIPs, Agentenzustände und Buchhaltungsdaten gehören nicht ins Repository. `.pi/`, `exports/`, `*.xlsx`, `*.xls` und `*.zip` sind ignoriert. Tests erzeugen ausschließlich synthetische Daten zur Laufzeit; keine reale Beispielarbeitsmappe wird committed.

Abdeckung: einzelne und mehrmonatige Pakete, unveränderte Originalbytes/-hashes, bestehende Snapshot-Unveränderlichkeit, reine Zahlungsnachträge, FX und separate Gebühren, historische Kontextquellen, später gesperrte Quellen, Firmenisolation, Nullbeträge, Drittübernahme, Wiedervorlage, Wertpapier-/Quellensteuerfelder, sichere relative Links und Formel-/Steuerzeichenbehandlung. PostgreSQL-Lock-/Paralleltests und Compose-/Mail-/Restore-Prüfungen bleiben Teil der bestehenden CI; ein lokaler SQLite-Lauf ersetzt diese nicht.
