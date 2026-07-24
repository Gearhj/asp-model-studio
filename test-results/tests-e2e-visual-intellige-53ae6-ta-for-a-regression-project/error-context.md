# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests\e2e\visual-intelligence-lab.spec.ts >> Visual Intelligence Foundation Phase 1: prototypes >> Interactive Distribution Explorer and Regression Diagnostic Explorer render real data for a regression project
- Location: tests\e2e\visual-intelligence-lab.spec.ts:40:3

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/visual-intelligence-lab", waiting until "load"

```

# Test source

```ts
  1   | import fs from "node:fs";
  2   | import path from "node:path";
  3   | import { fileURLToPath } from "node:url";
  4   | import { test, expect } from "@playwright/test";
  5   | import { attachDiagnostics } from "./helpers/diagnostics";
  6   | import { shot } from "./helpers/screenshots";
  7   | 
  8   | const __dirname = path.dirname(fileURLToPath(import.meta.url));
  9   | const REGRESSION_SEED_PATH = path.join(
  10  |   "C:\\Users\\james\\AppData\\Local\\Temp\\claude\\c--Users-james-ds-workflow-starter\\b3701922-26ad-4231-b773-a6d1a9d5ebff\\scratchpad",
  11  |   "viLab_regression_seed_state.json"
  12  | );
  13  | const CLASSIFICATION_SEED_PATH = path.join(path.dirname(REGRESSION_SEED_PATH), "viLab_classification_seed_state.json");
  14  | 
  15  | const CLASSIFICATION_ONLY_TERMS = ["confusion matrix", "precision", "recall", "specificity", "F1", "ROC AUC", "positive class", "alert rate"];
  16  | const REGRESSION_ONLY_TERMS = ["RMSE", "R-squared", "residual", "Q-Q plot", "actual vs. predicted", "MAE"];
  17  | 
  18  | function findTerms(text: string, terms: string[]): string[] {
  19  |   const lower = text.toLowerCase();
  20  |   return terms.filter((term) => lower.includes(term.toLowerCase()));
  21  | }
  22  | 
  23  | async function resumeSession(page: import("@playwright/test").Page, context: import("@playwright/test").BrowserContext, seedPath: string, projectName: string) {
  24  |   const seed = JSON.parse(fs.readFileSync(seedPath, "utf-8"));
  25  |   await context.addCookies([{ name: "atlas_session", value: seed.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  26  |   await page.addInitScript(
  27  |     ({ projectId, name }) => {
  28  |       const steps = ["dashboard", "step00", "step01", "step01b", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
  29  |       const stepStatus = Object.fromEntries(steps.map((id) => [id, "complete"]));
  30  |       const workflowSteps = steps.filter((s) => s !== "dashboard").map((id, index) => ({ id, label: id, route: `/${id}`, status: "complete", order: index }));
  31  |       const state = { projectId, modelId: name, projectName: name, projectType: "predictive-modeling", workflowId: "predictive-modeling", workflowSteps, currentStepId: "step08", steps: stepStatus, restoreWarnings: [] };
  32  |       window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state, version: 0 }));
  33  |     },
  34  |     { projectId: seed.project_id, name: projectName }
  35  |   );
  36  |   return seed;
  37  | }
  38  | 
  39  | test.describe("Visual Intelligence Foundation Phase 1: prototypes", () => {
  40  |   test("Interactive Distribution Explorer and Regression Diagnostic Explorer render real data for a regression project", async ({ page, context }, testInfo) => {
  41  |     test.setTimeout(3 * 60_000);
  42  |     const { dump } = attachDiagnostics(page, testInfo);
  43  |     await resumeSession(page, context, REGRESSION_SEED_PATH, "VI Lab Regression Seed");
  44  | 
> 45  |     await page.goto("/visual-intelligence-lab");
      |                ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  46  |     await expect(page.getByTestId("distribution-explorer")).toBeVisible({ timeout: 20_000 });
  47  | 
  48  |     // Variable selector, bin count, and segment metrics are populated with real data.
  49  |     // The first aggregate may need DuckDB-Wasm's ~35-40MB wasm module to finish
  50  |     // downloading and instantiating in the worker (first use only, then cached) --
  51  |     // poll rather than a fixed sleep so the test is robust to that one-time cost.
  52  |     await expect(page.getByTestId("variable-selector")).toBeVisible();
  53  |     await expect(page.getByTestId("segment-metrics")).toBeVisible();
  54  |     await expect(page.getByTestId("segment-metrics")).toContainText(/\d/, { timeout: 45_000 });
  55  |     await shot(page, testInfo, "01-distribution-explorer-regression");
  56  |     const metricsText = await page.getByTestId("segment-metrics").innerText();
  57  | 
  58  |     // Numeric cutoff entry mirrors what a drag would do -- updates segment metrics.
  59  |     const before = await page.getByTestId("segment-metrics").innerText();
  60  |     await page.getByLabel("Segment minimum").fill("2");
  61  |     await page.getByLabel("Segment maximum").fill("4");
  62  |     await page.waitForTimeout(1500);
  63  |     const after = await page.getByTestId("segment-metrics").innerText();
  64  |     expect(after).not.toBe(before);
  65  |     await shot(page, testInfo, "02-distribution-explorer-segment-selected");
  66  | 
  67  |     await page.getByTestId("reset-button").click();
  68  |     await page.waitForTimeout(500);
  69  | 
  70  |     // Regression Diagnostic Explorer.
  71  |     await page.getByTestId("vi-tab-regression").click();
  72  |     await expect(page.getByTestId("regression-diagnostic-explorer")).toBeVisible({ timeout: 20_000 });
  73  |     await page.waitForTimeout(3000);
  74  |     await shot(page, testInfo, "03-regression-diagnostic-explorer");
  75  | 
  76  |     await expect(page.getByTestId("regression-segment-metrics")).toBeVisible();
  77  |     const regressionText = await page.locator('[data-testid="regression-diagnostic-explorer"]').innerText();
  78  |     const classificationLeakage = findTerms(regressionText, CLASSIFICATION_ONLY_TERMS);
  79  |     console.log("VI_LAB_REGRESSION_CLASSIFICATION_LEAKAGE:", JSON.stringify(classificationLeakage));
  80  |     expect(classificationLeakage).toEqual([]);
  81  |     expect(regressionText).toMatch(/RMSE/);
  82  |     expect(regressionText).toMatch(/Residual/i);
  83  | 
  84  |     // Classification Decision Explorer must honestly refuse for a regression project.
  85  |     await page.getByTestId("vi-tab-classification").click();
  86  |     await expect(page.getByTestId("wrong-problem-type")).toBeVisible({ timeout: 10_000 });
  87  |     await shot(page, testInfo, "04-classification-explorer-wrong-problem-type");
  88  | 
  89  |     await dump();
  90  |   });
  91  | 
  92  |   test("Classification Decision Explorer renders real data and stays free of regression terminology", async ({ page, context }, testInfo) => {
  93  |     test.setTimeout(3 * 60_000);
  94  |     const { dump } = attachDiagnostics(page, testInfo);
  95  |     await resumeSession(page, context, CLASSIFICATION_SEED_PATH, "VI Lab Classification Seed");
  96  | 
  97  |     await page.goto("/visual-intelligence-lab");
  98  |     await page.getByTestId("vi-tab-classification").click();
  99  |     await expect(page.getByTestId("classification-decision-explorer")).toBeVisible({ timeout: 20_000 });
  100 |     await page.waitForTimeout(2500);
  101 |     await shot(page, testInfo, "05-classification-decision-explorer");
  102 | 
  103 |     await expect(page.getByTestId("confusion-matrix")).toBeVisible();
  104 |     const beforeMetrics = await page.getByTestId("classification-metrics").innerText();
  105 | 
  106 |     // Numeric threshold control updates threshold-dependent metrics.
  107 |     await page.getByTestId("threshold-input").fill("0.8");
  108 |     await page.getByTestId("threshold-input").blur();
  109 |     await page.waitForTimeout(1000);
  110 |     const afterMetrics = await page.getByTestId("classification-metrics").innerText();
  111 |     expect(afterMetrics).not.toBe(beforeMetrics);
  112 |     await shot(page, testInfo, "06-classification-threshold-changed");
  113 | 
  114 |     const classificationText = await page.locator('[data-testid="classification-decision-explorer"]').innerText();
  115 |     const regressionLeakage = findTerms(classificationText, REGRESSION_ONLY_TERMS);
  116 |     console.log("VI_LAB_CLASSIFICATION_REGRESSION_LEAKAGE:", JSON.stringify(regressionLeakage));
  117 |     expect(regressionLeakage).toEqual([]);
  118 |     // Case-insensitive: the DOM text is authored as "Precision"/"ROC AUC" but rendered
  119 |     // with CSS text-transform: uppercase, which innerText() reflects as visible text.
  120 |     expect(classificationText).toMatch(/precision/i);
  121 |     expect(classificationText).toMatch(/roc auc/i);
  122 | 
  123 |     await dump();
  124 |   });
  125 | });
  126 | 
```