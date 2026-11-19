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

type InvoiceStatus = PaymentStatus & {
  kind: string;
  number: string | null;
  original_name: string;
};

export default function Payments() {
  const { companyId } = useApp();
  const [mode, setMode] = useState("invoices");
  const [cursor, setCursor] = useState(0);
  const [filter, setFilter] = useState("all");
  const invoices = useQuery({
    queryKey: ["invoice-payments", companyId, cursor],
    queryFn: () =>
      api<PaymentPage<InvoiceStatus>>(
        `reconciliation/invoices/?company_id=${companyId}&cursor=${cursor}`,
      ),
    enabled: !!companyId && mode === "invoices",
  });
  const movements = useQuery({
    queryKey: ["bank-movements", companyId, cursor],
    queryFn: () =>
      api<PaymentPage<BankMovement>>(
        `reconciliation/transactions/?company_id=${companyId}&cursor=${cursor}`,
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
      <ErrorAlert error={invoices.error || movements.error} />
      <Stack direction="row" spacing={2}>
        <TextField
          select
          label="Ansicht"
          value={mode}
          onChange={(e) => {
            setMode(e.target.value);
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
          label="Filter auf dieser Seite"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <MenuItem value="all">Alle</MenuItem>
          <MenuItem value="open">Offene / ungeklärte</MenuItem>
          <MenuItem value="overdue">Überfällig</MenuItem>
        </TextField>
      </Stack>
      {mode === "invoices" &&
        invoices.data?.items
          .filter(
            (i) =>
              filter === "all" ||
              (filter === "overdue" ? i.overdue : i.status !== "paid"),
          )
          .map((i) => (
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
              </Stack>
            </Paper>
          ))}
      {mode === "transactions" &&
        movements.data?.items
          .filter((t) => filter === "all" || t.available !== "0.000000")
          .map((t) => (
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
                  {t.reversal
                    ? " · Rückbuchung: Zuordnungen manuell prüfen"
                    : ""}
                </Typography>
                {t.issues.length > 0 && (
                  <Alert severity="warning">{t.issues.join("; ")}</Alert>
                )}
                {t.sources.map((s) => (
                  <Link
                    key={s.document_id + s.locator}
                    to={`/documents/${s.document_id}`}
                  >
                    Originalauszug · {s.locator}
                  </Link>
                ))}
                <BankCandidates movement={t} />
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
