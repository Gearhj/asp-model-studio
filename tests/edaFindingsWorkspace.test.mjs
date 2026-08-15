import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const read = async (path) =>
  (await readFile(new URL(`../${path}`, import.meta.url), "utf8")).replace(
    /\r\n/g,
    "\n",
  );

const [helperSource, workspaceSource, documentationSource] = await Promise.all([
  read("src/lib/edaFindings.ts"),
  read("src/components/eda/FindingsDecisionWorkspace.tsx"),
  read("src/lib/edaDocumentationPayload.ts"),
]);

const compiledHelper = ts.transpileModule(helperSource, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const helper = await import(
  `data:text/javascript;base64,${Buffer.from(compiledHelper).toString("base64")}`
);

test("findings page separates finding disposition from reviewer sign-off", () => {
  for (const phrase of [
    "Finding Disposition Workspace",
    "Parent findings · Disposition · Bulk actions",
    "EDA Reviewer Summary",
    "Overall conclusion · Reviewer comments · Conditions · Overall status · Save to Evidence",
    "The Continue button requires this summary",
  ]) {
    assert.match(workspaceSource, new RegExp(phrase));
  }
});

const fixture = {
  overview: {
    target: "bad_flag",
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
      target_source_excluded: ["RiskPerformance"],
    },
  },
  target: {
    target: "bad_flag",
    profile: {
      event_rate: 0.07,
      event_count: 700,
      valid_count: 10_000,
    },
    target_quality: {
      missing_target_count: 0,
      invalid_target_values: [],
      unexpected_target_values: [],
      duplicate_target_bearing_rows: 17,
      target_derived_candidates: [],
      post_outcome_candidates: [
        {
          feature: "DecisionOutcome",
          assessment: "Review recommended",
          reason: "The field name suggests post-decision availability.",
        },
      ],
      perfect_relationship_candidates: [],
    },
  },
  predictors: {
    target: "bad_flag",
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
        metrics: {
          iv: 9.9,
          missing_rate: 0,
          distinct_count: 2,
        },
      },
      {
        feature: "bad_flag",
        kind: "categorical",
        metrics: {
          iv: 9.9,
          missing_rate: 0,
          distinct_count: 2,
        },
      },
    ],
  },
  relationships: {
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

test("auto-generated inventory consolidates every loaded EDA evidence family", () => {
  const inventory = helper.generateEdaFindings(fixture);
  for (const category of [
    "Data quality",
    "Target",
    "Predictors",
    "Relationships",
    "Stability",
  ]) {
    assert.ok(
      inventory.some((item) => item.category === category),
      `Expected a ${category} finding`,
    );
  }
  assert.ok(
    inventory.some((item) => item.title.includes("duplicate")),
    "Duplicate evidence should become a finding.",
  );
  assert.ok(
    inventory.some((item) => item.title.includes("unavailable")),
    "Honest stability unavailability should be documented.",
  );
  assert.ok(
    inventory.some(
      (item) =>
        item.category === "Target" &&
        item.affectedVariables.includes("DecisionOutcome") &&
        item.leakageEvidence.includes("post-decision"),
    ),
    "Applicable target leakage candidates should preserve their evidence.",
  );
});

test("high IV is a conservative review signal with lineage and shape context", () => {
  const inventory = helper.generateEdaFindings(fixture);
  const highIv = inventory.find((item) => item.iv >= 0.5);
  assert.ok(highIv);
  assert.equal(highIv.affectedVariables[0], "ExternalRiskEstimate");
  assert.equal(highIv.targetSourceStatus, "not_target_source");
  assert.match(highIv.leakageEvidence, /High IV alone does not establish leakage/);
  assert.match(highIv.eventRateShape, /governed groups/);
  assert.ok(highIv.suggestedTransformations.includes("No transformation"));
  assert.ok(highIv.suggestedTransformations.includes("Investigate further"));
});

test("target and deterministic target source never enter predictor review findings", () => {
  const inventory = helper.generateEdaFindings(fixture);
  const predictorVariables = inventory
    .filter((item) => item.category === "Predictors")
    .flatMap((item) => item.affectedVariables);
  assert.ok(!predictorVariables.includes("bad_flag"));
  assert.ok(!predictorVariables.includes("RiskPerformance"));
  const lineageFinding = inventory.find(
    (item) => item.targetSourceStatus === "excluded",
  );
  assert.deepEqual(lineageFinding.affectedVariables, ["RiskPerformance"]);
});

test("accepted and rejected decisions remain distinct from unresolved items", () => {
  const inventory = helper.generateEdaFindings(fixture);
  const accepted = inventory.find((item) => item.iv >= 0.5);
  const rejected = inventory.find(
    (item) =>
      item.category === "Relationships" &&
      item.metricLabel === "Correlation",
  );
  assert.ok(accepted);
  assert.ok(rejected);
  const state = {
    commentary: "Reviewed aggregate EDA evidence.",
    status: "reviewed",
    findingDecisions: {
      [accepted.id]: {
        disposition: "accepted",
        rationale: "Availability at application time was confirmed.",
        destination: "Validation",
        transformation: "Investigate further",
      },
      [rejected.id]: {
        disposition: "rejected",
        rationale: "Both measures represent different business concepts.",
        destination: "Feature Engineering",
        transformation: "No transformation",
      },
    },
  };
  const documented = helper.documentedFindingRows(fixture, state);
  assert.equal(
    documented.find((row) => row.finding_id === accepted.id)
      .reviewer_disposition,
    "accepted",
  );
  assert.equal(
    documented.find((row) => row.finding_id === rejected.id)
      .reviewer_disposition,
    "rejected",
  );
  assert.ok(
    documented.some((row) => row.reviewer_disposition === "unresolved"),
  );
});

test("carry-forward decisions are explicitly draft and non-mutating", () => {
  const inventory = helper.generateEdaFindings(fixture);
  const selected = inventory.find((item) => item.iv >= 0.5);
  const rows = helper.documentedFindingRows(fixture, {
    commentary: "",
    status: "reviewed",
    findingDecisions: {
      [selected.id]: {
        disposition: "accepted",
        rationale: "Send to independent validation for leakage review.",
        destination: "Validation",
        transformation: "Investigate further",
      },
    },
  });
  const accepted = rows.find((row) => row.finding_id === selected.id);
  assert.equal(accepted.carry_forward_mode, "draft_recommendation");
  assert.equal(accepted.mutation_applied, false);
  assert.equal(accepted.downstream_destination, "Validation");
});

test("workspace exposes filters, detail, transformations, queue, and reviewer controls", () => {
  for (const marker of [
    'data-testid="eda-findings-decision-workspace"',
    'data-testid="eda-findings-executive-summary"',
    'data-testid="eda-findings-inventory"',
    'data-testid="eda-findings-search"',
    'data-testid="eda-findings-category-filter"',
    'data-testid="eda-findings-severity-filter"',
    'data-testid="eda-findings-status-filter"',
    'data-testid="eda-findings-sort"',
    'data-testid="eda-finding-detail"',
    'data-testid="eda-suggested-transformations"',
    'data-testid="eda-carry-forward-queue"',
    'data-testid="eda-findings-reviewer-record"',
    'data-testid="eda-accept-unresolved-parent-findings"',
  ]) {
    assert.match(workspaceSource, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(workspaceSource, /motion-reduce:transition-none/);
  assert.match(workspaceSource, /No treatment applied/);
  assert.match(workspaceSource, /Apply summary to unresolved findings/);
  assert.match(workspaceSource, /unresolved_required_parent_ids/);
});

test("legacy duplicate decision, commentary, and overall status remain present", () => {
  assert.match(workspaceSource, /data-testid="eda-duplicate-decision"/);
  assert.match(workspaceSource, /Save duplicate-row decision/);
  assert.match(workspaceSource, /Reviewer commentary/);
  assert.match(workspaceSource, /Accepted for carry-forward/);
  assert.match(workspaceSource, /logDecision/);
});

test("MDD payload canonically separates review outcomes and downstream drafts", () => {
  for (const field of [
    "approved_findings",
    "rejected_findings",
    "unresolved_items",
    "carry_forward",
    "decision_history",
    "reviewer_record",
    "overall_conclusion",
    "automatic_transformations_applied",
    "missing_rationales",
    "draft_recommendation",
    "mutation_applied",
  ]) {
    assert.match(documentationSource, new RegExp(`\\b${field}\\b`));
  }
  assert.match(documentationSource, /documentedFindingRows/);
  assert.match(documentationSource, /findingDecisions/);
});

test("population selection is deferred as a roadmap note, not implemented", () => {
  assert.match(
    workspaceSource,
    /Roadmap: Population Selection and Eligibility Waterfall/,
  );
  assert.match(workspaceSource, /Deferred from this phase/);
  assert.doesNotMatch(workspaceSource, /onApplyTransformation|applyTransformation/);
  assert.doesNotMatch(workspaceSource, /\bfetch\s*\(/);
});
