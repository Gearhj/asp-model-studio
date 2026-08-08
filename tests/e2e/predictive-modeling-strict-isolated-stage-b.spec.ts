import fs from "node:fs";
import path from "node:path";
import {
  expect,
  test,
  type Locator,
  type Page,
  type Response,
  type TestInfo,
} from "@playwright/test";
import { loginUser } from "./helpers/auth";
import { attachDiagnostics } from "./helpers/diagnostics";
import { isolatedHarnessEnvironment } from "./helpers/isolatedHarness";
import { shot } from "./helpers/screenshots";
import { writeStrictPredictiveFixture } from "./helpers/strictPredictiveFixture";

type StageACheckpoint = {
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  training_job_id: string;
  training_run_id: string;
  candidate_id: string;
  candidate_decision_id: string;
  evaluation_package_id: string;
  disposable_user_email: string;
};

type CandidateLineage = {
  feature_manifest_version: string;
  validation_design_id: string;
  validation_design_version: string;
  split_id: string;
  target: string;
};

type CoverageRecord = {
  step: string;
  control: string;
  result: "passed" | "intentionally_absent";
  evidence: string;
};

const DISPOSABLE_PASSWORD = "AtlasE2ePassw0rd!";

function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value).trim();
}

function field(
  value: Record<string, unknown> | null | undefined,
  camel: string,
  snake: string,
): unknown {
  return value?.[camel] ?? value?.[snake];
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function exactProjectStep(projectId: string, step: string): RegExp {
  return new RegExp(`/projects/${escapeRegExp(projectId)}/${step}(?:[?#]|$)`);
}

async function expectExactStep(page: Page, projectId: string, step: string) {
  await expect(page).toHaveURL(exactProjectStep(projectId, step), {
    timeout: 180_000,
  });
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-project-context-status",
    "ready",
    { timeout: 180_000 },
  );
  await expect(page.getByTestId("project-context-gate")).toHaveCount(0, {
    timeout: 180_000,
  });
  await page.waitForTimeout(750);
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-project-context-status",
    "ready",
    { timeout: 180_000 },
  );
  await expect(page.getByTestId("project-context-gate")).toHaveCount(0, {
    timeout: 180_000,
  });
  await expect(page).toHaveURL(exactProjectStep(projectId, step));
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
}

async function readScopedProjectContext(page: Page, projectId: string) {
  return page.evaluate((exactProjectId) => {
    const storedUser = JSON.parse(
      localStorage.getItem("modelflow-user") || "null",
    ) as { userId?: string } | null;
    const userId = String(storedUser?.userId ?? "").trim();
    if (!userId) return null;
    const key = `modeling-tool-project-context:${encodeURIComponent(userId)}:${encodeURIComponent(exactProjectId)}`;
    return JSON.parse(localStorage.getItem(key) || "null");
  }, projectId);
}

async function strictContinue(
  page: Page,
  projectId: string,
  nextStep: string,
  timeout = 180_000,
) {
  const action = page.locator('[data-step-next-button="true"]');
  await expect(action).toHaveCount(1);
  await expect(action).toBeVisible();
  const workflowBar = action.locator(
    "xpath=ancestor::*[@data-workflow-action-scope][1]",
  );
  await expect(workflowBar).toContainText("Ready for next step", { timeout });
  await expect(action).toBeEnabled({ timeout });
  const readyLabel = (await action.innerText()).trim();
  await expect(action).toHaveAttribute("title", readyLabel);
  await action.click();
  await expectExactStep(page, projectId, nextStep);
}

function findStageACheckpoint(outputRoot: string): string {
  const matches: string[] = [];
  const visit = (directory: string) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const candidate = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(candidate);
      if (entry.isFile() && entry.name === "strict-stage-a-checkpoint.json") {
        matches.push(candidate);
      }
    }
  };
  visit(outputRoot);
  expect(
    matches,
    "Stage B must consume exactly one checkpoint written by Stage A in this isolated output root",
  ).toHaveLength(1);
  return matches[0];
}

function readCheckpoint(outputRoot: string): StageACheckpoint {
  const checkpointPath = findStageACheckpoint(outputRoot);
  const checkpoint = JSON.parse(fs.readFileSync(checkpointPath, "utf8")) as Partial<StageACheckpoint>;
  for (const key of [
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "training_job_id",
    "training_run_id",
    "candidate_id",
    "candidate_decision_id",
    "evaluation_package_id",
    "disposable_user_email",
  ] as const) {
    expect(text(checkpoint[key]), `Stage A checkpoint field ${key}`).not.toBe("");
  }
  return checkpoint as StageACheckpoint;
}

function isBackendResponse(
  response: Response,
  backendOrigin: string,
  pathname: string,
  method = "GET",
): boolean {
  const url = new URL(response.url());
  return (
    url.origin === backendOrigin &&
    url.pathname === pathname &&
    response.request().method() === method
  );
}

function rankedCandidates(payload: Record<string, any>): Array<Record<string, any>> {
  const candidates = [
    payload?.partial_ranked_results,
    payload?.summary?.ranked,
    payload?.ranked,
  ];
  return candidates.find((value) => Array.isArray(value)) ?? [];
}

async function responseJson(response: Response): Promise<Record<string, any>> {
  expect(response.status(), `${response.request().method()} ${new URL(response.url()).pathname}`).toBe(200);
  const payload = await response.json();
  expect(payload).toBeTruthy();
  return payload as Record<string, any>;
}

function assertInterpretationUrl(
  page: Page,
  checkpoint: StageACheckpoint,
  expectedComparisonIds?: string[],
) {
  const url = new URL(page.url());
  expect(url.pathname).toBe(`/projects/${checkpoint.project_id}/step09`);
  expect(url.searchParams.get("candidate_id")).toBe(checkpoint.candidate_id);
  expect(url.searchParams.get("training_run_id")).toBe(checkpoint.training_run_id);
  expect(url.searchParams.get("candidate_decision_id")).toBe(
    checkpoint.candidate_decision_id,
  );
  expect(url.searchParams.get("evaluation_package_id")).toBe(
    checkpoint.evaluation_package_id,
  );
  if (expectedComparisonIds) {
    expect((url.searchParams.get("compare") ?? "").split(",").filter(Boolean)).toEqual(
      expectedComparisonIds,
    );
  }
}

async function exerciseVisibleTabs(
  page: Page,
  step: string,
  coverage: CoverageRecord[],
) {
  const allTabs = page.getByRole("tab");
  const visibleTabs: Locator[] = [];
  for (let index = 0; index < await allTabs.count(); index += 1) {
    const tab = allTabs.nth(index);
    if (await tab.isVisible()) visibleTabs.push(tab);
  }
  if (!visibleTabs.length) {
    coverage.push({
      step,
      control: "semantic tabs",
      result: "intentionally_absent",
      evidence: "The rendered page exposes no role=tab controls.",
    });
    return;
  }
  for (let index = 0; index < visibleTabs.length; index += 1) {
    const tab = visibleTabs[index];
    const name = (await tab.innerText()).trim() || `tab ${index + 1}`;
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
    coverage.push({
      step,
      control: name,
      result: "passed",
      evidence: "Tab accepted the click and became the selected tab.",
    });
  }
}

function optionValues(select: Locator): Promise<string[]> {
  return select.locator("option").evaluateAll((options) =>
    options
      .map((option) => (option as HTMLOptionElement).value)
      .filter((value) => value.trim().length > 0),
  );
}

function record(value: unknown, label: string): Record<string, any> {
  expect(value, label).toBeTruthy();
  expect(Array.isArray(value), `${label} must be an object`).toBe(false);
  expect(typeof value, `${label} must be an object`).toBe("object");
  return value as Record<string, any>;
}

function finite(value: unknown, label: string): number {
  expect(typeof value, label).toBe("number");
  expect(Number.isFinite(value), label).toBe(true);
  return value as number;
}

function fixed(value: unknown, label: string, digits = 4): string {
  return finite(value, label).toFixed(digits);
}

function percent(value: unknown, label: string): string {
  return `${(finite(value, label) * 100).toFixed(1)}%`;
}

function displayedMetric(value: unknown, digits = 4): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "-";
}

function displayedDelta(reference: unknown, comparison: unknown): string {
  if (
    typeof reference !== "number" ||
    !Number.isFinite(reference) ||
    typeof comparison !== "number" ||
    !Number.isFinite(comparison)
  ) {
    return "-";
  }
  const delta = comparison - reference;
  return `${delta >= 0 ? "+" : ""}${delta.toFixed(4)}`;
}

function selectionMetricLabel(metric: Record<string, any>): string {
  const labels: Record<string, string> = {
    auc: "ROC-AUC",
    roc_auc: "ROC-AUC",
    pr_auc: "PR-AUC",
    rmse: "RMSE",
    mae: "MAE",
    r2: "R-squared",
  };
  const sourceLabels: Record<string, string> = {
    cross_validation_mean: "cross-validation mean",
    out_of_fold: "out-of-fold",
    training_validation_partition: "governed validation partition",
  };
  const name = text(metric.name).toLowerCase();
  return `${labels[name] ?? name.replaceAll("_", " ").toUpperCase()} - ${
    sourceLabels[text(metric.source)] ?? "unverified selection source"
  }`;
}

function normalizedSelectionMetric(metric: Record<string, any>): Record<string, any> {
  return {
    ...metric,
    name: metric.name ?? metric.selection_metric_name,
    source: metric.source ?? metric.selection_metric_source,
    partition_id: metric.partition_id ?? metric.selection_partition_id,
    value: metric.value ?? metric.selection_metric_value,
  };
}

function cleanModelName(value: unknown): string {
  return text(value).replace(/\s*\(k\s*=\s*\d+\)/i, "");
}

function svgPointCount(points: string | null): number {
  return text(points) ? text(points).split(/\s+/).length : 0;
}

function expectedPdpPoints(rows: Array<Record<string, any>>): string {
  const width = 520;
  const height = 260;
  const pad = 46;
  const predictions = rows.map((row) => finite(row.prediction, "PDP prediction"));
  const rawMin = Math.min(...predictions);
  const rawMax = Math.max(...predictions);
  const spread = Math.max(rawMax - rawMin, 0.001);
  const minY = rawMin - spread * 0.2;
  const maxY = rawMax + spread * 0.2;
  const plotWidth = width - pad - 18;
  const plotHeight = height - pad - 24;
  const x = (index: number) =>
    pad + (index / Math.max(1, rows.length - 1)) * plotWidth;
  const y = (value: number) =>
    18 + ((maxY - value) / (maxY - minY || 1)) * plotHeight;
  return predictions.map((value, index) => `${x(index)},${y(value)}`).join(" ");
}

async function expectExactBoundaryRendering(
  section: Locator,
  payload: Record<string, any>,
) {
  expect(payload.ok).toBe(true);
  const grid = payload.grid as Array<Record<string, any>>;
  const points = payload.points as Array<Record<string, any>>;
  const xDomain = payload.x_domain as unknown[];
  const yDomain = payload.y_domain as unknown[];
  const resolution = finite(payload.resolution, "decision-boundary resolution");
  expect(Array.isArray(grid)).toBe(true);
  expect(grid.length).toBe(resolution * resolution);
  expect(Array.isArray(points)).toBe(true);
  expect(points.length).toBeGreaterThan(0);
  expect(Array.isArray(xDomain)).toBe(true);
  expect(xDomain).toHaveLength(2);
  expect(Array.isArray(yDomain)).toBe(true);
  expect(yDomain).toHaveLength(2);

  const svg = section.locator("svg");
  await expect(svg).toBeVisible();
  await expect(svg).toHaveAttribute("data-x-feature", text(payload.x_feature));
  await expect(svg).toHaveAttribute("data-y-feature", text(payload.y_feature));
  await expect(svg.locator("rect")).toHaveCount(grid.length);
  await expect(svg.locator("circle")).toHaveCount(points.length);
  await expect(svg).toContainText(text(payload.x_feature));
  await expect(svg).toContainText(text(payload.y_feature));

  const width = 880;
  const height = 430;
  const pad = 54;
  const plotWidth = width - pad - 24;
  const plotHeight = height - pad - 24;
  const xMin = finite(xDomain[0], "decision-boundary x minimum");
  const xMax = finite(xDomain[1], "decision-boundary x maximum");
  const yMin = finite(yDomain[0], "decision-boundary y minimum");
  const yMax = finite(yDomain[1], "decision-boundary y maximum");
  const x = (value: unknown) =>
    pad + ((finite(value, "decision-boundary x value") - xMin) / (xMax - xMin || 1)) * plotWidth;
  const y = (value: unknown) =>
    18 + ((yMax - finite(value, "decision-boundary y value")) / (yMax - yMin || 1)) * plotHeight;

  const firstGrid = record(grid[0], "first decision-boundary grid cell");
  const firstRect = await svg.locator("rect").first().evaluate((node) => ({
    x: Number(node.getAttribute("x")),
    y: Number(node.getAttribute("y")),
    width: Number(node.getAttribute("width")),
    height: Number(node.getAttribute("height")),
  }));
  expect(firstRect.x).toBeCloseTo(x(firstGrid.x) - (plotWidth / resolution + 0.5) / 2, 8);
  expect(firstRect.y).toBeCloseTo(y(firstGrid.y) - (plotHeight / resolution + 0.5) / 2, 8);
  expect(firstRect.width).toBeCloseTo(plotWidth / resolution + 0.5, 8);
  expect(firstRect.height).toBeCloseTo(plotHeight / resolution + 0.5, 8);
  finite(firstGrid.score, "first decision-boundary score");

  const firstPoint = record(points[0], "first decision-boundary point");
  const firstCircle = await svg.locator("circle").first().evaluate((node) => ({
    cx: Number(node.getAttribute("cx")),
    cy: Number(node.getAttribute("cy")),
    fill: node.getAttribute("fill"),
  }));
  expect(firstCircle.cx).toBeCloseTo(x(firstPoint.x), 8);
  expect(firstCircle.cy).toBeCloseTo(y(firstPoint.y), 8);
  expect(firstCircle.fill).toBe(finite(firstPoint.class, "first decision-boundary point class") ? "#facc15" : "#4c1d95");
}

async function expectLabeledValue(
  scope: Locator,
  label: string,
  expectedValue: string,
) {
  const labelNode = scope.getByText(label, { exact: true });
  await expect(labelNode, `visible value label ${label}`).toHaveCount(1);
  await expect(labelNode.locator("xpath=..")).toContainText(expectedValue);
}

async function expectExactTableRow(
  table: Locator,
  key: string,
  expectedCells: string[],
) {
  const rows = table.locator("tbody tr");
  const matchingRows: Locator[] = [];
  for (let index = 0; index < await rows.count(); index += 1) {
    const row = rows.nth(index);
    const firstCell = row.getByRole("cell").first();
    if ((await firstCell.innerText()).trim() === key) matchingRows.push(row);
  }
  expect(matchingRows, `table row keyed by ${key}`).toHaveLength(1);
  const cells = (await matchingRows[0].getByRole("cell").allTextContents())
    .map((value) => value.trim().replace(/\s+/g, " "));
  expect(cells).toEqual(expectedCells);
}

test.describe("Strict isolated predictive modeling Stage B", () => {
  test("continues the exact Stage A candidate through Evaluation, Interpretation, Scoring, Documentation, Implementation, and Monitoring", async ({ page }, testInfo) => {
    test.setTimeout(22 * 60_000);
    const isolated = isolatedHarnessEnvironment();
    const checkpoint = readCheckpoint(isolated.outputRoot);
    const coverage: CoverageRecord[] = [];
    const { log, dump } = attachDiagnostics(page, testInfo);
    let modelVersionId = "";

    const writeCoverage = async () => {
      const file = testInfo.outputPath("strict-stage-b-coverage.json");
      fs.writeFileSync(
        file,
        `${JSON.stringify(
          {
            project_id: checkpoint.project_id,
            dataset_id: checkpoint.dataset_id,
            dataset_version_id: checkpoint.dataset_version_id,
            candidate_id: checkpoint.candidate_id,
            training_run_id: checkpoint.training_run_id,
            candidate_decision_id: checkpoint.candidate_decision_id,
            evaluation_package_id: checkpoint.evaluation_package_id,
            model_version_id: modelVersionId || null,
            coverage,
          },
          null,
          2,
        )}\n`,
        "utf8",
      );
      await testInfo.attach("strict-stage-b-coverage", {
        path: file,
        contentType: "application/json",
      });
    };

    try {
      // Re-authenticate only through the public user interface, then reopen the
      // exact Stage A project from the backend-authorized project registry.
      await loginUser(page, {
        email: checkpoint.disposable_user_email,
        password: DISPOSABLE_PASSWORD,
      });
      await page.goto("/projects/open");
      await expect(page.getByRole("heading", { name: "Recent Projects" })).toBeVisible();
      const projectName = `ATLAS Strict Stage A ${isolated.runId}`;
      await page
        .getByPlaceholder("Search project, target, dataset, or type")
        .fill(projectName);
      await page.getByRole("button", { name: "Card View", exact: true }).click();
      const projectCard = page.locator("article").filter({
        has: page.getByRole("heading", { name: projectName, exact: true }),
      });
      await expect(projectCard).toHaveCount(1);

      const lastTrainingResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/train/last"),
        { timeout: 180_000 },
      );
      const decisionResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/model/train/decision"),
        { timeout: 180_000 },
      );
      const commandCenterResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/eval/command_center"),
        { timeout: 180_000 },
      );
      const curvesResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/eval/curves"),
        { timeout: 180_000 },
      );
      await projectCard.getByRole("button", { name: "Open", exact: true }).click();
      await expectExactStep(page, checkpoint.project_id, "step08");
      const [lastTrainingPayload, decisionPayload, commandPayload, curvesPayload] = await Promise.all([
        lastTrainingResponsePromise.then(responseJson),
        decisionResponsePromise.then(responseJson),
        commandCenterResponsePromise.then(responseJson),
        curvesResponsePromise.then(responseJson),
      ]);

      const candidate = rankedCandidates(lastTrainingPayload).find(
        (row) => text(row.candidate_id) === checkpoint.candidate_id,
      );
      expect(candidate, "the exact Stage A candidate must be in the durable training result").toBeTruthy();
      expect(text(candidate?.project_id)).toBe(checkpoint.project_id);
      expect(text(candidate?.dataset_id)).toBe(checkpoint.dataset_id);
      expect(text(candidate?.dataset_version_id)).toBe(checkpoint.dataset_version_id);
      expect(text(candidate?.training_run_id)).toBe(checkpoint.training_run_id);
      const candidateLineage: CandidateLineage = {
        feature_manifest_version: text(candidate?.feature_manifest_version),
        validation_design_id: text(candidate?.validation_design_id),
        validation_design_version: text(candidate?.validation_design_version),
        split_id: text(candidate?.split_id),
        target: text(
          candidate?.target ??
            candidate?.target_name ??
            candidate?.candidate_contract?.target_name ??
            candidate?.candidate_contract?.target_definition?.target_name,
        ),
      };
      for (const [name, value] of Object.entries(candidateLineage)) {
        expect(value, `candidate lineage ${name}`).not.toBe("");
      }

      const decision = (decisionPayload.decision ?? decisionPayload) as Record<string, any>;
      expect(text(decision.decision_id)).toBe(checkpoint.candidate_decision_id);
      expect(text(decision.selected_candidate_id)).toBe(checkpoint.candidate_id);
      expect(text(decision.training_run_id)).toBe(checkpoint.training_run_id);
      const rawSelectionMetric = record(
        decision.selection_metric,
        "locked selection metric",
      );
      const selectionMetric = normalizedSelectionMetric(rawSelectionMetric);
      expect(text(selectionMetric.name)).not.toBe("");
      expect(text(selectionMetric.partition_id)).not.toBe("");
      expect(finite(selectionMetric.fold_count, "selection fold count")).toBeGreaterThan(0);
      finite(selectionMetric.value, "selection metric value");
      finite(selectionMetric.standard_deviation, "selection metric standard deviation");
      const evaluation = (commandPayload.evaluation_package ?? commandPayload) as Record<string, any>;
      expect(text(evaluation.evaluation_package_id ?? commandPayload.evaluation_package_id)).toBe(
        checkpoint.evaluation_package_id,
      );
      expect(text(evaluation.project_id ?? commandPayload.project_id)).toBe(checkpoint.project_id);
      expect(text(evaluation.dataset_id ?? commandPayload.dataset_id)).toBe(checkpoint.dataset_id);
      expect(text(evaluation.dataset_version_id ?? commandPayload.dataset_version_id)).toBe(
        checkpoint.dataset_version_id,
      );
      expect(text(evaluation.candidate_id ?? commandPayload.candidate_id)).toBe(
        checkpoint.candidate_id,
      );
      expect(text(evaluation.training_run_id ?? commandPayload.training_run_id)).toBe(
        checkpoint.training_run_id,
      );
      expect(text(evaluation.candidate_decision_id ?? commandPayload.candidate_decision_id)).toBe(
        checkpoint.candidate_decision_id,
      );
      expect(text(commandPayload.final_holdout_role ?? evaluation.final_holdout_role)).toBe(
        "reporting_only",
      );
      const finalHoldoutEvidence = record(
        evaluation.final_holdout_evidence ??
          evaluation.final_holdout_evidence_json ??
          commandPayload.final_holdout_evidence ??
          commandPayload.final_holdout_evidence_json,
        "final-holdout evidence",
      );
      const finalHoldoutMetrics = record(
        finalHoldoutEvidence.metrics,
        "final-holdout metrics",
      );
      const evaluationIsolationStatus = text(
        evaluation.isolation_status ?? evaluation.holdout_isolation_status,
      );
      expect(evaluationIsolationStatus, "Evaluation isolation status").not.toBe("");
      const thresholdMetrics = record(commandPayload.threshold, "threshold metrics");
      const calibration = record(commandPayload.calibration, "calibration evidence");
      const lift = record(commandPayload.lift, "lift evidence");
      const roc = record(curvesPayload.roc, "ROC curve");
      const pr = record(curvesPayload.pr, "precision-recall curve");
      expect(curvesPayload.ok).toBe(true);
      expect(text(curvesPayload.evaluation_package_id)).toBe(
        checkpoint.evaluation_package_id,
      );
      expect(text(curvesPayload.analysis_binding)).toBe(
        "exact_completed_package",
      );
      expect(Array.isArray(roc.fpr)).toBe(true);
      expect(roc.fpr.length).toBeGreaterThan(2);
      expect(roc.tpr).toHaveLength(roc.fpr.length);
      expect(Array.isArray(pr.recall)).toBe(true);
      expect(pr.recall.length).toBeGreaterThan(2);
      expect(pr.precision).toHaveLength(pr.recall.length);
      expect(Array.isArray(calibration.rows)).toBe(true);
      expect(calibration.rows.length).toBeGreaterThan(1);
      expect(Array.isArray(lift.deciles)).toBe(true);
      expect(lift.deciles.length).toBeGreaterThan(1);
      coverage.push({
        step: "Step08 Evaluation",
        control: "exact durable identity hydration",
        result: "passed",
        evidence: "Training, candidate-decision, and Evaluation-package responses matched every Stage A identifier.",
      });

      // Step 08: inspect every major analysis surface and exercise review,
      // comparison, all three Interpretation entry points, and the page-level
      // continue action without permitting any candidate fallback.
      await expect(page.getByTestId("evaluation-command-center")).toBeVisible();
      const selectionEvidence = page.getByTestId("selection-evidence");
      await expect(selectionEvidence).toContainText(checkpoint.candidate_id);
      await expect(selectionEvidence).toContainText(
        checkpoint.candidate_decision_id,
      );
      await expectLabeledValue(
        selectionEvidence,
        selectionMetricLabel(selectionMetric),
        fixed(selectionMetric.value, "rendered selection metric"),
      );
      await expectLabeledValue(
        selectionEvidence,
        "Selection partition",
        text(selectionMetric.partition_id),
      );
      await expectLabeledValue(
        selectionEvidence,
        "Fold summary",
        `${selectionMetric.fold_count} folds`,
      );
      const holdout = page.getByTestId("final-holdout-evidence");
      await expect(holdout).toContainText(checkpoint.evaluation_package_id);
      await expect(holdout).toContainText(/reporting.only/i);
      await expect(holdout).toContainText(/cannot.*select features/i);
      await expectLabeledValue(
        holdout,
        "PR-AUC · final holdout",
        fixed(finalHoldoutMetrics.pr_auc, "final-holdout PR-AUC"),
      );
      await expectLabeledValue(
        holdout,
        "Isolation status",
        evaluationIsolationStatus,
      );
      for (const testId of [
        "top-candidate-comparison",
        "interactive-model-explorer",
        "visual-intelligence-evaluation",
        "threshold-operating-policy",
        "dataset-performance",
        "stability-calibration",
        "full-leaderboard",
        "interpretation-comparison-tray",
      ]) {
        await expect(page.getByTestId(testId)).toBeVisible();
      }

      const reviewButton = page.getByRole("button", {
        name: "Review Locked Candidate",
        exact: true,
      });
      await expect(reviewButton).toHaveCount(1);
      const lockedCard = reviewButton.locator("xpath=ancestor::article[1]");
      await reviewButton.click();
      const explorer = page.getByTestId("interactive-model-explorer");
      await expect(explorer).toContainText(
        /locked/i,
      );
      await expectLabeledValue(
        explorer,
        "PR-AUC · final holdout",
        fixed(finalHoldoutMetrics.pr_auc, "explorer final-holdout PR-AUC"),
      );
      await expectLabeledValue(
        explorer,
        "Final-holdout ROC-AUC",
        fixed(finalHoldoutMetrics.roc_auc, "explorer final-holdout ROC-AUC"),
      );
      await expectLabeledValue(
        explorer,
        "Final-holdout recall",
        fixed(finalHoldoutMetrics.recall, "explorer final-holdout recall"),
      );
      const rocChart = explorer.getByRole("img", {
        name: "True positive rate by False positive rate",
      });
      const prChart = explorer.getByRole("img", {
        name: "Precision by Recall",
      });
      await expect(rocChart).toBeVisible();
      await expect(prChart).toBeVisible();
      expect(svgPointCount(await rocChart.locator("polyline").getAttribute("points"))).toBe(
        roc.fpr.length,
      );
      expect(svgPointCount(await prChart.locator("polyline").getAttribute("points"))).toBe(
        pr.recall.length,
      );
      const explorerConfusion = explorer
        .getByRole("heading", {
          name: `Confusion Matrix @ ${finite(thresholdMetrics.threshold, "threshold").toFixed(3)}`,
        })
        .locator("xpath=../..");
      for (const value of (thresholdMetrics.confusion as number[][]).flat()) {
        await expect(explorerConfusion).toContainText(value.toLocaleString());
      }

      const thresholdPolicy = page.getByTestId("threshold-operating-policy");
      const thresholdLabel = finite(thresholdMetrics.threshold, "deployment threshold").toFixed(3);
      await expect(thresholdPolicy).toContainText(thresholdLabel);
      const thresholdLiveMetrics = thresholdPolicy.getByTestId("threshold-live-metrics");
      await expectLabeledValue(
        thresholdLiveMetrics,
        `Precision @ ${thresholdLabel}`,
        percent(thresholdMetrics.precision, "threshold precision"),
      );
      await expectLabeledValue(
        thresholdLiveMetrics,
        `Recall @ ${thresholdLabel}`,
        percent(thresholdMetrics.recall, "threshold recall"),
      );
      await expectLabeledValue(
        thresholdLiveMetrics,
        `F1 @ ${thresholdLabel}`,
        fixed(thresholdMetrics.f1, "threshold F1"),
      );
      await expectLabeledValue(
        thresholdLiveMetrics,
        "False positives",
        finite(thresholdMetrics.false_positives, "false positives").toLocaleString(),
      );
      const reportingRoc = thresholdLiveMetrics.getByRole("img", {
        name: "Final holdout ROC reporting curve",
      });
      await expect(reportingRoc).toBeVisible();
      expect(svgPointCount(await reportingRoc.locator("polyline").getAttribute("points"))).toBe(
        roc.fpr.length,
      );

      const calibrationSection = page.getByTestId("stability-calibration");
      const reliabilityCurve = calibrationSection.getByRole("img", {
        name: "Observed event rate by Mean predicted probability",
      });
      await expect(reliabilityCurve).toBeVisible();
      expect(svgPointCount(await reliabilityCurve.locator("polyline").getAttribute("points"))).toBe(
        calibration.rows.length,
      );
      await expectLabeledValue(
        calibrationSection,
        "Brier score",
        fixed(calibration.brier_score, "calibration Brier score"),
      );

      const liftSection = page.getByTestId("lift-gain-capture");
      await expect(liftSection.locator("svg polyline")).toHaveCount(3);
      for (const polyline of await liftSection.locator("svg polyline").all()) {
        expect(svgPointCount(await polyline.getAttribute("points"))).toBe(lift.deciles.length + 1);
      }
      const firstLiftRow = record(lift.deciles[0], "first lift decile");
      await expectExactTableRow(
        liftSection.locator("table"),
        text(firstLiftRow.decile),
        [
          text(firstLiftRow.decile),
          finite(firstLiftRow.n, "lift rows").toLocaleString(),
          finite(firstLiftRow.positives, "lift events").toLocaleString(),
          percent(firstLiftRow.event_rate, "lift event rate"),
          finite(firstLiftRow.lift, "lift value").toFixed(2),
          percent(firstLiftRow.capture_rate, "lift capture"),
          finite(firstLiftRow.mean_score, "lift mean score").toFixed(4),
        ],
      );

      const fullLeaderboard = page.getByTestId("full-leaderboard");
      const lockedMetric = normalizedSelectionMetric(
        record(candidate?.selection_metric, "locked candidate selection metric"),
      );
      const lockedModelName = cleanModelName(candidate?.name);
      expect(lockedModelName).not.toBe("");
      const lockedLeaderboardRow = fullLeaderboard
        .locator("tbody tr")
        .filter({ hasText: lockedModelName })
        .filter({ hasText: "Locked" });
      await expect(lockedLeaderboardRow).toHaveCount(1);
      await expect(lockedLeaderboardRow).toContainText(
        fixed(lockedMetric.value, "leaderboard selection value"),
      );
      await expect(lockedLeaderboardRow).toContainText(text(lockedMetric.partition_id));
      await expect(lockedLeaderboardRow).toContainText(`${lockedMetric.fold_count} folds`);
      await expect(lockedLeaderboardRow).toContainText(
        `std. dev. ${fixed(lockedMetric.standard_deviation, "leaderboard standard deviation")}`,
      );
      await expect(lockedLeaderboardRow).toContainText("Locked");
      const addComparison = lockedCard.getByRole("button", {
        name: "Add to Comparison",
        exact: true,
      });
      await addComparison.click();
      await expect(lockedCard.getByRole("button", { name: "Remove from Comparison" })).toBeVisible();
      const candidateRanking = page.getByTestId("top-candidate-comparison");
      const challengerAdd = candidateRanking.getByRole("button", {
        name: "Add to Comparison",
        exact: true,
      }).first();
      await expect(challengerAdd).toBeVisible();
      const challengerCard = challengerAdd.locator("xpath=ancestor::article[1]");
      const challengerName = text(await challengerCard.getByRole("heading").innerText());
      expect(challengerName).not.toBe("");
      const challengerCandidate = rankedCandidates(lastTrainingPayload).find(
        (row) =>
          text(row.candidate_id) !== checkpoint.candidate_id &&
          cleanModelName(row.name) === challengerName,
      );
      const challengerCandidateId = text(challengerCandidate?.candidate_id);
      expect(challengerCandidateId).not.toBe("");
      await challengerAdd.click();
      const comparisonTray = page.getByTestId("interpretation-comparison-tray");
      await expect(comparisonTray).not.toContainText(
        "No model will be automatically selected",
      );
      await expect(comparisonTray.locator("article")).toHaveCount(2);
      const challengerTrayCard = comparisonTray
        .locator("article")
        .filter({ hasText: challengerName });
      await expect(challengerTrayCard).toHaveCount(1);
      await challengerTrayCard.getByTitle("Remove from Comparison").click();
      await expect(comparisonTray.locator("article")).toHaveCount(1);
      await expect(comparisonTray).not.toContainText(challengerName);
      await challengerCard.getByRole("button", { name: "Add to Comparison", exact: true }).click();
      await expect(comparisonTray.locator("article")).toHaveCount(2);
      await expect(comparisonTray).toContainText(challengerName);
      await exerciseVisibleTabs(page, "Step08 Evaluation", coverage);
      await shot(page, testInfo, "step08-exact-candidate-review-and-comparison");
      coverage.push({
        step: "Step08 Evaluation",
        control: "locked candidate review and comparison",
        result: "passed",
        evidence: "Backend curve points, threshold/calibration/lift values, the frozen leaderboard row, and tray add/remove state rendered for the exact locked candidate.",
      });

      // Page-level Continue is the primary next-page control and must carry all
      // four exact handoff identifiers in the URL.
      await strictContinue(page, checkpoint.project_id, "step09");
      assertInterpretationUrl(page, checkpoint, [
        checkpoint.candidate_id,
        challengerCandidateId,
      ]);
      await page.goBack();
      await expectExactStep(page, checkpoint.project_id, "step08");
      await expect(page.getByTestId("evaluation-command-center")).toBeVisible({ timeout: 180_000 });
      const reopenedTray = page.getByTestId("interpretation-comparison-tray");
      const clearComparison = reopenedTray.getByRole("button", {
        name: "Clear Comparison",
        exact: true,
      });
      await expect(clearComparison).toBeEnabled();
      await clearComparison.click();
      await expect(reopenedTray).toContainText("No model will be automatically selected");
      const reopenedLockedCard = page
        .getByRole("button", { name: "Review Locked Candidate", exact: true })
        .locator("xpath=ancestor::article[1]");
      await reopenedLockedCard.getByRole("button", { name: "Add to Comparison", exact: true }).click();
      await page
        .getByTestId("top-candidate-comparison")
        .getByRole("button", { name: "Add to Comparison", exact: true })
        .first()
        .click();
      await expect(reopenedTray.locator("article")).toHaveCount(2);
      const trayOpen = reopenedTray.getByRole("button", {
        name: "Open Reviewed Candidate",
        exact: true,
      });
      await expect(trayOpen).toBeEnabled();
      await trayOpen.click();
      await expectExactStep(page, checkpoint.project_id, "step09");
      assertInterpretationUrl(page, checkpoint, [
        checkpoint.candidate_id,
        challengerCandidateId,
      ]);
      await page.goBack();
      await expectExactStep(page, checkpoint.project_id, "step08");
      await expect(page.getByTestId("evaluation-command-center")).toBeVisible({ timeout: 180_000 });
      const directInterpretation = page
        .getByRole("button", { name: "Review Locked Candidate", exact: true })
        .locator("xpath=ancestor::article[1]")
        .getByRole("button", { name: "Open Interpretation", exact: true });
      await expect(directInterpretation).toBeEnabled();
      const importanceResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/importance"),
        { timeout: 180_000 },
      );
      const shapResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/shap"),
        { timeout: 180_000 },
      );
      await directInterpretation.click();
      await expectExactStep(page, checkpoint.project_id, "step09");
      assertInterpretationUrl(page, checkpoint, [
        checkpoint.candidate_id,
        challengerCandidateId,
      ]);
      const [importancePayload, shapPayload] = await Promise.all([
        importanceResponsePromise.then(responseJson),
        shapResponsePromise.then(responseJson),
      ]);
      expect(importancePayload.ok).toBe(true);
      expect(shapPayload.ok).toBe(true);
      expect(text(importancePayload.evaluation_package_id)).toBe(
        checkpoint.evaluation_package_id,
      );
      expect(text(shapPayload.evaluation_package_id)).toBe(
        checkpoint.evaluation_package_id,
      );
      const importanceRows = importancePayload.rows as Array<Record<string, any>>;
      const shapRows = shapPayload.rows as Array<Record<string, any>>;
      expect(Array.isArray(importanceRows)).toBe(true);
      expect(importanceRows.length).toBeGreaterThan(0);
      expect(Array.isArray(shapRows)).toBe(true);
      expect(shapRows.length).toBeGreaterThan(0);
      coverage.push({
        step: "Step08 Evaluation",
        control: "three exact Interpretation navigation controls",
        result: "passed",
        evidence: "Continue, Open Reviewed Candidate, and Open Interpretation all preserved the exact handoff query.",
      });

      // Step 09: verify provenance, change the explained feature with exact
      // backend responses, run RFE, and inspect the resulting feature table.
      await expect(page.getByRole("heading", {
        name: "Step 9: Model Interpretation and Final Model",
      })).toBeVisible({ timeout: 180_000 });
      const interpretationComparison = page.getByTestId("interpretation-candidate-comparison");
      await expect(interpretationComparison).toBeVisible();
      await expect(interpretationComparison.locator("article")).toHaveCount(2);
      const lockedComparisonCard = interpretationComparison.locator(
        `article[data-candidate-id="${checkpoint.candidate_id}"]`,
      );
      const challengerComparisonCard = interpretationComparison.locator(
        `article[data-candidate-id="${challengerCandidateId}"]`,
      );
      await expect(lockedComparisonCard).toContainText("Locked candidate");
      await expect(challengerComparisonCard).toContainText("Selection-evidence challenger");
      await expect(interpretationComparison).toContainText(/development-selection evidence only/i);
      await expect(interpretationComparison).toContainText(/cannot open the final holdout/i);
      for (const comparisonCandidate of [
        record(candidate, "locked comparison candidate"),
        record(challengerCandidate, "challenger comparison candidate"),
      ]) {
        const candidateId = text(comparisonCandidate.candidate_id);
        const metric = normalizedSelectionMetric(
          record(
            comparisonCandidate.selection_metric,
            `${candidateId} comparison selection metric`,
          ),
        );
        const card = interpretationComparison.locator(
          `article[data-candidate-id="${candidateId}"]`,
        );
        await expect(card).toContainText(
          fixed(metric.value, `${candidateId} comparison metric value`),
        );
        await expect(card).toContainText(text(metric.partition_id));
        await expect(card).toContainText(`${finite(metric.fold_count, `${candidateId} fold count`)} folds`);
      }
      const provenance = page.getByTestId("interpretation-selection-holdout-provenance");
      await expect(provenance).toContainText(checkpoint.candidate_decision_id);
      await expect(provenance).toContainText(checkpoint.evaluation_package_id);
      await expect(provenance).toContainText(/reporting-only/i);
      await expect(provenance).toContainText(/cannot change the candidate, features, calibration, or threshold/i);

      const decisionBoundarySection = page.getByTestId("decision-boundary-section");
      await expect(decisionBoundarySection).toBeVisible({ timeout: 180_000 });
      const boundaryXSelect = page.getByLabel("Decision boundary X feature");
      const boundaryYSelect = page.getByLabel("Decision boundary Y feature");
      await expect.poll(async () => (await optionValues(boundaryXSelect)).length, {
        timeout: 180_000,
      }).toBeGreaterThan(2);
      const initialBoundaryX = await boundaryXSelect.inputValue();
      const initialBoundaryY = await boundaryYSelect.inputValue();
      const alternateBoundaryX = (await optionValues(boundaryXSelect)).find(
        (feature) =>
          !feature.startsWith("PCA") &&
          feature !== initialBoundaryX &&
          feature !== initialBoundaryY,
      );
      expect(alternateBoundaryX, "an alternate numeric X feature").toBeTruthy();
      const boundaryXResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/decision_boundary")) return false;
        return new URL(response.url()).searchParams.get("x_feature") === alternateBoundaryX;
      }, { timeout: 180_000 });
      await boundaryXSelect.selectOption(alternateBoundaryX!);
      const boundaryXResponse = await boundaryXResponsePromise;
      const boundaryXPayload = await responseJson(boundaryXResponse);
      expect(text(new URL(boundaryXResponse.url()).searchParams.get("candidate_id"))).toBe(
        checkpoint.candidate_id,
      );
      expect(text(new URL(boundaryXResponse.url()).searchParams.get("evaluation_package_id"))).toBe(
        checkpoint.evaluation_package_id,
      );
      expect(text(boundaryXPayload.x_feature)).toBe(alternateBoundaryX);
      expect(text(boundaryXPayload.y_feature)).not.toBe("");
      expect(text(boundaryXPayload.y_feature)).not.toBe(alternateBoundaryX);
      await expect(boundaryXSelect).toHaveValue(text(boundaryXPayload.x_feature));
      await expect(boundaryYSelect).toHaveValue(text(boundaryXPayload.y_feature));
      await expectExactBoundaryRendering(decisionBoundarySection, boundaryXPayload);

      const previousBoundaryY = await boundaryYSelect.inputValue();
      const alternateBoundaryY = (await optionValues(boundaryYSelect)).find(
        (feature) =>
          !feature.startsWith("PCA") &&
          feature !== previousBoundaryY &&
          feature !== alternateBoundaryX,
      );
      expect(alternateBoundaryY, "an alternate numeric Y feature").toBeTruthy();
      const boundaryYResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/decision_boundary")) return false;
        const query = new URL(response.url()).searchParams;
        return query.get("x_feature") === alternateBoundaryX && query.get("y_feature") === alternateBoundaryY;
      }, { timeout: 180_000 });
      await boundaryYSelect.selectOption(alternateBoundaryY!);
      const boundaryYPayload = await boundaryYResponsePromise.then(responseJson);
      expect(text(boundaryYPayload.x_feature)).toBe(alternateBoundaryX);
      expect(text(boundaryYPayload.y_feature)).toBe(alternateBoundaryY);
      await expect(boundaryXSelect).toHaveValue(alternateBoundaryX!);
      await expect(boundaryYSelect).toHaveValue(alternateBoundaryY!);
      await expectExactBoundaryRendering(decisionBoundarySection, boundaryYPayload);
      coverage.push({
        step: "Step09 Interpretation",
        control: "Decision Boundary X and Y selectors",
        result: "passed",
        evidence: "Both numeric feature selectors issued exact candidate/evaluation-bound requests; the returned axes, complete response grid, observed points, and projected SVG geometry matched backend values.",
      });

      await expect(page.getByRole("heading", { name: "Feature Importance" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "SHAP Summary" })).toBeVisible();
      const importanceSection = page
        .getByRole("heading", { name: "Feature Importance" })
        .locator("xpath=ancestor::section[1]");
      const shapSection = page
        .getByRole("heading", { name: "SHAP Summary" })
        .locator("xpath=ancestor::section[1]");
      for (const row of importanceRows.slice(0, 3)) {
        const rendered = importanceSection
          .getByText(text(row.feature), { exact: true })
          .locator("xpath=..");
        await expect(rendered).toHaveCount(1);
        await expect(rendered).toContainText(fixed(row.importance, `${row.feature} importance`));
      }
      for (const row of shapRows.slice(0, 3)) {
        const rendered = shapSection
          .getByText(text(row.feature), { exact: true })
          .locator("xpath=..");
        await expect(rendered).toHaveCount(1);
        await expect(rendered).toContainText(fixed(row.importance, `${row.feature} SHAP value`));
      }
      const pdpSection = page
        .getByRole("heading", { name: "PDP / Sensitivity" })
        .locator("xpath=ancestor::section[1]");
      const featureSelect = pdpSection.locator("select");
      await expect(featureSelect).toBeEnabled({ timeout: 180_000 });
      const features = await optionValues(featureSelect);
      expect(features.length).toBeGreaterThan(1);
      const previousFeature = await featureSelect.inputValue();
      const selectedFeature = features.find((value) => value !== previousFeature)!;
      const pdpResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/pdp")) return false;
        return new URL(response.url()).searchParams.get("feature") === selectedFeature;
      }, { timeout: 90_000 });
      const sensitivityResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/sensitivity")) return false;
        return new URL(response.url()).searchParams.get("feature") === selectedFeature;
      }, { timeout: 90_000 });
      await featureSelect.selectOption(selectedFeature);
      const [pdpPayload, sensitivityPayload] = await Promise.all([
        pdpResponsePromise.then(responseJson),
        sensitivityResponsePromise.then(responseJson),
      ]);
      expect(pdpPayload.ok).toBe(true);
      expect(sensitivityPayload.ok).toBe(true);
      const pdpRows = pdpPayload.rows as Array<Record<string, any>>;
      const sensitivityRows = sensitivityPayload.rows as Array<Record<string, any>>;
      expect(Array.isArray(pdpRows)).toBe(true);
      expect(pdpRows.length).toBeGreaterThan(1);
      expect(Array.isArray(sensitivityRows)).toBe(true);
      expect(sensitivityRows.length).toBeGreaterThan(0);
      await expect(featureSelect).toHaveValue(selectedFeature);
      await expect(pdpSection).toContainText(selectedFeature);
      const pdpChart = pdpSection.locator("svg");
      await expect(pdpChart).toBeVisible();
      await expect(pdpChart.locator("circle")).toHaveCount(pdpRows.length);
      await expect(pdpChart.locator("polyline")).toHaveAttribute(
        "points",
        expectedPdpPoints(pdpRows),
      );
      const firstSensitivity = sensitivityRows[0];
      await expectExactTableRow(
        pdpSection.locator("table"),
        text(firstSensitivity.scenario),
        [
          text(firstSensitivity.scenario),
          fixed(firstSensitivity.prediction, "sensitivity prediction"),
          fixed(firstSensitivity.delta, "sensitivity delta"),
        ],
      );
      coverage.push({
        step: "Step09 Interpretation",
        control: "Evaluation comparison handoff",
        result: "passed",
        evidence: "The exact two-candidate comparison query re-resolved to backend candidate rows and rendered development-only selection evidence without changing the locked Interpretation candidate.",
      });
      coverage.push({
        step: "Step09 Interpretation",
        control: "PDP / Sensitivity feature selector",
        result: "passed",
        evidence: "Changing features rendered the exact backend PDP polyline/points and sensitivity scenario values for the selected feature.",
      });

      const rfeButton = page.getByRole("button", { name: /^Run RFE$/ });
      await expect(rfeButton).toBeEnabled({ timeout: 90_000 });
      const rfeResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/rfe"),
        { timeout: 90_000 },
      );
      await rfeButton.click();
      const rfePayload = await rfeResponsePromise.then(responseJson);
      expect(rfePayload.ok).toBe(true);
      expect(Array.isArray(rfePayload.rows)).toBe(true);
      expect(rfePayload.rows.length).toBeGreaterThan(0);
      expect(Array.isArray(rfePayload.curve)).toBe(true);
      expect(rfePayload.curve.length).toBeGreaterThan(1);
      await expect(page.getByRole("button", { name: "Rerun RFE" })).toBeVisible({ timeout: 90_000 });
      const rfeSection = page
        .getByRole("heading", { name: "Recursive Feature Elimination" })
        .locator("xpath=ancestor::section[1]");
      const recommendedCount = finite(
        rfePayload.recommended_count,
        "recommended RFE feature count",
      );
      const bestCount = finite(rfePayload.best_count, "best RFE feature count");
      const bestAuc = finite(rfePayload.best_auc, "best RFE AUC");
      await expect(rfeSection).toContainText(`Analysis point: ${recommendedCount} features`);
      await expect(rfeSection).toContainText(
        `Best RFE point: ${bestCount} features at AUC ${bestAuc.toFixed(4)}`,
      );
      const rfeChart = rfeSection.locator("svg");
      await expect(rfeChart).toBeVisible();
      await expect(rfeChart.locator("rect")).toHaveCount(rfePayload.curve.length);
      await expect(rfeChart.locator("circle")).toHaveCount(rfePayload.curve.length);
      expect(svgPointCount(await rfeChart.locator("polyline").getAttribute("points"))).toBe(
        rfePayload.curve.length,
      );
      const firstRfeRow = record(rfePayload.rows[0], "first RFE row");
      await expectExactTableRow(
        rfeSection.locator("table"),
        text(firstRfeRow.feature),
        [
          text(firstRfeRow.feature),
          finite(firstRfeRow.rank, "RFE rank") <= recommendedCount ? "Yes" : "No",
          text(firstRfeRow.rank),
          typeof firstRfeRow.importance === "number"
            ? firstRfeRow.importance.toFixed(4)
            : "-",
        ],
      );
      coverage.push({
        step: "Step09 Interpretation",
        control: "Run RFE",
        result: "passed",
        evidence: "The exact recommended/best AUC values, curve point count, and per-feature selection row rendered from the backend RFE response.",
      });

      // Promotion must not report success until the durable registry response
      // contains a verified model version and the complete exact lineage.
      const saveFinal = page.getByRole("button", { name: "Save as Final Model", exact: true });
      await expect(saveFinal).toBeEnabled({ timeout: 90_000 });
      await expect(page.getByTestId("durable-final-model-contract")).toHaveCount(0);
      const promotionResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/model/save_final", "POST"),
        { timeout: 180_000 },
      );
      const sensitivitySummaryResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/sensitivity_summary"),
        { timeout: 180_000 },
      );
      const vifResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/vif"),
        { timeout: 180_000 },
      );
      await saveFinal.click();
      const promotionPayload = await promotionResponsePromise.then(responseJson);
      const version = (promotionPayload.modelVersion ?? {}) as Record<string, any>;
      const promotion = (promotionPayload.promotion ?? {}) as Record<string, any>;
      const model = (promotionPayload.model ?? {}) as Record<string, any>;
      const lineage = (version.lineage ?? {}) as Record<string, any>;
      modelVersionId = text(field(version, "modelVersionId", "model_version_id"));
      const returnedModelId = text(field(version, "modelId", "model_id"));
      expect(modelVersionId).not.toBe("");
      expect(returnedModelId).not.toBe("");
      expect(text(field(version, "projectId", "project_id"))).toBe(checkpoint.project_id);
      expect(text(field(version, "datasetId", "dataset_id"))).toBe(checkpoint.dataset_id);
      expect(text(field(version, "datasetVersionId", "dataset_version_id"))).toBe(
        checkpoint.dataset_version_id,
      );
      expect(text(field(version, "trainingRunId", "training_run_id"))).toBe(
        checkpoint.training_run_id,
      );
      expect(text(field(version, "evaluationPackageId", "evaluation_package_id"))).toBe(
        checkpoint.evaluation_package_id,
      );
      expect(text(field(version, "candidateDecisionId", "candidate_decision_id"))).toBe(
        checkpoint.candidate_decision_id,
      );
      expect(text(field(lineage, "candidateId", "candidate_id"))).toBe(checkpoint.candidate_id);
      expect(text(field(lineage, "trainingJobId", "training_job_id"))).toBe(
        checkpoint.training_job_id,
      );
      expect(text(field(lineage, "trainingRunId", "training_run_id"))).toBe(
        checkpoint.training_run_id,
      );
      expect(text(field(lineage, "splitId", "split_id"))).toBe(candidateLineage.split_id);
      expect(text(field(lineage, "validationDesignId", "validation_design_id"))).toBe(
        candidateLineage.validation_design_id,
      );
      expect(text(field(lineage, "validationDesignVersion", "validation_design_version"))).toBe(
        candidateLineage.validation_design_version,
      );
      expect(text(field(lineage, "featureManifestVersion", "feature_manifest_version"))).toBe(
        candidateLineage.feature_manifest_version,
      );
      expect(text(field(lineage, "target", "target_name"))).toBe(candidateLineage.target);
      expect(promotion.status).toBe("finalized");
      expect(promotion.artifactVerified).toBe(true);
      expect(promotion.lineageStatus).toBe("verified");
      const promotedChecksum = text(promotion.checksum ?? version.checksum);
      expect(promotedChecksum).not.toBe("");
      expect(text(field(version, "selectionIntegrityStatus", "selection_integrity_status"))).toBe("verified");
      expect(text(field(version, "holdoutIsolationStatus", "holdout_isolation_status"))).toBe("verified");
      expect(text(field(version, "evaluationPackageIntegrityStatus", "evaluation_package_integrity_status"))).toBe("verified");
      expect(text(field(version, "promotionReadinessStatus", "promotion_readiness_status"))).toBe("verified");
      expect(text(field(version, "finalHoldoutStatus", "final_holdout_status"))).toBe("evaluated");
      if (text(promotion.designation) === "champion") {
        expect(text(field(model, "currentVersionId", "current_version_id"))).toBe(modelVersionId);
      }
      const durableContract = page.getByTestId("durable-final-model-contract");
      await expect(durableContract).toBeVisible({ timeout: 180_000 });
      await expect(durableContract).toContainText(modelVersionId);
      await expect(durableContract).toContainText(checkpoint.dataset_version_id);
      await expect(durableContract).toContainText(/verified/i);
      await expect(durableContract).toContainText(/reporting only/i);

      const [sensitivitySummaryResponse, vifResponse] = await Promise.all([
        sensitivitySummaryResponsePromise,
        vifResponsePromise,
      ]);
      for (const response of [sensitivitySummaryResponse, vifResponse]) {
        const query = new URL(response.url()).searchParams;
        expect(query.get("candidate_id")).toBe(checkpoint.candidate_id);
        expect(query.get("training_run_id")).toBe(checkpoint.training_run_id);
        expect(query.get("evaluation_package_id")).toBe(checkpoint.evaluation_package_id);
        expect(query.get("candidate_decision_id")).toBe(checkpoint.candidate_decision_id);
        expect(query.get("model_version_id")).toBe(modelVersionId);
      }
      const [sensitivitySummaryPayload, vifPayload] = await Promise.all([
        responseJson(sensitivitySummaryResponse),
        responseJson(vifResponse),
      ]);
      expect(sensitivitySummaryPayload.ok).toBe(true);
      expect(vifPayload.ok).toBe(true);
      const sensitivitySummaryRows = sensitivitySummaryPayload.rows as Array<Record<string, any>>;
      const vifRows = vifPayload.rows as Array<Record<string, any>>;
      expect(Array.isArray(sensitivitySummaryRows)).toBe(true);
      expect(sensitivitySummaryRows.length).toBeGreaterThan(0);
      expect(Array.isArray(vifRows)).toBe(true);
      expect(vifRows.length).toBeGreaterThan(1);

      const finalSensitivitySection = page
        .getByRole("heading", { name: "Final Model Sensitivity Analysis", exact: true })
        .locator("xpath=ancestor::section[1]");
      const finalSensitivityTable = finalSensitivitySection.locator("table");
      await expect(finalSensitivityTable.locator("tbody tr")).toHaveCount(
        sensitivitySummaryRows.length,
        { timeout: 180_000 },
      );
      const firstSensitivitySummary = record(
        sensitivitySummaryRows[0],
        "first final sensitivity summary row",
      );
      const sensitivityDelta =
        firstSensitivitySummary.delta ?? firstSensitivitySummary.worst_delta;
      const expectedDirection =
        text(firstSensitivitySummary.direction_explanation) ||
        (finite(sensitivityDelta, "final sensitivity delta") >= 0
          ? "Increasing this feature increases predicted bad risk."
          : "Increasing this feature decreases predicted bad risk.");
      const expectedFeatureCell = [
        text(firstSensitivitySummary.feature),
        text(firstSensitivitySummary.special_value_note),
      ].filter(Boolean).join(" ");
      const finalSensitivityCells = (
        await finalSensitivityTable.locator("tbody tr").first().getByRole("cell").allInnerTexts()
      ).map((value) => value.trim().replace(/\s+/g, " "));
      expect(finalSensitivityCells).toEqual([
        expectedFeatureCell,
        firstSensitivitySummary.negative_scenario_prediction == null
          ? "-"
          : fixed(firstSensitivitySummary.negative_scenario_prediction, "negative scenario prediction"),
        firstSensitivitySummary.positive_scenario_prediction == null
          ? "-"
          : fixed(firstSensitivitySummary.positive_scenario_prediction, "positive scenario prediction"),
        fixed(
          firstSensitivitySummary.baseline_prediction ?? firstSensitivitySummary.baseline,
          "final sensitivity baseline prediction",
        ),
        text(firstSensitivitySummary.largest_scenario ?? firstSensitivitySummary.worst_scenario),
        fixed(sensitivityDelta, "final sensitivity delta"),
        expectedDirection,
        "",
      ]);

      const vifSection = page
        .getByRole("heading", { name: "Variance Inflation Factor", exact: true })
        .locator("xpath=ancestor::section[1]");
      await expect(vifSection.locator("tbody tr")).toHaveCount(vifRows.length, {
        timeout: 180_000,
      });
      const firstVif = record(vifRows[0], "first final-model VIF row");
      await expectExactTableRow(vifSection.locator("table"), text(firstVif.feature), [
        text(firstVif.feature),
        fixed(firstVif.vif, "final-model VIF", 3),
        fixed(firstVif.tolerance, "final-model VIF tolerance"),
        fixed(firstVif.r_squared, "final-model VIF R-squared"),
        text(firstVif.status),
      ]);
      coverage.push({
        step: "Step09 Interpretation",
        control: "registered-model sensitivity and VIF",
        result: "passed",
        evidence: "Promotion triggered candidate-, decision-, evaluation-, and model-version-bound diagnostics; every returned row rendered, with exact first sensitivity and VIF row values.",
      });

      const restoredFinalStatusPromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/model/final/status"),
        { timeout: 180_000 },
      );
      const exactRecoveryPath = `/api/model-versions/${encodeURIComponent(modelVersionId)}/recovery-status`;
      const restoredRecoveryPromise = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return (
          url.origin === isolated.backendOrigin &&
          url.pathname === exactRecoveryPath &&
          response.request().method() === "GET"
        );
      }, { timeout: 180_000 });
      await page.reload();
      await expectExactStep(page, checkpoint.project_id, "step09");
      const [restoredFinalStatus, restoredRecoveryStatus] = await Promise.all([
        restoredFinalStatusPromise.then(responseJson),
        restoredRecoveryPromise.then(responseJson),
      ]);
      expect(restoredFinalStatus.ready).toBe(true);
      const restoredMetadata = record(restoredFinalStatus.metadata, "restored final-model metadata");
      expect(text(restoredMetadata.model_version_id ?? restoredMetadata.modelVersionId)).toBe(modelVersionId);
      expect(text(restoredMetadata.project_id ?? restoredMetadata.projectId)).toBe(checkpoint.project_id);
      expect(text(restoredMetadata.training_dataset_id ?? restoredMetadata.dataset_id)).toBe(checkpoint.dataset_id);
      expect(
        text(restoredMetadata.training_dataset_version_id ?? restoredMetadata.dataset_version_id),
      ).toBe(checkpoint.dataset_version_id);
      const recovery = record(restoredRecoveryStatus.recovery, "restored exact model recovery");
      expect(text(recovery.modelVersionId ?? recovery.model_version_id)).toBe(modelVersionId);
      expect(text(recovery.projectId ?? recovery.project_id)).toBe(checkpoint.project_id);
      expect(text(recovery.checksum)).toBe(promotedChecksum);
      expect(recovery.artifactVerified ?? recovery.artifact_verified).toBe(true);
      await expect(page.getByTestId("durable-final-model-contract")).toContainText(modelVersionId, {
        timeout: 180_000,
      });
      await expect(page.getByTestId("durable-final-model-contract")).toContainText(/verified/i);
      await expect(page.getByText(/artifact checksum verification passed/i)).toBeVisible();
      await shot(page, testInfo, "step09-hard-reload-exact-model-recovery");
      coverage.push({
        step: "Step09 Interpretation",
        control: "hard-reload exact final-model recovery",
        result: "passed",
        evidence: "A hard reload recovered the exact durable model_version_id from backend status and reverified the identical artifact checksum before Scoring was opened.",
      });
      await shot(page, testInfo, "step09-durable-final-model-promotion");
      await exerciseVisibleTabs(page, "Step09 Interpretation", coverage);
      coverage.push({
        step: "Step09 Interpretation",
        control: "Save as Final Model",
        result: "passed",
        evidence: "The UI reported success only after a verified durable model_version_id with exact lineage was returned.",
      });

      // Step 10: exercise TRAIN, External Validation, and OOT scoring with the
      // deterministic disposable schema, then prove exact durable run recovery
      // after a hard reload before allowing continuation.
      const finalStatusPromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/model/final/status"),
        { timeout: 180_000 },
      );
      await strictContinue(page, checkpoint.project_id, "step10");
      const finalStatus = await finalStatusPromise.then(responseJson);
      expect(finalStatus.ready).toBe(true);
      const finalMetadata = (finalStatus.metadata ?? {}) as Record<string, any>;
      expect(text(finalMetadata.model_version_id ?? finalMetadata.modelVersionId)).toBe(modelVersionId);
      expect(text(finalMetadata.project_id ?? finalMetadata.projectId)).toBe(checkpoint.project_id);
      expect(text(finalMetadata.training_dataset_id ?? finalMetadata.dataset_id)).toBe(
        checkpoint.dataset_id,
      );
      expect(text(finalMetadata.training_dataset_version_id ?? finalMetadata.dataset_version_id)).toBe(
        checkpoint.dataset_version_id,
      );
      await expect(page.getByTestId("final-model-scoring-contract")).toContainText(modelVersionId, {
        timeout: 180_000,
      });

      const scoringFixture = writeStrictPredictiveFixture(testInfo, 240);
      const testCsv = testInfo.outputPath("strict-predictive-external-validation.csv");
      const ootCsv = testInfo.outputPath("strict-predictive-oot.csv");
      fs.copyFileSync(scoringFixture.filePath, testCsv);
      fs.copyFileSync(scoringFixture.filePath, ootCsv);

      const trainZone = page.getByTestId("train-scoring-zone");
      const trainResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/score/development-split", "POST")) return false;
        return new URL(response.url()).searchParams.get("dataset_type") === "train";
      }, { timeout: 180_000 });
      await trainZone.getByRole("button", { name: "Score TRAIN", exact: true }).click();
      const trainScore = await trainResponsePromise.then(responseJson);
      expect(trainScore.ok).toBe(true);
      expect(text(trainScore.scoringRunId)).not.toBe("");
      await expect(trainZone).toContainText(/rows scored/i, { timeout: 180_000 });
      await expectLabeledValue(trainZone, "Rows", text(trainScore.rows));
      await expectLabeledValue(
        trainZone,
        "Mean Score",
        fixed(trainScore.score_summary?.mean, "TRAIN mean score"),
      );

      const testZone = page.getByTestId("test-scoring-zone");
      const testResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/score/upload", "POST")) return false;
        return new URL(response.url()).searchParams.get("dataset_type") === "test";
      }, { timeout: 180_000 });
      await testZone.locator('input[type="file"]').setInputFiles(testCsv);
      const testScore = await testResponsePromise.then(responseJson);
      expect(testScore.ok).toBe(true);
      expect(text(testScore.scoringRunId)).not.toBe("");
      await expect(testZone).toContainText(/rows scored/i, { timeout: 180_000 });
      await expectLabeledValue(testZone, "Rows", text(testScore.rows));
      await expectLabeledValue(
        testZone,
        "Mean Score",
        fixed(testScore.score_summary?.mean, "TEST mean score"),
      );
      const testPerformance = testZone
        .getByRole("heading", { name: "Performance Metrics" })
        .locator("xpath=..");
      await expectLabeledValue(
        testPerformance,
        "AUC",
        fixed(testScore.metrics?.auc, "TEST AUC"),
      );
      await expectLabeledValue(
        testPerformance,
        "PR_AUC",
        fixed(testScore.metrics?.pr_auc, "TEST PR-AUC"),
      );

      const ootZone = page.getByTestId("oot-scoring-zone");
      const ootResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/score/upload", "POST")) return false;
        return new URL(response.url()).searchParams.get("dataset_type") === "oot";
      }, { timeout: 180_000 });
      await ootZone.locator('input[type="file"]').setInputFiles(ootCsv);
      const ootScore = await ootResponsePromise.then(responseJson);
      expect(ootScore.ok).toBe(true);
      expect(text(ootScore.scoringRunId)).not.toBe("");
      await expect(ootZone).toContainText(/rows scored/i, { timeout: 180_000 });
      await expectLabeledValue(ootZone, "Rows", text(ootScore.rows));
      await expectLabeledValue(
        ootZone,
        "Mean Score",
        fixed(ootScore.score_summary?.mean, "OOT mean score"),
      );
      const ootPerformance = ootZone
        .getByRole("heading", { name: "Performance Metrics" })
        .locator("xpath=..");
      await expectLabeledValue(
        ootPerformance,
        "AUC",
        fixed(ootScore.metrics?.auc, "OOT AUC"),
      );
      await expectLabeledValue(
        ootPerformance,
        "PR_AUC",
        fixed(ootScore.metrics?.pr_auc, "OOT PR-AUC"),
      );

      const firstTestLift = record(testScore.lift?.[0], "first TEST lift row");
      await expectExactTableRow(
        testZone.getByRole("heading", { name: "Lift by Decile" }).locator("xpath=..").locator("table"),
        text(firstTestLift.decile),
        [
          text(firstTestLift.decile),
          finite(firstTestLift.n, "TEST lift rows").toLocaleString(),
          finite(firstTestLift.positives, "TEST lift positives").toLocaleString(),
          finite(firstTestLift.event_rate, "TEST lift event rate").toFixed(4),
          finite(firstTestLift.lift, "TEST lift").toFixed(2),
          finite(firstTestLift.capture_rate, "TEST lift capture").toFixed(4),
          finite(firstTestLift.mean_score, "TEST lift mean score").toFixed(5),
        ],
      );

      const crossDatasetPerformance = page.getByTestId("cross-dataset-performance");
      await expect(crossDatasetPerformance).toContainText(
        "3/3 populations available",
        { timeout: 180_000 },
      );
      const performanceTable = crossDatasetPerformance.locator("table").first();
      for (const [label, metricKey] of [
        ["ROC-AUC", "auc"],
        ["PR-AUC", "pr_auc"],
        ["KS", "ks"],
      ] as const) {
        const trainValue = trainScore.metrics?.[metricKey];
        const testValue = testScore.metrics?.[metricKey];
        const ootValue = ootScore.metrics?.[metricKey];
        await expectExactTableRow(performanceTable, label, [
          label,
          displayedMetric(trainValue),
          displayedMetric(testValue),
          displayedMetric(ootValue),
          displayedDelta(trainValue, testValue),
          displayedDelta(trainValue, ootValue),
        ]);
      }

      const scoreDistribution = page.getByTestId("score-distribution-comparison");
      await expect(scoreDistribution).toBeVisible();
      const scoreDistributionChart = scoreDistribution.getByRole("img", {
        name: "Score distribution comparison across TRAIN TEST and OOT",
      });
      await expect(scoreDistributionChart.locator("polyline")).toHaveCount(3);
      for (const polyline of await scoreDistributionChart.locator("polyline").all()) {
        expect(svgPointCount(await polyline.getAttribute("points"))).toBe(18);
      }

      const combinedVsi = page.getByTestId("combined-variable-stability-index");
      await expect(combinedVsi).toBeVisible();
      const testVsi = new Map<string, Record<string, any>>(
        (testScore.vsi as Array<Record<string, any>>).map((row) => [text(row.feature), row]),
      );
      const ootVsi = new Map<string, Record<string, any>>(
        (ootScore.vsi as Array<Record<string, any>>).map((row) => [text(row.feature), row]),
      );
      const topVsi = [...new Set([...testVsi.keys(), ...ootVsi.keys()])]
        .map((feature) => ({ feature, test: testVsi.get(feature), oot: ootVsi.get(feature) }))
        .sort(
          (left, right) =>
            Math.max(right.test?.value ?? -1, right.oot?.value ?? -1) -
            Math.max(left.test?.value ?? -1, left.oot?.value ?? -1),
        )[0];
      expect(topVsi).toBeTruthy();
      const topVsiStatus =
        topVsi.test?.status === "fail" || topVsi.oot?.status === "fail"
          ? "fail"
          : topVsi.test?.status === "warning" || topVsi.oot?.status === "warning"
            ? "warning"
            : "pass";
      await expectExactTableRow(combinedVsi.locator("table"), topVsi.feature, [
        "1",
        topVsi.feature,
        topVsi.test ? fixed(topVsi.test.value, "top TEST VSI") : "-",
        topVsi.oot ? fixed(topVsi.oot.value, "top OOT VSI") : "-",
        topVsiStatus,
      ]);
      await expect(page.getByTestId("stability-command-center")).toBeVisible();
      await expect(page.getByTestId("scored-output-registration")).toBeVisible();
      await shot(page, testInfo, "step10-train-test-oot-scoring-complete");
      coverage.push({
        step: "Step10 Scoring",
        control: "TRAIN, External Validation, and OOT scoring",
        result: "passed",
        evidence: "All three controls returned durable scoring_run_ids; exact metric/delta, lift, 18-bin distribution, and highest-VSI values rendered from those responses.",
      });

      const durableRunsPromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/scoring-runs")) return false;
        const query = new URL(response.url()).searchParams;
        return (
          query.get("projectId") === checkpoint.project_id &&
          query.get("datasetId") === checkpoint.dataset_id &&
          query.get("datasetVersionId") === checkpoint.dataset_version_id &&
          query.get("modelVersionId") === modelVersionId &&
          query.get("target") === candidateLineage!.target &&
          query.get("status") === "completed"
        );
      }, { timeout: 180_000 });
      await page.reload();
      await expectExactStep(page, checkpoint.project_id, "step10");
      const durableRunsPayload = await durableRunsPromise.then(responseJson);
      const durableRuns = (durableRunsPayload.scoringRuns ?? []) as Array<Record<string, any>>;
      expect(durableRuns).toHaveLength(3);
      expect(durableRuns.map((run) => text(run.partition)).sort()).toEqual(["oot", "test", "train"]);
      for (const run of durableRuns) {
        expect(text(run.projectId)).toBe(checkpoint.project_id);
        expect(text(run.datasetId)).toBe(checkpoint.dataset_id);
        expect(text(run.datasetVersionId)).toBe(checkpoint.dataset_version_id);
        expect(text(run.modelVersionId)).toBe(modelVersionId);
        expect(text(run.target)).toBe(candidateLineage.target);
        expect(text(run.status)).toBe("completed");
        expect(text(run.checksum)).not.toBe("");
        expect(run.archivedAt).toBeNull();
      }
      const historyPanel = page.getByTestId("scoring-history-panel");
      await expect(historyPanel).toBeVisible({ timeout: 180_000 });
      await expect(historyPanel.getByTestId("scoring-history-row")).toHaveCount(3);
      for (const run of durableRuns) {
        const historyRow = historyPanel
          .getByLabel(`Select ${run.scoringRunId} for comparison`)
          .locator("xpath=ancestor::li[1]");
        await expect(historyRow).toHaveCount(1);
        await expect(historyRow).toContainText(text(run.partition));
        await expect(historyRow).toContainText("completed");
        await expect(historyRow).toContainText(
          `${text(run.modelId) || "model"} -- ${finite(run.rowCount, "durable row count").toLocaleString()} rows`,
        );
      }

      const includeArchivedResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/scoring-runs")) return false;
        const query = new URL(response.url()).searchParams;
        return query.get("projectId") === checkpoint.project_id && query.get("includeArchived") === "true";
      }, { timeout: 90_000 });
      await historyPanel.getByLabel("Show archived").check();
      const includeArchivedPayload = await includeArchivedResponsePromise.then(responseJson);
      expect(
        (includeArchivedPayload.scoringRuns as Array<Record<string, any>>)
          .map((run) => text(run.scoringRunId))
          .sort(),
      ).toEqual(durableRuns.map((run) => text(run.scoringRunId)).sort());
      await historyPanel.getByLabel("Show archived").uncheck();

      const compareRuns = [
        durableRuns.find((run) => run.partition === "train"),
        durableRuns.find((run) => run.partition === "test"),
      ];
      expect(compareRuns.every(Boolean)).toBe(true);
      const compareIds = compareRuns.map((run) => text(run?.scoringRunId));
      for (const scoringRunId of compareIds) {
        await historyPanel.getByLabel(`Select ${scoringRunId} for comparison`).check();
      }
      await historyPanel
        .getByRole("button", { name: "Compare (2) Selected Runs", exact: true })
        .click();
      const comparePanel = historyPanel.getByTestId("va-compare-panel");
      await expect(comparePanel).toBeVisible();
      await expect(comparePanel.getByTestId("scoring-run-compare-checkbox")).toHaveCount(3, {
        timeout: 90_000,
      });
      for (const scoringRunId of compareIds) {
        await comparePanel.getByLabel(`Select ${scoringRunId} for comparison`).check();
      }
      const compareResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/scoring-runs/compare")) return false;
        const ids = new URL(response.url()).searchParams.get("ids")?.split(",") ?? [];
        return compareIds.every((id) => ids.includes(id));
      }, { timeout: 90_000 });
      await comparePanel.getByTestId("va-run-compare").click();
      const comparePayload = await compareResponsePromise.then(responseJson);
      const comparedRows = comparePayload.runs as Array<Record<string, any>>;
      expect(comparedRows.map((run) => text(run.scoringRunId)).sort()).toEqual(
        compareIds.slice().sort(),
      );
      const compareTable = comparePanel.getByTestId("va-compare-table");
      await expect(compareTable).toBeVisible();
      for (const run of comparedRows) {
        const row = compareTable
          .getByRole("cell", { name: text(run.scoringRunId), exact: true })
          .locator("xpath=..");
        await expect(row).toHaveCount(1);
        await expect(row).toContainText(text(run.partition));
        await expect(row).toContainText(text(run.modelId) || "-");
        await expect(row).toContainText(
          typeof run.rowCount === "number" ? run.rowCount.toLocaleString() : "-",
        );
        const firstMetrics = Object.entries(record(run.metrics, "compared metrics"))
          .filter(([, value]) => typeof value === "number")
          .slice(0, 3)
          .map(([key, value]) => `${key}=${(value as number).toFixed(3)}`)
          .join(", ");
        await expect(row).toContainText(firstMetrics || "-");
      }
      await expect(page.locator('[data-step-next-button="true"]')).toBeEnabled({ timeout: 180_000 });
      coverage.push({
        step: "Step10 Scoring",
        control: "hard-reload durable history and comparison",
        result: "passed",
        evidence: "The exact model/dataset/version query restored three checksummed runs; archived visibility remained read-only and two exact runs rendered in the comparison table.",
      });
      coverage.push({
        step: "Step10 Scoring",
        control: "Archive scoring run",
        result: "intentionally_absent",
        evidence: "Archive is a destructive durable-state mutation and would invalidate the exact non-archived three-run continuation contract proven by this test.",
      });
      await exerciseVisibleTabs(page, "Step10 Scoring", coverage);
      await strictContinue(page, checkpoint.project_id, "step11");

      // Step 11: verify both documentation links resolve to the real Studio,
      // return to the exact project step, and complete through its custom save.
      const documentationPage = page
        .getByRole("heading", {
          name: "Step 11: Documentation Review",
          exact: true,
        })
        .locator("xpath=ancestor::div[contains(@class,'w-full')][1]");
      await expect(documentationPage).toBeVisible();
      await expectLabeledValue(documentationPage, "Project", projectName);
      await expectLabeledValue(documentationPage, "Target", candidateLineage.target);
      const documentedChampionName = text(
        finalMetadata.model_name
          ?? finalMetadata.modelName
          ?? finalMetadata.name
          ?? candidate?.name
          ?? candidate?.model_name
          ?? returnedModelId,
      );
      expect(documentedChampionName).not.toBe("");
      await expectLabeledValue(documentationPage, "Champion", documentedChampionName);
      const documentationIdentity = page.getByTestId("mdd-promoted-model-identity");
      await expect(documentationIdentity).toBeVisible({ timeout: 180_000 });
      await expect(documentationIdentity).toContainText(documentedChampionName);
      await expect(documentationIdentity).toContainText(modelVersionId);
      await expect(documentationIdentity).toContainText(checkpoint.candidate_id);
      await expect(documentationIdentity).toContainText(checkpoint.training_run_id);
      await expect(documentationIdentity).toContainText(checkpoint.dataset_version_id);
      await expect(documentationIdentity).toContainText(candidateLineage.feature_manifest_version);
      await expect(documentationIdentity).toContainText(candidateLineage.validation_design_id);
      await expect(documentationIdentity).toContainText(/verified/i);
      await expect(documentationIdentity).toContainText(
        "Browser experiment flags cannot select or replace the documented champion.",
      );
      const requiredSectionsCard = page
        .getByText("Required sections", { exact: true })
        .locator("xpath=..");
      const requiredSectionsValue = Number(
        text(await requiredSectionsCard.locator("div").nth(1).innerText()),
      );
      expect(requiredSectionsValue).toBeGreaterThan(0);

      const readinessSection = page
        .getByRole("heading", { name: "Documentation readiness", exact: true })
        .locator("xpath=ancestor::div[contains(@class,'rounded-xl')][1]");
      const checklistLabels = [
        "Project context available",
        "Target or response selected",
        "Champion model selected",
        "Evidence available for document sections",
      ];
      for (const label of checklistLabels) {
        const checklistRow = readinessSection.getByText(label, { exact: true }).locator("xpath=..");
        await expect(checklistRow).toHaveCount(1);
        await expect(checklistRow.locator("svg")).toHaveCount(1);
        await expect(checklistRow.locator("svg")).toHaveAttribute(
          "class",
          /text-(?:emerald-600|slate-400)/,
        );
      }
      await expect(
        readinessSection.getByText("Project context available", { exact: true }).locator("xpath=../svg"),
      ).toHaveClass(/text-emerald-600/);
      await expect(
        readinessSection.getByText("Target or response selected", { exact: true }).locator("xpath=../svg"),
      ).toHaveClass(/text-emerald-600/);
      for (const linkName of ["Open Model Documentation Studio", "Open Studio Workspace"]) {
        const link = page.getByRole("link", { name: linkName, exact: true });
        await expect(link).toBeVisible();
        await link.click();
        await expect(page).toHaveURL(/\/model-document-studio(?:[?#]|$)/);
        await expect(page.getByRole("heading", { name: "Model Documentation Studio" })).toBeVisible({
          timeout: 90_000,
        });
        await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
        await page.goBack();
        await expectExactStep(page, checkpoint.project_id, "step11");
      }
      const outline = page
        .getByRole("heading", { name: "Current document outline preview" })
        .locator("xpath=ancestor::section[1]");
      await expect(outline).toBeVisible();
      await expect(outline.locator("div.mt-4 > div")).toHaveCount(
        Math.min(12, requiredSectionsValue),
      );
      await shot(page, testInfo, "step11-documentation-readiness-and-links");
      await exerciseVisibleTabs(page, "Step11 Documentation", coverage);
      const documentationContinue = page.getByRole("button", {
        name: "Mark Complete & Continue to Implementation",
        exact: true,
      });
      await expect(documentationContinue).toBeEnabled({ timeout: 180_000 });
      await documentationContinue.click();
      await expectExactStep(page, checkpoint.project_id, "step12");
      coverage.push({
        step: "Step11 Documentation",
        control: "Studio links and completion",
        result: "passed",
        evidence: "Project/target/section counts, the exact backend model_version_id/candidate/training-run/feature-manifest/validation-design identity, all four checklist states, the bounded outline, both Studio links, and fail-closed custom completion rendered and navigated to Step12.",
      });

      // Step 12: edit every handoff control, navigate, return, and assert the
      // values survived the page boundary before proceeding again.
      const implementationValues = {
        owner: "Disposable isolated implementation owner",
        targetDate: "2030-06-30",
        environment: "batch scoring",
        notes: "Disposable isolated handoff plan with approval gates, rollback controls, package verification, and monitoring ownership.",
      };
      await expect(page.getByLabel("Promoted model ID")).toHaveValue(returnedModelId);
      await expect(page.getByLabel("Promoted model ID")).not.toBeEditable();
      await expect(page.getByLabel("Promoted model version ID")).toHaveValue(modelVersionId);
      await expect(page.getByLabel("Promoted model version ID")).not.toBeEditable();
      const implementationIdentity = page.getByTestId("implementation-promoted-model-identity");
      await expect(implementationIdentity).toContainText(checkpoint.project_id);
      await expect(implementationIdentity).toContainText(checkpoint.dataset_version_id);
      await expect(implementationIdentity).toContainText(checkpoint.candidate_id);
      await expect(implementationIdentity).toContainText(/verified/i);
      await page.getByLabel("Implementation owner").fill(implementationValues.owner);
      await page.getByLabel("Target implementation date").fill(implementationValues.targetDate);
      await page.getByLabel("Implementation environment").selectOption(implementationValues.environment);
      const implementationNotes = page.getByPlaceholder(
        "Dependencies, approval gates, model package location, decision engine changes, rollback plan, controls, or handoff notes.",
        { exact: true },
      );
      await implementationNotes.fill(implementationValues.notes);
      await shot(page, testInfo, "step12-all-implementation-controls-complete");
      await exerciseVisibleTabs(page, "Step12 Implementation", coverage);
      await strictContinue(page, checkpoint.project_id, "step13");
      const persistedImplementation = await readScopedProjectContext(
        page,
        checkpoint.project_id,
      );
      expect(persistedImplementation).toMatchObject({
        implementationOwner: implementationValues.owner,
        implementationTargetDate: implementationValues.targetDate,
        implementationEnvironment: implementationValues.environment,
        implementationNotes: implementationValues.notes,
        promotedModelId: returnedModelId,
        promotedModelVersionId: modelVersionId,
        promotedCandidateId: checkpoint.candidate_id,
        promotedTrainingRunId: checkpoint.training_run_id,
        promotedDatasetId: checkpoint.dataset_id,
        promotedDatasetVersionId: checkpoint.dataset_version_id,
        promotedTarget: candidateLineage.target,
      });
      expect(text(persistedImplementation?.updatedAt)).not.toBe("");
      await page.goBack();
      await expectExactStep(page, checkpoint.project_id, "step12");
      await page.reload();
      await expectExactStep(page, checkpoint.project_id, "step12");
      await expect(page.getByLabel("Promoted model ID")).toHaveValue(returnedModelId);
      await expect(page.getByLabel("Promoted model version ID")).toHaveValue(modelVersionId);
      await expect(page.getByLabel("Implementation owner")).toHaveValue(implementationValues.owner);
      await expect(page.getByLabel("Target implementation date")).toHaveValue(implementationValues.targetDate);
      await expect(page.getByLabel("Implementation environment")).toHaveValue(implementationValues.environment);
      await expect(implementationNotes).toHaveValue(implementationValues.notes);
      await strictContinue(page, checkpoint.project_id, "step13");
      coverage.push({
        step: "Step12 Implementation",
        control: "all editable controls and persistence",
        result: "passed",
        evidence: "The exact implementation model identity and every handoff field were written to project context, then survived navigation and a hard Step12 reload on the same project route.",
      });

      // Step 13: exercise cadence, conditional cadence, every metric checkbox,
      // recommendation reset, notes, final completion, and durable 14/14 status.
      await expect(page.getByRole("heading", { name: "Step 13: Model Monitoring" })).toBeVisible();
      const productionSection = page
        .getByRole("heading", { name: "Production Models Under Monitoring" })
        .locator("xpath=ancestor::section[1]");
      await expect(productionSection.locator("article")).toHaveCount(4);
      const monitoringIdentity = page.getByTestId("monitoring-promoted-model-identity");
      await expect(monitoringIdentity).toContainText(returnedModelId);
      await expect(monitoringIdentity).toContainText(modelVersionId);
      await expect(monitoringIdentity).toContainText(checkpoint.dataset_version_id);
      await expect(monitoringIdentity).toContainText(/verified/i);
      const currentProductionCard = productionSection
        .locator("article")
        .filter({ hasText: returnedModelId });
      await expect(currentProductionCard).toHaveCount(1);
      await expect(currentProductionCard).toContainText(modelVersionId);
      await expect(currentProductionCard).toContainText(`Owner: ${implementationValues.owner}`);
      await expect(currentProductionCard).toContainText(
        `Deployed: ${implementationValues.targetDate}`,
      );
      await expect(currentProductionCard).toContainText("Cadence: monthly");
      for (const metric of ["AUC", "KS", "PSI", "VSI"]) {
        await expect(currentProductionCard).toContainText(`${metric}: Pending`);
      }

      const attritionCard = productionSection.locator("article").filter({ hasText: "15211 Portfolio Attrition Model" });
      await expect(attritionCard).toContainText("AUC: 0.742");
      await expect(attritionCard).toContainText("VSI: 2 red variables");
      const creditCard = productionSection.locator("article").filter({ hasText: "14877 Credit Line Increase Model" });
      await expect(creditCard).toContainText("AUC: 0.691");
      await expect(creditCard).toContainText("PSI: 0.29");
      const lossCard = productionSection.locator("article").filter({ hasText: "16004 Loss Forecast Model" });
      await expect(lossCard).toContainText("RMSE: 0.431");
      await expect(lossCard).toContainText("VSI: All pass");

      const escalationSection = page
        .getByRole("heading", { name: "Escalation Queue" })
        .locator("xpath=ancestor::section[1]");
      await expect(escalationSection.getByRole("columnheader")).toHaveText([
        "Severity",
        "Model",
        "Reason",
        "Owner",
        "Action",
      ]);
      const attritionRedEscalation = escalationSection
        .locator("tbody tr")
        .filter({ hasText: "15211 Portfolio Attrition Model" })
        .filter({ hasText: "VSI is in the red zone (2 red variables)." });
      await expect(attritionRedEscalation).toHaveCount(1);
      await expect(attritionRedEscalation).toContainText("Retention Analytics");
      await expect(attritionRedEscalation).toContainText(
        "Open monitoring exception and assign remediation owner.",
      );
      const complianceEscalation = escalationSection
        .locator("tbody tr")
        .filter({ hasText: "14877 Credit Line Increase Model" })
        .filter({ hasText: "Fair lending review overdue" });
      await expect(complianceEscalation).toHaveCount(1);
      await expect(complianceEscalation).toContainText(
        "Escalate to model governance and compliance owner.",
      );
      const monitoringAgeMonths = (deployedAt: string, now = new Date()) => {
        const start = new Date(deployedAt);
        return (now.getFullYear() - start.getFullYear()) * 12 + (now.getMonth() - start.getMonth());
      };
      const expectedAgeEscalations = ["2024-09-15", "2023-10-01", "2025-04-20"].filter(
        (deployedAt) => monitoringAgeMonths(deployedAt) >= 18,
      ).length;
      await expect(
        escalationSection.locator("tbody tr").filter({ hasText: /Model age is \d+ months; exceeds 18-month review threshold\./ }),
      ).toHaveCount(expectedAgeEscalations);

      const cadence = page.getByLabel("Monitoring cadence");
      await cadence.selectOption("custom");
      await expect(page.getByLabel("Custom cadence")).toBeVisible();
      await page.getByLabel("Custom cadence").fill("Every two weeks on the first business day");
      const metricsRegion = page
        .getByText("Performance and stability metrics", { exact: true })
        .locator("xpath=..")
        .locator('input[type="checkbox"]');
      const metricCount = await metricsRegion.count();
      expect(metricCount).toBeGreaterThan(0);
      for (let index = 0; index < metricCount; index += 1) {
        const checkbox = metricsRegion.nth(index);
        const wasChecked = await checkbox.isChecked();
        await checkbox.click();
        expect(await checkbox.isChecked()).toBe(!wasChecked);
      }
      await page.getByRole("button", { name: "Use Recommended Metrics", exact: true }).click();
      const checkedAfterRecommendation: string[] = [];
      for (let index = 0; index < metricCount; index += 1) {
        if (await metricsRegion.nth(index).isChecked()) {
          checkedAfterRecommendation.push(
            text(await metricsRegion.nth(index).locator("xpath=..").innerText()),
          );
        }
      }
      expect(checkedAfterRecommendation.sort()).toEqual(["AUC", "KS", "PSI", "VSI"]);
      const monitoringNotes =
        "Review discrimination, calibration, data drift, stability, overrides, alerts, and documented escalation actions on the governed cadence.";
      const monitoringNotesInput = page.getByPlaceholder(
        "Thresholds, owners, escalation paths, monitoring evidence, validation cadence, or remediation standards.",
        { exact: true },
      );
      await monitoringNotesInput.fill(monitoringNotes);
      await expect(monitoringNotesInput).toHaveValue(monitoringNotes);
      await shot(page, testInfo, "step13-monitoring-plan-complete");
      await exerciseVisibleTabs(page, "Step13 Monitoring", coverage);
      const completeWorkflow = page.locator('[data-step-next-button="true"]');
      await expect(completeWorkflow).toHaveText("Mark Complete & Return to Atlas Home");
      await expect(completeWorkflow).toBeEnabled();
      await completeWorkflow.click();
      await expect(page).toHaveURL(/\/dashboard(?:[?#]|$)/, { timeout: 180_000 });
      await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
      const persistedMonitoring = await readScopedProjectContext(
        page,
        checkpoint.project_id,
      );
      expect(persistedMonitoring).toMatchObject({
        promotedModelId: returnedModelId,
        promotedModelVersionId: modelVersionId,
        promotedCandidateId: checkpoint.candidate_id,
        promotedTrainingRunId: checkpoint.training_run_id,
        promotedDatasetId: checkpoint.dataset_id,
        promotedDatasetVersionId: checkpoint.dataset_version_id,
        promotedTarget: candidateLineage.target,
        monitoringCadence: "custom",
        monitoringCadenceCustom: "Every two weeks on the first business day",
        monitoringMetrics: ["AUC", "KS", "PSI", "VSI"],
        monitoringNotes,
      });

      await page.goto(`/projects/${checkpoint.project_id}/step13`);
      await expectExactStep(page, checkpoint.project_id, "step13");
      await page.reload();
      await expectExactStep(page, checkpoint.project_id, "step13");
      const restoredMonitoringIdentity = page.getByTestId("monitoring-promoted-model-identity");
      await expect(restoredMonitoringIdentity).toContainText(returnedModelId);
      await expect(restoredMonitoringIdentity).toContainText(modelVersionId);
      await expect(restoredMonitoringIdentity).toContainText(checkpoint.dataset_version_id);
      await expect(restoredMonitoringIdentity).toContainText(/verified/i);
      await expect(page.getByLabel("Monitoring cadence")).toHaveValue("custom");
      await expect(page.getByLabel("Custom cadence")).toHaveValue(
        "Every two weeks on the first business day",
      );
      const restoredMetrics = page
        .getByText("Performance and stability metrics", { exact: true })
        .locator("xpath=..")
        .locator('input[type="checkbox"]');
      const restoredCheckedMetrics: string[] = [];
      for (let index = 0; index < await restoredMetrics.count(); index += 1) {
        if (await restoredMetrics.nth(index).isChecked()) {
          restoredCheckedMetrics.push(
            text(await restoredMetrics.nth(index).locator("xpath=..").innerText()),
          );
        }
      }
      expect(restoredCheckedMetrics.sort()).toEqual(["AUC", "KS", "PSI", "VSI"]);
      await expect(page.getByPlaceholder(
        "Thresholds, owners, escalation paths, monitoring evidence, validation cadence, or remediation standards.",
        { exact: true },
      )).toHaveValue(monitoringNotes);
      const restoredProductionSection = page
        .getByRole("heading", { name: "Production Models Under Monitoring" })
        .locator("xpath=ancestor::section[1]");
      const restoredProductionCard = restoredProductionSection
        .locator("article")
        .filter({ hasText: returnedModelId });
      await expect(restoredProductionCard).toHaveCount(1);
      await expect(restoredProductionCard).toContainText(modelVersionId);
      await expect(restoredProductionCard).toContainText(`Owner: ${implementationValues.owner}`);
      await shot(page, testInfo, "step13-hard-reload-persistence");
      coverage.push({
        step: "Step13 Monitoring",
        control: "hard-reload monitoring-plan persistence",
        result: "passed",
        evidence: "After durable completion, the exact promoted model identity, custom cadence, recommended metrics, notes, and production card survived reopening Step13 and a hard reload.",
      });
      await page.goto("/projects/open");
      await page
        .getByPlaceholder("Search project, target, dataset, or type")
        .fill(projectName);
      await page.getByRole("button", { name: "Card View", exact: true }).click();
      const completedCard = page.locator("article").filter({
        has: page.getByRole("heading", { name: projectName, exact: true }),
      });
      await expect(completedCard).toHaveCount(1);
      await expect(completedCard).toContainText("14 of 14 steps complete", { timeout: 180_000 });
      await shot(page, testInfo, "step13-durable-workflow-completion");
      coverage.push({
        step: "Step13 Monitoring",
        control: "cadence, metrics, notes, and workflow completion",
        result: "passed",
        evidence: "Exact production-card metrics and escalation reasons rendered; recommended metrics and custom cadence persisted with the implementation identity; the project reopened as 14 of 14 complete.",
      });

      expect(log.pageErrors).toEqual([]);
      expect(log.failedRequests).toEqual([]);
      expect(log.failedResponses).toEqual([]);
      expect(log.consoleErrors).toEqual([]);
    } finally {
      await writeCoverage();
      await dump();
    }
  });
});
