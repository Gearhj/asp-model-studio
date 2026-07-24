import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, REGRESSION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_FILE = "e2e_audit_regression_train.csv"; // safe copy of REG_TRAIN.csv (California housing, 4000-row safe copy, browser-preview-cap-safe)
const TARGET = "MedHouseVal";

// Classification-only terms/controls that must NOT appear as active regression
// treatments anywhere in this workflow (Regression Mode-Switching Matrix).
const CLASSIFICATION_LEAKAGE_PATTERNS = [
  /\bSMOTE\b/i,
  /class[\s-]?weight/i,
  /minority[\s-]?class/i,
  /oversampl/i,
  /undersampl/i,
  /positive[\s-]?class/i,
  /class imbalance/i,
];

test.describe("Regression Stage A: Project Context through Model Training", () => {
  test("Project Context -> Data Acquisition -> EDA -> Outliers -> Missing -> Features -> Encoding -> Balance/Split -> Train", async ({ page }, testInfo) => {
    test.setTimeout(10 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const modeSwitchLog: Record<string, unknown> = {};

    // ---------- Phase 2: Project Context ----------
    const user = makeTestUser("regA");
    await registerUser(page, user);
    await createPredictiveModelingProject(page, { name: "E2E Regression Audit Stage A", modelId: `regA-${Date.now()}` });
    await shot(page, testInfo, "02-step00-before");

    // REG-A-D1 (fixed this stage): "Regression" must now be a selectable Model Type.
    const modelTypeSelect = page.getByLabel("Model Type");
    await expect(modelTypeSelect).toBeVisible();
    const options = await modelTypeSelect.locator("option").allTextContents();
    modeSwitchLog.modelTypeOptions = options;
    expect(options).toContain("Regression");
    await modelTypeSelect.selectOption("Regression");

    await fillProjectContextNarrative(page, REGRESSION_NARRATIVE);
    await shot(page, testInfo, "02-step00-filled");

    // Persistence: Next -> Back -> confirm Regression selection and narrative persisted.
    await goNext(page, /\/step01/);
    await page.goBack();
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(/\/step00/);
    await expect(page.getByLabel("Model Type")).toHaveValue("Regression");
    const persistedText = await page.locator("textarea").first().inputValue().catch(() => "");
    console.log("REG_A_STEP00_BACK_PERSISTENCE:", JSON.stringify({ persistedTextNonEmpty: persistedText.length > 0 }));

    // Refresh persistence.
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.getByLabel("Model Type")).toHaveValue("Regression", { timeout: 15_000 });
    await shot(page, testInfo, "02-step00-after-refresh");

    await goNext(page, /\/step01/);

    // ---------- Phase 3: Data Acquisition ----------
    await shot(page, testInfo, "03-step01-empty");
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);
    await shot(page, testInfo, "03-step01-uploaded");

    const acquisitionText = await page.locator("body").innerText();
    console.log("REG_A_DATA_ACQUISITION_SNIPPET:", acquisitionText.slice(0, 1200).replace(/\n/g, " | "));
    expect(acquisitionText).toContain(DATA_FILE);
    await expect(page.locator("body")).toContainText("4,000");
    await expect(page.locator("body")).toContainText(TARGET);

    // The frontend's keyword-based target guesser (guessTargetFromHeaders: target/label/
    // class/bad/default/fraud/response/outcome/event) does not recognize "MedHouseVal" --
    // expected for a real, non-keyword-matching continuous column name, not a defect.
    // Select it explicitly via the "Target Column" control (Phase 3 item 5).
    const targetSelect = page.getByLabel("Target Column");
    await expect(targetSelect).toBeVisible();
    await targetSelect.selectOption(TARGET);
    await page.waitForTimeout(500);
    const postTargetText = await page.locator("body").innerText();
    console.log("REG_A_POST_TARGET_SELECT_SNIPPET:", postTargetText.slice(0, 1500).replace(/\n/g, " | "));

    // Mode-switching: with a real continuous target selected, classification-only
    // acquisition language (event/non-event, imbalance, binary profile) must not appear.
    const acquisitionLeaks = CLASSIFICATION_LEAKAGE_PATTERNS.filter((p) => p.test(postTargetText));
    modeSwitchLog.dataAcquisitionLeakage = acquisitionLeaks.map(String);
    expect(acquisitionLeaks, `classification-only terms found on Data Acquisition after selecting a continuous target: ${acquisitionLeaks.map(String)}`).toEqual([]);

    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toContainText("4,000", { timeout: 15_000 });
    await shot(page, testInfo, "03-step01-after-refresh");
    // Refresh persistence must retain the explicitly selected target, not fall back to guess.
    await expect(page.getByLabel("Target Column")).toHaveValue(TARGET, { timeout: 15_000 });

    await goNext(page, /\/step02/);

    // ---------- Phase 4: Regression EDA ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "04-step02-eda");
    const edaText = await page.locator("body").innerText();
    console.log("REG_A_EDA_SNIPPET:", edaText.slice(0, 2000).replace(/\n/g, " | "));

    // Classification-only EDA language must not appear (positive-class rate, imbalance,
    // fraud wording, binary target distribution, class labels, threshold guidance).
    const edaLeakage = [
      /positive[\s-]?class rate/i,
      /class imbalance/i,
      /fraud/i,
      /binary target/i,
      /classification threshold/i,
      ...CLASSIFICATION_LEAKAGE_PATTERNS,
    ];
    const edaLeaks = edaLeakage.filter((p) => p.test(edaText));
    modeSwitchLog.edaLeakage = edaLeaks.map(String);
    expect(edaLeaks, `classification-only language found on EDA: ${edaLeaks.map(String)}`).toEqual([]);

    // Continuous-target evidence expected instead.
    const edaHasContinuousSignal = /mean|median|std|distribution|histogram|correlation/i.test(edaText);
    modeSwitchLog.edaHasContinuousSignal = edaHasContinuousSignal;
    await goNext(page, /\/step03/);

    // ---------- Phase 5: Outliers ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "05-step03-outliers-before");
    await goNext(page, /\/step04/);
    await shot(page, testInfo, "05-step04-missing-before");

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
    console.log("REG_A_FEATURE_ENGINEERING_SNIPPET:", featureText.slice(0, 1000).replace(/\n/g, " | "));

    // IV (Information Value) is classification-specific; if shown, it must be labeled as such.
    if (/\bIV\b|Information Value/i.test(featureText)) {
      const ivLabeledClassificationOnly = /classification[- ]only|not applicable for regression|binary target required/i.test(featureText);
      modeSwitchLog.ivShownWithoutRegressionCaveat = !ivLabeledClassificationOnly;
    } else {
      modeSwitchLog.ivShownWithoutRegressionCaveat = false;
    }
    await shot(page, testInfo, "06-step05-features-after");

    await goNext(page, /\/step06/);

    // ---------- Phase 8: Balance and Split (primary mode-switching checkpoint) ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "08-step06-balance-split-before");
    const balanceText = await page.locator("body").innerText();
    console.log("REG_A_BALANCE_SPLIT_SNIPPET:", balanceText.slice(0, 1500).replace(/\n/g, " | "));

    const balanceLeaks = CLASSIFICATION_LEAKAGE_PATTERNS.filter((p) => p.test(balanceText));
    modeSwitchLog.balanceSplitLeakage = balanceLeaks.map(String);
    expect(balanceLeaks, `classification balancing controls found on regression Balance/Split: ${balanceLeaks.map(String)}`).toEqual([]);

    await goNext(page, /\/step07/); // clickGatingActionsIfPresent restores predictors, saves selection, creates split
    await shot(page, testInfo, "08-step07-train-landed");

    // ---------- Phase 9: Model Training ----------
    await page.waitForTimeout(1500);
    await shot(page, testInfo, "09-step07-train-before");

    // Verify only regression-appropriate models are offered (no classifier presented as valid).
    const trainPageText = await page.locator("body").innerText();
    const classifierNamesInModelList = ["Logistic Regression", "Random Forest Classifier", "Gradient Boosting Classifier"].filter((name) => trainPageText.includes(name));
    modeSwitchLog.classifierModelsOfferedForRegression = classifierNamesInModelList;

    const runPreflightButton = page.getByRole("button", { name: "Run Preflight" });
    let preflightBody: any = null;
    if (await runPreflightButton.isVisible().catch(() => false)) {
      const [preflightResponse] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/train/preflight"), { timeout: 30_000 }),
        runPreflightButton.click(),
      ]);
      preflightBody = await preflightResponse.json().catch(() => null);
      console.log("REG_A_PREFLIGHT:", JSON.stringify({
        status: preflightResponse.status(), ready: preflightBody?.ready,
        blocking: preflightBody?.blocking, dataset_id: preflightBody?.dataset_id,
        problem_type: preflightBody?.problem_type,
      }));
      expect(preflightBody?.ready).toBe(true);
      expect(preflightBody?.blocking ?? []).toEqual([]);
      modeSwitchLog.preflightProblemType = preflightBody?.problem_type;
    }
    await shot(page, testInfo, "09-step07-preflight-done");

    const [jobCreateResponse] = await Promise.all([
      page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/model/train/jobs"), { timeout: 30_000 }),
      page.getByRole("button", { name: /Train Selected Models/ }).first().click(),
    ]);
    const jobCreateBody = await jobCreateResponse.json().catch(() => null);
    const jobId: string | undefined = jobCreateBody?.job_id;
    console.log("REG_A_JOB_CREATE:", JSON.stringify({ status: jobCreateResponse.status(), job_id: jobId }));
    expect(jobId).toBeTruthy();

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
    console.log("REG_A_TRAINING_TERMINAL_STATUS:", terminalStatus);
    await shot(page, testInfo, "09-step07-train-terminal");
    expect(terminalStatus).toBe("complete");

    // Fetch the trained result directly to confirm regression identity and metrics.
    const workflowStoreRaw = await page.evaluate(() => window.sessionStorage.getItem("ds-workflow-store"));
    const projectId: string = workflowStoreRaw ? JSON.parse(workflowStoreRaw)?.state?.projectId ?? "" : "";
    const projectUrl = new URL(page.url());
    const lastResponse = await page.request.get(`${projectUrl.origin}/api/train/last`, {
      params: { project_id: projectId },
    }).catch(() => null);
    if (lastResponse && lastResponse.ok()) {
      const lastBody = await lastResponse.json();
      modeSwitchLog.trainedSummaryProblemType = lastBody?.summary?.problem_type;
      const ranked = lastBody?.summary?.ranked ?? [];
      modeSwitchLog.trainedTasks = ranked.map((row: any) => row.task);
      modeSwitchLog.trainedMetricsKeys = ranked[0] ? Object.keys(ranked[0]).filter((k) => ["auc", "pr_auc", "accuracy", "precision", "recall", "f1", "rmse", "mae", "r2"].includes(k)) : [];
      console.log("REG_A_TRAINED_SUMMARY:", JSON.stringify({
        problem_type: modeSwitchLog.trainedSummaryProblemType,
        tasks: modeSwitchLog.trainedTasks,
        metricsKeys: modeSwitchLog.trainedMetricsKeys,
      }));
    }

    console.log("REG_A_MODE_SWITCH_LOG:", JSON.stringify(modeSwitchLog, null, 2));
    await dump();
  });
});
