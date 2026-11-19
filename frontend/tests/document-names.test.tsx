import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, post, APIError, type Document } from "../app/api";
import { DocumentName, NamePreview } from "../app/document-names";

vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const doc = {
  id: "test-id",
  version: 7,
  original_name: "Rechnung_1.pdf",
  handover_name: "2026-10-31 HoT Rechnung 123.pdf",
  effective_name: "2026-10-31 HoT Rechnung 123.pdf",
  proposed_name: "2026-10-31 HoT Rechnung 123.pdf",
  name_source: "generated",
  name_warning: "",
  name_conflict: false,
} as Document;

function mount(component: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>,
  );
}

beforeEach(() => vi.resetAllMocks());

describe("Übergabenamen", () => {
  it("zeigt Original und Vorschlag getrennt und setzt manuelle Namen mit Ausgangsversion", async () => {
    vi.mocked(api).mockResolvedValue(doc);
    mount(<DocumentName doc={doc} />);
    expect(
      screen.getByText("Originalname: Rechnung_1.pdf"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(`Vorschlag: ${doc.proposed_name}`),
    ).toBeInTheDocument();
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText("Manueller Übergabename"));
    await user.type(
      screen.getByLabelText("Manueller Übergabename"),
      "Manuell.pdf",
    );
    await user.click(
      screen.getByRole("button", { name: "Namen manuell setzen" }),
    );
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("documents/test-id/name/", {
        method: "PATCH",
        body: JSON.stringify({ base_version: 7, name: "Manuell.pdf" }),
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Generator übernehmen" }),
    );
    await waitFor(() =>
      expect(api).toHaveBeenLastCalledWith("documents/test-id/name/", {
        method: "PATCH",
        body: JSON.stringify({ base_version: 7, name: null }),
      }),
    );
  });

  it("schreibt beim Vorschauen nichts und übernimmt erst nach ausdrücklichem Klick", async () => {
    vi.mocked(post)
      .mockResolvedValueOnce([
        {
          document_id: doc.id,
          base_version: 7,
          original_name: doc.original_name,
          old_name: "Alt.pdf",
          new_name: "Geschützt.pdf",
          name_source: "manual",
          warning: "",
          conflict: true,
          manual_protected: true,
        },
      ])
      .mockResolvedValueOnce([]);
    mount(<NamePreview documents={[doc]} />);
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Übergabenamen vorschauen" }),
    );
    expect(await screen.findByText("Neu: Geschützt.pdf")).toBeInTheDocument();
    expect(screen.getByText(/manuell geschützt/)).toBeInTheDocument();
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("document-names/preview/", {
      document_ids: [doc.id],
    });
    await user.click(
      screen.getByRole("button", {
        name: "Namen jetzt versioniert übernehmen",
      }),
    );
    await waitFor(() =>
      expect(post).toHaveBeenLastCalledWith("document-names/backfill/", {
        entries: [{ document_id: doc.id, base_version: 7 }],
      }),
    );
  });

  it("zeigt Versionskonflikte ohne blinden Retry", async () => {
    vi.mocked(api).mockRejectedValue(new APIError("Vorschau neu laden", 409));
    mount(<DocumentName doc={doc} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Namen manuell setzen" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Vorschau neu laden",
    );
    expect(api).toHaveBeenCalledTimes(1);
  });
});
