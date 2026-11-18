import type { ReactNode } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { Link } from "react-router";
import { APIError, errorMessage, statusLabels } from "./api";

export function Status({ status }: { status: string }) {
  return (
    <Chip
      size="small"
      label={statusLabels[status] || status}
      color={
        ["ready", "accepted", "done"].includes(status)
          ? "success"
          : ["failed", "unknown", "partial"].includes(status)
            ? "error"
            : ["new", "review", "interrupted"].includes(status)
              ? "warning"
              : "default"
      }
      variant="outlined"
    />
  );
}
export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert severity="error" sx={{ my: 2 }}>
      <strong>{errorMessage(error)}</strong>
      {error instanceof APIError && error.details != null && (
        <Box
          component="pre"
          sx={{
            whiteSpace: "pre-wrap",
            overflowWrap: "anywhere",
            fontSize: ".8rem",
          }}
        >
          {JSON.stringify(error.details, null, 2)}
        </Box>
      )}
    </Alert>
  );
}
export function Loading() {
  return (
    <Stack direction="row" spacing={2} sx={{ p: 4 }}>
      <CircularProgress size={22} />
      <Typography>Wird geladen …</Typography>
    </Stack>
  );
}
export function Heading({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <Stack
      direction={{ xs: "column", sm: "row" }}
      sx={{
        gap: 2,
        alignItems: { sm: "center" },
        justifyContent: "space-between",
        mb: 3,
      }}
    >
      <Box>
        <Typography variant="h4" component="h1">
          {title}
        </Typography>
        {subtitle && (
          <Typography
            sx={{
              color: "text.secondary",
              mt: 0.8,
            }}
          >
            {subtitle}
          </Typography>
        )}
      </Box>
      {actions}
    </Stack>
  );
}
export function Empty({
  title,
  text,
  to,
  action,
}: {
  title: string;
  text: string;
  to?: string;
  action?: string;
}) {
  return (
    <Paper sx={{ p: { xs: 3, md: 6 }, textAlign: "center" }}>
      <Typography variant="h6">{title}</Typography>
      <Typography
        sx={{
          color: "text.secondary",
          mt: 1,
          mb: 2,
        }}
      >
        {text}
      </Typography>
      {to && (
        <Button component={Link} to={to} variant="contained">
          {action}
        </Button>
      )}
    </Paper>
  );
}
