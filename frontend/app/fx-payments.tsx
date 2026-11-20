import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Link } from "react-router";
import { api, post, idempotencyKey, type Document } from "./api";
import { ErrorAlert } from "./components";
import type { BankMovement } from "./payments";

interface Evidence {
  id: string;
  document_id: string;
  locator: string;
  original_amount: string;
  original_currency: string;
  rate: string;
  fee: string;
  method: string;
  quote?: string;
  paths: string[];
  card_date: string;
}
interface Preview {
  revision: string;
  evidence: Evidence;
  legs: {
    amount: string;
    invoice_currency: string;
    bank_principal: string;
    fee: string;
    bank_amount: string;
    bank_currency: string;
    invoice_date?: string;
    party?: string;
    reference?: string;
    review_reasons?: string[];
  }[];
  remaining_after?: {
    original_amount: string;
    original_currency: string;
    bank_amount: string;
    bank_currency: string;
    fee: string;
  };
  review_notes: string[];
}

export function FXPayment({
  doc,
  movement,
  canProcess,
}: {
  doc: Document;
  movement: BankMovement;
  canProcess: boolean;
}) {
  const cache = useQueryClient();
  const [evidenceId, setEvidenceId] = useState("");
  const [amount, setAmount] = useState("");
  const [principal, setPrincipal] = useState("");
  const [fee, setFee] = useState("0.00");
  const [reason, setReason] = useState("");
  const keys = useRef(new Map<string, string>());
  const sources = useQuery({
    queryKey: ["fx-evidence", movement.id, movement.version],
    queryFn: () =>
      api<{ items: Evidence[]; issues: { locator: string; reason: string }[] }>(
        `reconciliation/fx-evidence/?transaction_id=${movement.id}`,
      ),
  });
  const payload = {
    transaction_id: movement.id,
    bank_version: movement.version,
    evidence_id: evidenceId,
    legs: [
      {
        document_id: doc.id,
        document_version: doc.version,
        amount,
        bank_principal: principal,
        fee,
      },
    ],
  };
  const fingerprint = JSON.stringify(payload);
  const preview = useMutation({
    mutationFn: async () => ({
      fingerprint,
      plan: await post<Preview>("reconciliation/fx-preview/", payload),
    }),
  });
  const plan =
    preview.data?.fingerprint === fingerprint ? preview.data.plan : undefined;
  const confirm = useMutation({
    mutationFn: () => {
      const request = { ...payload, preview_revision: plan!.revision, reason };
      const fp = JSON.stringify(request);
      const key = keys.current.get(fp) || idempotencyKey();
      keys.current.set(fp, key);
      return post("reconciliation/fx-confirm/", {
        ...request,
        idempotency_key: key,
      });
    },
    onSuccess: async () => {
      preview.reset();
      await cache.invalidateQueries();
    },
  });
  return (
    <Stack spacing={2}>
      <Typography variant="h6">
        Fremdwährungsdeckung ausdrücklich prüfen
      </Typography>
      <Alert severity="info">
        Ein Bankbeleg ist vorhanden; die Zuordnung zur Rechnung fehlt
        möglicherweise noch. Händler und Betrag allein beweisen keine Zahlung.
        Kein Live-Kurs, keine Überweisung.
      </Alert>
      <ErrorAlert error={sources.error || preview.error || confirm.error} />
      {sources.data?.issues.map((i, n) => (
        <Alert key={n} severity="warning">
          FX-Beleg fehlt/ist unklar: {i.locator}: {i.reason}
        </Alert>
      ))}
      <TextField
        select
        label="Originalbeleg für Kurs und Gebühren"
        value={evidenceId}
        onChange={(e) => setEvidenceId(e.target.value)}
      >
        <MenuItem value="">Bitte wählen</MenuItem>
        {sources.data?.items.map((e) => (
          <MenuItem key={e.id} value={e.id}>
            {e.original_amount} {e.original_currency} · Kurs {e.rate} · Gebühren{" "}
            {e.fee} {movement.currency} · {e.method}
          </MenuItem>
        ))}
      </TextField>
      {sources.data?.items
        .filter((e) => e.id === evidenceId)
        .map((e) => (
          <Stack key={e.id}>
            <Link to={`/documents/${e.document_id}`}>
              Bankoriginal · {e.locator}
            </Link>
            <Typography>
              {e.paths.join(", ")} · Kartendatum:{" "}
              {e.card_date || "nicht belegt"}
            </Typography>
            {e.quote && (
              <Typography component="blockquote">{e.quote}</Typography>
            )}
          </Stack>
        ))}
      <TextField
        label="Deckung in Rechnungswährung (Dezimalpunkt)"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
      />
      <TextField
        label={`Rechnungsanteil in ${movement.currency} (ohne Gebühr)`}
        value={principal}
        onChange={(e) => setPrincipal(e.target.value)}
      />
      <TextField
        label={`Separat belegte Gebühr in ${movement.currency}`}
        value={fee}
        onChange={(e) => setFee(e.target.value)}
      />
      <Button
        disabled={
          !canProcess ||
          !evidenceId ||
          !amount ||
          !principal ||
          preview.isPending
        }
        onClick={() => preview.mutate()}
      >
        FX-Zuordnung vorschauen
      </Button>
      {plan && (
        <>
          {plan.legs.map((l, n) => (
            <Stack key={n}>
              <Typography>
                {l.party} · Rechnung {l.reference} · Rechnungsdatum{" "}
                {l.invoice_date || "nicht belegt"} · Bankhändler{" "}
                {movement.party_name}
              </Typography>
              <Typography>
                Rechnungsdeckung: {l.amount} {l.invoice_currency};
                Bankverbrauch: {l.bank_amount} {l.bank_currency} ={" "}
                {l.bank_principal} + {l.fee} Gebühr (keine Rechnungszahlung).
              </Typography>
              {l.review_reasons?.map((r) => (
                <Alert key={r} severity="warning">
                  {r}
                </Alert>
              ))}
            </Stack>
          ))}
          {plan.remaining_after && (
            <Typography>
              Verbleibende Originaldeckung:{" "}
              {plan.remaining_after.original_amount}{" "}
              {plan.remaining_after.original_currency}; Bankrest:{" "}
              {plan.remaining_after.bank_amount}{" "}
              {plan.remaining_after.bank_currency} (davon unzugewiesene Gebühr:{" "}
              {plan.remaining_after.fee}).
            </Typography>
          )}
          {plan.review_notes.map((n) => (
            <Alert key={n} severity="warning">
              {n}
            </Alert>
          ))}
          <TextField
            label="Prüfbegründung: Händler, Referenzen, Rechnungs-/Kartendatum, Kurs, Gebühr und Textbeleg geprüft"
            multiline
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <Button
            variant="contained"
            disabled={!canProcess || !reason.trim() || confirm.isPending}
            onClick={() => confirm.mutate()}
          >
            Belege und FX-Zuordnung ausdrücklich bestätigen
          </Button>
        </>
      )}
      {confirm.isSuccess && (
        <Alert severity="success">FX-Deckung gespeichert.</Alert>
      )}
    </Stack>
  );
}
