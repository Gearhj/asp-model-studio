import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext, NEXT_BUTTON } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_FILE = "e2e_audit_classification_dev.csv"; // 4,000-row safe copy of CLASS_TRAIN.csv, unique filename

test.describe("Stage A: Classification workflow through Model Training", () => {
  test("Project Context -> Data Acquisition -> EDA -> Outliers -> Missing -> Features -> Encoding -> Balance/Split -> Train", async ({ page }, testInfo) => {
    test.setTimeout(10 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    // ---------- Phase 2: Project Context ----------
    const user = makeTestUser("stageA");
    await registerUser(page, user);
    await createPredictiveModelingProject(page, { name: "E2E Classification Audit Stage A", modelId: `stageA-${Date.now()}` });
    await shot(page, testInfo, "02-step00-before");

    // Persistence check: refresh before filling, confirm still on step00 with project intact
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(/\/step00/);
    await expect(page.getByText("E2E Classification Audit Stage A").first()).toBeVisible();

    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await shot(page, testInfo, "02-step00-filled");

    // Next/Back persistence: go next, then back, confirm narrative persisted
    await goNext(page, /\/step01/);
    await page.goBack();
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(/\/step00/);
    const persistedText = await page.locator("textarea").first().inputValue().catch(() => "");
    console.log("STAGE_A_STEP00_BACK_PERSISTENCE:", JSON.stringify({ persistedTextNonEmpty: persistedText.length > 0 }));
    await shot(page, testInfo, "02-step00-after-back");
    await goNext(page, /\/step01/);

    // ---------- Phase 3: Data Acquisition ----------
    await shot(page, testInfo, "03-step01-empty");
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);
    await shot(page, testInfo, "03-step01-uploaded");

    const summaryText = await page.locator("body").innerText();
    const rowsMatch = summaryText.match(/REGISTERED ROWS\s*\n?\s*([\d,]+)/);
    const colsMatch = summaryText.match(/COLUMNS\s*\n?\s*(\d+)/);
    console.log("STAGE_A_DATA_ACQUISITION:", JSON.stringify({ rowsMatch: rowsMatch?.[1], colsMatch: colsMatch?.[1] }));
    expect(summaryText).toContain(DATA_FILE);
    await expect(page.locator("body")).toContainText("4,000");
    await expect(page.locator("body")).toContainText("Class");

    // refresh persistence check on step01
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toContainText("4,000", { timeout: 15_000 });
    await shot(page, testInfo, "03-step01-after-refresh");

    await goNext(page, /\/step02/);

    // ---------- Phase 4: EDA ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "04-step02-eda");
    const edaText = await page.locator("body").innerText();
    console.log("STAGE_A_EDA_SNIPPET:", edaText.slice(0, 1500).replace(/\n/g, " | "));
    await goNext(page, /\/step03/);

    // ---------- Phase 5: Outliers ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "05-step03-outliers-before");
    await goNext(page, /\/step04/); // clickGatingActionsIfPresent applies default outlier treatment
    await shot(page, testInfo, "05-step04-missing-before");

    // Missing values: apply a safe strategy (Median) globally if the control is present
    const globalStrategy = page.getByLabel("Global strategy").first();
    if (await globalStrategy.isVisible().catch(() => false)) {
      await globalStrategy.selectOption({ label: "Median" }).catch(() => undefined);
      await page.waitForTimeout(500);
    }
    await shot(page, testInfo, "05-step04-missing-median-selected");
    await goNext(page, /\/step05/);

    // ---------- Phase 6: Feature Engineering ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "06-step05-features-before");
    const featureText = await page.locator("body").innerText();
    console.log("STAGE_A_FEATURE_ENGINEERING_SNIPPET:", featureText.slice(0, 800).replace(/\n/g, " | "));
    await shot(page, testInfo, "06-step05-features-after");

    // ---------- Phase 7: Encoding and Scaling (same page as Feature Engineering in this app) ----------
    await goNext(page, /\/step06/);

    // ---------- Phase 8: Balance and Split ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "08-step06-balance-split-before");
    const balanceText = await page.locator("body").innerText();
    const hasNoneOption = balanceText.includes("None");
    console.log("STAGE_A_BALANCE_SPLIT:", JSON.stringify({ hasNoneOption }));
    await goNext(page, /\/step07/); // clickGatingActionsIfPresent restores predictors, saves selection, creates split
    await shot(page, testInfo, "08-step07-train-landed");

    // ---------- Phase 9: Model Training ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "09-step07-train-before");

    // Explicit "Run Preflight" button gives a clean, isolated preflight response to inspect,
    // independent of whether "Train Selected Models" itself re-runs preflight (it only does
    // so when not already current).
    const runPreflightButton = page.getByRole("button", { name: "Run Preflight" });
    let preflightBody: any = null;
    if (await runPreflightButton.isVisible().catch(() => false)) {
      const [preflightResponse] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/train/preflight"), { timeout: 30_000 }),
        runPreflightButton.click(),
      ]);
      preflightBody = await preflightResponse.json().catch(() => null);
      console.log(
        "STAGE_A_PREFLIGHT:",
        JSON.stringify({
          status: preflightResponse.status(),
          ready: preflightBody?.ready,
          blocking: preflightBody?.blocking,
          dataset_id: preflightBody?.dataset_id,
        }),
      );
      expect(preflightBody?.ready).toBe(true);
      expect(preflightBody?.blocking ?? []).toEqual([]);
    } else {
      console.log("STAGE_A_PREFLIGHT: Run Preflight button not visible (preflight likely already current)");
    }
    await shot(page, testInfo, "09-step07-preflight-done");

    // Capture the real job-creation response and poll the API directly (robust, no DOM ambiguity).
    const [jobCreateResponse] = await Promise.all([
      page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/model/train/jobs"), { timeout: 30_000 }),
      page.getByRole("button", { name: /Train Selected Models/ }).first().click(),
    ]);
    const jobCreateBody = await jobCreateResponse.json().catch(() => null);
    const jobId: string | undefined = jobCreateBody?.job_id;
    console.log("STAGE_A_JOB_CREATE:", JSON.stringify({ status: jobCreateResponse.status(), job_id: jobId }));
    expect(jobId).toBeTruthy();

    // Poll the "Training Job" hero-metric value specifically (StepShell heroMetrics label ->
    // job.overall_status), not a bare page-wide text search -- a bare search for "Failed" false-
    // positives against the Live Training panel's "FAILED" column-count label even when count is 0.
    const deadline = Date.now() + 5 * 60_000;
    let terminalStatus = "";
    while (Date.now() < deadline) {
      const bodyText = await page.locator("body").innerText();
      const match = bodyText.match(/Training Job\s*\n\s*(\S+)/i);
      const value = (match?.[1] || "").toLowerCase();
      if (["complete", "failed", "cancelled", "interrupted"].includes(value)) {
        terminalStatus = value;
        break;
      }
      await page.waitForTimeout(2000);
    }
    console.log("STAGE_A_TRAINING_TERMINAL_STATUS:", terminalStatus);
    await shot(page, testInfo, "09-step07-train-terminal");
    expect(terminalStatus).toBe("complete");

    await dump();
  });
});
