import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`Missing ${name}.`);
  return process.argv[index + 1];
}

const frontendUrl = argument("--frontend-url").replace(/\/$/, "");
const outputDirectory = path.resolve(argument("--output-directory"));
const expectedVersionId = argument("--expected-version-id");
const expectedAttributeCode = argument("--expected-attribute-code");
const routeUrl = `${frontendUrl}/tests/bureauCatalogAdmin.isolated.entry.html`;
await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({ headless: true });
try {
  const adminContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    extraHTTPHeaders: {
      "X-Synthetic-Principal": "synthetic-admin",
      "X-Synthetic-Role": "admin",
      "X-Synthetic-Tenant": "synthetic-tenant",
    },
  });
  const adminPage = await adminContext.newPage();
  adminPage.setDefaultNavigationTimeout(120_000);
  await adminPage.goto(routeUrl, { waitUntil: "domcontentloaded" });
  await adminPage.getByRole("heading", { name: "Bureau Catalog Administration" }).waitFor();
  await adminPage.getByText(expectedVersionId, { exact: false }).waitFor();
  await adminPage.getByRole("button", { name: "Validate integrity" }).click();
  await adminPage.getByText("Validation completed for exact version", { exact: false }).waitFor();

  const search = adminPage.getByLabel("Search attribute code or label");
  await search.fill("Synthetic operational");
  await adminPage.getByRole("button", { name: "Search", exact: true }).click();
  await adminPage.getByText(expectedAttributeCode, { exact: true }).first().waitFor();
  await adminPage.getByRole("button", { name: `Inspect exact attribute ${expectedAttributeCode}` }).click();
  await adminPage.locator('[data-testid="exact-attribute-result"]').getByText(expectedAttributeCode, { exact: true }).waitFor();

  await adminPage.getByRole("button", { name: "Retire version" }).click();
  await adminPage.getByRole("heading", { name: "Confirm catalog retirement" }).waitFor();
  const confirm = adminPage.getByRole("button", { name: "Confirm retirement" });
  if (!(await confirm.evaluate((node) => node === document.activeElement))) {
    throw new Error("The retirement confirmation did not receive keyboard focus.");
  }
  await adminPage.getByRole("button", { name: "Cancel" }).click();
  if (await confirm.isVisible().catch(() => false)) {
    throw new Error("The retirement confirmation did not close after cancellation.");
  }

  const adminText = await adminPage.locator("body").innerText();
  for (const forbidden of ["restricted_storage_reference", "attribute_definitions.jsonl", "special_value_definitions.jsonl"]) {
    if (adminText.includes(forbidden)) throw new Error("The admin UI exposed restricted storage metadata.");
  }
  await adminPage.screenshot({
    path: path.join(outputDirectory, "synthetic-bureau-catalog-admin.png"),
    fullPage: true,
  });
  await adminContext.close();

  const userContext = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    extraHTTPHeaders: {
      "X-Synthetic-Principal": "synthetic-reader",
      "X-Synthetic-Role": "user",
      "X-Synthetic-Tenant": "synthetic-tenant",
    },
  });
  const userPage = await userContext.newPage();
  userPage.setDefaultNavigationTimeout(120_000);
  await userPage.goto(routeUrl, { waitUntil: "domcontentloaded" });
  await userPage.getByRole("heading", { name: "Administrative access required" }).waitFor();
  if (await userPage.getByRole("button", { name: "Validate integrity" }).isVisible().catch(() => false)) {
    throw new Error("A non-admin principal reached catalog administration controls.");
  }
  if (await userPage.getByText(expectedVersionId, { exact: false }).isVisible().catch(() => false)) {
    throw new Error("A non-admin principal received catalog version metadata.");
  }
  await userContext.close();

  process.stdout.write(JSON.stringify({
    ok: true,
    admin_route_rendered: true,
    live_bounded_search_rendered: true,
    exact_record_rendered: true,
    retirement_two_step_confirmed: true,
    non_admin_controls_denied: true,
    screenshot_count: 1,
  }));
} finally {
  await browser.close();
}
