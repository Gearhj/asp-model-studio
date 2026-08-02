import { expect, test } from "@playwright/test";
import {
  parseLockedSelectionDecision,
  rankVerifiedSelectionCandidates,
  resolvePromotionReadiness,
  selectionMetricLabel,
  verifiedSelectionMetric,
} from "../../src/lib/selectionProvenance";

const metric = (overrides: Record<string, unknown> = {}) => ({
  name: "pr_auc",
  value: 0.72,
  source: "cross_validation_mean",
  partition_id: "train-partition-1",
  fold_definition_id: "folds-1",
  fold_count: 3,
  fold_values: [0.7, 0.72, 0.74],
  mean: 0.72,
  standard_deviation: 0.0163,
  out_of_fold_prediction_artifact_id: "",
  threshold_source: "frozen_cross_validation",
  calibration_source: "fold_local",
  created_at: "2026-07-31T12:00:00Z",
  ...overrides,
});

const candidate = (
  id: string,
  value: number,
  extras: Record<string, unknown> = {},
) => ({
  candidate_id: id,
  training_run_id: `run-${id}`,
  key: id,
  selection_metric: metric({
    value,
    mean: value,
    fold_values: [value - 0.01, value, value + 0.01],
  }),
  selection_integrity_status: "verified",
  holdout_isolation_status: "verified",
  ...extras,
});

const decision = (selected = candidate("a", 0.72)) => ({
  decision_id: "decision-1",
  status: "locked",
  selected_candidate_id: selected.candidate_id,
  training_run_id: selected.training_run_id,
  selection_metric: selected.selection_metric,
  selection_ranking_snapshot_hash: "ranking-sha256",
  selection_locked_at: "2026-07-31T12:01:00Z",
  actor: { user_id: "reviewer-1" },
});

const evaluationPackage = (selected = candidate("a", 0.72)) => ({
  evaluation_package_id: "eval-1",
  status: "complete",
  candidate_id: selected.candidate_id,
  training_run_id: selected.training_run_id,
  candidate_decision_id: "decision-1",
  selection_integrity_status: "verified",
  isolation_status: "verified",
  selection_evidence: {
    candidate_id: selected.candidate_id,
    candidate_decision_id: "decision-1",
    selection_metric: selected.selection_metric,
  },
  final_holdout_evidence: {
    candidate_id: selected.candidate_id,
    candidate_decision_id: "decision-1",
    evaluation_package_id: "eval-1",
    metric_source: "final_holdout",
    role: "reporting_only",
    metrics: { pr_auc: 0.68 },
  },
  holdout_exposure: {
    status: "evaluated",
    first_opened_at: "2026-07-31T12:02:00Z",
    candidate_decision_id: "decision-1",
    evaluation_package_id: "eval-1",
  },
});

test("selection ranking ignores final-holdout fields and is deterministic", () => {
  const rows = [
    candidate("b", 0.75, { final_holdout_metric: { pr_auc: 0.1 } }),
    candidate("a", 0.75, { final_holdout_metric: { pr_auc: 0.99 } }),
    candidate("c", 0.7, { final_holdout_metric: { pr_auc: 1 } }),
  ];
  expect(
    rankVerifiedSelectionCandidates(rows, "pr_auc", false).map(
      (row) => row.candidate_id,
    ),
  ).toEqual(["a", "b", "c"]);

  const changedHoldout = rows.map((row, index) => ({
    ...row,
    final_holdout_metric: { pr_auc: index / 10 },
  }));
  expect(
    rankVerifiedSelectionCandidates(
      changedHoldout,
      "pr_auc",
      false,
    ).map((row) => row.candidate_id),
  ).toEqual(["a", "b", "c"]);
});

test("fold outcome changes can change the selection leaderboard", () => {
  const rows = [candidate("a", 0.71), candidate("b", 0.7)];
  expect(
    rankVerifiedSelectionCandidates(rows, "pr_auc", false)[0]
      .candidate_id,
  ).toBe("a");
  rows[1] = candidate("b", 0.74);
  expect(
    rankVerifiedSelectionCandidates(rows, "pr_auc", false)[0]
      .candidate_id,
  ).toBe("b");
});

test("missing, final-holdout, and failed integrity evidence cannot rank", () => {
  const valid = candidate("valid", 0.7);
  const rows = [
    valid,
    candidate("holdout", 0.99, {
      selection_metric: metric({ source: "final_holdout" }),
    }),
    candidate("missing", 0.98, { selection_metric: undefined }),
    candidate("invalid", 0.97, {
      selection_integrity_status: "invalid_final_holdout_ranking",
    }),
    candidate("unisolated", 0.96, {
      holdout_isolation_status: "failed",
    }),
  ];
  expect(
    rankVerifiedSelectionCandidates(rows, "pr_auc", false).map(
      (row) => row.candidate_id,
    ),
  ).toEqual(["valid"]);
  expect(verifiedSelectionMetric(rows[1], "pr_auc")).toBeNull();
});

test("selection metric labels state the non-holdout source", () => {
  expect(selectionMetricLabel(metric() as never)).toBe(
    "PR-AUC - cross-validation mean",
  );
});

test("locked decision is exact and promotion readiness passes only a clean package", () => {
  const selected = candidate("a", 0.72);
  expect(parseLockedSelectionDecision(decision(selected))).not.toBeNull();
  const ready = resolvePromotionReadiness(
    selected,
    decision(selected),
    evaluationPackage(selected),
  );
  expect(ready.ready).toBe(true);
  expect(ready.candidateDecisionId).toBe("decision-1");
  expect(ready.evaluationPackageId).toBe("eval-1");
});

test("promotion fails closed for unlocked, contaminated, or incomplete evidence", () => {
  const selected = candidate("a", 0.72);
  expect(
    resolvePromotionReadiness(
      selected,
      { ...decision(selected), status: "proposed" },
      evaluationPackage(selected),
    ).ready,
  ).toBe(false);
  expect(
    resolvePromotionReadiness(selected, decision(selected), {
      ...evaluationPackage(selected),
      selection_integrity_status: "invalid_final_holdout_ranking",
    }).ready,
  ).toBe(false);
  expect(
    resolvePromotionReadiness(selected, decision(selected), {
      ...evaluationPackage(selected),
      isolation_status: "failed",
    }).ready,
  ).toBe(false);
  expect(
    resolvePromotionReadiness(selected, decision(selected), {
      ...evaluationPackage(selected),
      status: "draft",
    }).ready,
  ).toBe(false);
  expect(
    resolvePromotionReadiness(selected, decision(selected), {
      ...evaluationPackage(selected),
      final_holdout_evidence: {
        ...evaluationPackage(selected).final_holdout_evidence,
        metric_source: "cross_validation_mean",
      },
    }).ready,
  ).toBe(false);
});
