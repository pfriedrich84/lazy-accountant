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
  Tab,
  Tabs,
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
import { DocumentExclusion } from "../document-exclusion";
import { DocumentName } from "../document-names";

const expandIcon = (
  <svg
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    aria-hidden="true"
  >
    <path d="m6 9 6 6 6-6" />
  </svg>
);

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
  const [mobileView, setMobileView] = useState("data");
  const [zoom, setZoom] = useState(100);
  const [previewError, setPreviewError] = useState(false);
  const dirty =
    JSON.stringify({
      companyId,
      kind,
      period,
      accountId,
      categoryId,
      metadata,
      taxes,
      evidence,
      openPoints,
      related,
      duplicateOf,
    }) !==
    JSON.stringify({
      companyId: doc.company_id || "",
      kind: doc.kind || "",
      period: doc.period || "",
      accountId: doc.account_id || "",
      categoryId: doc.category_id || "",
      metadata: doc.metadata,
      taxes: JSON.stringify(doc.metadata.taxes || [], null, 2),
      evidence: JSON.stringify(doc.metadata.evidence || {}, null, 2),
      openPoints: (doc.metadata.open_points || []).join("\n"),
      related: (doc.related_ids || []).join("\n"),
      duplicateOf: doc.duplicate_of || "",
    });
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
      size="small"
    />
  );
  const bank = ["bank_pdf", "bank_camt", "security_pdf"].includes(kind);
  return (
    <Box
      className="document-workspace"
      sx={{ pb: { xs: 20, sm: 12 }, minWidth: 0 }}
    >
      <Button component={Link} to="/documents" size="small" sx={{ mb: 1 }}>
        Zur Liste
      </Button>
      <Stack direction="row" sx={{ alignItems: "start", gap: 2, mb: 3 }}>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography
            component="h1"
            variant="h5"
            sx={{
              overflowWrap: "anywhere",
              fontWeight: 700,
              fontSize: { xs: "1.125rem", sm: "1.5rem" },
              lineHeight: 1.35,
            }}
          >
            {doc.effective_name}
          </Typography>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ mt: 0.75, display: { xs: "none", sm: "block" } }}
          >
            Original prüfen, Angaben ergänzen und für die Übergabe freigeben.
          </Typography>
        </Box>
        <Status status={doc.status} />
      </Stack>
      {doc.is_excluded && (
        <Alert severity="info" sx={{ mb: 2 }}>
          <strong>Als Nichtbeleg ausgeschlossen</strong>: {doc.exclusion_reason}
          <Typography variant="body2">
            Die Bearbeitung ist gesperrt. Unter „Dokument verwalten“ lässt sich
            der Beleg wiederherstellen.
          </Typography>
          <Typography variant="caption">
            {doc.excluded_at &&
              new Date(doc.excluded_at).toLocaleString("de-AT")}{" "}
            · Bearbeiter {doc.excluded_by_id ?? "unbekannt"}. Original und
            Herkunft bleiben erhalten.
          </Typography>
        </Alert>
      )}
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
      <Tabs
        value={mobileView}
        onChange={(_, value: string) => setMobileView(value)}
        aria-label="Dokumentansicht"
        sx={{
          display: { xs: "flex", lg: "none" },
          mb: 2,
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Tab
          value="data"
          label="Prüfdaten"
          id="document-data-tab"
          aria-controls="document-data"
        />
        <Tab
          value="original"
          label="Original"
          id="document-original-tab"
          aria-controls="document-original"
        />
      </Tabs>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            lg: "minmax(0,1.15fr) minmax(380px,1fr)",
          },
          gap: 3,
          alignItems: "start",
        }}
      >
        <Paper
          id="document-original"
          aria-label="Originalvorschau"
          component="section"
          sx={{
            p: 2,
            minWidth: 0,
            display: {
              xs: mobileView === "original" ? "block" : "none",
              lg: "block",
            },
            position: { lg: "sticky" },
            top: { lg: 96 },
          }}
        >
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
              Original
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
          {doc.media_type !== "application/xml" && (
            <Stack
              direction="row"
              sx={{ gap: 1, alignItems: "center", mb: 1, flexWrap: "wrap" }}
            >
              <Button
                size="small"
                aria-label="Verkleinern"
                disabled={zoom <= 100}
                onClick={() => setZoom((z) => z - 25)}
              >
                −
              </Button>
              <Typography
                variant="body2"
                sx={{ fontVariantNumeric: "tabular-nums" }}
              >
                {zoom}%
              </Typography>
              <Button
                size="small"
                aria-label="Vergrößern"
                disabled={zoom >= 250}
                onClick={() => setZoom((z) => z + 25)}
              >
                +
              </Button>
              <Button size="small" onClick={() => setZoom(100)}>
                Einpassen
              </Button>
            </Stack>
          )}
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
                maxHeight: "calc(100dvh - 310px)",
                minHeight: 240,
                overflow: "auto",
                borderRadius: 1,
              }}
            >
              {previewError && (
                <Alert severity="warning">
                  Die Vorschau konnte nicht geladen werden. Bitte das Original
                  öffnen.
                </Alert>
              )}
              <Box sx={{ width: `${zoom}%`, minWidth: "100%" }}>
                <img
                  key={page}
                  className="preview-page"
                  src={`/api/documents/${doc.id}/page/?page=${page}`}
                  alt={`Originalseite ${page} von ${doc.original_name}`}
                  onError={() => setPreviewError(true)}
                  onLoad={() => setPreviewError(false)}
                  style={{ width: "100%" }}
                />
              </Box>
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
        <Stack
          id="document-data"
          component="section"
          aria-label="Prüfdaten"
          spacing={2}
          sx={{
            minWidth: 0,
            display: {
              xs: mobileView === "data" ? "flex" : "none",
              lg: "flex",
            },
          }}
        >
          <Paper
            component="fieldset"
            disabled={!!doc.is_excluded}
            sx={{
              p: { xs: 2, sm: 3 },
              m: 0,
              minWidth: 0,
              border: 0,
              "& .MuiTextField-root": { minWidth: 0 },
              "& .MuiInputBase-root": { fontSize: "0.9rem" },
            }}
          >
            <Stack
              direction="row"
              sx={{
                justifyContent: "space-between",
                alignItems: "baseline",
                gap: 2,
                mb: 2,
              }}
            >
              <Typography variant="h6" component="h2">
                Zuordnung & Prüfung
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Revision {doc.version}
              </Typography>
            </Stack>
            {doc.issues.length > 0 && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                <strong>
                  {doc.issues.length}{" "}
                  {doc.issues.length === 1
                    ? "offener Prüfpunkt"
                    : "offene Prüfpunkte"}
                </strong>
                <ul style={{ marginBottom: 0, paddingLeft: 18 }}>
                  {doc.issues.map((i, n) => (
                    <li key={n}>{i}</li>
                  ))}
                </ul>
              </Alert>
            )}
            <Stack spacing={2}>
              <Typography component="h3" variant="subtitle2">
                Zuordnung
              </Typography>
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
                  sx={{ whiteSpace: "nowrap", flexShrink: 0 }}
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
                  {field("bank_short_name", "Belegter Bank-Kurzname")}
                  {kind === "security_pdf" && (
                    <>
                      {field("valuation_date", "Bewertungsstichtag", "date")}
                      {field("isin", "ISIN")}
                    </>
                  )}
                </>
              )}
              <Typography
                component="h3"
                variant="subtitle2"
                sx={{ pt: 2, borderTop: 1, borderColor: "divider" }}
              >
                Belegdaten
              </Typography>
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
              <Typography
                component="h3"
                variant="subtitle2"
                sx={{ pt: 2, borderTop: 1, borderColor: "divider" }}
              >
                Beträge
              </Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2,minmax(0,1fr))",
                  gap: 2,
                }}
              >
                {field("net", "Netto (z. B. 100.00)")}
                {field("tax", "Steuer (z. B. 20.00)")}
                {field("gross", "Brutto (z. B. 120.00)")}
                {field("currency", "Währung (ISO, z. B. EUR)")}
              </Box>
              <Typography
                component="h3"
                variant="subtitle2"
                sx={{ pt: 2, borderTop: 1, borderColor: "divider" }}
              >
                Ergänzungen
              </Typography>
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
              <Accordion
                disableGutters
                elevation={0}
                sx={{
                  border: 1,
                  borderColor: "divider",
                  "&:before": { display: "none" },
                }}
              >
                <AccordionSummary expandIcon={expandIcon}>
                  Weitere Angaben & Verknüpfungen
                </AccordionSummary>
                <AccordionDetails>
                  <Stack spacing={2}>
                    {field(
                      "subtype",
                      "Unterart (z. B. Zahlungsbeleg oder Depotaufstellung)",
                    )}
                    {field(
                      "confirmed_partner_name",
                      "Bestätigte Geschäftspartnerbezeichnung (optional)",
                    )}
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
          {!doc.is_excluded &&
            ["incoming_invoice", "outgoing_invoice", "bank_camt"].includes(
              doc.kind,
            ) &&
            !!doc.company_id && (
              <Accordion
                disableGutters
                slotProps={{ transition: { mountOnEnter: true } }}
              >
                <AccordionSummary expandIcon={expandIcon}>
                  <Typography
                    component="span"
                    variant="subtitle1"
                    sx={{ fontWeight: 600 }}
                  >
                    Bankabgleich & Zahlungsstand
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <PaymentPanel doc={doc} embedded />
                </AccordionDetails>
              </Accordion>
            )}
          <Accordion disableGutters>
            <AccordionSummary expandIcon={expandIcon}>
              <Typography
                component="span"
                variant="subtitle1"
                sx={{ fontWeight: 600 }}
              >
                Dokument verwalten
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              {dirty && (
                <Alert severity="info" sx={{ mb: 2 }}>
                  Bitte zuerst die Prüfdaten speichern. Namensänderungen und
                  Ausschluss laden die Dokumentrevision neu.
                </Alert>
              )}
              <DocumentName
                doc={doc}
                disabled={dirty || save.isPending}
                embedded
              />
              <DocumentExclusion
                doc={doc}
                disabled={dirty || save.isPending}
                showStatus={false}
              />
            </AccordionDetails>
          </Accordion>
          <Accordion disableGutters>
            <AccordionSummary expandIcon={expandIcon}>
              <Typography
                component="span"
                variant="subtitle1"
                sx={{ fontWeight: 600 }}
              >
                Ablage & Nachvollziehbarkeit
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
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
                    label={`v${r.version} · ${r.source} · Bearbeiter ${r.actor_id} · ${new Date(r.created_at).toLocaleString("de-AT")}${r.reason ? ` · ${r.reason}` : ""}`}
                    sx={{
                      height: "auto",
                      "& .MuiChip-label": { whiteSpace: "normal", py: 0.5 },
                    }}
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
            </AccordionDetails>
          </Accordion>
        </Stack>
      </Box>
      <Paper
        component="section"
        aria-label="Prüfung abschließen"
        square
        sx={{
          position: "fixed",
          bottom: 0,
          left: { xs: 0, md: 240 },
          right: 0,
          zIndex: (theme) => theme.zIndex.appBar - 1,
          borderTop: 1,
          borderColor: "divider",
          px: { xs: 2, sm: 3, lg: 4 },
          pt: 1.5,
          pb: "max(12px, env(safe-area-inset-bottom))",
          boxShadow: "0 -4px 20px #102c240a",
        }}
      >
        <Stack
          direction={{ xs: "column", sm: "row" }}
          sx={{
            maxWidth: 1636,
            mx: "auto",
            gap: 1,
            justifyContent: "space-between",
            alignItems: { sm: "center" },
          }}
        >
          <Typography
            variant="body2"
            color="text.secondary"
            role="status"
            aria-live="polite"
          >
            {save.isPending
              ? "Wird gespeichert …"
              : doc.is_excluded
                ? "Beleg ausgeschlossen"
                : dirty
                  ? "Ungespeicherte Änderungen"
                  : "Keine ungespeicherten Änderungen"}
          </Typography>
          <Stack
            direction="row"
            sx={{ gap: 1, "& > button": { flex: { xs: 1, sm: "initial" } } }}
          >
            <Button
              variant="outlined"
              disabled={save.isPending || !!doc.is_excluded}
              onClick={() => save.mutate(false)}
            >
              Zwischenstand speichern
            </Button>
            <Button
              variant="contained"
              disabled={save.isPending || !!doc.is_excluded}
              onClick={() => save.mutate(true)}
            >
              Prüfen & freigeben
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Box>
  );
}

export default function DocumentDetail() {
  const { documentId } = useParams();
  const query = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api<Document>(`documents/${documentId}/`),
    refetchInterval: 3000,
  });
  const rescan = useMutation({
    mutationFn: () => api(`documents/${documentId}/scan/`, { method: "POST" }),
    onSuccess: () => query.refetch(),
  });
  if (query.isPending) return <Loading />;
  if (!query.data) return <ErrorAlert error={query.error} />;
  if (query.data.security_status !== "clean") {
    const doc = query.data;
    return (
      <Stack spacing={2}>
        <Heading
          title={doc.original_name}
          subtitle={`SHA256 ${doc.sha256} · ${doc.size} Bytes`}
        />
        <Alert
          severity={doc.security_status === "infected" ? "error" : "warning"}
        >
          Sicherheitssperre: {doc.security_status}. {doc.security_error}
          Vorschau, Original, Textextraktion, Bearbeitung und Paketaufnahme sind
          gesperrt.
        </Alert>
        <Typography>
          Malwareprüfung ist eine zusätzliche Schutzschicht, keine
          Sicherheitsgarantie.
        </Typography>
        {!!doc.security_impact?.package_ids.length && (
          <Alert severity="error">
            Betroffene Pakete: {doc.security_impact.package_ids.join(", ")}.
            Versandaufträge: {doc.security_impact.dispatch_ids.join(", ")}
          </Alert>
        )}
        <ErrorAlert error={rescan.error} />
        <Button
          disabled={
            rescan.isPending ||
            ["pending", "scanning"].includes(doc.security_status)
          }
          onClick={() => rescan.mutate()}
        >
          Erneute Prüfung anfordern (keine Freigabe ohne Scan)
        </Button>
        <Button component={Link} to="/documents">
          Zur Liste
        </Button>
      </Stack>
    );
  }
  return (
    <Editor key={`${query.data.id}:${query.data.version}`} doc={query.data} />
  );
}
