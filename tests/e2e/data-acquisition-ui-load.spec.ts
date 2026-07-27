import { test, expect } from "@playwright/test";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

// The COMPLETE CLASS_TRAIN registration, selected by id. The older same-named
// registration has no full artifact and is not used here.
const DATASET_ID = "ds_class_train_982c7a7d_35930";
const VERSION_ID = "v_1784989835930_982c7a7d";

const EXPECTED = { rows: 170884, columns: 31, events: 360, nonEvents: 170524, duplicates: 52, missingColumns: 29 };

test.describe("Data Acquisition: UI-driven Dataset Version load", () => {
  // The pinned version is owned by the local development user; the dataset ACL
  // correctly refuses anyone else, so the walkthrough runs AS the owner rather
  // than weakening the ACL. A dedicated E2E project is created each run so the
  // user's real project is never touched.
  test.use({ extraHTTPHeaders: { "X-ATLAS-USER-ID": "local-user" } });

  test("selects and loads the exact version through the UI, then reconciles the loaded page", async ({ page }, testInfo) => {
    test.setTimeout(15 * 60_000);
    const { log, dump } = attachDiagnostics(page, testInfo);

    // ---------- 1-3. Open a dedicated project and reach Data Acquisition ---
    await createPredictiveModelingProject(page, {
      name: `E2E Data Acquisition UI Load ${Date.now()}`,
      modelId: `00001-${Date.now()}`,
    });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await expect(page.getByTestId("atlas-breadcrumb-current")).toHaveText("Data Acquisition");

    // ---------- 4. Choose the Existing Dataset source in the UI ------------
    //
    // ROOT CAUSE of the previous run's unloaded screenshots: the earlier spec
    // linked the version over the API and reloaded. `sourceType` defaults to
    // "upload" and `selectedLibraryDatasetId` starts empty, so the page had
    // genuinely selected nothing -- correct behaviour, wrong test. The UI
    // selection below is what actually drives the load.
    await page.getByTestId("source-card-existing").click();
    const loadCommand = page.getByTestId("dataset-load-command");
    await expect(loadCommand).toBeVisible({ timeout: 60_000 });

    // ---------- 5. Select the exact dataset and version -------------------
    const datasetSelect = loadCommand.locator("select").first();
    const versionSelect = loadCommand.locator("select").nth(1);
    await expect(datasetSelect).toBeVisible();
    await datasetSelect.selectOption(DATASET_ID);
    await expect(versionSelect).toBeEnabled();
    await versionSelect.selectOption(VERSION_ID);
    await expect(datasetSelect).toHaveValue(DATASET_ID);
    await expect(versionSelect).toHaveValue(VERSION_ID);

    // ---------- Part C 1-5. Pre-load identity is truthful -----------------
    const loadButton = page.getByTestId("load-selected-version");
    await expect(loadButton).toHaveAttribute("data-load-state", "unloaded");
    await expect(loadButton).toHaveText(/Load Selected Version/);
    const beforeText = await page.locator("body").innerText();
    expect(beforeText, "a registered Library asset is never 'Not registered'").not.toContain("Not registered");
    expect(beforeText).toMatch(/Registration\s*Registered/i);
    expect(beforeText).toMatch(/Selected, not loaded/i);
    await shot(page, testInfo, "ui-01-selected-registered-not-loaded");

    // ---------- 6-7. Click Load and observe REAL loading ------------------
    await loadButton.click();
    // The button reports its own real state; no sleep is used.
    await expect(loadButton).toHaveAttribute("data-load-state", /loading|loaded/, { timeout: 30_000 });
    const progress = page.getByTestId("dataset-load-progress");
    await expect(progress).toBeVisible({ timeout: 30_000 });
    await shot(page, testInfo, "ui-02-loading-active-milestone");

    // ---------- 8. All seven real milestones complete ---------------------
    await expect(loadButton).toHaveAttribute("data-load-state", "loaded", { timeout: 8 * 60_000 });
    await expect(loadButton).toHaveText(/Version Loaded/);
    const milestoneCount = page.getByTestId("dataset-load-milestone-count");
    await expect(milestoneCount).toContainText("7 of 7", { timeout: 60_000 });
    await expect(page.getByTestId("dataset-loaded-identity")).toContainText(VERSION_ID);
    await shot(page, testInfo, "ui-03-seven-milestones-version-loaded");

    // ---------- Confirm the target and event mapping in the UI ------------
    // Without a confirmed target the page is genuinely blocked, so this is a
    // real step of the flow rather than test scaffolding.
    const targetSelect = page.getByLabel("Target Column");
    await expect(targetSelect).toBeVisible({ timeout: 60_000 });
    await targetSelect.selectOption("Class");
    await page.getByLabel("Event / Positive Value").fill("1");
    await page.getByLabel("Non-event / Negative Value").fill("0");
    await expect(targetSelect).toHaveValue("Class");

    // ---------- 9. Loaded results reconcile on the page -------------------
    const body = page.locator("body");
    await expect(body).toContainText("170,884", { timeout: 120_000 });
    const loadedText = await body.innerText();
    for (const value of ["170,884", "31"]) {
      expect(loadedText, `expected ${value} on the loaded page`).toContain(value);
    }
    // Governed profiling populates the quality figures; await them explicitly.
    await expect(body).toContainText("52", { timeout: 8 * 60_000 });
    await expect(body).toContainText("29");

    // ---------- 10-12. One lifecycle story, no contradiction -------------
    // Confirming the target restarts governed profiling, so the checkpoint
    // unmounts and remounts. Wait for profiling to settle before reading the
    // lifecycle labels -- no sleep, just the real completion signal.
    await expect(page.getByTestId("predictor-evaluation-summary")).toBeVisible({ timeout: 10 * 60_000 });
    const summaryStatus = page.getByTestId("readiness-summary-status");
    await expect(summaryStatus).toBeVisible({ timeout: 120_000 });
    const summaryText = await summaryStatus.innerText();
    console.log("UI_LOAD_LIFECYCLE:", summaryText);
    expect(summaryText).toMatch(/Analytical readiness:/);
    expect(summaryText).toMatch(/User review:/);

    const badge = page.getByTestId("readiness-status-badge");
    const badgeReadiness = await badge.getAttribute("data-readiness-status");
    const heroText = await body.innerText();
    const heroMatch = heroText.match(/Modeling Readiness\s*(Blocked|Ready with warnings|Ready|Not evaluated)/i);
    console.log("UI_LOAD_READINESS:", JSON.stringify({ badgeReadiness, hero: heroMatch?.[1] }));
    // The checkpoint badge and the hero are the SAME derivation, so they agree.
    if (heroMatch) {
      const heroValue = heroMatch[1].toLowerCase().replace(/\s+/g, "_");
      expect(badgeReadiness).toBe(heroValue);
    }
    expect(badgeReadiness).not.toBe("blocked");

    await shot(page, testInfo, "ui-04-unified-readiness-and-review");

    // ---------- 13-16. Predictor semantics -------------------------------
    await expect(page.getByTestId("predictor-evaluation-summary")).toBeVisible({ timeout: 8 * 60_000 });
    await expect(page.getByTestId("predictors-evaluated")).toContainText("30 predictors evaluated");
    await expect(page.getByTestId("target-exclusion-note")).toContainText("Target excluded from predictor IV");
    await expect(page.getByTestId("target-exclusion-note")).toContainText("Class");

    const variableText = await body.innerText();
    expect(variableText).toContain("Unusually strong");
    expect(variableText).toContain("review recommended");
    expect(variableText, "high IV must never be presented as confirmed leakage").not.toContain("Confirmed leakage");
    expect(variableText).not.toContain("Likely leakage");
    // The target is not a predictor defect.
    expect(variableText).not.toMatch(/Near-Zero Variance[\s\S]{0,80}\bClass\b/i);
    await shot(page, testInfo, "ui-05-variable-summary-high-iv-and-counts");

    // ---------- 17. No page errors caused by this phase -------------------
    console.log("UI_LOAD_FAILED_RESPONSES:", JSON.stringify(log.failedResponses));
    const phaseFailures = log.failedResponses.filter((entry) =>
      /\/api\/(data\/target-profile|datasets\/.*\/activate)/.test(entry)
    );
    expect(phaseFailures, `load/profile failures: ${phaseFailures.join(" | ")}`).toEqual([]);
    expect(log.pageErrors, `uncaught page errors: ${log.pageErrors.join(" | ")}`).toEqual([]);

    await dump();
  });
});
