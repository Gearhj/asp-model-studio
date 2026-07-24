import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REGRESSION_SEED_PATH = path.join(
  "C:\\Users\\james\\AppData\\Local\\Temp\\claude\\c--Users-james-ds-workflow-starter\\b3701922-26ad-4231-b773-a6d1a9d5ebff\\scratchpad",
  "viLab_regression_seed_state.json"
);
const CLASSIFICATION_SEED_PATH = path.join(path.dirname(REGRESSION_SEED_PATH), "viLab_classification_seed_state.json");

const CLASSIFICATION_ONLY_TERMS = ["confusion matrix", "precision", "recall", "specificity", "F1", "ROC AUC", "positive class", "alert rate"];
const REGRESSION_ONLY_TERMS = ["RMSE", "R-squared", "residual", "Q-Q plot", "actual vs. predicted", "MAE"];

function findTerms(text: string, terms: string[]): string[] {
  const lower = text.toLowerCase();
  return terms.filter((term) => lower.includes(term.toLowerCase()));
}

async function resumeSession(page: import("@playwright/test").Page, context: import("@playwright/test").BrowserContext, seedPath: string, projectName: string) {
  const seed = JSON.parse(fs.readFileSync(seedPath, "utf-8"));
  await context.addCookies([{ name: "atlas_session", value: seed.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.addInitScript(
    ({ projectId, name }) => {
      const steps = ["dashboard", "step00", "step01", "step01b", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
      const stepStatus = Object.fromEntries(steps.map((id) => [id, "complete"]));
      const workflowSteps = steps.filter((s) => s !== "dashboard").map((id, index) => ({ id, label: id, route: `/${id}`, status: "complete", order: index }));
      const state = { projectId, modelId: name, projectName: name, projectType: "predictive-modeling", workflowId: "predictive-modeling", workflowSteps, currentStepId: "step08", steps: stepStatus, restoreWarnings: [] };
      window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state, version: 0 }));
    },
    { projectId: seed.project_id, name: projectName }
  );
  return seed;
}

test.describe("Visual Intelligence Foundation Phase 1: prototypes", () => {
  test("Interactive Distribution Explorer and Regression Diagnostic Explorer render real data for a regression project", async ({ page, context }, testInfo) => {
    test.setTimeout(3 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await resumeSession(page, context, REGRESSION_SEED_PATH, "VI Lab Regression Seed");

    await page.goto("/visual-intelligence-lab");
    await expect(page.getByTestId("distribution-explorer")).toBeVisible({ timeout: 20_000 });

    // Variable selector, bin count, and segment metrics are populated with real data.
    // The first aggregate may need DuckDB-Wasm's ~35-40MB wasm module to finish
    // downloading and instantiating in the worker (first use only, then cached) --
    // poll rather than a fixed sleep so the test is robust to that one-time cost.
    await expect(page.getByTestId("variable-selector")).toBeVisible();
    await expect(page.getByTestId("segment-metrics")).toBeVisible();
    await expect(page.getByTestId("segment-metrics")).toContainText(/\d/, { timeout: 45_000 });
    await shot(page, testInfo, "01-distribution-explorer-regression");
    const metricsText = await page.getByTestId("segment-metrics").innerText();

    // Numeric cutoff entry mirrors what a drag would do -- updates segment metrics.
    const before = await page.getByTestId("segment-metrics").innerText();
    await page.getByLabel("Segment minimum").fill("2");
    await page.getByLabel("Segment maximum").fill("4");
    await page.waitForTimeout(1500);
    const after = await page.getByTestId("segment-metrics").innerText();
    expect(after).not.toBe(before);
    await shot(page, testInfo, "02-distribution-explorer-segment-selected");

    await page.getByTestId("reset-button").click();
    await page.waitForTimeout(500);

    // Regression Diagnostic Explorer.
    await page.getByTestId("vi-tab-regression").click();
    await expect(page.getByTestId("regression-diagnostic-explorer")).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(3000);
    await shot(page, testInfo, "03-regression-diagnostic-explorer");

    await expect(page.getByTestId("regression-segment-metrics")).toBeVisible();
    const regressionText = await page.locator('[data-testid="regression-diagnostic-explorer"]').innerText();
    const classificationLeakage = findTerms(regressionText, CLASSIFICATION_ONLY_TERMS);
    console.log("VI_LAB_REGRESSION_CLASSIFICATION_LEAKAGE:", JSON.stringify(classificationLeakage));
    expect(classificationLeakage).toEqual([]);
    expect(regressionText).toMatch(/RMSE/);
    expect(regressionText).toMatch(/Residual/i);

    // Classification Decision Explorer must honestly refuse for a regression project.
    await page.getByTestId("vi-tab-classification").click();
    await expect(page.getByTestId("wrong-problem-type")).toBeVisible({ timeout: 10_000 });
    await shot(page, testInfo, "04-classification-explorer-wrong-problem-type");

    await dump();
  });

  test("Classification Decision Explorer renders real data and stays free of regression terminology", async ({ page, context }, testInfo) => {
    test.setTimeout(3 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await resumeSession(page, context, CLASSIFICATION_SEED_PATH, "VI Lab Classification Seed");

    await page.goto("/visual-intelligence-lab");
    await page.getByTestId("vi-tab-classification").click();
    await expect(page.getByTestId("classification-decision-explorer")).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(2500);
    await shot(page, testInfo, "05-classification-decision-explorer");

    await expect(page.getByTestId("confusion-matrix")).toBeVisible();
    const beforeMetrics = await page.getByTestId("classification-metrics").innerText();

    // Numeric threshold control updates threshold-dependent metrics.
    await page.getByTestId("threshold-input").fill("0.8");
    await page.getByTestId("threshold-input").blur();
    await page.waitForTimeout(1000);
    const afterMetrics = await page.getByTestId("classification-metrics").innerText();
    expect(afterMetrics).not.toBe(beforeMetrics);
    await shot(page, testInfo, "06-classification-threshold-changed");

    const classificationText = await page.locator('[data-testid="classification-decision-explorer"]').innerText();
    const regressionLeakage = findTerms(classificationText, REGRESSION_ONLY_TERMS);
    console.log("VI_LAB_CLASSIFICATION_REGRESSION_LEAKAGE:", JSON.stringify(regressionLeakage));
    expect(regressionLeakage).toEqual([]);
    // Case-insensitive: the DOM text is authored as "Precision"/"ROC AUC" but rendered
    // with CSS text-transform: uppercase, which innerText() reflects as visible text.
    expect(classificationText).toMatch(/precision/i);
    expect(classificationText).toMatch(/roc auc/i);

    await dump();
  });
});
