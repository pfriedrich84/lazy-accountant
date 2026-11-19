import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { APIError, type Document, api, post } from "../app/api";
import { DocumentExclusion } from "../app/document-exclusion";

vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
  post: vi.fn(),
  idempotencyKey: () => "stable-dialog-key",
}));
const doc = {
  id: "doc-1",
  company_id: null,
  version: 2,
  is_excluded: false,
} as Document;
function setup(value = doc) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidated = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DocumentExclusion doc={value} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), invalidated };
}
beforeEach(() => vi.resetAllMocks());

describe("reversible Nichtbeleg-Aktion", () => {
  it("benötigt einen Grund, wiederholt Netzwerkfehler mit demselben Payload und lädt aktuellen Zustand", async () => {
    vi.mocked(post)
      .mockRejectedValueOnce(new TypeError("network lost"))
      .mockResolvedValueOnce({ document: doc, changed: true });
    const { user, invalidated } = setup();
    await user.click(
      screen.getByRole("button", { name: "Als Nichtbeleg ausschließen" }),
    );
    const submit = screen
      .getAllByRole("button", { name: "Als Nichtbeleg ausschließen" })
      .at(-1)!;
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Begründung"), "  Signatur  ");
    await user.click(submit);
    await screen.findByText("network lost");
    expect(screen.getByLabelText("Begründung")).toBeDisabled();
    await user.click(
      screen.getByRole("button", { name: "Identischen Auftrag wiederholen" }),
    );
    await waitFor(() => expect(invalidated).toHaveBeenCalled());
    expect(post).toHaveBeenCalledTimes(2);
    expect(vi.mocked(post).mock.calls[0]).toEqual(
      vi.mocked(post).mock.calls[1],
    );
    expect(vi.mocked(post).mock.calls[0]).toEqual([
      "documents/doc-1/exclude/",
      {
        base_version: 2,
        reason: "Signatur",
        idempotency_key: "stable-dialog-key",
      },
    ]);
  });
  it("erlaubt keinen blinden Retry nach Versionskonflikt", async () => {
    vi.mocked(post).mockRejectedValue(new APIError("Versionskonflikt", 409));
    const { user } = setup();
    await user.click(
      screen.getByRole("button", { name: "Als Nichtbeleg ausschließen" }),
    );
    await user.type(screen.getByLabelText("Begründung"), "Grund");
    await user.click(
      screen
        .getAllByRole("button", { name: "Als Nichtbeleg ausschließen" })
        .at(-1)!,
    );
    await screen.findByText(/Auftrag nicht blind wiederholen/);
    expect(
      screen.getByRole("button", { name: "Identischen Auftrag wiederholen" }),
    ).toBeDisabled();
  });
  it("zeigt Ausschluss und eingefrorenen Paketbezug ohne HTML-Ausführung", () => {
    setup({
      ...doc,
      is_excluded: true,
      exclusion_reason: "<b>kein HTML</b>",
      packaged_in: [{ id: "p", version: 1, revision: 1 }],
    });
    expect(screen.getByText(/<b>kein HTML<\/b>/)).toBeVisible();
    expect(screen.getByText(/Ausschluss verändert diese Pakete/)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Wiederherstellen" }),
    ).toBeEnabled();
  });
  it("deaktiviert Aktion ohne process-Recht der Firma", async () => {
    vi.mocked(api).mockResolvedValue({ permissions: { process: false } });
    setup({ ...doc, company_id: 1 });
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(
      screen.getByRole("button", { name: "Als Nichtbeleg ausschließen" }),
    ).toBeDisabled();
  });
});
