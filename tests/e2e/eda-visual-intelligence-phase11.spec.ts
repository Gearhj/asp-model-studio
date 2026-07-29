import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

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
const FORBIDDEN_FIELDS = ["bad_flag", "RiskPerformance", "atlas_split"];

test.use({ trace: "off", video: "off" });

test.describe("EDA Visual Intelligence Phase 1.1", () => {
  test.skip(
    !E2E_EMAIL || !E2E_PASSWORD,
    "Set real ATLAS_E2E_EMAIL and ATLAS_E2E_PASSWORD credentials.",
  );

  test("readability, governed sample reuse, linked state, and lazy WebGL", async ({
    page,
  }, testInfo) => {
    test.setTimeout(10 * 60_000);

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const relationshipBodies: Array<Record<string, unknown>> = [];
    const relationshipResponses: Array<Record<string, unknown>> = [];
    const webglChunkRequests: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("request", (request) => {
      if (
        /RelationshipWebGL|echarts-gl|claygl/i.test(request.url())
      ) {
        webglChunkRequests.push(request.url());
      }
      if (
        request.method() === "POST" &&
        request.url().includes("/api/eda/relationship-sample")
      ) {
        relationshipBodies.push(
          JSON.parse(request.postData() || "{}") as Record<string, unknown>,
        );
      }
    });
    page.on("response", async (response) => {
      if (!response.url().includes("/api/eda/relationship-sample")) return;
      try {
        relationshipResponses.push(
          (await response.json()) as Record<string, unknown>,
        );
      } catch {
        // The main assertions below report a missing response if parsing fails.
      }
    });

    const login = await page.request.post(
      "http://127.0.0.1:8001/api/auth/login",
      { data: { email: E2E_EMAIL, password: E2E_PASSWORD } },
    );
    expect(login.ok(), `credentialed login returned ${login.status()}`).toBeTruthy();

    await createPredictiveModelingProject(page, {
      name: `EDA Visual Intelligence 1.1 ${Date.now()}`,
      modelId: `eda-vi-11-${Date.now()}`,
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

    expect(webglChunkRequests, "WebGL must not load with the EDA shell").toEqual([]);

    await page.getByRole("tab", { name: "Predictors" }).click();
    const distribution = page.getByTestId("predictor-distribution-explorer");
    await expect(distribution).toBeVisible({ timeout: 90_000 });
    const metricGrid = page.getByTestId("eda-predictor-metric-grid");
    await expect(metricGrid).toContainText("Selected rows");
    await expect(metricGrid).toContainText("Selected share");
    await expect(metricGrid).toContainText("IQR (Q1");
    await expect(metricGrid).toContainText("Selected range");
    await expect(metricGrid.locator(":scope > div")).toHaveCount(8);

    const quantileGrid = page.getByTestId("eda-quantile-grid");
    await expect(quantileGrid).toHaveAttribute("data-display-mode", "compact");
    await page
      .getByTestId("eda-quantile-display-mode")
      .getByRole("button", { name: "expanded" })
      .click();
    await expect(quantileGrid).toHaveAttribute("data-display-mode", "expanded");
    const firstQuantile = quantileGrid.locator("button[data-quantile-index]").first();
    await expect(firstQuantile).toContainText("Lift vs population");
    await firstQuantile.click();
    await expect(firstQuantile).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("eda-linked-selection-summary")).toBeVisible();
    await shot(page, testInfo, "phase11-01-readable-distribution");

    await page.getByRole("tab", { name: "Relationships" }).click();
    const correlation = page.getByTestId("correlation-explorer");
    await expect(correlation).toBeVisible({ timeout: 90_000 });
    await expect(page.getByLabel("Variables shown")).toHaveValue("12");
    await expect(page.getByTestId("correlation-zoom-controls")).toContainText(
      "54px cells",
    );
    await page.getByRole("button", { name: "Zoom in correlation matrix" }).click();
    await page.getByRole("button", { name: "Fit matrix" }).click();
    await expect(page.getByTestId("correlation-matrix-scroll-frame")).toHaveAttribute(
      "data-zoom-mode",
      "fit",
    );
    await page.getByTestId("correlation-expand-matrix").click();
    await expect(correlation).toHaveAttribute("role", "dialog");
    await expect(correlation).toHaveAttribute("data-expanded", "true");
    await page.getByRole("button", { name: "Exit expanded correlation analysis" }).click();

    const pinIndex = await page
      .locator('rect.atlas-correlation-cell[data-visible="true"]')
      .evaluateAll((nodes) =>
        nodes.findIndex(
          (node) =>
            node.getAttribute("data-row") !== node.getAttribute("data-column"),
        ),
      );
    expect(pinIndex).toBeGreaterThanOrEqual(0);
    await page
      .locator('rect.atlas-correlation-cell[data-visible="true"]')
      .nth(pinIndex)
      .click();
    const pairDetail = page.getByTestId("correlation-pinned-pair-detail");
    await expect(pairDetail).toContainText("Exact correlation");
    await expect(pairDetail).toContainText("Pairwise N");
    await expect(pairDetail).toContainText("VIF");
    await expect(pairDetail).toContainText("bounded complete-case backend cohort");

    expect(
      webglChunkRequests,
      "WebGL must remain unloaded after correlation inspection",
    ).toEqual([]);
    await pairDetail.getByRole("button", { name: "Launch 3D explorer" }).click();
    const explorer = page.getByTestId("relationship-explorer");
    await expect(explorer).toBeVisible({ timeout: 60_000 });
    const xAxis = explorer.getByLabel("X axis");
    const yAxis = explorer.getByLabel("Y axis");
    const zAxis = explorer.getByLabel("Z axis · explicitly selected");
    await expect(xAxis).not.toHaveValue("");
    await expect(yAxis).not.toHaveValue("");

    for (const selector of [xAxis, yAxis, zAxis]) {
      const options = await selector.locator("option").allTextContents();
      for (const forbidden of FORBIDDEN_FIELDS) {
        expect(options).not.toContain(forbidden);
      }
    }
    expect(
      webglChunkRequests,
      "WebGL must remain unloaded until Z is explicitly selected",
    ).toEqual([]);

    const xValue = await xAxis.inputValue();
    const yValue = await yAxis.inputValue();
    const zOptions = await zAxis.locator("option:not([disabled])").allTextContents();
    const zValue = zOptions.find(
      (value) => value && value !== "No Z selected" && value !== xValue && value !== yValue,
    );
    expect(zValue).toBeTruthy();
    await zAxis.selectOption({ label: zValue! });
    await expect(page.getByTestId("relationship-webgl")).toBeVisible({
      timeout: 120_000,
    });
    await expect
      .poll(() => webglChunkRequests.length, { timeout: 60_000 })
      .toBeGreaterThan(0);
    await expect(explorer).toContainText("does not establish");
    await expect(explorer).toContainText("Linked range overlap");
    await shot(page, testInfo, "phase11-02-governed-3d-relationship");

    await expect
      .poll(
        () =>
          relationshipResponses.some(
            (payload) =>
              String((payload.axes as Record<string, unknown> | undefined)?.z ?? "") ===
              zValue,
          ),
        { timeout: 60_000 },
      )
      .toBe(true);
    const lastResponse = [...relationshipResponses].reverse().find(
      (payload) =>
        String((payload.axes as Record<string, unknown> | undefined)?.z ?? "") ===
        zValue,
    )!;
    expect(lastResponse.scope).toBe("rendered_sample");
    expect(Number(lastResponse.returned_rows)).toBeLessThanOrEqual(5000);
    for (const point of (lastResponse.points as Array<Record<string, unknown>>) ?? []) {
      expect(point).not.toHaveProperty("bad_flag");
      expect(point).not.toHaveProperty("RiskPerformance");
      expect(point).not.toHaveProperty("__target__");
    }
    for (const body of relationshipBodies) {
      for (const role of [
        "x_feature",
        "y_feature",
        "z_feature",
        "point_size_feature",
        "segment_feature",
        "selection_feature",
      ]) {
        if (body[role] != null) {
          expect(FORBIDDEN_FIELDS).not.toContain(String(body[role]));
        }
      }
    }

    const requestsBeforePresentationChanges = relationshipBodies.length;
    await explorer.getByRole("button", { name: "2D scatter" }).click();
    await explorer.getByRole("button", { name: "Sample density" }).click();
    await explorer.getByRole("button", { name: "3D explorer" }).click();
    await explorer.getByLabel("Color").selectOption("none");
    await explorer.getByLabel(/Point opacity/).fill("0.45");
    await explorer.getByLabel("Grid").uncheck();
    await explorer.getByLabel("Legend").uncheck();
    await explorer.getByRole("button", { name: "Rotate right" }).click();
    await explorer.getByRole("button", { name: "Zoom in" }).click();
    await explorer.getByRole("button", { name: "Pan left" }).click();
    await explorer.getByRole("button", { name: "Reset camera" }).click();
    await page.waitForTimeout(500);
    expect(
      relationshipBodies.length,
      "presentation and camera changes must reuse one sample signature",
    ).toBe(requestsBeforePresentationChanges);

    const stateDownload = page.waitForEvent("download");
    await explorer.getByRole("button", { name: "Export state" }).click();
    const download = await stateDownload;
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(Buffer.from(chunk));
    const exported = JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<
      string,
      unknown
    >;
    expect(exported).toHaveProperty("camera");
    expect(exported).toHaveProperty("axes");
    expect(exported).toHaveProperty("predictorManifestId");

    const governedBody = relationshipBodies.at(-1)!;
    const projectId = String(governedBody.project_id);
    const safeX = String(governedBody.x_feature);
    const safeY = String(governedBody.y_feature);
    const safeZ = String(governedBody.z_feature);
    for (const role of [
      "x_feature",
      "y_feature",
      "z_feature",
      "point_size_feature",
      "segment_feature",
      "selection_feature",
    ]) {
      const crafted = {
        project_id: projectId,
        target: "bad_flag",
        event_value: 1,
        problem_type: "classification",
        x_feature: safeX,
        y_feature: safeY,
        z_feature: safeZ,
        sample_limit: 500,
        [role]: "RiskPerformance",
      };
      const rejected = await page.request.post(
        "http://127.0.0.1:8001/api/eda/relationship-sample",
        { data: crafted },
      );
      expect(rejected.status(), `${role} must fail closed`).toBe(422);
      const detail = (await rejected.json()) as {
        detail?: { code?: string; rejected_fields?: Array<{ field?: string }> };
      };
      expect(detail.detail?.code).toBe("relationship_fields_not_authorized");
      expect(detail.detail?.rejected_fields?.some((row) => row.field === "RiskPerformance")).toBeTruthy();
    }

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
