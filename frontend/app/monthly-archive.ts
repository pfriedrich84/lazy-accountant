import { kinds, type Document } from "./api";

export interface ReviewCounts {
  total: number;
  ready: number;
  open: number;
}

export interface ArchiveFolder extends ReviewCounts {
  name: string;
  path: string;
  files: Document[];
}

export interface MonthPage {
  folders: ArchiveFolder[];
  unfiled: ReviewCounts & { files: Document[] };
  summary: ReviewCounts;
  total: number;
  next_cursor: string | null;
}

export function documentDate(doc: Document) {
  return (
    doc.metadata.valuation_date ||
    doc.metadata.date ||
    doc.metadata.period_end ||
    ""
  );
}

export function formatDocumentDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("de-AT", { timeZone: "UTC" }).format(date);
}

export function documentTitle(doc: Document) {
  // Preserve manual choices and safe fallback names; do not promote uncertain parser data.
  if (doc.name_source !== "generated") return doc.effective_name;
  // Account/depot names are carried by the effective filename, not this API's metadata.
  // Keep them for statements instead of making different accounts look identical.
  if (
    ["bank_pdf", "bank_camt"].includes(doc.kind) ||
    (doc.kind === "security_pdf" && !doc.metadata.isin)
  )
    return doc.effective_name;
  const metadata = doc.metadata;
  const partner = doc.kind.startsWith("outgoing_")
    ? metadata.confirmed_partner_name || metadata.recipient
    : metadata.bank_short_name ||
      metadata.confirmed_partner_name ||
      metadata.issuer;
  const label = metadata.subtype || kinds[doc.kind];
  return partner && label ? `${partner} · ${label}` : doc.effective_name;
}

export function mergeMonthPages(pages: MonthPage[]): ArchiveFolder[] {
  const first = pages[0];
  if (!first) return [];
  const folders = first.folders.map((folder) => ({
    ...folder,
    files: [] as Document[],
  }));
  if (first.unfiled.total) {
    folders.push({
      ...first.unfiled,
      name: "Noch nicht eingeordnet",
      path: "",
      files: [],
    });
  }
  for (const folder of folders) {
    const documents = new Map<string, Document>();
    for (const page of pages) {
      const files = folder.path
        ? page.folders.find((candidate) => candidate.name === folder.name)
            ?.files
        : page.unfiled.files;
      for (const doc of files || []) documents.set(doc.id, doc);
    }
    folder.files = [...documents.values()].sort(
      (a, b) =>
        documentDate(b).localeCompare(documentDate(a)) ||
        a.effective_name.localeCompare(b.effective_name, "de") ||
        a.id.localeCompare(b.id),
    );
  }
  return folders;
}
