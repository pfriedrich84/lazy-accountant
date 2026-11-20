import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

// localhost is a secure context even on HTTP: reproduce the API missing on LAN HTTP.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.crypto, "randomUUID", {
      value: undefined,
      configurable: true,
    });
  });
});

async function navigate(page: Page, title: string) {
  const item = page.getByRole("link", { name: title, exact: true });
  if (!(await item.first().isVisible()))
    await page.getByRole("button", { name: "Menü öffnen" }).click();
  await page
    .getByRole("link", { name: title, exact: true })
    .filter({ visible: true })
    .click();
}

async function inspectOriginal(page: Page, name: string) {
  await page
    .getByRole("button", { name: "Dokument verwalten", exact: true })
    .click();
  await expect(
    page.getByText(`Originalname: ${name}`, { exact: true }),
  ).toBeVisible();
  const originalTab = page.getByRole("tab", { name: "Original", exact: true });
  if (await originalTab.isVisible()) await originalTab.click();
  await expect(page.getByRole("link", { name: "Original öffnen" })).toBeVisible(
    { timeout: 90_000 },
  );
  const dataTab = page.getByRole("tab", { name: "Prüfdaten", exact: true });
  if (await dataTab.isVisible()) await dataTab.click();
}

async function login(page: Page) {
  await page.goto("/");
  expect(await page.evaluate(() => typeof window.crypto.randomUUID)).toBe(
    "undefined",
  );
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
}

test("Firma anlegen → PDF hochladen → prüfen → Paket herunterladen", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await navigate(page, "Einstellungen");
  await page
    .getByRole("button", { name: "+ Firma anlegen", exact: true })
    .click();
  const company = `Browser Test ${info.project.name} ${Date.now()}`;
  await page.getByLabel("Firmenname", { exact: true }).fill(company);
  await page
    .getByRole("button", { name: "Firma speichern", exact: true })
    .click();
  await expect(page.getByLabel("Anzeigename")).toHaveValue(company);
  await page.getByLabel("Steuerberater-Empfänger").fill("kanzlei@example.test");
  await page.getByRole("button", { name: "Firmendaten speichern" }).click();
  await expect(page.getByText("Firmendaten gespeichert.")).toBeVisible();
  await page.getByRole("tab", { name: "Konten & Kategorien" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Testkonto");
  await page
    .getByLabel("IBAN / Depotkennung", { exact: true })
    .fill("AT611904300234573201");
  await page
    .getByRole("button", { name: "Hinzufügen", exact: true })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Testkonto bearbeiten", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByLabel("Name", { exact: true })
    .fill("Geschäftskonto");
  await page
    .getByRole("button", { name: "Änderungen speichern", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Geschäftskonto bearbeiten",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("Neue Kategorie", { exact: true }).fill("Office");
  await page
    .getByRole("button", { name: "Hinzufügen", exact: true })
    .last()
    .click();
  await page
    .getByRole("button", { name: "Office bearbeiten", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByLabel("Name", { exact: true })
    .fill("Büro");
  await page
    .getByRole("button", { name: "Änderungen speichern", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Büro bearbeiten", exact: true }),
  ).toBeVisible();
  await navigate(page, "Dokumenteingang");
  await page.getByLabel("Eingang", { exact: true }).click();
  await page
    .getByRole("option", { name: "Firma ungeklärt", exact: true })
    .click();
  await page
    .getByLabel("Dokumentdateien")
    .setInputFiles(path.resolve("../var/samples/eingang.pdf"));
  await expect(page.getByText(/1 Datei\(en\) übernommen/)).toBeVisible();
  await expect(page.getByText(/^Original:/)).toHaveCount(0);
  await page
    .getByRole("row")
    .filter({
      has: page.getByRole("link", { name: /^eingang-[a-f0-9]+\.pdf$/ }),
    })
    .getByRole("link")
    .click();
  await inspectOriginal(page, "eingang.pdf");
  await expect(
    page.getByRole("heading", { name: /^eingang-[a-f0-9]+\.pdf$/ }),
  ).toBeVisible();
  const documentCompany = page
    .getByRole("main")
    .getByLabel("Firma", { exact: true });
  await expect(documentCompany).toHaveText("Ungeklärt");
  await documentCompany.click();
  await page.getByRole("option", { name: company, exact: true }).click();
  await page.getByLabel("Dokumentart", { exact: true }).click();
  await page
    .getByRole("option", { name: "Eingangsrechnung", exact: true })
    .click();
  await page
    .getByLabel("Übergabemonat", { exact: true })
    .last()
    .fill("2026-10");
  await page
    .getByLabel("Aussteller / Lieferant")
    .fill("Synthetischer Lieferant");
  await page.getByLabel("Empfänger / Kunde").fill(company);
  await page.getByLabel("Kategorie", { exact: true }).click();
  await page.getByRole("option", { name: "Büro", exact: true }).click();
  await page.getByLabel("Belegnummer", { exact: true }).fill("BROWSER-1");
  await page.getByLabel("Belegdatum", { exact: true }).fill("2026-10-15");
  await page.getByLabel("Netto (z. B. 100.00)").fill("100.00");
  await page.getByLabel("Steuer (z. B. 20.00)").fill("20.00");
  await page.getByLabel("Brutto (z. B. 120.00)").fill("120.00");
  await page.getByLabel("Währung (ISO, z. B. EUR)").fill("EUR");
  await page.getByRole("button", { name: "Prüfen & freigeben" }).click();
  await expect(page.getByText("Geprüft", { exact: true })).toBeVisible();
  await expect(page.locator(".preview-page")).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".preview-page")
        .evaluate((im: HTMLImageElement) => im.naturalWidth),
    )
    .toBeGreaterThan(0);
  await page.screenshot({ path: info.outputPath("pruefung.png") });
  await page
    .getByLabel("Übergabemonat", { exact: true })
    .first()
    .fill("2026-10");
  await navigate(page, "Übergabe & Versand");
  await page
    .getByRole("button", { name: "Vorschau erstellen", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Paketvorschau", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/1 Originale/)).toBeVisible();
  await page
    .getByRole("button", { name: "Paket verbindlich erzeugen" })
    .click();
  await expect(
    page.getByRole("link", { name: "ZIP herunterladen" }),
  ).toBeVisible({ timeout: 45_000 });
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "ZIP herunterladen" }).click();
  expect((await download).suggestedFilename()).toMatch(/paket-v\d+\.zip/);
  await page.screenshot({
    path: info.outputPath("uebergabe.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("Zwei vollständige Firmenmonate mit allen Dokumentarten über die Oberfläche", async ({
  page,
}, info) => {
  test.skip(
    info.project.name !== "desktop",
    "Der mobile zentrale Ablauf wird separat geprüft.",
  );
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  const files = [
    ["ausgang.pdf", "Ausgangsrechnung"],
    ["eingang.pdf", "Eingangsrechnung"],
    ["gutschrift.pdf", "Eingangsgutschrift"],
    ["storno.pdf", "Ausgangsstorno"],
    ["konto.pdf", "Kontoauszug PDF"],
    ["konto.xml", "Kontoauszug CAMT"],
    ["wertpapiere.pdf", "Wertpapierunterlage"],
    ["scan.png", "Sonstiger Beleg"],
  ];
  for (const [company, folder] of [
    ["Beispiel GmbH", ""],
    ["Zweite Firma", "Zweite-Firma"],
  ]) {
    await navigate(page, "Übersicht");
    await page.getByLabel("Firma", { exact: true }).click();
    await page.getByRole("option", { name: company, exact: true }).click();
    await page.getByLabel("Übergabemonat", { exact: true }).fill("2026-10");
    await navigate(page, "Dokumenteingang");
    await page
      .getByLabel("Dokumentdateien")
      .setInputFiles(
        files.map(([name]) => path.resolve("../var/samples", folder, name)),
      );
    await expect(page.getByText(/8 Datei\(en\) übernommen/)).toBeVisible();
    let bankPdfId = "";
    for (const [index, [name, kind]] of files.entries()) {
      await page
        .getByRole("row")
        .filter({
          has: page.getByRole("link", {
            name: new RegExp(
              `^${name.slice(0, name.lastIndexOf("."))}-[a-f0-9]+\\.${name.slice(name.lastIndexOf(".") + 1)}$`,
            ),
          }),
        })
        .getByRole("link")
        .click();
      await inspectOriginal(page, name);
      await page.getByLabel("Dokumentart", { exact: true }).click();
      await page.getByRole("option", { name: kind, exact: true }).click();
      await page
        .getByLabel("Übergabemonat", { exact: true })
        .last()
        .fill("2026-10");
      if (index >= 4 && index <= 6) {
        await page
          .getByLabel(index === 6 ? "Depot" : "Bankkonto", { exact: true })
          .click();
        await page
          .getByRole("option", {
            name: index === 6 ? /Geschäftsdepot/ : /Geschäftskonto/,
          })
          .click();
        await page
          .getByLabel("Auszugsbeginn", { exact: true })
          .fill("2026-10-01");
        await page
          .getByLabel("Auszugsende", { exact: true })
          .fill("2026-10-28");
        if (index === 4) bankPdfId = page.url().split("/").at(-1) || "";
        if (index === 5) {
          await page
            .getByRole("button", {
              name: "Weitere Angaben & Verknüpfungen",
            })
            .click();
          await page
            .getByLabel(
              "Verweise auf zugehörige Dokument-IDs (eine pro Zeile)",
              { exact: true },
            )
            .fill(bankPdfId);
        }
      } else {
        const outgoing = index === 0 || index === 3;
        await page
          .getByLabel("Aussteller / Lieferant")
          .fill(outgoing ? company : "Beispiel Lieferant");
        await page
          .getByLabel("Empfänger / Kunde")
          .fill(outgoing ? "Beispiel Kunde" : company);
        await page
          .getByLabel("Belegnummer", { exact: true })
          .fill(index === 7 ? "SCAN-2026-10" : `SYNTH-2026-10-${index}`);
        await page.getByLabel("Belegdatum", { exact: true }).fill("2026-10-15");
        await page.getByLabel("Netto (z. B. 100.00)").fill("100.00");
        await page.getByLabel("Steuer (z. B. 20.00)").fill("20.00");
        await page.getByLabel("Brutto (z. B. 120.00)").fill("120.00");
        await page.getByLabel("Währung (ISO, z. B. EUR)").fill("EUR");
      }
      await page.getByRole("button", { name: "Prüfen & freigeben" }).click();
      await expect(page.getByText("Geprüft", { exact: true })).toBeVisible();
      await navigate(page, "Dokumenteingang");
    }
    await navigate(page, "Übergabe & Versand");
    await page
      .getByRole("button", { name: "Vorschau erstellen", exact: true })
      .click();
    await expect(page.getByText(/8 Originale/)).toBeVisible();
    await page
      .getByRole("button", { name: "Paket verbindlich erzeugen" })
      .click();
    await expect(
      page.getByRole("link", { name: "ZIP herunterladen" }),
    ).toBeVisible({ timeout: 45_000 });
    const download = page.waitForEvent("download");
    await page.getByRole("link", { name: "ZIP herunterladen" }).click();
    expect((await download).suggestedFilename()).toMatch(/paket-v\d+\.zip/);
    await page.screenshot({
      path: info.outputPath(`${folder || "Beispiel-GmbH"}-monat.png`),
      fullPage: true,
    });
  }
  expect(errors).toEqual([]);
});
