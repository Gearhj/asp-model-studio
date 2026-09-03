from __future__ import annotations

import json
from collections.abc import Mapping
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


def _incremental_fixture(tmp_path) -> tuple[
    SimpleNamespace,
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    object,
    str,
]:
    resolved = _resolved()
    configuration = {"C": 1.0, "solver": "lbfgs", "max_iter": 1000}
    resources = {
        "nativeWorkers": 1,
        "exclusiveCandidate": False,
        "nestedOversubscriptionProhibited": True,
    }
    experiment = {
        "experimentId": "experiment-one",
        "candidateSpecificationTemplateSha256": "c" * 64,
        "algorithmId": "multinomial_logistic",
        "seed": 20260901,
        "featureUniverseId": "feature-a",
        "featureUniverseName": "feature-a",
        "featureUniverseChecksum": "f" * 64,
        "featureCount": 1,
        "sourceFeatureCount": 1,
        "featureSetContract": {
            "featureSetId": "feature-a",
            "name": "feature-a",
            "checksum": "f" * 64,
            "orderedFeatures": ["feature-a"],
        },
        "foldLocalSelector": None,
        "tuning": {
            "tuningMode": "FIXED",
            "gridPreset": "COMPACT",
            "configurations": [configuration],
            "configurationCount": 1,
            "totalFits": 5,
        },
        "executionResources": resources,
    }
    unsigned_plan = {
        "schemaVersion": jobs.MODEL_DEVELOPMENT_PLAN_SCHEMA_VERSION,
        "projectId": lab.EXPECTED_PROJECT_ID,
        "authorityKey": resolved.authority_key,
        "splitContractId": resolved.split["contractId"],
        "splitChecksum": resolved.split["checksum"],
        "foldCount": 5,
        "metric": "MULTICLASS_LOG_LOSS",
        "environment": {"python": "3.12"},
        "experiments": [experiment],
        "totalExperiments": 1,
        "totalConfigurations": 1,
        "totalFits": 5,
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "providerCalls": 0,
        "promotionRequested": False,
    }
    plan_sha = evaluation._sha(unsigned_plan)
    plan = {
        **unsigned_plan,
        "planId": "stage3-model-plan-" + plan_sha[:32],
        "checksum": plan_sha,
    }
    candidate = {
        **_candidate(model="multinomial_logistic"),
        "experimentId": experiment["experimentId"],
        "candidateSpecificationTemplateSha256": experiment[
            "candidateSpecificationTemplateSha256"
        ],
        "configurationIndex": 1,
        "hyperparameters": configuration,
        "featureCount": 1,
        "sourceFeatureCount": 1,
        "orderedFeatures": ["feature-a"],
        "refinementEvidence": None,
        "tuningMode": "FIXED",
        "gridPreset": "COMPACT",
        "executionResources": resources,
    }
    payload = {
        "schemaVersion": evaluation.INCREMENTAL_RECEIPT_SCHEMA_VERSION,
        "jobId": "job-one",
        "projectId": lab.EXPECTED_PROJECT_ID,
        "planId": plan["planId"],
        "planChecksum": plan["checksum"],
        "createdAt": "2026-09-02T09:00:00Z",
        "candidate": candidate,
        "finalOotTargetAccessed": False,
        "promotionStatus": "NOT_PROMOTED",
    }
    directory = tmp_path / "candidate-attempts" / "objects" / "sha256"
    directory.mkdir(parents=True)
    row = {
        "run_id": "job-one",
        "project_id": lab.EXPECTED_PROJECT_ID,
        "run_type": jobs.MODEL_DEVELOPMENT_JOB_TYPE,
        "status": "RUNNING",
        "started_at": "2026-09-02T08:00:00Z",
        "parameters_json": json.dumps(plan),
        "metrics_json": json.dumps({}),
        "artifacts_json": json.dumps({}),
    }
    receipt_sha = _point_row_at_payload(row, directory, payload, candidate)
    return resolved, plan, candidate, payload, row, directory, receipt_sha


def _point_row_at_payload(
    row: dict[str, object], directory, payload: object, pointer_candidate: Mapping[str, object]
) -> str:
    raw = evaluation.canonical_json_bytes(payload)
    receipt_sha = evaluation.hashlib.sha256(raw).hexdigest()
    (directory / f"{receipt_sha}.json").write_bytes(raw)
    row["metrics_json"] = json.dumps(
        {
            "completedCandidateReceipts": [
                {
                    "candidateId": pointer_candidate["candidateId"],
                    "candidateReceiptSha256": receipt_sha,
                    "status": pointer_candidate["status"],
                }
            ]
        }
    )
    return receipt_sha


def _install_active_row(monkeypatch: pytest.MonkeyPatch, row: dict[str, object]) -> None:
    class Repository:
        def list_for_project(self, _project_id: str) -> list[dict[str, object]]:
            return [row]

    monkeypatch.setattr(evaluation, "RunRepository", lambda _database: Repository())


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
    monkeypatch.setattr(
        evaluation,
        "_incremental_current_evidence",
        lambda *_args: {
            "status": "NONE",
            "candidateGroups": [],
            "verifiedCandidateReceipts": 0,
            "heldClosedReceipts": 0,
        },
    )
    result = evaluation.project_candidate_evaluation(object(), lab.EXPECTED_PROJECT_ID)
    assert result["authority"]["legacyGlobalMatrixUsed"] is False
    assert result["authority"]["base22FallbackAvailable"] is False
    assert result["population"]["finalOotLocked"] is True
    assert result["population"]["finalOotTargetAccessed"] is False
    assert result["activity"]["newFitsOnPageLoad"] == 0
    assert result["activity"]["immutableRunReceipts"] == 1


def test_verified_active_candidate_receipt_is_interim_and_not_selection_eligible(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    resolved, _plan, _candidate_value, _payload, row, directory, receipt_sha = (
        _incremental_fixture(tmp_path)
    )
    _install_active_row(monkeypatch, row)
    monkeypatch.setattr(evaluation, "_runtime_root", lambda: tmp_path)
    result = evaluation._incremental_current_evidence(
        object(), lab.EXPECTED_PROJECT_ID, resolved, []
    )
    assert result["status"] == "ACTIVE_WITH_VERIFIED_EVIDENCE"
    assert result["verifiedCandidateReceipts"] == 1
    assert result["heldClosedReceipts"] == 0
    group = result["candidateGroups"][0]
    assert group["meanOofLogLoss"] == pytest.approx(1.47)
    assert group["rankingEligible"] is False
    assert group["rank"] is None
    assert group["finalist"] is False
    assert group["developmentLabel"] == "INCREMENTAL_COMPLETE_NOT_SELECTION_ELIGIBLE"
    assert group["evidenceSources"] == ["INCREMENTAL_CURRENT_EVIDENCE"]
    assert group["attempts"][0]["receiptSchemaVersion"] == evaluation.INCREMENTAL_RECEIPT_SCHEMA_VERSION

    raw = (directory / f"{receipt_sha}.json").read_bytes()
    (directory / f"{receipt_sha}.json").write_bytes(raw + b" ")
    tampered = evaluation._incremental_current_evidence(
        object(), lab.EXPECTED_PROJECT_ID, resolved, []
    )
    assert tampered["candidateGroups"] == []
    assert tampered["heldClosedReceipts"] == 1


def test_incremental_receipt_rejects_boolean_configuration_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    resolved, _plan, candidate, payload, row, directory, _receipt_sha = (
        _incremental_fixture(tmp_path)
    )
    candidate["configurationIndex"] = True
    _point_row_at_payload(row, directory, payload, candidate)
    _install_active_row(monkeypatch, row)
    monkeypatch.setattr(evaluation, "_runtime_root", lambda: tmp_path)

    result = evaluation._incremental_current_evidence(
        object(), lab.EXPECTED_PROJECT_ID, resolved, []
    )
    assert result["candidateGroups"] == []
    assert result["heldClosedReceipts"] == 1
    assert result["diagnostics"][0]["code"] == "INCREMENTAL_RECEIPT_INTEGRITY_INVALID"


@pytest.mark.parametrize("job_status", ["INTERRUPTED", "FAILED"])
def test_orphaned_terminal_job_preserves_verified_candidate_attempt_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path, job_status: str
) -> None:
    resolved, _plan, _candidate_value, _payload, row, _directory, _receipt_sha = (
        _incremental_fixture(tmp_path)
    )
    row["status"] = job_status
    _install_active_row(monkeypatch, row)
    monkeypatch.setattr(evaluation, "_runtime_root", lambda: tmp_path)

    result = evaluation._incremental_current_evidence(
        object(), lab.EXPECTED_PROJECT_ID, resolved, []
    )
    assert result["status"] == "ORPHANED_TERMINAL_WITH_VERIFIED_EVIDENCE"
    assert result["verifiedCandidateReceipts"] == 1
    assert result["rankingEligible"] is False
    assert result["finalistSelectionEligible"] is False
    assert result["candidateGroups"][0]["developmentLabel"] == (
        "INCREMENTAL_COMPLETE_NOT_SELECTION_ELIGIBLE"
    )


def test_orphan_candidate_receipt_is_not_duplicated_after_terminal_v2_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    resolved, plan, _candidate_value, _payload, row, _directory, _receipt_sha = (
        _incremental_fixture(tmp_path)
    )
    row["status"] = "INTERRUPTED"
    _install_active_row(monkeypatch, row)
    monkeypatch.setattr(evaluation, "_runtime_root", lambda: tmp_path)
    terminal = {
        "schemaVersion": lab.RUN_RECEIPT_SCHEMA_VERSION_V2,
        "identity": {"planId": plan["planId"]},
    }

    result = evaluation._incremental_current_evidence(
        object(), lab.EXPECTED_PROJECT_ID, resolved, [terminal]
    )
    assert result["status"] == "TERMINAL_RECEIPT_AVAILABLE"
    assert result["candidateGroups"] == []
    assert result["verifiedCandidateReceipts"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("featureSetChecksum", "0" * 64),
        ("tuningMode", "GRID"),
        ("executionResources", {"nativeWorkers": 99}),
    ],
)
def test_incremental_receipt_binds_feature_tuning_and_resource_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path, field: str, value: object
) -> None:
    resolved, _plan, candidate, payload, row, directory, _receipt_sha = (
        _incremental_fixture(tmp_path)
    )
    candidate[field] = value
    _point_row_at_payload(row, directory, payload, candidate)
    _install_active_row(monkeypatch, row)
    monkeypatch.setattr(evaluation, "_runtime_root", lambda: tmp_path)

    result = evaluation._incremental_current_evidence(
        object(), lab.EXPECTED_PROJECT_ID, resolved, []
    )
    assert result["candidateGroups"] == []
    assert result["heldClosedReceipts"] == 1
    assert result["diagnostics"][0]["code"] == "INCREMENTAL_RECEIPT_INTEGRITY_INVALID"


def test_incremental_evidence_requires_current_plan_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    resolved, plan, _candidate_value, _payload, row, _directory, _receipt_sha = (
        _incremental_fixture(tmp_path)
    )
    unsigned = {key: value for key, value in plan.items() if key not in {"planId", "checksum"}}
    unsigned["schemaVersion"] = "SPORTS_STAGE3_MODEL_DEVELOPMENT_PLAN_V1"
    plan_sha = evaluation._sha(unsigned)
    row["parameters_json"] = json.dumps(
        {
            **unsigned,
            "planId": "stage3-model-plan-" + plan_sha[:32],
            "checksum": plan_sha,
        }
    )
    _install_active_row(monkeypatch, row)
    monkeypatch.setattr(evaluation, "_runtime_root", lambda: tmp_path)

    result = evaluation._incremental_current_evidence(
        object(), lab.EXPECTED_PROJECT_ID, resolved, []
    )
    assert result["status"] == "HELD_CLOSED"
    assert result["diagnostics"][0]["code"] == "INCREMENTAL_PLAN_AUTHORITY_INVALID"


@pytest.mark.parametrize("malformed_part", ["plan", "progress", "receipt"])
def test_incremental_evidence_fails_closed_on_malformed_decoded_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path, malformed_part: str
) -> None:
    resolved, _plan, candidate, _payload, row, directory, _receipt_sha = (
        _incremental_fixture(tmp_path)
    )
    if malformed_part == "plan":
        row["parameters_json"] = json.dumps([])
    elif malformed_part == "progress":
        row["metrics_json"] = json.dumps([])
    else:
        _point_row_at_payload(row, directory, [], candidate)
    _install_active_row(monkeypatch, row)
    monkeypatch.setattr(evaluation, "_runtime_root", lambda: tmp_path)

    result = evaluation._incremental_current_evidence(
        object(), lab.EXPECTED_PROJECT_ID, resolved, []
    )
    assert result["status"] in {"HELD_CLOSED", "ACTIVE_NO_VERIFIED_EVIDENCE"}
    assert result["candidateGroups"] == []
    assert result["heldClosedReceipts"] == 1
    assert result["diagnostics"][0]["code"] in {
        "INCREMENTAL_PLAN_SHAPE_INVALID",
        "INCREMENTAL_RECEIPT_LEDGER_SHAPE_INVALID",
        "INCREMENTAL_RECEIPT_SHAPE_INVALID",
    }


def test_current_and_historical_rows_are_grouped_from_their_own_receipt_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = _run(_candidate(loss=1.47), "1" * 64)
    current = _run(
        _candidate(loss=1.40),
        "2" * 64,
        schema=lab.RUN_RECEIPT_SCHEMA_VERSION_V2,
    )
    monkeypatch.setattr(evaluation, "resolve_model_lab_authority", lambda *_args: _resolved())
    monkeypatch.setattr(evaluation, "_read_runs", lambda *_args: [historical, current])
    monkeypatch.setattr(evaluation, "_decision_rows", lambda *_args: [])
    monkeypatch.setattr(
        evaluation,
        "_incremental_current_evidence",
        lambda *_args: {
            "status": "NONE",
            "candidateGroups": [],
            "verifiedCandidateReceipts": 0,
            "heldClosedReceipts": 0,
        },
    )

    result = evaluation.project_candidate_evaluation(object(), lab.EXPECTED_PROJECT_ID)
    assert len(result["currentBatches"]) == 1
    assert result["currentBatches"][0]["meanOofLogLoss"] == pytest.approx(1.40)
    assert result["currentBatches"][0]["evidenceSources"] == ["CURRENT_BATCH"]
    assert len(result["historicalEvidence"]["candidates"]) == 1
    assert result["historicalEvidence"]["candidates"][0]["meanOofLogLoss"] == pytest.approx(1.47)
    assert result["historicalEvidence"]["candidates"][0]["evidenceSources"] == [
        "HISTORICAL_BASELINE"
    ]
    assert len(result["candidateGroups"]) == 1
    assert result["candidateGroups"][0]["meanOofLogLoss"] == pytest.approx(1.40)
    assert result["candidateGroups"][0]["evidenceSources"] == ["CURRENT_BATCH"]


def test_candidate_grouping_rejects_malformed_decoded_shapes() -> None:
    malformed = _run(_candidate(), "1" * 64)
    malformed["candidates"] = {"candidate": _candidate()}
    with pytest.raises(lab.Stage3ModelLaboratoryError) as exc_info:
        evaluation._group_attempts([malformed])
    assert exc_info.value.code == "STAGE3_CANDIDATE_EVIDENCE_SHAPE_INVALID"


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


def _finalist_payload(
    group: Mapping[str, object],
    source: str,
    *,
    attempt_receipts: set[str] | None = None,
) -> dict[str, object]:
    attempts = [
        item
        for item in group["attempts"]
        if item["status"] == "COMPLETE"
        and item["evidenceSource"] == source
        and (
            attempt_receipts is None
            or item["runReceiptSha256"] in attempt_receipts
        )
    ]
    assert attempts
    representative = attempts[0]
    fingerprint = str(group["candidateFingerprint"])
    return {
        "candidateFingerprints": [fingerprint],
        "rationale": "Stable probability evidence merits bounded refinement.",
        "evaluationBatch": source,
        "candidateSelections": [
            {
                "candidateFingerprint": fingerprint,
                "evidenceSource": source,
                "representativeAttemptId": representative["attemptId"],
                "immutableEvidenceIdentity": representative["runReceiptSha256"],
                "attemptEvidence": [
                    {
                        "attemptId": item["attemptId"],
                        "runId": item["runId"],
                        "runReceiptSha256": item["runReceiptSha256"],
                    }
                    for item in attempts
                ],
            }
        ],
    }


def test_finalist_receipt_is_not_champion_and_binds_attempt_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _Repository()
    run = _run(_candidate(), "1" * 64)
    group = evaluation._group_attempts([run])[0]
    monkeypatch.setattr(evaluation, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(evaluation, "resolve_model_lab_authority", lambda *_args: _resolved())
    monkeypatch.setattr(evaluation, "_read_runs", lambda *_args: [run])
    monkeypatch.setattr(evaluation, "_persist_object", lambda _kind, body: {**body, "receiptSha256": "a" * 64})
    result = evaluation.save_finalist_selection(
        object(), lab.EXPECTED_PROJECT_ID,
        _finalist_payload(group, "HISTORICAL_BASELINE"),
        actor_user_id="scientist",
    )
    assert result["selection"]["decisionStatus"] == "FINALIST_FOR_REFINEMENT"
    assert result["selection"]["championSelected"] is False
    assert result["selection"]["promotionStatus"] == "NOT_PROMOTED"
    assert result["selection"]["evidenceSource"] == "HISTORICAL_BASELINE"
    assert result["selection"]["selectedCandidates"][0]["attemptReceiptSha256s"] == ["1" * 64]
    assert result["selection"]["selectedCandidates"][0]["attemptEvidence"] == [
        {
            "attemptId": run["candidates"][0]["candidateId"],
            "runId": run["runId"],
            "runReceiptSha256": "1" * 64,
            "receiptSchemaVersion": lab.RUN_RECEIPT_SCHEMA_VERSION,
            "createdAt": run["createdAt"],
            "resultFingerprint": result["selection"]["selectedCandidates"][0][
                "attemptEvidence"
            ][0]["resultFingerprint"],
        }
    ]


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda payload: payload.update({"evaluationBatch": "ALL"}),
            "STAGE3_FINALIST_EVIDENCE_SOURCE_REQUIRED",
        ),
        (
            lambda payload: payload["candidateSelections"][0].update(
                {"evidenceSource": "CURRENT_BATCH"}
            ),
            "STAGE3_FINALIST_EVIDENCE_SOURCE_MISMATCH",
        ),
        (
            lambda payload: payload["candidateSelections"][0]["attemptEvidence"][
                0
            ].update({"runReceiptSha256": "9" * 64}),
            "STAGE3_FINALIST_ATTEMPT_EVIDENCE_MISMATCH",
        ),
    ],
)
def test_finalist_save_rejects_non_exact_source_or_attempt_evidence(
    monkeypatch: pytest.MonkeyPatch, mutate, expected_code: str
) -> None:
    repository = _Repository()
    run = _run(_candidate(), "1" * 64)
    group = evaluation._group_attempts([run])[0]
    payload = _finalist_payload(group, "HISTORICAL_BASELINE")
    mutate(payload)
    monkeypatch.setattr(evaluation, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(evaluation, "resolve_model_lab_authority", lambda *_args: _resolved())
    monkeypatch.setattr(evaluation, "_read_runs", lambda *_args: [run])

    with pytest.raises(lab.Stage3ModelLaboratoryError) as exc_info:
        evaluation.save_finalist_selection(
            object(), lab.EXPECTED_PROJECT_ID, payload, actor_user_id="scientist"
        )
    assert exc_info.value.code == expected_code


def test_latest_finalist_receipt_is_current_and_source_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository()
    historical_selected = _run(
        _candidate(model="histogram_gradient_boosting", feature="feature-old"),
        "1" * 64,
    )
    historical_same_spec = _run(_candidate(), "2" * 64)
    current = _run(
        _candidate(), "3" * 64, schema=lab.RUN_RECEIPT_SCHEMA_VERSION_V2
    )
    runs = [historical_selected, historical_same_spec, current]
    monkeypatch.setattr(evaluation, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(evaluation, "resolve_model_lab_authority", lambda *_args: _resolved())
    monkeypatch.setattr(evaluation, "_read_runs", lambda *_args: runs)
    monkeypatch.setattr(
        evaluation,
        "_persist_object",
        lambda _kind, body: {**body, "receiptSha256": evaluation._sha(body)},
    )
    monkeypatch.setattr(
        evaluation,
        "_incremental_current_evidence",
        lambda *_args: {
            "status": "NONE",
            "candidateGroups": [],
            "verifiedCandidateReceipts": 0,
            "heldClosedReceipts": 0,
        },
    )

    old_group = evaluation._group_attempts([historical_selected])[0]
    old_result = evaluation.save_finalist_selection(
        object(),
        lab.EXPECTED_PROJECT_ID,
        _finalist_payload(old_group, "HISTORICAL_BASELINE"),
        actor_user_id="scientist",
    )
    old_id = old_result["selection"]["selectionId"]
    repository.rows[old_id]["started_at"] = "2026-09-01T12:00:00Z"

    combined_group = evaluation._group_attempts(
        [historical_same_spec, current]
    )[0]
    new_result = evaluation.save_finalist_selection(
        object(),
        lab.EXPECTED_PROJECT_ID,
        _finalist_payload(combined_group, "CURRENT_BATCH"),
        actor_user_id="scientist",
    )
    new_id = new_result["selection"]["selectionId"]
    repository.rows[new_id]["started_at"] = "2026-09-02T12:00:00Z"

    result = evaluation.project_candidate_evaluation(
        object(), lab.EXPECTED_PROJECT_ID
    )
    assert result["currentFinalistSelectionId"] == new_id
    assert result["finalists"][0]["authorityStatus"] == "CURRENT"
    assert result["finalists"][1]["authorityStatus"] == "SUPERSEDED"
    assert result["finalists"][1]["supersededBySelectionId"] == new_id
    assert result["currentBatches"][0]["finalist"] is True
    same_historical = next(
        item
        for item in result["historicalEvidence"]["candidates"]
        if item["candidateFingerprint"]
        == result["currentBatches"][0]["candidateFingerprint"]
    )
    assert same_historical["finalist"] is False
    old_candidate = next(
        item
        for item in result["historicalEvidence"]["candidates"]
        if item["candidateFingerprint"] == old_group["candidateFingerprint"]
    )
    assert old_candidate["finalist"] is False


def test_refinement_uses_frozen_finalist_attempt_after_later_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository()
    selected_run = _run(
        _candidate(),
        "1" * 64,
        schema=lab.RUN_RECEIPT_SCHEMA_VERSION_V2,
    )
    selected_run["createdAt"] = "2026-09-01T12:00:00Z"
    visible_runs = [selected_run]
    monkeypatch.setattr(evaluation, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(evaluation, "resolve_model_lab_authority", lambda *_args: _resolved())
    monkeypatch.setattr(evaluation, "_read_runs", lambda *_args: visible_runs)
    monkeypatch.setattr(
        evaluation,
        "_persist_object",
        lambda _kind, body: {**body, "receiptSha256": evaluation._sha(body)},
    )

    selected_group = evaluation._group_attempts([selected_run])[0]
    evaluation.save_finalist_selection(
        object(),
        lab.EXPECTED_PROJECT_ID,
        _finalist_payload(selected_group, "CURRENT_BATCH"),
        actor_user_id="scientist",
    )
    later_run = _run(
        _candidate(),
        "2" * 64,
        schema=lab.RUN_RECEIPT_SCHEMA_VERSION_V2,
    )
    later_run["createdAt"] = "2026-09-02T12:00:00Z"
    visible_runs.append(later_run)

    result = evaluation.plan_model_refinement(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {
            "candidateFingerprint": selected_group["candidateFingerprint"],
            "method": "STABILITY_SELECTION",
            "minimumRetainedFeatures": 24,
            "eliminationStep": 2,
        },
        actor_user_id="scientist",
    )
    assert result["plan"]["parentEvidenceSource"] == "CURRENT_BATCH"
    assert result["plan"]["parentAttemptId"] == selected_run["candidates"][0][
        "candidateId"
    ]
    assert result["plan"]["parentRunId"] == selected_run["runId"]
    assert result["plan"]["parentRunReceiptSha256"] == "1" * 64


def test_shap_request_persists_sample_identity_and_fails_closed_without_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _Repository()
    run = _run(_candidate(), "1" * 64)
    group = evaluation._group_attempts([run])[0]
    monkeypatch.setattr(evaluation, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(
        evaluation,
        "_candidate_group",
        lambda *_args, **_kwargs: (_resolved(), group),
    )
    monkeypatch.setattr(
        evaluation,
        "_decision_rows",
        lambda *_args: [
            {
                "run_id": "selection-one",
                "started_at": "2026-09-01T13:00:00Z",
                "parameters_json": json.dumps(
                    {
                        **_finalist_payload(group, "HISTORICAL_BASELINE"),
                        "selectedCandidates": [
                            {
                                **_finalist_payload(
                                    group, "HISTORICAL_BASELINE"
                                )["candidateSelections"][0],
                                "representativeRunId": run["runId"],
                            }
                        ],
                    }
                ),
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
    monkeypatch.setattr(
        evaluation,
        "_candidate_group",
        lambda *_args, **_kwargs: (_resolved(), group),
    )
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
    monkeypatch.setattr(jobs, "_available_memory_bytes", lambda: 32 * 1024**3)
    contract = jobs._parallelism([{"computeIntensity": "HIGH"}], "AUTO")
    assert contract["effectiveCandidateWorkers"] == 2
    assert contract["maximumCandidateWorkers"] == 2
    assert contract["estimatorNativeWorkers"] == 1
    assert contract["nestedOversubscriptionProhibited"] is True
    with pytest.raises(lab.Stage3ModelLaboratoryError, match="at most 2"):
        jobs._parallelism([{"computeIntensity": "LOW"}], 3)
