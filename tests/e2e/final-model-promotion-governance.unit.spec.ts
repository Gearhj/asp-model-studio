import { expect, test } from "@playwright/test";
import {
  promoteExactCandidate,
  restoreExactFinalModel,
} from "../../src/model-registry/finalModelPromotionClient";

const selectionMetric = {
  name: "pr_auc",
  value: 0.73,
  source: "out_of_fold",
  partition_id: "train-partition-1",
  fold_definition_id: "folds-1",
  fold_count: 3,
  fold_values: [0.72, 0.73, 0.74],
  mean: 0.73,
  standard_deviation: 0.0082,
  out_of_fold_prediction_artifact_id: "oof-1",
  threshold_source: "cross_validation",
  calibration_source: "fold_local",
  created_at: "2026-07-31T12:00:00Z",
};

const candidate = {
  candidate_id: "candidate-1",
  training_job_id: "job-1",
  training_run_id: "run-1",
  project_id: "project-1",
  dataset_id: "dataset-1",
  dataset_version_id: "version-1",
  target: "target",
  feature_manifest_version: "features-1",
  validation_design_id: "validation-1",
  validation_design_version: "validation-version-1",
  split_id: "split-1",
  key: "logreg",
  name: "Logistic Regression",
  task: "classification" as const,
  selectedAt: "2026-07-31T12:00:00Z",
};

const candidateEvidence = {
  ...candidate,
  selection_metric: selectionMetric,
  selection_integrity_status: "verified",
  holdout_isolation_status: "verified",
};

const decision = {
  decision_id: "decision-1",
  status: "locked",
  selected_candidate_id: candidate.candidate_id,
  training_run_id: candidate.training_run_id,
  selection_metric: selectionMetric,
  selection_ranking_snapshot_hash: "ranking-hash",
  selection_locked_at: "2026-07-31T12:01:00Z",
  actor: { user_id: "reviewer-1" },
};

const evaluationPackage = {
  evaluation_package_id: "eval-1",
  status: "complete",
  candidate_id: candidate.candidate_id,
  training_run_id: candidate.training_run_id,
  candidate_decision_id: decision.decision_id,
  selection_integrity_status: "verified",
  holdout_isolation_status: "verified",
  isolation_status: "verified",
  package_integrity_status: "verified",
  selection_evidence: { selection_metric: selectionMetric },
  final_holdout_evidence: {
    metric_source: "final_holdout",
    role: "reporting_only",
    metrics: { pr_auc: 0.69 },
  },
  holdout_exposure: {
    status: "evaluated",
    first_opened_at: "2026-07-31T12:02:00Z",
    candidate_decision_id: decision.decision_id,
    evaluation_package_id: "eval-1",
  },
};

test("promotion posts the exact locked decision and accepts only verified durable governance", async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: Record<string, unknown> = {};
  globalThis.fetch = (async (_input, init) => {
    requestBody = JSON.parse(String(init?.body ?? "{}"));
    return new Response(JSON.stringify({
      model: { modelId: "model-1", currentVersionId: "model-version-1" },
      modelVersion: {
        modelId: "model-1",
        modelVersionId: "model-version-1",
        projectId: candidate.project_id,
        datasetId: candidate.dataset_id,
        datasetVersionId: candidate.dataset_version_id,
        trainingRunId: candidate.training_run_id,
        featureManifestVersion: candidate.feature_manifest_version,
        evaluationPackageId: evaluationPackage.evaluation_package_id,
        candidateDecisionId: decision.decision_id,
        selectionIntegrityStatus: "verified",
        holdoutIsolationStatus: "verified",
        evaluationPackageIntegrityStatus: "verified",
        promotionReadinessStatus: "verified",
        finalHoldoutStatus: "evaluated",
        holdoutExposureId: "exposure-1",
        checksum: "sha256:abc",
        lineage: {
          candidateId: candidate.candidate_id,
          trainingJobId: candidate.training_job_id,
          trainingRunId: candidate.training_run_id,
          splitId: candidate.split_id,
          validationDesignId: candidate.validation_design_id,
          validationDesignVersion: candidate.validation_design_version,
          featureManifestVersion: candidate.feature_manifest_version,
          target: candidate.target,
          candidateDecisionId: decision.decision_id,
        },
      },
      promotion: {
        status: "finalized",
        artifactVerified: true,
        lineageStatus: "verified",
        checksum: "sha256:abc",
        designation: "champion",
        championGeneration: 1,
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  try {
    const promoted = await promoteExactCandidate(
      "http://127.0.0.1:8001/api",
      candidate,
      "eval-1",
      { candidateEvidence, candidateDecision: decision, evaluationPackage },
    );
    expect(requestBody.candidate_decision_id).toBe("decision-1");
    expect(requestBody.evaluation_package_id).toBe("eval-1");
    expect(promoted.modelVersionId).toBe("model-version-1");
    expect(promoted.promotionReadinessStatus).toBe("verified");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("promotion does not issue a request for contaminated or incomplete evidence", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = (async () => {
    called = true;
    throw new Error("must not be called");
  }) as typeof fetch;
  try {
    await expect(promoteExactCandidate(
      "http://127.0.0.1:8001/api",
      candidate,
      "eval-1",
      {
        candidateEvidence: { ...candidateEvidence, selection_integrity_status: "invalid_final_holdout_ranking" },
        candidateDecision: decision,
        evaluationPackage,
      },
    )).rejects.toThrow(/verified non-holdout selection evidence/i);
    expect(called).toBe(false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

const canonicalIdentity = {
  project_id: candidate.project_id,
  dataset_id: candidate.dataset_id,
  dataset_version_id: candidate.dataset_version_id,
};

const exactHandoff = {
  candidateId: candidate.candidate_id,
  trainingRunId: candidate.training_run_id,
  candidateDecisionId: decision.decision_id,
  evaluationPackageId: evaluationPackage.evaluation_package_id,
};

function exactFinalStatus(overrides: Record<string, unknown> = {}) {
  const modelVersion = {
    modelId: "model-1",
    modelVersionId: "model-version-1",
    projectId: candidate.project_id,
    datasetId: candidate.dataset_id,
    datasetVersionId: candidate.dataset_version_id,
    candidateId: candidate.candidate_id,
    trainingRunId: candidate.training_run_id,
    candidateDecisionId: decision.decision_id,
    evaluationPackageId: evaluationPackage.evaluation_package_id,
    selectionIntegrityStatus: "verified",
    holdoutIsolationStatus: "verified",
    evaluationPackageIntegrityStatus: "verified",
    promotionReadinessStatus: "verified",
    finalHoldoutStatus: "evaluated",
    holdoutExposureId: "exposure-1",
    ...overrides,
  };
  return {
    ok: true,
    ready: true,
    metadata: {
      ...modelVersion,
      project_id: candidate.project_id,
      training_dataset_id: candidate.dataset_id,
      training_dataset_version_id: candidate.dataset_version_id,
      target_name: candidate.target,
      model_version_id: "model-version-1",
      designation: "champion",
    },
    modelVersion,
  };
}

function exactRecovery() {
  return {
    ok: true,
    recovery: {
      status: "ready",
      projectId: candidate.project_id,
      modelId: "model-1",
      modelVersionId: "model-version-1",
      publicationStatus: "finalized",
      lineageStatus: "verified",
      artifactVerified: true,
      checksum: "sha256:abc",
      artifactFormat: "joblib",
    },
  };
}

test("exact final-model recovery verifies the Evaluation handoff before enabling recovery", async () => {
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input) => {
    const url = String(input);
    requests.push(url);
    if (url.includes("/recovery-status")) {
      return new Response(JSON.stringify(exactRecovery()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify(exactFinalStatus()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
  try {
    const restored = await restoreExactFinalModel(
      "http://127.0.0.1:8001/api",
      canonicalIdentity,
      candidate.target,
      exactHandoff,
    );
    expect(restored?.promotion.modelVersionId).toBe("model-version-1");
    expect(requests).toHaveLength(2);
    const statusUrl = new URL(requests[0]);
    expect(statusUrl.searchParams.get("candidate_id")).toBe(candidate.candidate_id);
    expect(statusUrl.searchParams.get("training_run_id")).toBe(candidate.training_run_id);
    expect(statusUrl.searchParams.get("candidate_decision_id")).toBe(decision.decision_id);
    expect(statusUrl.searchParams.get("evaluation_package_id")).toBe(evaluationPackage.evaluation_package_id);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("an older champion cannot satisfy a changed exact Evaluation handoff", async () => {
  const originalFetch = globalThis.fetch;
  const mismatches: Array<[string, Record<string, unknown>]> = [
    ["candidate", { candidateId: "older-candidate" }],
    ["training run", { trainingRunId: "older-run" }],
    ["candidate decision", { candidateDecisionId: "older-decision" }],
    ["evaluation package", { evaluationPackageId: "older-package" }],
  ];
  let recoveryRequests = 0;
  let statusOverride: Record<string, unknown> = {};
  globalThis.fetch = (async (input) => {
    const url = String(input);
    if (url.includes("/recovery-status")) {
      recoveryRequests += 1;
      return new Response(JSON.stringify(exactRecovery()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify(exactFinalStatus(statusOverride)), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
  try {
    for (const [label, override] of mismatches) {
      statusOverride = override;
      await expect(restoreExactFinalModel(
        "http://127.0.0.1:8001/api",
        canonicalIdentity,
        candidate.target,
        exactHandoff,
      ), label).rejects.toThrow(/does not match the exact Evaluation handoff/i);
    }
    expect(recoveryRequests).toBe(0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a partial explicit handoff fails closed without contacting current-model status", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = (async () => {
    called = true;
    throw new Error("must not be called");
  }) as typeof fetch;
  try {
    await expect(restoreExactFinalModel(
      "http://127.0.0.1:8001/api",
      canonicalIdentity,
      candidate.target,
      { candidateId: candidate.candidate_id },
    )).rejects.toThrow(/requires candidate_id, training_run_id, candidate_decision_id, and evaluation_package_id/i);
    expect(called).toBe(false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
