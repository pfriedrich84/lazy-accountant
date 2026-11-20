import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { api, type Document } from "../app/api";
import DocumentDetail from "../app/routes/document";
import { documentFixture } from "./fixtures/document";

vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
}));
vi.mock("../app/routes/shell", () => ({
  useApp: () => ({
    companies: [{ id: 1, name: "Beispielfirma" }],
    period: "2026-10",
  }),
}));

function mount(doc: Document = documentFixture) {
  vi.mocked(api).mockImplementation(async (path, init) => {
    if (path.includes("/text/"))
      return { text: "Synthetische Rechnung", pages: 2 } as never;
    if (path.includes("/duplicates/")) return [] as never;
    if (path.startsWith("companies/"))
      return {
        categories: [],
        accounts: [],
        permissions: { process: true },
      } as never;
    if (init?.method === "PUT")
      return {
        ...doc,
        metadata: JSON.parse(String(init.body)).metadata,
        version: doc.version + 1,
      } as never;
    return doc as never;
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/documents/${doc.id}`]}>
        <Routes>
          <Route path="/documents/:documentId" element={<DocumentDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => vi.resetAllMocks());

it("prioritizes review and keeps management and audit details collapsed", async () => {
  mount();
  expect(
    await screen.findByRole("heading", {
      name: documentFixture.effective_name,
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Prüfung abschließen" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Dokument verwalten" }),
  ).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.getByRole("button", { name: "Ablage & Nachvollziehbarkeit" }),
  ).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.getByRole("button", { name: "Bankabgleich & Zahlungsstand" }),
  ).toHaveAttribute("aria-expanded", "false");
});

it("tracks edits, prevents revision-changing management actions, and saves the versioned payload", async () => {
  mount();
  const user = userEvent.setup();
  const issuer = await screen.findByLabelText("Aussteller / Lieferant");
  await user.clear(issuer);
  await user.type(issuer, "Korrigierter Lieferant");
  expect(screen.getByRole("status")).toHaveTextContent(
    "Ungespeicherte Änderungen",
  );
  await user.click(screen.getByRole("button", { name: "Dokument verwalten" }));
  expect(
    screen.getByRole("button", { name: "Namen manuell setzen" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Als Nichtbeleg ausschließen" }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "Zwischenstand speichern" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `documents/${documentFixture.id}/`,
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const call = vi
    .mocked(api)
    .mock.calls.find(([, init]) => init?.method === "PUT")!;
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    base_version: 3,
    approve: false,
    metadata: { issuer: "Korrigierter Lieferant" },
  });
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent(
      "Keine ungespeicherten Änderungen",
    ),
  );
});

it("keeps excluded documents read-only, including the persistent actions", async () => {
  mount({
    ...documentFixture,
    is_excluded: true,
    exclusion_reason: "Synthetischer Nichtbeleg",
  });
  await screen.findByRole("heading", { name: documentFixture.effective_name });
  const actions = within(
    screen.getByRole("region", { name: "Prüfung abschließen" }),
  );
  expect(
    actions.getByRole("button", { name: "Prüfen & freigeben" }),
  ).toBeDisabled();
  expect(
    actions.getByRole("button", { name: "Zwischenstand speichern" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("Aussteller / Lieferant")).toBeDisabled();
});

it("does not render the editor for a quarantined document", async () => {
  mount({ ...documentFixture, security_status: "infected" });
  expect(
    await screen.findByText(/Sicherheitssperre: infected/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Prüfung abschließen" }),
  ).not.toBeInTheDocument();
});
