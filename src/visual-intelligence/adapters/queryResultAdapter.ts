// ATLAS Visual Intelligence Foundation -- query result adapters.
//
// Converts raw backend payloads (training summaries, DuckDB/Arrow query
// results) into typed, chart-ready rows. This is the ONE place that knows
// about the internal `y_score` field name -- everything downstream of an
// adapter call sees `prediction`, never `y_score` (Known Constraint #7: the
// backend reuses `y_score` for both classification scores and regression
// predictions; Visual Intelligence must not expose that internal name to users).
import type { ProblemType, ScoringPartition, VisualDatasetReference } from "../types";
import { referencesMatch } from "../types";

export type ClassificationRow = { rowId: string; actual: number; predictedScore: number };
export type RegressionRow = { rowId: string; actual: number; prediction: number; residual: number };

/** Rejects a raw payload whose reported context (project/dataset/model/scoring-run)
 *  does not match what the caller currently expects -- Phase H requirement: "reject
 *  mismatched project, dataset, version, model, or scoring-run context." Returns null
 *  (never throws) so callers can render an honest "stale/mismatched" state instead of
 *  crashing. */
export function acceptOrRejectContext(
  expected: VisualDatasetReference,
  received: VisualDatasetReference
): { accepted: true } | { accepted: false; reason: string } {
  if (!referencesMatch(expected, received)) {
    return { accepted: false, reason: "This result belongs to a different project, dataset, model, or scoring run than the current selection." };
  }
  return { accepted: true };
}

/** Normalizes raw actual/y_score arrays (as returned by /train/last's raw.<model>
 *  block, or a Scoring payload) into classification rows. `null`/`undefined`
 *  predictions are preserved as `null` rather than coerced to 0 -- a missing
 *  prediction is a different fact than a prediction of exactly zero. */
export function adaptClassificationRows(actual: readonly (number | null)[], predictedScore: readonly (number | null)[]): ClassificationRow[] {
  const rows: ClassificationRow[] = [];
  for (let i = 0; i < actual.length; i += 1) {
    const a = actual[i];
    const p = predictedScore[i];
    if (a === null || a === undefined || p === null || p === undefined) continue;
    rows.push({ rowId: String(i), actual: a, predictedScore: p });
  }
  return rows;
}

/** Normalizes raw actual/y_score arrays into regression rows, computing residual
 *  as actual - prediction (consistently, and labeled as such everywhere downstream --
 *  Regression Stage B's audit flagged residual-sign consistency as a defect risk). */
export function adaptRegressionRows(actual: readonly (number | null)[], yScore: readonly (number | null)[]): RegressionRow[] {
  const rows: RegressionRow[] = [];
  for (let i = 0; i < actual.length; i += 1) {
    const a = actual[i];
    const prediction = yScore[i];
    if (a === null || a === undefined || prediction === null || prediction === undefined) continue;
    rows.push({ rowId: String(i), actual: a, prediction, residual: a - prediction });
  }
  return rows;
}

export function inferPartitionLabel(partition: ScoringPartition | undefined): string {
  if (partition === "train") return "TRAIN (Development)";
  if (partition === "test") return "TEST (External Validation)";
  if (partition === "oot") return "OOT (Out-of-Time)";
  return "Unknown partition";
}

/** Guards against building a chart with the wrong vocabulary for the wrong
 *  problem type -- called defensively at each prototype's entry point. */
export function assertProblemType(expected: ProblemType, actual: ProblemType | null, componentName: string): void {
  if (actual !== null && actual !== expected) {
    throw new Error(`${componentName} is a ${expected} view but received ${actual} data. Refusing to render mismatched terminology.`);
  }
}
