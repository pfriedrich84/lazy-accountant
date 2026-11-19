import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { api, post, type Document } from "./api";
import { ErrorAlert } from "./components";

export function DocumentName({ doc }: { doc: Document }) {
  const cache = useQueryClient();
  const [name, setName] = useState(doc.handover_name || doc.effective_name);
  const save = useMutation({
    mutationFn: (value: string | null) =>
      api<Document>(`documents/${doc.id}/name/`, {
        method: "PATCH",
        body: JSON.stringify({ base_version: doc.version, name: value }),
      }),
    onSuccess: async (data) => {
      cache.setQueryData(["document", doc.id], data);
      await cache.invalidateQueries();
    },
  });
  return (
    <Paper sx={{ p: 2, mb: 2 }}>
      <Stack spacing={1}>
        <Typography variant="h6">Übergabename</Typography>
        <Typography>Originalname: {doc.original_name}</Typography>
        <Typography>Vorschlag: {doc.proposed_name}</Typography>
        <Typography>
          Verwendet: {doc.effective_name} · Quelle: {doc.name_source}
        </Typography>
        <Button component="a" href={`/api/documents/${doc.id}/download/`}>
          Original mit Übergabenamen herunterladen
        </Button>
        {doc.name_warning && (
          <Alert severity="warning">{doc.name_warning}</Alert>
        )}
        {doc.name_conflict && (
          <Alert severity="info">
            Namenskonflikt: stabiler ID-Suffix wird ergänzt. Die Dokumente
            bleiben separat.
          </Alert>
        )}
        <TextField
          label="Manueller Übergabename"
          value={name}
          onChange={(e) => setName(e.target.value)}
          fullWidth
        />
        <Typography variant="caption">
          Namensänderungen ändern keine Freigabe. Metadatenänderungen zuerst
          speichern; nach einer Namensänderung wird der Editor neu geladen.
        </Typography>
        <Stack direction="row" spacing={1}>
          <Button disabled={save.isPending} onClick={() => save.mutate(name)}>
            Namen manuell setzen
          </Button>
          <Button disabled={save.isPending} onClick={() => save.mutate(null)}>
            Generator übernehmen
          </Button>
        </Stack>
        <ErrorAlert error={save.error} />
      </Stack>
    </Paper>
  );
}

interface NamePreviewRow {
  document_id: string;
  base_version: number;
  original_name: string;
  old_name: string;
  new_name: string;
  name_source: string;
  warning: string;
  conflict: boolean;
  manual_protected: boolean;
}

export function NamePreview({ documents }: { documents: Document[] }) {
  const cache = useQueryClient();
  const [open, setOpen] = useState(false);
  const [batch, setBatch] = useState(0);
  const preview = useMutation({
    mutationFn: () =>
      post<NamePreviewRow[]>("document-names/preview/", {
        document_ids: documents
          .slice(batch * 100, (batch + 1) * 100)
          .map((d) => d.id),
      }),
    onSuccess: () => setOpen(true),
  });
  const apply = useMutation({
    mutationFn: () =>
      post("document-names/backfill/", {
        entries: preview.data?.map(({ document_id, base_version }) => ({
          document_id,
          base_version,
        })),
      }),
    onSuccess: async () => {
      setOpen(false);
      preview.reset();
      await cache.invalidateQueries();
    },
  });
  return (
    <>
      <Button
        disabled={!documents.length || preview.isPending}
        onClick={() => {
          apply.reset();
          preview.mutate();
        }}
      >
        Übergabenamen vorschauen
      </Button>
      {documents.length > 100 && (
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 1 }}>
          <Button
            disabled={batch === 0 || preview.isPending || apply.isPending}
            onClick={() => {
              setBatch((b) => b - 1);
              preview.reset();
            }}
          >
            Vorherige 100
          </Button>
          <Typography variant="caption">
            Geladene Dokumente {batch * 100 + 1}–
            {Math.min((batch + 1) * 100, documents.length)}
          </Typography>
          <Button
            disabled={
              (batch + 1) * 100 >= documents.length ||
              preview.isPending ||
              apply.isPending
            }
            onClick={() => {
              setBatch((b) => b + 1);
              preview.reset();
            }}
          >
            Nächste 100
          </Button>
        </Stack>
      )}
      <ErrorAlert error={preview.error} />
      <Dialog
        open={open}
        onClose={() => !apply.isPending && setOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Übergabenamen – Vorschau</DialogTitle>
        <DialogContent>
          <Alert severity="info">
            Bis zu 100 geladene Dokumente. Nur die explizite Übernahme ändert
            Namen und erzeugt Revisionen. Manuelle Namen, Originale, Freigaben
            und bestehende Pakete bleiben unverändert.
          </Alert>
          <Stack spacing={2} sx={{ mt: 2 }}>
            {preview.data?.map((row) => (
              <Paper
                variant="outlined"
                sx={{ p: 2, overflowWrap: "anywhere" }}
                key={row.document_id}
              >
                <Typography>Original: {row.original_name}</Typography>
                <Typography>Alt: {row.old_name}</Typography>
                <Typography>Neu: {row.new_name}</Typography>
                <Typography variant="caption">
                  Revision {row.base_version} · {row.name_source}
                  {row.manual_protected ? " · manuell geschützt" : ""}
                  {row.conflict ? " · Kollision: stabiler ID-Suffix" : ""}
                </Typography>
                {row.warning && <Alert severity="warning">{row.warning}</Alert>}
              </Paper>
            ))}
          </Stack>
          <ErrorAlert error={apply.error} />
        </DialogContent>
        <DialogActions>
          <Button disabled={apply.isPending} onClick={() => setOpen(false)}>
            Schließen
          </Button>
          <Button disabled={apply.isPending} onClick={() => apply.mutate()}>
            Namen jetzt versioniert übernehmen
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
