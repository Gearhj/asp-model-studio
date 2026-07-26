import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// 4,000-row safe copy of CLASS_TRAIN. The exact counts differ from the full
// 170,884-row asset; what is asserted here is that the page reports the EXACT
// server-side counts for whatever population is registered, and that they
// reconcile -- not a hard-coded number that only holds for one file.
const DATA_FILE = "e2e_audit_classification_dev.csv";

function parseCount(text: string): number {
  return Number(text.replace(/[^\d]/g, "")) || 0;
}

test.describe("EDA Target Intelligence walkthrough", () => {
  test("Target tab: identity, exact class balance, rare-event detail, confidence interval, V4 quantile analysis, finding persistence", async ({ page }, testInfo) => {
    test.setTimeout(10 * 60_000);
    const { log, dump } = attachDiagnostics(page, testInfo);

    // ---------- Setup: project, governance narrative, registered dataset ----
    const user = makeTestUser("targetIntel");
    await registerUser(page, user);
    await createPredictiveModelingProject(page, {
      name: "E2E Target Intelligence",
      modelId: `targetIntel-${Date.now()}`,
    });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);

    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);
    await expect(page.locator("body")).toContainText("Class");
    await goNext(page, /\/step02/);

    // ---------- 1. Open the Target tab ------------------------------------
    await page.getByRole("tab", { name: "Target" }).click();
    const workspace = page.getByTestId("target-intelligence-workspace");
    await expect(workspace).toBeVisible({ timeout: 60_000 });

    // ---------- Screenshot: Target Identity --------------------------------
    const identity = page.getByTestId("target-identity");
    await expect(identity).toBeVisible();
    await expect(identity).toContainText("Target Identity");
    await expect(page.getByTestId("target-identity-column")).toContainText("Class");
    await expect(page.getByTestId("target-identity-rows")).not.toBeEmpty();
    // Governance narrative is read from the durable backend Project Context.
    await expect(page.getByTestId("governance-targetDefinition")).toContainText("chargeback", { ignoreCase: true });
    await expect(page.getByTestId("governance-populationDefinition")).toContainText("authorization", { ignoreCase: true });
    await shot(page, testInfo, "target-01-identity");

    // ---------- 2. Verify exact counts -------------------------------------
    const balance = page.getByTestId("target-class-balance");
    await expect(balance).toBeVisible();
    await expect(page.getByTestId("target-event-count")).not.toContainText("Not available", { timeout: 60_000 });

    const eventCount = parseCount(await page.getByTestId("target-event-count").innerText());
    const nonEventCount = parseCount(await page.getByTestId("target-non-event-count").innerText());
    const totalPopulation = parseCount(await page.getByTestId("target-total-population").innerText());
    console.log("TARGET_INTELLIGENCE_CLASS_BALANCE:", JSON.stringify({ eventCount, nonEventCount, totalPopulation }));

    expect(eventCount).toBeGreaterThan(0);
    expect(nonEventCount).toBeGreaterThan(0);
    // Exactness: the parts must reconcile to the whole with no rounding slack.
    expect(eventCount + nonEventCount).toBe(totalPopulation);

    const eventRateText = await page.getByTestId("target-event-rate").innerText();
    const eventRate = Number(eventRateText.replace(/[^\d.]/g, "")) / 100;
    expect(Math.abs(eventRate - eventCount / totalPopulation)).toBeLessThan(0.001);
    await shot(page, testInfo, "target-02-class-balance");

    // ---------- 3. Population Scale <-> Rare-Event Detail -------------------
    const rareEventToggle = page.getByRole("button", { name: "Rare-Event Detail" });
    if (await rareEventToggle.isVisible().catch(() => false)) {
      await rareEventToggle.click();
      await expect(page.getByTestId("rare-event-scale-disclosure")).toBeVisible();
      await expect(page.getByTestId("rare-event-scale-disclosure")).toContainText("Adjusted scale");
      await shot(page, testInfo, "target-03-rare-event-detail");
      await page.getByRole("button", { name: "Population Scale" }).click();
      await expect(page.getByTestId("rare-event-scale-disclosure")).toBeHidden();
    }

    // Rare-event assessment section with its documented rule.
    const rareEvent = page.getByTestId("target-rare-event-assessment");
    await expect(rareEvent).toBeVisible();
    const imbalanceLabel = await page.getByTestId("target-imbalance-label").innerText();
    console.log("TARGET_INTELLIGENCE_IMBALANCE:", imbalanceLabel);
    expect(imbalanceLabel).toMatch(/Balanced|Mild imbalance|Moderate imbalance|Severe imbalance|Extreme rare event/);
    await expect(page.getByTestId("target-imbalance-implications")).toContainText("PR-AUC");
    await expect(page.getByTestId("target-no-automatic-treatment")).toContainText("has not enabled SMOTE");
    await shot(page, testInfo, "target-04-rare-event-assessment");

    // ---------- 4. Inspect the confidence interval -------------------------
    const interval = page.getByTestId("target-confidence-interval");
    await expect(interval).toBeVisible();
    await expect(page.getByTestId("ci-method")).toContainText("Wilson score interval");
    await expect(page.getByTestId("ci-confidence-level")).toContainText("95%");
    const lower = Number((await page.getByTestId("ci-lower-bound").innerText()).replace(/[^\d.]/g, ""));
    const point = Number((await page.getByTestId("ci-point-estimate").innerText()).replace(/[^\d.]/g, ""));
    const upper = Number((await page.getByTestId("ci-upper-bound").innerText()).replace(/[^\d.]/g, ""));
    console.log("TARGET_INTELLIGENCE_INTERVAL:", JSON.stringify({ lower, point, upper }));
    expect(lower).toBeLessThanOrEqual(point);
    expect(point).toBeLessThanOrEqual(upper);
    await expect(page.getByTestId("ci-explanation")).toContainText("does not measure model-performance uncertainty");
    await shot(page, testInfo, "target-05-confidence-interval");

    // ---------- 5 / 6. Select V4 and run target-by-quantile -----------------
    // Nothing has been analyzed yet: the panel must be idle, not pre-computed.
    await expect(page.getByTestId("target-predictor-phase")).toHaveAttribute("data-query-phase", "idle");

    await page.getByTestId("target-predictor-search").fill("V4");
    await page.getByTestId("target-predictor-select").selectOption("V4");
    await expect(page.getByTestId("target-analysis-type")).toHaveValue("numeric_quantile");
    await page.getByTestId("target-band-count").fill("10");
    await page.getByTestId("target-run-analysis").click();

    // ---------- 7. Verify the chart and the analytical summary --------------
    await expect(page.getByTestId("target-by-predictor-table")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("target-predictor-phase")).not.toHaveAttribute("data-query-phase", "idle");
    const bandRows = page.getByTestId("target-by-predictor-table").locator("tbody tr");
    expect(await bandRows.count()).toBeGreaterThanOrEqual(10);
    await expect(page.getByTestId("target-predictor-analytical-summary")).toBeVisible();
    await expect(page.getByTestId("target-predictor-interpretation")).toContainText("does not establish predictive value");
    // The rendered chart exists and is described for assistive technology.
    await expect(page.locator('[data-visual-intelligence-chart="true"]').first()).toBeVisible();
    await shot(page, testInfo, "target-06-v4-target-by-quantile");

    // ---------- 8. Segment analysis is empty until a field is chosen --------
    await expect(page.getByTestId("target-no-segment-field")).toContainText("No segment field selected.");
    const segmentSelect = page.getByTestId("target-segment-field-select");
    const segmentOptions = await segmentSelect.locator("option").allTextContents();
    const firstSegment = segmentOptions.find((label) => label && !label.startsWith("No segment"));
    if (firstSegment) {
      await segmentSelect.selectOption({ label: firstSegment });
      await page.waitForTimeout(3000);
      await expect(page.getByTestId("target-segment-table")).toBeVisible({ timeout: 60_000 });
    } else {
      // No governed segment candidate exists in this fixture -- the honest empty
      // state must remain, and no chart shell may be rendered.
      await expect(page.getByTestId("target-no-segment-field")).toBeVisible();
    }
    // Time analysis must NOT be offered for the numeric "Time" column.
    await expect(page.getByTestId("target-no-governed-time-field")).toContainText("No governed time field has been selected.");

    // ---------- Screenshot: Target Quality and Leakage ---------------------
    const quality = page.getByTestId("target-quality-leakage");
    await expect(quality).toBeVisible();
    await expect(page.getByTestId("leakage-assessment-rule")).toContainText("Confirmed leakage");
    await expect(page.getByTestId("leakage-assessment-rule")).toContainText("never sufficient");
    await shot(page, testInfo, "target-07-quality-and-leakage");

    // ---------- 9. Add a finding -------------------------------------------
    const findingTitle = `Extreme rare-event prevalence confirmed ${Date.now()}`;
    await page.getByTestId("target-finding-title").fill(findingTitle);
    await page.getByTestId("target-finding-detail").fill(
      "Exact server-side counts confirm the observed prevalence; stratified splitting and PR-AUC are required downstream."
    );
    await page.getByTestId("target-finding-severity").selectOption("warning");
    await page.getByTestId("target-finding-save").click();
    await expect(page.getByText(findingTitle)).toBeVisible({ timeout: 30_000 });
    await shot(page, testInfo, "target-08-finding-saved");

    // ---------- 10. Save the analysis to evidence --------------------------
    await page.getByTestId("target-save-evidence").click();
    await expect(page.getByTestId("target-findings-message")).toContainText("evidence", {
      ignoreCase: true,
      timeout: 30_000,
    });

    // ---------- 11 / 12. Refresh and verify the finding persists ------------
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.getByRole("tab", { name: "Target" }).click();
    await expect(page.getByTestId("target-intelligence-workspace")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(findingTitle)).toBeVisible({ timeout: 60_000 });

    // Mark reviewed, and confirm the durable status change survives.
    const savedFinding = page.getByTestId("target-finding-item").filter({ hasText: findingTitle }).first();
    await savedFinding.getByTestId("target-finding-review").click();
    await expect(savedFinding).toHaveAttribute("data-finding-status", "reviewed", { timeout: 30_000 });
    await shot(page, testInfo, "target-09-finding-persisted-after-refresh");

    // No console errors were introduced by this phase.
    //
    // Browser "Failed to load resource" console lines carry no URL, so they are
    // matched against the recorded failed responses instead. Only failures on
    // this phase's own endpoints are attributable here; pre-authentication 401s
    // and unrelated pre-existing routes are reported but not asserted on, so
    // this spec never fails for a defect it did not introduce.
    const PHASE_ENDPOINTS = /\/api\/(analytics\/target-(assessment|by-predictor|findings)|eda\/target-by-predictor|eda\/workspace\/target)/;
    const phaseFailures = log.failedResponses.filter((entry) => PHASE_ENDPOINTS.test(JSON.stringify(entry)));
    console.log("TARGET_INTELLIGENCE_FAILED_RESPONSES:", JSON.stringify(log.failedResponses));
    console.log("TARGET_INTELLIGENCE_PHASE_FAILURES:", JSON.stringify(phaseFailures));
    console.log("TARGET_INTELLIGENCE_CONSOLE_ERRORS:", JSON.stringify(log.consoleErrors));
    expect(phaseFailures, `Target Intelligence endpoints failed: ${JSON.stringify(phaseFailures)}`).toEqual([]);

    // No uncaught page errors (the class of console error this phase could cause).
    expect(log.pageErrors, `Uncaught page errors: ${log.pageErrors.join(" | ")}`).toEqual([]);

    await dump();
  });
});
