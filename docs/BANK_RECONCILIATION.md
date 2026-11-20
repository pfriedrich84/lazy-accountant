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
- UI: firmenweiter Zahlungsstand und Bankbewegungsliste, getrennte Hinweise/Referenztreffer, Dokumentdetail mit Quellen, Zuordnung/Aufhebung, Admin-Bankdatenverifikation und CAMT-Abgleich. Listen sind paginiert; Filter/Suche wirken firmenweit vor der Seiteneinteilung. Die UI setzt die Position bei Filter-, Ansichts- und Firmenwechsel zurück.
- Neue Pakete enthalten eingefrorene `Zahlungsstand.csv`, `.xlsx`, `.json`. Zahlungsänderungen erscheinen als `payment_changes` auch im Nachtrag bei unveränderter Dokumentrevision und ohne erneute Originaldatei. Alte ZIPs und Snapshots bleiben bytegleich.

### Gemeinsame Referenz für Zinsen und Kontogebühren

Die Abgleichprojektion `reconciliation-v2` erhält den ausdrücklich im CAMT angegebenen `BkTxCd` (Detail, sonst Buchung). Nur die Kombinationen **`ACMT/MCOP/INTR` mit CRDT** und **`ACMT/MDOP/COMM` mit DBIT** dürfen dieselbe Bankreferenz als zwei unterschiedliche Bewegungen desselben Firmenkontos verwenden. Der interne Schlüssel ergänzt dafür den Geschäftsvorfallcode; Originalreferenz und Originalbytes bleiben unverändert. Beträge, Daten, Zeilenpositionen oder bloße Gegenrichtung werden nicht als Ersatzkennung benutzt.

Reimport, umsortierte/überlappende Dateien und einzelne Teilmengen verwenden dieselben Bewegungen. Wiederholte gleichartige Abschlusszeilen, widersprüchliche Beträge/Daten, fehlende Codes und gewöhnliche Zahlungsreferenzkonflikte bleiben atomar gesperrt. Bestehende Legacy-Bewegungen werden nur anhand ihrer sicherheitsgeprüften Originalquellen qualifiziert; ihre IDs, Quellen und Zahlungshistorie bleiben erhalten. Unbelegte Altidentitäten werden nicht automatisch umgedeutet. Rückbuchungen behalten ihren separaten Identitätsworkflow. Keine allgemeine Referenzkonfliktauflösung und keine zusätzliche Zahlungsfreigabe.

Nach Deployment: das bisher blockierte Original mit aktuellem Prüfstand fachlich freigeben, dann den normalen CAMT-Abgleich mit aktueller Dokumentversion und neuem Idempotenzschlüssel ausführen. Keinen Ersatzbeleg hochladen oder Referenzen im XML erfinden. Ein früherer fehlgeschlagener Abgleich wird nicht automatisch wiederholt; gespeicherte erfolgreiche Idempotenz-Replays bleiben historisch unverändert.

## Bedienung

1. Rechnung und CAMT wie bisher importieren, Firma/Konto zuordnen und Originaldaten prüfen. Das Bankkonto benötigt seine IBAN als `identifier`.
2. Für Automatik: im Rechnungsdetail als Admin eine **unabhängig geprüfte** Geschäftspartner-IBAN mit Begründung bestätigen. Nicht einfach eine im neuen PDF behauptete IBAN übernehmen. Ohne diese Freigabe ist manuelle Zuordnung möglich, aber keine automatische Bestätigung.
3. Am geprüften CAMT-Dokument „CAMT abgleichen“ wählen. Eindeutige Treffer werden bestätigt; Mehrdeutigkeiten und offene Bankbewegungen bleiben unter „Zahlungsstand“ sichtbar.
4. Manuell im Rechnungsdetail eine Bewegung, Betrag und Begründung wählen. Mehrere Rechnungen können nacheinander Anteile derselben Bewegung erhalten; jeder Schritt prüft verfügbare Beträge atomar neu.
5. Eindeutige gebuchte CAMT-Vollrückbuchungen werden automatisch berücksichtigt, einschließlich Quellenlink in der Zahlungshistorie. Bei falscher Zuordnung oder nicht eindeutig maschinell zuordenbarer Rückbuchung: Original prüfen und Zuordnung ggf. begründet aufheben. Die Rechnung wird entsprechend wieder offen/teilweise bezahlt und ggf. überfällig. Keine Historie löschen.
6. Bei Versionskonflikt den aktuellen Stand neu laden und erneut prüfen. Frontend-Wiederholungen nach unbekanntem Fehler verwenden denselben Idempotenzschlüssel, solange der Payload unverändert bleibt.

## REST und MCP

REST und MCP verwenden dieselben Dienste `accounting/reconciliation.py`, `bank_state.py` und `bank_identity.py`. REST-Einstieg ist `/api/reconciliation/<operation>/`.

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
| GET `policy/?company_id=…` | `get_bank_automation_policy` | read |
| POST `policy/` | `set_bank_automation_policy(request=…)` | admin |
| GET `accounts/?company_id=…&period=YYYY-MM` | `get_bank_account_coverage` | read |
| POST `coverage/` | `set_bank_month_coverage(request=…)` | process |
| GET `identity-candidates/?duplicate_id=…` | `get_bank_identity_candidates` | read |
| GET `identity-preview/?duplicate_id=…&canonical_id=…` | `preview_bank_identity_merge` | read |
| POST `identity-merge/` | `merge_bank_transaction_identity(request=…)` | process |
| POST `identity-dispute/` | `dispute_bank_transaction_identity(request=…)` | process |
| GET `identity-history/?transaction_id=…` | `get_bank_identity_history` | read |

### Firmenweite Listenfilter (Folgearbeit)

Optionale Parameter gelten identisch für REST und die genannten MCP-Werkzeuge; ältere Aufrufe ohne Filter bleiben gültig:

- Rechnungen: `state=all|open|overdue|unresolved|review|unmatched|paid|partially_paid`, `kind=incoming_invoice|outgoing_invoice`, `search` und `as_of=YYYY-MM-DD`.
- Bank: `state=all|open|unallocated|review|pending|reversed|merged`, optional `account_id`, `direction=CRDT|DBIT` und `search`. Fremde Konten liefern 404. `reversed` bezeichnet die durch Bankrückbuchung aufgehobene **Originalbewegung**, nicht jede ungeklärte Rückbuchungszeile.
- `search` (max. 200 Zeichen) sucht Rechnungsnummer, Originalname und Rechnungspartei bzw. Verwendungszweck, Bankreferenz, Bankpartei und IBAN; keine unbeschränkte Volltext-/OCR-Suche.
- `open` umfasst unbezahlte/teilbezahlte/ungeklärte Rechnungen; bei Bankbewegungen verfügbaren Rest **oder** Prüfbedarf. `unmatched` bezeichnet Rechnungen ohne aktive Zuordnung, nicht einen Nachweis des Nichtbezahltseins. `unallocated` bedeutet technisch verfügbarer Rest; pending/ungeklärte Quellen bleiben trotzdem durch die bestehenden Zuordnungsguards gesperrt.
- `review_reasons` enthält konkrete Prüfgründe: ungeklärter Betrag/Währung, unbestätigte Rechnung, fehlende Fälligkeit, bestehende Dokument-/Bankwidersprüche, pending-Status, ungeklärter Rückbuchungsbezug oder fehlende Verwendungszweckreferenz. Das ist keine neue Sicherheitsskala und kein vollständiger globaler Kandidatenlauf; mehrdeutige Rechnungsreferenzen erklärt weiterhin der separate Kandidatendienst.
- Filter werden **vor** Pagination ausgewertet; `cursor` ist ein Offset in der gefilterten Ergebnismenge, `limit` 1–100. `filters` spiegelt die Auswahl zurück; Rechnungen liefern einen gemeinsamen `as_of`-Stichtag. Bei Änderungen zwischen Seiten neu laden; Offset-Pagination ist kein eingefrorener Export-Snapshot.
- Suche/Firma/Art/Konto/Richtung werden in der Datenbank eingegrenzt. Geld-/Prüfprädikate verwenden die gemeinsame Decimal-Projektion statt unsicherer SQL-Casts ungeklärter JSON-Metadaten. Batches von 100 und Prefetch der Zahlungshistorie, SQL-Aggregation verfügbarer Bankbeträge und Rückbuchungs-Subquery verhindern einfache N+1-Abfragen. Ein seltener Treffer oder großer Offset kann weiterhin einen großen Firmenbestand durchlaufen. Synthetische Querybudgettests sind **kein** Lastnachweis; weitergehende Index-/materialisierte Projektionsarbeit bleibt offen.

`auto_confirm=false` unterbindet neue automatische Rechnungszuordnungen, **nicht** die Berichtigung bereits bankbelegter Deckung durch eine eindeutig gebuchte Rückbuchung. Abgleichergebnisse enthalten zusätzlich `applied_reversals`; Bankbewegungen weisen `reversal_of_id`, `reversed_by_id` und Prüfhinweise aus. Statushistorien enthalten den aufhebenden Bankumsatz und seine Originalquellen.

Schreibschemas in `payment_schemas.py` verbieten unbekannte Felder. Ein beliebiger `paid=true`-Schalter existiert nicht. Normalisierung erhält `document_id`, `base_version`, `auto_confirm` (Default true) und `idempotency_key`. Zuordnung erhält `transaction_id`, `document_id`, `amount` als Dezimalstring, `bank_version`, `document_version`, `reason`, `idempotency_key`. Aufhebung erhält `allocation_id`, `bank_version`, `reason`, `idempotency_key`.

Firmen-/Tokenrechte werden vor jedem Zugriff und auch vor Idempotenz-Replay geprüft. Schreibvorgänge sperren in der Reihenfolge Actor, Firma, Bankbewegung, Rechnung (bei Dokumentaktionen Actor, Firma, Dokument). Summen werden unter Sperre neu berechnet. Identischer Schlüssel/identischer Payload hat einen Effekt; abweichender Payload gibt 409. Nicht authentisierte oder fremde Zugriffe erhalten keine Bankdaten. UI- oder Agentenrechte autorisieren niemals Zahlungen oder Mahnungen.

### Persistente Automatikpolicy und kontoweise Monatsabdeckung

`policy` speichert die Firmenpräferenz für neue konservative Rechnungszuordnungen. Ohne explizite Konfiguration bleibt die bereits vom Nutzer freigegebene Automatik aktiv (`version=0`, `persisted=false`); Konfigurationen sind dauerhaft versioniert und auditiert. `enabled=false` hat Vorrang vor `auto_confirm=true` am einzelnen Abgleich. Umgekehrt deaktiviert `auto_confirm=false` die Rechnungsautomatik für diesen Aufruf auch bei aktiver Firmenpolicy. Das Ändern der Policy startet **keinen** Abgleich und erzeugt keine Zahlung. Eindeutig belegte Bankrückbuchungen berichtigen vorhandene Deckung weiterhin unabhängig davon. Die Policy ist keine Überweisungs-, Versand- oder neue Gegenparteifreigabe.

Policy-Schreiben braucht `company_id`, `expected_version` (0 für noch keine Konfiguration), `enabled`, Begründung und Idempotenzschlüssel; nur Admin. Abgleichergebnisse enthalten den dabei geltenden Policystand und `auto_confirm_effective`. Historische idempotente Retries liefern den damaligen Effekt, nicht eine neue Ausführung mit inzwischen geänderter Policy.

`accounts` trennt je Bankkonto den **beobachteten Datenstand** (letztes gebuchtes Bewegungsdatum und Anzahl/pending über alle vorhandenen Monate) von der **Abdeckung des gewählten Monats**. Ein Datum allein beweist keine vollständige Monatsabdeckung. Ohne Auszug/Erklärung bleibt sie ungeklärt. Konten sind mit `cursor`/`limit` (1–100) paginiert; maximal 100 Monatsquellen und die letzten 100 Auditereignisse je Erklärung werden angezeigt. Eine größere Quellenmenge wird sichtbar als unvollständige Übersicht/Prüfbedarf gemeldet, nie still als sicher vollständig ausgegeben. Gesperrte normalisierte Quellen sperren auch die ausgegebenen Bankaggregate.

Die bereits bestätigte Produktvorgabe bleibt erhalten: **geprüfte Monatsauszüge gelten für ihren zugeordneten Monat als vollständig**, ohne erneute Pflichtbestätigung nur wegen unscharfer Monatsgrenzen oder Erstellung vor Monatsende. Die Projektion nennt diese Grundlage ausdrücklich `accepted_monthly_statement_convention`, nicht einen bankseitig bewiesenen lückenlosen Zeitraum. Parserdaten, Dokumente und alte Pakete werden dafür nicht umgeschrieben. Konkrete offene Punkte, Seitenlücken, Quellwidersprüche oder Sicherheitssperren bleiben sichtbarer Prüfbedarf.

Zusätzlich können Nutzer mit `process` eine quellenbezogene Monatsvollständigkeit ausdrücklich dokumentieren oder den Monat als `disputed`/`unknown` markieren. Schreiben braucht Firma/Konto/Monat, `expected_version`, Zustand, Begründung, Idempotenzschlüssel und konkrete `document_ids` samt `document_versions`. Eine Bestätigung braucht mindestens einen aktiven, geprüften, sauberen CAMT-/PDF-Auszug desselben Firmenkontos und Monats. Sie hebt **keine** Unsicherheiten einer PDF-Buchungsextraktion auf und macht keine Zahlung bankbelegt. Fehlende exakte Kalendergrenzen sind allein kein Ablehnungsgrund. Veraltete Quellen-/Erklärungsversion => 409; fremde Quellen/Konten => 404; konkrete offene Quellenwidersprüche verhindern Bestätigung.

Erklärungen bleiben mit Benutzer, Begründung, Quellenversionen/-prüfsummen und Historie erhalten. Eine spätere Quellsperre, ein Ausschluss oder Firmen-/Konten-/Monatswechsel macht die **wirksame** bestätigte Abdeckung strittig, ohne die frühere Erklärung zu löschen. Eine reine Namensrevision oder unscharfe Datumsgrenze invalidiert sie nicht. Wiederherstellung erzeugt keine Zahlung. Der bewusste Zustand `unknown`/`disputed` überschreibt die Monatskonvention, bis ein neuer begründeter Auftrag erfolgt. Die UI zeigt diese Zustände und bietet versionierte Aktionen statt blinder Wiederholung nach Versionskonflikt.

Sperrreihenfolge ist Actor → Firma → Quellendokumente; REST/MCP/UI verwenden denselben Dienst `bank_state.py`. Kontrollereignisse und idempotente Receipts werden atomar mit der Policy/Erklärung gespeichert. Historische Zahlungs-/Paket-Snapshots und Originale bleiben unverändert. Migration `0010` vereinigt die beiden bereits vorhandenen, inhaltsgleichen `0009`-Mergepfade aus Draft und main; `0011` ergänzt nur neue Kontrolltabellen. Keine bestehenden Erklärungen oder Zahlungen werden erfunden.

### Explizite CAMT-Identitätsauflösung (Folge-Draft)

Migration `0012` ergänzt nullable Verknüpfungen, dauerhafte Identitätsprüfhinweise und `BankIdentityResolution`. Bestehende Bewegungen, Bankdaten, Quellenzuordnungen und Zahlungen werden nicht umgeschrieben; es findet kein automatischer Identitätsbackfill statt.

Die UI unter „Bankbewegungen“ und REST/MCP bieten genau eine konservative Paarauflösung: **eine ungenutzte, quellenspezifische Beobachtung mit ausschließlich fehlender Bankkennung** kann einer bereits bankidentifizierten, gebuchten, widerspruchsfreien Bewegung desselben Firmenkontos zugeordnet werden. Bankseitige **TxId und Gegenkonto** müssen übereinstimmen, ebenso Betrag, Währung, Richtung, Buchungs-/Wertstellungsdatum, Partei und Verwendungszweck. Die Originale müssen aktiv, geprüft, sauber und CAMT sein. Betragsgleichheit oder `EndToEndId` allein reicht nicht. Weitere unverknüpfte Bewegungen mit derselben TxId, fremde Konten/Firmen, pending-/Rückbuchungsfälle, bereits verwendete Beobachtungen **einschließlich aufgehobener Zahlungshistorie**, Ketten und Widersprüche bleiben gesperrt. Bereits korrekt vorhandene Zahlungen an der kanonischen Bewegung dürfen bestehen bleiben.

Kandidaten/Vorschau sind keine Freigabe und keine Reservierung: Schreiben braucht beide Bewegungs- und sämtliche aktuellen Quellenversionen, Begründung und Idempotenzschlüssel. Actor → Firma → Bankbewegungen (stabile ID-Reihenfolge) → Originaldokumente werden gesperrt; danach werden hashgeprüfte Originalbytes erneut deterministisch geparst und die konkreten Ntry-/TxDtls-Belegstellen gegen die gespeicherten Fakten geprüft. Geänderte Versionen/Originalwidersprüche => 409, fremde Bewegung => 404, Quarantäne => 423. Kein Client darf Bankfakten überschreiben oder Quellenbeweise selbst behaupten. Der Prüfstand speichert Benutzer, Grund, Regelversion, Originalprüfsummen, Locator und Quellenversionen. Quellen bleiben bei ihrer ursprünglichen Beobachtung, bestehende Allocations und deren eingefrorene Evidenz bleiben unverändert.

Die verknüpfte Beobachtung bleibt in `all`/`merged` und an ihren Originalen sichtbar, hat aber immer **verfügbar = 0** und kann keine Zahlung erhalten. Ihre ursprüngliche Missing-ID-Prüfmeldung bleibt als `original_issues` und in der Datenbank erhalten, nicht als weiterhin offener effektiver Prüffall. Kanonische Quellenprojektionen und neue Allocation-Evidenz umfassen auch die verknüpften Originale (`observation_transaction_id` erhält den ursprünglichen Eigentümer). Normalisierung erzeugt keine zweite verbrauchbare Bewegung; die verknüpfte Beobachtung konkurriert auch nicht als zweites Original bei eindeutigen Bankrückbuchungen. Kontoaggregate zählen kanonische Bewegungen und verknüpfte Beobachtungen getrennt. Das Addieren aller sichtbaren Rohzeilen ist kein zulässiger Zahlungssaldo.

Eine explizite **Beanstandung** mit beiden aktuellen Bewegungsversionen markiert den Identitätsbezug und die kanonische Bankdeckung dauerhaft als strittig. Sie lässt Betrag, Quellen, Zahlungshistorie und Verknüpfung bestehen: keine automatische Entflechtung, keine Löschung und kein erneutes Freigeben bereits verbrauchbaren Geldes. Reimport entfernt diese Hinweise nicht. Ein danach nötiger finanzieller Korrektur-/Umbuchungsworkflow bleibt separat offen. Eine Sicherheitsbeanstandung darf auch ohne erneuten Zugriff auf ein gesperrtes Original gespeichert werden; Bankstatus und Audit mit Originalbezügen bleiben dann sicherheitsgesperrt. Quarantäne einer verknüpften Quelle sperrt auch die kanonische Bankdeckung.

Bankversionen und Bankdeckung gehen in neue Zahlungsstände/Nachträge ein; alte Paketbytes bleiben unverändert. Identitätsaktionen selbst erzeugen oder widerrufen keine Zahlung (`payment_effect=none`) und führen keine neue automatische Rechnungszuordnung aus. Danach bewusst neu gestartete Abgleiche verwenden weiterhin die bestehende Automatikpolicy und deren konservative Regeln.

Begrenzungen: maximal 20 Kandidaten mit sichtbarem Trunkierungshinweis, 100 eindeutige Originalquellen pro Schreibauftrag, insgesamt höchstens das konfigurierte Datei-Bytebudget (standardmäßig 25 MiB) und 10.000 geparste Buchungszeilen pro Originalprüfung; Historie maximal 100 Ereignisse. Überschreitungen werden gesperrt, nicht still als geprüft ausgegeben. Mehrfach-/Gruppenidentitäten, finanziell bereits verwendete Doppelbeobachtungen, geänderte Bankreferenzen, Feldkorrekturen, PDF-Verknüpfung und neue Layouts sind damit ausdrücklich nicht allgemein gelöst. Echte anonymisierte Bankabnahme bleibt offen.

### Sicherheitssperren nach #18

Die Bankadapter umgehen die Quarantäne nicht: Kandidaten und Rechnungslisten berücksichtigen nur aktuell als sauber markierte Dokumente mit passender Scan-Prüfsumme. Direkter Zahlungsstatus und neue Zuordnungen prüfen die Rechnung und alle beteiligten Bank-/Rückbuchungsquellen. Bei später gesperrten Quellen liefern die betroffenen Banklisten/Statusprojektionen einen kontrollierten **423**, statt alte extrahierte Bankdaten oder eine sichere Deckung zu behaupten. Auch ein erneuter Firmenabgleich wird bis zur Quellenprüfung gesperrt, wenn bereits normalisierte Bankquellen nicht mehr sauber sind. Historie/Originale werden dabei nicht gelöscht oder still aufgehoben. Der Sicherheitsworkflow aus #18 bleibt zuständig; kein neuer Freigabeweg im Bankdienst.

## Migration und bestehende Integrationen

Die Migrationen erzeugen Tabellen/Felder, keine Zahlungseffekte. `0008` vereinigt Dokumentausschluss und Bankzweig; `0009` vereinigt den inzwischen gemergten Sicherheitszweig #18 additiv. `0006` vereinigt den Bank- und Übergabenamen-Migrationszweig; `0007` ergänzt Rückbuchungsreferenzen und erhält beim Upgrade vorheriger Draft-Beobachtungen deren IDs/Quellen. Original und Rückbuchung haben getrennte interne Identitäten, auch wenn die Bank dieselbe Bankreferenz wiederholt. Bestehende Dokumente, Dateipfade, Originale und historische Parserresultate werden nicht umgeschrieben. `save_document_result` kann Zahlungsdaten nicht überschreiben. Finanzwirksame Änderungen referenzierter Rechnungen bzw. Firmen-/Konto-/Art-/Dublettenänderungen referenzierter Quellen werden derzeit mit 409 blockiert; der umfassende Korrekturworkflow ist noch offen. Auch aufgehobene Zuordnungen behalten ihren Dokumentbezug geschützt.

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

Dieser Stand erzeugt **keinen zweiten fachlichen Invoice-Stamm**: `PaymentAllocation.document_id` ist zunächst der Adapter für importierte Verpflichtungen. #9 muss bei Einführung seines gemeinsamen Payment-/Verpflichtungsmodells dieselben importierten Dokumentidentitäten übernehmen und fachliche Invoice und archiviertes PDF auf **eine** Verpflichtung abbilden. Bank-only-Allocations sind dann kontrolliert mit Herkunft zu übernehmen, nicht parallel zu einer zweiten Zahlung zu zählen. Manuelle Nichtbankzahlungen dürfen vorher nicht unabhängig eingeführt werden. Customer-Stammverwaltung ist ausdrücklich weiterhin Teil von #9, nicht durch `VerifiedBankParty` ersetzt. #8 ergänzt Organization-Grenzen über die bestehenden Company-Bezüge. Der Ausschluss aus #7 verwendet denselben Firma-/Dokumentsperrbereich: normalisierte Bankquellen und Rechnungen mit Zahlungshistorie (auch nach Aufhebung) werden mit begründetem 409 geschützt. Ausgeschlossene Dokumente erzeugen keine neuen Normalisierungen, Zuordnungen oder Kandidaten; Restore erzeugt keine Zahlung. Echte Nichtbelege bleiben reversibel ausschließbar.

## Verbleibend / vor vollständiger Abnahme von #10

- PDF-only-Extraktion und kontrollierte Feldbestätigung, Quellenzusammenführung CAMT+PDF.
- Bankkennungen nach echten anonymisierten Bankfixtures qualifizieren. Der aktuelle konservative Bankreferenzschlüssel kann bei geänderten Darstellungen einen Konflikt melden; keine automatische heuristische Zusammenführung. Die konservative, explizite Missing-ID→bankidentifizierte-Paarauflösung ist im Folge-Draft enthalten. Gruppen-/Mehrfachkonflikte, bereits finanziell verwendete Dubletten und geänderte Bankreferenzen benötigen weiterhin einen erweiterten Auflösungs-/Korrekturworkflow.
- Teilrückbuchungen, mehrfach verwendete Originalreferenzen und banklayoutspezifische Rückgabeinformationen außerhalb der konservativ unterstützten `RvslInd`-/`RtrInf`-/Bankreferenz-/TxId-Regel bleiben manuell zu prüfen. Kein automatischer anteiliger Saldoausgleich aufgrund Betrag oder Rechnungsnummer.
- Vollständiger fachlicher Storno-/Gutschrift-/Erstattungsworkflow, manuelle Nichtbankzahlungen und deren spätere Bankbestätigung gemeinsam mit #9. Dieser CAMT-Stand deckt normale ER/AR und bankbasierte Teil-/Sammelzahlung ab, keine komplette Buchhaltung.
- Weitergehende Auszugs-/Saldo-/Seitenlückenqualifikation anhand realer anonymisierter Bankbeispiele. Kontoweiser beobachteter Datenstand, Monatskonvention, explizite quellenbezogene Erklärungen und persistente Firmen-Automatikpolicy sind im Folge-Draft enthalten; kein Nachweis bankseitig lückenloser Abdeckung und kein Ersatz für reale Abnahme.
- Spezifischer finanzieller Korrekturworkflow statt derzeitiger 409-Sperre. Die Sicherheitsintegration mit Dokumentausschluss/Restore aus #7 ist enthalten; referenzierte Historie kann noch nicht fachlich umgebucht werden.
- Weitergehende Such-/Auswertungsoptimierung bei großen Beständen, breitere UI-/Browserabnahme und Lasttests. Firmenweite serverseitige Grundfilter sind in der Folgearbeit enthalten.
- PostgreSQL-Parallelitätstest ist vorhanden, wird unter SQLite ausdrücklich übersprungen. Er muss vor Merge gegen PostgreSQL erfolgreich laufen. SQLite-Ergebnisse beweisen keine Row-Lock-Sicherheit.
- Kein Deployment/keine produktive Migration im Rahmen dieses PRs.

## Prüfung

Backend: bestehende Suite plus synthetische ER-/AR-, Auto-/Fehlzuordnungs-, Teil-/Sammelzahlungs-, Reimport-, Pending→Booked-, Audit-/Widerrufs-, Rechte-/Scope-, Versions-/Idempotenz-, Paket-/Nachtrags- und Backfilltests. Die neuen MCP-Werkzeuge sind zusätzlich über echten Streamable-HTTP-Transport geprüft. Frontend: Typprüfung, Vitest einschließlich Zahlungsanzeige/Berechtigungen/CAMT-Auftrag sowie Produktionsbuild. Konkrete Ergebnisse stehen im PR; keine Testaussage für nicht ausgeführte PostgreSQL-/Browser-/Produktivumgebungen.
