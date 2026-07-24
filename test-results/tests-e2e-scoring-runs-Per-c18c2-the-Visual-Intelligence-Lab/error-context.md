# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests\e2e\scoring-runs.spec.ts >> Persistent Scoring Runs, Phase 1 >> Step10 Scoring page's history panel lists durable runs and links into the Visual Intelligence Lab
- Location: tests\e2e\scoring-runs.spec.ts:74:3

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/step10", waiting until "load"

```

# Test source

```ts
  1  | import fs from "node:fs";
  2  | import path from "node:path";
  3  | import { fileURLToPath } from "node:url";
  4  | import { test, expect } from "@playwright/test";
  5  | import { attachDiagnostics } from "./helpers/diagnostics";
  6  | import { shot } from "./helpers/screenshots";
  7  | 
  8  | const __dirname = path.dirname(fileURLToPath(import.meta.url));
  9  | const SEED_PATH = path.join(
  10 |   "C:\\Users\\james\\AppData\\Local\\Temp\\claude\\c--Users-james-ds-workflow-starter\\b3701922-26ad-4231-b773-a6d1a9d5ebff\\scratchpad",
  11 |   "scoringRun_seed_state.json"
  12 | );
  13 | 
  14 | async function resumeSession(page: import("@playwright/test").Page, context: import("@playwright/test").BrowserContext, projectId: string, cookieValue: string, projectName: string) {
  15 |   await context.addCookies([{ name: "atlas_session", value: cookieValue, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  16 |   await page.addInitScript(
  17 |     ({ projectId, name }) => {
  18 |       const steps = ["dashboard", "step00", "step01", "step01b", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
  19 |       const stepStatus = Object.fromEntries(steps.map((id) => [id, "complete"]));
  20 |       const workflowSteps = steps.filter((s) => s !== "dashboard").map((id, index) => ({ id, label: id, route: `/${id}`, status: "complete", order: index }));
  21 |       const state = { projectId, modelId: name, projectName: name, projectType: "predictive-modeling", workflowId: "predictive-modeling", workflowSteps, currentStepId: "step10", steps: stepStatus, restoreWarnings: [] };
  22 |       window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state, version: 0 }));
  23 |     },
  24 |     { projectId, name: projectName }
  25 |   );
  26 | }
  27 | 
  28 | test.describe("Persistent Scoring Runs, Phase 1", () => {
  29 |   test("Visual Intelligence Lab loads a durable scoring run from the URL and survives a refresh", async ({ page, context }, testInfo) => {
  30 |     test.setTimeout(3 * 60_000);
  31 |     const { dump } = attachDiagnostics(page, testInfo);
  32 |     const seed = JSON.parse(fs.readFileSync(SEED_PATH, "utf-8"));
  33 |     await resumeSession(page, context, seed.project_id, seed.cookies.atlas_session, "VI Lab Scoring Run Seed");
  34 | 
  35 |     const testRunId: string = seed.scoring_run_ids.test;
  36 |     await page.goto(`/visual-intelligence-lab?scoringRunId=${encodeURIComponent(testRunId)}`);
  37 | 
  38 |     // The selector reflects the URL-driven run, not a manual pick.
  39 |     await expect(page.getByTestId("vi-scoring-run-badge")).toBeVisible({ timeout: 20_000 });
  40 |     await expect(page.getByTestId("vi-scoring-run-select")).toHaveValue(testRunId);
  41 |     await shot(page, testInfo, "01-vi-lab-scoring-run-selected");
  42 | 
  43 |     // Distribution Explorer renders from the durable scoring-run source, not live workspace state.
  44 |     await expect(page.getByTestId("distribution-explorer")).toBeVisible({ timeout: 20_000 });
  45 |     await expect(page.getByTestId("variable-selector")).toBeVisible();
  46 |     await expect(page.getByTestId("scoring-run-source-badge").first()).toBeVisible({ timeout: 15_000 });
  47 |     await shot(page, testInfo, "02-vi-lab-distribution-scoring-run");
  48 | 
  49 |     // Regression Diagnostic Explorer also resolves from the same durable run.
  50 |     await page.getByTestId("vi-tab-regression").click();
  51 |     await expect(page.getByTestId("regression-diagnostic-explorer")).toBeVisible({ timeout: 20_000 });
  52 |     await expect(page.getByTestId("scoring-run-source-badge").first()).toBeVisible({ timeout: 15_000 });
  53 |     const regressionText = await page.locator('[data-testid="regression-diagnostic-explorer"]').innerText();
  54 |     expect(regressionText).toMatch(/RMSE/);
  55 |     await shot(page, testInfo, "03-vi-lab-regression-scoring-run");
  56 | 
  57 |     // The core durability claim: a hard refresh reloads the SAME run because its id
  58 |     // lives in the URL, not in React state -- unlike Step10_Scoring's plain useState.
  59 |     // (The active TAB itself is unrelated, ordinary React state -- Playwright must
  60 |     // re-select it after reload, same as a real user would see the default tab.)
  61 |     await page.reload();
  62 |     await expect(page.getByTestId("vi-scoring-run-select")).toHaveValue(testRunId, { timeout: 20_000 });
  63 |     await expect(page.getByTestId("distribution-explorer")).toBeVisible({ timeout: 20_000 });
  64 |     await expect(page.getByTestId("scoring-run-source-badge").first()).toBeVisible({ timeout: 15_000 });
  65 |     await shot(page, testInfo, "04-vi-lab-scoring-run-survives-refresh");
  66 | 
  67 |     // Switching back to "Live workspace data" clears the URL param and the durable badge.
  68 |     await page.getByTestId("vi-scoring-run-select").selectOption("");
  69 |     await expect(page.getByTestId("vi-scoring-run-badge")).toHaveCount(0);
  70 | 
  71 |     await dump();
  72 |   });
  73 | 
  74 |   test("Step10 Scoring page's history panel lists durable runs and links into the Visual Intelligence Lab", async ({ page, context }, testInfo) => {
  75 |     test.setTimeout(2 * 60_000);
  76 |     const { dump } = attachDiagnostics(page, testInfo);
  77 |     const seed = JSON.parse(fs.readFileSync(SEED_PATH, "utf-8"));
  78 |     await resumeSession(page, context, seed.project_id, seed.cookies.atlas_session, "VI Lab Scoring Run Seed");
  79 | 
> 80 |     await page.goto("/step10");
     |                ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  81 |     await expect(page.getByTestId("scoring-history-panel")).toBeVisible({ timeout: 20_000 });
  82 |     const rows = page.getByTestId("scoring-history-row");
  83 |     await expect(rows.first()).toBeVisible();
  84 |     expect(await rows.count()).toBeGreaterThanOrEqual(3); // TRAIN + TEST + OOT seeded runs
  85 |     await shot(page, testInfo, "05-step10-scoring-history-panel");
  86 | 
  87 |     // Reloading the page re-fetches history from the server, not from session state --
  88 |     // this is the concrete "refresh must never be the boundary" proof for Step10 itself.
  89 |     await page.reload();
  90 |     await expect(page.getByTestId("scoring-history-panel")).toBeVisible({ timeout: 20_000 });
  91 |     expect(await page.getByTestId("scoring-history-row").count()).toBeGreaterThanOrEqual(3);
  92 | 
  93 |     await dump();
  94 |   });
  95 | });
  96 | 
```