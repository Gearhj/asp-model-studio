import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { shot } from "./helpers/screenshots";
import { attachDiagnostics } from "./helpers/diagnostics";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// 4,000-row safe copy of CLASS_TRAIN.csv -- a genuine rare-event classification
// dataset, which is what makes the Part F event-rate assertions meaningful.
const DATA_FILE = "e2e_audit_classification_dev.csv";

/**
 * UX-DATAACQ-001..004 + Part H. Covers both persistence paths through the real UI:
 * a new workspace upload (which must keep the workspace-vs-register choice) and a
 * registered Dataset Library asset loaded into a second project (which must show a
 * read-only registered status panel and a full load lifecycle instead).
 */
test.describe("Data Acquisition UX and lifecycle", () => {
  test("new upload keeps persistence choices, shows readiness, and reports a true rare-event rate", async ({ page }, testInfo) => {
    test.setTimeout(6 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    await registerUser(page, makeTestUser("dataAcqUpload"));
    await createPredictiveModelingProject(page, { name: "E2E Data Acquisition Upload", modelId: `daUp-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);

    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);
    await page.getByLabel("Target Column").selectOption("Class");
    // Backend quality profiling supplies the authoritative full-population aggregates.
    await page.waitForTimeout(6000);

    // Part C2: an unregistered upload still gets both persistence choices.
    const persistenceCard = page.getByTestId("dataset-persistence-card");
    await expect(persistenceCard).toBeVisible();
    await expect(persistenceCard).toHaveAttribute("data-persistence-mode", "choice");
    await expect(page.getByRole("button", { name: "Project Workspace Only" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Register in Dataset Library" })).toBeVisible();
    await expect(page.getByTestId("persistence-source-label")).toHaveText("Workspace Upload");
    await expect(page.getByTestId("already-linked-badge")).toHaveCount(0);
    await shot(page, testInfo, "06-new-upload-persistence-choices");

    // Part E: modeling rows and browser preview rows are separately labelled.
    await expect(page.getByText("Modeling Rows", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Browser Preview Rows", { exact: true }).first()).toBeVisible();
    // The note always states the modeling population; its second sentence depends on
    // whether the browser holds the complete dataset or only a bounded preview.
    const rowNote = page.getByTestId("modeling-vs-preview-note");
    await expect(rowNote).toContainText("rows are available for backend modeling");
    await expect(rowNote).toContainText(/The browser holds the complete dataset\.|does not reduce the modeling population/);

    // Part D + H4: the readiness checkpoint is present, toned, and status-badged.
    const readiness = page.getByTestId("data-quality-readiness");
    await expect(readiness).toBeVisible();
    const readinessBg = await readiness.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(readinessBg, "readiness section must not be flat grey/white").not.toBe("rgb(255, 255, 255)");
    const badge = page.getByTestId("readiness-status-badge");
    await expect(badge).toBeVisible();
    const status = await badge.getAttribute("data-readiness-status");
    expect(["ready", "ready_with_warnings", "review_required", "blocked"]).toContain(status);
    await expect(page.getByTestId("readiness-summary")).toBeVisible();
    await shot(page, testInfo, "05-data-quality-readiness");

    // Part F: the event rate must reflect the full population, never a 0.00% derived
    // from the 100-row browser preview of a rare-event dataset.
    const eventRateStat = page.getByTestId("target-profile-event-rate");
    await expect(eventRateStat).toBeVisible();
    const eventRateText = (await eventRateStat.textContent()) ?? "";
    expect(eventRateText, "event rate must not collapse to zero for a rare-event target").not.toMatch(/\b0\.00%/);
    const formattedRate = eventRateText.match(/[\d.]+%/)?.[0] ?? "";
    const parsedRate = Number(formattedRate.replace("%", ""));
    expect(parsedRate, "CLASS_TRAIN's event rate is a small but nonzero percentage").toBeGreaterThan(0);
    expect(parsedRate).toBeLessThan(5);
    // The scope must be an authoritative population, never the browser preview.
    await expect(eventRateStat).toContainText(/Full registered population|Complete browser dataset/);
    await expect(eventRateStat).not.toContainText("Preview only");
    await expect(page.getByTestId("preview-only-event-rate-warning")).toHaveCount(0);

    // Part H3: the distribution chart uses the same authoritative aggregates.
    const distribution = page.getByTestId("target-distribution-panel");
    await expect(distribution).toBeVisible();
    // The chart, the Target Profile stat, and the accessible summary must all report
    // the identical formatted rate -- they read the same authoritative aggregate.
    const chartRate = (await page.getByTestId("target-distribution-event-rate").textContent()) ?? "";
    expect(chartRate).toContain(formattedRate);
    const accessibleSummary = (await page.getByTestId("target-distribution-summary").textContent()) ?? "";
    expect(accessibleSummary).toContain("Target Class");
    expect(accessibleSummary).toContain(formattedRate);
    await shot(page, testInfo, "07-target-distribution-population-scale");

    // Rare-Event Detail must disclose its adjusted scale.
    const rareEventToggle = page.getByRole("button", { name: "Rare-Event Detail" });
    if (await rareEventToggle.isVisible().catch(() => false)) {
      await rareEventToggle.click();
      await expect(page.getByTestId("rare-event-scale-disclosure")).toContainText("do not represent true relative magnitude");
      await shot(page, testInfo, "08-target-distribution-rare-event-detail");
      await page.getByRole("button", { name: "Population Scale" }).click();
    }

    // Part B: the empty browser-session history table is gone from the primary page.
    await expect(page.getByText("Browser Session Dataset History")).toHaveCount(0);
    await expect(page.getByText("No browser-session dataset versions captured yet")).toHaveCount(0);

    // Performance: the full dataset never reaches the browser.
    const cachedRows = await page.evaluate(() => {
      const key = Object.keys(sessionStorage).find((k) => k.startsWith("atlas:modeling-dataset"));
      if (!key) return null;
      const parsed = JSON.parse(sessionStorage.getItem(key) ?? "{}");
      return { rows: Array.isArray(parsed.rows) ? parsed.rows.length : 0, registered: parsed.registered_row_count ?? 0 };
    });
    expect(cachedRows, "a browser dataset cache should exist").not.toBeNull();
    // The browser cache is hard-bounded and never exceeds the registered population.
    // (This fixture is small enough that the bound is not reached, which is correct;
    // the load path for a large Library asset is covered by the next test.)
    expect(cachedRows!.rows, "browser must hold a bounded number of rows").toBeLessThanOrEqual(5000);
    expect(cachedRows!.rows).toBeLessThanOrEqual(cachedRows!.registered);

    await dump();
  });

  test("a registered Library asset shows the load lifecycle and a read-only registered status", async ({ page }, testInfo) => {
    test.setTimeout(8 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const libraryName = `E2E DataAcq Registered Asset ${Date.now()}`;

    await registerUser(page, makeTestUser("dataAcqLibrary"));

    // Register an asset first so there is a governed Library version to load.
    await createPredictiveModelingProject(page, { name: "E2E Data Acquisition Source", modelId: `daSrc-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);
    await page.getByLabel("Target Column").selectOption("Class");
    await page.waitForTimeout(1500);
    await page.getByRole("button", { name: "Register in Dataset Library" }).click();
    await page.getByPlaceholder(/Development Dataset/).fill(libraryName);
    await page.waitForTimeout(1000);
    const [registerResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/datasets/register-workspace"), { timeout: 30_000 }),
      page.getByTestId("register-dataset-action").click(),
    ]);
    expect(registerResponse.status()).toBe(200);
    const registered = await registerResponse.json();
    const datasetId: string = registered.dataset.datasetId;
    const versionId: string = registered.dataset.latestVersion.versionId;

    // Second project loads that governed version from the Library.
    await createPredictiveModelingProject(page, { name: "E2E Data Acquisition Library", modelId: `daLib-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.getByRole("button", { name: "Existing Dataset", exact: false }).click();
    await page.waitForTimeout(2000);

    // Part A: the action lives in its own command block with the selectors, and is
    // blue and unloaded before use.
    const command = page.getByTestId("dataset-load-command");
    await expect(command).toBeVisible();
    const loadButton = page.getByTestId("load-selected-version");
    await expect(loadButton).toBeVisible();
    await expect(loadButton).toHaveAttribute("data-load-state", "unloaded");
    await expect(loadButton).toHaveText(/Load Selected Version/);

    // The action must sit within the selector command block, not at the far right edge.
    const commandBox = (await command.boundingBox())!;
    const buttonBox = (await loadButton.boundingBox())!;
    expect(buttonBox.x, "load action must not be pushed to the far-right edge").toBeLessThan(
      commandBox.x + commandBox.width / 2
    );
    const unloadedBg = await loadButton.evaluate((el) => getComputedStyle(el).backgroundColor);
    const [ur, ug, ub] = unloadedBg.match(/\d+/g)!.map(Number);
    expect(ub, "unloaded action must be blue").toBeGreaterThan(ur);
    expect(ub).toBeGreaterThan(ug);
    await shot(page, testInfo, "01-existing-library-before-load");

    // Slow the activation call just enough to observe the real loading milestones.
    await page.route("**/activate**", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2500));
      await route.continue();
    });

    await loadButton.click();
    await expect(loadButton).toHaveAttribute("data-load-state", "loading", { timeout: 10_000 });
    await expect(loadButton).toHaveText(/Loading Selected Version/);
    await expect(loadButton).toBeDisabled();
    const progress = page.getByTestId("dataset-load-progress");
    await expect(progress).toBeVisible();
    await expect(page.getByTestId("dataset-load-status")).toBeVisible();
    // Part H1/2-3: discrete milestones only -- no synthetic percentage anywhere.
    const milestoneText = (await page.getByTestId("dataset-load-milestone-count").textContent()) ?? "";
    expect(milestoneText).toMatch(/\d of 7 milestones/);
    await expect(progress).not.toContainText("%");
    await shot(page, testInfo, "02-loading-milestones");

    // Part A/4 + H1/6: success is green, labelled, and states the governed identity.
    await expect(loadButton).toHaveAttribute("data-load-state", "loaded", { timeout: 60_000 });
    await expect(loadButton).toHaveText(/Version Loaded/);
    const loadedBg = await loadButton.evaluate((el) => getComputedStyle(el).backgroundColor);
    const [lr, lg, lb] = loadedBg.match(/\d+/g)!.map(Number);
    expect(lg, "loaded action must be green").toBeGreaterThan(lr);
    expect(lg).toBeGreaterThan(lb);
    await expect(page.getByTestId("dataset-loaded-identity")).toContainText(versionId);
    await expect(page.getByText(`Loaded ${libraryName}, version ${versionId}, into this project.`)).toBeVisible();
    await expect(progress).toHaveAttribute("data-load-phase", "loaded");
    await shot(page, testInfo, "03-loaded-success-state");

    // Part C1: a registered asset gets a read-only status panel, never the
    // workspace-vs-register choice.
    await page.getByLabel("Target Column").selectOption("Class");
    await page.waitForTimeout(3000);
    const persistence = page.getByTestId("dataset-persistence-card");
    await expect(persistence).toBeVisible();
    await expect(persistence).toHaveAttribute("data-persistence-mode", "registered-status");
    await expect(persistence).toContainText("Registered Dataset Library Asset");
    await expect(persistence).toContainText("The source asset remains in the Dataset Library if this project is deleted.");
    await expect(page.getByTestId("already-linked-badge")).toBeVisible();
    await expect(persistence).toContainText(datasetId);
    await expect(persistence).toContainText(versionId);
    await expect(persistence.getByRole("button", { name: "Project Workspace Only" })).toHaveCount(0);
    await expect(persistence.getByRole("button", { name: "Register in Dataset Library" })).toHaveCount(0);
    await expect(persistence.getByRole("link", { name: "Open in Dataset Library" })).toBeVisible();
    await shot(page, testInfo, "04-registered-asset-persistence-status");

    // Part A/5: changing the selection returns the action to the unloaded state and
    // stops reporting the prior version as loaded.
    const commandSelects = command.locator("select");
    await expect(commandSelects).toHaveCount(2);
    const datasetSelect = commandSelects.nth(0);
    const versionSelect = commandSelects.nth(1);

    if ((await versionSelect.locator("option").count()) > 1) {
      await versionSelect.selectOption({ index: 1 });
    } else {
      // Only one governed version exists for this asset, so drive the reset through
      // the dataset selector by re-dispatching a change on it.
      await datasetSelect.evaluate((el: HTMLSelectElement) => {
        el.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
    await expect(loadButton).toHaveAttribute("data-load-state", "unloaded", { timeout: 10_000 });
    await expect(loadButton).toHaveText(/Load Selected Version/);
    await expect(page.getByTestId("dataset-loaded-identity")).toHaveCount(0);
    await expect(page.getByTestId("dataset-load-progress")).toHaveCount(0);

    await dump();
  });

  test("target distribution loads from a bounded server aggregate without duplicate queries", async ({ page }, testInfo) => {
    test.setTimeout(8 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const libraryName = `E2E TargetDist Asset ${Date.now()}`;

    // Record every target-distribution call plus its payload size.
    const calls: { body: Record<string, unknown>; bytes: number; ms: number }[] = [];
    page.on("response", async (response) => {
      if (!response.url().includes("/analytics/target-distribution")) return;
      const body = await response.json().catch(() => null);
      calls.push({
        body: JSON.parse(response.request().postData() ?? "{}"),
        bytes: (await response.body().catch(() => Buffer.from(""))).length,
        ms: body?.durationMs ?? -1,
      });
    });

    await registerUser(page, makeTestUser("targetDist"));
    await createPredictiveModelingProject(page, { name: "E2E Target Distribution Source", modelId: `tdSrc-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);
    await page.getByLabel("Target Column").selectOption("Class");
    await page.waitForTimeout(1500);
    await page.getByRole("button", { name: "Register in Dataset Library" }).click();
    await page.getByPlaceholder(/Development Dataset/).fill(libraryName);
    await page.waitForTimeout(1000);
    const [registerResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/datasets/register-workspace"), { timeout: 30_000 }),
      page.getByTestId("register-dataset-action").click(),
    ]);
    const registered = await registerResponse.json();
    const versionId: string = registered.dataset.latestVersion.versionId;

    // Load the governed version into a second project -- this is the slow path.
    await createPredictiveModelingProject(page, { name: "E2E Target Distribution Consumer", modelId: `tdCon-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.getByRole("button", { name: "Existing Dataset", exact: false }).click();
    await page.waitForTimeout(2000);
    await page.getByTestId("load-selected-version").click();
    await expect(page.getByTestId("load-selected-version")).toHaveAttribute("data-load-state", "loaded", { timeout: 60_000 });

    calls.length = 0;
    await page.getByLabel("Target Column").selectOption("Class");

    // The panel resolves on its own, and the page stays interactive meanwhile.
    const queryState = page.getByTestId("target-distribution-query-state");
    await expect(page.getByLabel("Target Column")).toBeEnabled();
    await expect(queryState).toHaveAttribute("data-query-phase", /exact|cached|sampled/, { timeout: 30_000 });

    // Exact, not sampled, for an asset this size.
    await expect(queryState).toHaveAttribute("data-query-phase", /exact|cached/);
    await expect(page.getByTestId("sampled-estimate-disclosure")).toHaveCount(0);
    await expect(page.getByTestId("target-distribution-event-rate")).toContainText("0.20%");

    // Bounded payload, and no duplicate active queries from re-renders.
    expect(calls.length, `target-distribution calls: ${JSON.stringify(calls)}`).toBeGreaterThan(0);
    const distinct = new Set(calls.map((c) => JSON.stringify(c.body)));
    expect(distinct.size, "each distinct identity must be queried at most once").toBe(calls.length);
    for (const call of calls) {
      expect(call.bytes, "aggregate payload must stay bounded").toBeLessThan(4000);
    }
    // eslint-disable-next-line no-console
    console.log(`[perf] target-distribution calls=${calls.length} bytes=${calls.map((c) => c.bytes)} serverMs=${calls.map((c) => c.ms)}`);
    await shot(page, testInfo, "10-target-distribution-server-aggregate");

    await dump();
  });

  test("the page remains usable at a narrow viewport", async ({ page }, testInfo) => {
    test.setTimeout(5 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await page.setViewportSize({ width: 768, height: 1000 });

    await registerUser(page, makeTestUser("dataAcqNarrow"));
    await createPredictiveModelingProject(page, { name: "E2E Data Acquisition Narrow", modelId: `daNw-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);
    await page.getByLabel("Target Column").selectOption("Class");
    await page.waitForTimeout(5000);

    // No horizontal page overflow, and the key sections stay visible.
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "the page body must not scroll horizontally").toBeLessThanOrEqual(1);
    await expect(page.getByTestId("data-quality-readiness")).toBeVisible();
    await expect(page.getByTestId("dataset-persistence-card")).toBeVisible();
    await shot(page, testInfo, "09-narrow-viewport");

    await dump();
  });
});
