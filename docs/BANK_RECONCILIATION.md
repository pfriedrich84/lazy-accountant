# Bankabgleich – erster CAMT-Stand zu #10

## Freigegebener Produktumfang

In der Implementierungssession ausdrücklich entschieden:

- Eindeutig belegte Treffer dürfen automatisch bestätigt werden, nicht nur vorgeschlagen.
- CAMT hat Vorrang. PDF-only bleibt erwünscht, ist aber nachrangig.
- Aktuell kein Bedarf an Skonto, Gebührenausgleich, FX, Kreditkarten- oder Providerabstimmung. Abweichungen werden **nicht** still ausgeglichen.
- Überfälligkeit nur anzeigen; keine Mahnentwürfe, kein Mahnversand.
- Eindeutig im CAMT referenzierte Rückbuchungen automatisch berücksichtigen; nach erfolgreicher CAMT-Abnahme mergen und verbleibende Punkte in #10 offen halten.

Dies ist ein erster, separat prüfbarer Implementierungsstand, **keine vollständige Erledigung von #10**. Keine Überweisungen und keine Bankanbindung. Kein Versprechen rechtlich endgültiger Erfüllung. SaaS-Organisation, Rechnungskunde und Bankgegenpartei sind unterschiedliche Begriffe; die neuen Daten sind zunächst wie die bestehende Anwendung strikt firmenbezogen. #8 und #9 bleiben separate Vorhaben.

## Was vorhanden ist

- Additive Migration `0005_bank_reconciliation`: kanonische Bankbewegungen, n:m-Quellenbelege, positive Teilzuordnungen und explizit verifizierte Gegenpartei-/IBAN-Paare.
- Neue deterministische CAMT-Projektion aus unveränderten Originalbytes. Der bisherige `parse_camt` und vorhandene `parser_result` bleiben kompatibel und unverändert.
- Expliziter Abgleich geprüfter, einer Firma und einem Bankkonto zugeordneter CAMT-Dokumente. Die Konto-IBAN muss mit der Originaldatei übereinstimmen. `BOOK` ist erforderlich, um Zahlungen zu belegen; pending/unknown bleiben sichtbar, ohne Deckung zu erzeugen.
- Ntry-/TxDtls-Provenienz. Vollständig abstimmbare Sammelbuchungen werden auf Detailbeträge aufgeteilt, ohne den Parent zusätzlich zu zählen. Widersprüchliche Details werden als gesperrter Prüffall auf Parent-Ebene erhalten.
- Überlappende Quellen mit gleicher Bankreferenz im selben Firmen-/Kontokontext zählen einmal. Eine fehlende/unbrauchbare Bankreferenz erzeugt eine quellenspezifische Beobachtung **mit Zuordnungssperre**; der Fallbackhash wird nicht als bewiesene Identität verkauft. Widersprüchliche Referenzen brechen den Abgleich atomar mit Konflikt ab, statt bestehende Daten zu überschreiben.
- Bank-only-Zuordnungen für importierte Eingangs- **und** Ausgangsrechnungen. Manuelle Teil- und Sammelzahlungen durch mehrere atomare Zuordnungen. Nicht verbrauchter Betrag bleibt an der Bewegung verfügbar. Kein Überschreiten von Zahlung oder Rechnungsrest.
- Konservative Automatik: exakte Rechnungsreferenz mit Wortgrenzen, eindeutiger Rechnungsbestand, passende Richtung/Währung/voller Rest, geprüftes Dokument, gebuchte widerspruchsfreie Bankquelle und ausdrücklich durch Admin verifizierte Gegenpartei **und** IBAN. Name und Betrag allein genügen nie. Konkurrierende Bankbewegungen, eigene Konten, frühere aufgehobene Zuordnungen oder unklare Identitäten verhindern automatische Bestätigung. Die Regel ist absichtlich konservativ; keine unsichtbare Betrags- oder Namensähnlichkeit.
- Bankdatenfreigaben können ausdrücklich widerrufen werden. Widerruf sperrt künftige Automatik, löscht aber keine frühere Bankzahlung. Erneute Verifikation erzeugt einen neuen Auditdatensatz. Es gibt keine automatische Stammdatenübernahme aus Rechnungen.
- Gebuchte explizite Rückbuchungen (`RvslInd` oder `RtrInf`) werden vor neuen Rechnungszuordnungen berücksichtigt: eindeutige ursprüngliche Bankreferenz oder eindeutige `TxId` plus identisches Gegenkonto, gleiche Firma/eigenes Konto/Währung/voller Betrag, Gegenrichtung und plausibles Buchungsdatum. Widersprüchliche Gegenparteien, mehrere Original-/Rückbuchungskandidaten und Teilrückbuchungen bleiben Prüffälle. `EndToEndId`, Verwendungszweck, Betrag oder Name allein reichen ausdrücklich nicht. Die Originalbewegung wird gesperrt, aktive Zuordnungen werden mit konkretem Rückbuchungsbeleg auditierbar aufgehoben; Rechnungen öffnen sich entsprechend erneut. Auch vor dem Original importierte Rückbuchungen werden nach Vorliegen des Originals berücksichtigt. Pending-Rückbuchungen erzeugen keinen Widerruf. Ein ungeklärter belastbarer Rückbuchungshinweis führt zu Bankdeckung `disputed` statt einer sicheren Zahlungsbehauptung.
- Manuelle Aufhebung mit Zeitpunkt, Benutzer und Grund. Reimport stellt eine aufgehobene Zuordnung nicht still wieder her. Zuordnungen speichern ursprüngliche Dokument-/Bankversion, Quellen-IDs, Freigabe-IDs und Regelversion.
- Unabhängige Projektion `unpaid/partially_paid/paid/unresolved`, Restbetrag, Fälligkeit, `overdue=true/false/null`, Bankdeckung `none/partial/complete/unknown/disputed` und Berechnungsstichtag. Fehlende Fälligkeit ist ungeklärt; am Fälligkeitstag noch nicht überfällig. Datenstand bedeutet nicht, dass außerhalb des vorhandenen Bankbestands keine Zahlung erfolgt ist.
- UI: firmenweiter Zahlungsstand und Bankbewegungsliste, getrennte Hinweise/Referenztreffer, Dokumentdetail mit Quellen, Zuordnung/Aufhebung, Admin-Bankdatenverifikation und CAMT-Abgleich. Listen sind paginiert; UI-Filter wirken ausdrücklich auf die aktuelle Seite.
- Neue Pakete enthalten eingefrorene `Zahlungsstand.csv`, `.xlsx`, `.json`. Zahlungsänderungen erscheinen als `payment_changes` auch im Nachtrag bei unveränderter Dokumentrevision und ohne erneute Originaldatei. Alte ZIPs und Snapshots bleiben bytegleich.

## Bedienung

1. Rechnung und CAMT wie bisher importieren, Firma/Konto zuordnen und Originaldaten prüfen. Das Bankkonto benötigt seine IBAN als `identifier`.
2. Für Automatik: im Rechnungsdetail als Admin eine **unabhängig geprüfte** Geschäftspartner-IBAN mit Begründung bestätigen. Nicht einfach eine im neuen PDF behauptete IBAN übernehmen. Ohne diese Freigabe ist manuelle Zuordnung möglich, aber keine automatische Bestätigung.
3. Am geprüften CAMT-Dokument „CAMT abgleichen“ wählen. Eindeutige Treffer werden bestätigt; Mehrdeutigkeiten und offene Bankbewegungen bleiben unter „Zahlungsstand“ sichtbar.
4. Manuell im Rechnungsdetail eine Bewegung, Betrag und Begründung wählen. Mehrere Rechnungen können nacheinander Anteile derselben Bewegung erhalten; jeder Schritt prüft verfügbare Beträge atomar neu.
5. Eindeutige gebuchte CAMT-Vollrückbuchungen werden automatisch berücksichtigt, einschließlich Quellenlink in der Zahlungshistorie. Bei falscher Zuordnung oder nicht eindeutig maschinell zuordenbarer Rückbuchung: Original prüfen und Zuordnung ggf. begründet aufheben. Die Rechnung wird entsprechend wieder offen/teilweise bezahlt und ggf. überfällig. Keine Historie löschen.
6. Bei Versionskonflikt den aktuellen Stand neu laden und erneut prüfen. Frontend-Wiederholungen nach unbekanntem Fehler verwenden denselben Idempotenzschlüssel, solange der Payload unverändert bleibt.

## REST und MCP

Alle Operationen rufen denselben Service `accounting/reconciliation.py` auf. REST-Einstieg ist `/api/reconciliation/<operation>/`.

| REST | MCP | Recht |
| --- | --- | --- |
| GET `transactions/?company_id=…&cursor=0&limit=50` | `list_bank_transactions` | read |
| GET `invoices/?company_id=…&cursor=0&limit=50` | `list_invoice_payment_statuses` | read |
| GET `status/?document_id=…&as_of=YYYY-MM-DD` | `get_invoice_payment_status` | read |
| GET `candidates/?transaction_id=…` | `get_payment_candidates` | read |
| POST `normalize/` | `reconcile_bank_document(request=…)` | process |
| POST `allocate/` | `confirm_payment_allocation(request=…)` | process |
| POST `reverse/` | `reverse_payment_allocation(request=…)` | process |
| GET `verified-parties/?company_id=…` | `list_verified_bank_parties` | read |
| POST `verify-party/` | `verify_bank_party(request=…)` | admin |
| POST `revoke-party/` | `revoke_bank_party(request=…)` | admin |

`auto_confirm=false` unterbindet neue automatische Rechnungszuordnungen, **nicht** die Berichtigung bereits bankbelegter Deckung durch eine eindeutig gebuchte Rückbuchung. Abgleichergebnisse enthalten zusätzlich `applied_reversals`; Bankbewegungen weisen `reversal_of_id`, `reversed_by_id` und Prüfhinweise aus. Statushistorien enthalten den aufhebenden Bankumsatz und seine Originalquellen.

Schreibschemas in `payment_schemas.py` verbieten unbekannte Felder. Ein beliebiger `paid=true`-Schalter existiert nicht. Normalisierung erhält `document_id`, `base_version`, `auto_confirm` (Default true) und `idempotency_key`. Zuordnung erhält `transaction_id`, `document_id`, `amount` als Dezimalstring, `bank_version`, `document_version`, `reason`, `idempotency_key`. Aufhebung erhält `allocation_id`, `bank_version`, `reason`, `idempotency_key`.

Firmen-/Tokenrechte werden vor jedem Zugriff und auch vor Idempotenz-Replay geprüft. Schreibvorgänge sperren in der Reihenfolge Firma, Bankbewegung, Rechnung. Summen werden unter Sperre neu berechnet. Identischer Schlüssel/identischer Payload hat einen Effekt; abweichender Payload gibt 409. Nicht authentisierte oder fremde Zugriffe erhalten keine Bankdaten. UI- oder Agentenrechte autorisieren niemals Zahlungen oder Mahnungen.

## Migration und bestehende Integrationen

Die Migrationen erzeugen Tabellen/Felder, keine Zahlungseffekte. `0006` vereinigt den Bank- und Übergabenamen-Migrationszweig; `0007` ergänzt Rückbuchungsreferenzen und erhält beim Upgrade vorheriger Draft-Beobachtungen deren IDs/Quellen. Original und Rückbuchung haben getrennte interne Identitäten, auch wenn die Bank dieselbe Bankreferenz wiederholt. Bestehende Dokumente, Dateipfade, Originale und historische Parserresultate werden nicht umgeschrieben. `save_document_result` kann Zahlungsdaten nicht überschreiben. Finanzwirksame Änderungen referenzierter Rechnungen bzw. Firmen-/Konto-/Art-/Dublettenänderungen referenzierter Quellen werden derzeit mit 409 blockiert; der umfassende Korrekturworkflow ist noch offen. Auch aufgehobene Zuordnungen behalten ihren Dokumentbezug geschützt.

Expliziter Backfill, **standardmäßig Dry-Run mit DB-Rollback**, mit vorhandenen Firmenrechten:

```sh
uv run python backend/manage.py reconcile_bank_documents --user-id USER --company-id COMPANY
# Nach Prüfung: Quellen normalisieren, keine neuen Rechnungszuordnungen automatisch bestätigen
# Eindeutig gebuchte Rückbuchungen berichtigen dabei trotzdem bereits vorhandene Deckung
uv run python backend/manage.py reconcile_bank_documents --user-id USER --company-id COMPANY --apply
# Nur bei bewusst gewollter Automatik zusätzlich --auto-confirm
```

Der Bericht nennt Dokument-IDs, normalisierte Bewegungen, Bestätigungen und Fehler. Der Backfill ist anhand Dokumentversion und Modus idempotent. Eine spätere bewusste Neuberechnung nach Bankdatenfreigabe nutzt den normalen Abgleich mit neuem Auftragsschlüssel. Dies ist kein Scheduler und verändert keine Orca-Konfiguration.

### Vertrag mit #9

Dieser Stand erzeugt **keinen zweiten fachlichen Invoice-Stamm**: `PaymentAllocation.document_id` ist zunächst der Adapter für importierte Verpflichtungen. #9 muss bei Einführung seines gemeinsamen Payment-/Verpflichtungsmodells dieselben importierten Dokumentidentitäten übernehmen und fachliche Invoice und archiviertes PDF auf **eine** Verpflichtung abbilden. Bank-only-Allocations sind dann kontrolliert mit Herkunft zu übernehmen, nicht parallel zu einer zweiten Zahlung zu zählen. Manuelle Nichtbankzahlungen dürfen vorher nicht unabhängig eingeführt werden. Customer-Stammverwaltung ist ausdrücklich weiterhin Teil von #9, nicht durch `VerifiedBankParty` ersetzt. #8 ergänzt Organization-Grenzen über die bestehenden Company-Bezüge; #7 muss Ausschlüsse finanziell referenzierter Quellen mit diesem Guard abstimmen.

## Verbleibend / vor vollständiger Abnahme von #10

- PDF-only-Extraktion und kontrollierte Feldbestätigung, Quellenzusammenführung CAMT+PDF.
- Bankkennungen nach echten anonymisierten Bankfixtures qualifizieren. Der aktuelle konservative Bankreferenzschlüssel kann bei geänderten Darstellungen einen Konflikt melden; keine automatische heuristische Zusammenführung. Fehlende Identitäten benötigen noch einen expliziten Auflösungsworkflow.
- Teilrückbuchungen, mehrfach verwendete Originalreferenzen und banklayoutspezifische Rückgabeinformationen außerhalb der konservativ unterstützten `RvslInd`-/`RtrInf`-/Bankreferenz-/TxId-Regel bleiben manuell zu prüfen. Kein automatischer anteiliger Saldoausgleich aufgrund Betrag oder Rechnungsnummer.
- Vollständiger fachlicher Storno-/Gutschrift-/Erstattungsworkflow, manuelle Nichtbankzahlungen und deren spätere Bankbestätigung gemeinsam mit #9. Dieser CAMT-Stand deckt normale ER/AR und bankbasierte Teil-/Sammelzahlung ab, keine komplette Buchhaltung.
- Kontoweise Abdeckungs-/Vollständigkeitsanzeige und persistente Freigabepolicy je Firma. Kein erneutes Grundsatznachfragen allein wegen unscharfer Monatsgrenzen; aber auch keine automatische Behauptung vollständiger Abdeckung.
- Spezifischer Korrekturworkflow statt derzeitiger 409-Sperre; Integration mit dem noch ausstehenden Dokumentausschluss aus #7.
- Firmenweite serverseitige OP-Filter, detaillierte Such-/Auswertungsoptimierung bei großen Beständen, breitere UI-/Browserabnahme und Lasttests.
- PostgreSQL-Parallelitätstest ist vorhanden, wird unter SQLite ausdrücklich übersprungen. Er muss vor Merge gegen PostgreSQL erfolgreich laufen. SQLite-Ergebnisse beweisen keine Row-Lock-Sicherheit.
- Kein Deployment/keine produktive Migration im Rahmen dieses PRs.

## Prüfung

Backend: bestehende Suite plus synthetische ER-/AR-, Auto-/Fehlzuordnungs-, Teil-/Sammelzahlungs-, Reimport-, Pending→Booked-, Audit-/Widerrufs-, Rechte-/Scope-, Versions-/Idempotenz-, Paket-/Nachtrags- und Backfilltests. Die neuen MCP-Werkzeuge sind zusätzlich über echten Streamable-HTTP-Transport geprüft. Frontend: Typprüfung, Vitest einschließlich Zahlungsanzeige/Berechtigungen/CAMT-Auftrag sowie Produktionsbuild. Konkrete Ergebnisse stehen im PR; keine Testaussage für nicht ausgeführte PostgreSQL-/Browser-/Produktivumgebungen.
