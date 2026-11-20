import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  api,
  APIError,
  type Assignments,
  type Document,
  idempotencyKey,
  post,
} from "./api";
import { ErrorAlert } from "./components";

export function DocumentExclusion({
  doc,
  disabled = false,
  showStatus = true,
}: {
  doc: Document;
  disabled?: boolean;
  showStatus?: boolean;
}) {
  const cache = useQueryClient();
  const [reason, setReason] = useState("");
  const [command, setCommand] = useState<{
    key: string;
    reason?: string;
  } | null>(null);
  const permissions = useQuery({
    queryKey: ["assignments", doc.company_id],
    queryFn: () => api<Assignments>(`companies/${doc.company_id}/`),
    enabled: !!doc.company_id,
  });
  // Unassigned documents reachable in the session UI belong to this user.
  const canProcess = !doc.company_id || !!permissions.data?.permissions.process;
  const action = doc.is_excluded ? "restore" : "exclude";
  const title = doc.is_excluded
    ? "Wiederherstellen"
    : "Als Nichtbeleg ausschließen";
  const change = useMutation({
    retry: false,
    mutationFn: (payload: { key: string; reason: string }) =>
      post<{ document: Document; changed: boolean }>(
        `documents/${doc.id}/${action}/`,
        {
          base_version: doc.version,
          reason: payload.reason,
          idempotency_key: payload.key,
        },
      ),
    onSuccess: async () => {
      setCommand(null);
      // A retry may replay a historical result. Always reload current state.
      await cache.invalidateQueries();
    },
  });
  const failedConflict =
    change.error instanceof APIError &&
    [400, 403, 404, 409].includes(change.error.status);
  return (
    <Stack spacing={2} sx={{ mb: 2 }}>
      {doc.is_excluded && showStatus && (
        <Alert severity="info">
          <strong>Als Nichtbeleg ausgeschlossen</strong>: {doc.exclusion_reason}
          <Typography variant="body2">
            {doc.excluded_at &&
              new Date(doc.excluded_at).toLocaleString("de-AT")}
            {` · Bearbeiter ${doc.excluded_by_id ?? "unbekannt"}. Original und Herkunft bleiben erhalten.`}
          </Typography>
        </Alert>
      )}
      {!!doc.packaged_in?.length && (
        <Alert severity="warning">
          Bereits in eingefrorenen Paketen enthalten:{" "}
          {doc.packaged_in.map((p) => (
            <Box key={p.id}>
              <Link to={`/packages`}>Paket v{p.version}</Link> ·
              Dokumentrevision {p.revision}
            </Box>
          ))}
          Ausschluss verändert diese Pakete und deren Versandaufträge nicht.
        </Alert>
      )}
      <Box>
        <Button
          variant="outlined"
          disabled={disabled || !canProcess}
          onClick={() => {
            setReason("");
            change.reset();
            setCommand({ key: idempotencyKey() });
          }}
        >
          {title}
        </Button>
      </Box>
      <Dialog
        open={!!command}
        onClose={() => {
          if (!change.isPending) setCommand(null);
        }}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>{title}</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>
            {doc.is_excluded
              ? "Der gespeicherte Fachstand wird wieder aktiv; vorhandene Prüfpunkte gelten erneut."
              : "Reversibler Ausschluss aus Eingang und neuen Paketen. Kein Original wird gelöscht; verknüpfte Dokumente bleiben unverändert."}
          </Typography>
          <TextField
            autoFocus
            fullWidth
            multiline
            label="Begründung"
            value={reason}
            disabled={change.isPending || !!command?.reason}
            slotProps={{ htmlInput: { maxLength: 1000 } }}
            onChange={(e) => setReason(e.target.value)}
          />
          <ErrorAlert error={change.error} />
          {failedConflict && (
            <Alert severity="warning">
              Auftrag nicht blind wiederholen. Schließen und aktuellen Stand neu
              laden.
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            disabled={change.isPending}
            onClick={() => {
              setCommand(null);
              void cache.invalidateQueries({ queryKey: ["document", doc.id] });
            }}
          >
            Schließen / neu laden
          </Button>
          <Button
            variant="contained"
            disabled={!reason.trim() || change.isPending || failedConflict}
            onClick={() => {
              if (!command) return;
              const payload = {
                key: command.key,
                reason: command.reason ?? reason.trim(),
              };
              setCommand(payload);
              change.mutate(payload);
            }}
          >
            {change.isPending
              ? "Wird gespeichert …"
              : change.isError
                ? "Identischen Auftrag wiederholen"
                : title}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
