import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import {
  api,
  idempotencyKey,
  post,
  type Assignments,
  type Document,
} from "./api";
import { ErrorAlert } from "./components";

export interface BankMovement {
  merged_into_id?: string | null;
  canonical_version?: number;
  bank_reference?: string;
  references?: Record<string, string>;
  identity_review_points?: string[];
  identity_resolution?: {
    id: number;
    actor_id: number;
    reason: string;
    created_at: string;
    disputed_at: string | null;
    dispute_reason: string;
  } | null;
  review_reasons?: string[];
  id: string;
  version: number;
  amount: string;
  available: string;
  currency: string;
  direction: string;
  party_name: string;
  remittance: string;
  booked: boolean;
  reversal: boolean;
  reversal_of_id?: string | null;
  reversed_by_id?: string | null;
  issues: string[];
  sources: { document_id: string; locator: string }[];
}
export interface PaymentStatus {
  document_id: string;
  document_version: number;
  status: string;
  currency?: string;
  paid?: string;
  remaining?: string;
  due_date?: string;
  overdue: boolean | null;
  bank_evidence: string;
  assessment_notes?: string[];
  as_of: string;
  allocations: {
    id: string;
    transaction_id: string;
    bank_version: number;
    amount: string;
    decision: string;
    reversed_at: string | null;
    reversal_reason: string;
    reversal_sources?: { document_id: string; locator: string }[];
    reason: string;
  }[];
}
export interface PaymentPage<T> {
  items: T[];
  next_cursor: number | null;
}
export const paymentLabels: Record<string, string> = {
  unpaid: "Offen",
  partially_paid: "Teilweise bezahlt",
  paid: "Bezahlt",
  unresolved: "Ungeklärt",
};

export function BankCandidates({ movement }: { movement: BankMovement }) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["bank-candidates", movement.id, movement.version],
    queryFn: () =>
      api<{
        items: { document_id: string; reference: string; reasons: string[] }[];
      }>(`reconciliation/candidates/?transaction_id=${movement.id}`),
    enabled: open,
  });
  return (
    <Stack spacing={1}>
      <Button onClick={() => setOpen(!open)}>
        Referenztreffer und Gründe {open ? "ausblenden" : "anzeigen"}
      </Button>
      {open && (
        <>
          <ErrorAlert error={query.error} />
          {query.data?.items.length === 0 && (
            <Typography>
              Keine passende Rechnungsreferenz. Manuelle Prüfung möglich.
            </Typography>
          )}
          {query.data?.items.map((c) => (
            <Typography key={c.document_id}>
              <Link to={`/documents/${c.document_id}`}>{c.reference}</Link>:{" "}
              {c.reasons.join("; ") || "Eindeutiger Treffer"}
            </Typography>
          ))}
        </>
      )}
    </Stack>
  );
}

export function PaymentPanel({ doc }: { doc: Document }) {
  const cache = useQueryClient();
  const invoice = ["incoming_invoice", "outgoing_invoice"].includes(doc.kind);
  const bank = doc.kind === "bank_camt";
  const [cursor, setCursor] = useState(0);
  const [selected, setSelected] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [iban, setIban] = useState("");
  const [notice, setNotice] = useState("");
  const permissions = useQuery({
    queryKey: ["assignments", doc.company_id],
    queryFn: () => api<Assignments>(`companies/${doc.company_id}/`),
    enabled: !!doc.company_id,
  });
  const verifiedParties = useQuery({
    queryKey: ["bank-parties", doc.company_id],
    queryFn: () =>
      api<{ id: number; name: string; iban: string }[]>(
        `reconciliation/verified-parties/?company_id=${doc.company_id}`,
      ),
    enabled: invoice && !!permissions.data?.permissions.admin,
  });
  const status = useQuery({
    queryKey: ["payment-status", doc.id, doc.version],
    queryFn: () =>
      api<PaymentStatus>(`reconciliation/status/?document_id=${doc.id}`),
    enabled: invoice && !!doc.company_id,
  });
  const movements = useQuery({
    queryKey: ["bank-movements", doc.company_id, cursor],
    queryFn: () =>
      api<PaymentPage<BankMovement>>(
        `reconciliation/transactions/?company_id=${doc.company_id}&cursor=${cursor}`,
      ),
    enabled: invoice && !!doc.company_id,
  });
  const tx = movements.data?.items.find((t) => t.id === selected);
  const retryKeys = useRef(new Map<string, string>());
  const action = useMutation({
    mutationFn: ({
      operation,
      payload,
    }: {
      operation: string;
      payload: object;
    }) => {
      const data = { ...payload } as Record<string, unknown>;
      if ("idempotency_key" in data) {
        delete data.idempotency_key;
        const fingerprint = JSON.stringify([operation, data]);
        const key = retryKeys.current.get(fingerprint) || idempotencyKey();
        retryKeys.current.set(fingerprint, key);
        data.idempotency_key = key;
      }
      return post(`reconciliation/${operation}/`, data);
    },
    onSuccess: async (_data, variables) => {
      retryKeys.current.clear();
      setNotice(
        variables.operation === "normalize"
          ? "CAMT abgeglichen. Eindeutige Treffer wurden bestätigt und eindeutig referenzierte Rückbuchungen berücksichtigt; übrige Bewegungen unter Zahlungsstand prüfen."
          : "Gespeichert.",
      );
      await cache.invalidateQueries({
        predicate: (q) =>
          [
            "payment-status",
            "bank-movements",
            "bank-candidates",
            "invoice-payments",
            "bank-parties",
          ].includes(String(q.queryKey[0])),
      });
    },
  });
  if ((!invoice && !bank) || !doc.company_id) return null;
  const canProcess = permissions.data?.permissions.process;
  return (
    <Paper sx={{ p: 3 }}>
      <Stack spacing={2}>
        <Typography variant="h6">Bankabgleich & Zahlungsstand</Typography>
        <ErrorAlert
          error={
            action.error ||
            status.error ||
            movements.error ||
            verifiedParties.error
          }
        />
        {action.error && (
          <Button
            onClick={() => {
              void cache.invalidateQueries();
            }}
          >
            Aktuellen Stand neu laden (ungespeicherte Eingaben vorher sichern)
          </Button>
        )}
        {notice && <Alert severity="success">{notice}</Alert>}
        <Typography variant="body2">
          Bankbelege zeigen den verfügbaren Datenstand, keine Garantie
          endgültiger rechtlicher Erfüllung. Keine Überweisung, kein
          Mahnversand.
        </Typography>
        {bank && (
          <>
            <Typography>
              Nur geprüftes CAMT mit passender Konto-IBAN. Automatik benötigt
              exakte Rechnungsreferenz und eine ausdrücklich verifizierte
              Gegenpartei/IBAN.
            </Typography>
            <Button
              disabled={
                !canProcess || action.isPending || doc.status !== "ready"
              }
              variant="contained"
              onClick={() =>
                action.mutate({
                  operation: "normalize",
                  payload: {
                    document_id: doc.id,
                    base_version: doc.version,
                    auto_confirm: true,
                    idempotency_key: idempotencyKey(),
                  },
                })
              }
            >
              CAMT abgleichen (eindeutige Treffer bestätigen)
            </Button>
            <Button component={Link} to="/payments">
              Bankbewegungen und Zahlungsstand öffnen
            </Button>
          </>
        )}
        {invoice && status.data && (
          <>
            <Typography>
              <strong>{paymentLabels[status.data.status]}</strong> · bezahlt{" "}
              {status.data.paid ?? "?"} · offen {status.data.remaining ?? "?"}{" "}
              {status.data.currency}
            </Typography>
            <Alert severity={status.data.overdue ? "warning" : "info"}>
              {status.data.overdue === null
                ? "Fälligkeit ungeklärt"
                : status.data.overdue
                  ? "Überfällig"
                  : "Nicht überfällig"}
              {status.data.due_date && ` · fällig ${status.data.due_date}`} ·
              Stand {status.data.as_of}
            </Alert>
            <Typography>
              Bankdeckung: {status.data.bank_evidence}. Keine Zuordnung bedeutet
              nicht nachgewiesenes Nichtbezahltsein.
            </Typography>
            {status.data.assessment_notes?.map((point) => (
              <Alert key={point} severity="warning">
                Bankdeckung nicht sicher: {point}
              </Alert>
            ))}
            {status.data.allocations.map((a) => (
              <Stack
                key={a.id}
                spacing={1}
                sx={{ borderTop: "1px solid #ddd", pt: 1 }}
              >
                <Typography>
                  {a.amount} · {a.decision} · {a.reason}
                  {a.reversed_at ? ` · aufgehoben: ${a.reversal_reason}` : ""}
                </Typography>
                {a.reversal_sources?.map((s) => (
                  <Link
                    key={s.document_id + s.locator}
                    to={`/documents/${s.document_id}`}
                  >
                    Bankbeleg der Rückbuchung · {s.locator}
                  </Link>
                ))}
                {!a.reversed_at && (
                  <Button
                    disabled={!canProcess || !reason.trim() || action.isPending}
                    onClick={() =>
                      action.mutate({
                        operation: "reverse",
                        payload: {
                          allocation_id: a.id,
                          bank_version: a.bank_version,
                          reason,
                          idempotency_key: idempotencyKey(),
                        },
                      })
                    }
                  >
                    Zuordnung mit untenstehender Begründung aufheben
                  </Button>
                )}
              </Stack>
            ))}
            <TextField
              label="Bankbewegung für manuelle Zuordnung"
              select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              <MenuItem value="">Bitte wählen</MenuItem>
              {movements.data?.items.map((t) => (
                <MenuItem key={t.id} value={t.id} disabled={!!t.merged_into_id}>
                  {t.merged_into_id ? "Zusammengeführt · " : ""}
                  {t.direction} · {t.available} {t.currency} · {t.party_name} ·{" "}
                  {t.remittance.slice(0, 60)}
                </MenuItem>
              ))}
            </TextField>
            <Stack direction="row" spacing={1}>
              <Button
                disabled={!cursor}
                onClick={() => {
                  setCursor(Math.max(0, cursor - 50));
                  setSelected("");
                }}
              >
                Vorige Bewegungen
              </Button>
              <Button
                disabled={movements.data?.next_cursor == null}
                onClick={() => {
                  setCursor(movements.data!.next_cursor!);
                  setSelected("");
                }}
              >
                Weitere Bewegungen
              </Button>
            </Stack>
            {tx && (
              <>
                <Typography>
                  Gebucht: {tx.booked ? "ja" : "nein"} · {tx.issues.join("; ")}
                </Typography>
                {!tx.merged_into_id && <BankCandidates movement={tx} />}
              </>
            )}
            <TextField
              label="Zuordnungsbetrag (Dezimalpunkt)"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <TextField
              label="Begründung für Zuordnung / Aufhebung / Bankdatenprüfung"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <Button
              disabled={
                !canProcess ||
                !tx ||
                !!tx.merged_into_id ||
                !amount ||
                !reason.trim() ||
                action.isPending
              }
              onClick={() =>
                tx &&
                action.mutate({
                  operation: "allocate",
                  payload: {
                    transaction_id: tx.id,
                    document_id: doc.id,
                    amount,
                    bank_version: tx.version,
                    document_version: doc.version,
                    reason,
                    idempotency_key: idempotencyKey(),
                  },
                })
              }
            >
              Bankbetrag manuell zuordnen
            </Button>
            {permissions.data?.permissions.admin && (
              <>
                {verifiedParties.data?.map((p) => (
                  <Stack key={p.id} direction="row" spacing={1}>
                    <Typography>
                      {p.name} · {p.iban}
                    </Typography>
                    <Button
                      disabled={!reason.trim() || action.isPending}
                      onClick={() =>
                        action.mutate({
                          operation: "revoke-party",
                          payload: {
                            company_id: doc.company_id,
                            party_id: p.id,
                            reason,
                          },
                        })
                      }
                    >
                      Freigabe widerrufen
                    </Button>
                  </Stack>
                ))}
                <Alert severity="warning">
                  Nur unabhängig geprüfte Bankdaten bestätigen. Dadurch können
                  künftige eindeutige Referenztreffer automatisch zugeordnet
                  werden. Keine IBAN allein aus einem neuen PDF übernehmen.
                </Alert>
                <TextField
                  label="Verifizierte IBAN des Geschäftspartners"
                  value={iban}
                  onChange={(e) => setIban(e.target.value)}
                />
                <Button
                  disabled={!iban || !reason.trim() || action.isPending}
                  onClick={() =>
                    action.mutate({
                      operation: "verify-party",
                      payload: {
                        company_id: doc.company_id,
                        name:
                          doc.metadata[
                            doc.kind === "outgoing_invoice"
                              ? "recipient"
                              : "issuer"
                          ] || "",
                        iban,
                        reason,
                      },
                    })
                  }
                >
                  Gegenpartei/IBAN ausdrücklich verifizieren
                </Button>
              </>
            )}
          </>
        )}
      </Stack>
    </Paper>
  );
}
