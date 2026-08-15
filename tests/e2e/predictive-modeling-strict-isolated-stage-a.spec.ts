import fs from "node:fs";
import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import {
  CLASSIFICATION_NARRATIVE,
  fillProjectContextNarrative,
} from "./helpers/projectContext";
import { shot } from "./helpers/screenshots";
import { writeStrictPredictiveFixture } from "./helpers/strictPredictiveFixture";

type DurableIdentity = {
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  training_job_id: string;
  training_run_id: string;
  candidate_id: string;
  candidate_decision_id: string;
  evaluation_package_id: string | null;
  disposable_user_email: string;
};

type TrainingJob = {
  job_id: string;
  training_job_id?: string;
  training_run_id?: string;
  overall_status: string;
  total_count?: number;
  completed_count?: number;
  failed_count?: number;
  partial_ranked_results?: Array<{
    candidate_id?: string;
    training_run_id?: string;
    champion_eligible?: boolean;
    kind?: string;
  }>;
  summary?: {
    ranked?: Array<{
      candidate_id?: string;
      training_run_id?: string;
      champion_eligible?: boolean;
      kind?: string;
    }>;
  };
};

type TrainingSelectionSaveResponse = {
  project_id?: string;
  dataset_id?: string;
  dataset_version_id?: string;
  selection_revision?: number;
  revision?: number;
  selection?: {
    selected_algorithm_ids?: string[];
    selected_models?: string[];
  };
  selected_algorithm_ids?: string[];
  selected_models?: string[];
};

function exactProjectStep(projectId: string, step: string): RegExp {
  const escaped = projectId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`/projects/${escaped}/${step}(?:[?#]|$)`);
}

async function expectExactStep(page: Page, projectId: string, step: string) {
  await expect(page).toHaveURL(exactProjectStep(projectId, step), {
    timeout: 90_000,
  });
  // Project-scoped routes can reach their final URL before the authoritative
  // project-context provider finishes revalidating the route.  Do not touch a
  // transient page tree: it is intentionally replaced by ProjectContextGate
  // while the exact project is resolving.
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-project-context-status",
    "ready",
    { timeout: 90_000 },
  );
  await expect(page.getByTestId("project-context-gate")).toHaveCount(0, {
    timeout: 90_000,
  });
  // A same-project route can expose the prior ready snapshot for one render
  // before its post-render revalidation begins.  Require readiness to remain
  // stable across that transition window, then reassert the exact URL.
  await page.waitForTimeout(750);
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-project-context-status",
    "ready",
    { timeout: 90_000 },
  );
  await expect(page.getByTestId("project-context-gate")).toHaveCount(0, {
    timeout: 90_000,
  });
  await expect(page).toHaveURL(exactProjectStep(projectId, step));
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
}

async function strictContinue(
  page: Page,
  projectId: string,
  nextStep: string,
  timeout = 120_000,
) {
  const action = await expectReadyForNextStep(page, timeout);
  await action.click();
  await expect(page).toHaveURL(exactProjectStep(projectId, nextStep), {
    timeout,
  });
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
}

async function expectReadyForNextStep(page: Page, timeout = 120_000) {
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
  return action;
}

async function changeTrainingPortfolioAndWaitForSave(
  page: Page,
  trigger: () => Promise<unknown>,
  matchesRequest: (payload: Record<string, unknown>) => boolean,
): Promise<TrainingSelectionSaveResponse> {
  const status = page.getByTestId("portfolio-persistence-status");
  await expect(status).toBeVisible();
  const previousRevisionMatch = (await status.innerText()).match(/revision\s+(\d+)/i);
  const previousRevision = previousRevisionMatch
    ? Number(previousRevisionMatch[1])
    : null;
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) => {
        if (
          candidate.request().method() !== "POST" ||
          !candidate.url().includes("/api/model/train/selection")
        ) {
          return false;
        }
        try {
          return matchesRequest(
            candidate.request().postDataJSON() as Record<string, unknown>,
          );
        } catch {
          return false;
        }
      },
      { timeout: 60_000 },
    ),
    trigger(),
  ]);
  expect(response.status()).toBe(200);
  const payload = (await response.json()) as TrainingSelectionSaveResponse;
  const revision = Number(payload.selection_revision ?? payload.revision);
  expect(Number.isInteger(revision)).toBe(true);
  expect(revision).toBeGreaterThan(0);
  if (previousRevision != null) {
    expect(revision).toBeGreaterThan(previousRevision);
  }
  const persistenceBadge = status.locator(":scope > span").first();
  await expect(persistenceBadge).toContainText(/Portfolio saved/i, {
    timeout: 60_000,
  });
  await expect(persistenceBadge).toContainText(new RegExp(`revision\\s+${revision}$`, "i"), {
    timeout: 60_000,
  });
  return payload;
}

async function expectPrimaryTrainingActionEnabled(page: Page) {
  const action = page.getByRole("button", {
    name: /^(Validate Selected Models|Validate & Train Selected Models|Start Governed Training)$/,
  });
  await expect(action).toHaveCount(1);
  await expect(action).toBeEnabled({ timeout: 30_000 });
}

async function browserGetJson<T>(
  page: Page,
  url: string,
): Promise<{ status: number; payload: T | null }> {
  return page.evaluate(async (requestUrl) => {
    const response = await fetch(requestUrl, { credentials: "include" });
    return {
      status: response.status,
      payload: (await response.json().catch(() => null)) as T | null,
    };
  }, url);
}

async function selectFirstNonPlaceholder(select: Locator): Promise<string> {
  const values = await select.locator("option").evaluateAll((options) =>
    options
      .map((option) => (option as HTMLOptionElement).value)
      .filter((value) => value.trim().length > 0),
  );
  expect(values.length).toBeGreaterThan(0);
  await select.selectOption(values[0]);
  await expect(select).toHaveValue(values[0]);
  return values[0];
}

async function addEngineeredFeature(
  page: Page,
  type: "Interaction" | "Numeric Bin" | "Rule Category" | "Polynomial" | "Arithmetic" | "Date Derived",
  name: string,
  configure: () => Promise<void>,
) {
  await page.getByTestId("feature-builder-launcher").getByRole("button", { name: new RegExp(`^${type}`) }).click();
  const builder = page.getByTestId("feature-builder-configuration");
  await expect(builder).toBeVisible();
  await builder.getByLabel("New feature name").fill(name);
  await configure();
  await builder
    .getByLabel("Reviewer rationale")
    .fill(`Strict isolated acceptance rationale for ${name}; deterministic development-only feature construction.`);
  await builder.getByTestId("feature-builder-add").click();
  await expect(page.getByTestId("feature-transformation-plan")).toContainText(name);
  await expect(page.getByText("The feature definition is not valid.")).toHaveCount(0);
}

function writeCheckpoint(testInfo: TestInfo, identity: DurableIdentity) {
  fs.writeFileSync(
    testInfo.outputPath("strict-stage-a-checkpoint.json"),
    `${JSON.stringify(identity, null, 2)}\n`,
    "utf8",
  );
}

test.describe("Strict isolated predictive modeling Stage A", () => {
  test("executes every governed page contract from Project Context through an exact locked candidate", async ({ page }, testInfo) => {
    test.setTimeout(18 * 60_000);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const runId = process.env.ATLAS_E2E_RUN_ID;
    expect(runId, "the isolated runner must provide its deterministic run id").toMatch(
      /^atlas-hrt-[0-9]{8}-[0-9]{6}-[a-f0-9]{10}$/i,
    );
    const backendBaseUrl = process.env.ATLAS_E2E_BACKEND_URL?.replace(/\/$/, "");
    expect(
      backendBaseUrl,
      "the isolated runner must provide the exact isolated backend URL",
    ).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
    const fixture = writeStrictPredictiveFixture(testInfo);
    const user = makeTestUser("strict-stage-a");
    const projectName = `ATLAS Strict Stage A ${runId}`;
    const modelId = `strict-${runId!.slice(-10)}`;

    // Step 00 — disposable authentication and exact project context.
    await registerUser(page, user);
    await createPredictiveModelingProject(page, { name: projectName, modelId });
    const projectMatch = new URL(page.url()).pathname.match(/^\/projects\/([^/]+)\/step00$/);
    expect(projectMatch, "project creation must land on the exact project-scoped Step 00 route").not.toBeNull();
    const projectId = projectMatch![1];
    await expectExactStep(page, projectId, "step00");
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await page.getByRole("button", { name: "Generate Modeling Mission Summary" }).click();
    const missionDraft = page.getByLabel("Editable AI Modeling Mission Summary draft");
    await expect(missionDraft).toBeVisible();
    await expect(missionDraft).not.toHaveValue("");
    await page.getByRole("button", { name: "Accept Summary" }).click();
    await expect(page.getByTestId("accepted-modeling-mission-summary")).toBeVisible();
    await shot(page, testInfo, "step00-project-context-accepted");
    await strictContinue(page, projectId, "step01");

    // Step 01 — upload, target contract, durable registration, special values,
    // predictor authorization, and a sealed Analysis Partition.
    await expectExactStep(page, projectId, "step01");
    const [uploadResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/data/upload_csv"),
        { timeout: 90_000 },
      ),
      page
        .getByTestId("source-command-section")
        .locator('input[type="file"][accept*=".csv"]')
        .setInputFiles(fixture.filePath),
    ]);
    expect(uploadResponse.status()).toBe(200);
    const upload = await uploadResponse.json();
    const datasetId = String(upload?.dataset_id ?? upload?.datasetId ?? "");
    const datasetVersionId = String(
      upload?.dataset_version_id ?? upload?.versionId ?? "",
    );
    expect(upload?.project_id).toBe(projectId);
    expect(datasetId).not.toBe("");
    expect(datasetVersionId).not.toBe("");
    expect(Number(upload?.activation_revision)).toBeGreaterThan(0);
    const targetSelect = page.getByTestId("target-column-select");
    await expect(targetSelect.locator(`option[value="${fixture.target}"]`)).toHaveCount(1, {
      timeout: 90_000,
    });
    await targetSelect.selectOption(fixture.target);
    await expect(targetSelect).toHaveValue(fixture.target);
    await page.getByLabel("Event / Positive Value").fill("1");
    await page.getByLabel("Non-event / Negative Value").fill("0");
    const confirmInitialTarget = page.getByTestId(
      "confirm-initial-target-contract",
    );
    if (await confirmInitialTarget.isVisible()) {
      await confirmInitialTarget.click();
    }
    // The in-progress bootstrap notice is intentionally transient.  Verify the
    // durable authority and the stable page badge instead of racing an
    // intermediate success message that disappears once context rehydrates.
    await expect
      .poll(
        async () => {
          const response = await browserGetJson<Record<string, any>>(
            page,
            `${backendBaseUrl}/api/data/reproducibility-context?project_id=${encodeURIComponent(projectId)}`,
          );
          const context = response.payload;
          return (
            response.status === 200 &&
            context?.state === "partition_pending" &&
            context?.identity?.project_id === projectId &&
            context?.identity?.dataset_id === datasetId &&
            context?.identity?.dataset_version_id === datasetVersionId &&
            context?.target_contract?.target === fixture.target &&
            String(context?.target_contract?.event_value ?? "") === "1" &&
            String(context?.target_contract?.non_event_value ?? "") === "0" &&
            String(context?.target_contract?.target_contract_id ?? "").length > 0 &&
            String(
              context?.predictor_authorization?.predictor_authorization_id ?? "",
            ).length > 0 &&
            Array.isArray(
              context?.predictor_authorization?.selected_predictors,
            ) &&
            context.predictor_authorization.selected_predictors.includes(
              "annual_income",
            )
          );
        },
        { timeout: 90_000 },
      )
      .toBe(true);
    await expect(page.getByTestId("data-acquisition-target-setup")).toContainText(
      `Target contract confirmed: ${fixture.target}`,
    );
    await expect(confirmInitialTarget).toHaveCount(0);
    await expect(page.getByTestId("target-distribution-query-state")).toHaveAttribute(
      "data-query-phase",
      /exact|cached|sampled/,
      { timeout: 60_000 },
    );
    const persistence = page.getByTestId("dataset-persistence-card");
    await expect(persistence).toHaveAttribute("data-persistence-mode", "registered-status");
    await expect(persistence).toContainText("Registered and linked to this project");
    await persistence.locator("summary").click();
    await expect(persistence).toContainText(datasetId);
    await expect(persistence).toContainText(datasetVersionId);

    await expect
      .poll(
        async () => {
          const response = await browserGetJson<Record<string, unknown>>(
            page,
            `${backendBaseUrl}/api/data/active-identity?project_id=${encodeURIComponent(projectId)}`,
          );
          if (response.status !== 200) return null;
          const identity = response.payload;
          return {
            project_id: identity?.project_id,
            dataset_id: identity?.dataset_id,
            dataset_version_id: identity?.dataset_version_id,
          };
        },
        { timeout: 60_000 },
      )
      .toEqual({
        project_id: projectId,
        dataset_id: datasetId,
        dataset_version_id: datasetVersionId,
      });

    const specialWorkspace = page.getByTestId("special-value-decision-workspace");
    await expect(specialWorkspace).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("special-value-review-summary")).toBeVisible({
      timeout: 90_000,
    });
    const specialTable = page.getByTestId("special-value-feature-table");
    for (const column of fixture.specialValueColumns) {
      await expect(specialTable).toContainText(column);
    }
    await expect(page.getByTestId("special-value-analytical-scope")).toHaveAttribute(
      "data-final-holdout-accessed",
      "false",
    );

    const predictorFunnel = page.getByTestId("predictor-authorization-funnel");
    await expect(predictorFunnel).toBeVisible();
    await expect(predictorFunnel).toHaveAttribute(
      "data-predictor-authorization-id",
      /\S+/,
    );
    const updateAuthorization = page.getByTestId("update-predictor-authorization");
    if (await updateAuthorization.isEnabled()) {
      await updateAuthorization.click();
      await expect(updateAuthorization).toBeDisabled({ timeout: 60_000 });
    }

    const ratio = page.getByTestId("analysis-partition-holdout-ratio");
    await expect(ratio).toBeVisible();
    await expect(ratio.locator("option")).toHaveCount(3);
    const exerciseSplitPreview = async (
      holdoutShare: "0.3" | "0.2" | "0.1",
    ) => {
      const expectedHoldoutShare = Number(holdoutShare);
      const responsePromise = page.waitForResponse((response) => {
        if (
          response.request().method() !== "POST" ||
          !response.url().includes("/api/analysis-partitions/preview")
        ) {
          return false;
        }
        try {
          const request = response.request().postDataJSON() as {
            holdout_share?: number;
          };
          return request.holdout_share === expectedHoldoutShare;
        } catch {
          return false;
        }
      }, { timeout: 60_000 });
      await ratio.selectOption(holdoutShare);
      const response = await responsePromise;
      expect(response.status()).toBe(200);
      const payload = await response.json() as {
        ok?: boolean;
        preview?: {
          development_share?: number;
          holdout_share?: number;
          development_rows?: number;
          holdout_rows?: number;
          preview_fingerprint?: string;
          rationale_required?: boolean;
        };
      };
      expect(payload.ok).toBe(true);
      expect(payload.preview?.holdout_share).toBe(expectedHoldoutShare);
      expect(payload.preview?.development_share).toBe(1 - expectedHoldoutShare);
      expect(payload.preview?.development_rows).toBe(
        fixture.rowCount * (1 - expectedHoldoutShare),
      );
      expect(payload.preview?.holdout_rows).toBe(
        fixture.rowCount * expectedHoldoutShare,
      );
      expect(payload.preview?.preview_fingerprint).toMatch(/\S+/);
      await expect(ratio).toHaveValue(holdoutShare);
      const selectedGuidance = page
        .getByLabel("Split option guidance")
        .locator('[aria-current="true"]');
      await expect(selectedGuidance).toContainText(
        `${Math.round((1 - expectedHoldoutShare) * 100)}% Development / ${Math.round(expectedHoldoutShare * 100)}% Final Holdout`,
      );
      const rationale = page.getByTestId(
        "analysis-partition-selection-rationale",
      );
      if (payload.preview?.rationale_required) {
        await expect(rationale).toBeVisible();
        await expect(rationale).toHaveValue("");
        await expect(page.getByTestId("create-analysis-partition")).toBeDisabled();
        await rationale.fill(
          `Strict acceptance documents the governed ${Math.round((1 - expectedHoldoutShare) * 100)}/${Math.round(expectedHoldoutShare * 100)} split tradeoff.`,
        );
        await expect(page.getByTestId("create-analysis-partition")).toBeEnabled();
      } else {
        await expect(rationale).toHaveCount(0);
      }
      return payload.preview;
    };
    await exerciseSplitPreview("0.3");
    await exerciseSplitPreview("0.1");
    const recommendedPreview = await exerciseSplitPreview("0.2");
    expect(recommendedPreview?.rationale_required).toBe(false);
    const createPartition = page.getByTestId("create-analysis-partition");
    await expect(createPartition).toBeEnabled({ timeout: 60_000 });
    await createPartition.click();
    const completePartitionDocumentation = page.getByTestId(
      "complete-analysis-partition-documentation",
    );
    const currentPartitionSummary = page.getByTestId(
      "current-analysis-partition-summary",
    );
    await expect
      .poll(
        async () =>
          (await completePartitionDocumentation.isVisible()) ||
          (await currentPartitionSummary.isVisible()),
        { timeout: 90_000 },
      )
      .toBe(true);
    if (await completePartitionDocumentation.isVisible()) {
      await expect(completePartitionDocumentation).toBeEnabled({ timeout: 30_000 });
      await completePartitionDocumentation.click();
    }
    await expect(currentPartitionSummary).toBeVisible({
      timeout: 90_000,
    });
    await expect(currentPartitionSummary).toContainText(
      /Current|Sealed/i,
    );
    // Partition creation adds development-only target evidence to the special-
    // value contract. Treat and confirm the refreshed, partition-bound review
    // once, rather than accepting a structural draft that would immediately
    // become stale when the governed partition is sealed.
    await expect(page.getByTestId("special-value-analytical-scope")).toHaveAttribute(
      "data-target-analysis-scope",
      "development_population",
      { timeout: 90_000 },
    );
    await page
      .getByTestId("special-value-bulk-treatment")
      .selectOption("convert_to_category");
    const explicitBulkApply = page.getByTestId("apply-special-value-bulk-treatment");
    if (await explicitBulkApply.isVisible()) {
      await explicitBulkApply.click();
    }
    const confirmSpecialValues = specialWorkspace.getByRole("button", {
      name: "Confirm Special-Value Treatment",
      exact: true,
    });
    await expect(confirmSpecialValues).toBeEnabled({ timeout: 60_000 });
    await specialWorkspace
      .getByRole("button", { name: "Save Draft Review", exact: true })
      .click();
    await expect(confirmSpecialValues).toBeEnabled({ timeout: 60_000 });
    await confirmSpecialValues.click();
    await expect(page.getByTestId("special-value-confirmed-revision")).toBeVisible({
      timeout: 90_000,
    });
    await expectReadyForNextStep(page, 180_000);
    await shot(page, testInfo, "step01-data-acquisition-complete");
    await strictContinue(page, projectId, "step02", 180_000);

    // Step 02 — every tab is opened and its primary interaction is exercised.
    await expectExactStep(page, projectId, "step02");
    await expect(page.getByTestId("eda-governed-context-strip")).toContainText(datasetVersionId, {
      timeout: 90_000,
    });
    await expect(page.getByTestId("eda-overview-launch-surface")).toBeVisible();
    const datasetFingerprint = page.getByTestId("eda-dataset-fingerprint");
    await expect(datasetFingerprint).toBeVisible();
    await expect(datasetFingerprint).toContainText(fixture.rowCount.toLocaleString());
    await expect(datasetFingerprint).toContainText(fixture.target);
    await expect(
      datasetFingerprint.getByRole("img", {
        name: /numeric and .* categorical predictors/i,
      }),
    ).toBeVisible();
    await expect(page.getByTestId("eda-data-quality-health")).toContainText(
      /Missing cells.*Duplicate rows/s,
    );

    const edaTabRail = page.getByTestId("eda-analysis-tab-rail");
    await edaTabRail.getByRole("tab", { name: /^Target\b/ }).click();
    await expect(page.getByTestId("target-intelligence-workspace")).toBeVisible({
      timeout: 90_000,
    });
    const targetBalance = page.getByTestId("target-balance-confidence");
    await expect(targetBalance).toBeVisible();
    await expect(targetBalance.getByTestId("target-event-rate")).toHaveText("50.00%");
    await expect(targetBalance.getByTestId("target-event-count")).toHaveText(
      "480 Bad / 1",
    );
    await expect(targetBalance.getByTestId("target-non-event-count")).toHaveText(
      "480 Good / 0",
    );
    await expect(targetBalance.getByTestId("target-total-population")).toHaveText(
      "960 modeled rows",
    );
    await expect(page.getByTestId("target-confidence-interval")).toContainText(
      /95% Wilson confidence interval.*46\.84%.*50\.00%.*53\.16%.*not a forecast interval/s,
    );
    await expect(page.getByTestId("target-no-automatic-treatment")).toContainText(
      /has not enabled SMOTE.*set class weights.*undersampled/s,
    );

    // Target-directed analysis must execute against the exact 960-row
    // Development Population and render both aggregate bands and class-wise
    // box plots. The sealed 240-row final holdout is explicitly excluded.
    await page.getByTestId("target-predictor-search").fill("annual_income");
    await page.getByTestId("target-predictor-select").selectOption("annual_income");
    await page.getByTestId("target-analysis-type").selectOption("numeric_quantile");
    await page.getByTestId("target-band-count").fill("8");
    await page.getByTestId("target-include-missing").check();
    const [targetPredictorResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/api/analytics/target-by-predictor"),
        { timeout: 90_000 },
      ),
      page.getByTestId("target-run-analysis").click(),
    ]);
    expect(targetPredictorResponse.status()).toBe(200);
    const targetPredictorRequest = targetPredictorResponse.request().postDataJSON();
    expect(targetPredictorRequest.projectId).toBe(projectId);
    expect(targetPredictorRequest.datasetId).toBe(datasetId);
    expect(targetPredictorRequest.versionId).toBe(datasetVersionId);
    expect(targetPredictorRequest.target).toBe(fixture.target);
    expect(targetPredictorRequest.predictor).toBe("annual_income");
    expect(targetPredictorRequest.analysisType).toBe("numeric_quantile");
    expect(targetPredictorRequest.bands).toBe(8);
    const targetPredictorResult = await targetPredictorResponse.json();
    expect(targetPredictorResult.ok).toBe(true);
    expect(targetPredictorResult.datasetId).toBe(datasetId);
    expect(targetPredictorResult.versionId).toBe(datasetVersionId);
    expect(targetPredictorResult.target).toBe(fixture.target);
    expect(targetPredictorResult.predictor).toBe("annual_income");
    expect(targetPredictorResult.analyzedRowCount).toBe(960);
    expect(targetPredictorResult.analysisScope?.mode).toBe("governed_version");
    expect(targetPredictorResult.analysisScope?.populationRows).toBe(960);
    expect(targetPredictorResult.analysisScope?.finalHoldoutAccessed).toBe(false);
    expect(targetPredictorResult.finalHoldoutUsedForSelection).toBe(false);
    expect(targetPredictorResult.rows.length).toBeGreaterThanOrEqual(4);
    expect(targetPredictorResult.boxPlotByTarget).toHaveLength(2);
    for (const box of targetPredictorResult.boxPlotByTarget) {
      expect(box.q1).toBeLessThanOrEqual(box.median);
      expect(box.median).toBeLessThanOrEqual(box.q3);
    }
    await expect(page.getByTestId("target-predictor-phase")).toHaveAttribute(
      "data-query-phase",
      /ready|cached/,
      { timeout: 90_000 },
    );
    await expect(page.getByTestId("target-predictor-result-scope")).toContainText(
      /Development Population.*final holdout.*excluded/s,
    );
    const renderedTargetPredictorRows =
      targetPredictorResult.rows.length +
      (targetPredictorResult.missingGroup ? 1 : 0) +
      (targetPredictorResult.otherGroup ? 1 : 0);
    await expect(page.getByTestId("target-by-predictor-table").locator("tbody tr")).toHaveCount(
      renderedTargetPredictorRows,
    );
    await expect(page.getByTestId("target-predictor-box-plot")).toBeVisible();
    await expect(page.getByTestId("target-predictor-analytical-summary")).toBeVisible();

    await edaTabRail.getByRole("tab", { name: /^Predictors\b/ }).click();
    await expect(page.getByTestId("predictor-signal-landscape")).toBeVisible({
      timeout: 90_000,
    });
    const distributionVariable = page.getByTestId("eda-distribution-variable");
    await distributionVariable.selectOption("annual_income");
    const histogramBins = page.getByTestId("eda-distribution-bins");
    const binOptions = await histogramBins.locator("option").all();
    expect(binOptions.length).toBeGreaterThan(1);
    await histogramBins.selectOption({ index: 1 });
    const distributionExplorer = page.getByTestId("predictor-distribution-explorer");
    const distributionSvg = page.getByTestId("eda-distribution-svg");
    await expect(distributionSvg).toBeVisible({ timeout: 90_000 });
    await expect(distributionExplorer).toHaveAttribute("data-motion-phase", "settled", {
      timeout: 90_000,
    });
    await expect(distributionSvg.locator("rect.distribution-bar")).toHaveCount(15);
    await expect(distributionSvg.locator("path.density-line")).toHaveCount(1);
    await expect(distributionSvg.locator("path.event-rate-line")).toHaveCount(1);
    await distributionExplorer
      .getByRole("checkbox", { name: "Outlier bounds", exact: true })
      .check();
    await expect(distributionExplorer.getByText("Target classes")).toHaveCount(0);
    await expect(distributionSvg.locator("text.event-rate-bin-label").first()).toBeVisible();
    expect(await distributionSvg.locator("g.stat-marker").count()).toBeGreaterThanOrEqual(6);
    await expect(page.getByTestId("eda-predictor-metric-grid")).toContainText(
      /Selected rows.*Population share.*Selected mean.*Selected median/s,
    );
    const quantileGrid = page.getByTestId("eda-quantile-grid");
    await expect(quantileGrid).toBeVisible();
    const firstQuantile = quantileGrid.locator("button[data-quantile-index]").first();
    await firstQuantile.click();
    await expect(firstQuantile).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("eda-predictor-metric-grid")).not.toContainText(
      "Selected rangeFull Governed Population",
    );
    const distributionAlternative = page.getByTestId(
      "eda-distribution-accessibility-alternative",
    );
    await distributionAlternative.locator("summary").click();
    await expect(distributionAlternative.getByRole("table")).toBeVisible();
    await expect(distributionAlternative.getByRole("row")).toHaveCount(16);
    const secondaryInsightsBoundary = page.getByTestId(
      "predictor-secondary-insights-boundary",
    );
    await secondaryInsightsBoundary.scrollIntoViewIfNeeded();
    const explicitSecondaryInsightsLoad = page.getByRole("button", {
      name: "Load secondary predictor insights now",
      exact: true,
    });
    const secondaryInsights = page.getByTestId("predictor-secondary-insights");
    if (await explicitSecondaryInsightsLoad.isVisible().catch(() => false)) {
      await explicitSecondaryInsightsLoad.click({ timeout: 5_000 }).catch(async (error) => {
        if (!(await secondaryInsights.isVisible().catch(() => false))) {
          throw error;
        }
      });
    }
    await expect(secondaryInsights).toBeVisible({
      timeout: 90_000,
    });
    const predictorBoxPlot = page.getByTestId("eda-predictor-box-plot");
    await expect(predictorBoxPlot).toBeVisible();
    await expect(predictorBoxPlot).toHaveAttribute(
      "aria-label",
      /annual_income by target class.*Q1.*median.*Q3.*outliers/i,
    );
    await expect(predictorBoxPlot.getByRole("img")).toBeVisible();
    await expect(
      predictorBoxPlot.locator('circle[aria-label^="Observed minimum"]'),
    ).toHaveCount(2);
    await expect(
      predictorBoxPlot.locator('circle[aria-label^="Observed maximum"]'),
    ).toHaveCount(2);

    await edaTabRail.getByRole("tab", { name: /^Relationships\b/ }).click();
    const correlationExplorer = page.getByTestId("correlation-explorer");
    await expect(correlationExplorer).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("correlation-matrix-svg")).toBeVisible({
      timeout: 90_000,
    });
    expect(
      await page
        .getByTestId("correlation-matrix-svg")
        .locator("rect.atlas-correlation-cell")
        .count(),
    ).toBeGreaterThan(4);
    const incomeCorrelation = page
      .getByTestId("correlation-matrix-svg")
      .locator(
        'rect.atlas-correlation-cell[data-row="annual_income"][data-column="income_correlated"]',
      );
    const incomeCorrelationLabel = await incomeCorrelation.getAttribute("aria-label");
    const incomeCorrelationMatch = incomeCorrelationLabel?.match(/correlation (-?\d+\.\d{3})/);
    expect(incomeCorrelationMatch).not.toBeNull();
    expect(Math.abs(Number(incomeCorrelationMatch?.[1]))).toBeGreaterThan(0.25);
    await incomeCorrelation.click();
    const pinnedCorrelation = page.getByTestId("correlation-pinned-pair-detail");
    await expect(pinnedCorrelation).toBeVisible({ timeout: 90_000 });
    await expect(pinnedCorrelation).toContainText("annual_income");
    await expect(pinnedCorrelation).toContainText("income_correlated");
    await correlationExplorer.getByRole("button", { name: "Compact" }).click();
    await expect(correlationExplorer).toHaveAttribute("data-view-mode", "compact");
    await correlationExplorer.getByRole("button", { name: "Readable" }).click();
    await expect(correlationExplorer).toHaveAttribute("data-view-mode", "readable");
    await expect(page.getByTestId("relationship-explorer")).toBeVisible({ timeout: 90_000 });
    const pairwiseBuilder = page.locator("#eda-relationships-pairwise-plot");
    await pairwiseBuilder
      .getByRole("button", { name: "Generate pairwise plot", exact: true })
      .click();
    await expect(pairwiseBuilder.getByText(/Development Population source:/)).toBeVisible({
      timeout: 90_000,
    });

    const vifExplorer = page.getByTestId("vif-explorer");
    await expect(vifExplorer).toHaveAttribute(
      "data-analysis-scope",
      "development_population",
    );
    const annualIncomeVifButton = vifExplorer.locator(
      'button[data-variable="annual_income"]',
    );
    if ((await annualIncomeVifButton.getAttribute("aria-pressed")) !== "true") {
      await annualIncomeVifButton.click();
    }
    await expect(vifExplorer.getByTestId("vif-partner-list")).toContainText(
      "income_correlated",
    );
    const [vifSimulationResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/api/eda/vif-simulation"),
        { timeout: 90_000 },
      ),
      vifExplorer
        .getByRole("button", { name: "Simulate without annual_income", exact: true })
        .click(),
    ]);
    expect(vifSimulationResponse.status()).toBe(200);
    const vifSimulationRequest = vifSimulationResponse.request().postDataJSON();
    expect(vifSimulationRequest.project_id).toBe(projectId);
    expect(vifSimulationRequest.dataset_id).toBe(datasetId);
    expect(vifSimulationRequest.dataset_version_id).toBe(datasetVersionId);
    expect(vifSimulationRequest.excluded_feature).toBe("annual_income");
    const vifSimulation = await vifSimulationResponse.json();
    expect(vifSimulation.ok).toBe(true);
    expect(vifSimulation.project_id).toBe(projectId);
    expect(vifSimulation.dataset_id).toBe(datasetId);
    expect(vifSimulation.dataset_version_id).toBe(datasetVersionId);
    expect(vifSimulation.non_mutating).toBe(true);
    expect(vifSimulation.scope).toBe("development_population");
    expect(vifSimulation.final_holdout_accessed).toBe(false);
    expect(vifSimulation.after).toHaveLength(vifSimulation.summary.remaining_predictors);
    expect(vifSimulation.before.length).toBeGreaterThan(vifSimulation.after.length);
    expect(vifSimulation.after.length).toBeGreaterThan(0);
    for (const row of vifSimulation.after) {
      expect(row).toHaveProperty("before_vif");
      expect(row).toHaveProperty("delta");
    }
    const vifSimulationComparison = vifExplorer.getByTestId(
      "vif-simulation-comparison",
    );
    await expect(vifSimulationComparison).toContainText("Current governed set");
    await expect(vifSimulationComparison).toContainText("Temporary proposed set");
    await expect(vifSimulationComparison).toContainText(
      "No governed feature state was changed",
    );

    const vifResolutionPlan = page.getByTestId("vif-resolution-plan");
    await vifResolutionPlan.getByLabel("Resolution objective").selectOption("reduce_max_vif");
    await vifResolutionPlan
      .getByRole("checkbox", { name: "annual_income", exact: true })
      .check();
    const [vifPlanResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/api/eda/vif-resolution-plan") &&
          !response.url().includes("/decision"),
        { timeout: 120_000 },
      ),
      vifResolutionPlan.getByTestId("generate-vif-resolution-plan").click(),
    ]);
    expect(vifPlanResponse.status()).toBe(200);
    const vifPlanRequest = vifPlanResponse.request().postDataJSON();
    expect(vifPlanRequest.project_id).toBe(projectId);
    expect(vifPlanRequest.dataset_id).toBe(datasetId);
    expect(vifPlanRequest.dataset_version_id).toBe(datasetVersionId);
    expect(vifPlanRequest.resolution_objective).toBe("reduce_max_vif");
    expect(vifPlanRequest.protected_predictors).toContain("annual_income");
    const vifPlan = await vifPlanResponse.json();
    expect(vifPlan.ok).toBe(true);
    expect(vifPlan.plan_id).toMatch(/^vif-plan-/);
    expect(vifPlan.project_id).toBe(projectId);
    expect(vifPlan.dataset_id).toBe(datasetId);
    expect(vifPlan.dataset_version_id).toBe(datasetVersionId);
    expect(vifPlan.governed_feature_set_changed).toBe(false);
    expect(vifPlan.dataset_mutated).toBe(false);
    expect(vifPlan.analysis_scope.development_rows).toBe(960);
    expect(vifPlan.analysis_scope.sealed_final_holdout_rows_excluded).toBe(240);
    expect(vifPlan.analysis_scope.final_holdout_accessed).toBe(false);
    expect(vifPlan.calculation_count.governed_feature_set_calculations).toBe(1);
    expect(vifPlan.calculation_count.simulated_complete_vif_recalculations).toBeGreaterThan(0);
    expect(vifPlan.per_feature_vif_deltas.length).toBeGreaterThan(0);
    expect(vifPlan.clusters.length).toBeGreaterThan(0);
    expect(vifPlan.alternatives.length).toBeGreaterThan(0);
    expect(vifPlan.protected_predictors).toContain("annual_income");
    expect(
      vifPlan.proposed_exclusions.some(
        (proposal: { feature?: string }) => proposal.feature === "annual_income",
      ),
    ).toBe(false);
    expect(vifPlan.explicit_statement).toMatch(/governed feature set.*not changed/i);
    await expect(page.getByTestId("vif-resolution-result")).toBeVisible();
    await expect(page.getByTestId("vif-before-after-chart")).toBeVisible();
    await expect(page.getByTestId("vif-cluster-recommendations")).toBeVisible();
    const [vifDeferResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/api/eda/vif-resolution-plan/decision"),
        { timeout: 90_000 },
      ),
      page.getByTestId("vif-plan-actions").getByRole("button", { name: "Defer" }).click(),
    ]);
    expect(vifDeferResponse.status()).toBe(200);
    const vifDeferred = await vifDeferResponse.json();
    expect(vifDeferred.governed_feature_set_changed).toBe(false);
    expect(vifDeferred.dataset_mutated).toBe(false);

    await edaTabRail.getByRole("tab", { name: /^Stability & Segments\b/ }).click();
    await expect(page.getByTestId("eda-stability-workspace")).toBeVisible({
      timeout: 90_000,
    });
    const stability = page.getByTestId("eda-stability-workspace");
    await stability.getByLabel("Time field").selectOption(fixture.dateColumn);
    const selectedSegment = await selectFirstNonPlaceholder(
      stability.getByLabel("Segment field"),
    );
    const stabilityResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/eda/workspace/stability") &&
        response.request().method() === "POST",
      { timeout: 90_000 },
    );
    await stability.getByRole("button", { name: "Run analysis" }).click();
    const completedStabilityResponse = await stabilityResponse;
    expect(completedStabilityResponse.status()).toBe(200);
    await expect(stability).toContainText("Volume and event rate by time", {
      timeout: 90_000,
    });
    await expect(stability).toContainText("Population and event rate by segment");
    await expect(stability).toContainText(fixture.dateColumn);
    await expect(stability).toContainText(selectedSegment);
    await expect
      .poll(() => stability.getByText(/records \| \d+ events/).count(), {
        timeout: 90_000,
        message: "completed stability analysis must render populated time and segment rows",
      })
      .toBeGreaterThan(1);
    expect(await stability.getByText(/\d+(?:\.\d+)?%/).count()).toBeGreaterThan(1);

    await edaTabRail.getByRole("tab", { name: /^Findings\b/ }).click();
    const findingsWorkspace = page.getByTestId("eda-parent-findings-workspace");
    await expect(findingsWorkspace).toBeVisible({ timeout: 90_000 });
    const parentIds = await findingsWorkspace
      .locator("button[data-parent-id]")
      .evaluateAll((buttons) =>
        buttons.map((button) => button.getAttribute("data-parent-id") ?? ""),
      );
    expect(parentIds.length).toBeGreaterThan(0);
    for (const parentId of parentIds) {
      const parentButton = findingsWorkspace.locator(
        `button[data-parent-id="${parentId}"]`,
      );
      await parentButton.click();
      const disposition = page.getByTestId("eda-parent-finding-disposition");
      const requirement = await parentButton.getAttribute(
        "data-parent-requirement",
      );
      if (requirement === "informational") {
        await expect(disposition).toBeDisabled();
        await expect(page.getByTestId("eda-parent-system-disposition")).toContainText(
          "canonical system disposition",
        );
        continue;
      }
      const allowed = await disposition.locator("option").evaluateAll((options) =>
        options.map((option) => (option as HTMLOptionElement).value),
      );
      const selected = [
        "accepted",
        "documented",
        "no_action_required",
        "not_applicable",
        "deferred",
      ].find((value) => allowed.includes(value));
      expect(selected, `parent finding ${parentId} must expose a completion disposition`).toBeTruthy();
      await disposition.selectOption(selected!);
      await page
        .getByTestId("eda-parent-finding-rationale")
        .fill(`Strict acceptance disposition for governed parent finding ${parentId}.`);
    }
    const duplicateDecision = page.getByTestId("eda-duplicate-decision");
    if (await duplicateDecision.isVisible()) {
      await duplicateDecision.getByLabel("Duplicate row action").selectOption("exclude");
      await duplicateDecision
        .getByRole("button", { name: "Save duplicate-row decision" })
        .click();
      await expect(duplicateDecision).toContainText(/saved/i);
    }
    await page
      .getByPlaceholder(
        "Summarize the population, target, strongest signals, constraints, and readiness.",
      )
      .fill("The governed development population is suitable for controlled model development; target balance, signal evidence, data quality constraints, and holdout isolation were reviewed.");
    await page
      .getByPlaceholder("Record exceptions, open questions, and review priorities.")
      .fill("Carry forward special-value, outlier, missingness, correlation, and stability evidence under the recorded governed decisions.");
    await page.getByLabel("Overall EDA status").selectOption("accepted");
    await expect(page.getByTestId("eda-findings-completion-eligibility")).toContainText(
      "All required parent findings are eligible",
    );
    await page
      .getByRole("button", { name: "Save to Evidence Center", exact: true })
      .click();
    await expect(page.locator('[data-step-next-button="true"]')).toBeEnabled({
      timeout: 120_000,
    });
    await shot(page, testInfo, "step02-all-tabs-and-findings-accepted");
    const findingsContinue = page.getByTestId("eda-final-continue-button");
    await expect(findingsContinue).toHaveCount(1);
    await expect(findingsContinue).toBeEnabled({ timeout: 120_000 });
    const durableEdaCompletion = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname ===
          `/api/projects/${projectId}/workflow-state`,
      { timeout: 180_000 },
    );
    await findingsContinue.click();
    expect((await durableEdaCompletion).ok()).toBe(true);
    await expectExactStep(page, projectId, "step03");

    // Step 03 — outlier treatment recomputes the table and renders before/after charts.
    await expectExactStep(page, projectId, "step03");
    const outlierTable = page.getByTestId("outlier-feature-summary-table");
    await expect(outlierTable).toBeVisible({ timeout: 90_000 });
    const annualIncomeOutlierRow = outlierTable
      .locator("tbody tr")
      .filter({ hasText: "annual_income" })
      .first();
    const annualIncomeOutlierCount = annualIncomeOutlierRow.getByTestId(
      "outlier-count-cell",
    );
    const initialOutlierCount = (await annualIncomeOutlierCount.innerText()).trim();
    const globalOutlierTreatment = page.getByTestId("outlier-global-treatment");
    const outlierOptions = await globalOutlierTreatment.locator("option").evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value),
    );
    expect(outlierOptions).toContain("NONE");
    expect(outlierOptions).toContain("IQR_3_0");
    expect(outlierOptions).toContain("PCT_05_95");
    await globalOutlierTreatment.selectOption("NONE");
    await expect(annualIncomeOutlierCount).toHaveAttribute(
      "data-effective-method",
      "NONE",
    );
    await expect(annualIncomeOutlierCount.locator("span").first()).toHaveText("0");
    await globalOutlierTreatment.selectOption("IQR_3_0");
    await expect(annualIncomeOutlierCount).toHaveAttribute(
      "data-effective-method",
      "IQR_3_0",
    );
    const iqrThreeOutlierCount = Number(
      (await annualIncomeOutlierCount.locator("span").first().innerText()).replace(/,/g, ""),
    );
    expect(iqrThreeOutlierCount).toBeGreaterThan(0);
    await globalOutlierTreatment.selectOption("PCT_05_95");
    await expect(annualIncomeOutlierCount).toHaveAttribute(
      "data-effective-method",
      "PCT_05_95",
    );
    await expect(annualIncomeOutlierCount).not.toHaveText(initialOutlierCount, {
      timeout: 60_000,
    });
    const highImpactNotice = page.getByTestId("outlier-high-impact-inline-notice");
    await expect(highImpactNotice).toBeVisible();
    await expect(highImpactNotice).toContainText(
      /predictor.*exceed 10% projected change.*special values.*preserved/s,
    );
    const outlierSearch = page.getByLabel("Search all outlier predictors");
    const outlierFilter = page.getByLabel("Filter outlier feature table");
    const outlierSort = page.getByLabel("Sort all-feature outlier table");
    await outlierSearch.fill("annual_income");
    await expect(outlierTable.locator("tbody tr")).toHaveCount(1);
    await expect(annualIncomeOutlierRow).toContainText("annual_income");
    await expect(annualIncomeOutlierRow.locator("td")).toHaveCount(20);
    await outlierSearch.fill("");
    await outlierFilter.selectOption("specials");
    for (const column of fixture.specialValueColumns) {
      await expect(outlierTable).toContainText(column);
    }
    expect(await outlierTable.locator("tbody tr").count()).toBeGreaterThanOrEqual(
      fixture.specialValueColumns.length,
    );
    await outlierFilter.selectOption("all");
    await outlierSort.selectOption("name");
    await expect(outlierTable.locator("tbody tr").first()).toContainText("age_years");
    await outlierSort.selectOption("outliers");
    await page.getByTestId("outlier-histogram-limit").selectOption("20");
    const histogramGallery = page.getByTestId("outlier-cutoff-histogram-gallery");
    await expect(histogramGallery).toBeVisible();
    const beforeHistograms = histogramGallery.getByTestId("outlier-before-histogram");
    const afterHistograms = histogramGallery.getByTestId("outlier-after-histogram");
    await expect(beforeHistograms.first()).toBeVisible();
    await expect(afterHistograms.first()).toBeVisible();
    const renderedHistogramCount = await beforeHistograms.count();
    expect(renderedHistogramCount).toBeGreaterThan(5);
    await expect(afterHistograms).toHaveCount(renderedHistogramCount);
    expect(
      await beforeHistograms.first().locator('[title$="rendered values"]').count(),
    ).toBeGreaterThan(5);
    await expect(histogramGallery.getByTestId("outlier-low-cutoff-marker")).toHaveCount(
      renderedHistogramCount * 2,
    );
    await expect(histogramGallery.getByTestId("outlier-high-cutoff-marker")).toHaveCount(
      renderedHistogramCount * 2,
    );
    await expect(histogramGallery.getByTestId("outlier-low-cutoff").first()).toBeVisible();
    await expect(histogramGallery.getByTestId("outlier-high-cutoff").first()).toBeVisible();
    await expect(histogramGallery.getByTestId("outlier-low-cutoff").first()).not.toContainText(
      /—|Unavailable/,
    );
    await expect(histogramGallery.getByTestId("outlier-high-cutoff").first()).not.toContainText(
      /—|Unavailable/,
    );
    const firstCappedHistogram = histogramGallery
      .getByTestId("outlier-capped-histogram-clip")
      .first();
    const firstLowMarker = histogramGallery.getByTestId("outlier-low-cutoff-marker").nth(1);
    const firstHighMarker = histogramGallery.getByTestId("outlier-high-cutoff-marker").nth(1);
    const lowPosition = Number.parseFloat(
      String(await firstLowMarker.evaluate((element) => (element as HTMLElement).style.left)),
    );
    const highPosition = Number.parseFloat(
      String(await firstHighMarker.evaluate((element) => (element as HTMLElement).style.left)),
    );
    expect(lowPosition).toBeGreaterThanOrEqual(0);
    expect(highPosition).toBeGreaterThan(lowPosition);
    expect(highPosition).toBeLessThanOrEqual(100);
    const clipPath = await firstCappedHistogram.evaluate(
      (element) => (element as HTMLElement).style.clipPath,
    );
    expect(clipPath).toMatch(/^inset\(/);
    await expect(histogramGallery).toContainText(
      /no treated value extends beyond the dashed threshold lines/i,
    );
    const firstOverride = outlierTable.getByTestId("outlier-feature-override").first();
    const overrideLabel = await firstOverride.getAttribute("aria-label");
    expect(overrideLabel).toBeTruthy();
    const stableOverride = outlierTable.getByLabel(overrideLabel!);
    const overrideValues = await stableOverride.locator("option").evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value),
    );
    const explicitOverride = overrideValues.find((value) => value && value !== "USE_GLOBAL");
    expect(explicitOverride).toBeTruthy();
    await stableOverride.selectOption(explicitOverride!);
    await expect(stableOverride).toHaveValue(explicitOverride!);
    const overrideRationale = page.getByLabel(
      "Selected feature override rationale",
    );
    await expect(overrideRationale).toBeEnabled();
    await overrideRationale.fill(
      "Strict isolated acceptance verifies an explicit feature treatment with governed rationale.",
    );
    const [outlierApplyResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/api/outliers/apply"),
        { timeout: 120_000 },
      ),
      page.getByTestId("outlier-apply-treatments").click(),
    ]);
    expect(outlierApplyResponse.status()).toBe(200);
    const outlierApplyRequest = outlierApplyResponse.request().postDataJSON();
    expect(outlierApplyRequest.project_id).toBe(projectId);
    expect(outlierApplyRequest.expected_dataset_id).toBe(datasetId);
    expect(outlierApplyRequest.expected_dataset_version_id).toBe(datasetVersionId);
    expect(outlierApplyRequest.global_method).toBe("PCT_05_95");
    expect(outlierApplyRequest.acknowledged_high_impact).toBe(true);
    expect(Object.values(outlierApplyRequest.rationales)).toContain(
      "Strict isolated acceptance verifies an explicit feature treatment with governed rationale.",
    );
    const outlierApply = await outlierApplyResponse.json();
    expect(outlierApply.scope).toBe("full_dataset");
    expect(outlierApply.project_id).toBe(projectId);
    expect(outlierApply.dataset_id).toBe(datasetId);
    expect(outlierApply.dataset_version_id).toBe(datasetVersionId);
    expect(outlierApply.application.changed_values).toBeGreaterThan(0);
    expect(outlierApply.application.row_removal_applied).toBe(false);
    expect(outlierApply.application.high_impact_acknowledged).toBe(true);
    expect(
      outlierApply.application.treatments.reduce(
        (total: number, treatment: { special_values_preserved?: number }) =>
          total + Number(treatment.special_values_preserved ?? 0),
        0,
      ),
    ).toBeGreaterThan(0);
    for (const treatment of outlierApply.application.treatments) {
      expect(treatment.lower_threshold).toBeLessThanOrEqual(treatment.upper_threshold);
    }
    await expect(page.getByTestId("outlier-apply-treatments")).toContainText(
      "Treatments applied",
      { timeout: 120_000 },
    );
    await shot(page, testInfo, "step03-outliers-applied");
    await strictContinue(page, projectId, "step04", 180_000);

    // Step 04 — global strategy changes the projected imputation and is materialized.
    await expectExactStep(page, projectId, "step04");
    const missingTable = page.getByTestId("missing-all-feature-table");
    await expect(missingTable).toBeVisible({ timeout: 90_000 });
    const annualIncomeImputation = page.getByTestId("missing-imputed-value-annual_income");
    await expect(annualIncomeImputation).toBeVisible();
    const missingStrategy = page.getByTestId("missing-global-strategy");
    await missingStrategy.selectOption("Mean");
    await expect(missingStrategy).toHaveValue("Mean");
    const meanProjection = (await annualIncomeImputation.innerText()).trim();
    await missingStrategy.selectOption("Median");
    await expect(missingStrategy).toHaveValue("Median");
    await expect(annualIncomeImputation).not.toHaveText(meanProjection);
    await missingStrategy.selectOption("Mode");
    await expect(missingStrategy).toHaveValue("Mode");
    await page.getByTestId("missing-impact-count").selectOption("20");
    const annualIncomeImpact = page.getByTestId("missing-impact-annual_income");
    await expect(annualIncomeImpact).toBeVisible();
    await expect(annualIncomeImpact).toContainText(/26.*true nulls/s);
    await expect(page.getByTestId("missing-impact-value-annual_income")).not.toHaveText(
      /Unavailable|Not applicable/,
    );
    await missingStrategy.selectOption("Constant");
    await page.getByPlaceholder("Required for Constant").fill("-999");
    await expect(annualIncomeImputation).toContainText("-999");
    await expect(page.getByTestId("missing-impact-value-annual_income")).toHaveText("-999");
    const annualIncomeOverride = page.getByTestId("missing-override-annual_income");
    await annualIncomeOverride.selectOption("Median");
    await expect(annualIncomeOverride).toHaveValue("Median");
    await expect(page.getByTestId("missing-projection-annual_income")).toContainText(
      /0 nulls projected.*26 filled/s,
    );
    await annualIncomeOverride.selectOption("Drop Row");
    await expect(annualIncomeImputation).toHaveText(/Row removed/);
    await expect(page.getByTestId("missing-projection-annual_income")).toHaveText(
      /1,174 rows retained/,
    );
    let missingApplyRequestCount = 0;
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        request.url().includes("/api/missing/apply")
      ) {
        missingApplyRequestCount += 1;
      }
    });
    page.once("dialog", async (dialog) => dialog.dismiss());
    await page
      .locator("#missing-apply-decision")
      .getByRole("button", { name: "Apply treatments", exact: true })
      .click();
    await expect(page.getByText("Row-removal treatment was not applied.")).toBeVisible();
    expect(missingApplyRequestCount).toBe(0);
    await annualIncomeOverride.selectOption("USE_GLOBAL");
    await missingStrategy.selectOption("Mode");
    await expect(annualIncomeOverride).toHaveValue("USE_GLOBAL");
    await expect(missingStrategy).toHaveValue("Mode");
    const missingnessProfile = page.getByTestId("missingness-profile-chart");
    await expect(missingnessProfile).toBeVisible();
    for (const column of fixture.missingValueColumns) {
      await expect(missingnessProfile.getByTitle(new RegExp(`^${column}:`))).toBeVisible();
    }
    const missingSpecialProfile = page.getByTestId("missing-special-stacked-profile");
    await expect(missingSpecialProfile).toBeVisible();
    for (const column of fixture.specialValueColumns) {
      await expect(missingSpecialProfile).toContainText(column);
    }
    expect(
      await missingSpecialProfile.locator('[title^="Bureau special"]').count(),
    ).toBeGreaterThan(0);
    const annualIncomeHistogram = page.getByTestId("missing-histogram-annual_income");
    await expect(annualIncomeHistogram).toBeVisible();
    expect(
      await annualIncomeHistogram.locator('[title$="ordinary observations"]').count(),
    ).toBeGreaterThan(5);
    await expect(page.getByTestId("missing-lower-cutoff-annual_income")).toBeVisible();
    await expect(page.getByTestId("missing-upper-cutoff-annual_income")).toBeVisible();
    const missingImpactPreview = page.getByTestId("missing-impact-preview");
    await expect(missingImpactPreview).toBeVisible();
    await expect(
      missingImpactPreview.getByText("Cells filled", { exact: true }).locator(".."),
    ).toContainText("69");
    await expect(missingImpactPreview).toContainText(
      /annual_income.*Mode.*26.*0.*preserved separately/s,
    );
    const missingnessMechanism = page
      .locator("details")
      .filter({ hasText: "Missingness Mechanism Review" });
    await missingnessMechanism
      .getByText("Missingness Mechanism Review", { exact: true })
      .click();
    await expect(
      missingnessMechanism.getByText("Observed association", { exact: true }),
    ).toBeVisible();
    await expect(
      missingnessMechanism.getByText("Process knowledge", { exact: true }),
    ).toBeVisible();
    await expect(
      missingnessMechanism.getByText("Validation requirement", { exact: true }),
    ).toBeVisible();
    await expect(
      missingnessMechanism.getByText(/does not claim MCAR, MAR, or MNAR/),
    ).toBeVisible();
    const missingApplyDecision = page.locator("#missing-apply-decision");
    const applyMissing = missingApplyDecision.getByRole("button", {
      name: "Apply treatments",
      exact: true,
    });
    await expect(applyMissing).toBeEnabled();
    const [missingApplyResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/api/missing/apply"),
        { timeout: 120_000 },
      ),
      applyMissing.click(),
    ]);
    expect(missingApplyResponse.status()).toBe(200);
    expect(missingApplyRequestCount).toBe(1);
    const missingApplyRequest = missingApplyResponse.request().postDataJSON();
    expect(missingApplyRequest.project_id).toBe(projectId);
    expect(missingApplyRequest.expected_dataset_id).toBe(datasetId);
    expect(missingApplyRequest.expected_dataset_version_id).toBe(datasetVersionId);
    expect(
      Object.values(missingApplyRequest.config).every(
        (entry) => (entry as { strategy?: string }).strategy === "Mode",
      ),
    ).toBe(true);
    const missingApply = await missingApplyResponse.json();
    expect(missingApply.scope).toBe("full_dataset");
    expect(missingApply.project_id).toBe(projectId);
    expect(missingApply.dataset_id).toBe(datasetId);
    expect(missingApply.dataset_version_id).toBe(datasetVersionId);
    expect(missingApply.application.rows_before).toBe(1_200);
    expect(missingApply.application.rows_after).toBe(1_200);
    expect(missingApply.application.missing_before).toBe(69);
    expect(missingApply.application.missing_after).toBe(0);
    expect(missingApply.application.dropped_rows).toBe(0);
    expect(
      missingApply.application.treatments.map(
        (treatment: { feature: string }) => treatment.feature,
      ).sort(),
    ).toEqual([...fixture.missingValueColumns].sort());
    expect(
      missingApply.application.treatments.reduce(
        (total: number, treatment: { filled?: number }) =>
          total + Number(treatment.filled ?? 0),
        0,
      ),
    ).toBe(69);
    await expect(
      missingApplyDecision.getByRole("button", {
        name: "Current treatment applied",
        exact: true,
      }),
    ).toBeVisible({ timeout: 120_000 });
    await shot(page, testInfo, "step04-missing-values-applied");
    await strictContinue(page, projectId, "step05", 180_000);

    // Step 05 — every first-class feature builder creates a governed draft, then
    // the single completion action validates, previews, materializes, and confirms.
    await expectExactStep(page, projectId, "step05");
    await expect(page.getByTestId("feature-builder-launcher")).toBeVisible({ timeout: 90_000 });
    await addEngineeredFeature(page, "Interaction", "age_income_interaction", async () => {
      const builder = page.getByTestId("feature-builder-configuration");
      await builder.getByLabel("Left source").selectOption("age_years");
      await builder.getByLabel("Right source").selectOption("annual_income");
    });
    await addEngineeredFeature(page, "Numeric Bin", "income_band", async () => {
      const builder = page.getByTestId("feature-builder-configuration");
      await builder.getByLabel("Source predictor").selectOption("annual_income");
      await builder.getByLabel("Binning mode").selectOption("custom");
      await builder
        .getByRole("textbox", { name: "Cut points", exact: true })
        .fill("40000, 70000");
      await builder.getByLabel("Ordinary labels").fill("Low, Medium, High");
      await builder.getByLabel("Bureau-special label").fill("Bureau special");
      await builder.getByLabel("True-missing label").fill("Missing");
    });
    await addEngineeredFeature(page, "Rule Category", "high_utilization_band", async () => {
      const builder = page.getByTestId("feature-builder-configuration");
      await builder.getByLabel("Source predictor").selectOption("utilization_pct");
      await builder.getByLabel("Operator").selectOption("greater_than");
      await builder.getByLabel("Rule value").fill("80");
      await builder.getByLabel("Matched label").fill("High");
      await builder.getByLabel("Else label").fill("Standard");
      await builder.getByLabel("Bureau-special label").fill("Bureau special");
    });
    await addEngineeredFeature(page, "Polynomial", "recent_trade_count_squared", async () => {
      const builder = page.getByTestId("feature-builder-configuration");
      await builder.getByLabel("Source predictor").selectOption("recent_trade_count");
      await builder.getByLabel("Degree").selectOption("2");
    });
    await addEngineeredFeature(page, "Arithmetic", "income_pair_product", async () => {
      const builder = page.getByTestId("feature-builder-configuration");
      await builder.getByLabel("Left source").selectOption("annual_income");
      await builder.getByLabel("Right source").selectOption("income_correlated");
      await builder.getByLabel("Operation").selectOption("multiply");
      await builder.getByLabel("Result domain").selectOption("unrestricted");
      await builder.getByLabel("Domain evidence note").fill("Both inputs are compatible annual currency measures.");
    });
    await addEngineeredFeature(page, "Date Derived", "application_month", async () => {
      const builder = page.getByTestId("feature-builder-configuration");
      await builder.getByLabel("Source predictor").selectOption(fixture.dateColumn);
      await builder.getByLabel("Date component").selectOption("month");
    });
    const featurePlan = page.getByTestId("feature-transformation-plan");
    for (const engineered of [
      "age_income_interaction",
      "income_band",
      "high_utilization_band",
      "recent_trade_count_squared",
      "income_pair_product",
      "application_month",
    ]) {
      await expect(featurePlan).toContainText(engineered);
    }
    const featureSetReview = page.getByTestId("feature-set-review");
    await expect(featureSetReview).toBeVisible();
    const featureSearch = featureSetReview.getByLabel("Search feature set");
    const featureFilter = featureSetReview.getByLabel("Filter feature set");
    await featureFilter.selectOption("engineered");
    const engineeredInventoryRows = featurePlan.locator(
      'tbody tr:not([data-feature-origin="original"])',
    );
    await expect(engineeredInventoryRows).toHaveCount(6);
    await expect(engineeredInventoryRows.locator('input[type="checkbox"]:checked')).toHaveCount(
      6,
    );
    await featureSearch.fill("income_band");
    await expect(featurePlan.locator("tbody tr")).toHaveCount(1);
    const incomeBandRow = featurePlan.locator("tbody tr").first();
    await expect(incomeBandRow).toContainText(/income_band.*Engineered.*annual_income/s);
    await incomeBandRow.getByRole("button", { name: "Review details" }).click();
    const featureContractDetail = page.getByTestId("feature-contract-detail");
    await expect(featureContractDetail).toBeVisible();
    await expect(featureContractDetail).toContainText(/income_band.*annual_income/s);
    await expect(featureContractDetail).toContainText(/40000.*70000/s);
    await featureContractDetail.getByTitle("Close feature detail").click();
    await featureSearch.fill("");
    await featureFilter.selectOption("source");
    expect(await featurePlan.locator('tbody tr[data-feature-origin="original"]').count()).toBeGreaterThan(
      5,
    );
    await expect(featurePlan).toContainText("annual_income");
    await featureFilter.selectOption("all");

    const featureSecondaryTools = page.getByTestId(
      "feature-engineering-secondary-tools",
    );
    await featureSecondaryTools.locator(":scope > summary").click();
    const featureLineage = page.getByTestId("feature-lineage-graph");
    await expect(featureLineage).toBeVisible();
    await expect(featureLineage).toContainText(
      /age_years.*annual_income.*age_income_interaction/s,
    );
    await expect(featureLineage).toContainText(
      /application_date.*application_month/s,
    );
    expect(await featureLineage.locator(":scope > div > div").count()).toBeGreaterThanOrEqual(6);
    await shot(page, testInfo, "step05-six-builder-drafts");

    // The single governed continuation owns preview and materialization. Hold
    // its already-required materialization request briefly so the bounded,
    // non-mutating preview can be asserted before navigation completes.
    let releaseFeatureMaterialization: (() => void) | undefined;
    const featureMaterializationGate = new Promise<void>((resolve) => {
      releaseFeatureMaterialization = resolve;
    });
    await page.route("**/features/materialize", async (route) => {
      await featureMaterializationGate;
      await route.continue();
    });
    const featureMaterializationRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" && request.url().includes("/features/materialize"),
      { timeout: 180_000 },
    );
    const featureContinue = page.locator('[data-step-next-button="true"]');
    await expect(featureContinue).toBeEnabled({ timeout: 60_000 });
    await featureContinue.click();
    await featureMaterializationRequest;
    try {
      await expect(page.getByText("Bounded feature preview", { exact: true })).toBeVisible({
        timeout: 60_000,
      });
      const featurePreviewTable = page.getByRole("table").filter({
        has: page.getByRole("columnheader", { name: "age_income_interaction" }),
      });
      await expect(featurePreviewTable).toBeVisible();
      await expect(featurePreviewTable.getByRole("columnheader", { name: "income_band" })).toBeVisible();
      await expect(featurePreviewTable.getByRole("columnheader", { name: "application_month" })).toBeVisible();
      await expect(featurePreviewTable.getByRole("row")).toHaveCount(11);
    } finally {
      releaseFeatureMaterialization?.();
    }
    await expectExactStep(page, projectId, "step06");
    await page.unroute("**/features/materialize");

    // Step 06 — exercise the currently supported classification validation
    // approaches, then persist one exact development-only design.
    await expectExactStep(page, projectId, "step06");
    const immutablePartition = page.getByTestId("immutable-analysis-partition");
    await expect(immutablePartition).toBeVisible({
      timeout: 90_000,
    });
    const partitionSummary = page.getByTestId("analysis-partition-read-only-summary");
    await expect(partitionSummary).toContainText(/Development rows.*960/s);
    await expect(partitionSummary).toContainText(/Final holdout rows.*240/s);
    await expect(partitionSummary).toContainText(/Development \/ holdout.*80% \/ 20%/s);
    await expect(partitionSummary).toContainText(/Seal.*sealed/is);
    const validationDesignSummary = page.getByTestId("validation-design-summary");
    await expect(validationDesignSummary).toBeVisible();
    const cvControls = page.getByTestId("holdout-cv-controls");
    const validationApproach = cvControls.getByLabel("Validation approach");
    await expect(validationApproach).toHaveValue("stratified_k_fold");
    await validationApproach.selectOption("none");
    await expect(validationApproach).toHaveValue("none");
    await validationApproach.selectOption("stratified_k_fold");
    await expect(cvControls.getByLabel("Shuffle before folding")).toBeEnabled();
    await cvControls.getByLabel("Number of folds").selectOption("4");
    await cvControls.getByLabel("Number of folds").selectOption("5");
    await cvControls.getByTestId("fold-local-preprocessing").selectOption(
      "model_native_per_fold",
    );
    await cvControls.getByTestId("fold-local-preprocessing").selectOption(
      "fit_transform_per_fold",
    );
    await page
      .getByTestId("validation-design-rationale")
      .getByRole("textbox")
      .fill("Five-fold stratified development-only validation preserves the sealed final holdout and fits preprocessing independently in every fold.");
    await expect(validationDesignSummary).toContainText(
      /Cross-Validation Inside Training.*5-fold stratified k fold/s,
    );
    const partitionVisual = page.getByTestId("population-partition-visual");
    // Exact row counts are asserted above against the immutable, backend-
    // authoritative Analysis Partition summary. This composition is a design
    // preview and intentionally renders projected percentages until the
    // validation design has been persisted.
    await expect(partitionVisual).toContainText(/Training set.*80%/s);
    await expect(partitionVisual).toContainText(/Test holdout.*20%/s);
    await expect(partitionVisual.locator(".prep-split-preview__train")).toHaveAttribute(
      "style",
      /width: 80%/,
    );
    const foldArchitecture = page.getByTestId("fold-architecture-visual");
    await expect(foldArchitecture).toContainText("stratified k fold");
    await expect(foldArchitecture.getByText(/^Round \d+$/)).toHaveCount(5);
    const classBalanceVisual = page.getByTestId("class-balance-preservation");
    await expect(classBalanceVisual).toContainText(/Development.*960.*480.*480.*50\.0+%/s);
    await expect(classBalanceVisual.getByText(/^Fold \d+$/)).toHaveCount(5);

    const balancing = page.getByTestId("advanced-balancing-settings");
    await expect(balancing).toBeVisible();
    await balancing.getByRole("button", { name: /Oversample minority/ }).click();
    await expect(balancing).toContainText(/Current policy.*Oversample minority/i);
    await balancing.getByLabel("Target minority share").selectOption("0.4");
    await expect(balancing.getByLabel("Target minority share")).toHaveValue("0.4");
    await expect(balancing).toContainText("Fold-local resampling selected");
    await balancing.getByRole("button", { name: /^SMOTE/ }).click();
    await expect(balancing).toContainText(/Current policy.*SMOTE/i);
    await balancing.getByRole("button", { name: /No resampling/ }).click();
    await expect(balancing).toContainText(/Current policy.*No resampling/i);
    const classWeights = balancing.getByLabel("Class weights");
    await classWeights.selectOption("balanced");
    await expect(classWeights).toHaveValue("balanced");
    await classWeights.selectOption("none");
    await expect(classWeights).toHaveValue("none");

    const external = page.getByTestId("advanced-external-validation");
    await expect(external).toBeVisible();
    await external.getByLabel("Use separate TEST dataset").check();
    await expect(external.getByTestId("external-validation-datasets")).toBeVisible();
    await external.getByLabel("Use both TEST and OOT").check();
    const externalDatasets = external.getByTestId("external-validation-datasets");
    await expect(externalDatasets).toContainText("TEST dataset contract");
    await expect(externalDatasets).toContainText("OOT dataset contract");
    await expect(externalDatasets.getByLabel("TEST dataset")).toBeVisible();
    await expect(externalDatasets.getByLabel("OOT dataset")).toBeVisible();
    await external.getByLabel("No external dataset").check();
    await expect(external.getByTestId("external-validation-datasets")).toHaveCount(0);
    const finalPredictorReview = page.getByTestId("compact-final-predictor-review");
    await expect(finalPredictorReview).toBeVisible();
    for (const engineered of [
      "age_income_interaction",
      "income_band",
      "high_utilization_band",
      "recent_trade_count_squared",
      "income_pair_product",
      "application_month",
    ]) {
      await expect(finalPredictorReview).toContainText(engineered);
      await expect(finalPredictorReview.getByLabel(`Use ${engineered}`)).toBeChecked();
    }
    const readinessChecklist = page.getByTestId("validation-readiness-checklist");
    await expect(readinessChecklist.locator(":scope > div")).toHaveCount(8);
    await expect(readinessChecklist).toContainText(
      /Canonical dataset identity.*Feature manifest current.*K-fold cross-validation selected.*Balancing policy recorded/s,
    );
    await expect(page.getByTestId("validation-readiness-blocker")).toContainText(
      "Ready for the final action",
      { timeout: 90_000 },
    );
    await shot(page, testInfo, "step06-validation-design-ready");
    await strictContinue(page, projectId, "step07", 240_000);

    // Step 07 — verify both previously-problematic bench selectors keep the
    // primary action available, then train the quick supervised strategy.
    await expectExactStep(page, projectId, "step07");
    const trainingMissionControl = page.getByTestId("training-mission-control");
    await expect(trainingMissionControl).toBeVisible({ timeout: 90_000 });
    await expect(trainingMissionControl).toContainText(projectName);
    await expect(trainingMissionControl).toContainText(fixture.target);
    await expect(trainingMissionControl).toContainText(/6 engineered/);
    const lockedTrainingInputs = page.getByTestId("locked-training-inputs");
    await expect(lockedTrainingInputs).toBeVisible({
      timeout: 90_000,
    });
    await expect(lockedTrainingInputs).toContainText(datasetVersionId);
    await expect(page.getByTestId("validation-contract-readonly")).toContainText(
      /stratified k fold.*5 folds/s,
    );
    const hyperparameterControl = page.getByTestId("hyperparameter-search-control");
    await expect(hyperparameterControl).toHaveRole("group");
    await expect(page.getByRole("group", {
      name: "Hyperparameter search",
      exact: true,
    })).toBeVisible();
    const hyperparameterSearch = hyperparameterControl.getByRole("checkbox", {
      name: "Hyperparameter search",
      exact: true,
    });
    if (!(await hyperparameterSearch.isChecked())) {
      await changeTrainingPortfolioAndWaitForSave(
        page,
        () => hyperparameterSearch.check(),
        (payload) => payload.grid_search === true,
      );
    }
    const hyperparameterDepth = hyperparameterControl.getByRole("combobox", {
      name: "Hyperparameter search depth",
      exact: true,
    });
    if ((await hyperparameterDepth.inputValue()) !== "quick") {
      await changeTrainingPortfolioAndWaitForSave(
        page,
        () => hyperparameterDepth.selectOption("quick"),
        (payload) =>
          payload.grid_search === true && payload.grid_search_level === "quick",
      );
    }
    await expect(hyperparameterSearch).toBeChecked();
    await expect(hyperparameterDepth).toHaveValue("quick");
    let largeBenchJobRequests = 0;
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        request.url().includes("/api/model/train/jobs")
      ) {
        largeBenchJobRequests += 1;
      }
    });
    const expectedBalancedBench = [
      "logreg",
      "ridge_clf",
      "dtree",
      "sgd_log",
      "gnb",
      "bernoulli_nb",
      "rf",
      "extra_trees",
      "xgb",
      "lgbm",
      "linsvm",
    ];
    const expectedResearchBench = [
      "logreg",
      "ridge_clf",
      "dtree",
      "ebm",
      "lda",
      "gnb",
      "bernoulli_nb",
      "qda",
      "sgd_log",
      "histgb",
      "rf",
      "extra_trees",
      "xgb",
      "cat",
      "lgbm",
      "knn",
      "linsvm",
      "iso",
      "autoreg",
      "oneclass_svm",
      "elliptic",
      "mlp",
      "fnn",
      "tensorflow_dnn",
      "cnn",
      "rnn_lstm",
    ];
    const verifyLargeBenchPreflight = async (
      suiteButton: Locator,
      expectedModels: string[],
    ) => {
      const savedPortfolio = await changeTrainingPortfolioAndWaitForSave(
        page,
        () => suiteButton.click(),
        (payload) =>
          JSON.stringify(
            payload.selected_algorithm_ids ?? payload.selected_models ?? [],
          ) === JSON.stringify(expectedModels),
      );
      const savedSelection = savedPortfolio.selection ?? savedPortfolio;
      expect(
        savedSelection.selected_algorithm_ids ?? savedSelection.selected_models,
      ).toEqual(expectedModels);
      expect(savedPortfolio.project_id).toBe(projectId);
      expect(savedPortfolio.dataset_id).toBe(datasetId);
      expect(savedPortfolio.dataset_version_id).toBe(datasetVersionId);
      await expect(suiteButton).toHaveClass(/border-blue-500/);
      await expectPrimaryTrainingActionEnabled(page);
      await expect(
        page
          .getByTestId("model-portfolio-filters")
          .getByText("Selected", { exact: true })
          .locator(".."),
      ).toContainText(String(expectedModels.length));
      const [largePreflightResponse] = await Promise.all([
        page.waitForResponse(
          (response) =>
            response.request().method() === "POST" &&
            response.url().includes("/api/model/train/preflight"),
          { timeout: 120_000 },
        ),
        page
          .getByRole("button", { name: "Run Preflight", exact: true })
          .first()
          .click(),
      ]);
      expect(largePreflightResponse.status()).toBe(200);
      const largePreflightRequest = largePreflightResponse.request().postDataJSON();
      expect(largePreflightRequest.models).toEqual(expectedModels);
      expect(largePreflightRequest.grid_search).toBe(true);
      expect(largePreflightRequest.grid_search_level).toBe("quick");
      expect(largePreflightRequest.large_job_confirmed).toBe(false);
      const largePreflight = await largePreflightResponse.json();
      expect(largePreflight.ready).toBe(true);
      expect(largePreflight.blocking_errors ?? []).toEqual([]);
      expect(largePreflight.project_id).toBe(projectId);
      expect(largePreflight.dataset_id).toBe(datasetId);
      expect(largePreflight.dataset_version_id).toBe(datasetVersionId);
      expect(largePreflight.selected_algorithm_ids).toEqual(expectedModels);
      expect(largePreflight.base_fit_count).toBe(expectedModels.length * 5 * 4);
      expect(largePreflight.large_run.required).toBe(true);
      expect(largePreflight.large_run.threshold_fits).toBe(160);
      expect(largePreflight.large_run.acknowledged).toBe(false);
      expect(largePreflight.large_run.acknowledgement_required).toBe(true);
      expect(largePreflight.large_run_status).toBe("acknowledgement_required");
      expect(largePreflight.final_holdout_sealed).toBe(true);
      expect(largePreflight.final_holdout_access).toBe("contract_metadata_only");
      expect(largePreflight.selection_evidence_source).toBe(
        "development_population_cross_validation",
      );
      const largeRunConfirmation = page.getByTestId("large-job-confirmation");
      await expect(largeRunConfirmation).toBeVisible();
      const startGovernedTraining = page.getByRole("button", {
        name: "Acknowledge and Start Governed Training",
        exact: true,
      });
      await expect(startGovernedTraining).toBeDisabled();
      await largeRunConfirmation.getByRole("checkbox").check();
      await expect(startGovernedTraining).toBeEnabled();
      expect(largeBenchJobRequests).toBe(0);
    };
    const balancedBench = page.getByRole("button", {
      name: /^Balanced Challenger Bench\b/,
    });
    await verifyLargeBenchPreflight(balancedBench, expectedBalancedBench);
    const researchBench = page.getByRole("button", { name: /^Full Research Bench\b/ });
    await verifyLargeBenchPreflight(researchBench, expectedResearchBench);
    const transparentBaseline = page.getByTestId("candidate-strategy-selector").getByRole("button", {
      name: /^Transparent baseline/,
    });
    const expectedTransparentBaseline = ["logreg", "ridge_clf", "dtree"];
    const transparentSave = await changeTrainingPortfolioAndWaitForSave(
      page,
      () => transparentBaseline.click(),
      (payload) =>
        JSON.stringify(
          payload.selected_algorithm_ids ?? payload.selected_models ?? [],
        ) === JSON.stringify(expectedTransparentBaseline),
    );
    const transparentSelection = transparentSave.selection ?? transparentSave;
    expect(
      transparentSelection.selected_algorithm_ids ??
        transparentSelection.selected_models,
    ).toEqual(expectedTransparentBaseline);
    await expect(transparentBaseline).toHaveClass(/border-blue-600/);
    await expectPrimaryTrainingActionEnabled(page);
    await changeTrainingPortfolioAndWaitForSave(
      page,
      () => hyperparameterSearch.uncheck(),
      (payload) =>
        payload.grid_search === false &&
        JSON.stringify(
          payload.selected_algorithm_ids ?? payload.selected_models ?? [],
        ) === JSON.stringify(expectedTransparentBaseline),
    );
    await expect(hyperparameterSearch).not.toBeChecked();
    expect(largeBenchJobRequests).toBe(0);

    const portfolioFilters = page.getByTestId("model-portfolio-filters");
    await expect(
      portfolioFilters.getByText("Selected", { exact: true }).locator(".."),
    ).toContainText("3");
    const modelSearch = portfolioFilters.getByPlaceholder(
      "Name, family, purpose, or best use",
    );
    await modelSearch.fill("Logistic Regression");
    await expect(page.getByRole("heading", { name: "Logistic Regression", exact: true })).toBeVisible();
    await expect(
      portfolioFilters.getByText("Visible", { exact: true }).locator(".."),
    ).toContainText("1");
    await modelSearch.fill("");
    await portfolioFilters.getByLabel("Selected only").check();
    await expect(
      portfolioFilters.getByText("Visible", { exact: true }).locator(".."),
    ).toContainText("3");
    await portfolioFilters.getByLabel("Selected only").uncheck();
    const trainingPlan = page.getByTestId("training-plan-visual");
    await expect(trainingPlan).toContainText(/Candidates.*3 models/s);
    await expect(trainingPlan).toContainText(/Validation.*5 folds.*stratified k fold/s);

    const [preflightResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/model/train/preflight"),
        { timeout: 90_000 },
      ),
      page.getByRole("button", { name: "Run Preflight", exact: true }).click(),
    ]);
    expect(preflightResponse.status()).toBe(200);
    const preflight = await preflightResponse.json();
    expect(preflight.ready).toBe(true);
    expect(preflight.blocking_errors ?? []).toEqual([]);
    expect(preflight.project_id).toBe(projectId);
    expect(preflight.dataset_id).toBe(datasetId);
    expect(preflight.dataset_version_id).toBe(datasetVersionId);
    await expect(lockedTrainingInputs).toContainText(datasetId);
    await expect(lockedTrainingInputs).toContainText(datasetVersionId);
    await expect(page.getByTestId("authoritative-preflight-identity")).toContainText(
      String(preflight.preflight_id),
    );
    const preflightChecks = page.getByTestId("authoritative-preflight-checks");
    await expect(preflightChecks).toBeVisible();
    expect(await preflightChecks.locator(":scope > div").count()).toBeGreaterThan(3);
    await expect(preflightChecks.locator(":scope > div.border-red-200")).toHaveCount(0);
    await expect(page.getByTestId("final-holdout-sealed-status")).toContainText(/sealed/i);
    await expect(
      page.getByRole("button", { name: "Start Governed Training", exact: true }),
    ).toBeEnabled();

    const [jobCreateResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/model/train/jobs"),
        { timeout: 90_000 },
      ),
      page.getByRole("button", { name: "Start Governed Training", exact: true }).click(),
    ]);
    expect(jobCreateResponse.status()).toBe(200);
    const createdJob = (await jobCreateResponse.json()) as TrainingJob;
    expect(createdJob.job_id).toBeTruthy();

    const jobDeadline = Date.now() + 8 * 60_000;
    let terminalJob: TrainingJob = createdJob;
    while (Date.now() < jobDeadline) {
      const statusResponse = await browserGetJson<TrainingJob>(
        page,
        `${backendBaseUrl}/api/model/train/jobs/${encodeURIComponent(createdJob.job_id)}?project_id=${encodeURIComponent(projectId)}`,
      );
      expect(statusResponse.status).toBe(200);
      expect(statusResponse.payload).not.toBeNull();
      terminalJob = statusResponse.payload!;
      if (["complete", "failed", "cancelled", "interrupted"].includes(terminalJob.overall_status)) {
        break;
      }
      await page.waitForTimeout(2_000);
    }
    expect(terminalJob.overall_status).toBe("complete");
    expect(terminalJob.failed_count ?? 0).toBe(0);
    expect(terminalJob.completed_count).toBe(terminalJob.total_count);
    const ranked = terminalJob.partial_ranked_results ?? terminalJob.summary?.ranked ?? [];
    const eligibleRanked = ranked.filter(
      (row) => row.champion_eligible !== false && row.kind !== "anomaly",
    );
    expect(eligibleRanked.length).toBeGreaterThan(0);
    const eligible = ranked.find(
      (row) =>
        row.candidate_id &&
        row.champion_eligible !== false &&
        row.kind !== "anomaly",
    );
    expect(eligible?.candidate_id).toBeTruthy();
    const candidateId = eligible!.candidate_id!;
    const trainingRunId = String(
      eligible!.training_run_id ?? terminalJob.training_run_id ?? "",
    );
    expect(trainingRunId).not.toBe("");

    await expect(page.getByTestId("live-training-active-region")).toContainText(
      /Job complete/i,
      { timeout: 60_000 },
    );
    const leaderboardSection = page
      .getByRole("heading", { name: "Candidate Leaderboard", exact: true })
      .locator("xpath=ancestor::section[1]");
    await expect(leaderboardSection.getByTestId("candidate-comparison-visuals")).toBeVisible({
      timeout: 60_000,
    });
    await expect(
      leaderboardSection.getByText("Candidate models", { exact: true }).locator(".."),
    ).toContainText(String(eligibleRanked.length));
    const leaderboardTables = leaderboardSection.getByRole("table");
    await expect(leaderboardTables).toHaveCount(2);
    await expect(leaderboardTables.nth(0).locator("tbody tr")).toHaveCount(
      eligibleRanked.length,
    );
    await expect(leaderboardTables.nth(1).locator("tbody tr")).toHaveCount(
      eligibleRanked.length,
    );
    await expect(leaderboardSection).toContainText("Verified selection leader");
    const candidateSelect = page.getByLabel("Candidate to lock");
    await expect(candidateSelect.locator("option")).toHaveCount(eligibleRanked.length);
    await expect(candidateSelect.locator(`option[value="${candidateId}"]`)).toHaveCount(1);
    await candidateSelect.selectOption(candidateId);
    const lockCandidateDecision = page.getByRole("button", {
      name: "Lock candidate decision",
    });
    await expect(lockCandidateDecision).toBeEnabled();
    await expect(page.locator('[data-step-next-button="true"]')).toBeEnabled();
    await page
      .getByLabel("Decision rationale")
      .fill("Lock the exact supervised development-evidence candidate for downstream final-holdout Evaluation.");
    await page
      .getByLabel("Metric justification")
      .fill("The governed primary metric and frozen ranking snapshot are appropriate for candidate selection.");
    await page
      .getByLabel("Interpretability justification")
      .fill("The transparent baseline remains reviewable and its fitted artifact is reproducible.");
    await page
      .getByLabel("Calibration considerations")
      .fill("Calibration remains an Evaluation-stage review and did not rank this candidate on the final holdout.");
    await page
      .getByLabel("Fairness / validation prerequisites")
      .fill("Complete downstream segment, fairness, and stability review before approval.");
    await page
      .getByLabel("Deployment constraints")
      .fill("Deployment remains blocked pending Evaluation, Interpretation, documentation, and governance approval.");
    await page
      .getByLabel("Reviewer notes")
      .fill("Strict isolated acceptance candidate lock; no live data and no scoring.");

    const [decisionResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/model/train/decision"),
        { timeout: 90_000 },
      ),
      lockCandidateDecision.click(),
    ]);
    expect(decisionResponse.status()).toBe(200);
    const decisionEnvelope = await decisionResponse.json();
    const decision = decisionEnvelope?.decision ?? decisionEnvelope;
    expect(decision.status).toBe("locked");
    expect(decision.selected_candidate_id).toBe(candidateId);
    expect(decision.training_run_id).toBe(trainingRunId);
    expect(decision.project_id).toBe(projectId);
    const decisionId = String(decision.decision_id ?? "");
    expect(decisionId).not.toBe("");
    await expect(
      page.getByRole("button", { name: "Candidate decision locked", exact: true }),
    ).toBeVisible();
    await expect(page.locator('[data-step-next-button="true"]')).toBeEnabled({
      timeout: 60_000,
    });

    const checkpoint: DurableIdentity = {
      project_id: projectId,
      dataset_id: datasetId,
      dataset_version_id: datasetVersionId,
      training_job_id: String(terminalJob.training_job_id ?? terminalJob.job_id),
      training_run_id: trainingRunId,
      candidate_id: candidateId,
      candidate_decision_id: decisionId,
      evaluation_package_id: null,
      disposable_user_email: user.email,
    };
    writeCheckpoint(testInfo, checkpoint);
    console.log("STRICT_STAGE_A_DURABLE_IDENTITY:", JSON.stringify(checkpoint));
    await shot(page, testInfo, "step07-terminal-training-and-candidate-lock");

    const evaluationCommandResponsePromise = page.waitForResponse(
      (response) => {
        if (
          response.request().method() !== "GET" ||
          !response.url().includes("/eval/command_center")
        ) {
          return false;
        }
        const query = new URL(response.url()).searchParams;
        return (
          query.get("candidate_id") === candidateId &&
          query.get("candidate_decision_id") === decisionId &&
          query.get("evidence_scope") !== "selection_review"
        );
      },
      { timeout: 180_000 },
    );
    await strictContinue(page, projectId, "step08", 180_000);
    const evaluationCommandResponse = await evaluationCommandResponsePromise;
    expect(evaluationCommandResponse.status()).toBe(200);
    const evaluationCommand = await evaluationCommandResponse.json();
    const evaluationPackage = evaluationCommand?.evaluation_package ?? evaluationCommand;
    expect(String(evaluationPackage?.project_id ?? evaluationCommand?.project_id)).toBe(projectId);
    expect(String(evaluationPackage?.dataset_id ?? evaluationCommand?.dataset_id)).toBe(datasetId);
    expect(
      String(evaluationPackage?.dataset_version_id ?? evaluationCommand?.dataset_version_id),
    ).toBe(datasetVersionId);
    expect(String(evaluationPackage?.candidate_id ?? evaluationCommand?.candidate_id)).toBe(
      candidateId,
    );
    expect(
      String(evaluationPackage?.training_run_id ?? evaluationCommand?.training_run_id),
    ).toBe(trainingRunId);
    expect(
      String(
        evaluationPackage?.candidate_decision_id ??
          evaluationCommand?.candidate_decision_id,
      ),
    ).toBe(decisionId);
    await expect(page.getByTestId("evaluation-command-center")).toBeVisible({
      timeout: 180_000,
    });
    const performanceSummary = page.getByTestId("atlas-performance-summary");
    await expect(performanceSummary).toBeVisible();
    await expect(performanceSummary).toContainText(decisionId);
    await expect(performanceSummary).toContainText("Reporting package verified");
    const resolvedEvaluationPackageId = String(
      evaluationPackage?.evaluation_package_id ??
        evaluationCommand?.evaluation_package_id ??
        "",
    );
    expect(resolvedEvaluationPackageId).not.toBe("");
    const visibleReviewScope = page.getByTestId("selection-review-scope");
    await expect(visibleReviewScope).toBeVisible();
    await expect(visibleReviewScope).toContainText(resolvedEvaluationPackageId);
    const evaluationPackageId: string | null = resolvedEvaluationPackageId;
    checkpoint.evaluation_package_id = evaluationPackageId;
    writeCheckpoint(testInfo, checkpoint);
    await testInfo.attach("strict-stage-a-checkpoint", {
      path: testInfo.outputPath("strict-stage-a-checkpoint.json"),
      contentType: "application/json",
    });
    await shot(page, testInfo, "step08-exact-candidate-boundary");

    expect(pageErrors).toEqual([]);
    console.log("STRICT_STAGE_A_CHECKPOINT_PATH:", testInfo.outputPath("strict-stage-a-checkpoint.json"));
  });
});
