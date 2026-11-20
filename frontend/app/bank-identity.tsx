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
import { api, idempotencyKey, post, type Assignments } from "./api";
import { ErrorAlert } from "./components";
import type { BankMovement } from "./payments";

interface IdentityPreview {
  duplicate_id: string;
  canonical_id: string;
  duplicate_version: number;
  canonical_version: number;
  document_versions: Record<string, number>;
  can_merge: boolean;
  blockers: string[];
  criteria: string[];
}
interface IdentityCandidate extends IdentityPreview {
  bank_reference: string;
}

export function BankIdentityPanel({
  movement,
  companyId,
}: {
  movement: BankMovement;
  companyId: number;
}) {
  const cache = useQueryClient();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [disputeReason, setDisputeReason] = useState("");
  const merged = !!movement.merged_into_id;
  const enabled = open && !merged;
  const keys = useRef(new Map<string, string>());
  const permissions = useQuery({
    queryKey: ["assignments", companyId],
    queryFn: () => api<Assignments>(`companies/${companyId}/`),
    enabled: open,
  });
  const candidates = useQuery({
    queryKey: ["bank-identity-candidates", movement.id, movement.version],
    queryFn: () =>
      api<{ items: IdentityCandidate[]; truncated: boolean; note: string }>(
        `reconciliation/identity-candidates/?duplicate_id=${movement.id}`,
      ),
    enabled,
  });
  const preview = useQuery({
    queryKey: ["bank-identity-preview", movement.id, movement.version, target],
    queryFn: () =>
      api<IdentityPreview>(
        `reconciliation/identity-preview/?duplicate_id=${movement.id}&canonical_id=${target}`,
      ),
    enabled: enabled && !!target,
  });
  const action = useMutation({
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
      await Promise.all(
        [
          "bank-movements",
          "invoice-payments",
          "payment-status",
          "bank-account-state",
          "bank-identity-candidates",
          "bank-identity-preview",
        ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
      );
    },
  });
  if (!merged && movement.bank_reference) return null;
  return (
    <Stack spacing={1}>
      {merged && (
        <Alert
          severity={
            movement.identity_resolution?.disputed_at ? "warning" : "info"
          }
        >
          {movement.identity_resolution?.disputed_at
            ? "Identitätszusammenführung bestritten"
            : "Beobachtung zusammengeführt"}{" "}
          · kanonische Bewegung {movement.merged_into_id}. Nicht erneut
          verbrauchbar.
          {movement.identity_resolution && (
            <Typography variant="body2">
              Grund: {movement.identity_resolution.reason}
              {movement.identity_resolution.dispute_reason
                ? ` · Beanstandung: ${movement.identity_resolution.dispute_reason}`
                : ""}
            </Typography>
          )}
        </Alert>
      )}
      <Button onClick={() => setOpen(!open)}>
        {open
          ? "Identitätsprüfung schließen"
          : merged
            ? "Identitätsentscheidung prüfen"
            : "Umsatzidentität prüfen"}
      </Button>
      {open && (
        <>
          <Typography variant="body2">
            Nur fehlende Bankkennung auf bereits bankidentifizierte Bewegung
            auflösen. Originale und Zahlungen werden nicht verschoben; Betrag
            oder EndToEndId allein reichen nicht.
          </Typography>
          {!merged && (
            <>
              {candidates.data?.items.length === 0 && (
                <Alert severity="info">
                  Keine belastbare Paarauflösung verfügbar. Identität bleibt
                  gesperrt; keine Zahlung bestätigen.
                </Alert>
              )}
              {candidates.data?.truncated && (
                <Alert severity="warning">
                  Kandidatenübersicht begrenzt. Keine automatische
                  Zusammenführung.
                </Alert>
              )}
              {!!candidates.data?.items.length && (
                <TextField
                  select
                  label="Kanonische Bankbewegung"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                >
                  {candidates.data.items.map((candidate) => (
                    <MenuItem
                      key={candidate.canonical_id}
                      value={candidate.canonical_id}
                    >
                      {candidate.bank_reference} ·{" "}
                      {candidate.can_merge ? "vorprüfbar" : "gesperrt"}
                    </MenuItem>
                  ))}
                </TextField>
              )}
              {preview.data?.blockers.map((blocker) => (
                <Alert key={blocker} severity="warning">
                  {blocker}
                </Alert>
              ))}
              {preview.data?.can_merge && (
                <>
                  {preview.data.criteria.map((criterion) => (
                    <Typography key={criterion} variant="body2">
                      • {criterion}
                    </Typography>
                  ))}
                  <Alert severity="info">
                    Vorschau ist keine Reservierung. Originalbytes und
                    Quellen-/Bankversionen werden beim Speichern erneut geprüft.
                    Es wird keine Zahlung erzeugt.
                  </Alert>
                  {permissions.data?.permissions.process && (
                    <>
                      <TextField
                        label="Begründung zur Umsatzidentität"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        slotProps={{ htmlInput: { maxLength: 1000 } }}
                      />
                      <Button
                        disabled={!reason.trim() || action.isPending}
                        onClick={() => {
                          const value = preview.data!;
                          action.mutate({
                            operation: "identity-merge",
                            payload: {
                              duplicate_id: value.duplicate_id,
                              canonical_id: value.canonical_id,
                              duplicate_version: value.duplicate_version,
                              canonical_version: value.canonical_version,
                              document_versions: value.document_versions,
                              reason,
                            },
                          });
                        }}
                      >
                        Identitätszusammenführung bestätigen
                      </Button>
                    </>
                  )}
                </>
              )}
              <Button
                onClick={() => {
                  void candidates.refetch();
                  if (target) void preview.refetch();
                }}
              >
                Prüfstand neu laden
              </Button>
            </>
          )}
          {merged &&
            !movement.identity_resolution?.disputed_at &&
            permissions.data?.permissions.process && (
              <>
                <Alert severity="warning">
                  Eine Beanstandung markiert die Bankdeckung als strittig. Sie
                  löscht keine Zahlung und öffnet keinen Betrag erneut.
                  Vollständige finanzielle Korrektur bleibt ein gesonderter
                  Workflow.
                </Alert>
                <TextField
                  label="Begründung zur Identitätsbeanstandung"
                  value={disputeReason}
                  onChange={(e) => setDisputeReason(e.target.value)}
                  slotProps={{ htmlInput: { maxLength: 1000 } }}
                />
                <Button
                  disabled={
                    !disputeReason.trim() ||
                    action.isPending ||
                    !movement.canonical_version
                  }
                  onClick={() =>
                    action.mutate({
                      operation: "identity-dispute",
                      payload: {
                        duplicate_id: movement.id,
                        duplicate_version: movement.version,
                        canonical_version: movement.canonical_version,
                        reason: disputeReason,
                      },
                    })
                  }
                >
                  Zusammenführung beanstanden
                </Button>
              </>
            )}
          <ErrorAlert
            error={
              permissions.error ||
              candidates.error ||
              preview.error ||
              action.error
            }
          />
          {action.isSuccess && (
            <Alert severity="success">
              Identitätsentscheidung gespeichert. Keine Zahlung erzeugt oder
              gelöscht.
            </Alert>
          )}
        </>
      )}
    </Stack>
  );
}
