import { useRef, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import {
  Alert,
  Box,
  Button,
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
  type Job,
  type Page,
  idempotencyKey,
  kinds,
  post,
} from "../api";
import { Empty, ErrorAlert, Heading, Loading, Status } from "../components";
import { useApp } from "./shell";

export default function Documents() {
  const { companyId, period } = useApp();
  const cache = useQueryClient();
  const [params] = useSearchParams();
  const [status, setStatus] = useState(params.get("status") || "");
  const [kind, setKind] = useState("");
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("company");
  const [monthOnly, setMonthOnly] = useState(false);
  const [uploadInfo, setUploadInfo] = useState("");
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const filters = new URLSearchParams({
    limit: "40",
    ...(scope === "inbox"
      ? { company_id: "inbox" }
      : scope === "all"
        ? {}
        : companyId
          ? { company_id: String(companyId) }
          : {}),
    ...(status ? { status } : {}),
    ...(kind ? { kind } : {}),
    ...(search ? { search } : {}),
    ...(monthOnly ? { period } : {}),
  });
  const list = useInfiniteQuery({
    queryKey: ["document-list", filters.toString()],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page>(`documents/?${filters}&cursor=${pageParam}`),
    getNextPageParam: (p) => p.next_cursor || undefined,
  });
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      setUploadInfo("");
      const body = new FormData();
      files.forEach((f) => body.append("files", f));
      if (scope !== "inbox" && companyId)
        body.append("company_id", String(companyId));
      return api<{ results: { duplicate: boolean }[] }>("documents/", {
        method: "POST",
        body,
        headers: { "Idempotency-Key": idempotencyKey() },
      });
    },
    onSuccess: async (result) => {
      setUploadInfo(
        `${result.results.length} Datei(en) übernommen, davon ${result.results.filter((r) => r.duplicate).length} bereits vorhanden. Neue Dokumente sind noch nicht klassifiziert.`,
      );
      await cache.invalidateQueries();
    },
  });
  const imap = useMutation({
    mutationFn: () =>
      post<Job>("jobs/", {
        company_id: companyId,
        kind: "imap",
        idempotency_key: idempotencyKey(),
      }),
    onSuccess: () => cache.invalidateQueries(),
  });
  const rows = list.data?.pages.flatMap((p) => p.results) || [];
  return (
    <>
      <Heading
        title="Dokumenteingang"
        subtitle="Originale hochladen, vom Agenten auslesen lassen und offene Zuordnungen prüfen."
        actions={
          <Button
            variant="outlined"
            disabled={!companyId || imap.isPending}
            onClick={() => imap.mutate()}
          >
            IMAP jetzt abrufen
          </Button>
        }
      />
      <Paper
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (!upload.isPending)
            upload.mutate(Array.from(e.dataTransfer.files));
        }}
        sx={{
          p: 3,
          mb: 3,
          textAlign: "center",
          border: "2px dashed",
          borderColor: drag ? "primary.main" : "#cadad3",
          bgcolor: drag ? "#e5f0ec" : "#fafcfb",
        }}
      >
        <Typography variant="h6">Belege hier ablegen</Typography>
        <Typography
          variant="body2"
          sx={{
            color: "text.secondary",
            mb: 2,
          }}
        >
          PDF, JPG, PNG und CAMT-XML · bis zu 30 Dateien · standardmäßig 25 MiB
          pro Datei
        </Typography>
        <input
          ref={input}
          type="file"
          multiple
          accept=".pdf,.jpg,.jpeg,.png,.xml"
          hidden
          aria-label="Dokumentdateien"
          onChange={(e) => {
            if (e.target.files) upload.mutate(Array.from(e.target.files));
            e.target.value = "";
          }}
        />
        <Button
          onClick={() => input.current?.click()}
          variant="contained"
          disabled={upload.isPending}
        >
          {upload.isPending
            ? "Dateien werden übernommen …"
            : "Dateien auswählen"}
        </Button>
        <Typography
          variant="caption"
          sx={{
            display: "block",
            color: "text.secondary",
            mt: 1,
          }}
        >
          {scope === "inbox" || !companyId
            ? "Ohne Firmenzuordnung in den Eingang importieren."
            : "Import in die oben gewählte Firma. Dokumentart und Übergabemonat bleiben zunächst offen."}
        </Typography>
      </Paper>
      <ErrorAlert error={list.error || upload.error || imap.error} />
      {uploadInfo && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {uploadInfo}
        </Alert>
      )}
      {imap.data && (
        <Alert severity="info" sx={{ mb: 2 }}>
          IMAP-Auftrag {imap.data.id} gestartet. Status unter Übergabe &
          Versand.
        </Alert>
      )}
      <Stack
        direction={{ xs: "column", sm: "row" }}
        sx={{
          flexWrap: "wrap",
          gap: 2,
          mb: 2,
        }}
      >
        <TextField
          label="Suche"
          placeholder="Datei, Geschäftspartner, Nummer …"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ flex: 1, minWidth: 200 }}
        />
        <TextField
          select
          label="Eingang"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="company">Gewählte Firma</MenuItem>
          <MenuItem value="inbox">Firma ungeklärt</MenuItem>
          <MenuItem value="all">Alle berechtigten Firmen</MenuItem>
        </TextField>
        <TextField
          select
          label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          sx={{ minWidth: 150 }}
        >
          <MenuItem value="">Alle</MenuItem>
          <MenuItem value="open">Offen</MenuItem>
          <MenuItem value="new">Neu</MenuItem>
          <MenuItem value="review">Zu prüfen</MenuItem>
          <MenuItem value="ready">Geprüft</MenuItem>
        </TextField>
        <TextField
          select
          label="Dokumentart"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          sx={{ minWidth: 190 }}
        >
          <MenuItem value="">Alle Arten</MenuItem>
          {Object.entries(kinds).map(([k, v]) => (
            <MenuItem key={k} value={k}>
              {v}
            </MenuItem>
          ))}
        </TextField>
        <Button
          variant={monthOnly ? "contained" : "outlined"}
          onClick={() => setMonthOnly(!monthOnly)}
        >
          {monthOnly ? `Nur ${period}` : "Alle Monate"}
        </Button>
      </Stack>
      {list.isPending ? (
        <Loading />
      ) : !rows.length ? (
        <Empty
          title="Keine Dokumente in dieser Ansicht"
          text="Neue Dateien hochladen oder die Filter anpassen. Unzugeordnete Dateien finden Sie unter „Firma ungeklärt“."
        />
      ) : (
        <>
          <Typography
            variant="body2"
            sx={{
              color: "text.secondary",
              mb: 1,
            }}
          >
            {list.data?.pages[0].total} Dokumente gefunden
          </Typography>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Dokument / Geschäftspartner</TableCell>
                  <TableCell>Art</TableCell>
                  <TableCell>Monat</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Umfang</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((d) => (
                  <TableRow hover key={d.id}>
                    <TableCell>
                      <Link
                        to={`/documents/${d.id}`}
                        style={{ fontWeight: 650 }}
                      >
                        {d.original_name}
                      </Link>
                      <Typography
                        variant="caption"
                        sx={{
                          display: "block",
                          color: "text.secondary",
                        }}
                      >
                        {d.metadata.issuer || "Aussteller ungeklärt"}
                        {d.metadata.number ? ` · ${d.metadata.number}` : ""}
                      </Typography>
                    </TableCell>
                    <TableCell>{kinds[d.kind] || "Ungeklärt"}</TableCell>
                    <TableCell>{d.period || "—"}</TableCell>
                    <TableCell>
                      <Status status={d.status} />
                    </TableCell>
                    <TableCell align="right">{bytes(d.size)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          {list.hasNextPage && (
            <Box sx={{ mt: 2, textAlign: "center" }}>
              <Button
                onClick={() => list.fetchNextPage()}
                disabled={list.isFetchingNextPage}
              >
                Weitere Dokumente laden
              </Button>
            </Box>
          )}
        </>
      )}
    </>
  );
}
