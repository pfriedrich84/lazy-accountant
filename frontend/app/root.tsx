import type { ReactNode } from "react";
import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  useRouteError,
  isRouteErrorResponse,
} from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Alert,
  Box,
  CssBaseline,
  ThemeProvider,
  Typography,
  createTheme,
} from "@mui/material";
import "./style.css";

const client = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 15_000 } },
});
const theme = createTheme({
  palette: {
    primary: { main: "#175b50" },
    secondary: { main: "#bf743b" },
    background: { default: "#f5f7f7", paper: "#fff" },
  },
  typography: {
    fontFamily: "Inter, system-ui, -apple-system, sans-serif",
    h4: { fontWeight: 700, letterSpacing: "-.04em" },
    h5: { fontWeight: 650 },
  },
  shape: { borderRadius: 12 },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { textTransform: "none", fontWeight: 650 } },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { border: "1px solid #e1e7e5" } },
    },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiTableCell: {
      styleOverrides: {
        head: { fontWeight: 700, background: "#f8faf9", whiteSpace: "nowrap" },
      },
    },
  },
});

export function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="de">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Lazy Accountant</title>
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function Root() {
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Outlet />
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export function ErrorBoundary() {
  const error = useRouteError();
  return (
    <Box sx={{ p: 4 }}>
      <Typography variant="h4">Etwas ist schiefgegangen</Typography>
      <Alert severity="error">
        {isRouteErrorResponse(error)
          ? `${error.status} ${error.statusText}`
          : error instanceof Error
            ? error.message
            : "Unbekannter Fehler"}
      </Alert>
      <a href="/">Zur Übersicht</a>
    </Box>
  );
}
