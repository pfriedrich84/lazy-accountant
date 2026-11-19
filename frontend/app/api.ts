export class APIError extends Error {
  constructor(
    message: string,
    public status: number,
    public details?: unknown,
  ) {
    super(message);
  }
}
let csrfToken = "";
export async function ensureCSRF() {
  const r = await fetch("/api/auth/csrf/", { credentials: "same-origin" });
  csrfToken = (await r.json()).csrfToken;
  return csrfToken;
}
export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = init.method || "GET";
  if (!["GET", "HEAD"].includes(method) && !csrfToken) await ensureCSRF();
  const headers = new Headers(init.headers);
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  )
    headers.set("Content-Type", "application/json");
  if (csrfToken) headers.set("X-CSRFToken", csrfToken);
  const r = await fetch(`/api/${path}`, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok)
    throw new APIError(
      data.error || data.detail || `Anfrage fehlgeschlagen (${r.status})`,
      r.status,
      data.details,
    );
  if (data.csrfToken) csrfToken = data.csrfToken;
  return data as T;
}
export function post<T>(path: string, data: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: JSON.stringify(data) });
}
export function errorMessage(e: unknown) {
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}
export function idempotencyKey() {
  // randomUUID requires a secure context; getRandomValues also works on LAN HTTP.
  if (typeof globalThis.crypto?.randomUUID === "function")
    return globalThis.crypto.randomUUID();
  if (typeof globalThis.crypto?.getRandomValues !== "function")
    throw new Error("Der Browser unterstützt keine sichere Zufallsquelle.");
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export const kinds: Record<string, string> = {
  incoming_invoice: "Eingangsrechnung",
  incoming_credit: "Eingangsgutschrift",
  receipt: "Sonstiger Beleg",
  outgoing_invoice: "Ausgangsrechnung",
  outgoing_cancellation: "Ausgangsstorno",
  bank_pdf: "Kontoauszug PDF",
  bank_camt: "Kontoauszug CAMT",
  security_pdf: "Wertpapierunterlage",
};
export const statusLabels: Record<string, string> = {
  new: "Neu",
  review: "Zu prüfen",
  ready: "Geprüft",
  queued: "In Warteschlange",
  running: "In Bearbeitung",
  done: "Abgeschlossen",
  failed: "Fehlgeschlagen",
  accepted: "SMTP angenommen",
  unknown: "Ausgang unbekannt",
  partial: "Teilweise angenommen",
  sending: "Versand läuft",
  interrupted: "Unterbrochen",
};
export function bytes(n: number) {
  return n >= 1024 * 1024
    ? `${(n / 1024 / 1024).toFixed(1)} MiB`
    : `${(n / 1024).toFixed(1)} KiB`;
}
export interface Company {
  id: number;
  name: string;
  folder: string;
  legal_name: string;
  tax_id: string;
  address: string;
  recipients: string[];
  allow_open_issues: boolean;
}
export interface Account {
  id: number;
  name: string;
  kind: "bank" | "depot";
  identifier: string;
}
export interface Category {
  id: number;
  name: string;
}
export interface Assignments {
  company: Company;
  accounts: Account[];
  categories: Category[];
  permissions: Record<string, boolean>;
}
export interface Metadata {
  issuer?: string | null;
  recipient?: string | null;
  number?: string | null;
  date?: string | null;
  service_date?: string | null;
  due_date?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  period_assignment_confirmed?: boolean;
  period_assignment_reason?: string | null;
  currency?: string | null;
  net?: string | null;
  tax?: string | null;
  gross?: string | null;
  taxes?: { rate?: string | null; net?: string | null; tax?: string | null }[];
  subtype?: string | null;
  note?: string;
  open_points?: string[];
  evidence?: Record<
    string,
    {
      page?: number | null;
      excerpt: string;
      uncertain: boolean;
      reason: string;
    }
  >;
}
export interface Document {
  id: string;
  company_id: number | null;
  original_name: string;
  sha256: string;
  size: number;
  media_type: string;
  kind: string;
  period: string;
  account_id: number | null;
  category_id: number | null;
  metadata: Metadata;
  issues: string[];
  status: string;
  version: number;
  is_excluded?: boolean;
  exclusion_reason?: string;
  excluded_at?: string | null;
  excluded_by_id?: number | null;
  packaged_in?: { id: string; version: number; revision: number }[];
  filed_path: string;
  filing_status?: "pending" | "done";
  filing_error?: string;
  desired_path?: string;
  duplicate_of: string | null;
  related_ids?: string[];
  referenced_by_ids?: string[];
  created_at: string;
  updated_at: string;
  parser_error?: string;
  parser_result?: unknown;
  sources?: unknown[];
  revisions?: {
    version: number;
    actor_id: number;
    source: string;
    reason?: string;
    created_at: string;
  }[];
}
export interface Page {
  results: Document[];
  total: number;
  next_cursor: string | null;
}
export interface Package {
  id: string;
  company_id: number;
  periods: string[];
  version: number;
  parent_id: string | null;
  sha256: string;
  size: number;
  created_at: string;
  snapshot?: Preview;
}
export interface Preview {
  company: { id: number; name: string; folder: string };
  periods: string[];
  parent_id: string | null;
  recipients: string[];
  allow_open_issues: boolean;
  documents: (Document & { archive_path: string })[];
  excluded: { document: Document; reason: string }[];
  schema_version?: number;
  intentional_exclusions?: { document: Document; reason: string }[];
  excluded_inbox?: string[];
  exclusion_changes?: {
    document_id: string;
    original_name: string;
    old_revision: number;
    new_revision: number;
    action: "exclude" | "restore";
    reason: string;
    previous_package_id: string;
  }[];
  unassigned_inbox: string[];
  unchanged: string[];
  count: number;
  bytes: number;
  by_kind: Record<string, number>;
  max_package_bytes?: number;
}
export interface Job {
  id: string;
  company_id: number;
  kind: string;
  status: string;
  result: Record<string, unknown>;
  error: string;
  created_at: string;
}
export interface Dispatch {
  id: string;
  package_id: string;
  status: string;
  recipients: string[];
  resend_of: string | null;
  parts: {
    number: number;
    total: number;
    filename: string;
    sha256: string;
    bytes: number;
  }[];
  attempts: {
    id: number;
    part: number;
    message_id: string;
    status: string;
    detail: string;
  }[];
  created_at: string;
}
