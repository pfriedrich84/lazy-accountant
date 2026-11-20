import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Link } from "react-router";
import { api, idempotencyKey, post, type Assignments } from "./api";
import { ErrorAlert } from "./components";

interface Policy {
  enabled: boolean;
  version: number;
  persisted: boolean;
}
interface Coverage {
  version: number;
  declared_state: string;
  effective_state: string;
  basis: string;
  review_reasons: string[];
  sources: { document_id: string }[];
}
interface AccountState {
  account_id: number;
  account_name: string;
  period: string;
  coverage: Coverage;
  latest_booked_date: string | null;
  transaction_count: number | null;
  pending_count: number | null;
  security_blocked: boolean;
  statements_truncated?: boolean;
  statements: {
    document_id: string;
    version: number;
    ready_for_confirmation: boolean;
    review_reasons: string[];
  }[];
  history: { version: number; reason: string }[];
}

function useControlAction(companyId: number) {
  const cache = useQueryClient();
  const keys = useRef(new Map<string, string>());
  return useMutation({
    mutationFn: ({
      operation,
      payload,
    }: {
      operation: string;
      payload: object;
    }) => {
      const fingerprint = JSON.stringify([operation, payload]);
      const key = keys.current.get(fingerprint) || idempotencyKey();
      keys.current.set(fingerprint, key);
      return post(`reconciliation/${operation}/`, {
        ...payload,
        idempotency_key: key,
      });
    },
    onSuccess: async () => {
      keys.current.clear();
      await cache.invalidateQueries({ queryKey: ["bank-policy", companyId] });
      await cache.invalidateQueries({
        queryKey: ["bank-account-state", companyId],
      });
    },
  });
}

const labels: Record<string, string> = {
  confirmed: "Monatsvollständigkeit bestätigt",
  disputed: "Konkreter Prüfbedarf / Widerspruch",
  unknown: "Monatsabdeckung ungeklärt",
};

function AccountCoverage({
  companyId,
  account,
  canProcess,
}: {
  companyId: number;
  account: AccountState;
  canProcess: boolean;
}) {
  const [state, setState] = useState("confirmed");
  const [reason, setReason] = useState("");
  const action = useControlAction(companyId);
  return (
    <Paper sx={{ p: 2 }}>
      <Stack spacing={1}>
        <Typography variant="h6">
          {account.account_name} · {account.period}
        </Typography>
        <Typography>
          {labels[account.coverage.effective_state]} · Version{" "}
          {account.coverage.version}
        </Typography>
        {account.coverage.basis === "accepted_monthly_statement_convention" && (
          <Typography variant="body2">
            Gemäß bereits bestätigter Monatsregel: geprüfte Monatsauszüge gelten
            für ihren zugeordneten Monat als vollständig. Keine erneute
            Bestätigung allein wegen unscharfer Datumsgrenzen nötig.
          </Typography>
        )}
        <Typography variant="body2">
          Letzte beobachtete gebuchte Bewegung (alle Monate):{" "}
          {account.latest_booked_date || "keine sichere Angabe"} · Bewegungen:{" "}
          {account.transaction_count ?? "gesperrt"} · ausstehend:{" "}
          {account.pending_count ?? "gesperrt"}
        </Typography>
        {account.security_blocked && (
          <Alert severity="error">
            Bankquelle sicherheitsgesperrt. Datenstand nicht als sichere
            Abdeckung verwenden.
          </Alert>
        )}
        {account.coverage.review_reasons.map((reason) => (
          <Alert key={reason} severity="warning">
            {reason}
          </Alert>
        ))}
        {account.statements.map((source) => (
          <Typography key={source.document_id} variant="body2">
            <Link to={`/documents/${source.document_id}`}>
              Auszugsquelle · Version {source.version}
            </Link>
            {source.review_reasons.length > 0
              ? ` · ${source.review_reasons.join("; ")}`
              : " · geprüft"}
          </Typography>
        ))}
        {account.history[0] && (
          <Typography variant="body2">
            Letzte dokumentierte Erklärung: {account.history[0].reason}
          </Typography>
        )}
        {canProcess && (
          <Stack spacing={1}>
            <TextField
              select
              label="Abdeckung dokumentieren"
              value={state}
              onChange={(e) => setState(e.target.value)}
            >
              <MenuItem value="confirmed">
                Monatsvollständigkeit dokumentieren
              </MenuItem>
              <MenuItem value="disputed">Konkreten Widerspruch melden</MenuItem>
              <MenuItem value="unknown">
                Abdeckung als ungeklärt kennzeichnen
              </MenuItem>
            </TextField>
            <TextField
              label="Begründung zur Monatsabdeckung"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              slotProps={{ htmlInput: { maxLength: 1000 } }}
            />
            <Button
              disabled={
                !reason.trim() ||
                action.isPending ||
                (state === "confirmed" &&
                  (account.statements_truncated ||
                    !account.statements.some((s) => s.ready_for_confirmation)))
              }
              onClick={() =>
                action.mutate({
                  operation: "coverage",
                  payload: {
                    company_id: companyId,
                    account_id: account.account_id,
                    period: account.period,
                    expected_version: account.coverage.version,
                    state,
                    reason,
                    document_ids: account.statements
                      .filter((s) => s.ready_for_confirmation)
                      .map((s) => s.document_id),
                    document_versions: Object.fromEntries(
                      account.statements
                        .filter((s) => s.ready_for_confirmation)
                        .map((s) => [s.document_id, s.version]),
                    ),
                  },
                })
              }
            >
              Abdeckung speichern
            </Button>
          </Stack>
        )}
        <ErrorAlert error={action.error} />
        {action.isSuccess && (
          <Alert severity="success">
            Erklärung gespeichert. Keine Zahlung erzeugt.
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}

export function BankControls({
  companyId,
  period,
}: {
  companyId: number;
  period: string;
}) {
  const [reason, setReason] = useState("");
  const [cursor, setCursor] = useState(0);
  const permissions = useQuery({
    queryKey: ["assignments", companyId],
    queryFn: () => api<Assignments>(`companies/${companyId}/`),
  });
  const policy = useQuery({
    queryKey: ["bank-policy", companyId],
    queryFn: () =>
      api<Policy>(`reconciliation/policy/?company_id=${companyId}`),
  });
  const accounts = useQuery({
    queryKey: ["bank-account-state", companyId, period, cursor],
    queryFn: () =>
      api<{ items: AccountState[]; next_cursor: number | null }>(
        `reconciliation/accounts/?company_id=${companyId}&period=${encodeURIComponent(period)}&cursor=${cursor}`,
      ),
  });
  const action = useControlAction(companyId);
  return (
    <Stack spacing={2}>
      <Paper sx={{ p: 2 }}>
        <Stack spacing={1}>
          <Typography variant="h6">Automatikpolicy der Firma</Typography>
          {policy.data && (
            <Typography>
              Konservative Rechnungsautomatik:{" "}
              {policy.data.enabled ? "aktiv" : "deaktiviert"} · Version{" "}
              {policy.data.version}
              {!policy.data.persisted
                ? " · bisherige freigegebene Voreinstellung"
                : ""}
            </Typography>
          )}
          <Typography variant="body2">
            Gilt nur beim bewusst gestarteten CAMT-Abgleich. Keine
            Zahlungsanweisung. Eindeutig belegte Bankrückbuchungen korrigieren
            vorhandene Deckung auch bei deaktivierter Rechnungsautomatik.
          </Typography>
          {permissions.data?.permissions.admin && policy.data && (
            <>
              <TextField
                label="Begründung zur Automatikpolicy"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                slotProps={{ htmlInput: { maxLength: 1000 } }}
              />
              <Button
                disabled={!reason.trim() || action.isPending}
                onClick={() =>
                  action.mutate({
                    operation: "policy",
                    payload: {
                      company_id: companyId,
                      expected_version: policy.data!.version,
                      enabled: !policy.data!.enabled,
                      reason,
                    },
                  })
                }
              >
                Automatik {policy.data.enabled ? "deaktivieren" : "aktivieren"}
              </Button>
            </>
          )}
          <ErrorAlert error={policy.error || accounts.error || action.error} />
        </Stack>
      </Paper>
      <Typography variant="h6">
        Kontodatenstand & Monatsabdeckung · {period}
      </Typography>
      <Typography variant="body2">
        Buchungsdatenstand und Monatsvollständigkeit sind getrennt. Keine
        gefundene Zuordnung beweist kein Nichtbezahltsein.
      </Typography>
      {accounts.data?.items.map((account) => (
        <AccountCoverage
          key={`${account.account_id}-${period}`}
          companyId={companyId}
          account={account}
          canProcess={!!permissions.data?.permissions.process}
        />
      ))}
      <Stack direction="row" spacing={1}>
        <Button
          disabled={!cursor}
          onClick={() => setCursor(Math.max(0, cursor - 50))}
        >
          Vorherige Konten
        </Button>
        <Button
          disabled={accounts.data?.next_cursor == null}
          onClick={() => setCursor(accounts.data!.next_cursor!)}
        >
          Weitere Konten
        </Button>
      </Stack>
    </Stack>
  );
}
