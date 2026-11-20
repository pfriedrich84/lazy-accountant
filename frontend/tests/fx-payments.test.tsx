import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { api, post, type Document } from "../app/api";
import { FXPayment } from "../app/fx-payments";
import type { BankMovement } from "../app/payments";

vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
const evidence = {
  id: "synthetic-evidence",
  document_id: "bank-source",
  locator: "statement:0/entry:0/detail:0",
  original_amount: "60.00",
  original_currency: "USD",
  rate: "0.916666666666667",
  fee: "1.00",
  method: "bank-text-v1",
  paths: ["RmtInf/Ustrd[0]"],
  card_date: "2026-10-01",
  quote: "Synthetic original text",
};
function panel(canProcess = true) {
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <FXPayment
          doc={{ id: "invoice", version: 2 } as Document}
          movement={
            { id: "movement", version: 3, currency: "EUR" } as BankMovement
          }
          canProcess={canProcess}
        />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
async function fill() {
  await waitFor(() => expect(api).toHaveBeenCalled());
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByRole("option", { name: /60.00 USD/ }));
  fireEvent.change(screen.getByLabelText(/Deckung in Rechnungswährung/), {
    target: { value: "60.00" },
  });
  fireEvent.change(screen.getByLabelText(/Rechnungsanteil in EUR/), {
    target: { value: "55.00" },
  });
  fireEvent.change(screen.getByLabelText(/Separat belegte Gebühr/), {
    target: { value: "1.00" },
  });
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue({ items: [evidence], issues: [] } as never);
  vi.mocked(post).mockImplementation(async (path) =>
    path.includes("preview")
      ? ({
          revision: "synthetic-revision",
          evidence,
          review_notes: ["Synthetic dates checked"],
          legs: [
            {
              amount: "60.00",
              invoice_currency: "USD",
              bank_principal: "55.00",
              fee: "1.00",
              bank_amount: "56.00",
              bank_currency: "EUR",
            },
          ],
        } as never)
      : ({} as never),
  );
});
it("requires a preview and explicit review; separates invoice amount, bank principal and fee", async () => {
  panel();
  expect(
    screen.queryByRole("button", { name: /ausdrücklich bestätigen/ }),
  ).not.toBeInTheDocument();
  await fill();
  expect(screen.getByText("Synthetic original text")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /vorschauen/ }));
  const button = await screen.findByRole("button", {
    name: /ausdrücklich bestätigen/,
  });
  expect(button).toBeDisabled();
  expect(screen.getByText(/Bankverbrauch: 56.00 EUR/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/Prüfbegründung/), {
    target: { value: "All synthetic sources checked" },
  });
  fireEvent.click(button);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      "reconciliation/fx-confirm/",
      expect.objectContaining({
        preview_revision: "synthetic-revision",
        bank_version: 3,
        idempotency_key: expect.any(String),
        legs: [
          {
            document_id: "invoice",
            document_version: 2,
            amount: "60.00",
            bank_principal: "55.00",
            fee: "1.00",
          },
        ],
      }),
    ),
  );
});
it("discards the displayed preview when amounts change", async () => {
  panel();
  await fill();
  fireEvent.click(screen.getByRole("button", { name: /vorschauen/ }));
  await screen.findByRole("button", { name: /ausdrücklich bestätigen/ });
  fireEvent.change(screen.getByLabelText(/Deckung in Rechnungswährung/), {
    target: { value: "30.00" },
  });
  expect(
    screen.queryByRole("button", { name: /ausdrücklich bestätigen/ }),
  ).not.toBeInTheDocument();
});
it("explains missing FX evidence rather than claiming the invoice was not paid", async () => {
  vi.mocked(api).mockResolvedValue({
    items: [],
    issues: [{ locator: "entry:0", reason: "Missing original rate" }],
  } as never);
  panel(false);
  expect(
    await screen.findByText(/FX-Beleg fehlt\/ist unklar/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /vorschauen/ })).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});
