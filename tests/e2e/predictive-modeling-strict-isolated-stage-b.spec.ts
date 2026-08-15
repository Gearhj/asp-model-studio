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
const STOP_AFTER_INTERPRETATION =
  process.env.ATLAS_E2E_STOP_AFTER_INTERPRETATION?.trim() === "1";

const SELECTION_REVIEW_FIELDS = [
  "candidate_id",
  "training_job_id",
  "training_run_id",
  "project_id",
  "dataset_id",
  "dataset_version_id",
  "target",
  "feature_manifest_version",
  "validation_design_id",
  "validation_design_version",
  "split_id",
] as const;

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

function isExpectedNavigationAbort(
  entry: string,
  backendOrigin: string,
  frontendOrigin: string,
  projectId: string,
): boolean {
  const match = /^(GET|PUT) (https?:\/\/\S+) -- net::ERR_ABORTED$/.exec(entry);
  if (!match) return false;
  const [, method, rawUrl] = match;
  const url = new URL(rawUrl);
  if (url.origin === backendOrigin) {
    if (method === "PUT" && url.pathname === `/api/projects/${projectId}`) return true;
    if (method !== "GET") return false;
    return [
      "/api/auth/me",
      "/api/notifications/unread-count",
      "/api/preparation/documentation",
      "/api/train/last",
    ].includes(url.pathname);
  }
  return url.origin === frontendOrigin
    && method === "GET"
    && /^\/assets\/(?:modelMonitoring|rotate-ccw)-[^/]+\.js$/.test(url.pathname);
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
  // The strict diagnostic ledger treats browser-cancelled requests as failures.
  // Let route hydration, lazy chunks, notifications, and compatibility mirrors
  // finish before the test deliberately reloads or leaves the page.
  await page.waitForLoadState("networkidle", { timeout: 180_000 });
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
  await page.waitForLoadState("networkidle", { timeout });
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

function hasExactScoringQuery(
  responseUrl: string,
  checkpoint: StageACheckpoint,
  modelVersionId: string,
  target: string,
  datasetType: "train" | "test" | "oot",
): boolean {
  const query = new URL(responseUrl).searchParams;
  return (
    query.get("project_id") === checkpoint.project_id &&
    query.get("dataset_id") === checkpoint.dataset_id &&
    query.get("dataset_version_id") === checkpoint.dataset_version_id &&
    query.get("model_version_id") === modelVersionId &&
    query.get("target") === target &&
    query.get("dataset_type") === datasetType &&
    !query.has("model")
  );
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

function candidateField(
  candidate: Record<string, any>,
  name: (typeof SELECTION_REVIEW_FIELDS)[number],
): string {
  const contract = record(candidate.candidate_contract ?? {}, "candidate contract");
  if (name === "target") {
    return text(
      candidate.target ??
        candidate.target_name ??
        contract.target ??
        contract.target_name ??
        contract.target_definition?.target_name,
    );
  }
  if (name === "feature_manifest_version") {
    return text(
      candidate.feature_manifest_version ??
        contract.feature_manifest_version ??
        contract.feature_manifest_hash,
    );
  }
  return text(candidate[name] ?? contract[name]);
}

function candidateProblemType(candidate: Record<string, any>): string {
  return text(
    candidate.task ??
      candidate.problem_type ??
      candidate.candidate_contract?.problem_type,
  );
}

function evaluationModelFamily(candidate: Record<string, any>): string {
  const value = `${text(candidate.key)} ${text(candidate.name)}`.toLowerCase();
  if (/decision.?tree/.test(value)) return "Decision Tree";
  if (/random.?forest|extra.?trees/.test(value)) return "Tree Ensemble";
  if (/xgboost|lightgbm|catboost|histogram.?gradient|boosting/.test(value)) return "Gradient Boosting";
  if (/knn|nearest/.test(value)) return "K-Nearest Neighbors";
  if (/svm|support.?vector/.test(value)) return "Support Vector Machine";
  if (/naive.?bayes|gaussian.?nb/.test(value)) return "Gaussian Naive Bayes";
  if (/neural|mlp/.test(value)) return "Neural Network";
  if (/logistic|sgd/.test(value)) return "Linear Classifier";
  return "Supervised Estimator";
}

function modelSpecificTestId(candidate: Record<string, any>): string {
  return `model-specific-${evaluationModelFamily(candidate)
    .toLowerCase()
    .replace(/[^a-z]+/g, "-")}`;
}

function waitForSelectionReviewResponse(
  page: Page,
  backendOrigin: string,
  pathname: string,
  candidateId: string,
  timeout = 180_000,
): Promise<Response> {
  return page.waitForResponse((response) => {
    if (!isBackendResponse(response, backendOrigin, pathname)) return false;
    const query = new URL(response.url()).searchParams;
    return (
      query.get("candidate_id") === candidateId &&
      query.get("evidence_scope") === "selection_review"
    );
  }, { timeout });
}

function assertSelectionReviewBinding(
  response: Response,
  payload: Record<string, any>,
  candidate: Record<string, any>,
) {
  const query = new URL(response.url()).searchParams;
  expect(query.get("evidence_scope")).toBe("selection_review");
  for (const name of SELECTION_REVIEW_FIELDS) {
    const expected = candidateField(candidate, name);
    expect(expected, `${name} from ranked candidate`).not.toBe("");
    expect(query.get(name), `${name} request binding`).toBe(expected);
    expect(text(payload[name]), `${name} response binding`).toBe(expected);
  }
  const problemType = candidateProblemType(candidate);
  expect(problemType, "candidate problem type").not.toBe("");
  expect(query.get("problem_type")).toBe(problemType);
  expect(payload.ok).toBe(true);
  expect(text(payload.evidence_scope)).toBe("selection_review");
  expect(text(payload.analysis_binding)).toBe("exact_selection_review");
  expect(text(payload.evaluation_package_id)).toBe("");
  expect(text(payload.candidate_decision_id)).toBe("");
}

function assertEvaluationPackageBinding(
  payload: Record<string, any>,
  checkpoint: StageACheckpoint,
) {
  expect(payload.ok).toBe(true);
  expect(text(payload.project_id)).toBe(checkpoint.project_id);
  expect(text(payload.dataset_id)).toBe(checkpoint.dataset_id);
  expect(text(payload.dataset_version_id)).toBe(checkpoint.dataset_version_id);
  expect(text(payload.training_run_id)).toBe(checkpoint.training_run_id);
  expect(text(payload.candidate_id)).toBe(checkpoint.candidate_id);
  expect(text(payload.evaluation_package_id)).toBe(checkpoint.evaluation_package_id);
  const artifactPackage = payload.interpretation_artifact?.evaluation_package ??
    payload.evaluation_package ?? {};
  expect(text(artifactPackage.candidate_decision_id)).toBe(
    checkpoint.candidate_decision_id,
  );
  expect(text(payload.evidence_scope)).not.toBe("selection_review");
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
  const rawGrid = payload.grid as Array<Record<string, any>>;
  const rawPoints = payload.points as Array<Record<string, any>>;
  const xDomain = payload.x_domain as unknown[];
  const yDomain = payload.y_domain as unknown[];
  const resolution = finite(payload.resolution, "decision-boundary resolution");
  expect(Array.isArray(rawGrid)).toBe(true);
  expect(rawGrid.length).toBe(resolution * resolution);
  expect(Array.isArray(rawPoints)).toBe(true);
  expect(rawPoints.length).toBeGreaterThan(0);
  expect(Array.isArray(xDomain)).toBe(true);
  expect(xDomain).toHaveLength(2);
  expect(Array.isArray(yDomain)).toBe(true);
  expect(yDomain).toHaveLength(2);

  const width = 880;
  const height = 430;
  const pad = 54;
  const plotWidth = width - pad - 24;
  const plotHeight = height - pad - 24;
  const xMin = finite(xDomain[0], "decision-boundary x minimum");
  const xMax = finite(xDomain[1], "decision-boundary x maximum");
  const yMin = finite(yDomain[0], "decision-boundary y minimum");
  const yMax = finite(yDomain[1], "decision-boundary y maximum");
  const insideDomain = (row: Record<string, any>) => {
    const xValue = finite(row.x, "decision-boundary x value");
    const yValue = finite(row.y, "decision-boundary y value");
    return (
      xValue >= xMin &&
      xValue <= xMax &&
      yValue >= yMin &&
      yValue <= yMax
    );
  };
  const grid = rawGrid.filter(
    (row) => insideDomain(row) && typeof row.score === "number" && Number.isFinite(row.score),
  );
  const points = rawPoints.filter(
    (row) => insideDomain(row) && typeof row.class === "number" && Number.isFinite(row.class),
  );
  expect(grid.length).toBeGreaterThan(0);
  expect(points.length).toBeGreaterThan(0);

  const svg = section.locator("svg");
  await expect(svg).toBeVisible();
  await expect(svg).toHaveAttribute("data-x-feature", text(payload.x_feature));
  await expect(svg).toHaveAttribute("data-y-feature", text(payload.y_feature));
  await expect(svg).toHaveAttribute("data-visible-grid-cells", String(grid.length));
  await expect(svg).toHaveAttribute("data-visible-points", String(points.length));
  await expect(svg).toContainText(text(payload.x_feature));
  await expect(svg).toContainText(text(payload.y_feature));

  const gridLayer = svg.getByTestId("decision-boundary-grid");
  const pointLayer = svg.getByTestId("decision-boundary-points");
  await expect(gridLayer).toHaveAttribute("clip-path", /^url\(#decision-boundary-/);
  await expect(pointLayer).toHaveAttribute("clip-path", /^url\(#decision-boundary-/);
  await expect(svg.locator("clipPath path")).toHaveAttribute(
    "d",
    `M ${pad} 18 H ${width - 24} V ${height - pad} H ${pad} Z`,
  );
  await expect(gridLayer.locator("rect")).toHaveCount(grid.length);
  await expect(pointLayer.locator("circle")).toHaveCount(points.length);

  const x = (value: unknown) =>
    pad + ((finite(value, "decision-boundary x value") - xMin) / (xMax - xMin || 1)) * plotWidth;
  const y = (value: unknown) =>
    18 + ((yMax - finite(value, "decision-boundary y value")) / (yMax - yMin || 1)) * plotHeight;

  const firstGrid = record(grid[0], "first decision-boundary grid cell");
  const firstRect = await gridLayer.locator("rect").first().evaluate((node) => ({
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
  const firstCircle = await pointLayer.locator("circle").first().evaluate((node) => ({
    cx: Number(node.getAttribute("cx")),
    cy: Number(node.getAttribute("cy")),
    fill: node.getAttribute("fill"),
  }));
  expect(firstCircle.cx).toBeCloseTo(x(firstPoint.x), 8);
  expect(firstCircle.cy).toBeCloseTo(y(firstPoint.y), 8);
  expect(firstCircle.fill).toBe(finite(firstPoint.class, "first decision-boundary point class") ? "#facc15" : "#4c1d95");

  const circleCoordinates = await pointLayer.locator("circle").evaluateAll((nodes) =>
    nodes.map((node) => ({
      cx: Number(node.getAttribute("cx")),
      cy: Number(node.getAttribute("cy")),
    })),
  );
  for (const coordinate of circleCoordinates) {
    expect(coordinate.cx).toBeGreaterThanOrEqual(pad);
    expect(coordinate.cx).toBeLessThanOrEqual(width - 24);
    expect(coordinate.cy).toBeGreaterThanOrEqual(18);
    expect(coordinate.cy).toBeLessThanOrEqual(height - pad);
  }

  const gridCenters = await gridLayer.locator("rect").evaluateAll((nodes) =>
    nodes.map((node) => {
      const xValue = Number(node.getAttribute("x"));
      const yValue = Number(node.getAttribute("y"));
      const widthValue = Number(node.getAttribute("width"));
      const heightValue = Number(node.getAttribute("height"));
      return {
        x: xValue + widthValue / 2,
        y: yValue + heightValue / 2,
      };
    }),
  );
  for (const center of gridCenters) {
    expect(center.x).toBeGreaterThanOrEqual(pad);
    expect(center.x).toBeLessThanOrEqual(width - 24);
    expect(center.y).toBeGreaterThanOrEqual(18);
    expect(center.y).toBeLessThanOrEqual(height - pad);
  }
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
  keyCellIndex = 0,
) {
  const rows = table.locator("tbody tr");
  const matchingRows: Locator[] = [];
  for (let index = 0; index < await rows.count(); index += 1) {
    const row = rows.nth(index);
    const keyCell = row.getByRole("cell").nth(keyCellIndex);
    if ((await keyCell.innerText()).trim() === key) matchingRows.push(row);
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
      await page.waitForLoadState("networkidle", { timeout: 180_000 });
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

      await projectCard.getByRole("button", { name: "Open", exact: true }).click();
      await expectExactStep(page, checkpoint.project_id, "step00");

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
        (response) => {
          if (!isBackendResponse(response, isolated.backendOrigin, "/api/eval/command_center")) {
            return false;
          }
          const query = new URL(response.url()).searchParams;
          return (
            query.get("candidate_id") === checkpoint.candidate_id &&
            query.get("candidate_decision_id") === checkpoint.candidate_decision_id &&
            !query.has("evidence_scope")
          );
        },
        { timeout: 180_000 },
      );
      await page.goto(`/projects/${checkpoint.project_id}/step08`);
      await expectExactStep(page, checkpoint.project_id, "step08");
      const [lastTrainingPayload, decisionPayload, commandPayload] = await Promise.all([
        lastTrainingResponsePromise.then(responseJson),
        decisionResponsePromise.then(responseJson),
        commandCenterResponsePromise.then(responseJson),
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
      coverage.push({
        step: "Step08 Evaluation",
        control: "exact durable identity hydration",
        result: "passed",
        evidence: "Training, candidate-decision, and Evaluation-package responses matched every Stage A identifier.",
      });


      // Step 08: the visible ranked table is the primary model switcher. Every
      // exact supervised candidate must open real selection-review evidence.
      await expect(page.getByTestId("evaluation-command-center")).toBeVisible();
      const rankedSupervisedCandidates = rankedCandidates(lastTrainingPayload).filter(
        (row) =>
          text(row.candidate_id) &&
          text(row.training_run_id) === checkpoint.training_run_id &&
          row.champion_eligible !== false &&
          text(row.kind).toLowerCase() !== "anomaly" &&
          text(row.task).toLowerCase() !== "anomaly",
      );
      expect(rankedSupervisedCandidates.length).toBeGreaterThanOrEqual(2);
      const exactEvaluationCandidate = record(candidate, "Evaluation candidate");
      const championCandidate = record(
        rankedSupervisedCandidates[0],
        "top-ranked supervised candidate",
      );
      expect(text(championCandidate.candidate_id)).toBe(checkpoint.candidate_id);
      const evaluationFamily = evaluationModelFamily(exactEvaluationCandidate);
      const challengerCandidate = record(
        rankedSupervisedCandidates.find(
          (row) =>
            text(row.candidate_id) !== checkpoint.candidate_id &&
            evaluationModelFamily(row) !== evaluationFamily,
        ) ?? rankedSupervisedCandidates.find(
          (row) => text(row.candidate_id) !== checkpoint.candidate_id,
        ),
        "selection-review challenger",
      );
      const challengerCandidateId = text(challengerCandidate.candidate_id);
      const challengerName = cleanModelName(challengerCandidate.name);
      expect(challengerCandidateId).not.toBe("");
      expect(challengerName).not.toBe("");

      const resultsTableSection = page.getByTestId("primary-model-results-table");
      await expect(resultsTableSection).toBeVisible();
      const resultsTable = resultsTableSection.locator("table");
      const resultHeaders = (await resultsTable.getByRole("columnheader").allInnerTexts())
        .map((value) => value.trim().toLowerCase());
      expect(resultHeaders).toEqual([
        "rank",
        "model",
        "family",
        "selection metric",
        "source",
        "fold evidence",
        "runtime",
        "decision",
      ]);
      expect(resultHeaders).not.toContain("actions");
      await expect(resultsTable.locator("tbody tr")).toHaveCount(
        rankedSupervisedCandidates.length,
      );
      const championRow = resultsTable.locator("tbody tr").first();
      await expect(championRow.getByRole("cell").nth(0)).toHaveText("1");
      await expect(championRow.getByRole("cell").nth(1)).toContainText(
        cleanModelName(championCandidate.name),
      );
      await expect(championRow.getByRole("cell").last()).toHaveText("Champion");

      const explorer = page.getByTestId("interactive-model-explorer");
      await expect(explorer).toBeVisible();
      const evaluationModelSelector = explorer.getByTestId("evaluation-model-selector");

      const reviewEvaluationRow = async (candidateRow: Record<string, any>) => {
        const candidateId = text(candidateRow.candidate_id);
        const modelName = cleanModelName(candidateRow.name);
        const row = resultsTable.locator("tbody tr").filter({
          has: page.getByText(modelName, { exact: true }),
        });
        await expect(row).toHaveCount(1);
        const commandResponsePromise = waitForSelectionReviewResponse(
          page,
          isolated.backendOrigin,
          "/api/eval/command_center",
          candidateId,
        );
        const curvesResponsePromise = waitForSelectionReviewResponse(
          page,
          isolated.backendOrigin,
          "/api/eval/curves",
          candidateId,
        );
        await row.click();
        const [commandResponse, curvesResponse] = await Promise.all([
          commandResponsePromise,
          curvesResponsePromise,
        ]);
        const [reviewCommand, reviewCurves] = await Promise.all([
          responseJson(commandResponse),
          responseJson(curvesResponse),
        ]);
        assertSelectionReviewBinding(commandResponse, reviewCommand, candidateRow);
        assertSelectionReviewBinding(curvesResponse, reviewCurves, candidateRow);
        expect(text(reviewCommand.analysis_type)).toBe("command_center");
        expect(text(reviewCurves.analysis_type)).toBe("curves");

        const candidateMetric = normalizedSelectionMetric(
          record(candidateRow.selection_metric, `${modelName} selection metric`),
        );
        await expect(row).toHaveAttribute("aria-selected", "true");
        await expect(evaluationModelSelector).toHaveValue(candidateId);
        const reviewEvidence = explorer.getByTestId("model-review-evidence");
        await expect(reviewEvidence).toContainText(`${modelName} - rank`);
        await expect(reviewEvidence).toContainText(
          fixed(candidateMetric.value, `${modelName} visible selection metric`),
        );
        await expect(reviewEvidence.locator("table tbody tr").first()).toBeVisible();

        const roc = record(reviewCurves.roc, `${modelName} ROC curve`);
        const pr = record(reviewCurves.pr, `${modelName} precision-recall curve`);
        expect(Array.isArray(roc.fpr)).toBe(true);
        expect(roc.fpr.length).toBeGreaterThan(2);
        expect(roc.tpr).toHaveLength(roc.fpr.length);
        expect(Array.isArray(pr.recall)).toBe(true);
        expect(pr.recall.length).toBeGreaterThan(2);
        expect(pr.precision).toHaveLength(pr.recall.length);
        const rocChart = explorer.getByRole("img", {
          name: "True positive rate by False positive rate",
        });
        const prChart = explorer.getByRole("img", { name: "Precision by Recall" });
        await expect(rocChart).toBeVisible();
        await expect(prChart).toBeVisible();
        expect(svgPointCount(await rocChart.locator("polyline").getAttribute("points"))).toBe(
          roc.fpr.length,
        );
        expect(svgPointCount(await prChart.locator("polyline").getAttribute("points"))).toBe(
          pr.recall.length,
        );

        const thresholdMetrics = record(
          reviewCommand.threshold,
          `${modelName} threshold metrics`,
        );
        const thresholdLabel = finite(
          thresholdMetrics.threshold,
          `${modelName} threshold`,
        ).toFixed(3);
        const thresholdDashboard = explorer.getByTestId("threshold-live-metrics");
        await expectLabeledValue(
          thresholdDashboard,
          `Precision @ ${thresholdLabel}`,
          percent(thresholdMetrics.precision, `${modelName} threshold precision`),
        );
        await expectLabeledValue(
          thresholdDashboard,
          `Recall @ ${thresholdLabel}`,
          percent(thresholdMetrics.recall, `${modelName} threshold recall`),
        );
        await expectLabeledValue(
          thresholdDashboard,
          `F1 @ ${thresholdLabel}`,
          fixed(thresholdMetrics.f1, `${modelName} threshold F1`),
        );
        const confusionCard = thresholdDashboard
          .getByRole("heading", { name: `Confusion Matrix @ ${thresholdLabel}` })
          .locator("xpath=../..");
        for (const value of (thresholdMetrics.confusion as number[][]).flat()) {
          await expect(confusionCard).toContainText(value.toLocaleString());
        }

        const lift = record(reviewCommand.lift, `${modelName} lift evidence`);
        expect(Array.isArray(lift.deciles)).toBe(true);
        expect(lift.deciles.length).toBeGreaterThan(1);
        const liftSection = thresholdDashboard.getByTestId("lift-gain-capture");
        await expect(liftSection.locator("table tbody tr")).toHaveCount(lift.deciles.length);
        const firstLiftRow = record(lift.deciles[0], `${modelName} first lift decile`);
        await expectExactTableRow(
          liftSection.locator("table"),
          text(firstLiftRow.decile),
          [
            text(firstLiftRow.decile),
            finite(firstLiftRow.n, `${modelName} lift rows`).toLocaleString(),
            finite(firstLiftRow.positives, `${modelName} lift events`).toLocaleString(),
            percent(firstLiftRow.event_rate, `${modelName} lift event rate`),
            finite(firstLiftRow.lift, `${modelName} lift value`).toFixed(2),
            percent(firstLiftRow.capture_rate, `${modelName} lift capture`),
            finite(firstLiftRow.mean_score, `${modelName} lift mean score`).toFixed(4),
          ],
        );

        const calibration = record(
          reviewCommand.calibration,
          `${modelName} calibration evidence`,
        );
        expect(Array.isArray(calibration.rows)).toBe(true);
        expect(calibration.rows.length).toBeGreaterThan(1);
        const calibrationSection = page.getByTestId("stability-calibration");
        await expect(calibrationSection).toContainText(`Calibration evidence for ${modelName}`);
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
          fixed(calibration.brier_score, `${modelName} Brier score`),
        );

        const specificTestId = modelSpecificTestId(candidateRow);
        const modelSpecific = explorer.getByTestId(specificTestId);
        await expect(modelSpecific).toBeVisible({ timeout: 180_000 });
        await expect(modelSpecific).toContainText(
          `${evaluationModelFamily(candidateRow)} diagnostics`,
        );
        return {
          candidateId,
          modelName,
          specificTestId,
          reviewText: await reviewEvidence.innerText(),
        };
      };

      const challengerEvaluationReview = await reviewEvaluationRow(challengerCandidate);
      const governedEvaluationReview = await reviewEvaluationRow(exactEvaluationCandidate);
      expect(challengerEvaluationReview.candidateId).not.toBe(
        governedEvaluationReview.candidateId,
      );
      expect(challengerEvaluationReview.modelName).not.toBe(
        governedEvaluationReview.modelName,
      );
      expect(challengerEvaluationReview.reviewText).not.toBe(
        governedEvaluationReview.reviewText,
      );
      expect(challengerEvaluationReview.specificTestId).not.toBe(
        governedEvaluationReview.specificTestId,
      );

      const comparisonDistribution = page.getByTestId("model-score-distribution");
      await expect(comparisonDistribution).toBeVisible();
      const comparisonChart = comparisonDistribution.getByRole("img", {
        name: /ATLAS Model Comparison - five-fold .* distribution/,
      });
      await expect(comparisonChart).toBeVisible();
      await expect(comparisonChart).toHaveAttribute("viewBox", /^0 0 1600 /);
      const comparisonBounds = await comparisonChart.boundingBox();
      expect(comparisonBounds, "model comparison chart bounds").not.toBeNull();
      expect(comparisonBounds!.width).toBeGreaterThan(1_200);
      expect(comparisonBounds!.height).toBeGreaterThan(400);
      for (const family of [
        "Tree-based",
        "Transparent / linear",
        "Anomaly diagnostics",
        "Neural networks",
        "Distance / margin",
        "Other",
      ]) {
        await expect(comparisonChart.getByText(family, { exact: true })).toBeVisible();
      }
      const familyBoxColors = await comparisonChart
        .locator('rect[height="34"]')
        .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("fill") ?? ""));
      expect(new Set(familyBoxColors).size).toBeGreaterThanOrEqual(2);
      await exerciseVisibleTabs(page, "Step08 Evaluation", coverage);
      await shot(page, testInfo, "step08-row-driven-model-review-and-family-comparison");
      coverage.push({
        step: "Step08 Evaluation",
        control: "row-driven model results and family comparison",
        result: "passed",
        evidence: "The primary table had no Actions column, its top row was Champion, two exact candidates rebound selection-review charts, metrics, confusion matrices, lift/calibration tables, and model-specific diagnostics, and the materially large comparison chart used distinct family colors.",
      });

      // Continue opens the exact Evaluation candidate. Other candidates remain
      // available through Interpretation's explicit model selector.
      const importanceResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/importance")) return false;
        const query = new URL(response.url()).searchParams;
        return query.get("candidate_id") === checkpoint.candidate_id &&
          query.get("evaluation_package_id") === checkpoint.evaluation_package_id;
      }, { timeout: 180_000 });
      const shapResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/shap")) return false;
        const query = new URL(response.url()).searchParams;
        return query.get("candidate_id") === checkpoint.candidate_id &&
          query.get("evaluation_package_id") === checkpoint.evaluation_package_id;
      }, { timeout: 180_000 });
      await strictContinue(page, checkpoint.project_id, "step09");
      assertInterpretationUrl(page, checkpoint, [checkpoint.candidate_id]);
      const [importancePayload, shapPayload] = await Promise.all([
        importanceResponsePromise.then(responseJson),
        shapResponsePromise.then(responseJson),
      ]);
      assertEvaluationPackageBinding(importancePayload, checkpoint);
      assertEvaluationPackageBinding(shapPayload, checkpoint);
      const importanceRows = importancePayload.rows as Array<Record<string, any>>;
      const shapRows = shapPayload.rows as Array<Record<string, any>>;
      expect(Array.isArray(importanceRows)).toBe(true);
      expect(importanceRows.length).toBeGreaterThan(0);
      expect(Array.isArray(shapRows)).toBe(true);
      expect(shapRows.length).toBeGreaterThan(0);
      coverage.push({
        step: "Step08 Evaluation",
        control: "page-level Continue to Interpretation",
        result: "passed",
        evidence: "Continue durably completed Evaluation and preserved the exact candidate, training run, candidate decision, and Evaluation package query.",
      });


      // Step 09: use the visible model selector to review both the Evaluation
      // candidate and one exact challenger. Challenger analyses are strictly
      // selection-review scoped and cannot inherit promotion authority.
      await expect(page.getByRole("heading", {
        name: "Step 9: Model Interpretation and Final Model",
      })).toBeVisible({ timeout: 180_000 });
      const interpretationSelector = page.getByTestId("interpretation-model-selector");
      await expect(interpretationSelector).toBeVisible();
      await expect(interpretationSelector).toBeEnabled();
      const interpretationOptions = await optionValues(interpretationSelector);
      expect(interpretationOptions).toContain(checkpoint.candidate_id);
      expect(interpretationOptions).toContain(challengerCandidateId);
      await expect(interpretationSelector).toHaveValue(checkpoint.candidate_id);
      const selectedModelSummary = page.getByTestId("selected-model-summary");
      const evaluationName = cleanModelName(exactEvaluationCandidate.name);
      await expect(selectedModelSummary).toContainText(evaluationName);
      await expect(selectedModelSummary).toContainText(checkpoint.candidate_id);
      await expect(selectedModelSummary).toContainText("Evaluation candidate");
      await expect(selectedModelSummary).toContainText("Model evidence loaded", {
        timeout: 180_000,
      });

      const importanceSection = page
        .getByRole("heading", { name: "Feature Importance" })
        .locator("xpath=ancestor::section[1]");
      const shapSection = page
        .getByRole("heading", { name: "SHAP Summary" })
        .locator("xpath=ancestor::section[1]");
      const pdpSection = page
        .getByRole("heading", { name: "PDP / Sensitivity" })
        .locator("xpath=ancestor::section[1]");
      const hyperparameterSection = page
        .getByRole("heading", { name: "Final Hyperparameter Settings" })
        .locator("xpath=ancestor::section[1]");

      const expectInterpretationRows = async (
        importanceEvidence: Record<string, any>,
        shapEvidence: Record<string, any>,
      ) => {
        const exactImportanceRows = importanceEvidence.rows as Array<Record<string, any>>;
        const exactShapRows = shapEvidence.rows as Array<Record<string, any>>;
        expect(Array.isArray(exactImportanceRows)).toBe(true);
        expect(exactImportanceRows.length).toBeGreaterThan(0);
        expect(Array.isArray(exactShapRows)).toBe(true);
        expect(exactShapRows.length).toBeGreaterThan(0);
        for (const row of exactImportanceRows.slice(0, 3)) {
          const rendered = importanceSection
            .getByText(text(row.feature), { exact: true })
            .locator("xpath=..");
          await expect(rendered).toHaveCount(1);
          await expect(rendered).toContainText(
            fixed(row.importance, `${row.feature} importance`),
          );
        }
        for (const row of exactShapRows.slice(0, 3)) {
          const rendered = shapSection
            .getByText(text(row.feature), { exact: true })
            .locator("xpath=..");
          await expect(rendered).toHaveCount(1);
          await expect(rendered).toContainText(
            fixed(row.importance, `${row.feature} SHAP value`),
          );
        }
      };

      await expectInterpretationRows(importancePayload, shapPayload);

      const challengerImportancePromise = waitForSelectionReviewResponse(
        page,
        isolated.backendOrigin,
        "/api/interpretation/importance",
        challengerCandidateId,
      );
      const challengerShapPromise = waitForSelectionReviewResponse(
        page,
        isolated.backendOrigin,
        "/api/interpretation/shap",
        challengerCandidateId,
      );
      const challengerHyperparametersPromise = waitForSelectionReviewResponse(
        page,
        isolated.backendOrigin,
        "/api/interpretation/hyperparameters",
        challengerCandidateId,
      );
      const challengerPdpPromise = waitForSelectionReviewResponse(
        page,
        isolated.backendOrigin,
        "/api/interpretation/pdp",
        challengerCandidateId,
      );
      const challengerSensitivityPromise = waitForSelectionReviewResponse(
        page,
        isolated.backendOrigin,
        "/api/interpretation/sensitivity",
        challengerCandidateId,
      );
      const challengerBoundaryPromise = waitForSelectionReviewResponse(
        page,
        isolated.backendOrigin,
        "/api/interpretation/decision_boundary",
        challengerCandidateId,
      );
      await interpretationSelector.selectOption(challengerCandidateId);
      const [
        challengerImportanceResponse,
        challengerShapResponse,
        challengerHyperparametersResponse,
        challengerPdpResponse,
        challengerSensitivityResponse,
        challengerBoundaryResponse,
      ] = await Promise.all([
        challengerImportancePromise,
        challengerShapPromise,
        challengerHyperparametersPromise,
        challengerPdpPromise,
        challengerSensitivityPromise,
        challengerBoundaryPromise,
      ]);
      const [
        challengerImportancePayload,
        challengerShapPayload,
        challengerHyperparametersPayload,
        challengerPdpPayload,
        challengerSensitivityPayload,
        challengerBoundaryPayload,
      ] = await Promise.all([
        responseJson(challengerImportanceResponse),
        responseJson(challengerShapResponse),
        responseJson(challengerHyperparametersResponse),
        responseJson(challengerPdpResponse),
        responseJson(challengerSensitivityResponse),
        responseJson(challengerBoundaryResponse),
      ]);
      for (const [response, payload] of [
        [challengerImportanceResponse, challengerImportancePayload],
        [challengerShapResponse, challengerShapPayload],
        [challengerHyperparametersResponse, challengerHyperparametersPayload],
        [challengerPdpResponse, challengerPdpPayload],
        [challengerSensitivityResponse, challengerSensitivityPayload],
        [challengerBoundaryResponse, challengerBoundaryPayload],
      ] as Array<[Response, Record<string, any>]>) {
        assertSelectionReviewBinding(response, payload, challengerCandidate);
      }
      await expect(interpretationSelector).toHaveValue(challengerCandidateId);
      await expect(selectedModelSummary).toContainText(challengerName);
      await expect(selectedModelSummary).toContainText(challengerCandidateId);
      await expect(selectedModelSummary).toContainText("Selection review");
      await expect(selectedModelSummary).toContainText("Model evidence loaded", {
        timeout: 180_000,
      });
      await expectInterpretationRows(
        challengerImportancePayload,
        challengerShapPayload,
      );

      const challengerHyperparameterRows = challengerHyperparametersPayload.rows as
        | Array<Record<string, any>>
        | undefined;
      if (challengerHyperparameterRows?.length) {
        await expect(hyperparameterSection).toContainText(
          text(challengerHyperparameterRows[0].parameter),
        );
        await expect(hyperparameterSection).toContainText(
          text(challengerHyperparameterRows[0].value),
        );
      } else {
        await expect(hyperparameterSection).toContainText(
          "No grid-search settings were recorded for this model",
        );
      }

      const challengerPdpRows = challengerPdpPayload.rows as Array<Record<string, any>>;
      const challengerSensitivityRows = challengerSensitivityPayload.rows as Array<Record<string, any>>;
      expect(challengerPdpRows.length).toBeGreaterThan(1);
      expect(challengerSensitivityRows.length).toBeGreaterThan(0);
      const challengerPdpChart = pdpSection.locator("svg");
      await expect(challengerPdpChart.locator("circle")).toHaveCount(
        challengerPdpRows.length,
      );
      await expect(challengerPdpChart.locator("polyline")).toHaveAttribute(
        "points",
        expectedPdpPoints(challengerPdpRows),
      );
      const firstChallengerSensitivity = record(
        challengerSensitivityRows[0],
        "challenger sensitivity row",
      );
      await expectExactTableRow(
        pdpSection.locator("table"),
        text(firstChallengerSensitivity.scenario),
        [
          text(firstChallengerSensitivity.scenario),
          fixed(firstChallengerSensitivity.prediction, "challenger sensitivity prediction"),
          fixed(firstChallengerSensitivity.delta, "challenger sensitivity delta"),
        ],
      );
      const decisionBoundarySection = page.getByTestId("decision-boundary-section");
      await expect(decisionBoundarySection).toBeVisible({ timeout: 180_000 });
      await expectExactBoundaryRendering(
        decisionBoundarySection,
        challengerBoundaryPayload,
      );

      const challengerSaveFinal = page.getByRole("button", {
        name: "Save as Final Model",
        exact: true,
      });
      await expect(challengerSaveFinal).toBeDisabled();
      await expect(challengerSaveFinal).toHaveAttribute(
        "title",
        /Evaluation candidate/i,
      );
      await expect(page.getByTestId("exact-candidate-promotion")).toContainText(
        /Selection review only/i,
      );
      await shot(page, testInfo, "step09-challenger-selection-review");

      const waitForEvaluationArtifact = (pathname: string) =>
        page.waitForResponse((response) => {
          if (!isBackendResponse(response, isolated.backendOrigin, pathname)) return false;
          const query = new URL(response.url()).searchParams;
          return (
            query.get("candidate_id") === checkpoint.candidate_id &&
            query.get("candidate_decision_id") === checkpoint.candidate_decision_id &&
            query.get("evaluation_package_id") === checkpoint.evaluation_package_id &&
            !query.has("evidence_scope")
          );
        }, { timeout: 180_000 });
      const evaluationImportancePromise = waitForEvaluationArtifact(
        "/api/interpretation/importance",
      );
      const evaluationShapPromise = waitForEvaluationArtifact(
        "/api/interpretation/shap",
      );
      const evaluationPdpPromise = waitForEvaluationArtifact(
        "/api/interpretation/pdp",
      );
      const evaluationSensitivityPromise = waitForEvaluationArtifact(
        "/api/interpretation/sensitivity",
      );
      const evaluationBoundaryPromise = waitForEvaluationArtifact(
        "/api/interpretation/decision_boundary",
      );
      await interpretationSelector.selectOption(checkpoint.candidate_id);
      const [
        evaluationImportanceResponse,
        evaluationShapResponse,
        evaluationPdpResponse,
        evaluationSensitivityResponse,
        evaluationBoundaryResponse,
      ] = await Promise.all([
        evaluationImportancePromise,
        evaluationShapPromise,
        evaluationPdpPromise,
        evaluationSensitivityPromise,
        evaluationBoundaryPromise,
      ]);
      const [
        reboundImportancePayload,
        reboundShapPayload,
        evaluationPdpPayload,
        evaluationSensitivityPayload,
        evaluationBoundaryPayload,
      ] = await Promise.all([
        responseJson(evaluationImportanceResponse),
        responseJson(evaluationShapResponse),
        responseJson(evaluationPdpResponse),
        responseJson(evaluationSensitivityResponse),
        responseJson(evaluationBoundaryResponse),
      ]);
      for (const payload of [
        reboundImportancePayload,
        reboundShapPayload,
        evaluationPdpPayload,
        evaluationSensitivityPayload,
        evaluationBoundaryPayload,
      ]) {
        assertEvaluationPackageBinding(payload, checkpoint);
      }
      await expect(interpretationSelector).toHaveValue(checkpoint.candidate_id);
      await expect(selectedModelSummary).toContainText(evaluationName);
      await expect(selectedModelSummary).toContainText(checkpoint.candidate_id);
      await expect(selectedModelSummary).toContainText("Evaluation candidate");
      await expectInterpretationRows(reboundImportancePayload, reboundShapPayload);

      const evaluationPdpRows = evaluationPdpPayload.rows as Array<Record<string, any>>;
      const evaluationSensitivityRows = evaluationSensitivityPayload.rows as Array<Record<string, any>>;
      expect(evaluationPdpRows.length).toBeGreaterThan(1);
      expect(evaluationSensitivityRows.length).toBeGreaterThan(0);
      await expect(pdpSection.locator("svg polyline")).toHaveAttribute(
        "points",
        expectedPdpPoints(evaluationPdpRows),
      );
      const firstEvaluationSensitivity = record(
        evaluationSensitivityRows[0],
        "Evaluation-candidate sensitivity row",
      );
      await expectExactTableRow(
        pdpSection.locator("table"),
        text(firstEvaluationSensitivity.scenario),
        [
          text(firstEvaluationSensitivity.scenario),
          fixed(firstEvaluationSensitivity.prediction, "Evaluation sensitivity prediction"),
          fixed(firstEvaluationSensitivity.delta, "Evaluation sensitivity delta"),
        ],
      );
      await expectExactBoundaryRendering(
        decisionBoundarySection,
        evaluationBoundaryPayload,
      );
      await expect(challengerSaveFinal).toBeEnabled({ timeout: 180_000 });
      coverage.push({
        step: "Step09 Interpretation",
        control: "exact candidate model selector and promotion gate",
        result: "passed",
        evidence: "The challenger returned only exact selection-review artifacts, visibly rebound importance, SHAP, hyperparameter, PDP/sensitivity, and clipped decision-boundary content, and could not be promoted; selecting the Evaluation candidate restored its reporting package and promotion authority.",
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
          isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/sensitivity_summary") &&
          new URL(response.url()).searchParams.has("model_version_id"),
        { timeout: 180_000 },
      );
      const vifResponsePromise = page.waitForResponse(
        (response) =>
          isBackendResponse(response, isolated.backendOrigin, "/api/interpretation/vif") &&
          new URL(response.url()).searchParams.has("model_version_id"),
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
        .getByRole("heading", { name: "Selected Model Sensitivity Analysis", exact: true })
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
        .getByRole("heading", { name: "Selected Model Variance Inflation Factor", exact: true })
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
      coverage.push({
        step: "Step10 Scoring",
        control: "Interpretation Continue handoff",
        result: "passed",
        evidence: "The saved exact model version reached the project-scoped Scoring route and hydrated the durable scoring contract.",
      });
      if (STOP_AFTER_INTERPRETATION) {
        await page.waitForLoadState("networkidle", { timeout: 180_000 });
        await shot(page, testInfo, "step10-stop-after-interpretation-handoff");
        return;
      }

      const scoringFixture = writeStrictPredictiveFixture(testInfo, 240);
      const testCsv = testInfo.outputPath("strict-predictive-external-validation.csv");
      const ootCsv = testInfo.outputPath("strict-predictive-oot.csv");
      fs.copyFileSync(scoringFixture.filePath, testCsv);
      fs.copyFileSync(scoringFixture.filePath, ootCsv);

      const trainZone = page.getByTestId("train-scoring-zone");
      const trainResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/score/development-split", "POST")) return false;
        return hasExactScoringQuery(
          response.url(),
          checkpoint,
          modelVersionId,
          candidateLineage.target,
          "train",
        );
      }, { timeout: 180_000 });
      await trainZone.getByRole("button", { name: "Score TRAIN", exact: true }).click();
      const trainScore = await trainResponsePromise.then(responseJson);
      expect(trainScore.ok).toBe(true);
      expect(text(trainScore.scoringRunId)).not.toBe("");
      expect(text(trainScore.model?.modelVersionId ?? trainScore.model?.model_version_id)).toBe(
        modelVersionId,
      );
      await expect(trainZone).toContainText(/rows scored/i, { timeout: 180_000 });
      const trainSummaryMetrics = trainZone.getByTestId("scoring-summary-metrics");
      await expectLabeledValue(trainSummaryMetrics, "Rows", text(trainScore.rows));
      await expectLabeledValue(
        trainSummaryMetrics,
        "Mean Score",
        fixed(trainScore.score_summary?.mean, "TRAIN mean score"),
      );

      const testZone = page.getByTestId("test-scoring-zone");
      const testResponsePromise = page.waitForResponse((response) => {
        if (!isBackendResponse(response, isolated.backendOrigin, "/api/score/upload", "POST")) return false;
        return hasExactScoringQuery(
          response.url(),
          checkpoint,
          modelVersionId,
          candidateLineage.target,
          "test",
        );
      }, { timeout: 180_000 });
      await testZone.locator('input[type="file"]').setInputFiles(testCsv);
      const testScore = await testResponsePromise.then(responseJson);
      expect(testScore.ok).toBe(true);
      expect(text(testScore.scoringRunId)).not.toBe("");
      expect(text(testScore.model?.modelVersionId ?? testScore.model?.model_version_id)).toBe(
        modelVersionId,
      );
      expect(text(testScore.scoring_diagnostics?.feature_manifest_status)).toBe("reapplied");
      expect(testScore.scoring_diagnostics?.missing_features).toEqual([]);
      expect(testScore.scoring_diagnostics?.holdout_accessed_for_feature_materialization).toBe(false);
      await expect(testZone).toContainText(/rows scored/i, { timeout: 180_000 });
      const testSummaryMetrics = testZone.getByTestId("scoring-summary-metrics");
      await expectLabeledValue(testSummaryMetrics, "Rows", text(testScore.rows));
      await expectLabeledValue(
        testSummaryMetrics,
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
        return hasExactScoringQuery(
          response.url(),
          checkpoint,
          modelVersionId,
          candidateLineage.target,
          "oot",
        );
      }, { timeout: 180_000 });
      await ootZone.locator('input[type="file"]').setInputFiles(ootCsv);
      const ootScore = await ootResponsePromise.then(responseJson);
      expect(ootScore.ok).toBe(true);
      expect(text(ootScore.scoringRunId)).not.toBe("");
      expect(text(ootScore.model?.modelVersionId ?? ootScore.model?.model_version_id)).toBe(
        modelVersionId,
      );
      expect(text(ootScore.scoring_diagnostics?.feature_manifest_status)).toBe("reapplied");
      expect(ootScore.scoring_diagnostics?.missing_features).toEqual([]);
      expect(ootScore.scoring_diagnostics?.holdout_accessed_for_feature_materialization).toBe(false);
      await expect(ootZone).toContainText(/rows scored/i, { timeout: 180_000 });
      const ootSummaryMetrics = ootZone.getByTestId("scoring-summary-metrics");
      await expectLabeledValue(ootSummaryMetrics, "Rows", text(ootScore.rows));
      await expectLabeledValue(
        ootSummaryMetrics,
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
      ], 1);
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
        readinessSection
          .getByText("Project context available", { exact: true })
          .locator("xpath=..")
          .locator("svg"),
      ).toHaveClass(/text-emerald-600/);
      await expect(
        readinessSection
          .getByText("Target or response selected", { exact: true })
          .locator("xpath=..")
          .locator("svg"),
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
        await page.waitForLoadState("networkidle", { timeout: 180_000 });
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
      await page.waitForLoadState("networkidle", { timeout: 180_000 });
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
      await page.waitForLoadState("networkidle", { timeout: 180_000 });
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
      await page.waitForLoadState("networkidle", { timeout: 180_000 });
      await shot(page, testInfo, "step13-durable-workflow-completion");
      coverage.push({
        step: "Step13 Monitoring",
        control: "cadence, metrics, notes, and workflow completion",
        result: "passed",
        evidence: "Exact production-card metrics and escalation reasons rendered; recommended metrics and custom cadence persisted with the implementation identity; the project reopened as 14 of 14 complete.",
      });

      const expectedNavigationAborts = log.failedRequests.filter((entry) =>
        isExpectedNavigationAbort(
          entry,
          isolated.backendOrigin,
          isolated.frontendOrigin,
          checkpoint.project_id,
        ));
      const unexpectedRequestFailures = log.failedRequests.filter(
        (entry) => !expectedNavigationAborts.includes(entry),
      );
      const expectedUnauthenticatedResponses = log.failedResponses.filter(
        (entry) => entry === `401 GET ${isolated.backendOrigin}/api/auth/me`,
      );
      const unexpectedResponseFailures = log.failedResponses.filter(
        (entry) => !expectedUnauthenticatedResponses.includes(entry),
      );
      const expectedUnauthenticatedConsoleErrors = expectedUnauthenticatedResponses.length > 0
        ? log.consoleErrors.filter(
          (entry) => entry === "[error] Failed to load resource: the server responded with a status of 401 (Unauthorized)",
        )
        : [];
      const unexpectedConsoleErrors = log.consoleErrors.filter(
        (entry) => !expectedUnauthenticatedConsoleErrors.includes(entry),
      );
      expect(expectedNavigationAborts.length).toBeLessThanOrEqual(16);
      expect(expectedUnauthenticatedResponses.length).toBeLessThanOrEqual(1);
      expect(expectedUnauthenticatedConsoleErrors.length).toBeLessThanOrEqual(
        expectedUnauthenticatedResponses.length,
      );
      coverage.push({
        step: "Cross-workflow diagnostics",
        control: "failed-request ledger",
        result: "passed",
        evidence: `${expectedNavigationAborts.length} allowlisted browser navigation cancellations and ${expectedUnauthenticatedResponses.length} expected pre-login auth probe were preserved separately; no failed mutation, workflow-state, evidence, model, scoring, or unexpected request/response was accepted.`,
      });
      expect(log.pageErrors).toEqual([]);
      expect(unexpectedRequestFailures).toEqual([]);
      expect(unexpectedResponseFailures).toEqual([]);
      expect(unexpectedConsoleErrors).toEqual([]);
    } finally {
      await writeCoverage();
      await dump();
    }
  });
});
