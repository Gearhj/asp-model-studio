import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");
const [cockpit, shell, outliers, missing, api] = await Promise.all([
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/TreatmentStudioShell.tsx"),
  read("src/sports/cockpit/ProjectBoundOutlierStudio.tsx"),
  read("src/sports/cockpit/ProjectBoundMissingStudio.tsx"),
  read("src/sports/cockpit/projectTreatmentApi.ts"),
]);

function includesAll(source, values, label) {
  for (const value of values)
    assert.ok(source.includes(value), `${label} missing: ${value}`);
}

test("project-bound preparation and downstream steps use governed workflows while only segmentation remains held closed", () => {
  includesAll(
    cockpit,
    ["ProjectBoundOutlierStudio", "ProjectBoundMissingStudio", "ProjectBoundFeatureEngineering", "ProjectBoundSplitBalance"],
    "project-bound treatment routing",
  );
  assert.doesNotMatch(
    cockpit,
    /ProjectBoundLaterStepGate state=\{c\.currentGoldReview\} stepLabel="Outliers"/,
  );
  assert.doesNotMatch(
    cockpit,
    /ProjectBoundLaterStepGate state=\{c\.currentGoldReview\} stepLabel="Missing Values"/,
  );
  assert.doesNotMatch(
    cockpit,
    /ProjectBoundLaterStepGate state=\{c\.currentGoldReview\} stepLabel="Feature Engineering"/,
  );
  assert.doesNotMatch(
    cockpit,
    /ProjectBoundLaterStepGate state=\{c\.currentGoldReview\} stepLabel="Temporal Split"/,
  );
  assert.ok(cockpit.includes('stepLabel="Player Segmentation"'));
  assert.ok(cockpit.includes("ProjectBoundCandidateEvaluation"));
  assert.ok(cockpit.includes("ProjectBoundModelRefinement"));
  includesAll(
    cockpit,
    ["ProjectBoundCalibration", "ProjectBoundGameEvaluation", "ProjectBoundChampionDecision", "ProjectBoundRegistryHandoff"],
    "project-bound downstream routing",
  );
});

test("the shared Focus Mode shell is honest before evaluation and exposes authority-safe controls", () => {
  includesAll(
    shell,
    [
      "ANALYSIS NOT YET RUN",
      "unevaluated count is represented as zero.",
      "Unavailable.",
      "NOT EVALUATED",
      "NO TREATMENT ADOPTED",
      "Development-only table",
      "Final OOT is not filterable",
      'max="2026-08-13"',
      "Search treatment variables",
      "Treatment feature family",
      "Treatment core contextual scope",
      "Treatment data type",
      "Treatment severity",
      "Inspect excluded / advanced fields",
      "Save draft",
      "Compare to saved policy",
      "Version history",
      "Adopt for model development",
      "DESCRIPTIVE PREVIEW — FOLD-LOCAL VALUES WILL DIFFER",
      "No source / Gold mutation",
      "stage3-treatment-authority-strip",
    ],
    "shared treatment shell",
  );
});

test("outlier studio implements the governed method, treatment, table, and before-after contracts", () => {
  for (const method of [
    "IQR_1_5",
    "IQR_3_0",
    "P95_UPPER",
    "P99_UPPER",
    "P05_P95",
    "P01_P99",
    "DOMAIN_BOUNDS",
  ])
    assert.ok(
      outliers.includes(`"${method}"`),
      `missing outlier detector ${method}`,
    );
  for (const method of [
    "RETAIN",
    "FLAG_ONLY",
    "CAP_IQR",
    "WINSORIZE",
    "CAP_P95",
    "CAP_P99",
    "SET_MISSING",
    "EXCLUDE_ROW",
  ])
    assert.ok(
      outliers.includes(`"${method}"`),
      `missing outlier treatment ${method}`,
    );
  const columns = [
    "NUMBER OF OUTLIERS",
    "VARIABLE",
    "OUTLIER %",
    "LOWER-TAIL COUNT",
    "UPPER-TAIL COUNT",
    "DATA TYPE",
    "FEATURE FAMILY",
    "DEVELOPMENT NONMISSING N",
    "MISSING N",
    "LOWER THRESHOLD",
    "UPPER THRESHOLD",
    "MIN",
    "Q1",
    "MEDIAN",
    "Q3",
    "MAX",
    "MEAN",
    "STANDARD DEVIATION",
    "SELECTED DETECTION METHOD",
    "SELECTED TREATMENT",
    "TREATMENT VALUE / BOUNDS",
    "AFFECTED GAMES",
    "AFFECTED PLAYERS",
    "STATUS",
    "VIEW DETAILS",
  ];
  let cursor = -1;
  for (const column of columns) {
    const next = outliers.indexOf(`"${column}"`, cursor + 1);
    assert.ok(next > cursor, `outlier column missing/out of order: ${column}`);
    cursor = next;
  }
  includesAll(
    outliers,
    [
      'field: "numberOfOutliers"',
      'direction: "desc"',
      "eligibleDetectionMethods",
      "eligibleTreatments",
      "Apply global to all eligible",
      "Apply to selected",
      "Clear selected overrides",
      "Copy to family",
      "Before treatment",
      "After treatment preview",
      "identical bins, axes",
      "Distribution unchanged by design",
      "High-risk row exclusion",
      "population loss",
      "Set missing",
      "is recorded automatically",
      "FIT_THRESHOLDS_INSIDE_EACH_CHRONOLOGICAL_TRAINING_FOLD",
      "project-bound-outlier-table.csv",
      "raw-row bulk export is disabled",
    ],
    "outlier treatment behavior",
  );
});

test("missing studio separates reasons, enforces eligibility, and gates predicted imputation", () => {
  for (const method of [
    "RETAIN_WITH_INDICATOR",
    "MEAN",
    "MEDIAN",
    "MODE",
    "CONSTANT",
    "GOVERNED_PRIOR",
    "PREDICTED",
    "UNKNOWN_CATEGORY",
    "DROP_VARIABLE",
    "EXCLUDE_ROW",
  ])
    assert.ok(
      missing.includes(`"${method}"`),
      `missing imputation method ${method}`,
    );
  const columns = [
    "NUMBER OF MISSING VALUES",
    "VARIABLE",
    "MISSING %",
    "DEVELOPMENT N",
    "OBSERVED N",
    "DATA TYPE",
    "FEATURE FAMILY",
    "PRIMARY MISSINGNESS REASON",
    "NO-PRIOR-HISTORY COUNT",
    "INSUFFICIENT-HISTORY COUNT",
    "SOURCE-UNAVAILABLE COUNT",
    "COMPUTATION-FAILURE COUNT",
    "PAIRED MISSINGNESS INDICATOR",
    "SELECTED IMPUTATION METHOD",
    "IMPUTED VALUE / POLICY",
    "ELIGIBLE METHODS",
    "AFFECTED GAMES",
    "AFFECTED BATTERS",
    "AFFECTED PITCHERS",
    "STATUS",
    "VIEW DETAILS",
  ];
  let cursor = -1;
  for (const column of columns) {
    const next = missing.indexOf(`"${column}"`, cursor + 1);
    assert.ok(
      next > cursor,
      `missing-value column missing/out of order: ${column}`,
    );
    cursor = next;
  }
  includesAll(
    missing,
    [
      'field: "numberOfMissingValues"',
      'direction: "desc"',
      "Cold-start rows",
      "Source / computation failure",
      "Legitimate state; rows retained",
      "Retain paired missingness indicator",
      "eligibleMethods.includes",
      "ineligibleMethodReasons",
      "A constant treatment requires an explicit value",
      "Row-specific · preview not run",
      "Run leakage-safe preview",
      "CHRONOLOGICAL_GAME_GROUPED_CROSS_FIT",
      "NOT AN OUTCOME MODEL",
      "NOT AN ADOPTED IMPUTER",
      "eligiblePredictors",
      "excludedPredictorFields",
      "domainBoundViolations",
      "artifactChecksum",
      "Before imputation",
      "After imputation preview",
      "amber patterned overlay",
      "FIT_IMPUTATION_INSIDE_EACH_CHRONOLOGICAL_TRAINING_FOLD",
      "stage3.treatment.pendingMissing",
      "stage3.treatment.featureHandoff",
    ],
    "missing-value treatment behavior",
  );
});

test("treatment client is project-bound, cancellable, cache-keyed, and fails closed on OOT or model activity", () => {
  includesAll(
    api,
    [
      "/sports/stage3-treatment/${kind}/${action}",
      "AbortController",
      "controller.abort()",
      "generation.current",
      "treatmentCache",
      "authorityKey",
      "policyVersion",
      'scope === "DEVELOPMENT_ONLY"',
      "value.population.finalOotLocked",
      "finalOotTargetAccessed",
      "finalOotUsedForSelection",
      "legacyGlobalMatrixUsed",
      "providerCalls === 0",
      "modelActivity",
      '"policy/draft" | "policy/adopt" | "predicted-preview"',
      "Treatment response did not preserve project authority and the final-OOT lock.",
    ],
    "treatment API safety",
  );
  const surfaces = `${outliers}\n${missing}\n${api}`;
  assert.doesNotMatch(
    surfaces,
    /\/cockpit\/(outliers|missing)|fit_model|score_model|promote_model|sportsbook/i,
    "studios must not fall back to legacy/model/market execution",
  );
});

test("reviewed table, full-scope actions, detail controls, and mutation failures are explicit", () => {
  includesAll(
    outliers,
    [
      "OUTLIER_COLUMNS",
      'field: "outlierPercent"',
      'field: "selectedDetectionMethod"',
      "Custom lower threshold",
      "Custom upper threshold",
      "Include variable in policy",
      "boxPlotOption",
      "Development-only target-class composition",
      "targetCompositionBefore",
      "targetCompositionAfter",
      "fetchAllTreatmentRows<OutlierTableRow>",
      "families: [familyName]",
      "includeAdvanced: true",
      "familyRow.eligibleDetectionMethods.includes",
      "detectionMethod: effectiveOverride.detectionMethod",
      "Existing treatments and variable-specific bounds were preserved.",
      "where that detection method is invalid",
      "saveError={saveMutation.error}",
      "adoptError={adoptMutation.error}",
    ],
    "reviewed outlier behaviors",
  );
  includesAll(
    missing,
    [
      "MISSING_COLUMNS",
      'field: "missingPercent"',
      'field: "selectedImputationMethod"',
      "stage3-missing-predictor-set-editor",
      "Restore governed default",
      "Apply to feature family",
      "Unavailable methods:",
      "Std before / after",
      "Category distribution before and after preview",
      "Affected games",
      "Affected batters / pitchers",
      "Predicted preview failed:",
      "fetchAllTreatmentRows<MissingTableRow>",
      "families: [familyName]",
      "row.selectedImputationMethod",
      "row.eligibleMethods.includes(row.selectedImputationMethod)",
      "familyCompatibilityFailure",
      "availablePredictors",
      "availablePredictors.slice",
      "selectedPredictors",
      "predictorSelectionLimit",
      "Use all eligible",
      "predictorSet: override.predictorSet",
      "saveError={saveMutation.error}",
      "adoptError={adoptMutation.error}",
    ],
    "reviewed missing-value behaviors",
  );
  includesAll(
    api,
    [
      "fetchAllTreatmentRows",
      "pageSize: 100",
      "selectedVariables: undefined",
      "families: string[]",
      "availablePredictors: string[]",
    ],
    "full-scope treatment client",
  );
  assert.doesNotMatch(
    outliers,
    /selectedVariables:\s*selected/,
    "batch outlier selection must not filter the table request",
  );
  assert.doesNotMatch(
    missing,
    /selectedVariables:\s*selected/,
    "batch missing-value selection must not filter the table request",
  );
  assert.doesNotMatch(
    missing,
    /predictorSet:\s*override\.predictorSet\s*\?\?\s*\[\]/,
    "explicit empty predictor selections must never silently fall back",
  );
  includesAll(
    shell,
    [
      "Policy action failed:",
      "Save a draft policy before adoption.",
      "policy?.policyId",
    ],
    "visible policy mutation failures",
  );
});

test("scientific eligibility, handoffs, and active summaries fail closed", () => {
  includesAll(
    missing,
    [
      'coldStartMethod: "RETAIN_WITH_INDICATOR"',
      'coldStartDefault: "RETAIN_WITH_INDICATOR"',
      "sanitizeColdStartOverrides",
      "detail?.governedPriorAvailable !== true",
      "Governed prior unavailable:",
      "no registered hierarchical or league-prior authority exists",
      'override.method === "CONSTANT"',
      'override.method === "PREDICTED"',
      "No family overrides were created",
      "destination-specific predictor contract and preview",
      "table.value?.data.activeGlobalMethod",
      "Active proposal",
      "DESCRIPTIVE PREVIEW · FOLD-LOCAL VALUE WILL DIFFER",
    ],
    "missing scientific eligibility",
  );
  includesAll(
    outliers,
    [
      "table.value?.data.activeSummary",
      "Active preview",
      "selected.includes(row.variable)",
      "row.eligibleDetectionMethods.includes(globalDetection)",
      "method-ineligible selections",
      "pendingMissingRequirements",
      'reason: "OUTLIER_SET_TO_MISSING"',
      "requirements: pendingMissingRequirements",
    ],
    "outlier scientific eligibility",
  );
});

test("treatment handoffs remove outcome conditioning and preserve all pending missing requirements", () => {
  for (const source of [outliers, missing]) {
    includesAll(
      source,
      [
        "const { outcomes, ...safeFilters }",
        "Boolean(outcomes?.length)",
        "stage3-treatment-outcome-filter-removed",
        "Outcome-class filter removed.",
        "cannot be conditioned on the target outcome",
      ],
      "outcome-safe treatment handoff",
    );
  }
  includesAll(
    missing,
    [
      "pendingVariables",
      "pending.requirements",
      "stage3-pending-missing-requirement",
      "No imputation is active",
    ],
    "multi-variable missing handoff",
  );
  assert.doesNotMatch(
    outliers,
    /Create pending missing requirement/,
    "SET_MISSING handoff must be automatic rather than button-dependent",
  );
});

test("pending SET_MISSING requirements use the governed default-eligible outlier catalog", () => {
  includesAll(
    outliers,
    [
      "isAdvancedOutlierEligible",
      "isBinaryOutlierMetadata",
      "isDefaultOutlierEligible",
      'variable.role !== "SIMULATION_GENERATED_STATE"',
      ".filter(isDefaultOutlierEligible)",
      "!isDefaultOutlierEligible(variable)",
      "Boolean(overrides[variable.name])",
      "const catalogVariables = metadata.value",
      ": [];",
    ],
    "outlier-to-missing eligibility",
  );
  assert.match(
    outliers,
    /!isDefaultOutlierEligible\(variable\)[\s\S]*isAdvancedOutlierEligible\(variable\)[\s\S]*Boolean\(overrides\[variable\.name\]\)/,
    "default-excluded advanced variables must require an explicit eligible override",
  );
});

test("adoption is disabled whenever visible policy controls differ from the saved draft", () => {
  includesAll(
    shell,
    [
      "canonicalPolicySignature",
      "savedDraftAvailable && !hasUnsavedChanges",
      "if (hasUnsavedChanges) setConfirmAdopt(false)",
      "stage3-policy-unsaved-warning",
      "Unsaved policy changes.",
      "Save changes before adoption",
      "Adopt will never authorize the older draft silently.",
    ],
    "saved-draft adoption integrity",
  );
  includesAll(
    outliers,
    [
      "outlierPolicyControlSignature",
      "const draftHasUnsavedChanges",
      "policy?.status === \"DRAFT\"",
      "hasUnsavedChanges={draftHasUnsavedChanges}",
    ],
    "outlier draft equality",
  );
  includesAll(
    missing,
    [
      "missingPolicyControlSignature",
      "const draftHasUnsavedChanges",
      "policy?.status === \"DRAFT\"",
      "predictorSet: override.predictorSet",
      "seed: override.seed",
      "hasUnsavedChanges={draftHasUnsavedChanges}",
    ],
    "missing draft equality",
  );
});

test("predicted imputation uses canonical unfiltered evidence and renders the combined OOF after state", () => {
  includesAll(
    missing,
    [
      "PREDICTED_PREVIEW_SEED = 731026",
      "baseDetail?.canonicalPredictedPreviewSeed ?? PREDICTED_PREVIEW_SEED",
      'filters: override.method === "PREDICTED" ? {} : filters',
      "filters: {},",
      "complete authorized",
      "active descriptive filters are ignored",
      "predictorSet: value.data.eligiblePredictors",
      "seed: value.data.seed",
      "predictedResult.observedDistribution",
      "predictedResult.imputedDistribution",
      "predictedResult.after",
      "predictedResult.aggregateEffect",
    ],
    "canonical predicted preview",
  );
  assert.doesNotMatch(
    missing,
    /73102026/,
    "frontend must not use the obsolete predicted-preview seed",
  );
  includesAll(
    api,
    [
      "observedDistribution: DistributionPreview",
      "imputedDistribution: DistributionPreview",
      "aggregateEffect:",
      "canonicalPredictedPreviewSeed",
    ],
    "predicted aggregate response contract",
  );
});

test("predicted preview evidence is bound to the exact current request identity", () => {
  includesAll(
    missing,
    [
      "PREDICTED_PREVIEW_DESIGN",
      "predictedPreviewMatchesRequest",
      "preview.variable === variable",
      "preview.seed === seed",
      "preview.eligiblePredictors.length === predictorSet.length",
      "predictor === predictorSet[index]",
      "predictedPreviewRequestSpec",
      "currentPredictedRequestIdentity",
      "completedPredictedRequestIdentity",
      "currentPredictedRequestIdentityRef",
      "completedPredictedRequestIdentity.current = null",
      "predicted.reset()",
      "mutationPredictedResult ?? storedPredictedResult",
      '.run("predicted-preview", predictedPreviewRequestSpec)',
      "currentPredictedRequestIdentityRef.current !==",
    ],
    "predicted-preview request binding",
  );
  assert.match(
    missing,
    /variable: row\.variable,[\s\S]*filters: \{\},[\s\S]*predictorSet: selectedPredictors,[\s\S]*seed: canonicalPredictedPreviewSeed,[\s\S]*design: PREDICTED_PREVIEW_DESIGN/,
    "the request identity must cover the variable, ordered predictors, canonical seed, and full-development specification",
  );
  assert.doesNotMatch(
    missing,
    /const predictedResult\s*=\s*predicted\.value\?\.data\s*\?\?/,
    "an unbound prior mutation result must never take precedence",
  );
});

test("advanced metadata rows remain visibly unevaluated and noninteractive", () => {
  includesAll(
    outliers,
    [
      "eligible = row.eligible !== false",
      "Read-only metadata",
      "No treatment authorized",
      "row.exclusionReason",
      'eligible ? "View details" : "Not eligible"',
    ],
    "outlier excluded metadata",
  );
  includesAll(
    missing,
    [
      "eligible = row.eligible !== false",
      "No imputation authorized",
      "row.exclusionReason",
      'eligible ? "View details" : "Not eligible"',
    ],
    "missing excluded metadata",
  );
  includesAll(
    api,
    [
      "eligible: boolean",
      "excludedMetadataRows?: number",
      "exclusionReason?: string | null",
    ],
    "excluded metadata response contract",
  );
});
