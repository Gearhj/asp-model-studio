import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { createPredictiveModelingProject } from "./helpers/project";
import { goNext } from "./helpers/workflow";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const E2E_EMAIL = process.env.ATLAS_E2E_EMAIL || "";
const E2E_PASSWORD = process.env.ATLAS_E2E_PASSWORD || "";
const HELOC_FILE = path.resolve(
  __dirname,
  "../../server/artifacts/datasets/ds_heloc_train_6bdb184b_05905/versions/v_1785186305905_6bdb184b/data_full.csv",
);

// Authenticate through the real API so credentials never enter the DOM or an
// accessibility snapshot. Traces and video remain disabled because both are
// inappropriate artifacts for a credentialed acceptance run.
test.use({ trace: "off", video: "off" });

declare global {
  interface Window {
    __atlasBarHeights?: number[];
    __atlasMarkerTransforms?: string[];
    __atlasEdaPerformance?: Array<Record<string, unknown>>;
  }
}

async function installMotionEvidence(page: Page) {
  await page.addInitScript(() => {
    window.__atlasBarHeights = [];
    window.__atlasMarkerTransforms = [];
    window.__atlasEdaPerformance = [];
    window.addEventListener("atlas:eda-performance", (event) => {
      window.__atlasEdaPerformance?.push(
        (event as CustomEvent<Record<string, unknown>>).detail,
      );
    });
    window.addEventListener("DOMContentLoaded", () => {
      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          if (mutation.type !== "attributes") continue;
          const element = mutation.target as Element;
          if (
            mutation.attributeName === "height" &&
            element.matches("rect.distribution-bar")
          ) {
            const value = Number(element.getAttribute("height"));
            if (Number.isFinite(value)) window.__atlasBarHeights?.push(value);
          }
          if (
            mutation.attributeName === "transform" &&
            element.matches("g.stat-marker")
          ) {
            const value = element.getAttribute("transform");
            if (value) window.__atlasMarkerTransforms?.push(value);
          }
        }
      });
      observer.observe(document.documentElement, {
        subtree: true,
        attributes: true,
        attributeFilter: ["height", "transform"],
      });
    });
  });
}

test.describe("EDA Visual Intelligence Phase 1", () => {
  test.skip(
    !E2E_EMAIL || !E2E_PASSWORD,
    "Set real ATLAS_E2E_EMAIL and ATLAS_E2E_PASSWORD credentials.",
  );

  test("motion, linked analysis, authorization, responsiveness, and reduced motion", async ({
    page,
  }, testInfo) => {
    test.setTimeout(8 * 60_000);
    await installMotionEvidence(page);

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const distributionBodies: string[] = [];
    const workspaceSections: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("request", (request) => {
      if (request.method() !== "POST") return;
      if (request.url().includes("/api/eda/workspace/distribution")) {
        distributionBodies.push(request.postData() || "");
      }
      const section = request.url().match(/\/api\/eda\/workspace\/([^/?]+)/)?.[1];
      if (section) workspaceSections.push(section);
    });

    const login = await page.request.post(
      "http://127.0.0.1:8001/api/auth/login",
      { data: { email: E2E_EMAIL, password: E2E_PASSWORD } },
    );
    expect(login.ok(), `credentialed login returned ${login.status()}`).toBeTruthy();

    await createPredictiveModelingProject(page, {
      name: `EDA Visual Intelligence ${Date.now()}`,
      modelId: `eda-vi-${Date.now()}`,
    });
    await page.goto("/step01");
    await page.locator('input[type="file"]').first().setInputFiles(HELOC_FILE);
    await expect(page.getByLabel("Target Column")).toBeEnabled({ timeout: 60_000 });
    await page.getByLabel("Target Column").selectOption("bad_flag");
    await page.getByLabel("Event / Positive Value").fill("1");
    await page.getByLabel("Non-event / Negative Value").fill("0");
    await goNext(page, /\/step02/);

    await expect(
      page.getByRole("heading", { name: "Step 2: Exploratory Data Analysis" }),
    ).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("eda-predictor-authorization")).toContainText(
      "RiskPerformance",
    );
    expect(workspaceSections).toContain("overview");
    expect(workspaceSections).not.toContain("predictors");
    expect(workspaceSections).not.toContain("relationships");
    await shot(page, testInfo, "phase1-01-overview-authorization");

    await page.getByRole("tab", { name: "Predictors" }).click();
    const distribution = page.getByTestId("predictor-distribution-explorer");
    await expect(distribution).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("eda-distribution-svg")).toBeVisible();
    await expect(distribution).toHaveAttribute("data-motion-phase", "settled", {
      timeout: 15_000,
    });
    expect(workspaceSections).toContain("predictors");
    expect(workspaceSections).not.toContain("relationships");

    const predictorOptions = await page
      .getByTestId("eda-distribution-variable")
      .locator("option")
      .allTextContents();
    expect(predictorOptions.length).toBeGreaterThan(2);
    expect(predictorOptions).not.toContain("bad_flag");
    expect(predictorOptions).not.toContain("RiskPerformance");
    expect(predictorOptions).not.toContain("atlas_split");

    const bars = page.locator("rect.distribution-bar");
    await expect(bars.first()).toBeVisible();
    await bars.first().evaluate((node) => {
      (node as SVGRectElement).dataset.morphToken = "phase1-morph";
    });
    const markerTransformsBefore = await page
      .locator("g.stat-marker")
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("transform")));
    const currentPredictor = await page.getByTestId("eda-distribution-variable").inputValue();
    const nextPredictor = predictorOptions.find((value) => value !== currentPredictor);
    expect(nextPredictor).toBeTruthy();
    await page.getByTestId("eda-distribution-variable").selectOption(nextPredictor!);
    await expect(distribution).toHaveAttribute("data-motion-phase", "animating", {
      timeout: 30_000,
    });
    await shot(page, testInfo, "phase1-02-predictor-morph-animating");
    await expect(distribution).toHaveAttribute("data-motion-phase", "settled", {
      timeout: 15_000,
    });
    await expect(bars.first()).toHaveAttribute("data-morph-token", "phase1-morph");
    const markerTransformsAfter = await page
      .locator("g.stat-marker")
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("transform")));
    expect(markerTransformsAfter).not.toEqual(markerTransformsBefore);

    const motionEvidence = await page.evaluate(() => ({
      heights: window.__atlasBarHeights ?? [],
      transforms: window.__atlasMarkerTransforms ?? [],
    }));
    expect(motionEvidence.heights.some((height) => height === 0)).toBeTruthy();
    expect(motionEvidence.heights.some((height) => height > 5)).toBeTruthy();
    expect(new Set(motionEvidence.transforms).size).toBeGreaterThan(2);

    await bars.first().focus();
    const tooltip = page.getByTestId("eda-distribution-tooltip");
    await expect(tooltip).toContainText("rows");
    await expect(tooltip).toContainText("events");
    await expect(tooltip).toContainText("Missing bucket");

    const brushOverlay = page.locator("g.range-brush rect.overlay");
    const brushBounds = await brushOverlay.boundingBox();
    expect(brushBounds).toBeTruthy();
    await page.mouse.move(
      brushBounds!.x + brushBounds!.width * 0.24,
      brushBounds!.y + brushBounds!.height * 0.5,
    );
    await page.mouse.down();
    await page.mouse.move(
      brushBounds!.x + brushBounds!.width * 0.62,
      brushBounds!.y + brushBounds!.height * 0.5,
      { steps: 8 },
    );
    await page.mouse.up();
    const selectedRowsMetric = page
      .getByText("Selected rows", { exact: true })
      .locator("..");
    await page.waitForFunction(
      () =>
        window.__atlasEdaPerformance?.some(
          (event) => event.name === "brush-response",
        ) === true,
      undefined,
      { timeout: 60_000 },
    );
    await expect(selectedRowsMetric).toContainText(/\d/, { timeout: 60_000 });
    await expect(page.getByTestId("eda-linked-selection-summary")).toBeVisible();
    await expect(page.getByTestId("eda-missing-bucket")).toBeVisible();
    await page.getByTestId("eda-iv-by-bin-toggle").click();
    await expect(
      page.getByRole("columnheader", { name: "WoE", exact: true }),
    ).toBeVisible();
    await shot(page, testInfo, "phase1-03-brush-selected-metrics");

    expect(distributionBodies.length).toBeGreaterThanOrEqual(3);
    const duplicateBodies = distributionBodies.filter(
      (body, index) => distributionBodies.indexOf(body) !== index,
    );
    expect(duplicateBodies, "duplicate analytical distribution requests").toEqual([]);

    await page.getByRole("tab", { name: "Relationships" }).click();
    const correlation = page.getByTestId("correlation-explorer");
    await expect(correlation).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("correlation-matrix-svg")).toBeVisible();
    const correlationRows = await page
      .locator("rect.atlas-correlation-cell")
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-row")));
    expect(correlationRows).not.toContain("bad_flag");
    expect(correlationRows).not.toContain("RiskPerformance");

    await page.getByPlaceholder("Search full variable names").fill("ExternalRisk");
    await expect(correlation).toContainText(/1 of \d+ variables/);
    await page.getByPlaceholder("Search full variable names").fill("");
    await page.getByLabel("Matrix order").selectOption("clustered");
    await page.getByLabel("Minimum absolute correlation displayed").fill("0.25");
    const offDiagonalIndex = await page
      .locator('rect.atlas-correlation-cell[data-visible="true"]')
      .evaluateAll((nodes) =>
        nodes.findIndex(
          (node) =>
            node.getAttribute("data-row") !== node.getAttribute("data-column"),
        ),
      );
    expect(offDiagonalIndex).toBeGreaterThanOrEqual(0);
    const pairCell = page
      .locator('rect.atlas-correlation-cell[data-visible="true"]')
      .nth(offDiagonalIndex);
    await pairCell.hover();
    await expect(page.getByTestId("correlation-tooltip")).toBeVisible();
    await pairCell.click();
    await expect(page.getByText(/Selected variables:/).first()).toBeVisible({
      timeout: 60_000,
    });
    await shot(page, testInfo, "phase1-04-correlation-filter-hover-pin");

    const vif = page.getByTestId("vif-explorer");
    await expect(vif).toBeVisible();
    await expect(vif).toHaveAttribute("data-motion-phase", "settled", {
      timeout: 15_000,
    });
    await expect(page.getByTestId("vif-scope-badge")).toContainText(
      /backend rows|Bounded backend/,
    );
    const firstVifBar = vif
      .locator('button[data-variable][aria-pressed="false"]')
      .first();
    await firstVifBar.click();
    await expect(page.getByTestId("vif-partner-list")).toBeVisible();
    const simulate = page.getByRole("button", { name: /Simulate without/ });
    await expect(simulate).toBeEnabled();
    await simulate.click();
    await expect(page.getByTestId("vif-simulator")).toContainText(
      "No governed feature state was changed",
      { timeout: 60_000 },
    );
    await shot(page, testInfo, "phase1-05-vif-zones-partners-simulation");

    for (const viewport of [
      { width: 1366, height: 768, label: "1366x768" },
      { width: 1536, height: 864, label: "1536x864" },
      { width: 1920, height: 1080, label: "1920x1080" },
    ]) {
      await page.setViewportSize(viewport);
      await expect(vif).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `document overflow at ${viewport.label}`).toBeLessThanOrEqual(1);
      await shot(page, testInfo, `phase1-layout-${viewport.label}`);
    }

    const performanceEvents = await page.evaluate(
      () => window.__atlasEdaPerformance ?? [],
    );
    const performanceNames = performanceEvents.map((event) => event.name);
    expect(performanceNames).toContain("initial-page-shell");
    expect(performanceNames).toContain("first-useful-chart");
    expect(performanceNames).toContain("full-tab-readiness");
    expect(performanceNames).toContain("chart-update");
    expect(performanceNames).toContain("brush-response");
    console.log("EDA_PHASE1_PERFORMANCE:", JSON.stringify(performanceEvents));

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/step02");
    await page.getByRole("tab", { name: "Predictors" }).click();
    const reducedDistribution = page.getByTestId("predictor-distribution-explorer");
    await expect(reducedDistribution).toHaveAttribute("data-reduced-motion", "true", {
      timeout: 90_000,
    });
    await expect(reducedDistribution).toHaveAttribute("data-motion-phase", "settled");
    await shot(page, testInfo, "phase1-09-reduced-motion-final-state");

    expect(pageErrors, "uncaught page errors").toEqual([]);
    expect(
      consoleErrors.filter(
        (message) =>
          !/favicon|ResizeObserver loop|Failed to load resource.*404/i.test(message),
      ),
      "unexpected browser console errors",
    ).toEqual([]);
  });
});
