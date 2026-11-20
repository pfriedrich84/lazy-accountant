import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Box, Button, Paper, Stack, Typography } from "@mui/material";
import { api, type Job, type Page, type Package } from "../api";
import { Empty, ErrorAlert, Heading, Status } from "../components";
import { useApp } from "./shell";

export default function Home() {
  const { companyId, company, period } = useApp();
  const docs = useQuery({
    queryKey: ["documents", companyId, period],
    queryFn: () =>
      api<Page>(
        `documents/?company_id=${companyId}&period=${period}&limit=100`,
      ),
    enabled: !!companyId,
  });
  const open = useQuery({
    queryKey: ["open-count", companyId],
    queryFn: () =>
      api<Page>(`documents/?company_id=${companyId}&status=open&limit=1`),
    enabled: !!companyId,
  });
  const packages = useQuery({
    queryKey: ["packages", companyId],
    queryFn: () => api<Package[]>(`packages/?company_id=${companyId}`),
    enabled: !!companyId,
  });
  const jobs = useQuery({
    queryKey: ["jobs", companyId],
    queryFn: () => api<Job[]>(`jobs/?company_id=${companyId}`),
    enabled: !!companyId,
    refetchInterval: 10_000,
  });
  return (
    <>
      <Heading
        title="Bereit für den Monatsabschluss?"
        subtitle={
          company
            ? `${company.name} · ${period} · Ihre Unterlagen, übersichtlich und nachvollziehbar.`
            : "Legen Sie eine Firma an und sammeln Sie die ersten Belege."
        }
        actions={
          <Button component={Link} to="/documents" variant="contained">
            + Dokumente hochladen
          </Button>
        }
      />
      <ErrorAlert
        error={docs.error || open.error || packages.error || jobs.error}
      />
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr 1fr", lg: "repeat(4,1fr)" },
          gap: 2,
          mb: 3,
        }}
      >
        {[
          ["Dokumente im Monat", docs.data?.total || 0, "/months"],
          ["Noch zu prüfen", open.data?.total || 0, "/documents?status=open"],
          ["Paketversionen", packages.data?.length || 0, "/packages"],
          [
            "Laufende Aufträge",
            jobs.data?.filter((j) => ["queued", "running"].includes(j.status))
              .length || 0,
            "/packages",
          ],
        ].map(([title, count, to]) => (
          <Paper
            key={title}
            component={Link}
            to={String(to)}
            sx={{
              p: 3,
              textDecoration: "none",
              color: "inherit",
              "&:hover": { borderColor: "primary.main" },
            }}
          >
            <Typography
              variant="body2"
              sx={{
                color: "text.secondary",
              }}
            >
              {title}
            </Typography>
            <Typography
              variant="h3"
              sx={{
                fontWeight: 700,
                mt: 1,
              }}
            >
              {count}
            </Typography>
          </Paper>
        ))}
      </Box>
      <Paper
        sx={{
          p: { xs: 3, md: 4 },
          mb: 3,
          background: "linear-gradient(110deg,#175b50,#287b69)",
          color: "white",
        }}
      >
        <Typography variant="overline" sx={{ opacity: 0.8 }}>
          VOM EINGANG BIS ZUR ÜBERGABE
        </Typography>
        <Typography variant="h5" sx={{ mt: 1, maxWidth: 700 }}>
          Sammeln. Prüfen. Sicher übergeben.
        </Typography>
        <Typography sx={{ mt: 1, mb: 3, maxWidth: 750, opacity: 0.85 }}>
          Rechnungen, Kontoauszüge und Wertpapierunterlagen bleiben unverändert
          erhalten. Ihr Agent unterstützt beim Auslesen – Sie behalten die
          Kontrolle über offene Fragen und Versand.
        </Typography>
        <Stack
          direction="row"
          sx={{
            gap: 2,
            flexWrap: "wrap",
          }}
        >
          <Button
            component={Link}
            to="/documents"
            variant="contained"
            color="inherit"
            sx={{ color: "primary.main" }}
          >
            Zum Dokumenteingang
          </Button>
          <Button
            component={Link}
            to="/packages"
            variant="outlined"
            sx={{ color: "white", borderColor: "#ffffff70" }}
          >
            Übergabe vorbereiten
          </Button>
        </Stack>
      </Paper>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Zuletzt eingegangen
      </Typography>
      {!docs.data?.results.length ? (
        <Empty
          title="Der Monat ist noch leer"
          text="PDFs, Bilder oder CAMT-Dateien hochladen oder den IMAP-Abruf im Dokumenteingang starten."
          to="/documents"
          action="Dokumente importieren"
        />
      ) : (
        <Paper>
          {docs.data.results
            .slice(-6)
            .reverse()
            .map((d) => (
              <Stack
                key={d.id}
                direction={{ xs: "column", sm: "row" }}
                sx={{
                  gap: 1,
                  justifyContent: "space-between",
                  px: 3,
                  py: 2,
                  borderBottom: "1px solid #eef1ef",
                }}
              >
                <Box>
                  <Link to={`/documents/${d.id}`} style={{ fontWeight: 650 }}>
                    {d.effective_name}
                  </Link>
                  <Typography
                    variant="caption"
                    sx={{
                      display: "block",
                      color: "text.secondary",
                    }}
                  >
                    {d.metadata.issuer || "Aussteller noch ungeklärt"} ·{" "}
                    {d.metadata.number || "Keine Belegnummer"}
                  </Typography>
                </Box>
                <Status status={d.status} />
              </Stack>
            ))}
        </Paper>
      )}
    </>
  );
}
