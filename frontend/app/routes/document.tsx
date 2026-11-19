import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  Checkbox,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  api,
  type Assignments,
  type Document,
  type Metadata,
  kinds,
} from "../api";
import { ErrorAlert, Heading, Loading, Status } from "../components";
import { useApp } from "./shell";
import { PaymentPanel } from "../payments";

function Editor({ doc }: { doc: Document }) {
  const { companies, period: activePeriod } = useApp();
  const cache = useQueryClient();
  // Global viewing context is not evidence of an unassigned document's owner.
  const [companyId, setCompanyId] = useState(doc.company_id || "");
  const [kind, setKind] = useState(doc.kind || "");
  const [period, setPeriod] = useState(doc.period || "");
  const [accountId, setAccountId] = useState<number | "">(doc.account_id || "");
  const [categoryId, setCategoryId] = useState<number | "">(
    doc.category_id || "",
  );
  const [metadata, setMetadata] = useState<Metadata>(doc.metadata);
  const [taxes, setTaxes] = useState(
    JSON.stringify(doc.metadata.taxes || [], null, 2),
  );
  const [evidence, setEvidence] = useState(
    JSON.stringify(doc.metadata.evidence || {}, null, 2),
  );
  const [openPoints, setOpenPoints] = useState(
    (doc.metadata.open_points || []).join("\n"),
  );
  const [related, setRelated] = useState((doc.related_ids || []).join("\n"));
  const [duplicateOf, setDuplicateOf] = useState(doc.duplicate_of || "");
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState("");
  const assignments = useQuery({
    queryKey: ["assignments", companyId],
    queryFn: () => api<Assignments>(`companies/${companyId}/`),
    enabled: !!companyId,
  });
  const text = useQuery({
    queryKey: ["document-text", doc.id, page],
    queryFn: () =>
      api<{ text: string; pages?: number; structured?: unknown }>(
        `documents/${doc.id}/text/?page=${page}`,
      ),
  });
  const duplicates = useQuery({
    queryKey: ["duplicates", doc.id],
    queryFn: () =>
      api<{ document_id: string; reason: string }[]>(
        `documents/${doc.id}/duplicates/`,
      ),
  });
  const save = useMutation({
    mutationFn: (approve: boolean) =>
      api<Document>(`documents/${doc.id}/`, {
        method: "PUT",
        body: JSON.stringify({
          document_id: doc.id,
          base_version: doc.version,
          company_id: companyId || null,
          kind: kind || null,
          period: period || null,
          account_id: accountId || null,
          category_id: categoryId || null,
          metadata: {
            ...metadata,
            taxes: JSON.parse(taxes),
            evidence: JSON.parse(evidence),
            open_points: openPoints
              .split("\n")
              .map((s) => s.trim())
              .filter(Boolean),
          },
          related_ids: related
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean),
          duplicate_of: duplicateOf || null,
          approve,
        }),
      }),
    onSuccess: async (data) => {
      cache.setQueryData(["document", doc.id], data);
      await cache.invalidateQueries({
        predicate: (q) => q.queryKey[0] !== "document",
      });
      setNotice("Änderungen gespeichert.");
    },
  });
  const field = (key: keyof Metadata, label: string, type = "text") => (
    <TextField
      key={key}
      label={label}
      type={type}
      value={String(metadata[key] ?? "")}
      onChange={(e) =>
        setMetadata((m) => ({
          ...m,
          [key]: e.target.value || null,
          ...(key === "period_start" || key === "period_end"
            ? { period_assignment_confirmed: false }
            : {}),
        }))
      }
      slotProps={type === "date" ? { inputLabel: { shrink: true } } : undefined}
      fullWidth
    />
  );
  const bank = ["bank_pdf", "bank_camt", "security_pdf"].includes(kind);
  return (
    <>
      <Heading
        title={doc.original_name}
        subtitle={`Revision ${doc.version} · Original SHA256 ${doc.sha256.slice(0, 16)}…`}
        actions={
          <Stack
            direction="row"
            sx={{
              gap: 1,
            }}
          >
            <Status status={doc.status} />
            <Button component={Link} to="/documents">
              Zur Liste
            </Button>
          </Stack>
        }
      />
      <ErrorAlert error={save.error || assignments.error} />
      {doc.filing_status === "pending" && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Die Metadaten sind gespeichert, die physische Ablage ist noch
          ausstehend. Der Worker setzt die journalisierte Dateioperation fort.{" "}
          {doc.filing_error}
        </Alert>
      )}
      {notice && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {notice}
        </Alert>
      )}
      {save.error && (
        <Button
          onClick={() => {
            void cache.invalidateQueries({ queryKey: ["document", doc.id] });
          }}
        >
          Aktuellen Stand neu laden (ungespeicherte Eingaben vorher sichern)
        </Button>
      )}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            lg: "minmax(0,1fr) minmax(420px,1fr)",
          },
          gap: 3,
          alignItems: "start",
        }}
      >
        <Paper sx={{ p: 2, position: { lg: "sticky" }, top: { lg: 100 } }}>
          <Stack
            direction="row"
            sx={{
              alignItems: "center",
              gap: 1,
              justifyContent: "space-between",
              mb: 2,
            }}
          >
            <Typography
              sx={{
                fontWeight: 700,
              }}
            >
              Originalvorschau
            </Typography>
            <Button
              component="a"
              href={`/api/documents/${doc.id}/original/`}
              target="_blank"
              rel="noreferrer"
            >
              Original öffnen
            </Button>
          </Stack>
          {doc.media_type === "application/xml" ? (
            <Box
              component="pre"
              sx={{
                p: 1,
                fontSize: ".75rem",
                maxHeight: "65vh",
                overflow: "auto",
                whiteSpace: "pre-wrap",
              }}
            >
              {JSON.stringify(doc.parser_result, null, 2)}
            </Box>
          ) : (
            <Box
              sx={{
                bgcolor: "#e9eeec",
                p: 1,
                maxHeight: "72vh",
                overflow: "auto",
                borderRadius: 1,
              }}
            >
              <img
                className="preview-page"
                src={`/api/documents/${doc.id}/page/?page=${page}`}
                alt={`Originalseite ${page} von ${doc.original_name}`}
              />
            </Box>
          )}
          {doc.media_type === "application/pdf" && (
            <Stack
              direction="row"
              sx={{
                alignItems: "center",
                justifyContent: "center",
                gap: 2,
                mt: 2,
              }}
            >
              <Button
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Zurück
              </Button>
              <Typography>
                Seite {page} / {text.data?.pages || "?"}
              </Typography>
              <Button
                disabled={page >= (text.data?.pages || 1)}
                onClick={() => setPage((p) => p + 1)}
              >
                Weiter
              </Button>
            </Stack>
          )}
          <Accordion sx={{ mt: 2 }}>
            <AccordionSummary>Text-/CAMT-Auslese anzeigen</AccordionSummary>
            <AccordionDetails>
              <ErrorAlert error={text.error} />
              <Box
                component="pre"
                sx={{
                  whiteSpace: "pre-wrap",
                  fontSize: ".8rem",
                  maxHeight: 300,
                  overflow: "auto",
                }}
              >
                {text.data?.text ||
                  "Keine Textebene vorhanden. Original visuell prüfen."}
              </Box>
            </AccordionDetails>
          </Accordion>
        </Paper>
        <Stack spacing={2}>
          <PaymentPanel doc={doc} />
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Zuordnung & Prüfung
            </Typography>
            {doc.issues.length > 0 && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                <strong>{doc.issues.length} offene Prüfpunkte</strong>
                <ul style={{ marginBottom: 0, paddingLeft: 18 }}>
                  {doc.issues.map((i, n) => (
                    <li key={n}>{i}</li>
                  ))}
                </ul>
              </Alert>
            )}
            <Stack spacing={2}>
              <TextField
                select
                label="Firma"
                slotProps={{
                  select: { displayEmpty: true },
                  inputLabel: { shrink: true },
                }}
                helperText={
                  !companyId
                    ? "Firma ist ungeklärt – Original prüfen und bewusst auswählen."
                    : undefined
                }
                value={companyId}
                onChange={(e) => {
                  setCompanyId(e.target.value ? Number(e.target.value) : "");
                  setAccountId("");
                  setCategoryId("");
                }}
              >
                <MenuItem value="">Ungeklärt</MenuItem>
                {companies.map((c) => (
                  <MenuItem value={c.id} key={c.id}>
                    {c.name}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Dokumentart"
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value);
                  setAccountId("");
                }}
              >
                <MenuItem value="">Ungeklärt</MenuItem>
                {Object.entries(kinds).map(([k, v]) => (
                  <MenuItem value={k} key={k}>
                    {v}
                  </MenuItem>
                ))}
              </TextField>
              <Stack
                direction="row"
                sx={{
                  gap: 1,
                }}
              >
                <TextField
                  label="Übergabemonat"
                  type="month"
                  value={period}
                  onChange={(e) => {
                    setPeriod(e.target.value);
                    setMetadata((m) => ({
                      ...m,
                      period_assignment_confirmed: false,
                    }));
                  }}
                  slotProps={{ inputLabel: { shrink: true } }}
                  fullWidth
                />
                <Button
                  onClick={() =>
                    setPeriod(
                      metadata.date?.slice(0, 7) ||
                        metadata.period_end?.slice(0, 7) ||
                        activePeriod,
                    )
                  }
                >
                  Aus Datum
                </Button>
              </Stack>
              <TextField
                select
                label="Kategorie"
                value={categoryId}
                onChange={(e) =>
                  setCategoryId(e.target.value ? Number(e.target.value) : "")
                }
              >
                <MenuItem value="">Keine Kategorie</MenuItem>
                {assignments.data?.categories.map((c) => (
                  <MenuItem key={c.id} value={c.id}>
                    {c.name}
                  </MenuItem>
                ))}
              </TextField>
              {bank && (
                <>
                  <TextField
                    select
                    label={kind === "security_pdf" ? "Depot" : "Bankkonto"}
                    value={accountId}
                    onChange={(e) =>
                      setAccountId(e.target.value ? Number(e.target.value) : "")
                    }
                  >
                    <MenuItem value="">Ungeklärt</MenuItem>
                    {assignments.data?.accounts
                      .filter(
                        (a) =>
                          a.kind ===
                          (kind === "security_pdf" ? "depot" : "bank"),
                      )
                      .map((a) => (
                        <MenuItem key={a.id} value={a.id}>
                          {a.name} · {a.identifier}
                        </MenuItem>
                      ))}
                  </TextField>
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    sx={{
                      gap: 2,
                    }}
                  >
                    {field("period_start", "Auszugsbeginn", "date")}
                    {field("period_end", "Auszugsende", "date")}
                  </Stack>
                  {metadata.period_start &&
                    metadata.period_end &&
                    metadata.period_start.slice(0, 7) !==
                      metadata.period_end.slice(0, 7) && (
                      <Alert severity="warning">
                        <Stack sx={{ gap: 1 }}>
                          <Typography>
                            Mehrmonatiger Originalzeitraum bleibt unverändert.
                            Die Ablage in einem einzelnen Übergabemonat muss
                            bewusst bestätigt werden.
                          </Typography>
                          <FormControlLabel
                            control={
                              <Checkbox
                                checked={!!metadata.period_assignment_confirmed}
                                onChange={(e) =>
                                  setMetadata((m) => ({
                                    ...m,
                                    period_assignment_confirmed:
                                      e.target.checked,
                                  }))
                                }
                              />
                            }
                            label="Zuordnung zum gewählten Übergabemonat ausdrücklich bestätigt"
                          />
                          {field(
                            "period_assignment_reason",
                            "Begründung der mehrmonatigen Zuordnung",
                          )}
                        </Stack>
                      </Alert>
                    )}
                  {field("subtype", "Unterart")}
                </>
              )}
              <Stack
                direction={{ xs: "column", sm: "row" }}
                sx={{
                  gap: 2,
                }}
              >
                {field("issuer", "Aussteller / Lieferant")}
                {field("recipient", "Empfänger / Kunde")}
              </Stack>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                sx={{
                  gap: 2,
                }}
              >
                {field("number", "Belegnummer")}
                {field("date", "Belegdatum", "date")}
              </Stack>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                sx={{
                  gap: 2,
                }}
              >
                {field("service_date", "Leistungsdatum", "date")}
                {field("due_date", "Fälligkeit", "date")}
              </Stack>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2,1fr)",
                  gap: 2,
                }}
              >
                {field("net", "Netto (z. B. 100.00)")}
                {field("tax", "Steuer (z. B. 20.00)")}
                {field("gross", "Brutto (z. B. 120.00)")}
                {field("currency", "Währung (ISO, z. B. EUR)")}
              </Box>
              <TextField
                label="Notiz"
                multiline
                minRows={2}
                value={metadata.note || ""}
                onChange={(e) =>
                  setMetadata((m) => ({ ...m, note: e.target.value }))
                }
              />
              <TextField
                label="Offene Punkte (einer pro Zeile)"
                multiline
                minRows={2}
                value={openPoints}
                onChange={(e) => setOpenPoints(e.target.value)}
              />
              <Accordion>
                <AccordionSummary>
                  Steueraufteilung, Belegstellen & Verknüpfungen
                </AccordionSummary>
                <AccordionDetails>
                  <Stack spacing={2}>
                    <TextField
                      label="Steueraufteilungen (JSON: rate, net, tax als Strings)"
                      multiline
                      minRows={3}
                      value={taxes}
                      onChange={(e) => setTaxes(e.target.value)}
                    />
                    <TextField
                      label="Belegstellen / Unsicherheit (JSON)"
                      multiline
                      minRows={3}
                      value={evidence}
                      onChange={(e) => setEvidence(e.target.value)}
                    />
                    <TextField
                      label="Verweise auf zugehörige Dokument-IDs (eine pro Zeile)"
                      helperText="Diese Verweise gehören zur Revision dieses Dokuments. Eingehende Verweise werden im jeweiligen Quelldokument geändert."
                      multiline
                      value={related}
                      onChange={(e) => setRelated(e.target.value)}
                    />
                    {(doc.referenced_by_ids?.length || 0) > 0 && (
                      <Alert severity="info">
                        Andere Dokumente verweisen auf dieses Original:{" "}
                        {doc.referenced_by_ids?.map((id) => (
                          <Box key={id}>
                            <Link to={`/documents/${id}`}>{id}</Link>
                          </Box>
                        ))}
                      </Alert>
                    )}
                    <TextField
                      label="Dublette von (Dokument-ID)"
                      value={duplicateOf}
                      onChange={(e) => setDuplicateOf(e.target.value)}
                    />
                  </Stack>
                </AccordionDetails>
              </Accordion>
              {!!duplicates.data?.length && (
                <Alert severity="warning">
                  Dublettenhinweise:
                  {duplicates.data.map((h) => (
                    <Box key={h.document_id}>
                      <Link to={`/documents/${h.document_id}`}>{h.reason}</Link>
                    </Box>
                  ))}
                </Alert>
              )}
              <Stack
                direction="row"
                sx={{
                  gap: 2,
                  flexWrap: "wrap",
                }}
              >
                <Button
                  variant="outlined"
                  disabled={save.isPending}
                  onClick={() => save.mutate(false)}
                >
                  Zwischenstand speichern
                </Button>
                <Button
                  variant="contained"
                  disabled={save.isPending}
                  onClick={() => save.mutate(true)}
                >
                  Prüfen & freigeben
                </Button>
              </Stack>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                }}
              >
                Freigabe erfolgt nur bei vollständigen, plausiblen Daten. Neuere
                Korrekturen können nicht mit einer alten Revision überschrieben
                werden.
              </Typography>
            </Stack>
          </Paper>
          <Paper sx={{ p: 3 }}>
            <Typography
              sx={{
                fontWeight: 700,
              }}
            >
              Ablage & Nachvollziehbarkeit
            </Typography>
            <Typography className="file-path" sx={{ mt: 1 }}>
              {doc.filed_path}
            </Typography>
            <Typography
              variant="caption"
              sx={{ display: "block", mt: 1, overflowWrap: "anywhere" }}
            >
              SHA256: {doc.sha256}
            </Typography>
            <Stack
              direction="row"
              sx={{
                gap: 1,
                flexWrap: "wrap",
                mt: 2,
              }}
            >
              {doc.revisions?.map((r) => (
                <Chip
                  key={r.version}
                  size="small"
                  label={`v${r.version} · ${r.source} · ${new Date(r.created_at).toLocaleString("de-AT")}`}
                />
              ))}
            </Stack>
            <Accordion sx={{ mt: 2 }}>
              <AccordionSummary>Importherkunft</AccordionSummary>
              <AccordionDetails>
                <Box
                  component="pre"
                  sx={{
                    whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                    fontSize: ".75rem",
                  }}
                >
                  {JSON.stringify(doc.sources, null, 2)}
                </Box>
              </AccordionDetails>
            </Accordion>
          </Paper>
        </Stack>
      </Box>
    </>
  );
}

export default function DocumentDetail() {
  const { documentId } = useParams();
  const query = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api<Document>(`documents/${documentId}/`),
  });
  if (query.isPending) return <Loading />;
  if (!query.data) return <ErrorAlert error={query.error} />;
  return (
    <Editor key={`${query.data.id}:${query.data.version}`} doc={query.data} />
  );
}
