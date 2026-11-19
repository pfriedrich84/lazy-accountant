import { expect, test } from "@playwright/test";

test("harmless EICAR remains quarantined without preview or original access", async ({
  page,
}) => {
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
  // Keep the intentionally unresolved malware case out of the shared personal
  // inbox: later independent SMTP smokes must still obey the open-issues rule.
  const company = `Quarantäne Browser ${Date.now()}`;
  await page.goto("/settings");
  await page
    .getByRole("button", { name: "+ Firma anlegen", exact: true })
    .click();
  await page.getByLabel("Firmenname", { exact: true }).fill(company);
  await page
    .getByRole("button", { name: "Firma speichern", exact: true })
    .click();
  await expect(page.getByLabel("Anzeigename")).toHaveValue(company);
  await page.goto("/documents");
  await page.getByRole("banner").getByLabel("Firma", { exact: true }).click();
  await page.getByRole("option", { name: company, exact: true }).click();
  const eicar =
    "X5O!P%@AP[4\\PZX54(P^)7CC)7}$" +
    "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*";
  await page.getByLabel("Dokumentdateien").setInputFiles({
    name: "harmless-eicar.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(eicar),
  });
  await expect(page.getByText(/1 Datei\(en\) übernommen/)).toBeVisible();
  await page
    .getByRole("link", { name: "harmless-eicar.txt", exact: true })
    .first()
    .click();
  await expect(page.getByText(/Sicherheitssperre: infected/)).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByRole("link", { name: "Original öffnen" })).toHaveCount(
    0,
  );
  await expect(page.locator("img.preview-page")).toHaveCount(0);
  const id = page.url().split("/").filter(Boolean).at(-1);
  for (const representation of ["original", "text", "page"]) {
    const response = await page.request.get(
      `/api/documents/${id}/${representation}/`,
    );
    expect(response.status()).toBe(423);
  }
});
