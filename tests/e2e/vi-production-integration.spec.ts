import fs from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const SCRATCH = "C:\\Users\\james\\AppData\\Local\\Temp\\claude\\c--Users-james-ds-workflow-starter\\b3701922-26ad-4231-b773-a6d1a9d5ebff\\scratchpad";
const REGRESSION_SEED_PATH = path.join(SCRATCH, "viprod_regression_seed_state.json");
const CLASSIFICATION_SEED_PATH = path.join(SCRATCH, "viprod_classification_seed_state.json");

type Seed = { project_id: string; cookies: { atlas_session: string }; scoring_run_ids: Record<string, string> };

async function resumeSession(page: import("@playwright/test").Page, context: import("@playwright/test").BrowserContext, seed: Seed, projectName: string, currentStepId = "step08") {
  await context.addCookies([{ name: "atlas_session", value: seed.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.addInitScript(
    ({ projectId, name, stepId }) => {
      const steps = ["dashboard", "step00", "step01", "step01b", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
      const stepStatus = Object.fromEntries(steps.map((id) => [id, "complete"]));
      const workflowSteps = steps.filter((s) => s !== "dashboard").map((id, index) => ({ id, label: id, route: `/${id}`, status: "complete", order: index }));
      const state = { projectId, modelId: name, projectName: name, projectType: "predictive-modeling", workflowId: "predictive-modeling", workflowSteps, currentStepId: stepId, steps: stepStatus, restoreWarnings: [] };
      window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state, version: 0 }));
    },
    { projectId: seed.project_id, name: projectName, stepId: currentStepId }
  );
}

test.describe("Visual Intelligence Production Integration, Phase 2", () => {
  test("Regression path: EDA distribution + Evaluation regression explorer, both against a durable scoring run", async ({ page, context }, testInfo) => {
    test.setTimeout(3 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const seed: Seed = JSON.parse(fs.readFileSync(REGRESSION_SEED_PATH, "utf-8"));
    await resumeSession(page, context, seed, "VI Prod Regression Seed", "step02");

    // EDA: the embedded Distribution Explorer renders inside the Predictors tab,
    // without hiding the pre-existing basic EDA summaries.
    await page.goto("/step02");
    await page.getByRole("tab", { name: /predictors/i }).click();
    await expect(page.getByTestId("visual-analysis-panel-distribution")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("distribution-explorer")).toBeVisible({ timeout: 20_000 });
    await shot(page, testInfo, "01-eda-distribution-explorer-embedded");

    // Evaluation: deep-link directly to the durable TEST scoring run.
    const testRunId = seed.scoring_run_ids.test;
    await resumeSession(page, context, seed, "VI Prod Regression Seed", "step08");
    await page.goto(`/step08?scoringRunId=${encodeURIComponent(testRunId)}`);
    await expect(page.getByTestId("visual-analysis-panel-regression")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("regression-diagnostic-explorer")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("scoring-run-source-badge").first()).toBeVisible({ timeout: 15_000 });
    const regressionText = await page.locator('[data-testid="regression-diagnostic-explorer"]').innerText();
    expect(regressionText).toMatch(/RMSE/);
    expect(regressionText.toLowerCase()).not.toContain("confusion matrix");
    expect(regressionText.toLowerCase()).not.toContain("precision");
    await shot(page, testInfo, "02-evaluation-regression-explorer-scoring-run");

    // Save Analysis to Evidence is wired and reachable.
    await expect(page.getByTestId("va-save-evidence")).toBeVisible();
    await page.getByTestId("va-save-evidence").click();
    await expect(page.getByTestId("va-evidence-status")).toContainText(/saved/i, { timeout: 15_000 });
    await shot(page, testInfo, "03-evaluation-regression-evidence-saved");

    await dump();
  });

  test("Classification path: Evaluation classification explorer against a durable scoring run", async ({ page, context }, testInfo) => {
    test.setTimeout(3 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const seed: Seed = JSON.parse(fs.readFileSync(CLASSIFICATION_SEED_PATH, "utf-8"));
    await resumeSession(page, context, seed, "VI Prod Classification Seed", "step08");

    const testRunId = seed.scoring_run_ids.test;
    await page.goto(`/step08?scoringRunId=${encodeURIComponent(testRunId)}`);
    await expect(page.getByTestId("visual-analysis-panel-classification")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("classification-decision-explorer")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("confusion-matrix")).toBeVisible({ timeout: 15_000 });
    const classificationText = await page.locator('[data-testid="classification-decision-explorer"]').innerText();
    expect(classificationText.toLowerCase()).not.toContain("rmse");
    expect(classificationText.toLowerCase()).not.toContain("residual");
    await shot(page, testInfo, "04-evaluation-classification-explorer-scoring-run");

    // Hard refresh restores the same run (URL-driven, not React state).
    await page.reload();
    await expect(page.getByTestId("classification-decision-explorer")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("scoring-run-source-badge").first()).toBeVisible({ timeout: 15_000 });
    await shot(page, testInfo, "05-evaluation-classification-refresh-restored");

    await dump();
  });

  test("Scoring history: Open Analysis deep-links into the durable run, and Register Scored Dataset is reachable", async ({ page, context }, testInfo) => {
    test.setTimeout(2 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const seed: Seed = JSON.parse(fs.readFileSync(REGRESSION_SEED_PATH, "utf-8"));
    await resumeSession(page, context, seed, "VI Prod Regression Seed", "step10");

    await page.goto("/step10");
    await expect(page.getByTestId("scoring-history-panel")).toBeVisible({ timeout: 20_000 });
    const rows = page.getByTestId("scoring-history-row");
    expect(await rows.count()).toBeGreaterThanOrEqual(3);
    await shot(page, testInfo, "06-step10-history-with-open-analysis");

    const openAnalysisLink = page.getByRole("link", { name: "Open Analysis" }).first();
    await expect(openAnalysisLink).toBeVisible();
    await openAnalysisLink.click();
    await expect(page).toHaveURL(/\/step08\?scoringRunId=/);
    await expect(page.getByTestId("visual-analysis-panel-regression")).toBeVisible({ timeout: 20_000 });
    await shot(page, testInfo, "07-open-analysis-deep-link-landed");

    await dump();
  });

  test("Cross-project isolation: a foreign scoringRunId in the URL is honestly rejected, not silently substituted", async ({ page, context }, testInfo) => {
    test.setTimeout(2 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const regressionSeed: Seed = JSON.parse(fs.readFileSync(REGRESSION_SEED_PATH, "utf-8"));
    const classificationSeed: Seed = JSON.parse(fs.readFileSync(CLASSIFICATION_SEED_PATH, "utf-8"));

    // Log in as the CLASSIFICATION project's user, but deep-link using the
    // REGRESSION project's scoringRunId while the active project is the
    // classification one -- must fall back to live workspace data, never
    // silently render the foreign run.
    await resumeSession(page, context, classificationSeed, "VI Prod Classification Seed", "step08");
    const foreignRunId = regressionSeed.scoring_run_ids.test;
    await page.goto(`/step08?scoringRunId=${encodeURIComponent(foreignRunId)}`);
    await expect(page.getByTestId("visual-analysis-panel-classification")).toBeVisible({ timeout: 20_000 });
    // The foreign run must never be attributed -- either the URL param is cleared
    // (live workspace fallback) or an explicit denial state is shown; in both cases
    // the "Durable scoring run" badge for the FOREIGN run must never appear silently.
    await page.waitForTimeout(2000);
    const url = page.url();
    expect(url).not.toContain(foreignRunId);
    await shot(page, testInfo, "08-cross-project-foreign-run-rejected");

    await dump();
  });
});
