import { expect, test, type Page } from "@playwright/test";

async function manage(page: Page) {
  const section = page.getByRole("button", {
    name: "Dokument verwalten",
    exact: true,
  });
  if ((await section.getAttribute("aria-expanded")) !== "true")
    await section.click();
}
import { readFileSync } from "node:fs";
import path from "node:path";

test("Signaturgrafik ausschließen, separat finden und ohne Freigabe wiederherstellen", async ({
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
  await page.goto("/documents");
  await page.getByLabel("Eingang", { exact: true }).click();
  await page
    .getByRole("option", { name: "Firma ungeklärt", exact: true })
    .click();
  const filename = `signature-${info.project.name}-${Date.now()}.png`;
  const bytes = Buffer.concat([
    readFileSync(path.resolve("../var/samples/scan.png")),
    Buffer.from(filename),
  ]);
  await page
    .getByLabel("Dokumentdateien")
    .setInputFiles({ name: filename, mimeType: "image/png", buffer: bytes });
  const signatureRow = page.getByRole("row").filter({
    has: page.getByRole("link", {
      name: new RegExp(`^${filename.slice(0, -4)}-[a-f0-9]+\\.png$`),
    }),
  });
  await signatureRow.getByRole("link").click();
  await manage(page);
  await expect(
    page.getByText(`Originalname: ${filename}`, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: new RegExp(`^${filename.slice(0, -4)}-[a-f0-9]+\\.png$`),
    }),
  ).toBeVisible();
  const docUrl = page.url();
  await page
    .getByRole("button", { name: "Als Nichtbeleg ausschließen", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", {
      name: "Als Nichtbeleg ausschließen",
      exact: true,
    }),
  ).toBeDisabled();
  await dialog
    .getByLabel("Begründung")
    .fill("Visuell geprüfte Signaturgrafik; kein Beleg <b>untrusted</b>");
  await dialog
    .getByRole("button", { name: "Als Nichtbeleg ausschließen", exact: true })
    .click();
  await expect(
    page.getByText("Als Nichtbeleg ausgeschlossen", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Prüfen & freigeben" }),
  ).toBeDisabled();
  const originalTab = page.getByRole("tab", { name: "Original", exact: true });
  if (await originalTab.isVisible()) await originalTab.click();
  await expect(
    page.getByRole("link", { name: "Original öffnen" }),
  ).toBeVisible();
  const dataTab = page.getByRole("tab", { name: "Prüfdaten", exact: true });
  if (await dataTab.isVisible()) await dataTab.click();
  await expect(
    page.getByText(/Visuell geprüfte Signaturgrafik/).first(),
  ).toContainText("<b>untrusted</b>");
  await page.getByRole("link", { name: "Zur Liste" }).click();
  await page.getByLabel("Eingang", { exact: true }).click();
  await page
    .getByRole("option", { name: "Firma ungeklärt", exact: true })
    .click();
  await page.getByLabel("Suche").fill(filename);
  await expect(
    page.getByText("Keine Dokumente in dieser Ansicht"),
  ).toBeVisible();
  await page.getByLabel("Ausschluss", { exact: true }).click();
  await page
    .getByRole("option", { name: "Ausgeschlossene Nichtbelege", exact: true })
    .click();
  await signatureRow.getByRole("link").click();
  await expect(page).toHaveURL(docUrl);
  await manage(page);
  await page
    .getByRole("button", { name: "Wiederherstellen", exact: true })
    .click();
  await dialog.getByLabel("Begründung").fill("Wiederherstellung prüfen");
  await dialog
    .getByRole("button", { name: "Wiederherstellen", exact: true })
    .click();
  await expect(
    page.getByText("Als Nichtbeleg ausgeschlossen", { exact: true }),
  ).toHaveCount(0);
  await manage(page);
  await expect(
    page.getByRole("button", {
      name: "Als Nichtbeleg ausschließen",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Prüfen & freigeben" }),
  ).toBeEnabled();
  await expect(
    page.getByText("Als Nichtbeleg ausgeschlossen", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Ablage & Nachvollziehbarkeit", exact: true })
    .click();
  await expect(page.getByText(/v3 · restore/)).toContainText(
    "Wiederherstellung prüfen",
  );
  await expect(page.getByText("3 offene Prüfpunkte")).toBeVisible();
  // Restore is intentionally not an approval. Leave only this test's synthetic
  // image excluded, otherwise a later real worker/mail smoke correctly blocks
  // on the still-unassigned active inbox document after backup/restore.
  await page
    .getByRole("button", { name: "Als Nichtbeleg ausschließen", exact: true })
    .click();
  await dialog
    .getByLabel("Begründung")
    .fill("Testbereinigung: synthetische Signaturgrafik");
  await dialog
    .getByRole("button", { name: "Als Nichtbeleg ausschließen", exact: true })
    .click();
  await expect(
    page.getByText("Als Nichtbeleg ausgeschlossen", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
