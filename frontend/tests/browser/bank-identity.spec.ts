import { expect, test } from "@playwright/test";

test("CAMT-Identität verknüpfen und beanstanden ohne Zahlungen zu verschieben", async ({
  page,
}, info) => {
  test.setTimeout(60_000);
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
  const csrf = (await (await page.request.get("/api/auth/csrf/")).json())
    .csrfToken;
  const headers = { "X-CSRFToken": csrf };
  const company = (await (await page.request.get("/api/companies/")).json())[0];
  const assignments = await (
    await page.request.get(`/api/companies/${company.id}/`)
  ).json();
  const account = assignments.accounts.find(
    (item: { kind: string }) => item.kind === "bank",
  );
  const unique = `IDENTITY-${info.project.name}-${Date.now()}`.replace(
    /[^A-Za-z0-9-]/g,
    "-",
  );
  const ids: string[] = [];
  for (const reference of ["", `BANK-${unique}`]) {
    // Synthetic CAMT originals, deliberately equal TxId/counteraccount/facts.
    const xml = `<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>
      <Id>${unique}</Id><FrToDt><FrDtTm>2026-10-01T00:00:00Z</FrDtTm><ToDtTm>2026-10-31T23:59:59Z</ToDtTm></FrToDt>
      <Acct><Id><IBAN>${account.identifier}</IBAN></Id><Ccy>EUR</Ccy></Acct><Ntry><Amt Ccy="EUR">120.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>
      <BookgDt><Dt>2026-10-15</Dt></BookgDt><ValDt><Dt>2026-10-15</Dt></ValDt><AcctSvcrRef>${reference}</AcctSvcrRef>
      <NtryDtls><TxDtls><Refs><AcctSvcrRef>${reference}</AcctSvcrRef><TxId>${unique}</TxId></Refs><RltdPties><Dbtr><Pty><Nm>Synthetic Identity Party</Nm></Pty></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct></RltdPties><RmtInf><Ustrd>${unique}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>`;
    const upload = await page.request.post("/api/documents/", {
      headers,
      multipart: {
        company_id: String(company.id),
        files: {
          name: `${unique}-${reference ? "canonical" : "observation"}.xml`,
          mimeType: "application/xml",
          buffer: Buffer.from(xml),
        },
      },
    });
    expect(upload.status()).toBe(201);
    const id = (await upload.json()).results[0].document.id;
    const doc = await (await page.request.get(`/api/documents/${id}/`)).json();
    const approved = await page.request.put(`/api/documents/${id}/`, {
      headers,
      data: {
        document_id: id,
        base_version: doc.version,
        company_id: company.id,
        kind: "bank_camt",
        period: "2026-10",
        account_id: account.id,
        metadata: doc.metadata,
        approve: true,
      },
    });
    expect(approved.ok()).toBe(true);
    const value = await approved.json();
    const normalized = await page.request.post(
      "/api/reconciliation/normalize/",
      {
        headers,
        data: {
          document_id: id,
          base_version: value.version,
          auto_confirm: false,
          idempotency_key: `${unique}-${reference ? "canonical" : "observation"}`,
        },
      },
    );
    expect(normalized.ok()).toBe(true);
    ids.push((await normalized.json()).transaction_ids[0]);
  }
  await page.goto("/payments");
  await page.getByRole("combobox", { name: "Ansicht", exact: true }).click();
  await page
    .getByRole("option", {
      name: "Bankbewegungen / fehlende Zuordnung",
      exact: true,
    })
    .click();
  await page.getByRole("textbox", { name: "Firmenweit suchen" }).fill(unique);
  const searched = page.waitForResponse(
    (response) => new URL(response.url()).searchParams.get("search") === unique,
  );
  await page.getByRole("button", { name: "Suchen", exact: true }).click();
  expect((await searched).ok()).toBe(true);
  const identityButton = page.getByRole("button", {
    name: "Umsatzidentität prüfen",
    exact: true,
  });
  await expect(identityButton).toHaveCount(1);
  await identityButton.click();
  await page.getByRole("combobox", { name: "Kanonische Bankbewegung" }).click();
  await page
    .getByRole("option", { name: `BANK-${unique} · vorprüfbar`, exact: true })
    .click();
  await expect(
    page.getByText(/Bank-TxId und Gegenkonto stimmen überein/),
  ).toBeVisible();
  const merge = page.getByRole("button", {
    name: "Identitätszusammenführung bestätigen",
    exact: true,
  });
  await expect(merge).toBeDisabled();
  await page
    .getByLabel("Begründung zur Umsatzidentität")
    .fill("Synthetische Originale explizit gegengeprüft");
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/identity-merge/") &&
      response.request().method() === "POST",
  );
  await merge.click();
  expect((await (await saved).json()).payment_effect).toBe("none");
  await expect(page.getByText(/Beobachtung zusammengeführt/)).toBeVisible();
  await page
    .getByLabel("Begründung zur Identitätsbeanstandung")
    .fill("Synthetischer Bezug nachträglich bestritten");
  const disputed = page.waitForResponse(
    (response) =>
      response.url().endsWith("/identity-dispute/") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Zusammenführung beanstanden", exact: true })
    .click();
  expect((await (await disputed).json()).payment_effect).toBe("none");
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Identitätszusammenführung bestritten" }),
  ).toBeVisible();
  const movements = await (
    await page.request.get(
      `/api/reconciliation/transactions/?company_id=${company.id}&search=${unique}`,
    )
  ).json();
  const duplicate = movements.items.find(
    (item: { id: string }) => item.id === ids[0],
  );
  expect(duplicate.merged_into_id).toBe(ids[1]);
  expect(duplicate.available).toBe("0");
  const history = await (
    await page.request.get(
      `/api/reconciliation/identity-history/?transaction_id=${ids[1]}`,
    )
  ).json();
  expect(
    history.items.map((item: { operation: string }) => item.operation),
  ).toEqual(["identity.merge", "identity.dispute"]);
  expect(errors).toEqual([]);
});
