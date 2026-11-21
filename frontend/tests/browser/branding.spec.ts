import { expect, test } from "@playwright/test";

// Isolated UI fixture: no real credentials, backend writes or customer data.
test("approved branding loads and keeps mobile company selection beside the menu", async ({ page }) => {
  let authenticated = false;
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem("company", "1");
    localStorage.setItem("period", "2026-10");
  });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown;
    if (path === "/api/auth/session/") data = authenticated ? { username: "Demo" } : null;
    else if (path === "/api/auth/csrf/") data = { csrfToken: "synthetic-branding-fixture" };
    else if (path === "/api/auth/login/") {
      authenticated = true;
      data = { username: "Demo" };
    } else if (path === "/api/companies/") {
      data = [{ id: 1, name: "Musterwerk GmbH mit einem langen Firmennamen (Demo)", folder: "Demo" }];
    } else if (path === "/api/folders/1/") {
      data = {
        folders: [], unfiled: { files: [], total: 0, ready: 0, open: 0 },
        summary: { total: 0, ready: 0, open: 0 }, total: 0, next_cursor: null,
      };
    } else {
      await route.fulfill({ status: 404, json: { error: `Unexpected fixture API: ${path}` } });
      return;
    }
    await route.fulfill({ json: data });
  });

  await page.goto("/months");
  const loginLogo = page.getByRole("img", { name: "Lazy Accountant" });
  await expect(loginLogo).toBeVisible();
  await expect.poll(() => loginLogo.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  const favicon = page.locator('link[rel="icon"]');
  await expect(favicon).toHaveAttribute("type", "image/svg+xml");
  await expect(favicon).toHaveAttribute("href", /.+/);
  await page.getByLabel("Benutzername").fill("synthetic-demo");
  await page.getByLabel("Passwort").fill("synthetic-local-fixture-only");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Monatsablage", exact: true })).toBeVisible();

  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    const menu = page.getByRole("button", { name: "Menü öffnen" });
    const company = page.getByRole("combobox", { name: "Firma", exact: true });
    const menuBox = await menu.boundingBox();
    const companyBox = await company.boundingBox();
    expect(menuBox).not.toBeNull();
    expect(companyBox).not.toBeNull();
    expect(Math.abs(companyBox!.y - menuBox!.y)).toBeLessThan(20);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Menü öffnen" }).click();
  await expect(page.getByRole("img", { name: "Lazy Accountant" }).last()).toBeVisible();
  await page.getByRole("link", { name: "Monatsablage", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Firma", exact: true })).toBeVisible();

  await page.setViewportSize({ width: 1440, height: 1000 });
  const sidebarLogo = page.getByRole("img", { name: "Lazy Accountant" });
  await expect(sidebarLogo).toBeVisible();
  await expect.poll(() => sidebarLogo.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  expect(errors).toEqual([]);
});
