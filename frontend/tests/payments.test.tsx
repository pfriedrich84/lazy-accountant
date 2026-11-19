import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, post, type Document } from "../app/api";
import { PaymentPanel } from "../app/payments";

vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const invoice = {
  id: "invoice-1",
  version: 2,
  company_id: 1,
  kind: "outgoing_invoice",
  metadata: { recipient: "Acme Customer" },
  status: "ready",
} as Document;

function panel(doc = invoice) {
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false } },
          })
        }
      >
        <PaymentPanel doc={doc} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith("companies/"))
      return {
        permissions: { read: true, process: true, admin: false },
      } as never;
    if (path.includes("transactions/"))
      return { items: [], next_cursor: null } as never;
    if (path.includes("status/"))
      return {
        document_id: "invoice-1",
        document_version: 2,
        status: "partially_paid",
        currency: "EUR",
        paid: "40",
        remaining: "80",
        due_date: "2026-10-20",
        overdue: true,
        bank_evidence: "partial",
        as_of: "2026-10-21",
        allocations: [],
      } as never;
    throw new Error(`Unexpected URL ${path}`);
  });
});

describe("Bankabgleich", () => {
  it("zeigt Teilzahlung, Rest und Überfälligkeit als getrennte Angaben", async () => {
    panel();
    expect(await screen.findByText("Teilweise bezahlt")).toBeInTheDocument();
    expect(screen.getByText(/offen 80 EUR/)).toBeInTheDocument();
    expect(screen.getByText(/Überfällig/)).toBeInTheDocument();
    expect(screen.getByText(/Bankdeckung: partial/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /verifizieren/ }),
    ).not.toBeInTheDocument();
  });

  it("erfindet bei fehlender Fälligkeit keine Überfälligkeit", async () => {
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, init) => {
      const value = await original(path, init);
      return path.includes("status/")
        ? ({ ...(value as object), overdue: null, due_date: null } as never)
        : value;
    });
    panel();
    expect(await screen.findByText(/Fälligkeit ungeklärt/)).toBeInTheDocument();
    expect(screen.queryByText(/^Überfällig/)).not.toBeInTheDocument();
  });

  it("startet den autorisierten CAMT-Abgleich mit Version und Idempotenzschlüssel", async () => {
    vi.mocked(post).mockResolvedValue({ confirmed: [] });
    panel({ ...invoice, kind: "bank_camt" });
    const button = await screen.findByRole("button", {
      name: /CAMT abgleichen/,
    });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "reconciliation/normalize/",
        expect.objectContaining({
          document_id: "invoice-1",
          base_version: 2,
          auto_confirm: true,
          idempotency_key: expect.any(String),
        }),
      ),
    );
  });

  it("behält nach unbekanntem Netzwerkfehler den Auftragsschlüssel bei", async () => {
    vi.mocked(post)
      .mockRejectedValueOnce(new Error("Verbindung unterbrochen"))
      .mockResolvedValueOnce({ confirmed: [] });
    panel({ ...invoice, kind: "bank_camt" });
    const button = await screen.findByRole("button", {
      name: /CAMT abgleichen/,
    });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(
      await screen.findByText("Verbindung unterbrochen"),
    ).toBeInTheDocument();
    fireEvent.click(button);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(post).mock.calls[0][1]).toEqual(
      vi.mocked(post).mock.calls[1][1],
    );
  });

  it("begrenzt Schreibaktionen auf process-Rechte", async () => {
    vi.mocked(api).mockResolvedValue({
      permissions: { read: true, process: false },
    } as never);
    panel({ ...invoice, kind: "bank_camt" });
    const button = await screen.findByRole("button", {
      name: /CAMT abgleichen/,
    });
    await waitFor(() => expect(button).toBeDisabled());
    expect(post).not.toHaveBeenCalled();
  });
});
