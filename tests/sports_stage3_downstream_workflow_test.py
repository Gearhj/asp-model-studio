from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.sports_current_statcast import stage3_candidate_evaluation as downstream
from server.sports_current_statcast import stage3_model_laboratory as lab


class _Repository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}

    def upsert(self, row: dict[str, object]) -> dict[str, object]:
        self.rows[str(row["run_id"])] = row
        return row

    def list_for_project(self, project_id: str) -> list[dict[str, object]]:
        return [
            row for row in self.rows.values() if row.get("project_id") == project_id
        ]

    def get(self, run_id: str) -> dict[str, object] | None:
        return self.rows.get(run_id)


def _resolved() -> SimpleNamespace:
    return SimpleNamespace(
        project_id=lab.EXPECTED_PROJECT_ID,
        project_name="MLB 2026 Current-Data Game Forecast Challenger",
        authority_key="current-gold-authority",
        eda_authority=SimpleNamespace(
            gold_manifest_sha=lab.EXPECTED_GOLD_MANIFEST_SHA,
        ),
        split={
            "contractId": lab.EXPECTED_SPLIT["splitContractId"],
            "checksum": lab.EXPECTED_SPLIT["checksum"],
        },
        outlier_policy={
            "policyId": lab.EXPECTED_OUTLIER_POLICY["policyId"],
            "checksum": lab.EXPECTED_OUTLIER_POLICY["checksum"],
        },
        missing_policy={
            "policyId": lab.EXPECTED_MISSING_POLICY["policyId"],
            "checksum": lab.EXPECTED_MISSING_POLICY["checksum"],
        },
        feature_sets=[],
    )


def _candidate(
    *,
    model: str,
    feature_id: str,
    feature_name: str,
    loss: float,
) -> dict[str, object]:
    return {
        "candidateId": f"candidate-{model}-{feature_id}",
        "modelFamily": model,
        "featureSetId": feature_id,
        "featureSetName": feature_name,
        "featureSetChecksum": "f" * 64,
        "featureCount": 2,
        "orderedFeatures": ["feature_a", "feature_b"],
        "hyperparameters": {"max_depth": 6},
        "status": "COMPLETE",
        "foldsCompleted": 5,
        "meanOofLogLoss": loss,
        "summedBrier": 0.702,
        "ece": 0.004,
        "macroF1Diagnostic": 0.091,
        "accuracyDiagnostic": 0.455,
        "foldStability": {"logLossStdDev": 0.004},
        "runtimeMs": 1_500_000,
        "classCalibration": [
            {
                "class": "STRIKEOUT",
                "observedRate": 0.23,
                "meanPredictedProbability": 0.229,
            }
        ],
        "evaluationEvidence": {
            "status": "AVAILABLE_AGGREGATED_DEVELOPMENT_ONLY",
            "reloadableArtifactSha256": None,
        },
        "folds": [
            {
                "foldNumber": fold,
                "metrics": {
                    "multiclassLogLoss": loss,
                    "summedBrier": 0.702,
                    "ece": 0.004,
                    "accuracy": 0.455,
                    "macroF1": 0.091,
                },
            }
            for fold in range(1, 6)
        ],
    }


def _run(
    candidate: dict[str, object],
    receipt_sha: str,
    *,
    schema: str,
    created_at: str,
) -> dict[str, object]:
    return {
        "schemaVersion": schema,
        "runId": f"run-{receipt_sha[:8]}",
        "runReceiptSha256": receipt_sha,
        "createdAt": created_at,
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
            "seed": 20260901,
        },
        "environment": {"python": "3.12", "implementation": "a" * 64},
        "plan": {
            "experiments": [
                {
                    "experimentId": candidate["candidateId"],
                    "featureSetContract": {
                        "orderedFeatures": candidate["orderedFeatures"]
                    },
                    "seed": 20260901,
                }
            ]
        },
        "candidates": [
            {**candidate, "experimentId": candidate["candidateId"]}
        ],
    }


def _finalist_payload(group: dict[str, object]) -> dict[str, object]:
    return _finalist_payloads([group])


def _finalist_payloads(
    groups: list[dict[str, object]],
) -> dict[str, object]:
    selected = []
    for group in groups:
        attempt = group["attempts"][0]
        selected.append(
            {
                "candidateFingerprint": group["candidateFingerprint"],
                "evidenceSource": "CURRENT_BATCH",
                "representativeAttemptId": attempt["attemptId"],
                "immutableEvidenceIdentity": attempt["runReceiptSha256"],
                "attemptEvidence": [
                    {
                        "attemptId": attempt["attemptId"],
                        "runId": attempt["runId"],
                        "runReceiptSha256": attempt["runReceiptSha256"],
                    }
                ],
            }
        )
    return {
        "candidateFingerprints": [
            group["candidateFingerprint"] for group in groups
        ],
        "candidateSelections": selected,
        "evaluationBatch": "CURRENT_BATCH",
        "rationale": "Advance the strongest current full-feature candidate for review.",
    }


@pytest.fixture
def workflow(monkeypatch: pytest.MonkeyPatch):
    repository = _Repository()
    current = _run(
        _candidate(
            model="xgboost",
            feature_id="full-eligible",
            feature_name="Full Eligible Feature Set",
            loss=1.473323,
        ),
        "2" * 64,
        schema=lab.RUN_RECEIPT_SCHEMA_VERSION_V2,
        created_at="2026-09-02T12:00:00Z",
    )
    second_current = _run(
        _candidate(
            model="lightgbm",
            feature_id="full-eligible",
            feature_name="Full Eligible Feature Set",
            loss=1.475436,
        ),
        "3" * 64,
        schema=lab.RUN_RECEIPT_SCHEMA_VERSION_V2,
        created_at="2026-09-02T12:01:00Z",
    )
    historical = _run(
        _candidate(
            model="xgboost",
            feature_id="calendar",
            feature_name="B CORE_PLUS_CALENDAR",
            loss=1.472899,
        ),
        "1" * 64,
        schema=lab.RUN_RECEIPT_SCHEMA_VERSION,
        created_at="2026-09-01T12:00:00Z",
    )
    runs = [current, second_current, historical]
    monkeypatch.setattr(downstream, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(
        downstream, "resolve_model_lab_authority", lambda *_args: _resolved()
    )
    monkeypatch.setattr(downstream, "_read_runs", lambda *_args: runs)
    monkeypatch.setattr(
        downstream,
        "_persist_object",
        lambda _kind, body: {**body, "receiptSha256": downstream._sha(body)},
    )
    groups = downstream._group_attempts([current, second_current])
    group = groups[0]
    downstream.save_finalist_selection(
        object(),
        lab.EXPECTED_PROJECT_ID,
        _finalist_payloads(groups),
        actor_user_id="scientist",
    )
    return repository, group


def test_project_downstream_replaces_zero_fit_placeholder_with_current_evidence(
    workflow,
) -> None:
    _repository, group = workflow
    result = downstream.project_stage3_downstream(
        object(), lab.EXPECTED_PROJECT_ID
    )
    assert result["finalists"][0]["candidateFingerprint"] == group[
        "candidateFingerprint"
    ]
    assert result["finalists"][0]["meanOofLogLoss"] == pytest.approx(1.473323)
    assert result["historicalBenchmark"]["meanOofLogLoss"] == pytest.approx(
        1.472899
    )
    assert result["activity"] == {
        "newFitsOnPageLoad": 0,
        "calibrationFits": 0,
        "simulationRuns": 0,
        "finalOotRowsAccessed": 0,
        "providerCalls": 0,
        "modelsPromoted": 0,
        "modelsExported": 0,
    }
    assert result["population"]["finalOotLocked"] is True
    assert result["population"]["finalOotTargetAccessed"] is False


def test_worse_candidate_can_be_registered_as_research_challenger_without_promotion(
    workflow,
) -> None:
    _repository, group = workflow
    fingerprint = str(group["candidateFingerprint"])
    calibration = downstream.save_project_calibration_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {"candidateFingerprint": fingerprint, "disposition": "RETAIN_RAW"},
        actor_user_id="scientist",
    )["decision"]
    assert calibration["calibrationApplied"] is False
    assert calibration["rawMetrics"]["ece"] == pytest.approx(0.004)

    game = downstream.save_project_game_evaluation_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {
            "candidateFingerprint": fingerprint,
            "disposition": "DEFER_UNTIL_EXECUTABLE_ARTIFACT",
        },
        actor_user_id="scientist",
    )["decision"]
    assert game["gameSimulationRun"] is False
    assert game["developmentResearchSelectionMayContinue"] is True
    assert "GOVERNED_PREGAME_LINEUP_AUTHORITY" in game["missingPrerequisites"]

    selection = downstream.save_project_challenger_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {
            "candidateFingerprint": fingerprint,
            "decision": "REGISTER_RESEARCH_CHALLENGER",
        },
        actor_user_id="scientist",
    )["decision"]
    comparison = selection["developmentComparison"]
    assert comparison["candidateOutperformedBenchmark"] is False
    assert comparison["outperformanceRequiredToRegisterResearchChallenger"] is False
    assert selection["modelStatus"] == "RESEARCH_CHALLENGER"
    assert selection["championSelected"] is False
    assert selection["promotionStatus"] == "NOT_PROMOTED"
    assert selection["finalOotTargetAccessed"] is False

    registered = downstream.register_project_research_handoff(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {"selectionId": selection["decisionId"]},
        actor_user_id="scientist",
    )
    assert registered["entry"]["modelStatus"] == "RESEARCH_CHALLENGER"
    assert registered["entry"]["artifactStatus"] == (
        "EXECUTABLE_ARTIFACT_NOT_MATERIALIZED"
    )
    assert registered["entry"]["deploymentStatus"] == "NOT_DEPLOYABLE"
    assert registered["entry"]["exportStatus"] == "NOT_EXPORTED"
    assert registered["entry"]["modelsFit"] == 0
    replay = downstream.register_project_research_handoff(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {"selectionId": selection["decisionId"]},
        actor_user_id="scientist",
    )
    assert replay["idempotentReplay"] is True
    assert replay["entry"]["registryEntryId"] == registered["entry"][
        "registryEntryId"
    ]


def test_game_evaluation_fails_closed_until_calibration_disposition_is_saved(
    workflow,
) -> None:
    _repository, group = workflow
    with pytest.raises(lab.Stage3ModelLaboratoryError) as exc_info:
        downstream.save_project_game_evaluation_decision(
            object(),
            lab.EXPECTED_PROJECT_ID,
            {
                "candidateFingerprint": group["candidateFingerprint"],
                "disposition": "DEFER_UNTIL_EXECUTABLE_ARTIFACT",
            },
            actor_user_id="scientist",
        )
    assert exc_info.value.code == "STAGE3_CURRENT_CALIBRATION_DECISION_REQUIRED"


def test_second_finalist_recalibration_invalidates_the_older_game_chain(
    workflow,
) -> None:
    _repository, first_group = workflow
    initial = downstream.project_stage3_downstream(
        object(), lab.EXPECTED_PROJECT_ID
    )
    assert len(initial["finalists"]) == 2
    first_fingerprint = str(first_group["candidateFingerprint"])
    second_fingerprint = next(
        str(item["candidateFingerprint"])
        for item in initial["finalists"]
        if item["candidateFingerprint"] != first_fingerprint
    )

    first_calibration = downstream.save_project_calibration_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {"candidateFingerprint": first_fingerprint, "disposition": "RETAIN_RAW"},
        actor_user_id="scientist",
    )["decision"]
    downstream.save_project_game_evaluation_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {
            "candidateFingerprint": first_fingerprint,
            "disposition": "DEFER_UNTIL_EXECUTABLE_ARTIFACT",
        },
        actor_user_id="scientist",
    )
    before_change = downstream.project_stage3_downstream(
        object(), lab.EXPECTED_PROJECT_ID
    )
    assert before_change["gates"]["gameEvaluationDecisionCurrent"] is True

    second_calibration = downstream.save_project_calibration_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {"candidateFingerprint": second_fingerprint, "disposition": "RETAIN_RAW"},
        actor_user_id="scientist",
    )["decision"]
    assert second_calibration["decisionId"] != first_calibration["decisionId"]
    after_change = downstream.project_stage3_downstream(
        object(), lab.EXPECTED_PROJECT_ID
    )
    assert after_change["gates"]["calibrationDecisionCurrent"] is True
    assert after_change["gates"]["gameEvaluationDecisionCurrent"] is False
    assert after_change["gates"]["challengerDecisionReady"] is False

    with pytest.raises(lab.Stage3ModelLaboratoryError) as exc_info:
        downstream.save_project_challenger_decision(
            object(),
            lab.EXPECTED_PROJECT_ID,
            {
                "candidateFingerprint": second_fingerprint,
                "decision": "REGISTER_RESEARCH_CHALLENGER",
            },
            actor_user_id="scientist",
        )
    assert exc_info.value.code == "STAGE3_CURRENT_DOWNSTREAM_REVIEW_REQUIRED"


def test_new_finalist_selection_invalidates_old_selection_and_registry_chain(
    workflow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repository, group = workflow
    fingerprint = str(group["candidateFingerprint"])
    initial = downstream.project_stage3_downstream(
        object(), lab.EXPECTED_PROJECT_ID
    )
    initial_finalist_selection_id = initial["authority"]["finalistSelectionId"]
    downstream.save_project_calibration_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {"candidateFingerprint": fingerprint, "disposition": "RETAIN_RAW"},
        actor_user_id="scientist",
    )
    downstream.save_project_game_evaluation_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {
            "candidateFingerprint": fingerprint,
            "disposition": "DEFER_UNTIL_EXECUTABLE_ARTIFACT",
        },
        actor_user_id="scientist",
    )
    selection = downstream.save_project_challenger_decision(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {
            "candidateFingerprint": fingerprint,
            "decision": "REGISTER_RESEARCH_CHALLENGER",
        },
        actor_user_id="scientist",
    )["decision"]
    downstream.register_project_research_handoff(
        object(),
        lab.EXPECTED_PROJECT_ID,
        {"selectionId": selection["decisionId"]},
        actor_user_id="scientist",
    )
    current = downstream.project_stage3_downstream(
        object(), lab.EXPECTED_PROJECT_ID
    )
    assert current["gates"]["challengerDecisionCurrent"] is True
    assert current["gates"]["registryHandoffCurrent"] is True

    monkeypatch.setattr(downstream, "now_iso", lambda: "2099-01-01T00:00:00Z")
    new_finalists = downstream.save_finalist_selection(
        object(),
        lab.EXPECTED_PROJECT_ID,
        _finalist_payload(group),
        actor_user_id="scientist",
    )["selection"]
    assert new_finalists["selectionId"] != initial_finalist_selection_id

    stale = downstream.project_stage3_downstream(
        object(), lab.EXPECTED_PROJECT_ID
    )
    assert stale["gates"]["calibrationDecisionCurrent"] is False
    assert stale["gates"]["challengerDecisionCurrent"] is False
    assert stale["gates"]["registryHandoffCurrent"] is False

    with pytest.raises(lab.Stage3ModelLaboratoryError) as exc_info:
        downstream.register_project_research_handoff(
            object(),
            lab.EXPECTED_PROJECT_ID,
            {"selectionId": selection["decisionId"]},
            actor_user_id="scientist",
        )
    assert exc_info.value.code == "STAGE3_RESEARCH_CHALLENGER_SELECTION_REQUIRED"
