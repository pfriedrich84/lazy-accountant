# Beleggebundene Fremdwährungsdeckung (bank-fx-v1)

Es werden keine Zahlungen ausgelöst und keine Live-Kurse abgefragt. Der bestehende
Gleichwährungsabgleich und seine Automatik bleiben konservativ. FX-Zuordnungen
benötigen immer eine explizite Prüfung und Bestätigung.

## Beträge und Rundung

`PaymentAllocation.amount` ist ausschließlich Rechnungswährungsdeckung.
`bank_amount` ist der tatsächlich verbrauchte Bankwährungsbetrag einschließlich
der dieser Zuordnung ausdrücklich zugewiesenen Gebühr. Migration 0013 übernimmt
für bestehende Gleichwährungszuordnungen exakt den bisherigen Betrag.

Die unveränderliche FX-Evidenz hält Original-Kartenbetrag/-währung, gebuchten
Bankbetrag/-währung, explizite Kursrichtung (Bankwährung je Originalwährung oder
inverse Notierung bei E-COMM), getrennte
Gebühr, Quellen-ID, Dokumentversion, SHA-256, XML-Pfade und gegebenenfalls
Textzitat/Zeichenpositionen fest. Rechnungsoriginale und Bankbewegungen werden
nicht umgeschrieben. Rechnungswährung muss mit Original-Kartenwährung übereinstimmen.

Decimal-Arithmetik, maximal 40 Kursstellen, 64 Stellen Arbeitspräzision und
`ROUND_HALF_UP` auf die ISO-4217-Minor-Unit sind fest definiert. Es muss gelten:

```
round(Originalbetrag * belegter Kurs) + belegte Gebühr = Bankbetrag
# Bei invers notiertem E-COMM-Kurs (Originalwährung je Bankwährung):
round(Originalbetrag / belegter Kurs) + belegte Gebühr = Bankbetrag
```

Teilzuordnungen verwenden kumulierte Rundung: neue Bank-Rechnungsdeckung =
`round((bisherige Originaldeckung + neue Deckung) * Kurs) - bisheriger Bank-Rechnungsanteil`
(bei inverser Notierung Division statt Multiplikation, ohne vorherige Rundung eines Kehrwerts).
So bleibt auch die letzte Minor Unit konsistent. Gebühren zählen niemals als
Rechnungszahlung. Nicht verbrauchte Gebühren bleiben als Bankrest sichtbar;
es gibt keine implizite Gebührenbuchung oder Abschreibung.

## Unterstützte Quellen und bewusste Grenzen

Ein eindeutig einzelnes `TxDtls` pro CAMT-Eintrag wird unterstützt.
Strukturfelder haben Vorrang: `AmtDtls/InstdAmt/Amt` (alternativ Originalbetrag in
`TxAmt/Amt`), `InstdAmt/CcyXchg` oder `TxAmt/CcyXchg` mit `SrcCcy`, `TrgtCcy`,
`XchgRate`, und separat belegte `Chrgs/Rcrd/Amt`. Auch eine Gebühr von null muss
explizit belegt sein. Abweichende Detailbeträge werden nicht für die Automatik
freigegeben; nur die FX-Prüfung darf eine durch die Originalfelder vollständig
abgestimmte Abweichung bestätigen.

Fehlen strukturierte FX-Angaben, erkennt `bank-text-v1` ausschließlich diese genaue,
einmalig vorkommende Syntax innerhalb eines `RmtInf/Ustrd` (synthetisches Beispiel):

```
ORIGINAL 60.00 USD; RATE 0.916666666666667 USD/EUR; FEE 1.00 EUR; CARD DATE 2026-10-01
```

Zusätzlich unterstützt `bank-ecomm-v1` genau die folgende, quellengeprüfte
E-COMM-Grammatik (vollständig synthetisches Beispiel):

```text
E-COMM       84,00 USD K7   16.04. 09:42FABLEX, LAB. NEW CLOUDPORT 58243 840SPESEN: 1,75  KURS: 1,200000  VOM:14.04.2031
```

Diese Grammatik muss ein gesamtes einzelnes `RmtInf/Ustrd` ausfüllen, ohne
Whitespace-Normalisierung: sieben ASCII-Leerzeichen nach `E-COMM`, drei nach der
Kartenkennung (Buchstabe + Ziffer), je zwei vor `KURS:` und `VOM:`. Kein Abstand
zwischen Uhrzeit und Händler sowie zwischen dreistelligem Ländercode und
`SPESEN:`. Händler-/Ortstext erlaubt Großbuchstaben, Ziffern, Leerzeichen,
Komma, Punkt und Bindestrich; vor dem Ländercode steht eine fünfstellige Postleitzahl.
Beträge haben zwei, der Kurs sechs Nachkommastellen mit Dezimalkomma.
Unterstützt werden nur EUR-Bankbelastungen mit abweichender Originalwährung.

`KURS:` und `SPESEN:` deklarieren selbst weder Kursrichtung noch Gebührenwährung.
Für diese Grammatik wird die inverse Relation geprüft:
`round(Original / KURS) + SPESEN = Bankbetrag EUR`.
Passt auch die Multiplikation auf denselben Centbetrag, ist die Richtung mehrdeutig
und es gibt keine Evidenz. Die Evidenz bewahrt den notierten Kurs unverändert mit
`rate_direction = "original currency per bank currency"` sowie `direction_basis`
und `fee_basis`: Richtung und EUR-Inklusivgebühr sind durch Betragskonsistenz
abgeleitet, nicht strukturiert deklariert. Die Vorschau weist ausdrücklich darauf
hin; eine Bestätigung bleibt erforderlich. Das Rundungsverfahren ist die lokale
Abgleichregel, keine Behauptung über die interne Bankberechnung.

Das Karten-/Uhrzeitfeld hat kein Jahr. Es bleibt als `card_date_text` erhalten;
`card_date` bleibt leer und die Datumsprüfung offen. `VOM:` bleibt als `vom_text`
erhalten und wird nicht als Karten- oder Kursdatum interpretiert. Ungültige
Kalendertage/Uhrzeiten werden abgelehnt; ein Jahr wird nicht ergänzt.

Ein vorhandenes gleichwähriges `InstdAmt/Amt` oder `TxAmt/Amt` sperrt den
Text-Fallback nicht, sofern **alle** vorhandenen Detailbeträge exakt dem gebuchten
Bankbetrag/-währung entsprechen und keine `CcyXchg`- oder `Chrgs`-Angaben vorliegen.
Fremdwährungsbeträge, abweichende Detailbeträge, unvollständige FX-Strukturen und
strukturierte Gebühren dürfen nicht durch Text übersteuert werden. Vollständige
strukturierte FX-Belege behalten Vorrang. Mehrere Textbelegstellen, auch über beide
Textgrammatiken oder mehrere `Ustrd` verteilt, sind mehrdeutig.

Das ist **kein allgemeiner Banktext- oder Sprachparser**. Andere Schreibweisen,
fehlende Gebühren, unvollständige FX-Strukturfelder, mehrere Belegstellen oder
widersprüchliche Quellen bleiben ungeklärt. Weitere Bankformate benötigen einen
separaten versionierten Parser mit synthetischen Tests; keine Rechnungszuordnung
anhand eines Betrags allein. FX-Gutschriften mit Gebühren und mehrteilige
CAMT-Sammelbuchungen werden bewusst nicht unterstützt. Atomare Sammelzuordnung
einer eindeutigen Bankbewegung auf mehrere Rechnungen ist dagegen möglich.

## REST / MCP

REST unter `/api/reconciliation/`:

1. `GET fx-evidence/?transaction_id=…` liefert aus dem Original rekonstruierte
   Belege oder konkrete Probleme. Kandidaten bleiben über `GET candidates/`
   verfügbar, einschließlich Händler, Rechnungs-/Bankdatum, Währungen,
   Referenztreffer und Prüfgründen.
2. `POST fx-preview/`: `transaction_id`, `bank_version`, `evidence_id`, `legs`.
   Jede Position enthält `document_id`, `document_version`, `amount` (Rechnungswährung),
   `bank_principal` (Bankwährung ohne Gebühr), `fee` (Bankwährung).
3. `POST fx-confirm/`: dieselben Felder plus `preview_revision`, `reason`,
   `idempotency_key`. Die Vorschau wird unter Firmensperre erneut berechnet;
   veraltete Bank-/Dokument-/Zahlungsrevisionen ergeben 409. Alle Positionen
   werden atomar bestätigt oder vollständig zurückgerollt.
4. Bestehendes `POST reverse/` hebt die Zuordnung mit exakt denselben gespeicherten
   Beträgen auf. Eindeutige gebuchte Bankrückbuchungen entwerten ebenfalls die
   gesamte ursprüngliche Deckung, ohne ihre Evidenz zu löschen.

MCP entspricht diesen Operationen mit `get_fx_payment_evidence`,
`preview_fx_payment_allocation`, `confirm_fx_payment_allocation` und dem
bestehenden `reverse_payment_allocation`.

Die Vorschau ersetzt keine Einzelfallprüfung. Insbesondere Händler, Referenzen,
Rechnungs-/Kartendatum, Datumswidersprüche und Textauslese müssen in der
Prüfbegründung bewertet werden. Ein gedrucktes „bezahlt“ ist weiterhin kein
Banknachweis. Die UI trennt fehlende Beleginformationen von fehlender Zuordnung.
Sie bietet Einzelzuordnungen; Teil-/Sammelzuordnungen sind über REST/MCP möglich.

## Status, Export und Sicherheit

Zahlungsstände summieren Rechnungswährung, Bankverfügbarkeit summiert Bankwährung.
Die Zahlungshistorie enthält beide Währungen sowie Originalquellen. Neue
Paket-Snapshots verwenden Zahlungsschema 2 und bewahren die vollständige FX-Evidenz
und Zahlungsrevision. Neue Pakete liefern eine [Excel-Arbeitsmappe](HANDOVER_WORKBOOK.md):
Das Blatt Zahlungszuordnungen trennt Rechnungsbetrag, Bankgegenwert, Gebühren und
FX-Originaltext. Es ersetzt die separate `Zahlungsstand.json`. Nachträge berücksichtigen
reine Zahlungsänderungen. Bestehende ZIPs und Snapshot-Inhalte werden nicht umgeschrieben;
ältere Pakete bleiben in ihrem gespeicherten Format verfügbar.

Firmenrechte, Sicherheitsprüfung sämtlicher Originalquellen, Ausschlüsse,
Duplikat-/Identitätssperren und Rückbuchungssperren gelten auch für FX.
Parallelzugriffe verwenden dieselbe Company-/Row-Lock-Reihenfolge wie der
bestehende Bankabgleich. Der Konkurrenztest läuft nur auf PostgreSQL; SQLite
beweist keine Row-Lock-Sicherheit. Alle Fixtures sind synthetisch.
