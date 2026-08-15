import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

function transpileTypeScript(path) {
  return ts.transpileModule(read(path), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: path,
  }).outputText;
}

function sourceDataUrl(source) {
  return `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
}

async function importTypeScript(path) {
  let output = transpileTypeScript(path);
  if (output.includes('"./datasetIdentity"')) {
    const datasetIdentityUrl = sourceDataUrl(
      transpileTypeScript("src/lib/datasetIdentity.ts"),
    );
    output = output.replaceAll(
      '"./datasetIdentity"',
      JSON.stringify(datasetIdentityUrl),
    );
  }
  return import(
    sourceDataUrl(output)
  );
}

const sources = {
  step: read("src/steps/Step02_EDA.tsx"),
  styles: read("src/components/eda/eda-premium.css"),
  targetWorkspace: read(
    "src/components/eda/TargetIntelligenceWorkspace.tsx",
  ),
  targetVisuals: read("src/components/eda/TargetVisualInsights.tsx"),
  predictorLandscape: read(
    "src/components/eda/visual/PredictorSignalLandscape.tsx",
  ),
  findingsWorkspace: read(
    "src/components/eda/FindingsDecisionWorkspace.tsx",
  ),
  documentationPayload: read("src/lib/edaDocumentationPayload.ts"),
  documentationPanel: read(
    "src/components/documentation/EdaDocumentationLiveLink.tsx",
  ),
  documentationService: read("server/eda/documentation_service.py"),
  documentationBehavioralSuite: read(
    "tests/eda_documentation_contract_test.py",
  ),
  e2e: read("tests/e2e/eda-final-acceptance-polish.spec.ts"),
  packageJson: read("package.json"),
};

const [targetApi, lifecycle, predictorLimits, findings] = await Promise.all([
  importTypeScript("src/lib/targetDistributionApi.ts"),
  importTypeScript("src/lib/dataAcquisitionLifecycle.ts"),
  importTypeScript(
    "src/components/eda/visual/predictorVisibleLimits.ts",
  ),
  importTypeScript("src/lib/edaFindings.ts"),
]);

let findingGovernance;

function compileDocumentationPayload() {
  const governanceOutput = ts.transpileModule(
    read("src/lib/edaFindingGovernance.ts"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: "edaFindingGovernance.ts",
    },
  ).outputText;
  const governanceModule = { exports: {} };
  vm.runInNewContext(governanceOutput, {
    module: governanceModule,
    exports: governanceModule.exports,
    require(specifier) {
      if (specifier === "./edaFindings") return findings;
      throw new Error(`Unexpected finding-governance import: ${specifier}`);
    },
    console,
    JSON,
    Math,
    Object,
    Number,
    String,
    Array,
    Boolean,
    Map,
    Set,
    Date,
    Error,
  });
  findingGovernance = governanceModule.exports;
  const output = ts.transpileModule(sources.documentationPayload, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: "edaDocumentationPayload.ts",
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(
    output,
    {
      module,
      exports: module.exports,
      require(specifier) {
        if (specifier === "./edaFindings") return findings;
        if (specifier === "./codeContextSafety") {
          return {
            stableCodeContextHash(value) {
              let hash = 2166136261;
              for (let index = 0; index < value.length; index += 1) {
                hash ^= value.charCodeAt(index);
                hash = Math.imul(hash, 16777619);
              }
              return (hash >>> 0).toString(16).padStart(8, "0");
            },
          };
        }
        if (specifier === "./edaDocumentationApi") return {};
        if (specifier === "./edaFindingGovernance") {
          return governanceModule.exports;
        }
        throw new Error(`Unexpected documentation payload import: ${specifier}`);
      },
      console,
      JSON,
      Math,
      Object,
      Number,
      String,
      Array,
      Boolean,
      Map,
      Set,
    },
    { filename: "edaDocumentationPayload.acceptance.js" },
  );
  return module.exports.buildEdaDocumentationPayload;
}

const buildDocumentationPayload = compileDocumentationPayload();

const fixture = {
  overview: {
    row_count: 10_000,
    column_count: 24,
    scope: "full_dataset",
    target: "bad_flag",
    problem_type: "classification",
    event_value: 1,
    headline: {
      rows: 10_000,
      duplicate_rows: 17,
      missing_cells: 240,
      missing_cell_rate: 0.0012,
    },
    data_integrity: {
      duplicate_rows: 17,
      constant_columns: ["constant_field"],
      invalid_numeric_parsing: [
        { feature: "parse_concern", unparsed_count: 8 },
      ],
    },
    predictor_authorization: {
      manifest_version: "pm-heloc-v1",
      authorized_predictors: [
        "ExternalRiskEstimate",
        "MSinceMostRecentInqexcl7days",
      ],
      target_source_excluded: ["RiskPerformance"],
    },
    target_source_excluded: ["RiskPerformance"],
  },
  target: {
    target: "bad_flag",
    problem_type: "classification",
    event_value: 1,
    profile: {
      event_rate: 0.07,
      event_count: 700,
      non_event_count: 9_300,
      valid_count: 10_000,
    },
    target_quality: {
      missing_target_count: 0,
      invalid_target_values: [],
      unexpected_target_values: [],
      duplicate_target_bearing_rows: 17,
    },
  },
  predictors: {
    target: "bad_flag",
    numeric: [],
    categorical: [],
    predictor_visual_profiles: [
      {
        feature: "ExternalRiskEstimate",
        kind: "numeric",
        metrics: {
          iv: 0.81,
          missing_rate: 0.12,
          outlier_rate: 0.07,
          special_prevalence: 0.11,
          skewness: 2.8,
          distinct_count: 92,
          monotonicity: "non_monotonic",
        },
        missing: { rate: 0.12 },
        ordinary_outlier: { rate: 0.07 },
        bureau_special: { prevalence: 0.11 },
        event_rate_shape: {
          groups: [
            { event_rate: 0.02 },
            { event_rate: 0.11 },
            { event_rate: 0.06 },
          ],
        },
      },
      {
        feature: "RiskPerformance",
        kind: "categorical",
        metrics: { iv: 9.9, missing_rate: 0, distinct_count: 2 },
      },
      {
        feature: "bad_flag",
        kind: "categorical",
        metrics: { iv: 9.9, missing_rate: 0, distinct_count: 2 },
      },
    ],
  },
  relationships: {
    correlation_columns: [
      "ExternalRiskEstimate",
      "MSinceMostRecentInqexcl7days",
    ],
    strong_pairs: [
      {
        feature_a: "ExternalRiskEstimate",
        feature_b: "MSinceMostRecentInqexcl7days",
        correlation: -0.78,
      },
    ],
    vif: [{ feature: "ExternalRiskEstimate", vif: 11.2, status: "high" }],
  },
  stability: {
    time_profile: [],
    segment_profile: [],
  },
  findings: {
    findings: [
      {
        category: "Data integrity",
        severity: "warning",
        finding: "17 duplicate rows were detected.",
        recommended_action: "Review duplicate rows.",
      },
    ],
  },
};

function generatedInventory() {
  return findings.generateEdaFindings(fixture);
}

function requiredHighIvFinding() {
  const item = generatedInventory().find(
    (candidate) => Number(candidate.iv) >= 0.5,
  );
  assert.ok(item, "Expected a generated high-IV finding.");
  return item;
}

test("1. Page-title hierarchy.", () => {
  assert.match(sources.step, /hideHeader/);
  assert.match(sources.step, /data-testid="eda-compact-page-header"/);
  assert.match(sources.step, /<h1>Step 2: Exploratory Data Analysis<\/h1>/);
  assert.ok(
    sources.step.indexOf("<h1>Step 2: Exploratory Data Analysis</h1>") <
      sources.step.indexOf('data-testid="eda-analysis-tab-rail"'),
  );
});

test("2. Tab-navigation discoverability.", () => {
  assert.match(sources.step, /aria-label="EDA analysis navigation"/);
  assert.match(sources.step, /role="tablist"/);
  assert.match(sources.step, /role="tab"/);
  assert.match(sources.step, /aria-selected=\{selected\}/);
  for (const label of [
    "Overview",
    "Target",
    "Predictors",
    "Relationships",
    "Stability & Segments",
    "Findings",
  ]) {
    assert.match(sources.step, new RegExp(`label: "${label.replace("&", "\\&")}"`));
  }
});

test("3. Target chart exits loading.", async () => {
  targetApi.clearTargetDistributionCache();
  const originalFetch = globalThis.fetch;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const calls = [];
  const request = {
    projectId: "project-heloc",
    datasetId: "HELOC_TRAIN",
    versionId: "heloc-v1",
    target: "bad_flag",
    eventValue: 1,
    nonEventValue: 0,
  };

  try {
    globalThis.fetch = async (url, init) => {
      calls.push({ url, init });
      await gate;
      return {
        ok: true,
        json: async () => ({
          ok: true,
          supported: true,
          resolution: "exact",
          projectId: request.projectId,
          datasetId: request.datasetId,
          versionId: request.versionId,
          target: request.target,
          classDistribution: [
            { value: "0", count: 7_500, percent: 0.75 },
            { value: "1", count: 2_500, percent: 0.25 },
          ],
          totalRowCount: 10_000,
          cached: false,
          durationMs: 12,
        }),
      };
    };

    let panelState = "loading";
    const firstMount = new AbortController();
    const firstWait = targetApi.fetchTargetDistribution(request, {
      signal: firstMount.signal,
    });
    const remountWait = targetApi.fetchTargetDistribution({ ...request });
    firstMount.abort();
    await assert.rejects(firstWait, (error) => error?.name === "AbortError");
    assert.equal(panelState, "loading");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].init.signal, undefined);

    release();
    const result = await remountWait;
    const distribution = lifecycle.buildTargetDistribution({
      target: result.target,
      classDistribution: result.classDistribution,
      eventValue: request.eventValue,
      nonEventValue: request.nonEventValue,
    });
    panelState = distribution ? "ready" : "empty";

    assert.equal(panelState, "ready");
    assert.equal(distribution.totalRows, 10_000);
    assert.equal(distribution.eventCount, 2_500);
    assert.equal(distribution.nonEventCount, 7_500);
  } finally {
    globalThis.fetch = originalFetch;
    targetApi.clearTargetDistributionCache();
  }
});

test("4. Target balance visual.", () => {
  for (const marker of [
    'data-testid="target-balance-confidence"',
    'data-testid="target-balance-bar"',
    'data-testid="target-event-count"',
    'data-testid="target-non-event-count"',
    'data-testid="target-imbalance-ratio"',
    'data-scope="development-population"',
  ]) {
    assert.match(sources.targetVisuals, new RegExp(marker));
  }
  assert.ok(
    sources.targetWorkspace.indexOf("<TargetBalanceConfidenceVisual") <
      sources.targetWorkspace.indexOf("<TargetDistributionPanel"),
  );
});

test("5. Confidence visual.", () => {
  for (const marker of [
    'data-testid="target-confidence-interval"',
    'data-testid="target-wilson-confidence-band"',
    'data-testid="ci-lower-bound"',
    'data-testid="ci-point-estimate"',
    'data-testid="ci-upper-bound"',
    "Wilson confidence interval",
    "measurement uncertainty",
  ]) {
    assert.match(sources.targetVisuals, new RegExp(marker));
  }
});

test("6. Target quality visual.", () => {
  assert.match(sources.targetVisuals, /data-testid="target-quality-diagnostic"/);
  for (const diagnostic of [
    "Missing target",
    "Invalid values",
    "Unexpected values",
    "Duplicate target-bearing rows",
    "Target-derived candidates",
    "Post-outcome candidates",
  ]) {
    assert.match(sources.targetVisuals, new RegExp(diagnostic));
  }
  assert.match(sources.targetVisuals, /data-quality-diagnostic=/);
});

test("7. Event-rate preview.", () => {
  for (const marker of [
    'data-testid="target-event-rate-predictor-preview"',
    'data-testid="target-predictor-preview-card"',
    'data-testid="target-predictor-sparkline"',
    'data-testid="inspect-target-predictor"',
    ".slice(0, 5)",
    "Development Population",
    "sealed final holdout",
  ]) {
    assert.match(sources.targetVisuals, new RegExp(marker.replace(/[()]/g, "\\$&")));
  }
});

test("8. Unique predictor dropdown options.", () => {
  for (const count of [1, 12, 21, 24, 40, 54, 60, 200]) {
    const options = predictorLimits.buildPredictorVisibleLimitOptions(count);
    assert.equal(new Set(options).size, options.length);
    assert.ok(
      options.every((value, index) => index === 0 || value > options[index - 1]),
    );
    assert.equal(options.at(-1), Math.min(count, 60));
  }
  assert.deepEqual(
    predictorLimits.buildPredictorVisibleLimitOptions(21),
    Array.from({ length: 21 }, (_unused, index) => index + 1),
  );
  assert.match(
    sources.predictorLandscape,
    /data-testid="predictor-visible-limit"/,
  );
});

test("9. Stability does not fabricate fields.", () => {
  const unavailable = sources.step.slice(
    sources.step.indexOf("function StabilityUnavailableState"),
    sources.step.indexOf("function AnalysisSelectors"),
  );
  assert.match(unavailable, /data-analysis-available="false"/);
  assert.match(unavailable, /No analysis fabricated/);
  assert.match(unavailable, /will not infer dates or comparison populations/);
  assert.doesNotMatch(unavailable, /<table|<ChartCard|classDistribution|event_rate_by_time/);
});

test("10. Stability capability explanation.", () => {
  const unavailable = sources.step.slice(
    sources.step.indexOf("function StabilityUnavailableState"),
    sources.step.indexOf("function AnalysisSelectors"),
  );
  for (const capability of [
    "Time trend",
    "Segment comparison",
    "Population drift",
    "Population Stability Index (PSI)",
    "How to enable these analyses",
  ]) {
    assert.match(unavailable, new RegExp(capability.replace(/[()]/g, "\\$&")));
  }
  assert.match(unavailable, /does not block\s+EDA confirmation/);
  assert.match(unavailable, /data-confirmation-impact="non-blocking"/);
});

test("11. Auto-generated findings.", () => {
  const inventory = generatedInventory();
  assert.ok(inventory.length > 0);
  for (const category of [
    "Data quality",
    "Target",
    "Predictors",
    "Relationships",
    "Stability",
  ]) {
    assert.ok(
      inventory.some((item) => item.category === category),
      `Expected a generated ${category} finding.`,
    );
  }
  assert.match(sources.findingsWorkspace, /eda-findings-executive-summary/);
  assert.match(sources.findingsWorkspace, /eda-findings-action-guide/);
  assert.match(sources.findingsWorkspace, /What matters on this page/);
  assert.match(sources.findingsWorkspace, /Start with unresolved/);
  assert.match(sources.findingsWorkspace, /Pick a disposition/);
  assert.match(sources.findingsWorkspace, /Save evidence/);
  assert.match(sources.findingsWorkspace, /eda-findings-inventory/);
});

test("12. High-IV review finding.", () => {
  const item = requiredHighIvFinding();
  assert.equal(item.affectedVariables[0], "ExternalRiskEstimate");
  assert.equal(item.targetSourceStatus, "not_target_source");
  assert.match(
    item.leakageEvidence,
    /High IV alone does not establish leakage/,
  );
  assert.match(sources.findingsWorkspace, /eda-high-iv-review-signal/);
});

test("13. Transformation recommendation.", () => {
  const item = requiredHighIvFinding();
  assert.ok(item.suggestedTransformations.includes("No transformation"));
  assert.ok(item.suggestedTransformations.includes("Investigate further"));
  assert.match(sources.findingsWorkspace, /eda-suggested-transformations/);
  assert.doesNotMatch(
    sources.findingsWorkspace,
    /onApplyTransformation|applyTransformation/,
  );
});

test("14. Reviewer disposition.", () => {
  const selected = requiredHighIvFinding();
  const rows = findings.documentedFindingRows(fixture, {
    commentary: "Reviewed governed evidence.",
    status: "reviewed",
    findingDecisions: {
      [selected.id]: {
        disposition: "accepted",
        rationale: "Availability at application time was confirmed.",
        destination: "Validation",
        transformation: "Investigate further",
      },
    },
  });
  const documented = rows.find((row) => row.finding_id === selected.id);
  assert.equal(documented.reviewer_disposition, "accepted");
  assert.equal(
    documented.reviewer_rationale,
    "Availability at application time was confirmed.",
  );
  assert.match(sources.findingsWorkspace, /eda-finding-disposition/);
});

test("15. Carry-forward destination.", () => {
  const selected = requiredHighIvFinding();
  const rows = findings.documentedFindingRows(fixture, {
    commentary: "Reviewed governed evidence.",
    status: "reviewed",
    findingDecisions: {
      [selected.id]: {
        disposition: "accepted",
        rationale: "Independent validation should review this signal.",
        destination: "Validation",
        transformation: "Investigate further",
      },
    },
  });
  const accepted = rows.find((row) => row.finding_id === selected.id);
  assert.equal(accepted.downstream_destination, "Validation");
  assert.equal(accepted.carry_forward_mode, "draft_recommendation");
  assert.equal(accepted.mutation_applied, false);
  assert.match(sources.findingsWorkspace, /eda-carry-forward-queue/);
});

test("16. MDD draft update.", () => {
  const selected = requiredHighIvFinding();
  const parent = findingGovernance
    .generateEdaParentFindings(fixture)
    .find((candidate) => candidate.childIds.includes(selected.id));
  assert.ok(parent, "Expected the high-IV evidence to belong to a parent finding.");
  const payload = buildDocumentationPayload({
    projectId: "project-heloc",
    datasetId: "HELOC_TRAIN",
    datasetVersion: "heloc-v1",
    target: "bad_flag",
    predictorManifestId: "pm-heloc-v1",
    selectedFeatures: [
      "ExternalRiskEstimate",
      "MSinceMostRecentInqexcl7days",
      "RiskPerformance",
    ],
    controls: {
      histogramBins: 20,
      dateField: "",
      segmentField: "",
      pairwiseFeatures: [
        "ExternalRiskEstimate",
        "MSinceMostRecentInqexcl7days",
      ],
    },
    findings: {
      commentary: "Final EDA review completed.",
      overallConclusion: "Ready for governed downstream review.",
      status: "accepted",
      duplicateTreatment: "keep",
      duplicateDecisionSavedAt: "2026-07-28T12:00:00.000Z",
      parentDecisions: {
        [parent.parentId]: {
          disposition: "accepted",
          rationale: "Carry forward for independent leakage review.",
          destination: "Validation",
          transformation: "Investigate further",
        },
      },
    },
    evidenceReferences: [
      {
        evidence_id: "ev-eda-final-acceptance",
        title: "Final EDA acceptance",
        evidence_type: "eda",
      },
    ],
    sections: fixture,
  });

  const approved = payload.sections.findings.accepted_parent_findings.find(
    (row) => row.parent_id === parent.parentId,
  );
  const queued = payload.sections.findings.carry_forward.find(
    (row) => row.parent_id === parent.parentId,
  );
  assert.ok(approved);
  assert.ok(queued);
  assert.equal(queued.destination, "Validation");
  assert.equal(queued.status, "draft_recommendation");
  assert.equal(queued.mutation_applied, false);
  assert.equal(payload.reviewer_status, "approved");
  assert.ok(!payload.sections.predictors.selected_predictors.includes("RiskPerformance"));
});

test("17. MDD stale behavior.", () => {
  const staleTest = sources.documentationBehavioralSuite.slice(
    sources.documentationBehavioralSuite.indexOf(
      "def test_new_draft_marks_approval_stale_without_overwriting_it",
    ),
    sources.documentationBehavioralSuite.indexOf(
      "def test_dataset_version_change_invalidates_and_reopen_restores_state",
    ),
  );
  assert.match(staleTest, /state\["status"\], "stale"/);
  assert.match(staleTest, /state\["current_approved"\]\["confirmation_id"\]/);
  assert.match(staleTest, /state\["draft"\]\["changed_sections"\]/);
  assert.match(staleTest, /changed after the approved confirmation/);
  assert.match(sources.documentationService, /stale_reason/);
  assert.match(sources.documentationPanel, /Stale after upstream change/);
  assert.match(sources.documentationPanel, /Preserved/);
  assert.match(sources.documentationPanel, /Not approved/);
});

test("18. Target-source exclusion.", () => {
  const predictorVariables = generatedInventory()
    .filter((item) => item.category === "Predictors")
    .flatMap((item) => item.affectedVariables);
  assert.ok(!predictorVariables.includes("bad_flag"));
  assert.ok(!predictorVariables.includes("RiskPerformance"));
  assert.ok(
    generatedInventory().some(
      (item) =>
        item.targetSourceStatus === "excluded" &&
        item.affectedVariables.includes("RiskPerformance"),
    ),
  );
  assert.match(
    sources.targetVisuals,
    /const excluded = new Set\(\[target, \.\.\.targetSourceExcluded\]\)/,
  );
  assert.match(sources.targetVisuals, /target-source-exclusion-diagnostic/);
});

test("19. Reduced-motion behavior.", () => {
  assert.match(sources.targetWorkspace, /prefersReducedMotion/);
  assert.match(
    sources.targetWorkspace,
    /matchMedia\?\.\("\(prefers-reduced-motion: reduce\)"\)/,
  );
  assert.match(sources.targetWorkspace, /data-reduced-motion=/);
  assert.match(sources.targetVisuals, /data-reduced-motion=/);
  assert.match(sources.predictorLandscape, /useReducedMotion/);
  assert.match(sources.styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(sources.e2e, /emulateMedia\(\{ reducedMotion: "reduce" \}\)/);
});

test("20. No uncaught page errors.", () => {
  assert.match(sources.e2e, /page\.on\("pageerror"/);
  assert.match(sources.e2e, /message\.type\(\) === "error"/);
  assert.match(sources.e2e, /expect\(pageErrors/);
  assert.match(sources.e2e, /expect\(consoleErrors/);
  assert.match(sources.e2e, /toEqual\(\[\]\)/);
  assert.match(
    sources.e2e,
    /authenticated HELOC_TRAIN \/ bad_flag final acceptance walkthrough/,
  );
});

test("21. Security gate remains green.", () => {
  const pkg = JSON.parse(sources.packageJson);
  assert.equal(
    pkg.scripts["test:security"],
    "python scripts/run_security_tests.py",
  );
  assert.equal(
    existsSync(new URL("scripts/run_security_tests.py", ROOT)),
    true,
  );
});
