import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { api, type Assignments, type Company, post } from "../api";
import { ErrorAlert, Heading, Loading } from "../components";
import { useApp } from "./shell";

type MailConfig = Record<string, string | number | boolean | string[] | null>;
const mailKeys = [
  "imap_host",
  "imap_port",
  "imap_tls",
  "imap_user",
  "imap_folder",
  "import_since",
  "enabled",
  "aliases",
  "smtp_host",
  "smtp_port",
  "smtp_user",
  "smtp_security",
  "sender",
  "reply_to",
  "max_message_bytes",
  "subject_template",
  "body_template",
];

function CompanySettings({ company }: { company: Company }) {
  const cache = useQueryClient();
  const [form, setForm] = useState(company);
  const [recipients, setRecipients] = useState(company.recipients.join("\n"));
  const [notice, setNotice] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      api<Company>(`companies/${company.id}/`, {
        method: "PATCH",
        body: JSON.stringify({
          ...form,
          recipients: recipients
            .split(/[\n,;]/)
            .map((s) => s.trim())
            .filter(Boolean),
        }),
      }),
    onSuccess: () => {
      setNotice(true);
      void cache.invalidateQueries();
    },
  });
  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Firmendaten & Übergaberegeln
      </Typography>
      <Stack spacing={2}>
        {(["name", "legal_name", "tax_id", "address"] as const).map(
          (key, i) => (
            <TextField
              key={key}
              label={
                [
                  "Anzeigename",
                  "Vollständiger Firmenname",
                  "UID / Steuernummer",
                  "Anschrift",
                ][i]
              }
              value={form[key]}
              onChange={(e) =>
                setForm((f) => ({ ...f, [key]: e.target.value }))
              }
              multiline={key === "address"}
            />
          ),
        )}
        <TextField
          label="Ablageordner (unveränderlich)"
          value={company.folder}
          slotProps={{ input: { readOnly: true } }}
        />
        <TextField
          label="Steuerberater-Empfänger (eine Adresse pro Zeile)"
          multiline
          minRows={2}
          value={recipients}
          onChange={(e) => setRecipients(e.target.value)}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={form.allow_open_issues}
              onChange={(e) =>
                setForm((f) => ({ ...f, allow_open_issues: e.target.checked }))
              }
            />
          }
          label="Versand trotz offener / ausgeschlossener Unterlagen erlauben"
        />
        <Alert severity="info">
          Empfänger und Versandregel werden bei der Paketerstellung eingefroren.
          Änderungen gelten erst für neu erzeugte Paketversionen.
        </Alert>
        <Button
          variant="contained"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Firmendaten speichern
        </Button>
        <ErrorAlert error={save.error} />
        {notice && <Alert severity="success">Firmendaten gespeichert.</Alert>}
      </Stack>
    </Paper>
  );
}

function AssignmentSettings({ companyId }: { companyId: number }) {
  const cache = useQueryClient();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("bank");
  const [identifier, setIdentifier] = useState("");
  const [category, setCategory] = useState("");
  const query = useQuery({
    queryKey: ["assignments", companyId],
    queryFn: () => api<Assignments>(`companies/${companyId}/`),
  });
  const create = useMutation({
    mutationFn: (collection: string) =>
      post(
        `companies/${companyId}/${collection}/`,
        collection === "accounts"
          ? { name, kind, identifier }
          : { name: category },
      ),
    onSuccess: () => {
      setName("");
      setIdentifier("");
      setCategory("");
      void cache.invalidateQueries({ queryKey: ["assignments", companyId] });
    },
  });
  return (
    <Stack
      sx={{
        gap: 3,
      }}
    >
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Bankkonten & Depots
        </Typography>
        {query.data?.accounts.map((a) => (
          <Typography key={a.id} sx={{ my: 1 }}>
            {a.name} · {a.kind === "bank" ? "Bankkonto" : "Depot"} ·{" "}
            {a.identifier}{" "}
            <Typography component="span" variant="caption">
              (ID {a.id})
            </Typography>
          </Typography>
        ))}
        <Divider sx={{ my: 2 }} />
        <Stack
          direction={{ xs: "column", sm: "row" }}
          sx={{
            gap: 2,
            flexWrap: "wrap",
          }}
        >
          <TextField
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <TextField
            select
            label="Art"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            sx={{ minWidth: 130 }}
          >
            <MenuItem value="bank">Bankkonto</MenuItem>
            <MenuItem value="depot">Depot</MenuItem>
          </TextField>
          <TextField
            label="IBAN / Depotkennung"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
          />
          <Button
            variant="contained"
            disabled={!name || create.isPending}
            onClick={() => create.mutate("accounts")}
          >
            Hinzufügen
          </Button>
        </Stack>
      </Paper>
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Kategorien
        </Typography>
        <Typography sx={{ mb: 2 }}>
          {query.data?.categories
            .map((c) => `${c.name} (ID ${c.id})`)
            .join(" · ") || "Noch keine Kategorien."}
        </Typography>
        <Stack
          direction="row"
          sx={{
            gap: 2,
          }}
        >
          <TextField
            label="Neue Kategorie"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
          <Button
            variant="contained"
            disabled={!category || create.isPending}
            onClick={() => create.mutate("categories")}
          >
            Hinzufügen
          </Button>
        </Stack>
      </Paper>
      <ErrorAlert error={query.error || create.error} />
    </Stack>
  );
}

function MailEditor({
  companyId,
  config,
}: {
  companyId: number;
  config: MailConfig;
}) {
  const cache = useQueryClient();
  const [form, setForm] = useState(config);
  const [imapPassword, setImapPassword] = useState<string | null>(null);
  const [smtpPassword, setSmtpPassword] = useState<string | null>(null);
  const [notice, setNotice] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      api(`settings/${companyId}/mail/`, {
        method: "PUT",
        body: JSON.stringify({
          ...Object.fromEntries(mailKeys.map((k) => [k, form[k]])),
          imap_password: imapPassword,
          smtp_password: smtpPassword,
        }),
      }),
    onSuccess: () => {
      setNotice(true);
      setImapPassword(null);
      setSmtpPassword(null);
      void cache.invalidateQueries({ queryKey: ["mail", companyId] });
    },
  });
  const field = (key: string, label: string, type = "text") => (
    <TextField
      key={key}
      label={label}
      type={type}
      value={form[key] ?? ""}
      onChange={(e) =>
        setForm((f) => ({
          ...f,
          [key]:
            type === "number"
              ? Number(e.target.value)
              : e.target.value || (key === "import_since" ? null : ""),
        }))
      }
      fullWidth
      slotProps={type === "date" ? { inputLabel: { shrink: true } } : undefined}
    />
  );
  return (
    <>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" },
          gap: 3,
        }}
      >
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Eingang über IMAP
          </Typography>
          <Stack spacing={2}>
            {field("imap_host", "IMAP-Host")}
            <Stack
              direction="row"
              sx={{
                gap: 2,
              }}
            >
              {field("imap_port", "Port", "number")}
              <FormControlLabel
                control={
                  <Checkbox
                    checked={Boolean(form.imap_tls)}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, imap_tls: e.target.checked }))
                    }
                  />
                }
                label="TLS"
              />
            </Stack>
            {field("imap_user", "Benutzer")}
            <TextField
              label={
                config.imap_password_set
                  ? "Neues Passwort (vorhandenes bleibt sonst erhalten)"
                  : "Passwort"
              }
              type="password"
              autoComplete="new-password"
              value={imapPassword || ""}
              onChange={(e) => setImapPassword(e.target.value)}
            />
            {field("imap_folder", "Ordner")}
            {field("import_since", "Expliziter Importbeginn", "date")}
            <TextField
              label="Empfänger-/Aliasregel (optional, eine Adresse pro Zeile)"
              multiline
              value={Array.isArray(form.aliases) ? form.aliases.join("\n") : ""}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  aliases: e.target.value
                    .split("\n")
                    .map((s) => s.trim())
                    .filter(Boolean),
                }))
              }
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={Boolean(form.enabled)}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, enabled: e.target.checked }))
                  }
                />
              }
              label="Regelmäßigen IMAP-Abruf aktivieren"
            />
            <Alert severity="info">
              Dediziertes Belegpostfach oder gezielter Ordner empfohlen.
              Nachrichten werden nicht gelöscht. Ohne Aliasregel ist das
              Postfach eindeutig dieser Firma zugeordnet.
            </Alert>
            <Typography variant="caption">
              Letzter Abruf: {String(config.last_scan_at || "noch keiner")} ·
              UID {String(config.last_uid || 0)}
            </Typography>
          </Stack>
        </Paper>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Paketversand über SMTP
          </Typography>
          <Stack spacing={2}>
            {field("smtp_host", "SMTP-Host")}
            {field("smtp_port", "Port", "number")}
            <TextField
              select
              label="Transportsicherheit"
              value={form.smtp_security || "starttls"}
              onChange={(e) =>
                setForm((f) => ({ ...f, smtp_security: e.target.value }))
              }
            >
              <MenuItem value="starttls">STARTTLS</MenuItem>
              <MenuItem value="ssl">TLS (SSL-Port)</MenuItem>
              <MenuItem value="none">
                Unverschlüsselt (nur lokales Testsystem)
              </MenuItem>
            </TextField>
            {field("smtp_user", "Benutzer")}
            <TextField
              label={
                config.smtp_password_set
                  ? "Neues Passwort (vorhandenes bleibt sonst erhalten)"
                  : "Passwort"
              }
              type="password"
              autoComplete="new-password"
              value={smtpPassword || ""}
              onChange={(e) => setSmtpPassword(e.target.value)}
            />
            {field("sender", "Absenderadresse", "email")}
            {field("reply_to", "Antwortadresse", "email")}
            {field(
              "max_message_bytes",
              "Maximale Nachrichtengröße in Bytes",
              "number",
            )}
            {field("subject_template", "Betreffvorlage")}
            <TextField
              label="Mailtext-Vorlage"
              multiline
              minRows={4}
              value={form.body_template || ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, body_template: e.target.value }))
              }
            />
            <Typography variant="caption">
              Platzhalter: {"{company}, {period}, {version}, {notes}"}
            </Typography>
            <Alert severity="warning">
              SMTP-Annahme ist keine Zustellbestätigung. Bei unbekanntem Ausgang
              wird nicht automatisch erneut versendet.
            </Alert>
          </Stack>
        </Paper>
      </Box>
      <Stack
        direction="row"
        sx={{
          gap: 2,
          mt: 3,
        }}
      >
        <Button
          variant="contained"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Mail-Einstellungen speichern
        </Button>
        {notice && <Alert severity="success">Gespeichert.</Alert>}
      </Stack>
      <ErrorAlert error={save.error} />
    </>
  );
}

function MailSettings({ companyId }: { companyId: number }) {
  const q = useQuery({
    queryKey: ["mail", companyId],
    queryFn: () => api<MailConfig>(`settings/${companyId}/mail/`),
  });
  const errors = useQuery({
    queryKey: ["import-errors", companyId],
    queryFn: () =>
      api<{ id: number; error: string; provenance: Record<string, unknown> }[]>(
        `import-errors/${companyId}/`,
      ),
  });
  return (
    <>
      <ErrorAlert error={q.error || errors.error} />
      {q.isPending ? (
        <Loading />
      ) : (
        q.data && (
          <MailEditor key={companyId} companyId={companyId} config={q.data} />
        )
      )}
      {!!errors.data?.length && (
        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6">Nicht übernommene Mailanhänge</Typography>
          {errors.data.map((e) => (
            <Alert severity="warning" key={e.id} sx={{ mt: 2 }}>
              {String(e.provenance.filename || e.provenance.uid || "")}:{" "}
              {e.error}
              <Typography
                variant="caption"
                sx={{
                  display: "block",
                }}
              >
                Datei-/Nachrichtenherkunft bleibt gespeichert.
              </Typography>
            </Alert>
          ))}
        </Paper>
      )}
    </>
  );
}

function Tokens({ companyId }: { companyId: number | null }) {
  const cache = useQueryClient();
  const [name, setName] = useState("Orca-Agent");
  const [scopes, setScopes] = useState(["read", "process", "inbox"]);
  const [raw, setRaw] = useState("");
  const list = useQuery({
    queryKey: ["tokens"],
    queryFn: () =>
      api<
        {
          id: number;
          name: string;
          prefix: string;
          scopes: string[];
          revoked: boolean;
        }[]
      >("tokens/"),
  });
  const create = useMutation({
    mutationFn: () =>
      post<{ token: string }>("tokens/", {
        name,
        company_ids: companyId ? [companyId] : [],
        scopes,
      }),
    onSuccess: (result) => {
      setRaw(result.token);
      void cache.invalidateQueries({ queryKey: ["tokens"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api(`tokens/${id}/`, { method: "DELETE" }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["tokens"] }),
  });
  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6">MCP-Zugang für den externen Agenten</Typography>
      <Typography
        sx={{
          color: "text.secondary",
          my: 2,
        }}
      >
        Endpunkt:{" "}
        <code>
          {typeof location !== "undefined" ? location.origin : ""}/mcp/
        </code>
        <br />
        Authentifizierung: <code>Authorization: Bearer &lt;Token&gt;</code>.
        Kein LLM-Schlüssel erforderlich.
      </Typography>
      <TextField
        label="Tokenname"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <Stack
        direction="row"
        sx={{
          flexWrap: "wrap",
        }}
      >
        {[
          ["read", "Lesen"],
          ["process", "Verarbeiten"],
          ["send", "Versenden"],
          ["inbox", "Unzugeordneter Eingang"],
        ].map(([key, title]) => (
          <FormControlLabel
            key={key}
            label={title}
            control={
              <Checkbox
                checked={scopes.includes(key)}
                onChange={(e) =>
                  setScopes((s) =>
                    e.target.checked ? [...s, key] : s.filter((v) => v !== key),
                  )
                }
              />
            }
          />
        ))}
      </Stack>
      <Button
        variant="contained"
        disabled={!companyId || create.isPending}
        onClick={() => create.mutate()}
      >
        Token für gewählte Firma erzeugen
      </Button>
      {raw && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          Nur jetzt sichtbar – sicher speichern und nicht in Git oder Protokolle
          kopieren:
          <Box
            component="code"
            sx={{
              display: "block",
              overflowWrap: "anywhere",
              mt: 1,
              userSelect: "all",
            }}
          >
            {raw}
          </Box>
          <Button onClick={() => setRaw("")}>Anzeige schließen</Button>
        </Alert>
      )}
      <ErrorAlert error={create.error || list.error || revoke.error} />
      <Divider sx={{ my: 3 }} />
      {list.data?.map((t) => (
        <Stack
          key={t.id}
          direction="row"
          sx={{
            gap: 2,
            alignItems: "center",
            py: 1,
          }}
        >
          <Box sx={{ flex: 1 }}>
            <Typography>
              {t.name} · {t.prefix}… {t.revoked ? "(widerrufen)" : ""}
            </Typography>
            <Typography variant="caption">{t.scopes.join(", ")}</Typography>
          </Box>
          <Button disabled={t.revoked} onClick={() => revoke.mutate(t.id)}>
            Widerrufen
          </Button>
        </Stack>
      ))}
    </Paper>
  );
}

export default function Settings() {
  const { company, companyId, setCompanyId } = useApp();
  const cache = useQueryClient();
  const [tab, setTab] = useState(0);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const create = useMutation({
    mutationFn: () => post<Company>("companies/", { name, folder }),
    onSuccess: async (c) => {
      setOpen(false);
      setName("");
      setFolder("");
      setCompanyId(c.id);
      await cache.invalidateQueries({ queryKey: ["companies"] });
    },
  });
  return (
    <>
      <Heading
        title="Einstellungen"
        subtitle="Firmen bleiben getrennt. Mailgeheimnisse werden verschlüsselt gespeichert und nie zurückgelesen."
        actions={
          <Button variant="contained" onClick={() => setOpen(true)}>
            + Firma anlegen
          </Button>
        }
      />
      <Tabs
        value={tab}
        onChange={(_, v: number) => setTab(v)}
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{ mb: 3 }}
      >
        <Tab label="Firma" />
        <Tab label="Konten & Kategorien" />
        <Tab label="IMAP & SMTP" />
        <Tab label="Agent / MCP" />
      </Tabs>
      {tab === 0 && company && (
        <CompanySettings key={company.id} company={company} />
      )}
      {tab === 1 && companyId && (
        <AssignmentSettings key={companyId} companyId={companyId} />
      )}
      {tab === 2 && companyId && (
        <MailSettings key={companyId} companyId={companyId} />
      )}
      {tab === 3 && <Tokens companyId={companyId} />}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Neue Firma anlegen</DialogTitle>
        <DialogContent>
          <Stack
            sx={{
              gap: 2,
              pt: 1,
            }}
          >
            <TextField
              label="Firmenname"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setFolder(
                  e.target.value
                    .normalize("NFKD")
                    .replace(/[\u0300-\u036f]/g, "")
                    .replace(/[^a-zA-Z0-9_-]+/g, "-")
                    .replace(/^-+|-+$/g, "")
                    .slice(0, 80),
                );
              }}
            />
            <TextField
              label="Eindeutiger Ablageordner"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              helperText="Buchstaben, Ziffern, - und _. Nach Anlage unveränderlich."
            />
            <ErrorAlert error={create.error} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Abbrechen</Button>
          <Button
            variant="contained"
            disabled={!name || !folder || create.isPending}
            onClick={() => create.mutate()}
          >
            Firma speichern
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
