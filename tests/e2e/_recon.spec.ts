import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { goNext } from "./helpers/workflow";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIAG_FILE = "E2E_DIAG_CLASS_TRAIN_20260723101021.csv";

test("clean-restart diagnostic: single preflight submission", async ({ page }) => {
  test.setTimeout(6 * 60_000);

  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  const failedResponses: { url: string; status: number; body: string }[] = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("requestfailed", (r) => failedRequests.push(`${r.method()} ${r.url()} -- ${r.failure()?.errorText}`));
  page.on("response", async (r) => {
    if (r.status() >= 400) {
      let body = "";
      try { body = (await r.text()).slice(0, 1000); } catch { /* ignore */ }
      failedResponses.push({ url: r.url(), status: r.status(), body });
    }
  });

  const user = makeTestUser("cleanrestart-diag");
  console.log("DIAG_USER:", JSON.stringify(user));
  await registerUser(page, user);

  await createPredictiveModelingProject(page, { name: "E2E Diag Clean Restart", modelId: `diag-${Date.now()}` });
  console.log("DIAG_PROJECT_URL:", page.url());

  await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
  await goNext(page, /\/step01/);

  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles(path.join(__dirname, "data", DIAG_FILE));
  await page.waitForTimeout(4000);
  await goNext(page, /\/step02/);
  await goNext(page, /\/step03/);
  await goNext(page, /\/step04/);
  await goNext(page, /\/step05/);
  await goNext(page, /\/step06/);
  await goNext(page, /\/step07/);
  await page.waitForTimeout(1500);

  // Submit preflight exactly once, capturing the response network payload directly.
  const [preflightResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/train/preflight"), { timeout: 30_000 }),
    (async () => {
      const trainButton = page.getByRole("button", { name: /Train Selected Models/ });
      await trainButton.first().click();
    })(),
  ]);
  const preflightBody = await preflightResponse.json().catch(() => null);
  const fs = await import("node:fs");
  fs.writeFileSync(
    "test-results/e2e/_clean-restart-diag-preflight.json",
    JSON.stringify(
      {
        status: preflightResponse.status(),
        ready: preflightBody?.ready,
        blocking: preflightBody?.blocking,
        warnings: preflightBody?.warnings,
        dataset_id: preflightBody?.dataset_id,
        dataset_version: preflightBody?.dataset_version,
        split_id: preflightBody?.split_id,
        feature_manifest_version: preflightBody?.feature_manifest_version,
      },
      null,
      2,
    ),
  );
  console.log("PREFLIGHT_STATUS:", preflightResponse.status());
  console.log("PREFLIGHT_KEY_FIELDS:", JSON.stringify({ ready: preflightBody?.ready, blocking: preflightBody?.blocking, dataset_id: preflightBody?.dataset_id }));

  await page.waitForTimeout(1000);
  console.log("CONSOLE_ERRORS:", JSON.stringify(consoleErrors));
  console.log("FAILED_REQUESTS:", JSON.stringify(failedRequests));
  console.log("FAILED_RESPONSES:", JSON.stringify(failedResponses));

  await page.screenshot({ path: "test-results/e2e/_clean-restart-diag-preflight.png", fullPage: true });
});
