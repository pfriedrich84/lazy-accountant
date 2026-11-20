import { expect, test } from "@playwright/test";

// Synthetic fixtures only: this UI regression never reads production documents.
test("Monatsablage: vollständige Zahlen, Nachladen und offene Prüfungen", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const documents = Array.from({ length: 105 }, (_, index) => ({
    id: `month-document-${index}`,
    effective_name: `2026-10-15 Testbank Ausschüttung TEST${index}.pdf`,
    original_name: `ORIGINAL_${index}.pdf`,
    name_source: index === 0 ? "manual" : "generated",
    kind: "security_pdf",
    status: index < 101 ? "ready" : "review",
    metadata: {
      bank_short_name: "Testbank",
      subtype: "Ausschüttung",
      date: "2026-10-15",
      isin: `TEST${index}`,
    },
  }));
  documents[0].effective_name = `${"Langer-manueller-Name-".repeat(8)}.pdf`;
  await page.addInitScript(() => {
    localStorage.setItem("company", "1");
    localStorage.setItem("period", "2026-10");
  });
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let data: unknown;
    if (url.pathname === "/api/auth/session/") data = { username: "UI-Test" };
    else if (url.pathname === "/api/companies/")
      data = [{ id: 1, name: "Testfirma", folder: "Testfirma" }];
    else if (url.pathname === "/api/folders/1/") {
      const empty = url.searchParams.get("period") === "2026-11";
      const open = url.searchParams.get("status") === "open";
      const all = empty ? [] : documents;
      const matching = open
        ? all.filter((doc) => doc.status === "review")
        : all;
      const offset = Number(url.searchParams.get("cursor") || "0");
      const counts = {
        total: all.length,
        ready: empty ? 0 : 101,
        open: empty ? 0 : 4,
      };
      data = {
        folders: [
          {
            name: "Wertpapiere",
            path: `Testfirma/${empty ? "2026/11" : "2026/10"}/Wertpapiere/`,
            ...counts,
            files: matching.slice(offset, offset + 100),
          },
          {
            name: "ER",
            path: "Testfirma/2026/10/ER/",
            total: 0,
            ready: 0,
            open: 0,
            files: [],
          },
        ],
        unfiled: { files: [], total: 0, ready: 0, open: 0 },
        summary: counts,
        total: matching.length,
        next_cursor: matching.length > offset + 100 ? "100" : null,
      };
    } else {
      await route.fulfill({
        status: 404,
        json: { error: `Unexpected fixture API: ${url.pathname}` },
      });
      return;
    }
    await route.fulfill({ json: data });
  });

  await page.goto("/months");
  await expect(
    page.getByRole("heading", { name: "Monatsablage", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByText("105 Dokumente · 101 geprüft · 4 zu prüfen", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("100 von 105 Dokumenten angezeigt", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/^Original:/)).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Wertpapiere", level: 2 }),
  ).toBeVisible();
  await expect(
    page.getByText("/Testfirma/2026/10/Wertpapiere/", { exact: true }),
  ).not.toBeVisible();
  await page.getByText("Ablagepfad anzeigen", { exact: true }).first().click();
  await expect(
    page.getByText("/Testfirma/2026/10/Wertpapiere/", { exact: true }),
  ).toBeVisible();
  await page.getByText("Ablagepfad anzeigen", { exact: true }).first().click();

  // Includes a very long manual name. Check actual DOM geometry, not just the viewport setting.
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("months-archive.png"),
    fullPage: false,
  });
  await page
    .getByRole("button", { name: "Weitere Dokumente laden", exact: true })
    .click();
  await expect(
    page.getByText("105 von 105 Dokumenten angezeigt", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Weitere Dokumente laden", exact: true }),
  ).toHaveCount(0);

  await page
    .getByRole("button", { name: "Zu prüfen (4)", exact: true })
    .click();
  await expect(
    page.getByText("4 von 4 offenen Dokumenten angezeigt", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "ER", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("main li")).toHaveCount(4);
  await expect(
    page.getByText("105 Dokumente · 101 geprüft · 4 zu prüfen", {
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("months-open.png"),
    fullPage: true,
  });

  if (info.project.name === "desktop") {
    for (const width of [1600, 768, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
    }
  }

  // Native details can be operated without a mouse.
  const pathToggle = page.getByText("Ablagepfad anzeigen", { exact: true });
  await pathToggle.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("/Testfirma/2026/10/Wertpapiere/", { exact: true }),
  ).toBeVisible();

  await page.getByLabel("Übergabemonat", { exact: true }).fill("2026-11");
  await expect(
    page.getByText("Für diesen Monat sind noch keine Dokumente zugeordnet.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Alle zugeordneten Dokumente sind geprüft.", {
      exact: true,
    }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});
