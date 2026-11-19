import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Alert, Box, Button, Paper, Stack, Typography } from "@mui/material";
import { api, type Document, kinds } from "../api";
import { Empty, ErrorAlert, Heading, Loading, Status } from "../components";
import { useApp } from "./shell";

export default function Months() {
  const { companyId, period } = useApp();
  const query = useQuery({
    queryKey: ["folders", companyId, period],
    queryFn: () =>
      api<{
        folders: { name: string; path: string; files: Document[] }[];
        next_cursor: string | null;
      }>(`folders/${companyId}/?period=${period}`),
    enabled: !!companyId,
  });
  return (
    <>
      <Heading
        title="Monatsablage"
        subtitle="Diese Ordner existieren tatsächlich im persistenten Ablagestamm. Der Übergabemonat bestimmt den Pfad – nicht das Importdatum."
        actions={
          <Button component={Link} to="/packages" variant="contained">
            Paketvorschau öffnen
          </Button>
        }
      />
      <ErrorAlert error={query.error} />
      {!companyId ? (
        <Empty
          title="Keine Firma ausgewählt"
          text="Zuerst eine Firma in den Einstellungen anlegen."
        />
      ) : query.isPending ? (
        <Loading />
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", xl: "1fr 1fr" },
            gap: 3,
          }}
        >
          {query.data?.folders.map((folder) => (
            <Paper key={folder.name} sx={{ p: 3 }}>
              <Stack
                direction="row"
                sx={{
                  justifyContent: "space-between",
                  mb: 1,
                }}
              >
                <Typography variant="h5">▤ {folder.name}</Typography>
                <Typography
                  sx={{
                    color: "text.secondary",
                  }}
                >
                  {folder.files.length} Dateien
                </Typography>
              </Stack>
              <Typography
                className="file-path"
                sx={{
                  color: "text.secondary",
                  mb: 2,
                }}
              >
                /{folder.path}
              </Typography>
              {folder.files.length ? (
                folder.files.map((d) => (
                  <Box
                    key={d.id}
                    sx={{ py: 1.5, borderTop: "1px solid #eef1ef" }}
                  >
                    <Stack
                      direction="row"
                      sx={{
                        gap: 1,
                        justifyContent: "space-between",
                      }}
                    >
                      <Link
                        to={`/documents/${d.id}`}
                        style={{ overflowWrap: "anywhere" }}
                      >
                        {d.effective_name}
                        <Typography variant="caption" sx={{ display: "block" }}>
                          Original: {d.original_name}
                        </Typography>
                      </Link>
                      <Status status={d.status} />
                    </Stack>
                    <Typography
                      variant="caption"
                      sx={{
                        color: "text.secondary",
                      }}
                    >
                      {kinds[d.kind]} ·{" "}
                      {d.metadata.number ||
                        d.metadata.period_end ||
                        "Ohne Belegnummer"}
                    </Typography>
                  </Box>
                ))
              ) : (
                <Typography
                  sx={{
                    color: "text.secondary",
                    py: 3,
                  }}
                >
                  Dieser Ordner ist leer und bleibt auch im vollständigen Export
                  erhalten.
                </Typography>
              )}
            </Paper>
          ))}
        </Box>
      )}
      {query.data?.next_cursor && (
        <Alert severity="info" sx={{ mt: 2 }}>
          Hier werden die ersten 100 Dokumente gezeigt. Alle Dokumente finden
          Sie in der paginierten Dokumentliste.
        </Alert>
      )}
    </>
  );
}
