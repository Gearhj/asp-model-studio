import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const read = async (path) =>
  (await readFile(new URL(`../${path}`, import.meta.url), "utf8")).replace(
    /\r\n/g,
    "\n",
  );

const [findingSource, governanceSource, payloadSource, workspaceSource, mddSource] =
  await Promise.all([
    read("src/lib/edaFindings.ts"),
    read("src/lib/edaFindingGovernance.ts"),
    read("src/lib/edaDocumentationPayload.ts"),
    read("src/components/eda/FindingsDecisionWorkspace.tsx"),
    read("src/components/documentation/EdaDocumentationLiveLink.tsx"),
  ]);

const transpile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;

const findingHelper = await import(
  `data:text/javascript;base64,${Buffer.from(transpile(findingSource)).toString("base64")}`
);
globalThis.__atlasEdaFindingHelper = findingHelper;
const compiledGovernance = transpile(governanceSource).replace(
  /import\s*\{[^}]*generateEdaFindings[^}]*\}\s*from\s*["']\.\/edaFindings["'];?/s,
  "const { generateEdaFindings } = globalThis.__atlasEdaFindingHelper;",
);
const governance = await import(
  `data:text/javascript;base64,${Buffer.from(compiledGovernance).toString("base64")}`
);

const fixture = {
  overview: {
    target: "bad_flag",
    headline: { rows: 1000, duplicate_rows: 12 },
    data_integrity: { duplicate_rows: 12 },
    predictor_authorization: { target_source_excluded: ["RiskPerformance"] },
  },
  target: {
    target: "bad_flag",
    profile: { event_rate: 0.48, event_count: 480, valid_count: 1000 },
  },
  predictors: {
    target: "bad_flag",
    predictor_visual_profiles: [
      {
        feature: "ExternalRiskEstimate",
        metrics: { iv: 0.82, monotonicity: "non_monotonic" },
        event_rate_shape: { groups: [{ event_rate: 0.1 }, { event_rate: 0.4 }] },
      },
    ],
  },
  relationships: {
    strong_pairs: [
      {
        feature_a: "NumInqLast6M",
        feature_b: "NumInqLast6Mexcl7days",
        correlation: 0.93,
      },
    ],
    vif: [{ feature: "NumInqLast6M", vif: 52.87 }],
  },
  stability: { time_profile: [], segment_profile: [] },
  findings: { findings: [] },
};

test("parent groups preserve immutable child evidence and required counts", () => {
  const parents = governance.generateEdaParentFindings(fixture);
  const duplicate = parents.find((row) => row.family === "exact_duplicate_rows");
  const inquiry = parents.find(
    (row) => row.family === "inquiry_multicollinearity_cluster",
  );
  const stability = parents.find(
    (row) => row.family === "stability_segments_unavailable",
  );
  assert.ok(duplicate);
  assert.ok(inquiry);
  assert.ok(stability);
  assert.equal(stability.requirement, "informational");
  assert.equal(
    governance.resolveParentFindingDecision(stability, {
      commentary: "",
      status: "draft",
    }).disposition,
    "not_applicable",
  );
  assert.ok(Object.isFrozen(inquiry.childEvidence));
  assert.ok(inquiry.childEvidence.every(Object.isFrozen));
  const summary = governance.summarizeFindingGovernance(parents, {
    commentary: "",
    status: "draft",
  });
  assert.equal(
    summary.required_parent_finding_count,
    parents.filter((row) => row.requirement !== "informational").length,
  );
  assert.ok(summary.unresolved_parent_finding_count > 0);
  assert.equal(
    summary.child_evidence_count,
    parents.reduce((total, parent) => total + parent.childIds.length, 0),
  );
});

test("eligible governed dispositions replace universal acceptance", () => {
  const parents = governance.generateEdaParentFindings(fixture);
  const parentDecisions = Object.fromEntries(
    parents
      .filter((parent) => parent.requirement !== "informational")
      .map((parent) => [
        parent.parentId,
        {
          disposition: "rejected",
          rationale: "Evidence reviewed; the recommendation is not adopted.",
          destination: "",
          transformation: "No transformation",
          ...(parent.family === "exact_duplicate_rows"
            ? { resolutionAction: "retain_current_population" }
            : {}),
        },
      ]),
  );
  const state = {
    commentary: "Reviewer commentary is complete.",
    overallConclusion: "EDA is suitable for governed carry-forward.",
    status: "accepted",
    parentDecisions,
  };
  const result = governance.evaluateFindingsCompletionEligibility(
    parents,
    state,
  );
  assert.equal(result.eligible, true);
  assert.equal(result.governance.unresolved_parent_finding_count, 0);
  assert.equal(result.stability_not_applicable, true);
});

test("informational parents retain their canonical system disposition", () => {
  const parents = governance.generateEdaParentFindings(fixture);
  const informational = parents.find(
    (parent) =>
      parent.requirement === "informational" && parent.systemDisposition,
  );
  assert.ok(informational);
  const tamperedState = {
    commentary: "Reviewed.",
    overallConclusion: "Suitable for governed carry-forward.",
    status: "accepted",
    parentDecisions: {
      [informational.parentId]: {
        disposition: "accepted",
        rationale: "A stale browser draft attempted to change system evidence.",
        destination: "Feature Engineering",
        transformation: "No transformation",
      },
    },
  };
  const decision = governance.resolveParentFindingDecision(
    informational,
    tamperedState,
  );
  assert.equal(decision.disposition, informational.systemDisposition);
  assert.equal(
    governance.isEligibleParentDisposition(informational, decision),
    true,
  );
  const row = governance
    .documentedParentFindingRows(parents, tamperedState)
    .find((item) => item.parent_id === informational.parentId);
  assert.equal(row.reviewer_disposition, informational.systemDisposition);
  assert.equal(row.decision_origin, "system_informational_default");
  assert.throws(
    () =>
      governance.applyBulkParentDisposition({
        parents,
        state: tamperedState,
        family: informational.family,
        disposition: "accepted",
        rationale: "Attempted bulk mutation.",
        destination: "Feature Engineering",
        actor: "Reviewer",
      }),
    /canonical system disposition/i,
  );
});

test("overall acceptance never implicitly accepts child evidence", () => {
  const rows = findingHelper.documentedFindingRows(fixture, {
    commentary: "Reviewed.",
    overallConclusion: "Accepted at the overall EDA level.",
    status: "accepted",
  });
  assert.ok(rows.length > 0);
  assert.ok(
    rows.every((row) => row.reviewer_disposition === "unresolved"),
  );
});

test("governed finding inventory is invariant to full-population holdout-only changes", () => {
  const governed = {
    overview: {
      target: "bad_flag",
      predictor_authorization: { target_source_excluded: ["RiskPerformance"] },
    },
    target: {
      governed_target_artifact: {
        target: "bad_flag",
        problem_type: "classification",
        event_rate: 0.4,
        event_count: 32,
        valid_count: 80,
        missing_count: 0,
      },
    },
    predictors: {
      governed_predictor_artifacts: {
        ExternalRiskEstimate: {
          iv: 0.7,
          iv_woe: {
            bins: [
              { bin_type: "ordinary_valid_range", event_rate: 0.2 },
              { bin_type: "ordinary_valid_range", event_rate: 0.6 },
            ],
          },
          monotonicity: { valid_value_shape: "Non-monotonic" },
          value_classification: {
            development_counts: {
              true_null: 8,
              bureau_special_value: 8,
              ordinary_valid_value: 64,
              parse_failure: 0,
              ordinary_numeric_outlier: 2,
            },
            full_population_counts: { true_null: 1000 },
          },
          special_values: {
            groups: [{ population_share: 0.1 }],
            full_population_groups: [{ population_share: 0.9 }],
          },
          ordinary_outlier: { rate: 0.95 },
        },
      },
    },
    relationships: {
      governed_relationship_artifact: {
        correlation: {
          columns: ["ExternalRiskEstimate"],
          pearson_matrix: [[1]],
        },
        vif: [],
      },
    },
    stability: { time_profile: [], segment_profile: [] },
    findings: { findings: [] },
  };
  const baseline = findingHelper.generateEdaFindings(governed);
  const changed = structuredClone(governed);
  const artifact =
    changed.predictors.governed_predictor_artifacts.ExternalRiskEstimate;
  artifact.value_classification.full_population_counts = {
    true_null: 0,
    ordinary_valid_value: 50000,
  };
  artifact.special_values.full_population_groups = [];
  artifact.ordinary_outlier = { rate: 0, count: 0 };
  changed.overview.headline = { missing_cells: 99999 };
  assert.deepEqual(findingHelper.generateEdaFindings(changed), baseline);
  assert.equal(
    baseline.some((row) => row.metricLabel === "Ordinary-outlier rate"),
    false,
  );
});

test("blockers and accepted-with-conditions remain fail closed", () => {
  const parents = governance.generateEdaParentFindings(fixture);
  const blocker = parents.find((parent) => parent.requirement === "blocker");
  const state = {
    commentary: "Reviewed.",
    overallConclusion: "Conditionally suitable.",
    status: "accepted_with_conditions",
    parentDecisions: {
      [blocker.parentId]: {
        disposition: "deferred",
        rationale: "Deferred pending review.",
        destination: "Validation",
        transformation: "No transformation",
      },
    },
  };
  const result = governance.evaluateFindingsCompletionEligibility(parents, state);
  assert.equal(result.eligible, false);
  assert.match(result.blockers.join(" "), /required parent finding/i);
  assert.match(result.blockers.join(" "), /at least one documented condition/i);
});

test("bulk disposition audits every parent and child without mutation", () => {
  const parents = governance.generateEdaParentFindings(fixture);
  const family = parents.find(
    (parent) => parent.requirement === "required",
  ).family;
  const before = JSON.stringify(fixture);
  const next = governance.applyBulkParentDisposition({
    parents,
    state: { commentary: "", status: "draft" },
    family,
    disposition: "deferred",
    rationale: "Send this family for downstream expert review.",
    destination: "Feature Engineering",
    actor: "Reviewer 17",
    timestamp: "2026-08-01T12:00:00.000Z",
  });
  const audit = next.bulkDispositionAudit[0];
  assert.equal(audit.actor, "Reviewer 17");
  assert.equal(audit.timestamp, "2026-08-01T12:00:00.000Z");
  assert.ok(audit.parentIds.length > 0);
  assert.ok(audit.childIds.length > 0);
  assert.equal(Object.keys(audit.priorStatuses).length, audit.parentIds.length);
  assert.equal(JSON.stringify(fixture), before);
});

test("governed evidence carries only parent proposals and immutable children", () => {
  const parents = governance.generateEdaParentFindings(fixture);
  const required = parents.find(
    (parent) => parent.requirement === "required",
  );
  const evidence = governance.buildGovernedFindingEvidencePayload(fixture, {
    commentary: "Reviewed.",
    status: "accepted",
    parentDecisions: {
      [required.parentId]: {
        disposition: "deferred",
        rationale: "Carry to downstream expert review.",
        destination: "Feature Engineering",
        transformation: "No transformation",
      },
    },
  });
  const proposal = evidence.carryForward.find(
    (row) => row.parent_id === required.parentId,
  );
  assert.ok(proposal);
  assert.equal(proposal.mutationApplied, false);
  assert.ok(proposal.child_ids.length > 0);
  assert.equal("finding_id" in proposal, false);
  assert.ok(evidence.childEvidence.every((row) => row.immutable === true));
  assert.equal(evidence.automaticTransformationsApplied, false);
});

test("generated reviewer draft is editable and explicitly non-approving", () => {
  const parents = governance.generateEdaParentFindings(fixture);
  const draft = governance.buildOptionalReviewerDraft(
    parents,
    { commentary: "", status: "draft" },
    "2026-08-01T12:00:00.000Z",
  );
  assert.equal(draft.nonApproving, true);
  assert.match(draft.commentary, /does not approve EDA/i);
  assert.equal(draft.generatedAt, "2026-08-01T12:00:00.000Z");
});

test("frontend presents parent governance, optional draft, and structured MDD staleness", () => {
  for (const marker of [
    "eda-parent-findings-workspace",
    "eda-parent-child-evidence",
    "eda-parent-finding-review-controls",
    "eda-findings-bulk-disposition",
    "eda-generate-reviewer-draft",
    "data-generated-draft-non-approving",
  ]) {
    assert.match(workspaceSource, new RegExp(marker));
  }
  for (const field of [
    "parent_findings",
    "finding_groups",
    "required_parent_finding_count",
    "unresolved_parent_finding_count",
    "bulk_disposition_audit",
    "reviewer_record",
    "stability_limitation",
    "governance_contract_version",
  ]) {
    assert.match(payloadSource, new RegExp(field));
  }
  assert.match(mddSource, /Review stale documentation/);
  assert.match(mddSource, /Changed source fields/);
  assert.match(mddSource, /Analytical staleness/);
  assert.match(mddSource, /Narrative-only staleness/);
});

delete globalThis.__atlasEdaFindingHelper;
