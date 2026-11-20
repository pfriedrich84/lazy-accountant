import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { BankControls } from "../app/bank-controls";
import { api, post } from "../app/api";

vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
let admin = true;
function app() {
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <BankControls companyId={1} period="2026-10" />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  admin = true;
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith("companies/"))
      return { permissions: { read: true, process: admin, admin } } as never;
    if (path.includes("policy/"))
      return { enabled: true, version: 3, persisted: true } as never;
    return {
      items: [
        {
          account_id: 2,
          account_name: "Synthetic Bank",
          period: "2026-10",
          latest_booked_date: "2026-10-15",
          transaction_count: 3,
          pending_count: 1,
          security_blocked: false,
          coverage: {
            version: 0,
            declared_state: "unknown",
            effective_state: "confirmed",
            basis: "accepted_monthly_statement_convention",
            review_reasons: [],
            sources: [],
          },
          statements: [
            {
              document_id: "source-1",
              version: 2,
              ready_for_confirmation: true,
              review_reasons: [],
            },
          ],
          history: [],
        },
      ],
    } as never;
  });
  vi.mocked(post).mockResolvedValue({} as never);
});

it("zeigt Monatsregel getrennt vom beobachteten Buchungsdatum, ohne erneute Pflichtbestätigung", async () => {
  app();
  expect(
    await screen.findByText(/Gemäß bereits bestätigter Monatsregel/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Letzte beobachtete gebuchte Bewegung.*2026-10-15/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Monatsvollständigkeit bestätigt · Version 0/),
  ).toBeInTheDocument();
  expect(vi.mocked(post)).not.toHaveBeenCalled();
});

it("speichert explizite Adminpolicy mit Version, Grund und stabiler Wiederholung", async () => {
  vi.mocked(post).mockRejectedValue(new Error("Netzwerk unbekannt"));
  app();
  const button = await screen.findByRole("button", {
    name: "Automatik deaktivieren",
  });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Begründung zur Automatikpolicy"), {
    target: { value: "Nur Vorschläge gewünscht" },
  });
  fireEvent.click(button);
  await screen.findByText("Netzwerk unbekannt");
  fireEvent.click(button);
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(vi.mocked(post).mock.calls[0]).toEqual(vi.mocked(post).mock.calls[1]);
  expect(vi.mocked(post).mock.calls[0][1]).toMatchObject({
    company_id: 1,
    expected_version: 3,
    enabled: false,
    reason: "Nur Vorschläge gewünscht",
  });
});

it("dokumentiert Quellen und Monatsabdeckung ohne Zahlungsauftrag", async () => {
  app();
  fireEvent.change(
    await screen.findByLabelText("Begründung zur Monatsabdeckung"),
    { target: { value: "Originalmonat geprüft" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Abdeckung speichern" }));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(vi.mocked(post).mock.calls[0]).toEqual([
    "reconciliation/coverage/",
    expect.objectContaining({
      company_id: 1,
      account_id: 2,
      period: "2026-10",
      expected_version: 0,
      state: "confirmed",
      document_ids: ["source-1"],
    }),
  ]);
  expect(
    await screen.findByText("Erklärung gespeichert. Keine Zahlung erzeugt."),
  ).toBeInTheDocument();
});

it("bietet read-only Tokens keine Kontrollschreibaktionen an", async () => {
  admin = false;
  app();
  await screen.findByText(/Synthetic Bank/);
  expect(
    screen.queryByRole("button", { name: "Automatik deaktivieren" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Abdeckung speichern" }),
  ).not.toBeInTheDocument();
});
