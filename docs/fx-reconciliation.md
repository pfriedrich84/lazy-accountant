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
Bankbetrag/-währung, Kursrichtung (Bankwährung je Originalwährung), getrennte
Gebühr, Quellen-ID, Dokumentversion, SHA-256, XML-Pfade und gegebenenfalls
Textzitat/Zeichenpositionen fest. Rechnungsoriginale und Bankbewegungen werden
nicht umgeschrieben. Rechnungswährung muss mit Original-Kartenwährung übereinstimmen.

Decimal-Arithmetik, maximal 40 Kursstellen, 64 Stellen Arbeitspräzision und
`ROUND_HALF_UP` auf die ISO-4217-Minor-Unit sind fest definiert. Es muss gelten:

```
round(Originalbetrag * belegter Kurs) + belegte Gebühr = Bankbetrag
```

Teilzuordnungen verwenden kumulierte Rundung: neue Bank-Rechnungsdeckung =
`round((bisherige Originaldeckung + neue Deckung) * Kurs) - bisheriger Bank-Rechnungsanteil`.
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

Fehlen Strukturfelder, erkennt `bank-text-v1` ausschließlich diese genaue,
einmalig vorkommende Syntax innerhalb eines `RmtInf/Ustrd` (synthetisches Beispiel):

```
ORIGINAL 60.00 USD; RATE 0.916666666666667 USD/EUR; FEE 1.00 EUR; CARD DATE 2026-10-01
```

Das ist **kein allgemeiner Banktext- oder Sprachparser**. Andere Schreibweisen,
fehlende Gebühren, unvollständige Strukturfelder, mehrere Belegstellen oder
widersprüchliche Quellen bleiben ungeklärt. Weitere Bankformate benötigen einen
separaten versionierten Parser mit synthetischen Tests; keine Interpretation
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
Paket-Snapshots verwenden Zahlungsschema 2; `Zahlungsstand.json` exportiert die
vollständige FX-Evidenz und Zahlungsrevision. Nachträge berücksichtigen reine
Zahlungsänderungen. Bestehende Snapshot-Inhalte werden nicht umgeschrieben;
ältere Snapshots exportieren weiterhin ihre gespeicherte Schemaversion.

Firmenrechte, Sicherheitsprüfung sämtlicher Originalquellen, Ausschlüsse,
Duplikat-/Identitätssperren und Rückbuchungssperren gelten auch für FX.
Parallelzugriffe verwenden dieselbe Company-/Row-Lock-Reihenfolge wie der
bestehende Bankabgleich. Der Konkurrenztest läuft nur auf PostgreSQL; SQLite
beweist keine Row-Lock-Sicherheit. Alle Fixtures sind synthetisch.
