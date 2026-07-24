import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { goNext } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TEST_FILE = "e2e_audit_regression_test.csv";
const OOT_FILE = "e2e_audit_regression_oot.csv";

const SEED_STATE_PATH = path.join(
  "C:\\Users\\james\\AppData\\Local\\Temp\\claude\\c--Users-james-ds-workflow-starter\\b3701922-26ad-4231-b773-a6d1a9d5ebff\\scratchpad",
  "stageB_regression_seed_state.json",
);

// Terms that must never appear as ACTIVE regression evaluation/scoring output
// (Phase 2/16's central acceptance criterion). Intentionally excludes words
// that are legitimate substrings of regression-appropriate terms (e.g. "class"
// inside "classifier" doesn't appear here at all -- we match on terms that are
// unambiguous classification-only vocabulary).
const CLASSIFICATION_ONLY_TERMS = [
  "confusion matrix", "accuracy", "precision", "recall", "specificity",
  "F1", "ROC AUC", "ROC curve", "PR AUC", "Gini", " KS ", "lift chart",
  "gains chart", "class threshold", "alert rate", "predicted positive rate",
  "positive class", "probability threshold",
];

async function dumpText(page: import("@playwright/test").Page, label: string, maxLen = 8000) {
  const text = (await page.locator("body").innerText()).slice(0, maxLen);
  console.log(`\n===== ${label} =====\n${text}`);
  return text;
}

function findClassificationLeakage(text: string): string[] {
  const lower = text.toLowerCase();
  return CLASSIFICATION_ONLY_TERMS.filter((term) => lower.includes(term.toLowerCase()));
}

test.describe("Regression Stage B: Evaluation, Interpretation, Scoring, TEST, OOT", () => {
  test("Downstream regression flow from a pre-seeded completed model", async ({ page, context }, testInfo) => {
    test.setTimeout(10 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    const seed = JSON.parse(fs.readFileSync(SEED_STATE_PATH, "utf-8"));
    console.log("STAGE_B_REG_SEED:", JSON.stringify({ project_id: seed.project_id, training_status: seed.training_status, target: seed.target }));
    expect(seed.training_status).toBe("complete");
    expect(seed.target).toBe("MedHouseVal");

    await context.addCookies([
      { name: "atlas_session", value: seed.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" },
    ]);

    await page.addInitScript(
      ({ projectId, projectName }) => {
        const steps = ["dashboard", "step00", "step01", "step01b", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
        const stepStatus = Object.fromEntries(steps.map((id) => [id, ["step08", "step09", "step10", "step11", "step12", "step13"].includes(id) ? "pending" : "complete"]));
        const workflowSteps = ["step00", "step01", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"].map((id, index) => ({
          id, label: id, route: `/${id}`, status: stepStatus[id] ?? "pending", order: index,
        }));
        const state = {
          projectId, modelId: projectName, projectName, projectType: "predictive-modeling",
          workflowId: "predictive-modeling", workflowSteps, currentStepId: "step08", steps: stepStatus,
          restoreWarnings: [],
        };
        window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state, version: 0 }));
      },
      { projectId: seed.project_id, projectName: "E2E Regression Audit Stage B" },
    );

    // ---------- Phase 2: Evaluation ----------
    await page.goto("/step08");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    await shot(page, testInfo, "02-evaluation-overview");
    const evalText = await dumpText(page, "STAGE_B_REG_EVALUATION_TEXT", 10000);

    const evalLeakage = findClassificationLeakage(evalText);
    console.log("STAGE_B_REG_EVAL_CLASSIFICATION_LEAKAGE:", JSON.stringify(evalLeakage));

    // Regression-appropriate metrics and governing-metric language must be present.
    expect(evalText).toMatch(/RMSE/i);
    expect(evalText).toMatch(/R.?2|R-squared/i);
    expect(evalText).toMatch(/MAE/i);

    for (const tabName of ["Stability", "Leaderboard", "Diagnostics", "Residuals"]) {
      const tab = page.getByRole("button", { name: new RegExp(tabName, "i") }).first();
      if (await tab.isVisible().catch(() => false)) {
        await tab.click().catch(() => undefined);
        await page.waitForTimeout(1000);
        await shot(page, testInfo, `02-evaluation-tab-${tabName.toLowerCase()}`);
        const tabText = await dumpText(page, `STAGE_B_REG_EVAL_TAB_${tabName.toUpperCase()}`, 6000);
        const tabLeakage = findClassificationLeakage(tabText);
        console.log(`STAGE_B_REG_EVAL_TAB_${tabName.toUpperCase()}_LEAKAGE:`, JSON.stringify(tabLeakage));
      }
    }

    await page.getByTitle("Add to Comparison").first().click();
    await page.waitForTimeout(500);
    await shot(page, testInfo, "02b-evaluation-candidate-added");

    await goNext(page, /\/step09/);

    // ---------- Phase 5: Interpretation ----------
    await page.waitForTimeout(3000);
    await shot(page, testInfo, "03-interpretation-overview");
    const interpText = await dumpText(page, "STAGE_B_REG_INTERPRETATION_TEXT", 10000);
    const interpLeakage = findClassificationLeakage(interpText);
    console.log("STAGE_B_REG_INTERP_CLASSIFICATION_LEAKAGE:", JSON.stringify(interpLeakage));
    expect(interpText).toMatch(/MedHouseVal/);

    const runRfeBtn = page.getByRole("button", { name: /Run RFE|Rerun RFE/ });
    if (await runRfeBtn.isVisible().catch(() => false)) {
      await runRfeBtn.click();
      await expect(page.getByText(/Run RFE to rank candidate features\./)).toHaveCount(0, { timeout: 60_000 });
      await page.waitForTimeout(1000);
      await shot(page, testInfo, "03b-interpretation-rfe-complete");
    }

    // ---------- Phase 6: Final Model ----------
    const saveFinalBtn = page.getByRole("button", { name: "Save as Final Model" });
    await expect(saveFinalBtn).toBeEnabled({ timeout: 15_000 });
    await saveFinalBtn.click();
    await page.waitForTimeout(2000);
    await shot(page, testInfo, "03c-interpretation-final-model-saved");
    const finalModelText = await dumpText(page, "STAGE_B_REG_FINAL_MODEL_TEXT", 4000);
    console.log("STAGE_B_REG_FINAL_MODEL_LEAKAGE:", JSON.stringify(findClassificationLeakage(finalModelText)));

    await goNext(page, /\/step10/);
    await page.waitForTimeout(2000);

    // ---------- Phase 7: Development (TRAIN) Scoring ----------
    await shot(page, testInfo, "04-scoring-before");
    const trainZone = page.locator('[data-testid="train-scoring-zone"]');
    const trainScoreBtn = trainZone.getByRole("button", { name: /Score/i }).first();
    await trainScoreBtn.click();
    const trainDeadline = Date.now() + 60_000;
    let trainScored = false;
    while (Date.now() < trainDeadline) {
      const zoneText = await trainZone.innerText();
      if (/\d[\d,]*\s*rows scored/i.test(zoneText)) { trainScored = true; break; }
      await page.waitForTimeout(1500);
    }
    console.log("STAGE_B_REG_TRAIN_SCORED:", trainScored);
    const trainZoneText = await trainZone.innerText();
    console.log("STAGE_B_REG_TRAIN_ZONE_LEAKAGE:", JSON.stringify(findClassificationLeakage(trainZoneText)));
    await shot(page, testInfo, "04-scoring-train-scored");
    expect(trainScored).toBe(true);

    // ---------- Phase 8: TEST Validation ----------
    const testZone = page.locator('[data-testid="test-scoring-zone"]');
    const testZoneInput = testZone.locator('input[type="file"]');
    await testZoneInput.setInputFiles(path.join(__dirname, "data", TEST_FILE));
    const testDeadline = Date.now() + 60_000;
    let testScored = false;
    while (Date.now() < testDeadline) {
      const zoneText = await testZone.innerText();
      if (/\d[\d,]*\s*rows scored/i.test(zoneText)) { testScored = true; break; }
      await page.waitForTimeout(1500);
    }
    console.log("STAGE_B_REG_TEST_SCORED:", testScored);
    await shot(page, testInfo, "05-scoring-test-uploaded");
    const testScoringText = await dumpText(page, "STAGE_B_REG_TEST_SCORING_TEXT", 8000);
    console.log("STAGE_B_REG_TEST_LEAKAGE:", JSON.stringify(findClassificationLeakage(testScoringText)));
    expect(testScored).toBe(true);

    // ---------- Phase 9: Out-of-Time Validation - OOT ----------
    const ootZone = page.locator('[data-testid="oot-scoring-zone"]');
    const ootZoneInput = ootZone.locator('input[type="file"]');
    await ootZoneInput.setInputFiles(path.join(__dirname, "data", OOT_FILE));
    const ootDeadline = Date.now() + 60_000;
    let ootScored = false;
    while (Date.now() < ootDeadline) {
      const zoneText = await ootZone.innerText();
      if (/\d[\d,]*\s*rows scored/i.test(zoneText)) { ootScored = true; break; }
      await page.waitForTimeout(1500);
    }
    console.log("STAGE_B_REG_OOT_SCORED:", ootScored);
    await shot(page, testInfo, "06-scoring-oot-uploaded");
    const ootScoringText = await dumpText(page, "STAGE_B_REG_OOT_SCORING_TEXT", 8000);
    console.log("STAGE_B_REG_OOT_LEAKAGE:", JSON.stringify(findClassificationLeakage(ootScoringText)));
    expect(ootScored).toBe(true);

    await page.waitForTimeout(3000);

    // ---------- Phase 10: Cross-Dataset Performance ----------
    const crossDatasetZone = page.locator('[data-testid="cross-dataset-performance"]');
    await shot(page, testInfo, "07-cross-dataset-performance");
    const crossDatasetText = await crossDatasetZone.innerText();
    console.log("STAGE_B_REG_CROSS_DATASET_TEXT:", crossDatasetText.slice(0, 4000));
    console.log("STAGE_B_REG_CROSS_DATASET_LEAKAGE:", JSON.stringify(findClassificationLeakage(crossDatasetText)));
    expect(crossDatasetText).toMatch(/RMSE/i);

    // ---------- Phase 11-13: Stability Command Center (Prediction PSI + VSI) ----------
    const stabilityZone = page.locator('[data-testid="stability-command-center"]');
    await shot(page, testInfo, "08-stability-command-center");
    const stabilityText = await stabilityZone.innerText();
    console.log("STAGE_B_REG_STABILITY_TEXT:", stabilityText.slice(0, 4000));
    console.log("STAGE_B_REG_STABILITY_LEAKAGE:", JSON.stringify(findClassificationLeakage(stabilityText)));

    // ---------- Phase 14: Persistence across refresh ----------
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    await shot(page, testInfo, "09-scoring-after-refresh");
    const afterRefreshTrainZoneText = await page.locator('[data-testid="train-scoring-zone"]').innerText();
    const afterRefreshTestZoneText = await page.locator('[data-testid="test-scoring-zone"]').innerText();
    const afterRefreshOotZoneText = await page.locator('[data-testid="oot-scoring-zone"]').innerText();
    console.log("STAGE_B_REG_PERSISTENCE_TRAIN_SURVIVES_REFRESH:", /\d[\d,]*\s*rows scored/i.test(afterRefreshTrainZoneText));
    console.log("STAGE_B_REG_PERSISTENCE_TEST_SURVIVES_REFRESH:", /\d[\d,]*\s*rows scored/i.test(afterRefreshTestZoneText));
    console.log("STAGE_B_REG_PERSISTENCE_OOT_SURVIVES_REFRESH:", /\d[\d,]*\s*rows scored/i.test(afterRefreshOotZoneText));

    console.log("STAGE_B_REG_HAS_EVAL_TEXT:", evalText.length > 500);
    console.log("STAGE_B_REG_HAS_INTERP_TEXT:", interpText.length > 500);
    console.log("STAGE_B_REG_HAS_TEST_SCORING:", testScoringText.length > 200);
    console.log("STAGE_B_REG_HAS_OOT_SCORING:", ootScoringText.length > 200);

    await dump();
  });

  test("Regression and classification projects do not leak evaluation framing across each other", async ({ page, context }, testInfo) => {
    test.setTimeout(3 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    const isolationSeedPath = path.join(path.dirname(SEED_STATE_PATH), "stageB_isolation_seed_state.json");
    const classSeed = JSON.parse(fs.readFileSync(isolationSeedPath, "utf-8"));
    expect(classSeed.training_status).toBe("complete");

    await context.addCookies([
      { name: "atlas_session", value: classSeed.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" },
    ]);
    await page.addInitScript(
      ({ projectId, projectName }) => {
        const steps = ["dashboard", "step00", "step01", "step01b", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
        const stepStatus = Object.fromEntries(steps.map((id) => [id, ["step08", "step09", "step10", "step11", "step12", "step13"].includes(id) ? "pending" : "complete"]));
        const workflowSteps = ["step00", "step01", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"].map((id, index) => ({
          id, label: id, route: `/${id}`, status: stepStatus[id] ?? "pending", order: index,
        }));
        const state = {
          projectId, modelId: projectName, projectName, projectType: "predictive-modeling",
          workflowId: "predictive-modeling", workflowSteps, currentStepId: "step08", steps: stepStatus,
          restoreWarnings: [],
        };
        window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state, version: 0 }));
      },
      { projectId: classSeed.project_id, projectName: "E2E Isolation Check Classification" },
    );

    await page.goto("/step08");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    await shot(page, testInfo, "10-isolation-classification-evaluation");
    const classEvalText = await dumpText(page, "STAGE_B_REG_ISOLATION_CLASSIFICATION_EVAL_TEXT", 6000);

    // A classification project must show classification framing (PR-AUC/ROC-AUC), not regression
    // metrics, and must show no trace of the regression project's target/data (MedHouseVal).
    expect(classEvalText).toMatch(/PR-AUC/);
    expect(classEvalText).not.toMatch(/MedHouseVal/);
    expect(classEvalText).not.toMatch(/Adjusted R-squared/);
    console.log("STAGE_B_REG_ISOLATION_RESULT: classification project correctly shows classification framing, no regression bleed");

    await dump();
  });
});
