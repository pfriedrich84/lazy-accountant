import { expect, test } from "@playwright/test";

test("Zahlungslisten filtern firmenweit über echte REST-Antworten", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page
    .getByLabel("Benutzername")
    .fill(process.env.ADMIN_USERNAME || "admin");
  await page
    .getByLabel(/^Passwort/)
    .fill(process.env.ADMIN_PASSWORD || "synthetic-test-password");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Bereit für den Monatsabschluss?" }),
  ).toBeVisible();
  const initial = page.waitForResponse((r) =>
    r.url().includes("/api/reconciliation/invoices/"),
  );
  const policy = page.waitForResponse((r) =>
    r.url().includes("/api/reconciliation/policy/"),
  );
  const accountState = page.waitForResponse((r) =>
    r.url().includes("/api/reconciliation/accounts/"),
  );
  await page.goto("/payments");
  expect((await initial).ok()).toBe(true);
  expect((await (await policy).json()).rule_version).toBe(
    "exact-reference-known-iban-v1",
  );
  expect(Array.isArray((await (await accountState).json()).items)).toBe(true);
  await expect(
    page.getByRole("heading", {
      name: "Automatikpolicy der Firma",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Firmenweiter Filter", exact: true })
    .click();
  const overdue = page.waitForResponse((r) => {
    const url = new URL(r.url());
    return (
      url.pathname.endsWith("/reconciliation/invoices/") &&
      url.searchParams.get("state") === "overdue"
    );
  });
  await page.getByRole("option", { name: "Überfällig", exact: true }).click();
  const invoiceResult = await (await overdue).json();
  expect(invoiceResult.filters.state).toBe("overdue");
  expect(
    invoiceResult.items.every(
      (row: { overdue: boolean | null }) => row.overdue === true,
    ),
  ).toBe(true);
  await page
    .getByRole("textbox", { name: "Firmenweit suchen" })
    .fill("synthetic-no-such-invoice-filter-91827");
  const search = page.waitForResponse(
    (r) =>
      new URL(r.url()).searchParams.get("search") ===
      "synthetic-no-such-invoice-filter-91827",
  );
  await page.getByRole("button", { name: "Suchen", exact: true }).click();
  expect((await (await search).json()).items).toEqual([]);
  await expect(page.getByText("Keine Einträge vorhanden.")).toBeVisible();
  await page.getByRole("combobox", { name: "Ansicht", exact: true }).click();
  const bank = page.waitForResponse((r) =>
    r.url().includes("/api/reconciliation/transactions/"),
  );
  await page
    .getByRole("option", {
      name: "Bankbewegungen / fehlende Zuordnung",
      exact: true,
    })
    .click();
  expect((await (await bank).json()).filters.state).toBe("all");
  await page
    .getByRole("combobox", { name: "Firmenweiter Filter", exact: true })
    .click();
  const review = page.waitForResponse((r) => {
    const url = new URL(r.url());
    return (
      url.pathname.endsWith("/reconciliation/transactions/") &&
      url.searchParams.get("state") === "review"
    );
  });
  await page.getByRole("option", { name: "Zur Prüfung", exact: true }).click();
  expect((await (await review).json()).filters.state).toBe("review");
  expect(errors).toEqual([]);
});
