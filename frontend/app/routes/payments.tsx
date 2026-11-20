import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import {
  Alert,
  Button,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { api, kinds } from "../api";
import { ErrorAlert, Heading } from "../components";
import {
  BankCandidates,
  paymentLabels,
  type BankMovement,
  type PaymentPage,
  type PaymentStatus,
} from "../payments";
import { useApp } from "./shell";
import { BankControls } from "../bank-controls";
import { BankIdentityPanel } from "../bank-identity";

type InvoiceStatus = PaymentStatus & {
  kind: string;
  number: string | null;
  original_name: string;
  review_reasons: string[];
};

export default function Payments() {
  const { companyId, period } = useApp();
  return (
    <Stack spacing={2}>
      {companyId && (
        <BankControls
          key={`${companyId}-${period}`}
          companyId={companyId}
          period={period}
        />
      )}
      <PaymentLists key={companyId} companyId={companyId} />
    </Stack>
  );
}

function PaymentLists({ companyId }: { companyId: number | null }) {
  const [mode, setMode] = useState("invoices");
  const [cursor, setCursor] = useState(0);
  const [filter, setFilter] = useState("all");
  const [kind, setKind] = useState("");
  const [search, setSearch] = useState("");
  const [draftSearch, setDraftSearch] = useState("");
  const parameters = new URLSearchParams({
    company_id: String(companyId),
    cursor: String(cursor),
    state: filter,
    search,
    ...(mode === "invoices" && kind ? { kind } : {}),
  });
  const invoices = useQuery({
    queryKey: ["invoice-payments", companyId, cursor, filter, kind, search],
    queryFn: () =>
      api<PaymentPage<InvoiceStatus>>(`reconciliation/invoices/?${parameters}`),
    enabled: !!companyId && mode === "invoices",
  });
  const movements = useQuery({
    queryKey: ["bank-movements", companyId, cursor, filter, search],
    queryFn: () =>
      api<PaymentPage<BankMovement>>(
        `reconciliation/transactions/?${parameters}`,
      ),
    enabled: !!companyId && mode === "transactions",
  });
  const data = mode === "invoices" ? invoices.data : movements.data;
  return (
    <Stack spacing={2}>
      <Heading
        title="Zahlungsstand & Bankabgleich"
        subtitle="Firmenweiter Datenstand über alle Monate; Überfälligkeit wird nur angezeigt."
      />
      <Alert severity="info">
        CAMT zuerst am geprüften Kontoauszug abgleichen. Betrag allein beweist
        keine Zahlung. PDF-only und automatische Sonderfallkorrekturen sind noch
        nicht verfügbar.
      </Alert>
      <ErrorAlert
        error={mode === "invoices" ? invoices.error : movements.error}
      />
      {(mode === "invoices" ? invoices.isFetching : movements.isFetching) && (
        <Typography role="status">Daten werden geladen …</Typography>
      )}
      <Stack direction="row" spacing={2}>
        <TextField
          select
          label="Ansicht"
          value={mode}
          onChange={(e) => {
            setMode(e.target.value);
            setFilter("all");
            setCursor(0);
          }}
        >
          <MenuItem value="invoices">Ein- und Ausgangsrechnungen</MenuItem>
          <MenuItem value="transactions">
            Bankbewegungen / fehlende Zuordnung
          </MenuItem>
        </TextField>
        <TextField
          select
          label="Firmenweiter Filter"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setCursor(0);
          }}
        >
          <MenuItem value="all">Alle</MenuItem>
          <MenuItem value="open">Offene / ungeklärte</MenuItem>
          <MenuItem value="review">Zur Prüfung</MenuItem>
          {mode === "invoices"
            ? [
                <MenuItem key="overdue" value="overdue">
                  Überfällig
                </MenuItem>,
                <MenuItem key="unresolved" value="unresolved">
                  Betrag / Währung ungeklärt
                </MenuItem>,
                <MenuItem key="unmatched" value="unmatched">
                  Ohne aktive Bankzuordnung
                </MenuItem>,
                <MenuItem key="partially_paid" value="partially_paid">
                  Teilweise bezahlt
                </MenuItem>,
                <MenuItem key="paid" value="paid">
                  Bezahlt
                </MenuItem>,
              ]
            : [
                <MenuItem key="unallocated" value="unallocated">
                  Verfügbarer Restbetrag
                </MenuItem>,
                <MenuItem key="pending" value="pending">
                  Nicht gebucht / ungeklärt
                </MenuItem>,
                <MenuItem key="reversed" value="reversed">
                  Durch Bank rückgebucht
                </MenuItem>,
                <MenuItem key="merged" value="merged">
                  Zusammengeführte Beobachtungen
                </MenuItem>,
              ]}
        </TextField>
        {mode === "invoices" && (
          <TextField
            select
            label="Rechnungsart"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setCursor(0);
            }}
          >
            <MenuItem value="">ER und AR</MenuItem>
            <MenuItem value="incoming_invoice">Eingangsrechnungen</MenuItem>
            <MenuItem value="outgoing_invoice">Ausgangsrechnungen</MenuItem>
          </TextField>
        )}
      </Stack>
      <Stack
        component="form"
        direction="row"
        spacing={2}
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(draftSearch.trim());
          setCursor(0);
        }}
      >
        <TextField
          label="Firmenweit suchen"
          value={draftSearch}
          slotProps={{ htmlInput: { maxLength: 200 } }}
          onChange={(e) => setDraftSearch(e.target.value)}
          helperText="Rechnungsnummer / Partei bzw. Bankreferenz"
        />
        <Button type="submit">Suchen</Button>
      </Stack>
      <Typography variant="body2">
        Filter gelten vor der Seiteneinteilung für alle Firmenmonate. Keine
        Zuordnung ist kein Nachweis des Nichtbezahltseins.
      </Typography>
      {mode === "invoices" &&
        invoices.data?.items.map((i) => (
          <Paper key={i.document_id} sx={{ p: 2 }}>
            <Stack spacing={1}>
              <Typography>
                <Link to={`/documents/${i.document_id}`}>
                  {i.number || i.original_name}
                </Link>{" "}
                · {kinds[i.kind]}
              </Typography>
              <Typography>
                {paymentLabels[i.status]} · bezahlt {i.paid ?? "?"} · Rest{" "}
                {i.remaining ?? "?"} {i.currency}
              </Typography>
              <Typography>
                {i.overdue === null
                  ? "Fälligkeit ungeklärt"
                  : i.overdue
                    ? "Überfällig"
                    : "Nicht überfällig"}{" "}
                · Bankdeckung: {i.bank_evidence} · Stand {i.as_of}
              </Typography>
              {i.review_reasons?.map((point) => (
                <Alert key={point} severity="warning">
                  Prüfhinweis: {point}
                </Alert>
              ))}
            </Stack>
          </Paper>
        ))}
      {mode === "transactions" &&
        movements.data?.items.map((t) => (
          <Paper key={t.id} sx={{ p: 2 }}>
            <Stack spacing={1}>
              <Typography>
                {t.direction} · {t.amount} {t.currency} · verfügbar{" "}
                {t.available} · {t.party_name}
              </Typography>
              <Typography>
                {t.remittance || "Keine Rechnungsreferenz"}
              </Typography>
              <Typography>
                {t.booked ? "Gebucht" : "Buchungsstatus ungeklärt/ausstehend"}
                {t.reversed_by_id
                  ? " · durch Bank rückgebucht, nicht mehr verfügbar"
                  : ""}
                {t.reversal
                  ? t.reversal_of_id
                    ? " · Rückbuchung eindeutig berücksichtigt"
                    : " · Rückbuchung: Bezug manuell prüfen"
                  : ""}
              </Typography>
              {(t.review_reasons || t.issues).length > 0 && (
                <Alert severity="warning">
                  {(t.review_reasons || t.issues).join("; ")}
                </Alert>
              )}
              {t.sources.map((s) => (
                <Link
                  key={s.document_id + s.locator}
                  to={`/documents/${s.document_id}`}
                >
                  Originalauszug · {s.locator}
                </Link>
              ))}
              {companyId && (
                <BankIdentityPanel movement={t} companyId={companyId} />
              )}
              {!t.merged_into_id && <BankCandidates movement={t} />}
            </Stack>
          </Paper>
        ))}
      {data?.items.length === 0 && (
        <Typography>Keine Einträge vorhanden.</Typography>
      )}
      <Stack direction="row" spacing={1}>
        <Button
          disabled={!cursor}
          onClick={() => setCursor(Math.max(0, cursor - 50))}
        >
          Zurück
        </Button>
        <Button
          disabled={data?.next_cursor == null}
          onClick={() => setCursor(data!.next_cursor!)}
        >
          Weitere
        </Button>
      </Stack>
    </Stack>
  );
}
