import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Document } from "../app/api";
import {
  documentTitle,
  mergeMonthPages,
  type MonthPage,
} from "../app/monthly-archive";
import Months from "../app/routes/months";

const context = vi.hoisted(() => ({ companyId: 1, period: "2026-10" }));
vi.mock("../app/routes/shell", () => ({ useApp: () => context }));
vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
}));

function document(id: string, overrides: Partial<Document> = {}): Document {
  return {
    id,
    original_name: `ORIGINAL_${id}.pdf`,
    effective_name: `2026-10-15 Erste Bank Ausschüttung ${id}.pdf`,
    name_source: "generated",
    kind: "security_pdf",
    status: "ready",
    metadata: {
      bank_short_name: "Erste Bank",
      subtype: "Ausschüttung",
      date: "2026-10-15",
      isin: id,
    },
    ...overrides,
  } as Document;
}

function page(files: Document[], next: string | null = null): MonthPage {
  return {
    folders: [
      {
        name: "Wertpapiere",
        path: "Firma/2026/10/Wertpapiere/",
        files,
        total: 105,
        ready: 101,
        open: 4,
      },
      {
        name: "ER",
        path: "Firma/2026/10/ER/",
        files: [],
        total: 0,
        ready: 0,
        open: 0,
      },
    ],
    unfiled: { files: [], total: 0, ready: 0, open: 0 },
    summary: { total: 105, ready: 101, open: 4 },
    total: 105,
    next_cursor: next,
  };
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <Months />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  context.companyId = 1;
  context.period = "2026-10";
});

describe("Monatsablage", () => {
  it("zeigt Monatszahlen unabhängig von geladenen Seiten und lädt weitere Dokumente", async () => {
    vi.mocked(api).mockImplementation(async (url) => {
      return (
        url.includes("cursor=next")
          ? page([document("DE002")])
          : page([document("DE001")], "next")
      ) as never;
    });
    mount();
    expect(
      await screen.findByText("105 Dokumente · 101 geprüft · 4 zu prüfen"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("1 von 105 Dokumenten angezeigt"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Original:/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Wertpapiere" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("ISIN DE001", { exact: false }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Firma/2026/10/Wertpapiere/", { exact: false }),
    ).not.toBeVisible();
    await userEvent.click(screen.getAllByText("Ablagepfad anzeigen")[0]);
    expect(
      screen.getByText("Firma/2026/10/Wertpapiere/", { exact: false }),
    ).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Weitere Dokumente laden" }),
    );
    expect(
      await screen.findByText("2 von 105 Dokumenten angezeigt"),
    ).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("folders/1/?period=2026-10&cursor=next");
    expect(
      screen.queryByRole("button", { name: "Weitere Dokumente laden" }),
    ).not.toBeInTheDocument();
  });

  it("filtert offene Prüfungen serverseitig und behält die Monatszahlen", async () => {
    vi.mocked(api).mockImplementation(async (url) => {
      const result = page([
        document(url.includes("status=open") ? "OPEN" : "READY", {
          status: url.includes("status=open") ? "review" : "ready",
        }),
      ]);
      if (url.includes("status=open")) result.total = 4;
      return result as never;
    });
    mount();
    await screen.findByText("105 Dokumente · 101 geprüft · 4 zu prüfen");
    await userEvent.click(
      screen.getByRole("button", { name: "Zu prüfen (4)" }),
    );
    expect(
      await screen.findByText("1 von 4 offenen Dokumenten angezeigt"),
    ).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("folders/1/?period=2026-10&status=open");
    expect(
      screen.queryByRole("heading", { name: "ER" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Zu prüfen (4)" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText("105 Dokumente · 101 geprüft · 4 zu prüfen"),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Alle Dokumente" }),
    );
    expect(
      await screen.findByRole("heading", { name: "ER" }),
    ).toBeInTheDocument();
  });

  it("wechselt beim Firmen- oder Monatswechsel auf einen neuen Cursor", async () => {
    vi.mocked(api).mockResolvedValue(page([document("FIRST")], "next"));
    const view = mount();
    await screen.findByText("1 von 105 Dokumenten angezeigt");
    context.companyId = 2;
    context.period = "2026-11";
    view.rerender(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient()}>
          <Months />
        </QueryClientProvider>
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("folders/2/?period=2026-11"),
    );
  });

  it("unterscheidet leere Monate von vollständig geprüften Dokumenten", async () => {
    const result = page([]);
    result.summary = { total: 0, ready: 0, open: 0 };
    result.total = 0;
    result.folders.forEach((folder) => {
      folder.total = 0;
      folder.open = 0;
      folder.ready = 0;
    });
    vi.mocked(api).mockResolvedValue(result);
    mount();
    expect(
      await screen.findByText("0 Dokumente · 0 geprüft · 0 zu prüfen"),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Zu prüfen (0)" }),
    );
    expect(
      await screen.findByText(
        "Für diesen Monat sind noch keine Dokumente zugeordnet.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Alle zugeordneten Dokumente sind geprüft."),
    ).not.toBeInTheDocument();
  });

  it("zeigt auch Dokumente ohne Ordnerzuordnung statt sie still zu verbergen", async () => {
    const result = page([]);
    result.unfiled = {
      total: 1,
      ready: 0,
      open: 1,
      files: [
        document("UNFILED", {
          kind: "",
          status: "new",
          name_source: "fallback",
          effective_name: "Eingang-123.pdf",
        }),
      ],
    };
    vi.mocked(api).mockResolvedValue(result);
    mount();
    const heading = await screen.findByRole("heading", {
      name: "Noch nicht eingeordnet",
    });
    const section = heading.closest("section")!;
    expect(
      within(section).getByRole("link", { name: "Eingang-123.pdf" }),
    ).toBeInTheDocument();
    expect(
      within(section).queryByText("Ablagepfad anzeigen"),
    ).not.toBeInTheDocument();
  });

  it("erhält geladene Dokumente bei einem fehlgeschlagenen Nachladen", async () => {
    vi.mocked(api).mockImplementation(async (url) => {
      if (url.includes("cursor=")) throw new Error("Netzwerk unterbrochen");
      return page([document("DE001")], "next") as never;
    });
    mount();
    await screen.findByText("1 von 105 Dokumenten angezeigt");
    await userEvent.click(
      screen.getByRole("button", { name: "Weitere Dokumente laden" }),
    );
    expect(
      await screen.findByText("Netzwerk unterbrochen"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Erste Bank · Ausschüttung" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Weitere Dokumente laden" }),
    ).toBeEnabled();
  });

  it("bewahrt manuelle und sichere Fallback-Namen", () => {
    const manual = document("MANUAL", {
      name_source: "manual",
      effective_name: "Meine Bezeichnung.pdf",
    });
    expect(documentTitle(manual)).toBe("Meine Bezeichnung.pdf");
    expect(documentTitle({ ...manual, name_source: "fallback" })).toBe(
      "Meine Bezeichnung.pdf",
    );
  });

  it("behält Konto- und Depotbezeichnungen in Auszügen bei", () => {
    const bank = document("BANK", {
      kind: "bank_pdf",
      effective_name: "2026-10-31 Bank Betriebskonto Auszug.pdf",
    });
    expect(documentTitle(bank)).toBe(bank.effective_name);
    const depot = document("DEPOT", {
      metadata: { bank_short_name: "Bank", subtype: "Depotauszug" },
      effective_name: "2026-10-31 Bank Depot A Depotauszug.pdf",
    });
    expect(documentTitle(depot)).toBe(depot.effective_name);
  });

  it("führt Seiten ohne doppelte IDs zusammen und sortiert nach Datum", () => {
    const older = document("OLD", { metadata: { date: "2026-10-01" } });
    const newer = document("NEW", { metadata: { date: "2026-10-31" } });
    const folders = mergeMonthPages([
      page([older], "next"),
      page([newer, older]),
    ]);
    expect(folders[0].files.map((doc) => doc.id)).toEqual(["NEW", "OLD"]);
    expect(folders[0].total).toBe(105);
  });
});
