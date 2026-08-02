import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const read = (path) =>
  fs.readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const sources = {
  step: read("src/steps/Step02_EDA.tsx"),
  target: read("src/components/eda/TargetIntelligenceWorkspace.tsx"),
  distribution: read(
    "src/components/eda/visual/PredictorDistributionExplorer.tsx",
  ),
  correlation: read("src/components/eda/visual/CorrelationExplorer.tsx"),
  relationship: read("src/components/eda/visual/RelationshipExplorer.tsx"),
  relationshipWebGl: read(
    "src/components/eda/visual/RelationshipWebGL.tsx",
  ),
  styles: read("src/components/eda/eda-premium.css"),
  payload: read("src/lib/edaDocumentationPayload.ts"),
  findings: read("src/lib/edaFindings.ts"),
  findingGovernance: read("src/lib/edaFindingGovernance.ts"),
  api: read("src/lib/edaDocumentationApi.ts"),
  mdd: read(
    "src/components/documentation/EdaDocumentationLiveLink.tsx",
  ),
  studio: read("src/steps/ModelDocumentationStudio.tsx"),
  backend: read("server/eda/documentation_service.py"),
  backendTypes: read("server/eda/documentation_types.py"),
  router: read("server/eda/eda_router.py"),
  codeSafety: read("src/lib/codeContextSafety.ts"),
  pythonPanel: read("src/components/StepPythonPanel.tsx"),
  codeWorkspace: read("src/components/code/CodeWorkspacePanel.tsx"),
  backendTests: read("tests/eda_documentation_contract_test.py"),
  e2e: read("tests/e2e/eda-premium-experience.spec.ts"),
};

const checks = [];
function check(name, callback) {
  try {
    callback();
    checks.push({ name, ok: true });
  } catch (error) {
    checks.push({ name, ok: false, error });
  }
}

function includesAll(source, markers) {
  for (const marker of markers) {
    assert.ok(source.includes(marker), `Missing marker: ${marker}`);
  }
}

const commonJsCompilerOptions = {
  target: ts.ScriptTarget.ES2021,
  module: ts.ModuleKind.CommonJS,
  esModuleInterop: true,
};
const compiledFindings = ts.transpileModule(sources.findings, {
  compilerOptions: commonJsCompilerOptions,
  fileName: "edaFindings.ts",
}).outputText;
const findingsModule = { exports: {} };
vm.runInNewContext(
  compiledFindings,
  {
    module: findingsModule,
    exports: findingsModule.exports,
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
  { filename: "edaFindings.test.js" },
);

const compiledFindingGovernance = ts.transpileModule(
  sources.findingGovernance,
  {
    compilerOptions: commonJsCompilerOptions,
    fileName: "edaFindingGovernance.ts",
  },
).outputText;
const findingGovernanceModule = { exports: {} };
vm.runInNewContext(
  compiledFindingGovernance,
  {
    module: findingGovernanceModule,
    exports: findingGovernanceModule.exports,
    require(specifier) {
      if (specifier === "./edaFindings") return findingsModule.exports;
      throw new Error(`Unexpected governance test import: ${specifier}`);
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
  },
  { filename: "edaFindingGovernance.test.js" },
);

const compiledPayload = ts.transpileModule(sources.payload, {
  compilerOptions: {
    ...commonJsCompilerOptions,
  },
  fileName: "edaDocumentationPayload.ts",
}).outputText;
const payloadModule = { exports: {} };
vm.runInNewContext(
  compiledPayload,
  {
    module: payloadModule,
    exports: payloadModule.exports,
    require(specifier) {
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
      if (specifier === "./edaFindings") return findingsModule.exports;
      if (specifier === "./edaFindingGovernance") {
        return findingGovernanceModule.exports;
      }
      throw new Error(`Unexpected payload test import: ${specifier}`);
    },
    console,
    JSON,
    Math,
    Object,
    Number,
    String,
    Array,
    Boolean,
    Set,
  },
  { filename: "edaDocumentationPayload.test.js" },
);

const buildPayload = payloadModule.exports.buildEdaDocumentationPayload;
const baseInput = {
  projectId: "project-heloc",
  datasetId: "ds-heloc-train",
  datasetVersion: "heloc-v1",
  target: "bad_flag",
  predictorManifestId: "pm-heloc-v1",
  selectedFeatures: [
    "ExternalRiskEstimate",
    "MSinceOldestTradeOpen",
    "RiskPerformance",
  ],
  controls: {
    histogramBins: 20,
    dateField: "",
    segmentField: "",
    pairwiseFeatures: ["ExternalRiskEstimate", "MSinceOldestTradeOpen"],
  },
  findings: {
    commentary: "Reviewed the full governed HELOC population.",
    overallConclusion:
      "Governed EDA evidence is suitable for documented carry-forward.",
    status: "accepted",
    duplicateTreatment: "review",
  },
  evidenceReferences: [
    {
      evidence_id: "ev-eda-heloc",
      title: "HELOC EDA",
      evidence_type: "eda",
    },
  ],
  sections: {
    overview: {
      row_count: 10459,
      column_count: 24,
      scope: "full_dataset",
      target: "bad_flag",
      problem_type: "classification",
      event_value: 1,
      dataset_version: "heloc-v1",
      duration_ms: 120,
      cache_status: "miss",
      headline: {
        rows: 10459,
        predictors: 22,
        numeric_predictors: 22,
        categorical_predictors: 0,
        missing_cells: 0,
        missing_cell_rate: 0,
        duplicate_rows: 0,
      },
      data_integrity: {
        constant_columns: [],
        invalid_numeric_parsing: [],
      },
      available_fields: {
        date_candidates: [],
        segment_candidates: [],
      },
      predictor_authorization: {
        manifest_version: "pm-heloc-v1",
        authorized_predictors: [
          "ExternalRiskEstimate",
          "MSinceOldestTradeOpen",
        ],
        target_source_excluded: ["RiskPerformance"],
      },
      target_source_excluded: ["RiskPerformance"],
      target_profile: {
        class_distribution: [
          { value: "0", count: 7000, rate: 0.669 },
          { value: "1", count: 3459, rate: 0.331 },
        ],
        event_count: 3459,
        non_event_count: 7000,
        event_rate: 0.331,
        rare_event: false,
      },
    },
    target: {
      problem_type: "classification",
      event_value: 1,
      profile: {
        event_count: 3459,
        non_event_count: 7000,
        event_rate: 0.331,
        class_distribution: [],
      },
      identity: {
        target: "bad_flag",
        source: "RiskPerformance",
        event_mapping: "Bad → 1",
        non_event_mapping: "Good → 0",
      },
      full_population_assessment: { prevalence: "common_event" },
      target_quality: { leakage_review: "target source excluded" },
    },
    predictors: {
      numeric: [
        {
          feature: "ExternalRiskEstimate",
          count: 10459,
          missing_count: 0,
          missing_rate: 0,
          mean: 72,
          iv: 0.45,
          monotonicity: "decreasing",
          outlier_rate: 0.01,
        },
        {
          feature: "MSinceOldestTradeOpen",
          count: 10459,
          missing_count: 0,
          missing_rate: 0,
          mean: 210,
          iv: 0.11,
          monotonicity: "increasing",
          outlier_rate: 0.02,
        },
      ],
      categorical: [],
      missingness: [],
    },
    relationships: {
      correlation_columns: [
        "ExternalRiskEstimate",
        "MSinceOldestTradeOpen",
      ],
      strong_pairs: [],
      vif: [
        { feature: "ExternalRiskEstimate", vif: 1.4 },
        { feature: "MSinceOldestTradeOpen", vif: 1.4 },
      ],
      pairwise_scope: "rendered_sample",
    },
    stability: {
      date_field: null,
      segment_field: null,
      time_profile: [],
      segment_profile: [],
    },
    findings: { findings: [], carry_forward: {} },
  },
};
const governedContract = {
  artifact_id: "eda-contract-heathash",
  artifact_hash: "contract-hash-1",
  analysis_scope: "development_population",
  analysis_population_id: "development-split-1",
  rows_used: 8367,
  rows_excluded: 2092,
  special_value_policy_id: "eda-special-policy-1",
  binning_specification: {
    method: "quantile_actual_value_boundaries",
    requested_bins: 10,
  },
  calculation_method: {
    iv_woe: "quantile_actual_value_boundaries_additive_smoothing",
    correlation: ["pearson", "spearman"],
    vif: "complete_case_ols_r_squared",
  },
  created_at: "2026-08-01T10:00:00Z",
  predictor_artifacts: { duplicated_nested_payload: true },
  relationship_artifact: { duplicated_nested_payload: true },
};
const governedPredictorArtifacts = {
  ExternalRiskEstimate: {
    artifact_id: "eda-predictor-external-risk",
    artifact_hash: "predictor-hash-1",
    iv_artifact_id: "eda-iv-external-risk",
    iv_woe: {
      binning_method: "development_population_quantile_actual_value_boundaries",
      special_value_treatment:
        "separate_named_groups_outside_ordinary_quantiles",
    },
    ordinary_outlier: {
      calculation_method: "1.5_iqr_over_ordinary_valid_numeric_values_only",
      excludes_bureau_special_values: true,
    },
  },
};
const governedRelationshipArtifact = {
  artifact_id: "eda-relationships-heloc",
  artifact_hash: "relationships-hash-1",
  correlation_method: ["pearson", "spearman"],
  vif_method: "complete_case_ols_r_squared",
};
baseInput.sections.overview.governed_analytical_contract = governedContract;
baseInput.sections.predictors.governed_predictor_artifacts =
  governedPredictorArtifacts;
baseInput.sections.relationships.governed_relationship_artifact =
  governedRelationshipArtifact;
const generated = buildPayload(baseInput);

check("1. Overview has a deliberate analytical launch hierarchy", () => {
  includesAll(sources.step, [
    'data-testid="eda-overview-launch-surface"',
    'data-testid="eda-dataset-fingerprint"',
    'data-testid="eda-overview-population-balance"',
    'data-testid="eda-data-quality-health"',
    'data-testid="eda-overview-attention"',
  ]);
});

check("2. Target is consolidated into the five intended analytical stories", () => {
  includesAll(sources.target, [
    'data-testid="target-governed-lineage"',
    'data-testid="target-prevalence-story"',
    'data-testid="target-prevalence-ring"',
    'data-testid="target-uncertainty-guidance"',
    "Target by Predictor",
    "Target Quality",
  ]);
});

check("3. IV by Bin is primary and visible by default", () => {
  assert.match(sources.distribution, /useState\(true\)/);
  assert.ok(sources.distribution.includes('data-visible-by-default="true"'));
  assert.ok(sources.distribution.includes('data-testid="eda-iv-by-bin"'));
});

check("4. Accessible distribution data is a secondary disclosure", () => {
  includesAll(sources.distribution, [
    'data-testid="eda-distribution-accessibility-alternative"',
    "Accessibility and export alternative",
  ]);
});

check("5. Heatmap defaults to the complete 12-variable readable matrix", () => {
  assert.match(sources.correlation, /DEFAULT_SUBSET_LIMIT = 12/);
  assert.match(sources.correlation, /useState<MatrixViewMode>\("readable"\)/);
});

check("6. Heatmap height is derived from its matrix dimensions", () => {
  includesAll(sources.correlation, [
    'data-matrix-height={dimensions.height.toFixed(0)}',
    "dimensions.cellSize",
    "dimensions.height",
  ]);
});

check("7. Readable heatmap has no default internal vertical scroll", () => {
  assert.ok(sources.correlation.includes("data-default-vertical-scroll={"));
  assert.ok(
    sources.correlation.includes(
      '!isExpanded && matrixViewMode === "readable" ? "false" : "bounded"',
    ),
  );
  assert.match(
    sources.correlation,
    /matrixViewMode === "compact"[\s\S]{0,180}\? "relative overflow-auto overscroll-contain max-h-\[34rem\]"[\s\S]{0,120}: "relative overflow-visible"/,
  );
});

check("8. Relationship Explorer is first-class and never disclosure-gated", () => {
  includesAll(sources.step, [
    'data-testid="eda-relationship-explorer-section"',
    "<RelationshipExplorer",
  ]);
  assert.doesNotMatch(sources.step, /relationshipExplorerOpen/);
});

check("9. The visible relationship entry exposes 2D, density, and 3D modes", () => {
  includesAll(sources.relationship, [
    "2D Scatter",
    "Density",
    "3D Explorer",
  ]);
});

check("10. The 3D WebGL engine remains behind a second lazy boundary", () => {
  assert.match(
    sources.relationship,
    /lazy\(\(\) => import\("\.\/RelationshipWebGL"\)\)/,
  );
  assert.ok(sources.relationshipWebGl.includes('from "echarts-gl/charts"'));
  assert.doesNotMatch(sources.step, /echarts-gl/);
});

check("11. Canonical EDA documentation payload is generated for all six sections", () => {
  assert.deepEqual(
    Object.keys(generated.sections).sort(),
    [
      "findings",
      "overview",
      "predictors",
      "relationships",
      "stability_and_segments",
      "target",
    ],
  );
  assert.equal(generated.eda_analysis_version.startsWith("eda-"), true);
  assert.equal(generated.unresolved_blocking_findings.length, 0);
});

check("11b. Governed artifact identity and methods reach MDD without duplicate nesting", () => {
  const contract = generated.sections.overview.governed_analytical_contract;
  assert.equal(contract.artifact_id, governedContract.artifact_id);
  assert.equal(contract.artifact_hash, governedContract.artifact_hash);
  assert.equal(contract.created_at, governedContract.created_at);
  assert.equal(contract.predictor_artifacts, undefined);
  assert.equal(contract.relationship_artifact, undefined);
  assert.equal(
    generated.sections.predictors.governed_predictor_artifacts
      .ExternalRiskEstimate.iv_woe.binning_method,
    governedPredictorArtifacts.ExternalRiskEstimate.iv_woe.binning_method,
  );
  assert.equal(
    generated.sections.predictors.governed_predictor_artifacts
      .ExternalRiskEstimate.ordinary_outlier.calculation_method,
    governedPredictorArtifacts.ExternalRiskEstimate.ordinary_outlier
      .calculation_method,
  );
  assert.equal(
    generated.sections.relationships.governed_relationship_artifact.artifact_id,
    governedRelationshipArtifact.artifact_id,
  );
});

check("11c. Volatile artifact execution metadata does not change EDA analysis identity", () => {
  const reloaded = JSON.parse(JSON.stringify(baseInput));
  reloaded.sections.overview.governed_analytical_contract.created_at =
    "2026-08-01T11:00:00Z";
  reloaded.sections.predictors.governed_predictor_artifacts.ExternalRiskEstimate.generated_at =
    "2026-08-01T11:00:00Z";
  reloaded.sections.relationships.governed_relationship_artifact.cache_status =
    "hit";
  reloaded.sections.overview.duration_ms = 999;
  reloaded.sections.overview.cache_status = "hit";
  const afterRestart = buildPayload(reloaded);
  assert.equal(afterRestart.eda_analysis_version, generated.eda_analysis_version);
  assert.equal(
    afterRestart.sections.overview.governed_analytical_contract.created_at,
    "2026-08-01T11:00:00Z",
  );
});

check("11d. Exact backend documentation record wins over browser-local review state", () => {
  const recovered = payloadModule.exports.hydrateEdaFindingsFromDocumentation(
    {
      ...generated,
      updated_at: "2026-08-01T12:00:00Z",
      duplicate_decision:
        "Keep duplicate rows as documented repeated observations.",
      reviewer_record: {
        ...generated.reviewer_record,
        overall_conclusion: "Recovered governed conclusion.",
        reviewer_commentary: "Recovered governed commentary.",
        overall_review_status: "accepted_with_conditions",
        required_conditions: ["Independent validation review."],
      },
      sections: {
        ...generated.sections,
        findings: {
          ...generated.sections.findings,
          parent_findings: [
            {
              parent_id: "eda-parent-recovered",
              reviewer_disposition: "rejected",
              reviewer_rationale: "Reviewed and not adopted.",
              downstream_destination: null,
              suggested_transformation: "No transformation",
            },
          ],
        },
      },
    },
    {
      commentary: "Stale browser commentary.",
      status: "draft",
      overallConclusion: "Stale browser conclusion.",
    },
  );
  assert.equal(recovered.commentary, "Recovered governed commentary.");
  assert.equal(recovered.overallConclusion, "Recovered governed conclusion.");
  assert.equal(recovered.status, "accepted_with_conditions");
  assert.equal(recovered.duplicateTreatment, "keep");
  assert.equal(
    recovered.parentDecisions["eda-parent-recovered"].disposition,
    "rejected",
  );
  assert.deepEqual(
    Array.from(recovered.requiredConditions),
    ["Independent validation review."],
  );
});

check("12. Confirmation persists a server snapshot consumed by MDD", () => {
  includesAll(sources.step, [
    "confirmEdaDocumentation",
    "confirmation.documentation_version",
    "getEdaDocumentationState",
  ]);
  includesAll(sources.studio, ["<EdaDocumentationLiveLink", "projectId={projectId}"]);
  includesAll(sources.api, ["/eda/completion", "idempotency_key"]);
  includesAll(sources.router, ["EDACompletionRequest", "complete_eda_governance"]);
  includesAll(sources.backend, ["def complete(", "completion_sequence", "current_confirmation_id", "approvals"]);
  includesAll(sources.step, ["evidenceId", "sourceRunReference"]);
});

check("13. Upstream changes save a separate draft and mark approval stale", () => {
  includesAll(sources.step, [
    "saveEdaDocumentationDraft",
    "approvedVersion === payload.eda_analysis_version",
    "requires reconfirmation",
  ]);
  includesAll(sources.backend, ["_mark_current_stale", "_auto_invalidate", "changed_sections"]);
});

check("14. MDD separates approved content, draft changes, and stale status", () => {
  includesAll(sources.mdd, [
    "Current approved EDA documentation",
    "Draft changes",
    "Stale after upstream change",
    "Not approved",
  ]);
});

check("15. Confirmation actor, time, version, lineage, and evidence are audited", () => {
  includesAll(sources.backend, [
    '"confirmed_at": confirmed_at',
    '"confirmed_by": actor["user_id"]',
    '"documentation_version"',
    '"governed_context"',
    '"evidenceIds"',
  ]);
  assert.doesNotMatch(sources.backendTypes, /confirmed_by:\s*str/);
});

check("16. CLASS_TRAIN code remains visibly mismatched against HELOC_TRAIN", () => {
  includesAll(sources.codeSafety, [
    'CODE_CONTEXT_WARNING = "This edited code was created for a different dataset or target."',
  ]);
  includesAll(sources.codeWorkspace, [
    "Keep historical draft",
    "Reset to current generated code",
    "View diff",
    "Save as separate notebook version",
  ]);
});

check("17. Stale code evidence requires exact-context acknowledgement", () => {
  includesAll(sources.pythonPanel, [
    "acknowledgeCodeDraftContext",
    "pythonContextEvaluation.canUseAsCurrent",
    "sasContextEvaluation.canUseAsCurrent",
  ]);
  includesAll(sources.codeSafety, [
    "draftIdentity",
    "currentContextIdentity",
    "acknowledgement",
  ]);
});

check("18. RiskPerformance is documented and excluded from selected predictors", () => {
  assert.deepEqual(generated.target_source_exclusions, ["RiskPerformance"]);
  assert.equal(
    generated.sections.predictors.selected_predictors.includes(
      "RiskPerformance",
    ),
    false,
  );
  assert.equal(generated.target, "bad_flag");
});

check("19. Predictor inventory is bound to the exact manifest identity", () => {
  assert.equal(generated.predictor_manifest_id, "pm-heloc-v1");
  assert.deepEqual(generated.sections.predictors.selected_predictors, [
    "ExternalRiskEstimate",
    "MSinceOldestTradeOpen",
  ]);
  assert.ok(sources.backend.includes("_assert_active_scope"));
});

check("20. Browser acceptance explicitly fails on uncaught page errors", () => {
  includesAll(sources.e2e, [
    'page.on("pageerror"',
    'page.on("console"',
    "expect(pageErrors)",
  ]);
});

check("21. Supported 1366, 1536, and 1920 layouts are exercised", () => {
  includesAll(sources.e2e, [
    "1366",
    "768",
    "1536",
    "864",
    "1920",
    "1080",
  ]);
  assert.ok(sources.styles.includes("@media"));
});

check("22. Motion has a reduced-motion fallback", () => {
  includesAll(sources.styles, [
    "@keyframes eda-tab-enter",
    "@keyframes eda-grow",
    "@keyframes eda-ring-enter",
    "@media (prefers-reduced-motion: reduce)",
    "animation: none !important",
  ]);
});

check("23. Confirmation retries cannot duplicate documentation versions", () => {
  includesAll(sources.backend, [
    "idempotent=True",
    "payload_digest",
    "performance_metadata",
  ]);
  assert.ok(
    sources.backendTests.includes(
      "test_identical_confirmation_is_idempotent_and_non_duplicating",
    ),
  );
});

check("24. Project reopen restores the confirmed EDA record", () => {
  assert.ok(
    sources.backendTests.includes(
      "test_dataset_version_change_invalidates_and_reopen_restores_state",
    ),
  );
  assert.ok(sources.backend.includes("def _read("));
});

check("25. Dataset or version changes invalidate approved EDA documentation", () => {
  includesAll(sources.backend, [
    "changed_fields",
    "active_lineage",
    "approved_lineage",
    "The active governed EDA lineage changed after confirmation",
  ]);
  assert.ok(
    sources.backendTests.includes('self.context["dataset_version"] = "heloc-v2"'),
  );
});

for (const [index, result] of checks.entries()) {
  console.log(`${result.ok ? "ok" : "not ok"} ${index + 1} - ${result.name}`);
}

const failures = checks.filter((result) => !result.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(`\n${failure.name}\n${failure.error?.stack ?? failure.error}`);
  }
  process.exitCode = 1;
} else {
  console.log(
    `\nedaPremiumIntegration.test.mjs: all ${checks.length} checks passed.`,
  );
}
