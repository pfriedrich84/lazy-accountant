import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

async function navigate(page: Page, title: string) {
  const item = page.getByRole("link", { name: title, exact: true });
  if (!(await item.first().isVisible()))
    await page.getByRole("button", { name: "Menü öffnen" }).click();
  await page
    .getByRole("link", { name: title, exact: true })
    .filter({ visible: true })
    .click();
}

test("Firma anlegen → PDF hochladen → prüfen → Paket herunterladen", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
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
  await navigate(page, "Dokumenteingang");
  await page
    .getByLabel("Dokumentdateien")
    .setInputFiles(path.resolve("../var/samples/eingang.pdf"));
  await expect(page.getByText(/1 Datei\(en\) übernommen/)).toBeVisible();
  await page.getByRole("link", { name: "eingang.pdf", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "eingang.pdf" }),
  ).toBeVisible();
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
