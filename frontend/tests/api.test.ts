import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});
describe("gemeinsamer API-Client", () => {
  it("sendet CSRF und lässt Multipart-Grenzen vom Browser setzen", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ csrfToken: "csrf" }),
      })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ results: [] }) });
    vi.stubGlobal("fetch", fetch);
    const { api } = await import("../app/api");
    const body = new FormData();
    body.append("files", new File(["original"], "test.pdf"));
    await api("documents/", { method: "POST", body });
    const init = fetch.mock.calls[1][1];
    expect(init.credentials).toBe("same-origin");
    expect(init.headers.get("X-CSRFToken")).toBe("csrf");
    expect(init.headers.has("Content-Type")).toBe(false);
    expect(init.body).toBe(body);
  });
  it("reicht serverseitige Decimal-/Versionsfehler ohne automatischen Neuversuch weiter", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ csrfToken: "csrf" }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          error: "Versionskonflikt",
          details: { current_version: 7 },
        }),
      });
    vi.stubGlobal("fetch", fetch);
    const { post } = await import("../app/api");
    await expect(
      post("documents/id/", { gross: "120.00" }),
    ).rejects.toMatchObject({ status: 409, details: { current_version: 7 } });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][1].body).toBe('{"gross":"120.00"}');
  });
});
