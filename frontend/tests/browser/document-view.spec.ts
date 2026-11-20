import { expect, test, type Page } from "@playwright/test";
import { documentFixture } from "../fixtures/document";

const company = { id: 1, name: "Beispielfirma (synthetisch)" };

async function fixture(page: Page, overrides = {}) {
  let doc = { ...documentFixture, ...overrides };
  const writes: Record<string, unknown>[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    let data: unknown = [];
    if (url.pathname.endsWith("/page/")) {
      await route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123"><rect width="794" height="1123" fill="white"/><g font-family="sans-serif" fill="#213c34"><text x="60" y="80" font-size="15">SYNTHETISCHER TESTBELEG</text><text x="60" y="200" font-size="30">Rechnung TEST-1042</text><text x="60" y="280" font-size="20">Musterlieferant · 15.10.2026</text><text x="60" y="420" font-size="24">Gesamtbetrag: 120,00 EUR</text></g></svg>',
      });
      return;
    }
    if (url.pathname.endsWith("/auth/session/"))
      data = { username: "Synthetischer Test" };
    else if (url.pathname.endsWith("/auth/csrf/"))
      data = { csrfToken: "synthetic-test-token" };
    else if (url.pathname === "/api/companies/") data = [company];
    else if (url.pathname === "/api/companies/1/")
      data = {
        company,
        categories: [],
        accounts: [],
        permissions: { process: true },
      };
    else if (url.pathname.endsWith("/text/"))
      data = { text: "Synthetischer Testbeleg", pages: 2 };
    else if (url.pathname.endsWith("/duplicates/")) data = [];
    else if (url.pathname === `/api/documents/${doc.id}/`) {
      if (request.method() === "PUT") {
        const payload = request.postDataJSON();
        writes.push(payload);
        doc = { ...doc, ...payload, version: doc.version + 1 };
      }
      data = doc;
    } else if (url.pathname.endsWith("/transactions/"))
      data = { items: [], next_cursor: null };
    else if (url.pathname.endsWith("/status/"))
      data = {
        status: "unpaid",
        allocations: [],
        paid: "0",
        remaining: "120.00",
      };
    await route.fulfill({ json: data });
  });
  await page.goto(`/documents/${doc.id}`);
  return writes;
}

async function selectView(page: Page, name: "Original" | "Prüfdaten") {
  const tab = page.getByRole("tab", { name, exact: true });
  if (await tab.isVisible()) await tab.click();
}

test("review workspace is responsive, zoomable and retains edits across views", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const writes = await fixture(page);
  await expect(
    page.getByRole("heading", { name: documentFixture.effective_name }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Dokument verwalten", exact: true }),
  ).toHaveAttribute("aria-expanded", "false");
  const actions = page.getByRole("region", { name: "Prüfung abschließen" });
  await expect(
    actions.getByRole("button", { name: "Prüfen & freigeben" }),
  ).toBeInViewport();
  await page.screenshot({
    path: info.outputPath("review.png"),
    fullPage: false,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);

  await page
    .getByLabel("Aussteller / Lieferant", { exact: true })
    .fill("Korrigierter Lieferant");
  await expect(page.getByRole("status")).toHaveText(
    "Ungespeicherte Änderungen",
  );
  await selectView(page, "Original");
  await expect(
    page.getByRole("link", { name: "Original öffnen", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Vergrößern", exact: true }).click();
  await expect(page.getByText("125%", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await expect(page.getByAltText(/^Originalseite 2/)).toBeVisible();
  await page.getByRole("button", { name: "Einpassen", exact: true }).click();
  await expect(page.getByText("100%", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await selectView(page, "Prüfdaten");
  await expect(
    page.getByLabel("Aussteller / Lieferant", { exact: true }),
  ).toHaveValue("Korrigierter Lieferant");
  await page
    .getByRole("button", { name: "Dokument verwalten", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Namen manuell setzen", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", {
      name: "Als Nichtbeleg ausschließen",
      exact: true,
    }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Ablage & Nachvollziehbarkeit", exact: true })
    .click();
  await expect(
    actions.getByRole("button", {
      name: "Zwischenstand speichern",
      exact: true,
    }),
  ).toBeInViewport();
  await actions
    .getByRole("button", { name: "Zwischenstand speichern", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Keine ungespeicherten Änderungen",
  );
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    base_version: 3,
    approve: false,
    metadata: { issuer: "Korrigierter Lieferant" },
  });
  expect(errors).toEqual([]);
});

test("excluded originals remain viewable but cannot be approved", async ({
  page,
}) => {
  await fixture(page, {
    is_excluded: true,
    exclusion_reason: "Synthetischer Nichtbeleg",
  });
  await expect(
    page.getByText("Als Nichtbeleg ausgeschlossen", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Prüfen & freigeben", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByLabel("Aussteller / Lieferant", { exact: true }),
  ).toBeDisabled();
  await selectView(page, "Original");
  await expect(
    page.getByRole("link", { name: "Original öffnen", exact: true }),
  ).toBeVisible();
});

test("bank period confirmation and advanced fields remain available", async ({
  page,
}) => {
  await fixture(page, {
    kind: "bank_pdf",
    metadata: { period_start: "2026-09-01", period_end: "2026-10-31" },
  });
  await expect(page.getByLabel("Auszugsbeginn", { exact: true })).toHaveValue(
    "2026-09-01",
  );
  await expect(
    page.getByLabel(
      "Zuordnung zum gewählten Übergabemonat ausdrücklich bestätigt",
    ),
  ).not.toBeChecked();
  await page
    .getByLabel("Zuordnung zum gewählten Übergabemonat ausdrücklich bestätigt")
    .check();
  await page
    .getByRole("button", {
      name: "Weitere Angaben & Verknüpfungen",
      exact: true,
    })
    .click();
  await expect(
    page.getByLabel("Steueraufteilungen (JSON: rate, net, tax als Strings)", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Dublette von (Dokument-ID)", { exact: true }),
  ).toBeVisible();
});

test("quarantine never exposes editing or approval controls", async ({
  page,
}) => {
  await fixture(page, { security_status: "infected" });
  await expect(page.getByText(/Sicherheitssperre: infected/)).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Prüfung abschließen" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Original öffnen", exact: true }),
  ).toHaveCount(0);
});
