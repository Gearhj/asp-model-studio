// Regression Stage B: independent metric validator. Recomputes MAE/MSE/RMSE/R2
// from raw y_true/y_score arrays returned by a live /train/last payload and
// asserts they match the backend-reported metrics to floating point tolerance.
// This is the automated form of the manual independent-verification pass done
// during the Regression Stage B audit (Phase 2 item 4 of the report).
//
// Seeding reuses tests/e2e/helpers/seedTrainedRegressionProject.py (proven
// working, already used by the Regression Stage B Playwright spec) rather
// than reimplementing cookie-jar HTTP handling in Node.
import assert from "node:assert/strict";
import test from "node:test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = "http://127.0.0.1:8001/api";
const PYTHON = path.join(__dirname, "..", ".venv", "Scripts", "python.exe");
const SEED_SCRIPT = path.join(__dirname, "e2e", "helpers", "seedTrainedRegressionProject.py");
const HERMETIC = process.env.ATLAS_HERMETIC_MODE === "HERMETIC_REGRESSION";

function recomputeRegressionMetrics(yTrue, yPred) {
  const n = yTrue.length;
  const errors = yTrue.map((yt, i) => yt - yPred[i]);
  const mae = errors.reduce((sum, e) => sum + Math.abs(e), 0) / n;
  const mse = errors.reduce((sum, e) => sum + e * e, 0) / n;
  const rmse = Math.sqrt(mse);
  const meanY = yTrue.reduce((sum, y) => sum + y, 0) / n;
  const ssTot = yTrue.reduce((sum, y) => sum + (y - meanY) ** 2, 0);
  const ssRes = errors.reduce((sum, e) => sum + e * e, 0);
  const r2 = ssTot ? 1 - ssRes / ssTot : null;
  return { mae, mse, rmse, r2 };
}

test("independently recomputed MAE/MSE/RMSE/R2 match backend-reported regression metrics", { timeout: 240_000 }, async () => {
  let summary;
  let cleanup = async () => {};
  if (HERMETIC) {
    // Recorded backend-shaped payload for the pure independent validator. The
    // live acceptance path below still seeds and reads /train/last.
    summary = {
      problem_type: "regression",
      raw: {
        linreg: {
          y_true: [-2, 0, 2, 4],
          y_score: [-1, 0.5, 2.5, 5],
          metrics: {
            mae: 0.75,
            mse: 0.625,
            rmse: 0.7905694150420949,
            r2: 0.875,
            accuracy: null,
            precision: null,
            recall: null,
            f1: null,
            confusion_matrix: null,
          },
        },
      },
    };
  } else {
    const stdout = execFileSync(PYTHON, [SEED_SCRIPT, "E2E Metric Validator Regression"], { encoding: "utf-8" });
    const seed = JSON.parse(stdout.trim().split("\n").pop());
    assert.equal(seed.training_status, "complete");
    const sessionCookie = seed.cookies.atlas_session;
    const response = await fetch(`${BASE}/train/last?project_id=${seed.project_id}`, {
      headers: { Cookie: `atlas_session=${sessionCookie}` },
    });
    const payload = await response.json();
    summary = payload.summary;
    cleanup = async () => {
      await fetch(`${BASE}/projects/${seed.project_id}`, { method: "DELETE", headers: { Cookie: `atlas_session=${sessionCookie}` } });
    };
  }

  try {
    assert.equal(summary.problem_type, "regression");
    const raw = summary.raw.linreg;
    const recomputed = recomputeRegressionMetrics(raw.y_true, raw.y_score);
    const backend = raw.metrics;

    assert.ok(Math.abs(recomputed.mae - backend.mae) < 1e-9, `MAE mismatch: ${recomputed.mae} vs ${backend.mae}`);
    assert.ok(Math.abs(recomputed.mse - backend.mse) < 1e-9, `MSE mismatch: ${recomputed.mse} vs ${backend.mse}`);
    assert.ok(Math.abs(recomputed.rmse - backend.rmse) < 1e-9, `RMSE mismatch: ${recomputed.rmse} vs ${backend.rmse}`);
    assert.ok(Math.abs(recomputed.r2 - backend.r2) < 1e-9, `R2 mismatch: ${recomputed.r2} vs ${backend.r2}`);

    // Regression predictions must not be artificially constrained to [0, 1] --
    // a linear model is free to extrapolate below/above the observed target range.
    const minPred = Math.min(...raw.y_score);
    const maxPred = Math.max(...raw.y_score);
    assert.ok(minPred < 0 || maxPred > 1, "predictions look suspiciously constrained to a [0,1]-like range for a regression model");

    // Classification-only keys must be present-but-null for schema consistency, never populated.
    assert.equal(backend.accuracy, null);
    assert.equal(backend.precision, null);
    assert.equal(backend.recall, null);
    assert.equal(backend.f1, null);
    assert.equal(backend.confusion_matrix, null);
  } finally {
    await cleanup();
  }
});
