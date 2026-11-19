import { useEffect, useState } from "react";
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
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  api,
  bytes,
  type Dispatch,
  type Job,
  type Package,
  type Preview,
  idempotencyKey,
  kinds,
  post,
} from "../api";
import { Empty, ErrorAlert, Heading, Status } from "../components";
import { useApp } from "./shell";

export default function Packages() {
  const { companyId, period } = useApp();
  const cache = useQueryClient();
  const [extraPeriods, setExtraPeriods] = useState("");
  const [parentId, setParentId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [jobId, setJobId] = useState("");
  const [confirmation, setConfirmation] = useState<{
    packageId: string;
    resendOf?: string;
  } | null>(null);
  const list = useQuery({
    queryKey: ["packages", companyId],
    queryFn: () => api<Package[]>(`packages/?company_id=${companyId}`),
    enabled: !!companyId,
    refetchInterval: 10_000,
  });
  const dispatches = useQuery({
    queryKey: ["dispatches", companyId],
    queryFn: () => api<Dispatch[]>(`dispatches/?company_id=${companyId}`),
    enabled: !!companyId,
    refetchInterval: 5000,
  });
  const jobs = useQuery({
    queryKey: ["jobs", companyId],
    queryFn: () => api<Job[]>(`jobs/?company_id=${companyId}`),
    enabled: !!companyId,
    refetchInterval: 5000,
  });
  const selected = useQuery({
    queryKey: ["package", selectedId],
    queryFn: () => api<Package>(`packages/${selectedId}/`),
    enabled: !!selectedId,
  });
  const preview = useMutation({
    mutationFn: () =>
      post<Preview>("packages/preview/", {
        company_id: companyId,
        periods: [
          period,
          ...extraPeriods
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        ],
        parent_id: parentId || null,
      }),
    onSuccess: () => setSelectedId(""),
  });
  const create = useMutation({
    mutationFn: () =>
      post<Job>("packages/", {
        company_id: companyId,
        periods: preview.data?.periods,
        parent_id: preview.data?.parent_id,
        idempotency_key: idempotencyKey(),
      }),
    onSuccess: (j) => {
      setJobId(j.id);
      void cache.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api<Job>(`jobs/${jobId}/`),
    enabled: !!jobId,
    refetchInterval: (q) =>
      ["done", "failed"].includes(q.state.data?.status || "") ? false : 1500,
  });
  useEffect(() => {
    if (job.data?.status === "done" && job.data.result.id) {
      setSelectedId(String(job.data.result.id));
      void cache.invalidateQueries({ queryKey: ["packages"] });
      void cache.invalidateQueries({ queryKey: ["jobs"] });
    }
  }, [job.data, cache]);
  const send = useMutation({
    mutationFn: (p: { packageId: string; resendOf?: string }) =>
      post<Dispatch>(`packages/${p.packageId}/send/`, {
        idempotency_key: idempotencyKey(),
        resend_of: p.resendOf || null,
      }),
    onSuccess: () => {
      setConfirmation(null);
      void cache.invalidateQueries({ queryKey: ["dispatches"] });
      void cache.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const resume = useMutation({
    mutationFn: (id: string) => post<Job>(`jobs/${id}/resume/`, {}),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["jobs"] }),
  });
  const shown = selectedId ? selected.data?.snapshot : preview.data;
  return (
    <>
      <Heading
        title="Übergabe & Versand"
        subtitle="Erst Vollständigkeit prüfen, dann einen unveränderlichen Snapshot erzeugen und ausdrücklich versenden."
      />
      <ErrorAlert
        error={
          list.error ||
          dispatches.error ||
          jobs.error ||
          selected.error ||
          preview.error ||
          create.error ||
          send.error ||
          resume.error
        }
      />
      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          sx={{
            gap: 2,
            alignItems: { md: "center" },
          }}
        >
          <Typography
            sx={{
              fontWeight: 700,
              minWidth: 150,
            }}
          >
            Übergabe {period}
          </Typography>
          <TextField
            label="Weitere Monate (optional, durch Komma getrennt)"
            placeholder="2026-09, 2026-11"
            value={extraPeriods}
            onChange={(e) => setExtraPeriods(e.target.value)}
            sx={{ flex: 1 }}
          />
          <TextField
            select
            label="Nachtrag zu"
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
            sx={{ minWidth: 220 }}
          >
            <MenuItem value="">Vollständiges Paket</MenuItem>
            {list.data?.map((p) => (
              <MenuItem key={p.id} value={p.id}>
                Version {p.version} · {p.periods.join(", ")}
              </MenuItem>
            ))}
          </TextField>
          <Button
            variant="contained"
            disabled={!companyId || preview.isPending}
            onClick={() => preview.mutate()}
          >
            Vorschau erstellen
          </Button>
        </Stack>
      </Paper>
      {shown && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            sx={{
              gap: 2,
              justifyContent: "space-between",
              mb: 2,
            }}
          >
            <Box>
              <Typography variant="h5">
                {selectedId
                  ? `Paketversion ${selected.data?.version}`
                  : "Paketvorschau"}
              </Typography>
              <Typography
                sx={{
                  color: "text.secondary",
                }}
              >
                {shown.company.name} · {shown.periods.join(", ")} ·{" "}
                {shown.count} Originale · {bytes(shown.bytes)}
              </Typography>
            </Box>
            <Stack
              direction="row"
              sx={{
                gap: 1,
              }}
            >
              {selectedId ? (
                <>
                  <Button
                    component="a"
                    href={`/api/packages/${selectedId}/download/`}
                    variant="outlined"
                  >
                    ZIP herunterladen
                  </Button>
                  <Button
                    variant="contained"
                    onClick={() => {
                      const prior = dispatches.data?.find(
                        (d) => d.package_id === selectedId,
                      );
                      setConfirmation({
                        packageId: selectedId,
                        resendOf: prior?.id,
                      });
                    }}
                    disabled={send.isPending}
                  >
                    Versand vorbereiten
                  </Button>
                </>
              ) : (
                <Button
                  variant="contained"
                  onClick={() => create.mutate()}
                  disabled={
                    create.isPending ||
                    shown.count === 0 ||
                    (!!shown.max_package_bytes &&
                      shown.bytes > shown.max_package_bytes) ||
                    (!!jobId &&
                      ["queued", "running"].includes(job.data?.status || ""))
                  }
                >
                  Paket verbindlich erzeugen
                </Button>
              )}
            </Stack>
          </Stack>
          <Typography sx={{ mb: 2 }}>
            <strong>Empfänger:</strong>{" "}
            {shown.recipients.join(", ") ||
              "Keine hinterlegt – vor Paketbildung in Einstellungen ergänzen."}
          </Typography>
          {!selectedId &&
          shown.max_package_bytes &&
          shown.bytes > shown.max_package_bytes ? (
            <Alert severity="error" sx={{ mb: 2 }}>
              Die Originale überschreiten das konfigurierte Paketlimit von{" "}
              {bytes(shown.max_package_bytes)}. Weniger Monate auswählen oder
              das Betriebslimit bewusst anpassen.
            </Alert>
          ) : null}
          {shown.parent_id && (
            <Alert severity="info" sx={{ mb: 2 }}>
              Nachtrag zu {shown.parent_id}. {shown.unchanged.length}{" "}
              unveränderte Dokumente aus Vorgängern werden nicht erneut
              aufgenommen.
            </Alert>
          )}
          {!!shown.intentional_exclusions?.length && (
            <Alert severity="info" sx={{ mb: 2 }}>
              <strong>
                Bewusst ausgeschlossene Nichtbelege (nicht blockierend)
              </strong>
              {shown.intentional_exclusions.map((e) => (
                <Box key={e.document.id}>
                  <Link to={`/documents/${e.document.id}`}>
                    {e.document.original_name}
                  </Link>
                  {` · ${e.document.period || "ohne Monatszuordnung"}: ${e.reason}`}
                </Box>
              ))}
            </Alert>
          )}
          {!!shown.excluded_inbox?.length && (
            <Alert severity="info" sx={{ mb: 2 }}>
              {shown.excluded_inbox.length} ausgeschlossene Nichtbelege in Ihrer
              persönlichen Inbox (nicht blockierend, nicht in diesem
              Firmenexport enthalten).
            </Alert>
          )}
          {!!shown.exclusion_changes?.length && (
            <Alert severity="info" sx={{ mb: 2 }}>
              <strong>
                Ausschluss-/Wiederherstellungsänderungen zum Vorgänger
              </strong>
              {shown.exclusion_changes.map((e) => (
                <Box key={e.document_id}>
                  <Link to={`/documents/${e.document_id}`}>
                    {e.original_name}
                  </Link>
                  {` · ${e.action === "exclude" ? "Ausgeschlossen" : "Wiederhergestellt"} · v${e.old_revision} → v${e.new_revision}: ${e.reason}`}
                </Box>
              ))}
              Bereits erstellte Pakete und Versandaufträge bleiben unverändert.
            </Alert>
          )}
          {(shown.excluded.length > 0 || shown.unassigned_inbox.length > 0) && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              <strong>Offene Punkte bleiben sichtbar.</strong>{" "}
              {shown.excluded.length} prüfbedingt ausgeschlossene Dokumente und{" "}
              {shown.unassigned_inbox.length} Dokumente ohne Firmenzuordnung.{" "}
              {shown.allow_open_issues
                ? "Versandregel erlaubt offene Punkte."
                : "Versand ist mit diesen offenen Punkten gesperrt."}
              {shown.excluded.map((e) => (
                <Box key={e.document.id}>
                  <Link to={`/documents/${e.document.id}`}>
                    {e.document.original_name}
                  </Link>
                  : {e.reason}
                </Box>
              ))}
            </Alert>
          )}
          <TableContainer>
            <Table size="small" sx={{ minWidth: 650 }}>
              <TableHead>
                <TableRow>
                  <TableCell>Original</TableCell>
                  <TableCell>Art</TableCell>
                  <TableCell>Pfad im ZIP</TableCell>
                  <TableCell>Revision</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {shown.documents.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell>
                      <Link to={`/documents/${d.id}`}>{d.original_name}</Link>
                    </TableCell>
                    <TableCell>{kinds[d.kind]}</TableCell>
                    <TableCell>
                      <span className="file-path">{d.archive_path}</span>
                    </TableCell>
                    <TableCell>{d.version}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <Typography
            variant="caption"
            sx={{
              color: "text.secondary",
              display: "block",
              mt: 2,
            }}
          >
            Enthalten sind Originale, CSV/XLSX, Begleitschreiben und
            Inhaltsliste mit Prüfsummen. Alle vier Monatsordner bleiben
            erhalten. Ein erzeugtes Paket ändert sich nicht mehr.
          </Typography>
        </Paper>
      )}
      {job.data && (
        <Alert
          severity={job.data.status === "failed" ? "error" : "info"}
          sx={{ mb: 3 }}
        >
          Paketerstellung: <Status status={job.data.status} /> {job.data.error}
        </Alert>
      )}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", xl: "1fr 1fr" },
          gap: 3,
        }}
      >
        <Box>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Gespeicherte Paketversionen
          </Typography>
          {!list.data?.length ? (
            <Empty
              title="Noch keine Pakete"
              text="Erstellen Sie zuerst eine Vorschau für den gewählten Monat."
            />
          ) : (
            <Paper>
              {list.data.map((p) => (
                <Stack
                  key={p.id}
                  direction="row"
                  sx={{
                    justifyContent: "space-between",
                    gap: 2,
                    p: 2,
                    borderBottom: "1px solid #eef1ef",
                  }}
                >
                  <Box>
                    <Typography
                      sx={{
                        fontWeight: 700,
                      }}
                    >
                      Version {p.version} {p.parent_id ? "· Nachtrag" : ""}
                    </Typography>
                    <Typography
                      variant="body2"
                      sx={{
                        color: "text.secondary",
                      }}
                    >
                      {p.periods.join(", ")} · {bytes(p.size)} ·{" "}
                      {new Date(p.created_at).toLocaleString("de-AT")}
                    </Typography>
                  </Box>
                  <Button onClick={() => setSelectedId(p.id)}>Ansehen</Button>
                </Stack>
              ))}
            </Paper>
          )}
        </Box>
        <Box>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Versandhistorie
          </Typography>
          {!dispatches.data?.length ? (
            <Empty
              title="Noch nichts versendet"
              text="Der Versand erfolgt nur auf ausdrücklichen Auftrag an die im Snapshot gespeicherten Empfänger."
            />
          ) : (
            <Stack
              sx={{
                gap: 2,
              }}
            >
              {dispatches.data.map((d) => (
                <Paper key={d.id} sx={{ p: 2 }}>
                  <Stack
                    direction="row"
                    sx={{
                      justifyContent: "space-between",
                    }}
                  >
                    <Status status={d.status} />
                    <Typography variant="caption">
                      {new Date(d.created_at).toLocaleString("de-AT")}
                    </Typography>
                  </Stack>
                  <Typography sx={{ mt: 1 }}>
                    {d.recipients.join(", ")}
                  </Typography>
                  {d.resend_of && (
                    <Typography variant="caption">
                      Ausdrücklicher Neuversand von {d.resend_of}
                    </Typography>
                  )}
                  {d.attempts.map((a) => (
                    <Box key={a.id} sx={{ mt: 1 }}>
                      <Typography variant="body2">
                        Teil {a.part}: {a.detail || a.status}
                      </Typography>
                      <Typography
                        variant="caption"
                        sx={{ overflowWrap: "anywhere" }}
                      >
                        {a.message_id}
                      </Typography>
                    </Box>
                  ))}
                  {!["queued", "sending"].includes(d.status) && (
                    <Button
                      color={d.status === "unknown" ? "warning" : "primary"}
                      sx={{ mt: 1 }}
                      onClick={() =>
                        setConfirmation({
                          packageId: d.package_id,
                          resendOf: d.id,
                        })
                      }
                    >
                      Ausdrücklich erneut senden
                    </Button>
                  )}
                </Paper>
              ))}
            </Stack>
          )}
        </Box>
      </Box>
      <Paper sx={{ p: 3, mt: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Hintergrund- & Agentenaufträge
        </Typography>
        {jobs.data?.slice(0, 20).map((j) => (
          <Stack
            key={j.id}
            direction={{ xs: "column", sm: "row" }}
            sx={{
              gap: 2,
              py: 1,
              borderTop: "1px solid #eef1ef",
            }}
          >
            <Typography sx={{ minWidth: 90 }}>{j.kind}</Typography>
            <Status status={j.status} />
            <Typography
              variant="body2"
              sx={{ flex: 1, overflowWrap: "anywhere" }}
            >
              {j.error || j.id}
            </Typography>
            {["failed", "interrupted"].includes(j.status) &&
              ["imap", "package"].includes(j.kind) && (
                <Button size="small" onClick={() => resume.mutate(j.id)}>
                  Fortsetzen
                </Button>
              )}
          </Stack>
        ))}
        {!jobs.data?.length && (
          <Typography
            sx={{
              color: "text.secondary",
            }}
          >
            Noch keine Aufträge.
          </Typography>
        )}
      </Paper>
      <Dialog open={!!confirmation} onClose={() => setConfirmation(null)}>
        <DialogTitle>
          {confirmation?.resendOf
            ? "Ausdrücklichen Neuversand bestätigen"
            : "Paket per SMTP versenden"}
        </DialogTitle>
        <DialogContent>
          <Typography>
            Versendet wird der gespeicherte, unveränderliche Snapshot an seine
            hinterlegten Empfänger.
          </Typography>
          {confirmation?.resendOf && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              Dies ist ein neuer, protokollierter Versandversuch. Bei
              unbekanntem Ausgang zuerst im Mailserver prüfen: Der vorherige
              Versand könnte bereits angenommen worden sein.
            </Alert>
          )}
          <Typography variant="body2" sx={{ mt: 2 }}>
            „SMTP angenommen“ bedeutet nicht bestätigte Zustellung. Große ZIPs
            werden in nummerierte Binärteile mit Gesamtinhaltsliste aufgeteilt.
          </Typography>
          <ErrorAlert error={send.error} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmation(null)}>Abbrechen</Button>
          <Button
            variant="contained"
            disabled={send.isPending}
            onClick={() => confirmation && send.mutate(confirmation)}
          >
            Jetzt verbindlich senden
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
