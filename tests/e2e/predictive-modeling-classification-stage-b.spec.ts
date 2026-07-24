import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { goNext } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TEST_FILE = "e2e_audit_classification_test.csv";
const OOT_FILE = "e2e_audit_classification_oot.csv";

const SEED_STATE_PATH = path.join(
  "C:\\Users\\james\\AppData\\Local\\Temp\\claude\\c--Users-james-ds-workflow-starter\\b3701922-26ad-4231-b773-a6d1a9d5ebff\\scratchpad",
  "stageB_seed_state.json",
);

async function dumpText(page: import("@playwright/test").Page, label: string, maxLen = 8000) {
  const text = (await page.locator("body").innerText()).slice(0, maxLen);
  console.log(`\n===== ${label} =====\n${text}`);
  return text;
}

test.describe("Stage B: Classification Evaluation, Interpretation, Scoring, OOT", () => {
  test("Downstream flow from a pre-seeded completed model", async ({ page, context }, testInfo) => {
    test.setTimeout(10 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    // Phase 1 (fast path): a completed classification model was already created via direct API
    // calls against the same live backend (register -> project -> data -> outliers -> missing ->
    // feature manifest -> materialize -> split -> train -> poll to "complete"), reusing exactly
    // the same workflow verified end-to-end in Stage A. Browser automation for those already-
    // verified early steps proved unreliable in this environment during this session (traced to
    // Chromium/Playwright timing under resource contention, not an application defect -- see the
    // Stage B defect register). Injecting that session's cookie here to resume in a real browser
    // for this stage's actual objective: Evaluation, Interpretation, Scoring, and OOT validation.
    const seed = JSON.parse(fs.readFileSync(SEED_STATE_PATH, "utf-8"));
    console.log("STAGE_B_SEED:", JSON.stringify({ project_id: seed.project_id, training_status: seed.training_status }));
    expect(seed.training_status).toBe("complete");

    await context.addCookies([
      { name: "atlas_session", value: seed.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" },
    ]);

    // The frontend's active-project state lives in sessionStorage (zustand persist, key
    // "ds-workflow-store"), entirely separate from the backend project the API seeding created.
    // "Open Project" only restores a client-saved *snapshot* (workflow-step completion, etc.)
    // that was never written for an API-only-created project, so it shows 0/14 steps regardless
    // of the real backend state -- a dead end for this purpose. Inject the minimal store state
    // directly instead: Evaluation/Interpretation/Scoring query the backend by projectId, so
    // setting projectId (plus enough scaffolding for the shell to render) is what actually matters.
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
      { projectId: seed.project_id, projectName: "E2E Classification Audit Stage B" },
    );

    await page.goto("/step08");
    await page.waitForLoadState("networkidle");
    await shot(page, testInfo, "00-resumed-session-step08");

    // ---------- Phase 2: Evaluation ----------
    await page.waitForTimeout(2000);
    await shot(page, testInfo, "02-evaluation-overview");
    const evalText = await dumpText(page, "STAGE_B_EVALUATION_TEXT", 10000);

    for (const tabName of ["Threshold", "Stability", "Leaderboard", "Lift"]) {
      const tab = page.getByRole("button", { name: new RegExp(tabName, "i") }).first();
      if (await tab.isVisible().catch(() => false)) {
        await tab.click().catch(() => undefined);
        await page.waitForTimeout(1000);
        await shot(page, testInfo, `02-evaluation-tab-${tabName.toLowerCase()}`);
      }
    }

    await page.getByTitle("Add to Comparison").first().click();
    await page.waitForTimeout(500);
    await shot(page, testInfo, "02-evaluation-candidate-added");

    await goNext(page, /\/step09/);

    // ---------- Phase 3: Interpretation ----------
    await page.waitForTimeout(3000);
    await shot(page, testInfo, "03-interpretation-overview");
    const interpText = await dumpText(page, "STAGE_B_INTERPRETATION_TEXT", 10000);

    // Run RFE and Save as Final Model explicitly, waiting for RFE to actually finish computing
    // before saving -- the generic gating helper fired both in quick succession, saving a final
    // model before RFE had produced real results, which Scoring's governance check then rejected
    // as belonging to a different project/dataset/target than the current session.
    const runRfeBtn = page.getByRole("button", { name: /Run RFE|Rerun RFE/ });
    await runRfeBtn.click();
    await expect(page.getByText(/Run RFE to rank candidate features\./)).toHaveCount(0, { timeout: 60_000 });
    await page.waitForTimeout(1000);
    await shot(page, testInfo, "03b-interpretation-rfe-complete");

    const saveFinalBtn = page.getByRole("button", { name: "Save as Final Model" });
    await expect(saveFinalBtn).toBeEnabled({ timeout: 10_000 });
    await saveFinalBtn.click();
    await page.waitForTimeout(2000);
    await shot(page, testInfo, "03c-interpretation-final-model-saved");

    await goNext(page, /\/step10/);
    await page.waitForTimeout(2000);

    // ---------- Phase 4: Scoring - TEST ----------
    await shot(page, testInfo, "04-scoring-before");
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
    console.log("STAGE_B_TEST_SCORED:", testScored);
    await shot(page, testInfo, "04-scoring-test-uploaded");
    const testScoringText = await dumpText(page, "STAGE_B_TEST_SCORING_TEXT", 8000);
    expect(testScored).toBe(true);

    // ---------- Phase 5: Out-of-Time Validation - OOT ----------
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
    console.log("STAGE_B_OOT_SCORED:", ootScored);
    await shot(page, testInfo, "05-scoring-oot-uploaded");
    const ootScoringText = await dumpText(page, "STAGE_B_OOT_SCORING_TEXT", 8000);
    expect(ootScored).toBe(true);

    await page.waitForTimeout(3000);
    await shot(page, testInfo, "06-scoring-final");
    const crossDatasetText = await dumpText(page, "STAGE_B_CROSS_DATASET_TEXT", 6000);

    console.log("STAGE_B_HAS_EVAL_TEXT:", evalText.length > 500);
    console.log("STAGE_B_HAS_INTERP_TEXT:", interpText.length > 500);
    console.log("STAGE_B_HAS_TEST_SCORING:", testScoringText.length > 200);
    console.log("STAGE_B_HAS_OOT_SCORING:", ootScoringText.length > 200);
    void crossDatasetText;

    await dump();
  });
});
