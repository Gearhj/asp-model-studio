import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import {
  expect,
  test,
  type Locator,
  type Page,
  type Response,
  type TestInfo,
} from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative } from "./helpers/projectContext";

type JsonRecord = Record<string, any>;

const HELOC_SOURCE = path.resolve(
  "server",
  "artifacts",
  "datasets",
  "ds_heloc_train_6bdb184b_05905",
  "versions",
  "v_1785186305905_6bdb184b",
  "data_full.csv",
);

const HELOC_CONTEXT = {
  registeredRows: 6_275,
  developmentRows: 5_020,
  holdoutRows: 1_255,
  target: "bad_flag",
  eventValue: "1",
  nonEventValue: "0",
  deterministicTargetSource: "RiskPerformance",
  registeredSpecialValueCells: 15_324,
  specialValuePredictors: 22,
} as const;

function exactProjectStep(projectId: string, step: string): RegExp {
  const escaped = projectId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`/projects/${escaped}/${step}(?:[?#]|$)`);
}

async function expectExactStep(page: Page, projectId: string, step: string) {
  await expect(page).toHaveURL(exactProjectStep(projectId, step), {
    timeout: 90_000,
  });
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-project-context-status",
    "ready",
    { timeout: 90_000 },
  );
  await expect(page.getByTestId("project-context-gate")).toHaveCount(0, {
    timeout: 90_000,
  });
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
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

type CanonicalSpecialReviewFixture = {
  specialValueReviewId: string;
  detectionFingerprint: string;
  revision: number;
  detectedCount: number;
};

/**
 * Installs the fixture's exact HELOC special-value lineage in the disposable
 * SQLite authority. ExternalRiskEstimate=-9 remains a protected reserved
 * sentinel, but it is intentionally outside the 22-feature governed bureau
 * review contract. There is no product/test API for supplying that upstream
 * data-dictionary classification, so the acceptance harness records the
 * fixture-only detection revision directly in its isolated append-only audit
 * stream. The live store and the repository-local store are never addressed.
 */
function installCanonicalHelocSpecialReviewFixture(
  projectId: string,
): CanonicalSpecialReviewFixture {
  const outputRoot = process.env.ATLAS_PLAYWRIGHT_OUTPUT_ROOT;
  if (!outputRoot) {
    throw new Error("The isolated Playwright output authority is unavailable.");
  }
  const databasePath = path.resolve(
    outputRoot,
    "..",
    "persistence",
    "atlas_local.db",
  );
  if (!fs.existsSync(databasePath)) {
    throw new Error("The isolated persistence authority is unavailable.");
  }
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const script = String.raw`
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

from server.preprocessing.special_value_review_service import (
    detected_variables,
    detection_fingerprint,
)

database_path, project_id, expected_development_rows = sys.argv[1:4]
expected_development_rows = int(expected_development_rows)
connection = sqlite3.connect(database_path, timeout=30)
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA busy_timeout = 30000")
try:
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT * FROM special_value_reviews WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("The isolated exact-version special-value review is missing.")
    detection = json.loads(row["detection_json"])
    if (
        not detection.get("analysis_partition_id")
        or detection.get("target_analysis_scope") != "development_population"
        or int(detection.get("development_rows") or 0) != expected_development_rows
    ):
        raise RuntimeError("The isolated review is not bound to the exact Development Population.")
    external_risk = next(
        (
            item
            for item in detection.get("variables", [])
            if item.get("variable") == "ExternalRiskEstimate"
        ),
        None,
    )
    if external_risk is None or int(external_risk.get("special_value_count") or 0) != 357:
        raise RuntimeError("The copied HELOC sentinel fixture does not match its exact contract.")
    external_risk["likely_bureau"] = False
    external_risk["reasons"] = list(external_risk.get("reasons") or []) + [
        "Canonical HELOC metadata classifies -9 as a protected reserved sentinel outside the governed bureau review contract."
    ]
    detection["likely_variable_count"] = 22
    detection["variables_with_special_values"] = 22
    fingerprint = detection_fingerprint(detection)
    detected_count = len(detected_variables(detection))
    if detected_count != 22:
        raise RuntimeError(f"Expected 22 governed HELOC special-value predictors, found {detected_count}.")
    previous_fingerprint = str(row["detection_fingerprint"])
    next_revision = int(row["revision"]) + 1
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        UPDATE special_value_reviews
        SET detection_fingerprint = ?, detection_json = ?, decisions_json = '[]',
            reviewer_rationale = '', status = 'not_started', detected_count = ?,
            reviewed_count = 0, open_count = ?, blocks_confirmation = 1,
            blocks_continuation = 1, revision = ?, updated_at = ?,
            confirmed_by = NULL, confirmed_at = NULL
        WHERE special_value_review_id = ? AND revision = ?
        """,
        (
            fingerprint,
            json.dumps(detection, sort_keys=True, separators=(",", ":")),
            detected_count,
            detected_count,
            next_revision,
            now,
            row["special_value_review_id"],
            row["revision"],
        ),
    )
    if connection.total_changes != 1:
        raise RuntimeError("The isolated special-value fixture revision was stale.")
    connection.execute(
        """
        INSERT INTO special_value_review_events (
          special_value_review_event_id, special_value_review_id, project_id,
          dataset_id, dataset_version_id, revision, event_type,
          actor_user_id, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, 'detection_refreshed', ?, ?, ?)
        """,
        (
            "svre_fixture_" + uuid.uuid4().hex,
            row["special_value_review_id"],
            row["project_id"],
            row["dataset_id"],
            row["dataset_version_id"],
            next_revision,
            row["updated_by"],
            now,
            json.dumps(
                {
                    "fixture": "canonical_heloc_special_value_lineage",
                    "previous_detection_fingerprint": previous_fingerprint,
                    "detection_fingerprint": fingerprint,
                    "governed_special_value_predictor_count": detected_count,
                    "protected_reserved_sentinel": "ExternalRiskEstimate=-9",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )
    connection.commit()
    print(
        json.dumps(
            {
                "specialValueReviewId": row["special_value_review_id"],
                "detectionFingerprint": fingerprint,
                "revision": next_revision,
                "detectedCount": detected_count,
            }
        )
    )
finally:
    connection.close()
`;
  const output = execFileSync(
    python,
    [
      "-c",
      script,
      databasePath,
      projectId,
      String(HELOC_CONTEXT.developmentRows),
    ],
    {
      cwd: process.cwd(),
      encoding: "utf-8",
      timeout: 60_000,
    },
  );
  return JSON.parse(output.trim()) as CanonicalSpecialReviewFixture;
}

async function boundedShot(
  locator: Locator,
  testInfo: TestInfo,
  label: string,
) {
  await locator.scrollIntoViewIfNeeded();
  const file = testInfo.outputPath(`${label}.png`);
  await locator.screenshot({ path: file });
  await testInfo.attach(label, { path: file, contentType: "image/png" });
}

async function responseJson(response: Response): Promise<JsonRecord> {
  expect(response.status()).toBe(200);
  return (await response.json()) as JsonRecord;
}

test.describe("Focused isolated analytical-scope and preprocessing integrity", () => {
  test("reconciles HELOC populations and proves pre-lock preparation isolation", async ({ page }, testInfo) => {
    test.setTimeout(18 * 60_000);

    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    const apiTrace: Array<{ method: string; path: string; status: number }> = [];
    const edaPayloads: Record<string, JsonRecord> = {};
    let latestOutlierSummary: JsonRecord | null = null;
    let latestOutlierApplication: JsonRecord | null = null;
    let latestMissingSummary: JsonRecord | null = null;
    let targetQualityText = "";
    let outlierScopeText = "";
    let missingZeroStateText = "";
    let duplicateRecoveryText = "";
    let canonicalSpecialReviewFixture: CanonicalSpecialReviewFixture | null = null;
    let latestBureauDetectionPayload: JsonRecord | null = null;

    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("response", (response) => {
      void (async () => {
        const url = new URL(response.url());
        if (!url.pathname.startsWith("/api/")) return;
        apiTrace.push({
          method: response.request().method(),
          path: url.pathname,
          status: response.status(),
        });
        if (response.status() !== 200) return;
        const sectionMatch = url.pathname.match(
          /\/api\/eda\/workspace\/(overview|target|predictors|relationships|stability|findings)$/,
        );
        try {
          if (
            response.request().method() === "POST" &&
            url.pathname.endsWith("/api/data/bureau-detection")
          ) {
            latestBureauDetectionPayload =
              (await response.json()) as JsonRecord;
          } else if (sectionMatch) {
            edaPayloads[sectionMatch[1]] = (await response.json()) as JsonRecord;
          } else if (url.pathname.endsWith("/api/outliers/summary")) {
            latestOutlierSummary = (await response.json()) as JsonRecord;
          } else if (url.pathname.endsWith("/api/missing/summary")) {
            latestMissingSummary = (await response.json()) as JsonRecord;
          }
        } catch {
          // The status/path trace remains usable if a response body is not JSON.
        }
      })();
    });

    expect(process.env.ATLAS_E2E_RUN_ID).toMatch(
      /^atlas-hrt-[0-9]{8}-[0-9]{6}-[a-f0-9]{10}$/i,
    );
    const backendBaseUrl = process.env.ATLAS_E2E_BACKEND_URL?.replace(/\/$/, "");
    expect(backendBaseUrl).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
    const frontendBaseUrl = process.env.ATLAS_E2E_BASE_URL?.replace(/\/$/, "");
    expect(frontendBaseUrl).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);

    expect(fs.existsSync(HELOC_SOURCE), "the repository acceptance fixture must exist").toBe(true);
    const fixturePath = testInfo.outputPath("heloc-analytical-scope-fixture.csv");
    fs.copyFileSync(HELOC_SOURCE, fixturePath);
    const fixtureRows = fs.readFileSync(fixturePath, "utf8").trimEnd().split(/\r?\n/).length - 1;
    expect(fixtureRows).toBe(HELOC_CONTEXT.registeredRows);

    const user = makeTestUser("scope-preprocessing-v2");
    await registerUser(page, user);
    await createPredictiveModelingProject(page, {
      name: `ATLAS HELOC Scope Integrity ${process.env.ATLAS_E2E_RUN_ID}`,
      modelId: `scope-${process.env.ATLAS_E2E_RUN_ID!.slice(-10)}`,
    });
    const projectMatch = new URL(page.url()).pathname.match(
      /^\/projects\/([^/]+)\/step00$/,
    );
    expect(projectMatch).not.toBeNull();
    const projectId = projectMatch![1];
    await expectExactStep(page, projectId, "step00");

    await fillProjectContextNarrative(page, {
      businessObjective:
        "Assess consumer credit risk for governed analyst review while preserving independent final validation.",
      intendedModelUse:
        "Senior credit-risk analysts use the score as decision support; policy owners retain final authority and review all overrides.",
      targetDefinition:
        "Whether an account exhibits the governed bad-credit performance outcome represented by bad_flag.",
      populationDefinition:
        "The registered HELOC analytical population subject to the governed predictor authorization and sealed analysis partition.",
      observationWindow:
        "Bureau attributes available at the governed application observation point, before outcome realization.",
      performanceWindow:
        "The subsequent governed performance period used to establish the binary credit-risk outcome.",
    });
    await page.getByRole("button", { name: "Generate Modeling Mission Summary" }).click();
    await expect(page.getByLabel("Editable AI Modeling Mission Summary draft")).not.toHaveValue("");
    await page.getByRole("button", { name: "Accept Summary" }).click();
    await expect(page.getByTestId("accepted-modeling-mission-summary")).toBeVisible();
    await page.locator('[data-step-next-button="true"]').click();
    await expectExactStep(page, projectId, "step01");

    const [uploadResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/data/upload_csv"),
        { timeout: 120_000 },
      ),
      page
        .getByTestId("source-command-section")
        .locator('input[type="file"][accept*=".csv"]')
        .setInputFiles(fixturePath),
    ]);
    const upload = await responseJson(uploadResponse);
    const datasetId = String(upload.dataset_id ?? upload.datasetId ?? "");
    const datasetVersionId = String(
      upload.dataset_version_id ?? upload.versionId ?? "",
    );
    expect(datasetId).not.toBe("");
    expect(datasetVersionId).not.toBe("");
    expect(Number(upload.row_count ?? upload.rows)).toBe(HELOC_CONTEXT.registeredRows);

    const targetSelect = page.getByTestId("target-column-select");
    await expect(
      targetSelect.locator(`option[value="${HELOC_CONTEXT.target}"]`),
    ).toHaveCount(1, { timeout: 90_000 });
    await targetSelect.selectOption(HELOC_CONTEXT.target);
    await page.getByLabel("Event / Positive Value").fill(HELOC_CONTEXT.eventValue);
    await page
      .getByLabel("Non-event / Negative Value")
      .fill(HELOC_CONTEXT.nonEventValue);
    const confirmTarget = page.getByTestId("confirm-initial-target-contract");
    if (await confirmTarget.isVisible()) await confirmTarget.click();

    await expect
      .poll(
        async () => {
          const result = await browserGetJson<JsonRecord>(
            page,
            `${backendBaseUrl}/api/data/reproducibility-context?project_id=${encodeURIComponent(projectId)}`,
          );
          const context = result.payload;
          return (
            result.status === 200 &&
            context?.identity?.dataset_id === datasetId &&
            context?.identity?.dataset_version_id === datasetVersionId &&
            context?.target_contract?.target === HELOC_CONTEXT.target &&
            Array.isArray(
              context?.predictor_authorization?.deterministic_source_exclusions,
            ) &&
            context.predictor_authorization.deterministic_source_exclusions.includes(
              HELOC_CONTEXT.deterministicTargetSource,
            ) &&
            !context?.predictor_authorization?.authorized_predictors?.includes(
              HELOC_CONTEXT.deterministicTargetSource,
            )
          );
        },
        { timeout: 120_000 },
      )
      .toBe(true);

    await expect(page.getByTestId("special-value-decision-workspace")).toBeVisible({
      timeout: 120_000,
    });
    const ratio = page.getByTestId("analysis-partition-holdout-ratio");
    await expect(ratio).toBeVisible();
    await expect(ratio).toHaveValue("0.2");
    const partitionPreview = page.getByTestId("analysis-partition-preview");
    await expect(partitionPreview).toContainText("Backend preview", {
      timeout: 120_000,
    });
    await expect(partitionPreview).toContainText(
      HELOC_CONTEXT.developmentRows.toLocaleString(),
      { timeout: 120_000 },
    );
    await expect(partitionPreview).toContainText(
      HELOC_CONTEXT.holdoutRows.toLocaleString(),
      { timeout: 120_000 },
    );

    await expect(page.getByTestId("create-analysis-partition")).toBeEnabled({
      timeout: 60_000,
    });
    await page.getByTestId("create-analysis-partition").click();
    const documentPartition = page.getByTestId(
      "complete-analysis-partition-documentation",
    );
    const partitionSummary = page.getByTestId("current-analysis-partition-summary");
    await expect
      .poll(
        async () =>
          (await documentPartition.isVisible()) || (await partitionSummary.isVisible()),
        { timeout: 120_000 },
      )
      .toBe(true);
    if (await documentPartition.isVisible()) {
      await expect(documentPartition).toBeEnabled();
      await documentPartition.click();
    }
    await expect(partitionSummary).toBeVisible({ timeout: 120_000 });

    const specialScope = page.getByTestId("special-value-analytical-scope");
    await expect(specialScope).toHaveAttribute(
      "data-target-analysis-scope",
      "development_population",
      { timeout: 120_000 },
    );
    await expect
      .poll(
        () =>
          latestBureauDetectionPayload?.analysis_partition_id &&
          latestBureauDetectionPayload?.target_analysis_scope ===
            "development_population" &&
          Number(latestBureauDetectionPayload?.development_rows) ===
            HELOC_CONTEXT.developmentRows,
        { timeout: 120_000 },
      )
      .toBe(true);

    // Preserve the exact backend result and overlay only the fixture's
    // upstream data-dictionary classification before remounting the workspace.
    const canonicalDetectionPayload = JSON.parse(
      JSON.stringify(latestBureauDetectionPayload),
    ) as JsonRecord;
    canonicalSpecialReviewFixture =
      installCanonicalHelocSpecialReviewFixture(projectId);
    canonicalDetectionPayload.variables = (
      canonicalDetectionPayload.variables ?? []
    ).map((row: JsonRecord) =>
      row.variable === "ExternalRiskEstimate"
        ? {
            ...row,
            likely_bureau: false,
            reasons: [
              ...(row.reasons ?? []),
              "Canonical HELOC metadata classifies -9 as a protected reserved sentinel outside the governed bureau review contract.",
            ],
          }
        : row,
    );
    canonicalDetectionPayload.likely_variable_count =
      HELOC_CONTEXT.specialValuePredictors;
    canonicalDetectionPayload.variables_with_special_values =
      HELOC_CONTEXT.specialValuePredictors;
    canonicalDetectionPayload.special_value_review = {
      ...(canonicalDetectionPayload.special_value_review ?? {}),
      detection_fingerprint:
        canonicalSpecialReviewFixture.detectionFingerprint,
      revision: canonicalSpecialReviewFixture.revision,
      status: "not_started",
      detected_count: canonicalSpecialReviewFixture.detectedCount,
      reviewed_count: 0,
      open_count: canonicalSpecialReviewFixture.detectedCount,
      open_items: (canonicalDetectionPayload.variables ?? [])
        .filter(
          (row: JsonRecord) =>
            row.likely_bureau && Number(row.special_value_count ?? 0) > 0,
        )
        .map((row: JsonRecord) => String(row.variable))
        .sort(),
      blocks_confirmation: true,
      blocks_continuation: true,
      confirmation_allowed: false,
      variable_decisions: [],
    };
    const bureauDetectionRoute = "**/api/data/bureau-detection";
    await page.route(bureauDetectionRoute, async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        headers: {
          "access-control-allow-origin": String(frontendBaseUrl),
          "access-control-allow-credentials": "true",
          "content-type": "application/json",
        },
        body: JSON.stringify(canonicalDetectionPayload),
      });
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await expectExactStep(page, projectId, "step01");
    await expect(partitionSummary).toBeVisible({ timeout: 120_000 });
    await expect(specialScope).toHaveAttribute(
      "data-target-analysis-scope",
      "development_population",
      { timeout: 120_000 },
    );
    await expect(page.getByTestId("special-value-review-summary")).toContainText(
      /Bureau variables detected\s*22/i,
    );
    await page
      .getByTestId("special-value-bulk-treatment")
      .selectOption("convert_to_category");
    const applyBulkSpecial = page.getByTestId("apply-special-value-bulk-treatment");
    if (await applyBulkSpecial.isVisible()) await applyBulkSpecial.click();
    const specialWorkspace = page.getByTestId("special-value-decision-workspace");
    await specialWorkspace
      .getByRole("button", { name: "Save Draft Review", exact: true })
      .click();
    const confirmSpecial = specialWorkspace.getByRole("button", {
      name: "Confirm Special-Value Treatment",
      exact: true,
    });
    await expect(confirmSpecial).toBeEnabled({ timeout: 90_000 });
    await confirmSpecial.click();
    await expect(page.getByTestId("special-value-confirmed-revision")).toBeVisible({
      timeout: 120_000,
    });
    await page.unroute(bureauDetectionRoute);

    await expect(partitionSummary).toContainText("Registered Population");
    await expect(partitionSummary).toContainText(
      HELOC_CONTEXT.registeredRows.toLocaleString(),
    );
    await expect(partitionSummary).toContainText("Development Population");
    await expect(partitionSummary).toContainText(
      HELOC_CONTEXT.developmentRows.toLocaleString(),
    );
    await expect(partitionSummary).toContainText("Sealed Final Holdout");
    await expect(partitionSummary).toContainText(
      HELOC_CONTEXT.holdoutRows.toLocaleString(),
    );
    await expect(
      page.getByText(
        `Development Population: ${HELOC_CONTEXT.registeredRows.toLocaleString()} Rows`,
        { exact: true },
      ),
    ).toHaveCount(0);
    await boundedShot(partitionSummary, testInfo, "01-data-acquisition-populations");

    const dataQualitySection = page
      .getByRole("heading", { name: "Data Quality", exact: true })
      .locator("xpath=ancestor::section[1]");
    await expect.soft(dataQualitySection).toContainText(/redundant rows beyond/i, {
      timeout: 90_000,
    });
    await expect.soft(dataQualitySection).toContainText(/participant rows/i);
    await expect.soft(dataQualitySection).toContainText(/exact groups/i);
    await expect.soft(dataQualitySection).toContainText(/Registered Population/i);
    await expect.soft(dataQualitySection).toContainText(/comparison columns/i);
    await boundedShot(dataQualitySection, testInfo, "02-data-acquisition-duplicates");

    const nextFromAcquisition = page.locator('[data-step-next-button="true"]');
    await expect(nextFromAcquisition).toBeEnabled({ timeout: 180_000 });
    const overviewResponsePromise = page.waitForResponse(
      (response) =>
        response.status() === 200 &&
        response.url().includes("/api/eda/workspace/overview"),
      { timeout: 180_000 },
    );
    await nextFromAcquisition.click();
    await expectExactStep(page, projectId, "step02");
    await overviewResponsePromise;
    await expect(page.getByTestId("eda-overview-launch-surface")).toBeVisible({
      timeout: 180_000,
    });

    const expectedScopes = [
      ["overview", "registered_structural_population", HELOC_CONTEXT.registeredRows],
      ["target", "development_population", HELOC_CONTEXT.developmentRows],
      ["predictors", "development_population", HELOC_CONTEXT.developmentRows],
      ["relationships", "development_population", HELOC_CONTEXT.developmentRows],
      ["stability", "development_population", HELOC_CONTEXT.developmentRows],
      ["findings", "development_population", HELOC_CONTEXT.developmentRows],
    ] as const;
    const observedScopes: Array<{
      tab: string;
      scope: string | null;
      text: string;
      responseScope: unknown;
      responseRows: unknown;
    }> = [];
    const edaRail = page.getByTestId("eda-analysis-tab-rail");
    for (const [tab, expectedScope, expectedRows] of expectedScopes) {
      if (tab !== "overview") {
        await edaRail.locator(`[data-tab-id="${tab}"]`).click();
      }
      await expect(edaRail).toHaveAttribute("data-active-tab", tab, {
        timeout: 120_000,
      });
      await expect(page.locator(`#eda-tabpanel-${tab}`)).toBeVisible({
        timeout: 120_000,
      });
      await expect
        .poll(() => Boolean(edaPayloads[tab]), { timeout: 180_000 })
        .toBe(true);
      const scopeBadge = edaRail.locator(".atlas-data-scope");
      await expect.soft(scopeBadge).toHaveAttribute("data-scope", expectedScope);
      await expect.soft(scopeBadge).toContainText(expectedRows.toLocaleString());
      await expect.soft(scopeBadge).not.toContainText(
        tab === "overview"
          ? "Development Population"
          : HELOC_CONTEXT.registeredRows.toLocaleString(),
      );
      observedScopes.push({
        tab,
        scope: await scopeBadge.getAttribute("data-scope"),
        text: (await scopeBadge.innerText()).trim(),
        responseScope: edaPayloads[tab]?.scope,
        responseRows: edaPayloads[tab]?.row_count,
      });
      expect.soft(edaPayloads[tab]?.scope).toBe(expectedScope);
      expect.soft(edaPayloads[tab]?.row_count).toBe(expectedRows);
      expect.soft(
        edaPayloads[tab]?.population_contract?.counts?.registered_population_rows,
      ).toBe(HELOC_CONTEXT.registeredRows);
      expect.soft(
        edaPayloads[tab]?.population_contract?.counts?.development_population_rows,
      ).toBe(HELOC_CONTEXT.developmentRows);
      expect.soft(
        edaPayloads[tab]?.population_contract?.counts?.sealed_final_holdout_rows,
      ).toBe(HELOC_CONTEXT.holdoutRows);
    }
    await expect(
      page.getByText(
        `Development Population: ${HELOC_CONTEXT.registeredRows.toLocaleString()} Rows`,
        { exact: true },
      ),
    ).toHaveCount(0);

    const overviewDuplicates =
      edaPayloads.overview?.population_contract?.duplicates;
    expect.soft(overviewDuplicates?.registered_predictor_frame).toMatchObject({
      scope: "registered_structural_population",
      duplicate_group_count: 2,
      duplicate_participant_rows: 354,
      redundant_duplicate_rows: 352,
      keep_semantics: "first",
      target_included: false,
    });
    expect.soft(overviewDuplicates?.development_analysis_frame).toMatchObject({
      scope: "development_population",
      duplicate_group_count: 3,
      duplicate_participant_rows: 282,
      redundant_duplicate_rows: 279,
      keep_semantics: "first",
      target_included: true,
    });

    await edaRail.locator('[data-tab-id="target"]').click();
    const targetLineage = page.getByTestId("target-governed-lineage");
    await expect(targetLineage).toBeVisible({ timeout: 120_000 });
    await expect(targetLineage).toHaveAttribute(
      "aria-label",
      new RegExp(`${HELOC_CONTEXT.deterministicTargetSource}.*excluded from predictors`, "i"),
    );
    const targetQuality = page.getByTestId("target-quality-leakage");
    targetQualityText = (await targetQuality.innerText()).trim();
    await expect.soft(targetQuality).toContainText(
      /known deterministic target source.*excluded upstream/i,
    );
    await expect.soft(targetQuality).toContainText(
      /no additional.*candidate.*authorized predictors/i,
    );
    await boundedShot(
      page.getByTestId("target-intelligence-workspace"),
      testInfo,
      "03-target-lineage-and-leakage",
    );

    await edaRail.locator('[data-tab-id="findings"]').click();
    await expect(page.getByTestId("eda-findings-decision-workspace")).toBeVisible({
      timeout: 180_000,
    });
    await page.locator('button[data-parent-family="exact_duplicate_rows"]').click();
    await expect(page.getByTestId("eda-duplicate-parent-resolution")).toHaveCount(1);
    const legacyDuplicate = page.getByTestId("eda-duplicate-decision");
    await expect(legacyDuplicate).toHaveAttribute(
      "data-authority",
      "read-only-legacy-history",
    );
    await expect(legacyDuplicate.locator("select, textarea, input, button")).toHaveCount(0);

    const outlierSummaryPromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith("/api/outliers/summary"),
      { timeout: 180_000 },
    );
    await page.goto(`/projects/${projectId}/step03`);
    await expectExactStep(page, projectId, "step03");
    const outlierSummary = await responseJson(await outlierSummaryPromise);
    latestOutlierSummary = outlierSummary;
    await expect(page.getByTestId("outlier-feature-summary-table")).toBeVisible({
      timeout: 180_000,
    });
    expect.soft(outlierSummary.preprocessing_contract_version).toBe(2);
    expect.soft(outlierSummary.scope).toBe("development_population");
    expect.soft(outlierSummary.row_count).toBe(HELOC_CONTEXT.developmentRows);
    expect.soft(outlierSummary.registered_population_rows).toBe(
      HELOC_CONTEXT.registeredRows,
    );
    expect.soft(outlierSummary.final_holdout_parameter_influence).toBe(false);
    expect.soft(outlierSummary.final_holdout_target_accessed).toBe(false);
    expect.soft(outlierSummary.final_holdout_used_for_selection).toBe(false);
    expect.soft(outlierSummary.final_holdout_transformed_or_materialized_prelock).toBe(
      false,
    );
    const outlierTreatmentSection = page
      .getByRole("heading", {
        name: "All-Feature Outlier Summary and Treatment Table",
        exact: true,
      })
      .locator("xpath=ancestor::section[1]");
    await expect.soft(outlierTreatmentSection.locator(".atlas-data-scope")).toContainText(
      `Development Population: ${HELOC_CONTEXT.developmentRows.toLocaleString()} Rows`,
    );
    outlierScopeText = (
      await outlierTreatmentSection.locator(".atlas-data-scope").innerText()
    ).trim();
    await expect(
      page.getByText(
        `Development Population: ${HELOC_CONTEXT.registeredRows.toLocaleString()} Rows`,
        { exact: true },
      ),
    ).toHaveCount(0);

    await page.getByTestId("outlier-global-treatment").selectOption("NONE");
    const [outlierApplyResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().endsWith("/api/outliers/apply"),
        { timeout: 180_000 },
      ),
      page.getByTestId("outlier-apply-treatments").click(),
    ]);
    const outlierApply = await responseJson(outlierApplyResponse);
    const outlierApplication = outlierApply.application;
    latestOutlierApplication = outlierApplication;
    expect.soft(outlierApplication.preprocessing_contract_version).toBe(2);
    expect.soft(outlierApplication.fit_scope).toBe("development_preview");
    expect.soft(outlierApplication.development_preview_fit?.fit_population_rows).toBe(
      HELOC_CONTEXT.developmentRows,
    );
    expect.soft(outlierApplication.backend_materialization).toBe(false);
    expect.soft(outlierApplication.processed_frame_materialized).toBe(false);
    expect.soft(outlierApplication.sealed_holdout_transformed).toBe(false);
    expect.soft(outlierApplication.final_holdout_parameter_influence).toBe(false);
    expect.soft(outlierApplication.development_preview?.counts).toEqual(
      expect.objectContaining({
        flagged_cell_count: expect.any(Number),
        affected_row_count: expect.any(Number),
        affected_row_rate: expect.any(Number),
        affected_predictor_count: expect.any(Number),
      }),
    );
    await expect.soft(page.getByText(/Flagged cells/i).first()).toBeVisible();
    await expect.soft(page.getByText(/Affected rows/i).first()).toBeVisible();
    await expect.soft(page.getByText(/full-data ordinary values flagged/i)).toHaveCount(0);
    await boundedShot(
      page.getByTestId("outlier-feature-summary-table"),
      testInfo,
      "04-outlier-development-fit-and-count-units",
    );

    const missingSummaryPromise = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        response.url().includes("/api/missing/summary"),
      { timeout: 180_000 },
    );
    await page.goto(`/projects/${projectId}/step04`);
    await expectExactStep(page, projectId, "step04");
    const missingSummary = await responseJson(await missingSummaryPromise);
    latestMissingSummary = missingSummary;
    await expect(page.getByTestId("missing-values-zero-state")).toBeVisible({
      timeout: 180_000,
    });
    expect.soft(missingSummary.preprocessing_contract_version).toBe(2);
    expect.soft(missingSummary.scope).toBe("development_population");
    expect.soft(missingSummary.row_count).toBe(HELOC_CONTEXT.developmentRows);
    expect.soft(missingSummary.registered_population_rows).toBe(
      HELOC_CONTEXT.registeredRows,
    );
    expect.soft(missingSummary.counts).toMatchObject({
      flagged_cell_count: 0,
      affected_row_count: 0,
      affected_predictor_count: 0,
    });
    const registeredSpecialValueCells = Object.values<JsonRecord>(
      missingSummary.stats ?? {},
    ).reduce(
      (total, row) =>
        total + Number(row?.registered_structural?.special_value_count ?? 0),
      0,
    );
    const registeredSpecialValuePredictors = Object.values<JsonRecord>(
      missingSummary.stats ?? {},
    ).filter(
      (row) => Number(row?.registered_structural?.special_value_count ?? 0) > 0,
    ).length;
    expect.soft(registeredSpecialValueCells).toBe(
      HELOC_CONTEXT.registeredSpecialValueCells,
    );
    expect.soft(registeredSpecialValuePredictors).toBe(
      HELOC_CONTEXT.specialValuePredictors,
    );
    await expect(page.getByTestId("missing-global-strategy")).toHaveValue("None");
    await expect(page.getByTestId("missing-values-zero-state")).toContainText(
      /Recommended strategy:\s*None/i,
    );
    await expect(page.getByTestId("missing-values-zero-state")).toContainText(
      /without creating a new backend modeling frame/i,
    );
    await expect.soft(page.locator("main")).toContainText(
      /Governed special-value cells\s*15,324\s*across 22 predictors/i,
    );
    await expect(page.getByText("No processed frame will be created", { exact: true })).toBeVisible();
    missingZeroStateText = (
      await page.getByTestId("missing-values-zero-state").innerText()
    ).trim();

    const validateNoTreatment = page.getByRole("button", {
      name: "Validate no treatment",
      exact: true,
    });
    const [missingValidateResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().endsWith("/api/missing/validate"),
        { timeout: 180_000 },
      ),
      validateNoTreatment.click(),
    ]);
    const missingValidate = await responseJson(missingValidateResponse);
    expect.soft(missingValidate.validation?.approved_policy).toMatchObject({
      preprocessing_contract_version: 2,
      active_treatment: "NONE",
      materialization_required: false,
      processed_frame_created: false,
      true_null_cell_count: 0,
    });
    expect.soft(missingValidate.validation?.processed_frame_materialized).toBe(false);
    expect.soft(missingValidate.validation?.sealed_holdout_transformed).toBe(false);
    expect.soft(missingValidate.validation?.final_holdout_parameter_influence).toBe(
      false,
    );
    await boundedShot(
      page.locator("main").getByTestId("missing-values-zero-state").locator("xpath=ancestor::main[1]"),
      testInfo,
      "05-missing-zero-null-none-no-frame",
    );

    const reloadSummaryPromise = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        response.url().includes("/api/missing/summary"),
      { timeout: 180_000 },
    );
    await page.reload();
    await expectExactStep(page, projectId, "step04");
    const reloadedMissing = await responseJson(await reloadSummaryPromise);
    latestMissingSummary = reloadedMissing;
    expect.soft(reloadedMissing.preprocessing_contract_version).toBe(2);
    expect.soft(reloadedMissing.legacy_artifact_status).toBeNull();
    expect.soft(reloadedMissing.application).toBeNull();
    expect.soft(reloadedMissing.validation?.approved_policy?.active_treatment).toBe(
      "NONE",
    );
    expect.soft(reloadedMissing.validation?.processed_frame_materialized).toBe(false);
    await expect(page.getByTestId("missing-values-zero-state")).toBeVisible({
      timeout: 180_000,
    });

    await page.goto(`/projects/${projectId}/step02`);
    await expectExactStep(page, projectId, "step02");
    const findingsTab = page
      .getByTestId("eda-analysis-tab-rail")
      .locator('[data-tab-id="findings"]');
    await findingsTab.click();
    await expect(page.getByTestId("eda-findings-decision-workspace")).toBeVisible({
      timeout: 180_000,
    });
    await page.locator('button[data-parent-family="exact_duplicate_rows"]').click();
    const duplicateAuthority = page.getByTestId("eda-duplicate-parent-resolution");
    await expect(duplicateAuthority).toHaveCount(1);
    await duplicateAuthority.selectOption("exclude_upstream_and_repartition");
    const duplicateDetail = page.getByTestId("eda-parent-finding-detail");
    await expect(duplicateDetail).toContainText(
      /Exclusion invalidates the current population and remains blocked until upstream registration and partition revision are complete/i,
    );
    await expect(duplicateDetail).toContainText(
      /cannot remove rows.*change the split.*navigate automatically/i,
    );
    await expect(page.getByTestId("eda-findings-completion-eligibility")).toContainText(
      /completion blocker/i,
    );
    await expect(page.getByTestId("eda-duplicate-decision")).toHaveAttribute(
      "data-authority",
      "read-only-legacy-history",
    );
    duplicateRecoveryText = (await duplicateDetail.innerText()).trim();
    await boundedShot(
      duplicateDetail,
      testInfo,
      "06-findings-single-duplicate-authority-repartition",
    );

    const safeEdaEvidence = Object.fromEntries(
      Object.entries(edaPayloads).map(([section, payload]) => [
        section,
        {
          scope: payload.scope,
          row_count: payload.row_count,
          population_counts: payload.population_contract?.counts,
          holdout_truth: payload.population_contract?.holdout_truth,
          duplicates: payload.population_contract?.duplicates,
          target_source_excluded: payload.target_source_excluded,
          completion_contract: payload.completion_contract,
        },
      ]),
    );
    await testInfo.attach("focused-browser-contract-evidence", {
      body: Buffer.from(
        JSON.stringify(
          {
            project_id: projectId,
            dataset_id: datasetId,
            dataset_version_id: datasetVersionId,
            canonical_special_value_fixture: canonicalSpecialReviewFixture,
            observed_eda_scopes: observedScopes,
            eda: safeEdaEvidence,
            outliers: latestOutlierSummary
              ? {
                  scope: latestOutlierSummary.scope,
                  row_count: latestOutlierSummary.row_count,
                  registered_population_rows:
                    latestOutlierSummary.registered_population_rows,
                  preprocessing_contract_version:
                    latestOutlierSummary.preprocessing_contract_version,
                  holdout_truth: latestOutlierSummary.population_contract?.holdout_truth,
                  legacy_artifact_status:
                    latestOutlierSummary.legacy_artifact_status,
                  displayed_scope: outlierScopeText,
                  application: latestOutlierApplication
                    ? {
                        preprocessing_contract_version:
                          latestOutlierApplication.preprocessing_contract_version,
                        fit_scope: latestOutlierApplication.fit_scope,
                        fit_population_rows:
                          latestOutlierApplication.development_preview_fit
                            ?.fit_population_rows,
                        development_preview_fit:
                          latestOutlierApplication.development_preview_fit,
                        application_scope:
                          latestOutlierApplication.application_scope,
                        backend_materialization:
                          latestOutlierApplication.backend_materialization,
                        processed_frame_materialized:
                          latestOutlierApplication.processed_frame_materialized,
                        sealed_holdout_transformed:
                          latestOutlierApplication.sealed_holdout_transformed,
                        final_holdout_target_accessed:
                          latestOutlierApplication.final_holdout_target_accessed,
                        final_holdout_parameter_influence:
                          latestOutlierApplication.final_holdout_parameter_influence,
                        final_holdout_used_for_selection:
                          latestOutlierApplication.final_holdout_used_for_selection,
                        final_holdout_transformed_or_materialized_prelock:
                          latestOutlierApplication.final_holdout_transformed_or_materialized_prelock,
                        development_preview_counts:
                          latestOutlierApplication.development_preview?.counts,
                      }
                    : null,
                }
              : null,
            missing: latestMissingSummary
              ? {
                  scope: latestMissingSummary.scope,
                  row_count: latestMissingSummary.row_count,
                  registered_population_rows:
                    latestMissingSummary.registered_population_rows,
                  counts: latestMissingSummary.counts,
                  preprocessing_contract_version:
                    latestMissingSummary.preprocessing_contract_version,
                  validation: latestMissingSummary.validation,
                  legacy_artifact_status:
                    latestMissingSummary.legacy_artifact_status,
                  registered_special_value_cells: registeredSpecialValueCells,
                  registered_special_value_predictors:
                    registeredSpecialValuePredictors,
                  application: latestMissingSummary.application,
                  zero_state_text: missingZeroStateText,
                }
              : null,
            target_quality_text: targetQualityText,
            duplicate_recovery_text: duplicateRecoveryText,
            api_trace: apiTrace.slice(-400),
            console_errors: consoleErrors.slice(-50),
            page_errors: pageErrors,
          },
          null,
          2,
        ),
      ),
      contentType: "application/json",
    });

    expect.soft(pageErrors).toEqual([]);
    expect.soft(consoleErrors.filter((message) => /uncaught|typeerror/i.test(message))).toEqual([]);
  });
});
