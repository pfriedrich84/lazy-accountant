import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Alert, Box, Button, Paper, Stack, Typography } from "@mui/material";
import { api } from "../api";
import { Empty, ErrorAlert, Heading, Loading, Status } from "../components";
import {
  documentDate,
  documentTitle,
  formatDocumentDate,
  mergeMonthPages,
  type MonthPage,
} from "../monthly-archive";
import { useApp } from "./shell";

export default function Months() {
  const { companyId, period } = useApp();
  const [openOnly, setOpenOnly] = useState(false);
  const query = useInfiniteQuery({
    queryKey: ["folders", companyId, period, openOnly],
    initialPageParam: "",
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ period });
      if (pageParam) params.set("cursor", pageParam);
      if (openOnly) params.set("status", "open");
      return api<MonthPage>(`folders/${companyId}/?${params}`);
    },
    getNextPageParam: (page) => page.next_cursor || undefined,
    enabled: !!companyId,
  });
  const pages = query.data?.pages || [];
  const summary = pages[0]?.summary;
  const folders = mergeMonthPages(pages);
  const loaded = folders.reduce(
    (count, folder) => count + folder.files.length,
    0,
  );
  const total = pages[0]?.total || 0;

  return (
    <>
      <Heading
        title="Monatsablage"
        subtitle="Dokumente des gewählten Übergabemonats finden und offene Prüfungen im Blick behalten."
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
          text="Wählen Sie oben eine Firma aus oder legen Sie eine Firma in den Einstellungen an."
          to="/settings"
          action="Einstellungen öffnen"
        />
      ) : query.isPending ? (
        <Loading />
      ) : (
        <>
          {summary && (
            <Box sx={{ mb: 3 }}>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                sx={{
                  gap: 1.5,
                  alignItems: { sm: "center" },
                  justifyContent: "space-between",
                }}
              >
                <Typography role="status" sx={{ fontWeight: 650 }}>
                  {summary.total}{" "}
                  {summary.total === 1 ? "Dokument" : "Dokumente"}
                  {" · "}
                  {summary.ready} geprüft{" · "}
                  {summary.open} zu prüfen
                </Typography>
                <Stack direction="row" sx={{ gap: 1, flexWrap: "wrap" }}>
                  <Button
                    variant={openOnly ? "outlined" : "contained"}
                    aria-pressed={!openOnly}
                    onClick={() => setOpenOnly(false)}
                  >
                    Alle Dokumente
                  </Button>
                  <Button
                    variant={openOnly ? "contained" : "outlined"}
                    aria-pressed={openOnly}
                    onClick={() => setOpenOnly(true)}
                  >
                    Zu prüfen ({summary.open})
                  </Button>
                </Stack>
              </Stack>
              <Typography
                variant="body2"
                sx={{ color: "text.secondary", mt: 1 }}
              >
                Prüfstand der zugeordneten Dokumente. Vollständigkeit und
                Übergabe prüfen Sie in der Paketvorschau.
              </Typography>
            </Box>
          )}
          {openOnly && total === 0 && summary && (
            <Alert severity="success" sx={{ mb: 3 }}>
              {summary.total
                ? "Alle zugeordneten Dokumente sind geprüft."
                : "Für diesen Monat sind noch keine Dokumente zugeordnet."}
            </Alert>
          )}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "minmax(0, 1fr)",
                xl: "repeat(2, minmax(0, 1fr))",
              },
              gap: 3,
            }}
          >
            {folders
              .filter((folder) => !openOnly || folder.open > 0)
              .map((folder) => {
                const matching = openOnly ? folder.open : folder.total;
                return (
                  <Paper
                    key={folder.name}
                    component="section"
                    sx={{ p: { xs: 2, sm: 3 }, minWidth: 0 }}
                  >
                    <Stack
                      direction="row"
                      sx={{
                        gap: 2,
                        flexWrap: "wrap",
                        alignItems: "baseline",
                        justifyContent: "space-between",
                        mb: 1,
                      }}
                    >
                      <Typography variant="h5" component="h2">
                        {folder.name}
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{ color: "text.secondary" }}
                      >
                        {folder.total}{" "}
                        {folder.total === 1 ? "Dokument" : "Dokumente"}
                        {folder.open
                          ? ` · ${folder.open} zu prüfen`
                          : folder.total
                            ? " · alle geprüft"
                            : ""}
                      </Typography>
                    </Stack>
                    {folder.path ? (
                      <Box
                        component="details"
                        sx={{ mb: 1.5, color: "text.secondary" }}
                      >
                        <Box
                          component="summary"
                          sx={{
                            cursor: "pointer",
                            py: 0.5,
                            fontSize: "0.875rem",
                          }}
                        >
                          Ablagepfad anzeigen
                        </Box>
                        <Typography className="file-path" sx={{ mt: 0.5 }}>
                          /{folder.path}
                        </Typography>
                      </Box>
                    ) : (
                      <Typography
                        variant="body2"
                        sx={{ color: "text.secondary", mb: 1.5 }}
                      >
                        Diese Dokumente benötigen noch eine Dokumentart für die
                        Ablage.
                      </Typography>
                    )}
                    <Box component="ul" sx={{ m: 0, p: 0, listStyle: "none" }}>
                      {folder.files.map((doc) => {
                        const date = documentDate(doc);
                        const reference =
                          doc.metadata.isin || doc.metadata.number;
                        return (
                          <Box
                            component="li"
                            key={doc.id}
                            sx={{
                              py: 1.5,
                              borderTop: 1,
                              borderColor: "divider",
                            }}
                          >
                            <Stack
                              direction={{ xs: "column", sm: "row" }}
                              sx={{
                                gap: 1,
                                alignItems: {
                                  xs: "flex-start",
                                  sm: "baseline",
                                },
                                justifyContent: "space-between",
                              }}
                            >
                              <Box
                                sx={{
                                  minWidth: 0,
                                  width: { xs: "100%", sm: "auto" },
                                }}
                              >
                                <Link
                                  to={`/documents/${doc.id}`}
                                  title={doc.effective_name}
                                  style={{
                                    display: "inline-block",
                                    paddingBlock: 4,
                                    fontWeight: 650,
                                    overflowWrap: "anywhere",
                                    textUnderlineOffset: "0.2em",
                                  }}
                                >
                                  {documentTitle(doc)}
                                </Link>
                                {(date || reference) && (
                                  <Typography
                                    variant="body2"
                                    sx={{
                                      color: "text.secondary",
                                      overflowWrap: "anywhere",
                                      mt: 0.25,
                                    }}
                                  >
                                    {date && (
                                      <time dateTime={date}>
                                        {formatDocumentDate(date)}
                                      </time>
                                    )}
                                    {date && reference ? " · " : ""}
                                    {reference &&
                                      `${doc.metadata.isin ? "ISIN" : "Nr."} ${reference}`}
                                  </Typography>
                                )}
                              </Box>
                              <Box sx={{ flexShrink: 0 }}>
                                <Status status={doc.status} />
                              </Box>
                            </Stack>
                          </Box>
                        );
                      })}
                    </Box>
                    {folder.files.length < matching && (
                      <Typography
                        variant="body2"
                        sx={{ color: "text.secondary", mt: 1 }}
                      >
                        {folder.files.length} von {matching}{" "}
                        {openOnly ? "offenen Dokumenten" : "Dokumenten"}{" "}
                        angezeigt. Weitere Dokumente unten laden.
                      </Typography>
                    )}
                    {matching === 0 && (
                      <Typography
                        variant="body2"
                        sx={{ color: "text.secondary", py: 2 }}
                      >
                        Noch keine Dokumente. Der Ordner bleibt im vollständigen
                        Export erhalten.
                      </Typography>
                    )}
                  </Paper>
                );
              })}
          </Box>
          {summary && total > 0 && (
            <Stack sx={{ mt: 3, gap: 1, alignItems: "center" }}>
              <Typography
                variant="body2"
                role="status"
                sx={{ color: "text.secondary" }}
              >
                {loaded} von {total}{" "}
                {openOnly ? "offenen Dokumenten" : "Dokumenten"} angezeigt
              </Typography>
              {query.hasNextPage && (
                <Button
                  variant="outlined"
                  disabled={query.isFetchingNextPage}
                  onClick={() => void query.fetchNextPage()}
                >
                  {query.isFetchingNextPage
                    ? "Weitere Dokumente werden geladen …"
                    : "Weitere Dokumente laden"}
                </Button>
              )}
            </Stack>
          )}
        </>
      )}
    </>
  );
}
