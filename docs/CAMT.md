# CAMT-Unterstützung

Parser: `backend/accounting/camt.py`, `defusedxml` mit verbotenen DTDs, Entities und externen Referenzen. Originalbytes werden **vor der Auslese** unverändert mit SHA256 in privater Quarantäne gespeichert. Erst ein erfolgreicher lokaler ClamAV-Scan erlaubt den ressourcenbegrenzten Parserprozess. Ein Parser-/Versionsfehler verliert keine Originaldatei, bleibt aber als sichtbarer Sicherheitsfehler gesperrt. Siehe [SECURITY.md](SECURITY.md).

## Explizit akzeptierte Namespaces

Für `camt.052`, `camt.053` und `camt.054` jeweils die Versionen **001.02, 001.08, 001.10, 001.11, 001.12, 001.13**:

```text
urn:iso:std:iso:20022:tech:xsd:camt.052.001.{02,08,10,11,12,13}
urn:iso:std:iso:20022:tech:xsd:camt.053.001.{02,08,10,11,12,13}
urn:iso:std:iso:20022:tech:xsd:camt.054.001.{02,08,10,11,12,13}
```

Die geschweiften Klammern oben sind Dokumentations-Kurzschreibweise, kein wörtlicher Namespace. Der Parser akzeptiert nur die konkret aufgelösten 18 Namen. Die Liste wird nicht stillschweigend auf zukünftige Versionen erweitert.

## Strukturierte Auslese

Unterstützt wird der gemeinsame strukturierte Kern von `Stmt`, `Rpt` und `Ntfctn`: Auszugskennung, IBAN bzw. andere Kontokennung, Kontowährung, Zeitraum sowie `Ntry`-Beträge, Währung, Soll/Haben-Kennzeichen, Buchungsdatum, Referenz und Zusatztext. Beträge sind `Decimal` und werden als Dezimalstrings zurückgegeben. Soll/Haben bleibt als Originalkennzeichen erhalten; keine LLM-Neuberechnung, kein Rechnungsabgleich.

Dies ist **keine vollständige XSD-Validierung** aller Bank-Spezialvarianten und kein Vollimport sämtlicher CAMT-Detailfelder. Fehlende Angaben bleiben leer, Konten-/Firmenzuordnung und unvollständige/mehmonatige Zeiträume müssen geprüft werden. Das XML-Original bleibt für die Steuerberatung und spätere Parsererweiterungen erhalten. CAMT und PDF desselben Auszugs werden verknüpft, aber weder zusammengeführt noch gegeneinander dedupliziert.

## Interpretation von Kontrollabweichungen (Skill 1.2)

Der Agent unterscheidet **Ausleseverlust**, **quelleninterne Zählabweichung** und **Geld-/Saldoabweichung**. `TxsSummry/NbOfNtries` ist eine Behauptung im Original, kein Beweis dafür, wie viele direkte `Ntry`-Elemente tatsächlich vorhanden sind. `TxDtls` können Unterpositionen einer Sammelbuchung sein und dürfen nicht mit `Ntry` gleichgesetzt werden.

Bei Auffälligkeiten muss ein entity-sicheres, deterministisches Prüfskript mit `Decimal` die tatsächlichen Originaleinträge, Parserausgabe und deklarierten Zähler/Summen je Auszug und Währung vergleichen. Der aktuelle Kernparser liefert keine fertigen Summen-/Saldo-Diagnosen; ein Parsererfolg allein ersetzt diese Kontrolle nicht. Geeignete Buchungs-Anfangs-/Endsalden und Soll/Haben-Vorzeichen beachten; keine verfügbaren Salden oder Fremdwährungs-Unterbeträge dazumischen. Ein vorhandenes passendes PDF muss die Bestands-/Betragskontrolle bestätigen.

| Befund | Behandlung |
| --- | --- |
| Original enthält weniger Einträge als sein Zählfeld; alle tatsächlichen Einträge sind vollständig gelesen und erforderliche Summen-/Saldo-/PDF-Kontrollen stimmen | Quellenanomalie als `metadata.note` und sichere Feldevidenz erhalten; allein kein Freigabeblocker |
| Originaleinträge fehlen in der Parserausgabe oder Beträge/Salden widersprechen sich | Offener Prüfpunkt, keine Freigabe |
| Benötigte Kontrollen fehlen oder Sammelbuchung/Währung/Zuordnung bleibt unklar | Ungeklärt lassen, keine vermeintliche Entwarnung |

Nie eine zusätzliche Buchung erfinden oder Original/Zählfelder korrigieren. Eine Null-/Abschlusszeile ist nur bei Beleg eine Erklärung, sonst lediglich eine Hypothese. Andere offene Punkte bleiben bestehen. Die Regel ändert die **Agenteninterpretation**, nicht die Originale oder die Backend-Freigabevalidierung.

Ein PDF ohne eigenen Zeitraumaufdruck darf den ausdrücklich angegebenen Zeitraum eines eindeutig passenden CAMT übernehmen. Konto/Firma, Auszugsidentität, Buchungsbestand und Kontrollwerte müssen übereinstimmen; Datumswidersprüche bleiben offen. CAMT-Dokument-ID, XML-Pfad und Wert in der PDF-Evidenz dokumentieren und beide Dokumente verknüpfen. Nicht aus erster Buchung oder Saldenstichtag einen vermeintlichen Monatsbeginn ableiten; Buchungs- und Valutadatum unterscheiden.

## Fehler und Grenzen

- Unbekannter/fehlender Namespace, kaputtes XML oder fehlender Auszug: `security_status=error`, sichtbarer Fehlergrund, keine Freigabe und kein Datei-/Textzugriff.
- DTD/Entity-Versuch: Abbruch der Auslese, Original bleibt erhalten; keine Netzwerk-/Dateisystemauflösung.
- Uploadlimit standardmäßig 25 MiB. Der Mailimport prüft zusätzlich die gesamte Nachricht vor dem Abruf (50 MiB) und die Anhangsanzahl.
- Nicht unterstützte Mailanhänge bleiben als gesperrte Importfälle mit Herkunft und gesicherten Bytes im technischen `_quarantine`-Bereich erhalten. Überlimit-Nachrichten bleiben unverändert im Postfach mit sichtbarem Fehler/UID.
- Bank-/Depotunterlagen benötigen für die Freigabe bekanntes Konto/Depot und Auszugsbeginn/-ende. Ein Parsererfolg ist kein Nachweis einer richtigen Firmenzuordnung oder vollständigen Buchhaltung.

Tests enthalten synthetisches CAMT, nicht unterstützte Versionen und schädliche XML-Entities. Repräsentative anonymisierte Originaldateien der konkreten Banken gehören zur produktiven Live-Abnahme.
