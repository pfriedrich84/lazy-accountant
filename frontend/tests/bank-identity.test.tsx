import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { BankIdentityPanel } from "../app/bank-identity";
import { api, post } from "../app/api";
import type { BankMovement } from "../app/payments";

vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));
let canProcess = true;
let eligible = true;
const movement = {
  id: "observation",
  version: 1,
  bank_reference: "",
  issues: ["Identität ungeklärt"],
  sources: [],
} as unknown as BankMovement;
const preview = {
  duplicate_id: "observation",
  canonical_id: "canonical",
  duplicate_version: 1,
  canonical_version: 4,
  document_versions: { "source-1": 2, "source-2": 3 },
  can_merge: true,
  blockers: [],
  criteria: ["Bank-TxId und Gegenkonto stimmen überein"],
};
function app(value = movement) {
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <BankIdentityPanel movement={value} companyId={1} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
async function selectTarget() {
  fireEvent.click(
    screen.getByRole("button", { name: "Umsatzidentität prüfen" }),
  );
  fireEvent.mouseDown(
    await screen.findByRole("combobox", { name: "Kanonische Bankbewegung" }),
  );
  fireEvent.click(screen.getByRole("option", { name: /SYNTH-BANK/ }));
}
beforeEach(() => {
  canProcess = true;
  eligible = true;
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith("companies/"))
      return { permissions: { read: true, process: canProcess } } as never;
    if (path.includes("identity-candidates"))
      return { items: [{ ...preview, bank_reference: "SYNTH-BANK" }] } as never;
    return {
      ...preview,
      can_merge: eligible,
      blockers: eligible ? [] : ["Buchungsdaten widersprechen sich"],
    } as never;
  });
  vi.mocked(post).mockResolvedValue({} as never);
});

it("schreibt nie beim Lesen und zeigt belegte Vorschau statt Betragssicherheit", async () => {
  app();
  expect(api).not.toHaveBeenCalled();
  await selectTarget();
  expect(
    await screen.findByText(/Bank-TxId und Gegenkonto stimmen überein/),
  ).toBeInTheDocument();
  const button = screen.getByRole("button", {
    name: "Identitätszusammenführung bestätigen",
  });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Begründung zur Umsatzidentität"), {
    target: { value: "Originale geprüft" },
  });
  fireEvent.click(button);
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(vi.mocked(post).mock.calls[0]).toEqual([
    "reconciliation/identity-merge/",
    expect.objectContaining({
      duplicate_id: "observation",
      canonical_id: "canonical",
      duplicate_version: 1,
      canonical_version: 4,
      document_versions: { "source-1": 2, "source-2": 3 },
      reason: "Originale geprüft",
    }),
  ]);
  expect(
    await screen.findByText(
      "Identitätsentscheidung gespeichert. Keine Zahlung erzeugt oder gelöscht.",
    ),
  ).toBeInTheDocument();
});

it("behält Idempotenzschlüssel und Vorschauversionen nach unbekanntem Netzwerkfehler", async () => {
  vi.mocked(post).mockRejectedValue(new Error("Netzwerk unbekannt"));
  app();
  await selectTarget();
  fireEvent.change(
    await screen.findByLabelText("Begründung zur Umsatzidentität"),
    { target: { value: "Originale geprüft" } },
  );
  const button = screen.getByRole("button", {
    name: "Identitätszusammenführung bestätigen",
  });
  fireEvent.click(button);
  await screen.findByText("Netzwerk unbekannt");
  fireEvent.click(button);
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(vi.mocked(post).mock.calls[0]).toEqual(vi.mocked(post).mock.calls[1]);
});

it("bietet bei Widerspruch oder fehlendem Schreibscope keine Bestätigung an", async () => {
  eligible = false;
  app();
  await selectTarget();
  await screen.findByText("Buchungsdaten widersprechen sich");
  expect(
    screen.queryByRole("button", {
      name: "Identitätszusammenführung bestätigen",
    }),
  ).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it("dokumentiert Beanstandung ohne Betrag erneut freizugeben", async () => {
  app({
    ...movement,
    version: 2,
    merged_into_id: "canonical",
    canonical_version: 5,
    identity_resolution: {
      id: 1,
      actor_id: 1,
      created_at: "2026-10-15",
      reason: "Originale geprüft",
      disputed_at: null,
      dispute_reason: "",
    },
  });
  expect(screen.getByText(/Nicht erneut verbrauchbar/)).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Identitätsentscheidung prüfen" }),
  );
  fireEvent.change(
    await screen.findByLabelText("Begründung zur Identitätsbeanstandung"),
    { target: { value: "Bezug widersprüchlich" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Zusammenführung beanstanden" }),
  );
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(vi.mocked(post).mock.calls[0]).toEqual([
    "reconciliation/identity-dispute/",
    expect.objectContaining({
      duplicate_id: "observation",
      duplicate_version: 2,
      canonical_version: 5,
      reason: "Bezug widersprüchlich",
    }),
  ]);
});

it("lässt readonly Vorschau lesen, aber nicht schreiben", async () => {
  canProcess = false;
  app();
  await selectTarget();
  await screen.findByText(/Bank-TxId und Gegenkonto stimmen überein/);
  expect(
    screen.queryByRole("button", {
      name: "Identitätszusammenführung bestätigen",
    }),
  ).not.toBeInTheDocument();
});
