import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import Payments from "../app/routes/payments";
import { api } from "../app/api";

const context = vi.hoisted(() => ({ companyId: 1 as number | null }));
vi.mock("../app/routes/shell", () => ({ useApp: () => context }));
vi.mock("../app/bank-controls", () => ({ BankControls: () => null }));
vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
}));

function app() {
  return (
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <Payments />
      </QueryClientProvider>
    </MemoryRouter>
  );
}
function requested(values: Record<string, string>, endpoint = "invoices") {
  return vi.mocked(api).mock.calls.some(([path]) => {
    const url = new URL(path, "http://synthetic.test/");
    return (
      url.pathname.includes(endpoint) &&
      Object.entries(values).every(([k, v]) => url.searchParams.get(k) === v)
    );
  });
}
function select(label: string, option: string) {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: label }));
  fireEvent.click(screen.getByRole("option", { name: option }));
}

beforeEach(() => {
  vi.clearAllMocks();
  context.companyId = 1;
  vi.mocked(api).mockImplementation(async (path) => {
    const url = new URL(path, "http://synthetic.test/");
    if (url.pathname.includes("transactions"))
      return { items: [], next_cursor: null } as never;
    const filtered = url.searchParams.get("state") === "overdue";
    return {
      next_cursor: filtered ? null : 50,
      items: filtered
        ? [
            {
              document_id: "late-invoice",
              kind: "outgoing_invoice",
              number: "LATE-60",
              original_name: "synthetic.pdf",
              status: "partially_paid",
              paid: "40",
              remaining: "80",
              currency: "EUR",
              overdue: true,
              bank_evidence: "partial",
              as_of: "2026-11-01",
              review_reasons: ["Synthetischer Prüfhinweis"],
            },
          ]
        : [],
    } as never;
  });
});

it("sendet Firmenfilter vor Pagination, zeigt Server-Prüfgründe und setzt Cursor zurück", async () => {
  render(app());
  await waitFor(() =>
    expect(requested({ state: "all", cursor: "0" })).toBe(true),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Weitere" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Weitere" }));
  await waitFor(() => expect(requested({ cursor: "50" })).toBe(true));
  select("Firmenweiter Filter", "Überfällig");
  await waitFor(() =>
    expect(requested({ state: "overdue", cursor: "0" })).toBe(true),
  );
  expect(await screen.findByText("LATE-60")).toBeInTheDocument();
  expect(screen.getByText(/Synthetischer Prüfhinweis/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Weitere" })).toBeDisabled();
  select("Rechnungsart", "Ausgangsrechnungen");
  await waitFor(() =>
    expect(requested({ kind: "outgoing_invoice", state: "overdue" })).toBe(
      true,
    ),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Firmenweit suchen" }), {
    target: { value: "LATE & 60" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Suchen" }));
  await waitFor(() =>
    expect(requested({ search: "LATE & 60", cursor: "0" })).toBe(true),
  );
});

it("setzt inkompatible Filter bei Ansichtswechsel und Seiten bei Firmenwechsel zurück", async () => {
  const view = render(app());
  await waitFor(() => expect(requested({ company_id: "1" })).toBe(true));
  select("Firmenweiter Filter", "Überfällig");
  select("Ansicht", "Bankbewegungen / fehlende Zuordnung");
  await waitFor(() =>
    expect(requested({ state: "all", cursor: "0" }, "transactions")).toBe(true),
  );
  select("Firmenweiter Filter", "Zur Prüfung");
  await waitFor(() =>
    expect(requested({ state: "review" }, "transactions")).toBe(true),
  );
  context.companyId = 2;
  view.rerender(app());
  await waitFor(() =>
    expect(requested({ company_id: "2", state: "all", cursor: "0" })).toBe(
      true,
    ),
  );
});
