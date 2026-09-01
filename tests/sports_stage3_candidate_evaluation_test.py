from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from server.sports_current_statcast import stage3_candidate_evaluation as evaluation
from server.sports_current_statcast import stage3_model_jobs as jobs
from server.sports_current_statcast import stage3_model_laboratory as lab


def _resolved() -> SimpleNamespace:
    return SimpleNamespace(
        project_id=lab.EXPECTED_PROJECT_ID,
        project_name="MLB 2026 Current-Data Game Forecast Challenger",
        authority_key="authority-key",
        eda_authority=SimpleNamespace(
            gold_manifest_sha=lab.EXPECTED_GOLD_MANIFEST_SHA,
        ),
        split={"contractId": lab.EXPECTED_SPLIT["splitContractId"], "checksum": lab.EXPECTED_SPLIT["checksum"]},
        outlier_policy={"policyId": lab.EXPECTED_OUTLIER_POLICY["policyId"], "checksum": lab.EXPECTED_OUTLIER_POLICY["checksum"]},
        missing_policy={"policyId": lab.EXPECTED_MISSING_POLICY["policyId"], "checksum": lab.EXPECTED_MISSING_POLICY["checksum"]},
        feature_sets=[],
    )


def _candidate(*, model: str = "xgboost", feature: str = "feature-a", loss: float = 1.47, status: str = "COMPLETE") -> dict[str, object]:
    return {
        "candidateId": f"candidate-{model}-{feature}",
        "modelFamily": model,
        "featureSetId": feature,
        "featureSetName": feature,
        "featureSetChecksum": "f" * 64,
        "featureCount": 48,
        "hyperparameters": {"n_jobs": 1},
        "status": status,
        "foldsCompleted": 5 if status == "COMPLETE" else 0,
        "meanOofLogLoss": loss if status == "COMPLETE" else None,
        "summedBrier": 0.75 if status == "COMPLETE" else None,
        "ece": 0.02 if status == "COMPLETE" else None,
        "macroF1Diagnostic": 0.31 if status == "COMPLETE" else None,
        "accuracyDiagnostic": 0.42 if status == "COMPLETE" else None,
        "foldStability": {"logLossStdDev": 0.01} if status == "COMPLETE" else None,
        "runtimeMs": 1000,
        "folds": [
            {
                "foldNumber": fold,
                "metrics": {
                    "multiclassLogLoss": loss,
                    "summedBrier": 0.75,
                    "ece": 0.02,
                    "accuracy": 0.42,
                    "macroF1": 0.31,
                },
            }
            for fold in range(1, 6)
        ] if status == "COMPLETE" else [],
        "errorCode": None if status == "COMPLETE" else "SOURCE_UNAVAILABLE",
        "errorReason": None if status == "COMPLETE" else "Mandatory feature unavailable.",
    }


def _run(candidate: dict[str, object], receipt: str, *, schema: str = lab.RUN_RECEIPT_SCHEMA_VERSION, seed: int = 731026) -> dict[str, object]:
    return {
        "schemaVersion": schema,
        "runId": f"run-{receipt[:8]}",
        "runReceiptSha256": receipt,
        "createdAt": "2026-09-01T12:00:00Z",
        "identity": {
            "projectId": lab.EXPECTED_PROJECT_ID,
            "goldDatasetId": lab.CURRENT_GOLD_DATASET_ID,
            "goldManifestSha": lab.EXPECTED_GOLD_MANIFEST_SHA,
            "splitContractId": lab.EXPECTED_SPLIT["splitContractId"],
            "splitChecksum": lab.EXPECTED_SPLIT["checksum"],
            "outlierPolicyId": lab.EXPECTED_OUTLIER_POLICY["policyId"],
            "outlierPolicyChecksum": lab.EXPECTED_OUTLIER_POLICY["checksum"],
            "missingPolicyId": lab.EXPECTED_MISSING_POLICY["policyId"],
            "missingPolicyChecksum": lab.EXPECTED_MISSING_POLICY["checksum"],
            "targetOrder": list(lab.GOLD_CLASS_ORDER),
            "seed": seed,
        },
        "environment": {"python": "3.12", "implementation": "a" * 64},
        "candidates": [candidate],
    }


def test_repeated_receipts_group_without_mutating_or_deleting_attempts() -> None:
    first = _run(_candidate(), "1" * 64)
    second = deepcopy(first)
    second["runId"] = "run-second"
    second["runReceiptSha256"] = "2" * 64
    before = deepcopy([first, second])
    grouped = evaluation._group_attempts([first, second])
    assert len(grouped) == 1
    assert grouped[0]["attemptCount"] == 2
    assert grouped[0]["completedAttemptCount"] == 2
    assert grouped[0]["reproducibilityStatus"] == "REPRODUCED"
    assert {attempt["runReceiptSha256"] for attempt in grouped[0]["attempts"]} == {"1" * 64, "2" * 64}
    assert [first, second] == before


def test_same_specification_with_different_metrics_requires_reproducibility_review() -> None:
    first = _run(_candidate(loss=1.47), "1" * 64)
    second = _run(_candidate(loss=1.48), "2" * 64)
    grouped = evaluation._group_attempts([first, second])
    assert len(grouped) == 1
    assert grouped[0]["reproducibilityStatus"] == "REPRODUCIBILITY_REVIEW_REQUIRED"
    assert grouped[0]["rankingEligible"] is False


def test_fingerprint_changes_for_scientific_input_not_runtime() -> None:
    base = _run(_candidate(), "1" * 64)
    runtime_only = deepcopy(base)
    runtime_only["candidates"][0]["runtimeMs"] = 999_999
    different_seed = deepcopy(base)
    different_seed["identity"]["seed"] = 17
    assert evaluation.candidate_specification_fingerprint(base, base["candidates"][0]) == evaluation.candidate_specification_fingerprint(runtime_only, runtime_only["candidates"][0])
    assert evaluation.candidate_specification_fingerprint(base, base["candidates"][0]) != evaluation.candidate_specification_fingerprint(different_seed, different_seed["candidates"][0])


def test_project_evaluation_is_read_only_project_bound_and_oot_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(_candidate(), "1" * 64)
    monkeypatch.setattr(evaluation, "resolve_model_lab_authority", lambda *_args: _resolved())
    monkeypatch.setattr(evaluation, "_read_runs", lambda *_args: [run])
    monkeypatch.setattr(evaluation, "_decision_rows", lambda *_args: [])
    result = evaluation.project_candidate_evaluation(object(), lab.EXPECTED_PROJECT_ID)
    assert result["authority"]["legacyGlobalMatrixUsed"] is False
    assert result["authority"]["base22FallbackAvailable"] is False
    assert result["population"]["finalOotLocked"] is True
    assert result["population"]["finalOotTargetAccessed"] is False
    assert result["activity"]["newFitsOnPageLoad"] == 0
    assert result["activity"]["immutableRunReceipts"] == 1


class _Repository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}

    def upsert(self, row: dict[str, object]) -> dict[str, object]:
        self.rows[str(row["run_id"])] = row
        return row

    def list_for_project(self, _project_id: str) -> list[dict[str, object]]:
        return list(self.rows.values())

    def get(self, run_id: str) -> dict[str, object] | None:
        return self.rows.get(run_id)


def test_finalist_receipt_is_not_champion_and_binds_attempt_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _Repository()
    run = _run(_candidate(), "1" * 64)
    fingerprint = evaluation.candidate_specification_fingerprint(run, run["candidates"][0])
    monkeypatch.setattr(evaluation, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(evaluation, "resolve_model_lab_authority", lambda *_args: _resolved())
    monkeypatch.setattr(evaluation, "_read_runs", lambda *_args: [run])
    monkeypatch.setattr(evaluation, "_persist_object", lambda _kind, body: {**body, "receiptSha256": "a" * 64})
    result = evaluation.save_finalist_selection(
        object(), lab.EXPECTED_PROJECT_ID,
        {"candidateFingerprints": [fingerprint], "rationale": "Stable probability evidence merits bounded refinement."},
        actor_user_id="scientist",
    )
    assert result["selection"]["decisionStatus"] == "FINALIST_FOR_REFINEMENT"
    assert result["selection"]["championSelected"] is False
    assert result["selection"]["promotionStatus"] == "NOT_PROMOTED"
    assert result["selection"]["selectedCandidates"][0]["attemptReceiptSha256s"] == ["1" * 64]


def test_shap_request_persists_sample_identity_and_fails_closed_without_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _Repository()
    run = _run(_candidate(), "1" * 64)
    group = evaluation._group_attempts([run])[0]
    monkeypatch.setattr(evaluation, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(evaluation, "_candidate_group", lambda *_args: (_resolved(), group))
    monkeypatch.setattr(
        evaluation,
        "_decision_rows",
        lambda *_args: [
            {
                "parameters_json": json.dumps(
                    {"candidateFingerprints": [group["candidateFingerprint"]]}
                )
            }
        ],
    )
    monkeypatch.setattr(evaluation, "_persist_object", lambda _kind, body: {**body, "receiptSha256": "a" * 64})
    monkeypatch.setattr(evaluation.importlib.util, "find_spec", lambda name: None if name == "shap" else object())
    result = evaluation.request_candidate_analysis(
        object(), lab.EXPECTED_PROJECT_ID,
        {"candidateFingerprint": group["candidateFingerprint"], "analysisKind": "SHAP", "sampleSize": 500, "seed": 12, "targetClass": "HOME_RUN"},
        actor_user_id="scientist",
    )
    assert result["analysis"]["status"] == "NOT_AVAILABLE_DEPENDENCY_NOT_INSTALLED"
    assert result["analysis"]["sample"]["scope"] == "DEVELOPMENT_ONLY"
    assert len(result["analysis"]["sample"]["sampleIdentitySha256"]) == 64
    assert result["analysis"]["finalOotTargetAccessed"] is False


def test_shap_and_sensitivity_require_a_persisted_finalist_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    group = evaluation._group_attempts([_run(_candidate(), "1" * 64)])[0]
    monkeypatch.setattr(evaluation, "_candidate_group", lambda *_args: (_resolved(), group))
    monkeypatch.setattr(evaluation, "_decision_rows", lambda *_args: [])
    for kind in ("SHAP", "SENSITIVITY"):
        with pytest.raises(lab.Stage3ModelLaboratoryError, match="finalist selection receipt"):
            evaluation.request_candidate_analysis(
                object(),
                lab.EXPECTED_PROJECT_ID,
                {
                    "candidateFingerprint": group["candidateFingerprint"],
                    "analysisKind": kind,
                    "sampleSize": 500,
                    "seed": 12,
                    "targetClass": "HOME_RUN",
                },
                actor_user_id="scientist",
            )


def test_parallelism_is_bounded_and_estimator_workers_remain_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(jobs, "_physical_memory_bytes", lambda: 32 * 1024**3)
    contract = jobs._parallelism([{"computeIntensity": "HIGH"}], "AUTO")
    assert contract["effectiveCandidateWorkers"] == 2
    assert contract["maximumCandidateWorkers"] == 2
    assert contract["estimatorNativeWorkers"] == 1
    assert contract["nestedOversubscriptionProhibited"] is True
    with pytest.raises(lab.Stage3ModelLaboratoryError, match="at most 2"):
        jobs._parallelism([{"computeIntensity": "LOW"}], 3)
