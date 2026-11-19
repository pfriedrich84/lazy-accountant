import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, Outlet, useOutletContext } from "react-router";
import {
  Alert,
  AppBar,
  Box,
  Button,
  Divider,
  Drawer,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Toolbar,
  Typography,
} from "@mui/material";
import { api, type Company, post } from "../api";
import { ErrorAlert, Loading } from "../components";

export interface AppContext {
  companyId: number | null;
  company: Company | undefined;
  companies: Company[];
  period: string;
  setCompanyId: (id: number) => void;
  setPeriod: (period: string) => void;
}
export function useApp() {
  return useOutletContext<AppContext>();
}
const navigation = [
  ["/", "Übersicht", "◫"],
  ["/documents", "Dokumenteingang", "↓"],
  ["/months", "Monatsablage", "▤"],
  ["/payments", "Zahlungsstand", "€"],
  ["/packages", "Übergabe & Versand", "↗"],
  ["/settings", "Einstellungen", "⚙"],
];

function Login() {
  const query = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        p: 3,
        background: "linear-gradient(135deg,#e3efe9,#f7f8f5)",
      }}
    >
      <Paper sx={{ p: 5, maxWidth: 430, width: "100%" }}>
        <Typography
          color="primary"
          sx={{
            fontWeight: 800,
            mb: 3,
          }}
        >
          LAZY ACCOUNTANT
        </Typography>
        <Typography variant="h4" component="h1">
          Alles an einem Ort.
        </Typography>
        <Typography
          sx={{
            color: "text.secondary",
            my: 2,
          }}
        >
          Belege sammeln, prüfen und vollständig an die Steuerberatung
          übergeben.
        </Typography>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(undefined);
            try {
              await post("auth/login/", { username, password });
              await query.invalidateQueries();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Stack spacing={2}>
            <TextField
              label="Benutzername"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <TextField
              label="Passwort"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Button
              type="submit"
              variant="contained"
              size="large"
              disabled={busy}
            >
              {busy ? "Anmeldung läuft …" : "Anmelden"}
            </Button>
          </Stack>
          <ErrorAlert error={error} />
        </form>
        <Typography
          variant="caption"
          sx={{
            color: "text.secondary",
            display: "block",
            mt: 3,
          }}
        >
          Privater HTTP-Betrieb im internen Netz. Nicht öffentlich
          bereitstellen.
        </Typography>
      </Paper>
    </Box>
  );
}

export default function Shell() {
  const cache = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => api<{ username: string }>("auth/session/"),
    staleTime: Infinity,
  });
  const companies = useQuery({
    queryKey: ["companies"],
    queryFn: () => api<Company[]>("companies/"),
    enabled: !!session.data,
  });
  const [chosen, setChosen] = useState<number | null>(() =>
    typeof localStorage === "undefined"
      ? null
      : Number(localStorage.getItem("company")) || null,
  );
  const [period, setPeriodState] = useState(() =>
    typeof localStorage === "undefined"
      ? new Date().toISOString().slice(0, 7)
      : localStorage.getItem("period") || new Date().toISOString().slice(0, 7),
  );
  const [mobile, setMobile] = useState(false);
  if (session.isPending) return <Loading />;
  if (!session.data) return <Login />;
  const companyId = companies.data?.some((c) => c.id === chosen)
    ? chosen
    : companies.data?.[0]?.id || null;
  const setCompanyId = (id: number) => {
    localStorage.setItem("company", String(id));
    setChosen(id);
  };
  const setPeriod = (value: string) => {
    if (value) {
      localStorage.setItem("period", value);
      setPeriodState(value);
    }
  };
  const company = companies.data?.find((c) => c.id === companyId);
  const sidebar = (
    <Box
      sx={{ p: 2, height: "100%", display: "flex", flexDirection: "column" }}
    >
      <Typography
        color="primary"
        sx={{
          fontWeight: 850,
          letterSpacing: "-.03em",
          p: 2,
          mb: 2,
        }}
      >
        lazy accountant<span style={{ color: "#bf743b" }}>.</span>
      </Typography>
      <List>
        {navigation.map(([to, title, symbol]) => (
          <ListItemButton
            component={NavLink}
            to={to}
            end={to === "/"}
            key={to}
            onClick={() => setMobile(false)}
            sx={{
              borderRadius: 2,
              my: 0.5,
              gap: 1.5,
              "&.active": {
                bgcolor: "#e5f0ec",
                color: "primary.main",
                fontWeight: 700,
              },
            }}
          >
            <span aria-hidden>{symbol}</span>
            <ListItemText primary={title} />
          </ListItemButton>
        ))}
      </List>
      <Box sx={{ mt: "auto", p: 2 }}>
        <Divider sx={{ mb: 2 }} />
        <Typography
          variant="caption"
          sx={{
            color: "text.secondary",
          }}
        >
          Originale bleiben Originale.
          <br />
          Keine interne KI-Anbindung nötig.
        </Typography>
      </Box>
    </Box>
  );
  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Box
        component="nav"
        sx={{ width: { md: 240 }, flexShrink: { md: 0 } }}
        aria-label="Hauptnavigation"
      >
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: "none", md: "block" },
            "& .MuiDrawer-paper": {
              width: 240,
              border: 0,
              borderRight: "1px solid #e1e7e5",
            },
          }}
        >
          {sidebar}
        </Drawer>
        <Drawer
          open={mobile}
          onClose={() => setMobile(false)}
          sx={{ display: { md: "none" }, "& .MuiDrawer-paper": { width: 260 } }}
        >
          {sidebar}
        </Drawer>
      </Box>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <AppBar
          position="sticky"
          color="inherit"
          elevation={0}
          sx={{ border: 0, borderBottom: "1px solid #e1e7e5" }}
        >
          <Toolbar sx={{ gap: 2, py: 1, flexWrap: "wrap" }}>
            <IconButton
              onClick={() => setMobile(true)}
              aria-label="Menü öffnen"
              sx={{ display: { md: "none" } }}
            >
              ☰
            </IconButton>
            <FormControl size="small" sx={{ minWidth: { xs: 150, sm: 240 } }}>
              <InputLabel id="active-company-label">Firma</InputLabel>
              <Select
                labelId="active-company-label"
                id="active-company"
                label="Firma"
                value={companyId || ""}
                onChange={(e) => setCompanyId(Number(e.target.value))}
              >
                {companies.data?.map((c) => (
                  <MenuItem value={c.id} key={c.id}>
                    {c.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Übergabemonat"
              type="month"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
              sx={{ width: 175 }}
            />
            <Box sx={{ flex: 1 }} />
            <Typography
              variant="body2"
              sx={{
                color: "text.secondary",
                display: { xs: "none", sm: "block" },
              }}
            >
              {session.data.username}
            </Typography>
            <Button
              size="small"
              onClick={async () => {
                await post("auth/logout/", {});
                cache.clear();
                location.href = "/";
              }}
            >
              Abmelden
            </Button>
          </Toolbar>
        </AppBar>
        <Box
          component="main"
          sx={{ p: { xs: 2, sm: 3, lg: 4 }, maxWidth: 1700, mx: "auto" }}
        >
          <ErrorAlert error={companies.error} />
          {!companies.isPending && !companyId && (
            <Alert severity="info" sx={{ mb: 3 }}>
              Noch keine Firma vorhanden. Unter{" "}
              <Link to="/settings">Einstellungen</Link> die erste Firma anlegen.
            </Alert>
          )}
          <Outlet
            context={
              {
                companyId,
                company,
                companies: companies.data || [],
                period,
                setCompanyId,
                setPeriod,
              } satisfies AppContext
            }
          />
        </Box>
      </Box>
    </Box>
  );
}
