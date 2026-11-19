import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});
describe("Idempotenzschlüssel auf LAN-HTTP", () => {
  it("verwendet randomUUID, wenn die sichere Kontext-API verfügbar ist", async () => {
    const randomUUID = vi.fn(() => "12345678-1234-4234-8234-123456789abc");
    vi.stubGlobal("crypto", { randomUUID });
    const { idempotencyKey } = await import("../app/api");
    expect(idempotencyKey()).toBe("12345678-1234-4234-8234-123456789abc");
    expect(randomUUID).toHaveBeenCalledTimes(1);
  });
  it("erzeugt ohne randomUUID eine kryptografische UUID v4 mit korrekten Variantenbits", async () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => bytes.fill(255));
    vi.stubGlobal("crypto", { getRandomValues });
    const { idempotencyKey } = await import("../app/api");
    expect(idempotencyKey()).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
    expect(getRandomValues).toHaveBeenCalledTimes(1);
    expect(getRandomValues.mock.calls[0][0]).toHaveLength(16);
  });
  it("verwendet bei fehlender Kryptografie keine unsicheren Zufallszahlen", async () => {
    vi.stubGlobal("crypto", undefined);
    const { idempotencyKey } = await import("../app/api");
    expect(() => idempotencyKey()).toThrow("keine sichere Zufallsquelle");
  });
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
