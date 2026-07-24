import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test, expect, type Page, type BrowserContext } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..", "..");
const PYTHON = path.join(ROOT, ".venv", "Scripts", "python.exe");
const SEED_SCRIPT = path.join(__dirname, "helpers", "seedScoringProject.py");
const LOG_DIR = path.join(ROOT, "test-results", "e2e", "logs");
const SHOT_DIR = path.join(ROOT, "test-results", "e2e", "screenshots");
const CLASS_TEST = "C:/Users/james/FAAI/CLASS_TEST.csv";
const CLASS_OOT = "C:/Users/james/FAAI/CLASS_OOT.csv";

/**
 * Stage B.7: Classification Scoring, TEST validation, and OOT validation.
 * API-seeds a trained project with a SAVED final model (CLASS_TRAIN.csv through
 * the product's real /data/upload_csv path), then exercises the real Scoring UI:
 * development TRAIN scoring, TEST upload, OOT upload, cross-dataset comparison,
 * Prediction PSI / VSI, registration, and project isolation. Full backend
 * payloads are captured to test-results/e2e/logs for independent offline
 * metric/PSI validation (see helpers/validateScoringPayloads.py).
 */

function seedProject(): any {
  const seedFile = process.env.B7_SEED_FILE;
  if (seedFile && fs.existsSync(seedFile)) {
    return JSON.parse(fs.readFileSync(seedFile, "utf-8").trim().split("\n").pop() as string);
  }
  const raw = execFileSync(PYTHON, [SEED_SCRIPT, "E2E Classification Scoring OOT"], {
    encoding: "utf-8", timeout: 900_000,
  });
  return JSON.parse(raw.trim().split("\n").pop() as string);
}

async function seedWorkflowStore(page: Page, projectId: string, projectName: string) {
  await page.addInitScript(({ projectId, projectName }) => {
    const steps = ["step00", "step01", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
    const stepStatus = Object.fromEntries(steps.map((id) => [id, ["step10", "step11", "step12", "step13"].includes(id) ? "pending" : "complete"]));
    const workflowSteps = steps.map((id, index) => ({ id, label: id, route: `/${id}`, status: stepStatus[id] ?? "pending", order: index }));
    window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({
      state: {
        projectId, modelId: projectName, projectName, projectType: "predictive-modeling",
        workflowId: "predictive-modeling", workflowSteps, currentStepId: "step10", steps: stepStatus,
        restoreWarnings: [],
      },
      version: 0,
    }));
  }, { projectId, projectName });
}

test("Scoring: development, TEST, OOT, comparison, PSI/VSI, isolation", async ({ page, context, browser }) => {
  test.setTimeout(30 * 60_000);
  fs.mkdirSync(LOG_DIR, { recursive: true });
  fs.mkdirSync(SHOT_DIR, { recursive: true });

  const consoleErrors: string[] = [];
  const networkErrors: string[] = [];
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
  page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
  page.on("crash", () => consoleErrors.push("RENDERER CRASH (page.on crash)"));
  page.on("response", (res) => {
    if (res.status() >= 400 && res.url().includes("/api/")) networkErrors.push(`${res.status()} ${res.request().method()} ${res.url()}`);
  });

  const seed = seedProject();
  expect(seed.training_status).toBe("complete");
  expect(seed.final_ready, JSON.stringify(seed)).toBe(true);

  await context.addCookies([
    { name: "atlas_session", value: seed.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" },
  ]);
  await seedWorkflowStore(page, seed.project_id, "E2E Classification Scoring OOT");

  // ---- Phase 1: Scoring entry state -------------------------------------
  const [statusResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/model/final/status"), { timeout: 60_000 }),
    page.goto("/step10"),
  ]);
  const statusBody = await statusResponse.json().catch(() => null);
  expect(statusBody?.ready, JSON.stringify(statusBody)).toBe(true);
  await expect(page.getByTestId("final-model-scoring-contract")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Verified artifact", { exact: true })).toBeVisible();
  await expect(page.getByText(/belongs to a different project, dataset version, or target/i)).toHaveCount(0);
  await expect(page.getByText("A verified final model is required", { exact: false })).toHaveCount(0);
  await page.screenshot({ path: path.join(SHOT_DIR, "b7-01-scoring-entry.png"), fullPage: true });

  // Refresh preserves ready state (final-model contract is backend-derived).
  await page.reload();
  await expect(page.getByTestId("final-model-scoring-contract")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/belongs to a different project/i)).toHaveCount(0);

  // ---- Phase 2: development TRAIN scoring --------------------------------
  const scoreTrainBtn = page.getByRole("button", { name: "Score TRAIN" });
  await expect(scoreTrainBtn).toBeEnabled({ timeout: 20_000 });
  const [trainResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/score/development-split"), { timeout: 300_000 }),
    scoreTrainBtn.click(),
  ]);
  expect(trainResponse.status()).toBe(200);
  // NOTE: scoring responses carry the FULL scored output (100k+ rows) and are
  // too large for CDP body capture ("evicted from inspector cache") -- the UI
  // outcome is asserted here, and the payloads are captured out-of-band by
  // helpers/validateScoringPayloads.py (capture mode) for independent metric
  // validation against the same endpoints and session.
  await expect(page.getByTestId("train-scoring-zone").getByText(/rows scored/)).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "b7-02-train-scored.png"), fullPage: true });

  // ---- Phase 3: TEST upload + scoring ------------------------------------
  const [testResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/score/upload") && r.url().includes("dataset_type=test"), { timeout: 300_000 }),
    page.locator('[data-testid="test-scoring-zone"] input[type="file"]').setInputFiles(CLASS_TEST),
  ]);
  expect(testResponse.status()).toBe(200);
  await expect(page.getByTestId("test-scoring-zone").getByText("56,961 rows scored")).toBeVisible({ timeout: 60_000 });
  // TRAIN result not overwritten by TEST scoring.
  await expect(page.getByTestId("train-scoring-zone").getByText(/rows scored/)).toBeVisible();
  await page.screenshot({ path: path.join(SHOT_DIR, "b7-03-test-scored.png"), fullPage: true });

  // ---- Phase 4: OOT upload + scoring -------------------------------------
  const [ootResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/score/upload") && r.url().includes("dataset_type=oot"), { timeout: 300_000 }),
    page.locator('[data-testid="oot-scoring-zone"] input[type="file"]').setInputFiles(CLASS_OOT),
  ]);
  expect(ootResponse.status()).toBe(200);
  await expect(page.getByTestId("oot-scoring-zone").getByText("56,962 rows scored")).toBeVisible({ timeout: 60_000 });
  // Neither TRAIN nor TEST results were overwritten.
  await expect(page.getByTestId("train-scoring-zone").getByText(/rows scored/)).toBeVisible();
  await expect(page.getByTestId("test-scoring-zone").getByText(/rows scored/)).toBeVisible();

  // ---- Phase 5: cross-dataset performance --------------------------------
  const comparison = page.getByTestId("cross-dataset-performance");
  await expect(comparison.getByText("3/3 populations available")).toBeVisible({ timeout: 20_000 });
  await expect(comparison.locator("table")).toBeVisible();
  const comparisonText = await comparison.innerText();
  fs.writeFileSync(path.join(LOG_DIR, "b7_comparison_table.txt"), comparisonText);
  await comparison.scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(SHOT_DIR, "b7-04-cross-dataset.png"), fullPage: true });

  // ---- Phase 6-8: stability command center (PSI + VSI) -------------------
  const stability = page.getByTestId("stability-command-center");
  await stability.scrollIntoViewIfNeeded();
  await expect(stability.getByRole("heading", { name: "TRAIN vs TEST" })).toBeVisible();
  await expect(stability.getByRole("heading", { name: "TRAIN vs OOT" })).toBeVisible();
  await expect(stability.getByText("Prediction PSI").first()).toBeVisible();
  await expect(page.getByTestId("combined-variable-stability-index")).toBeVisible();
  const stabilityText = await stability.innerText();
  fs.writeFileSync(path.join(LOG_DIR, "b7_stability_center.txt"), stabilityText);
  await page.screenshot({ path: path.join(SHOT_DIR, "b7-05-stability-center.png"), fullPage: true });

  // Export path 1: save stability evidence.
  const [evidenceResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/evidence") && r.request().method() === "POST", { timeout: 60_000 }),
    stability.getByRole("button", { name: "Save as Evidence" }).click(),
  ]);
  expect(evidenceResponse.status()).toBe(200);
  const evidenceBody = await evidenceResponse.json().catch(() => null);
  fs.writeFileSync(path.join(LOG_DIR, "b7_evidence_response.json"), JSON.stringify(evidenceBody));

  // Export path 2: register the TEST scored output to the Dataset Library via
  // section G (Scored Output Registration; rows are ordered TRAIN, TEST, OOT).
  const registerTest = page.getByTestId("scored-output-registration").getByRole("button", { name: /^Register/ }).nth(1);
  await registerTest.scrollIntoViewIfNeeded();
  const [registerResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/scoring/register-scored-dataset"), { timeout: 180_000 }),
    registerTest.click(),
  ]);
  expect(registerResponse.status()).toBe(200);
  const registerBody = await registerResponse.json().catch(() => null);
  fs.writeFileSync(path.join(LOG_DIR, "b7_register_test_response.json"), JSON.stringify(registerBody));
  await page.screenshot({ path: path.join(SHOT_DIR, "b7-06-registered.png"), fullPage: true });

  // ---- Phase 2.7 observation: persistence through refresh ----------------
  await page.reload();
  await expect(page.getByTestId("final-model-scoring-contract")).toBeVisible({ timeout: 20_000 });
  const trainZoneAfterReload = await page.getByTestId("train-scoring-zone").innerText();
  fs.writeFileSync(path.join(LOG_DIR, "b7_after_reload_train_zone.txt"), trainZoneAfterReload);

  // ---- Phase 9: project isolation ----------------------------------------
  const isoRaw = execFileSync(PYTHON, ["-c", `
import json, uuid, httpx
s = httpx.Client(timeout=60.0)
sfx = uuid.uuid4().hex[:8]
r = s.post("http://127.0.0.1:8001/api/auth/register", json={"email": f"e2e-scoring-iso-{sfx}@atlas-e2e.local", "displayName": "E2E Scoring Iso", "password": "AtlasE2ePassw0rd!", "role": "data_scientist"})
r.raise_for_status()
u = r.json()["user"]
r = s.post("http://127.0.0.1:8001/api/projects", json={"projectName": "E2E Scoring Isolation Probe", "projectType": "predictive-modeling"})
r.raise_for_status()
print(json.dumps({"user_id": u["userId"], "project_id": r.json()["project"]["projectId"], "cookies": dict(s.cookies)}))
`], { encoding: "utf-8", timeout: 120_000 });
  const iso = JSON.parse(isoRaw.trim().split("\n").pop() as string);

  const isoContext: BrowserContext = await browser.newContext();
  await isoContext.addCookies([
    { name: "atlas_session", value: iso.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" },
  ]);
  const isoPage = await isoContext.newPage();
  await seedWorkflowStore(isoPage, iso.project_id, "E2E Scoring Isolation Probe");
  await isoPage.goto("http://127.0.0.1:5174/step10");
  // The second project has no trained/final model: scoring must be blocked,
  // with no leakage of the first project's results.
  await expect(isoPage.getByText("A verified final model is required", { exact: false })).toBeVisible({ timeout: 30_000 });
  await expect(isoPage.getByText(/rows scored/)).toHaveCount(0);
  await expect(isoPage.getByText("E2E Classification Scoring OOT")).toHaveCount(0);
  await isoPage.screenshot({ path: path.join(SHOT_DIR, "b7-07-isolation-second-project.png"), fullPage: true });

  // Interleaved read back on the first project: its contract is still intact.
  await page.reload();
  await expect(page.getByTestId("final-model-scoring-contract")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/belongs to a different project/i)).toHaveCount(0);
  await isoContext.close();

  fs.writeFileSync(path.join(LOG_DIR, "b7_console_errors.log"), consoleErrors.join("\n") || "(none)");
  fs.writeFileSync(path.join(LOG_DIR, "b7_network_errors.log"), networkErrors.join("\n") || "(none)");
  fs.writeFileSync(path.join(LOG_DIR, "b7_isolation_state.json"), JSON.stringify(iso));
});
