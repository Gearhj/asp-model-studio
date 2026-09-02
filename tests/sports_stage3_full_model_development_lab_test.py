from __future__ import annotations

import os
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest

from server.persistence.db import Database
from server.sports_current_statcast import stage3_model_catalog as catalog
from server.sports_current_statcast import stage3_model_eligibility as eligibility
from server.sports_current_statcast import stage3_model_jobs as jobs
from server.sports_current_statcast import stage3_model_laboratory as lab


def _row(
    name: str,
    *,
    role: str = "PREGAME_FEATURE",
    governance: str = "ELIGIBLE",
    availability: str = "AVAILABLE_IN_EXACT_CONTEXTUAL_GOLD",
    missing: float = 0.0,
    leakage: str = "NO_TARGET_OR_FUTURE_EVIDENCE",
    cold_start: str = "NOT_APPLICABLE",
    forecast: str = "PREGAME_KNOWN",
    order: int = 1,
) -> dict[str, object]:
    return {
        "name": name,
        "order": order,
        "role": role,
        "dataType": "NUMERIC",
        "featureFamily": "TEST",
        "governanceStatus": governance,
        "availabilityStatus": availability,
        "missingPercentDevelopment": missing,
        "leakageRisk": leakage,
        "coldStartRelevance": cold_start,
        "forecastTimeAvailability": forecast,
        "pointInTimeTreatment": "PRIOR_EVIDENCE_ONLY",
        "sourceLineage": ["governed-test-authority"],
        "inactiveReason": "Rivalry mapping is proposed but not approved." if governance != "ELIGIBLE" else None,
    }


def _authority() -> SimpleNamespace:
    eda = SimpleNamespace(
        project_id="asp-mtddc6pw",
        source_dataset_id="asp.mlb.statcast.current-pa.v1",
        source_manifest_sha="1" * 64,
        gold_manifest_sha=lab.EXPECTED_GOLD_MANIFEST_SHA,
        contextual_manifest_sha="2" * 64,
        review_digest="3" * 64,
    )
    return SimpleNamespace(
        project_id="asp-mtddc6pw",
        authority_key="authority-key",
        project_name="MLB 2026 Current-Data Game Forecast Challenger",
        eda_authority=eda,
        split={
            "contractId": lab.EXPECTED_SPLIT["splitContractId"],
            "contractVersion": 2,
            "checksum": lab.EXPECTED_SPLIT["checksum"],
        },
        outlier_policy={
            "policyId": lab.EXPECTED_OUTLIER_POLICY["policyId"],
            "policyVersion": 2,
            "checksum": lab.EXPECTED_OUTLIER_POLICY["checksum"],
        },
        missing_policy={
            "policyId": lab.EXPECTED_MISSING_POLICY["policyId"],
            "policyVersion": 2,
            "checksum": lab.EXPECTED_MISSING_POLICY["checksum"],
        },
        feature_sets=[],
    )


def _exact_rows() -> list[dict[str, object]]:
    rows = [_row(f"eligible_{index:03d}", order=index + 1) for index in range(228)]
    rows.append(
        _row(
            "cold_start_governed",
            cold_start="RELEVANT_GOVERNED_PRIOR_AND_INDICATOR",
            order=len(rows) + 1,
        )
    )
    for name in ("context_inning", "context_half", "context_outs", "context_base_mask", "context_score_diff"):
        rows.append(
            _row(
                name,
                role="SIMULATION_GENERATED_STATE",
                forecast=eligibility.SIMULATOR_SUPPLIED_CONTRACT,
                order=len(rows) + 1,
            )
        )
    for name in eligibility.SOURCE_UNAVAILABLE_FEATURES:
        rows.append(_row(name, missing=100.0, order=len(rows) + 1))
    rows.extend(
        [
            _row("holiday_name", missing=97.8554, order=len(rows) + 1),
            _row("doubleheader_game_number", missing=98.0817, order=len(rows) + 2),
        ]
    )
    for index in range(12):
        rows.append(
            _row(
                f"unapproved_rivalry_{index:02d}",
                governance="PROPOSED_NOT_APPROVED",
                missing=100.0,
                order=len(rows) + 1,
            )
        )
    assert len(rows) == 254
    return rows


def _build_exact_eligibility(monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, dict[str, object]]:
    authority = _authority()
    rows = _exact_rows()
    monkeypatch.setattr(eligibility.feature_engineering, "_catalog", lambda _authority: (rows, {}))
    monkeypatch.setattr(
        eligibility.feature_engineering,
        "_default_transformations",
        lambda ordered, _by_name: {
            "schemaVersion": "TEST_TRANSFORMATIONS_V1",
            "ordered": [{"feature": name, "steps": ["RETAIN_RAW"]} for name in ordered],
        },
    )
    return authority, eligibility.build_model_eligibility(authority)


def test_full_eligible_exact_counts_and_governed_exclusions_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _authority_value, result = _build_exact_eligibility(monkeypatch)
    assert result["featureSetKey"] == "FULL_ELIGIBLE_MODELING_SET"
    assert result["featureCount"] == 234
    assert result["reconciliation"] == {
        "physicalCandidateCount": 254,
        "eligiblePredictorCount": 234,
        "excludedPredictorCount": 20,
        "sourceUnavailable": 6,
        "missingness": 2,
        "pitLeakage": 0,
        "identity": 0,
        "computationFailure": 0,
        "other": 12,
    }
    assert set(eligibility.SOURCE_UNAVAILABLE_FEATURES).isdisjoint(result["orderedFeatures"])
    assert "holiday_name" not in result["orderedFeatures"]
    assert "doubleheader_game_number" not in result["orderedFeatures"]
    assert "cold_start_governed" in result["orderedFeatures"]
    assert result["coldStartRowsDropped"] is False
    assert result["simulatorGeneratedStateFeatures"] == [
        "context_inning",
        "context_half",
        "context_outs",
        "context_base_mask",
        "context_score_diff",
    ]
    assert result["finalOotLocked"] is True
    assert result["finalOotTargetAccessed"] is False


def test_default_binary_transform_matches_adopted_data_type_aware_missing_policy() -> None:
    transformations = eligibility.feature_engineering._default_transformations(
        ["complete_flag", "physically_missing_flag"],
        {
            "complete_flag": {
                "binary": True,
                "dataType": "numeric",
                "missingPercentDevelopment": 0.0,
            },
            "physically_missing_flag": {
                "binary": True,
                "dataType": "numeric",
                "missingPercentDevelopment": 0.661,
            },
        },
    )
    assert transformations["ordered"] == [
        {"feature": "complete_flag", "steps": ["BINARY_PASSTHROUGH"]},
        {"feature": "physically_missing_flag", "steps": ["BINARY_MODE_IMPUTE"]},
    ]


@pytest.mark.parametrize(
    ("row", "classification", "status", "override"),
    [
        (_row("source", availability="SOURCE_UNAVAILABLE", missing=100.0), "SOURCE_UNAVAILABLE", "SOURCE_UNAVAILABLE_EXCLUDED", False),
        (_row("complete_null", missing=100.0), "MISSINGNESS", "ONE_HUNDRED_PERCENT_MISSING_EXCLUDED", False),
        (_row("sparse_95", missing=95.0), "MISSINGNESS", "REVIEW_REQUIRED_SEMANTIC_SPARSE", True),
        (_row("sparse_80", missing=80.0), "MISSINGNESS", "REVIEW_REQUIRED_80_TO_95_PERCENT_MISSING", True),
        (_row("sparse_50", missing=50.0), "MISSINGNESS", "REVIEW_REQUIRED_50_TO_80_PERCENT_MISSING", True),
        (_row("failed", availability="COMPUTATION_FAILURE"), "COMPUTATION_FAILURE", "COMPUTATION_FAILURE_EXCLUDED", False),
        (_row("future_sparse", missing=99.0, leakage="FUTURE_TARGET_EVIDENCE"), "PIT_LEAKAGE", "POINT_IN_TIME_CONTRACT_REJECTED", False),
        (_row("identifier", role="IDENTIFIER"), "IDENTITY", "ROLE_NOT_MODEL_ELIGIBLE", False),
        (_row("sim_unsafe", role="SIMULATION_GENERATED_STATE", forecast="ACTUAL_TARGET_GAME_STATE"), "PIT_LEAKAGE", "SIMULATOR_SUPPLY_CONTRACT_MISSING", False),
    ],
)
def test_feature_eligibility_fail_closed_rules(
    row: dict[str, object], classification: str, status: str, override: bool
) -> None:
    result = eligibility._classification(row)
    assert result["eligible"] is False
    assert result["classification"] == classification
    assert result["status"] == status
    assert result["overrideAllowed"] is override


def test_cold_start_and_exact_simulator_contract_remain_eligible() -> None:
    cold = eligibility._classification(
        _row("cold", cold_start="RELEVANT_GOVERNED_PRIOR_AND_INDICATOR")
    )
    simulator = eligibility._classification(
        _row(
            "context_inning",
            role="SIMULATION_GENERATED_STATE",
            forecast=eligibility.SIMULATOR_SUPPLIED_CONTRACT,
        )
    )
    assert cold["eligible"] is True
    assert cold["status"] == "ELIGIBLE_COLD_START_GOVERNED"
    assert simulator["eligible"] is True
    assert simulator["status"] == "ELIGIBLE_SIMULATOR_SUPPLIED_STATE"


def test_preserved_feature_sets_are_assessed_without_mutating_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _authority_value, result = _build_exact_eligibility(monkeypatch)
    a = {"featureSetId": "A", "orderedFeatures": ["eligible_000"]}
    b = {"featureSetId": "B", "orderedFeatures": ["eligible_000", "holiday_name", "doubleheader_game_number"]}
    c = {"featureSetId": "C", "orderedFeatures": ["eligible_000", *eligibility.SOURCE_UNAVAILABLE_FEATURES]}
    assert eligibility.assess_feature_set(a, result)["executionStatus"] == "EXECUTABLE"
    b_result = eligibility.assess_feature_set(b, result)
    assert b_result["executionStatus"] == "REVIEW_REQUIRED_DEFAULT_EXCLUDED"
    assert {item["name"] for item in b_result["reviewRequiredFeatures"]} == {
        "holiday_name", "doubleheader_game_number"
    }
    c_result = eligibility.assess_feature_set(c, result)
    assert c_result["executionStatus"] == "NON_EXECUTABLE_CURRENT_AUTHORITY"
    assert {item["name"] for item in c_result["blockingFeatures"]} == set(
        eligibility.SOURCE_UNAVAILABLE_FEATURES
    )
    assert c_result["historicalRegistrationPreserved"] is True
    assert c_result["immutableRegistrationMutated"] is False
    for broken in (
        {"featureSetId": "empty", "orderedFeatures": []},
        {"featureSetId": "unknown", "orderedFeatures": ["not_in_authority"]},
        {"featureSetId": "duplicate", "orderedFeatures": ["eligible_000", "eligible_000"]},
    ):
        assert eligibility.assess_feature_set(broken, result)["executionStatus"] == "NON_EXECUTABLE_CURRENT_AUTHORITY"


def test_model_catalog_taxonomy_and_compute_guards() -> None:
    models = {item["id"]: item for item in catalog.model_catalog()}
    assert set(models) == {
        "class_frequency_null", "multinomial_logistic", "elastic_net_logistic",
        "decision_tree", "random_forest", "extra_trees", "histogram_gradient_boosting",
        "xgboost", "lightgbm", "catboost", "linear_svm", "sgd_classifier", "knn",
        "gaussian_naive_bayes", "mlp",
    }
    assert models["knn"]["available"] is False
    assert models["knn"]["status"] == "COMPUTE_GUARDED"
    assert models["knn"]["computeGuard"]["fullPopulationAutoExecution"] is False
    assert all(
        item["defaultTuningMode"] == "FIXED" for item in models.values()
    )
    assert models["elastic_net_logistic"]["automaticBundleEligible"] is False
    assert (
        models["elastic_net_logistic"]["computeGuard"][
            "fullEligibleFeatureSetExecution"
        ]
        is False
    )
    assert models["sgd_classifier"]["automaticBundleEligible"] is True
    anomaly = catalog.anomaly_analytics_catalog()
    assert anomaly["rankingMetric"] is None
    assert anomaly["status"] == "SEPARATE_RESEARCH_CAPABILITY_NOT_MODEL_COMPETITION"
    for identifier, definition in models.items():
        if identifier in {"class_frequency_null", "knn"} or not definition["available"]:
            continue
        estimator = lab._model(identifier, 123, definition["fixedHyperparameters"])
        assert hasattr(estimator, "fit")
        if identifier in {"random_forest", "extra_trees", "xgboost", "lightgbm"}:
            assert estimator.n_jobs == 1


def test_fixed_grid_random_counts_are_exact_deterministic_and_bounded() -> None:
    models = {item["id"]: item for item in catalog.model_catalog()}
    xgb = models["xgboost"]
    compact = catalog.plan_configurations(xgb, {"tuningMode": "GRID", "gridPreset": "COMPACT"}, seed=7)
    assert compact["configurationCount"] == 6
    assert compact["totalFits"] == 30
    full = catalog.plan_configurations(xgb, {"tuningMode": "GRID", "gridPreset": "FULL"}, seed=7)
    assert full["configurationCount"] == 1_152
    assert full["totalFits"] == 5_760
    assert full["configurations"] == []
    assert full["exceedsHardLimit"] is True
    random_one = catalog.plan_configurations(
        xgb, {"tuningMode": "RANDOM", "gridPreset": "FULL", "randomIterations": 7}, seed=91
    )
    random_two = catalog.plan_configurations(
        xgb, {"tuningMode": "RANDOM", "gridPreset": "FULL", "randomIterations": 7}, seed=91
    )
    assert random_one["configurations"] == random_two["configurations"]
    assert random_one["configurationCount"] == 7
    assert random_one["totalFits"] == 35
    fixed = catalog.plan_configurations(
        models["multinomial_logistic"], {"tuningMode": "FIXED"}, seed=1
    )
    assert fixed["configurationCount"] == 1
    assert fixed["totalFits"] == 5


def test_legacy_runtime_controls_are_migrated_before_candidate_identity() -> None:
    models = {item["id"]: item for item in catalog.model_catalog()}
    xgb = models["xgboost"]

    for algorithm_id in (
        "random_forest",
        "extra_trees",
        "xgboost",
        "lightgbm",
        "knn",
    ):
        definition = models[algorithm_id]
        clean_fixed = catalog.plan_configurations(
            definition,
            {"tuningMode": "FIXED"},
            seed=7,
        )
        for legacy_value in (1, 1.0):
            migrated_fixed = catalog.plan_configurations(
                definition,
                {
                    "tuningMode": "FIXED",
                    "fixedHyperparameters": {"n_jobs": legacy_value},
                },
                seed=7,
            )
            assert migrated_fixed == clean_fixed
            assert "n_jobs" not in migrated_fixed["configurations"][0]

    clean_compact = catalog.plan_configurations(
        xgb,
        {
            "tuningMode": "GRID",
            "gridPreset": "COMPACT",
            "compactGrid": [dict(xgb["fixedHyperparameters"])],
        },
        seed=7,
    )
    migrated_compact = catalog.plan_configurations(
        xgb,
        {
            "tuningMode": "GRID",
            "gridPreset": "COMPACT",
            "compactGrid": [
                {**dict(xgb["fixedHyperparameters"]), "n_jobs": 1}
            ],
        },
        seed=7,
    )
    assert migrated_compact == clean_compact

    clean_custom = catalog.plan_configurations(
        xgb,
        {
            "tuningMode": "GRID",
            "gridPreset": "CUSTOM",
            "customGrid": {"max_depth": [5]},
        },
        seed=7,
    )
    migrated_custom = catalog.plan_configurations(
        xgb,
        {
            "tuningMode": "GRID",
            "gridPreset": "CUSTOM",
            "customGrid": {"max_depth": [5], "n_jobs": [1]},
        },
        seed=7,
    )
    assert migrated_custom == clean_custom

    catboost = models["catboost"]
    clean_catboost = catalog.plan_configurations(
        catboost,
        {"tuningMode": "FIXED"},
        seed=7,
    )
    migrated_catboost = catalog.plan_configurations(
        catboost,
        {
            "tuningMode": "FIXED",
            "fixedHyperparameters": {"thread_count": 1},
        },
        seed=7,
    )
    assert migrated_catboost == clean_catboost


def test_legacy_runtime_control_migration_remains_strict() -> None:
    models = {item["id"]: item for item in catalog.model_catalog()}
    xgb = models["xgboost"]
    for rejected in (True, False, -1, 0, 2, "1", None):
        with pytest.raises(ValueError, match="n_jobs is runtime-managed"):
            catalog.plan_configurations(
                xgb,
                {
                    "tuningMode": "FIXED",
                    "fixedHyperparameters": {"n_jobs": rejected},
                },
                seed=7,
            )
    for rejected_domain in ([True], [-1], [0], [2], ["1"], [1, 1]):
        with pytest.raises(ValueError, match="n_jobs is runtime-managed"):
            catalog.plan_configurations(
                xgb,
                {
                    "tuningMode": "GRID",
                    "gridPreset": "CUSTOM",
                    "customGrid": {
                        "max_depth": [5],
                        "n_jobs": rejected_domain,
                    },
                },
                seed=7,
            )
    for unknown in ("n_job", "njobs", "worker_count"):
        with pytest.raises(ValueError, match="Unsupported hyperparameter"):
            catalog.plan_configurations(
                xgb,
                {
                    "tuningMode": "FIXED",
                    "fixedHyperparameters": {unknown: 1},
                },
                seed=7,
            )
    with pytest.raises(ValueError, match="Unsupported hyperparameter.*thread_count"):
        catalog.plan_configurations(
            xgb,
            {
                "tuningMode": "FIXED",
                "fixedHyperparameters": {"thread_count": 1},
            },
            seed=7,
        )


def test_runtime_native_worker_authority_overrides_legacy_candidate_knobs() -> None:
    models = {item["id"]: item for item in catalog.model_catalog()}
    parameters = {**models["random_forest"]["fixedHyperparameters"], "n_jobs": 1}
    estimator = lab._model(
        "random_forest",
        123,
        parameters,
        native_workers=3,
    )
    assert estimator.n_jobs == lab._bounded_native_workers(3)
    assert parameters["n_jobs"] == 1


def test_unsafe_hyperparameters_and_empty_custom_grid_fail_at_planning() -> None:
    models = {item["id"]: item for item in catalog.model_catalog()}
    with pytest.raises(ValueError, match="early_stopping"):
        catalog.plan_configurations(
            models["histogram_gradient_boosting"],
            {"tuningMode": "FIXED", "fixedHyperparameters": {"early_stopping": True}},
            seed=1,
        )
    with pytest.raises(ValueError, match="n_jobs"):
        catalog.plan_configurations(
            models["random_forest"],
            {"tuningMode": "FIXED", "fixedHyperparameters": {"n_jobs": -1}},
            seed=1,
        )
    with pytest.raises(ValueError, match="requires at least one parameter domain"):
        catalog.plan_configurations(
            models["multinomial_logistic"],
            {"tuningMode": "GRID", "gridPreset": "CUSTOM", "customGrid": {}},
            seed=1,
        )
    with pytest.raises(ValueError, match="min_samples_split"):
        catalog.plan_configurations(
            models["decision_tree"],
            {
                "tuningMode": "FIXED",
                "fixedHyperparameters": {"min_samples_split": 1},
            },
            seed=1,
        )
    if models["catboost"]["available"]:
        with pytest.raises(ValueError, match="depth"):
            catalog.plan_configurations(
                models["catboost"],
                {
                    "tuningMode": "FIXED",
                    "fixedHyperparameters": {"depth": 17},
                },
                seed=1,
            )
    if models["lightgbm"]["available"]:
        with pytest.raises(ValueError, match="num_leaves"):
            catalog.plan_configurations(
                models["lightgbm"],
                {
                    "tuningMode": "FIXED",
                    "fixedHyperparameters": {"num_leaves": 1},
                },
                seed=1,
            )


def _planner(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> tuple[Database, SimpleNamespace, dict[str, object]]:
    authority, full = _build_exact_eligibility(monkeypatch)
    authority.feature_sets = [
        {"featureSetId": "A", "name": "A CORE_GOLD_48", "checksum": "a" * 64, "orderedFeatures": ["eligible_000"]},
        {"featureSetId": "B", "name": "B CORE_PLUS_CALENDAR", "checksum": "b" * 64, "orderedFeatures": ["eligible_000", "holiday_name", "doubleheader_game_number"]},
        {"featureSetId": "C", "name": "C CORE_PLUS_REST_TRAVEL", "checksum": "c" * 64, "orderedFeatures": ["eligible_000", *eligibility.SOURCE_UNAVAILABLE_FEATURES]},
    ]
    monkeypatch.setattr(jobs, "resolve_model_lab_authority", lambda _database, _project: authority)
    monkeypatch.setattr(jobs, "build_model_eligibility", lambda _resolved: full)
    return Database(tmp_path / "plan.db"), authority, full


def _payload(authority: SimpleNamespace, experiment: dict[str, object]) -> dict[str, object]:
    return {
        "authorityKey": authority.authority_key,
        "splitContractId": authority.split["contractId"],
        "experiments": [experiment],
        "seed": 20260901,
    }


def test_legacy_runtime_control_does_not_change_signed_plan_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    database, authority, _full = _planner(monkeypatch, tmp_path)
    clean = jobs.plan_model_development_queue(
        database,
        authority.project_id,
        _payload(
            authority,
            {"algorithmId": "random_forest", "tuningMode": "FIXED"},
        ),
    )
    migrated = jobs.plan_model_development_queue(
        database,
        authority.project_id,
        _payload(
            authority,
            {
                "algorithmId": "random_forest",
                "tuningMode": "FIXED",
                "fixedHyperparameters": {"n_jobs": 1},
            },
        ),
    )
    assert migrated == clean
    assert migrated["planId"] == clean["planId"]
    assert migrated["checksum"] == clean["checksum"]
    assert "n_jobs" not in migrated["experiments"][0]["tuning"]["configurations"][0]
    assert migrated["experiments"][0]["executionResources"]["nativeWorkers"] >= 1


def test_queue_plan_defaults_to_full_eligible_and_never_scans_or_fits(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    database, authority, full = _planner(monkeypatch, tmp_path)
    monkeypatch.setattr(jobs, "_fold_frame", lambda *_args, **_kwargs: pytest.fail("planning must not scan"))
    monkeypatch.setattr(jobs, "_evaluate_candidate", lambda *_args, **_kwargs: pytest.fail("planning must not fit"))
    plan = jobs.plan_model_development_queue(
        database,
        authority.project_id,
        _payload(
            authority,
            {"algorithmId": "multinomial_logistic", "tuningMode": "FIXED", "gridPreset": "COMPACT"},
        ),
    )
    assert plan["experiments"][0]["featureUniverseId"] == full["featureSetId"]
    assert plan["experiments"][0]["featureCount"] == 234
    assert plan["totalFits"] == 5
    assert plan["executable"] is True
    assert plan["finalOotTargetAccessed"] is False
    assert plan["promotionRequested"] is False


def test_full_feature_saga_is_compute_guarded_but_bounded_subset_remains_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    database, authority, full = _planner(monkeypatch, tmp_path)
    full_request = _payload(
        authority,
        {"algorithmId": "elastic_net_logistic", "tuningMode": "FIXED"},
    )
    with pytest.raises(lab.Stage3ModelLaboratoryError) as guarded:
        jobs.plan_model_development_queue(
            database, authority.project_id, full_request
        )
    assert guarded.value.code == "MODEL_DEVELOPMENT_RESOURCE_GUARD"
    assert "sgd_classifier" in str(guarded.value)

    cloned_full = _payload(
        authority,
        {
            "algorithmId": "elastic_net_logistic",
            "featureUniverseId": "CUSTOM_SUBSET",
            "orderedFeatures": list(full["orderedFeatures"]),
            "tuningMode": "FIXED",
        },
    )
    with pytest.raises(lab.Stage3ModelLaboratoryError) as cloned_guard:
        jobs.plan_model_development_queue(
            database, authority.project_id, cloned_full
        )
    assert cloned_guard.value.code == "MODEL_DEVELOPMENT_RESOURCE_GUARD"

    bounded = _payload(
        authority,
        {
            "algorithmId": "elastic_net_logistic",
            "featureUniverseId": "CUSTOM_SUBSET",
            "orderedFeatures": list(full["orderedFeatures"][:8]),
            "tuningMode": "FIXED",
        },
    )
    plan = jobs.plan_model_development_queue(
        database, authority.project_id, bounded
    )
    assert plan["experiments"][0]["featureCount"] == 8
    assert plan["totalFits"] == 5


def test_round_robin_tasks_and_resource_compatibility_are_deterministic() -> None:
    def experiment(
        identifier: str,
        count: int,
        *,
        exclusive: bool = False,
        feature_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "experimentId": identifier,
            "algorithmId": identifier,
            "featureSetContract": (
                {
                    "featureSetId": feature_id,
                    "checksum": feature_id * 64,
                }
                if feature_id
                else None
            ),
            "executionResources": {
                "exclusiveCandidate": exclusive,
                "nativeWorkers": 1,
            },
            "tuning": {
                "configurations": [
                    {"configuration": index} for index in range(1, count + 1)
                ]
            },
        }

    tasks = jobs._build_candidate_tasks(
        [experiment("alpha", 3), experiment("beta", 2)]
    )
    assert [task["taskId"] for task in tasks] == [
        "alpha:1",
        "beta:1",
        "alpha:2",
        "beta:2",
        "alpha:3",
    ]
    assert jobs._task_can_start(tasks[1], [tasks[0]]) is True
    assert jobs._task_can_start(tasks[2], [tasks[0]]) is False
    exclusive = jobs._build_candidate_tasks([experiment("heavy", 1, exclusive=True)])[0]
    assert jobs._task_can_start(exclusive, [tasks[0]]) is False
    assert jobs._task_can_start(exclusive, []) is True
    assert jobs._task_can_start(tasks[0], [exclusive]) is False

    feature_grouped = jobs._build_candidate_tasks(
        [
            experiment("alpha", 2, feature_id="a"),
            experiment("beta", 2, feature_id="b"),
            experiment("gamma", 2, feature_id="a"),
        ]
    )
    assert [task["taskId"] for task in feature_grouped] == [
        "alpha:1",
        "gamma:1",
        "alpha:2",
        "gamma:2",
        "beta:1",
        "beta:2",
    ]
    assert jobs._task_can_start(feature_grouped[-2], [feature_grouped[0]]) is False


def test_native_worker_budget_is_bounded_and_model_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(jobs, "_physical_memory_bytes", lambda: 32 * 1024**3)
    monkeypatch.setattr(jobs, "_available_memory_bytes", lambda: 28 * 1024**3)
    definitions = {item["id"]: item for item in catalog.model_catalog()}
    xgb = jobs._execution_resources(definitions["xgboost"])
    logistic = jobs._execution_resources(definitions["multinomial_logistic"])
    assert xgb["exclusiveCandidate"] is True
    assert xgb["nativeWorkers"] == 4
    assert logistic["exclusiveCandidate"] is False
    assert logistic["nativeWorkers"] == 1
    contract = jobs._parallelism(
        [{"computeIntensity": "VERY_HIGH", "executionResources": xgb}], "AUTO"
    )
    assert contract["effectiveCandidateWorkers"] == 2
    assert contract["exclusiveCandidateWorkers"] == 1
    assert contract["maximumEstimatorNativeWorkers"] == 4
    assert contract["schedulingPolicy"] == jobs.MODEL_DEVELOPMENT_SCHEDULING_POLICY

    monkeypatch.setattr(jobs, "_available_memory_bytes", lambda: 8 * 1024**3)
    # Volatile free memory cannot change the reviewed plan identity. It may
    # only reduce actual concurrency when the job starts.
    stable_plan = jobs._parallelism(
        [{"computeIntensity": "VERY_HIGH", "executionResources": xgb}], "AUTO"
    )
    assert stable_plan == contract
    constrained = jobs._runtime_candidate_worker_admission(2)
    assert constrained["effectiveCandidateWorkers"] == 1
    assert constrained["availableMemoryGiBAtStart"] == 8.0


def test_c_is_rejected_before_scan_and_b_override_is_auditable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    database, authority, _full = _planner(monkeypatch, tmp_path)
    monkeypatch.setattr(jobs, "_fold_frame", lambda *_args, **_kwargs: pytest.fail("planner must not scan"))
    with pytest.raises(lab.Stage3ModelLaboratoryError) as c_error:
        jobs.plan_model_development_queue(
            database,
            authority.project_id,
            _payload(authority, {"algorithmId": "multinomial_logistic", "featureUniverseId": "C", "tuningMode": "FIXED"}),
        )
    assert c_error.value.code == "MODEL_DEVELOPMENT_FEATURE_SET_NON_EXECUTABLE"
    with pytest.raises(lab.Stage3ModelLaboratoryError) as b_error:
        jobs.plan_model_development_queue(
            database,
            authority.project_id,
            _payload(
                authority,
                {
                    "algorithmId": "multinomial_logistic",
                    "featureUniverseId": "B",
                    "tuningMode": "FIXED",
                    "eligibilityOverrideRationale": "A sufficiently long scientific rationale.",
                },
            ),
        )
    assert b_error.value.code == "MODEL_DEVELOPMENT_FEATURE_SET_SEMANTIC_ACK_REQUIRED"
    experiment = {
        "algorithmId": "multinomial_logistic",
        "featureUniverseId": "B",
        "tuningMode": "FIXED",
        "eligibilityOverrideRationale": "Null means no governed calendar state for this prospective run.",
        "prospectiveSemanticCompatibilityAcknowledged": True,
        "foldLocalTreatmentAcknowledged": True,
    }
    plan = jobs.plan_model_development_queue(
        database, authority.project_id, _payload(authority, experiment)
    )
    override = plan["experiments"][0]["featureSetContract"]["executionCompatibilityOverride"]
    assert override["rationale"] == experiment["eligibilityOverrideRationale"]
    assert override["prospectiveSemanticCompatibilityAcknowledged"] is True
    assert override["foldLocalTreatmentAcknowledged"] is True


def test_nested_forbidden_options_custom_subset_and_stale_plan_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    database, authority, full = _planner(monkeypatch, tmp_path)
    with pytest.raises(lab.Stage3ModelLaboratoryError) as forbidden:
        jobs.plan_model_development_queue(
            database,
            authority.project_id,
            _payload(
                authority,
                {"algorithmId": "multinomial_logistic", "tuningMode": "FIXED", "promote": True},
            ),
        )
    assert forbidden.value.code == "MODEL_DEVELOPMENT_FORBIDDEN_OPTION"
    with pytest.raises(lab.Stage3ModelLaboratoryError) as custom:
        jobs.plan_model_development_queue(
            database,
            authority.project_id,
            _payload(
                authority,
                {
                    "algorithmId": "multinomial_logistic",
                    "featureUniverseId": "CUSTOM_SUBSET",
                    "orderedFeatures": ["eligible_000", "batting_altitude_change_feet"],
                    "tuningMode": "FIXED",
                },
            ),
        )
    assert custom.value.code == "MODEL_DEVELOPMENT_CUSTOM_FEATURE_INELIGIBLE"
    plan = jobs.plan_model_development_queue(
        database,
        authority.project_id,
        _payload(authority, {"algorithmId": "class_frequency_null", "tuningMode": "FIXED"}),
    )
    jobs._assert_plan_current(authority, full, plan)
    stale = deepcopy(plan)
    stale["authorityKey"] = "superseded"
    with pytest.raises(lab.Stage3ModelLaboratoryError) as stale_error:
        jobs._assert_plan_current(authority, full, stale)
    assert stale_error.value.code == "MODEL_DEVELOPMENT_QUEUED_AUTHORITY_STALE"


def test_cancel_unstarted_is_idempotent_and_preserves_original_timestamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    job_id = "stage3-model-job-test"
    row: dict[str, object] = {
        "run_id": job_id,
        "project_id": lab.EXPECTED_PROJECT_ID,
        "run_type": jobs.MODEL_DEVELOPMENT_JOB_TYPE,
        "workflow_type": "sports_stage3_model_development",
        "status": "RUNNING",
        "started_at": "2026-09-02T08:00:00Z",
        "completed_at": None,
        "parameters_json": jobs.json_dumps({"planId": "plan"}),
        "metrics_json": jobs.json_dumps(
            {"state": "RUNNING", "completedFits": 5, "totalFits": 25}
        ),
        "artifacts_json": jobs.json_dumps({}),
        "error_json": jobs.json_dumps({}),
        "created_by": "scientist",
    }

    class Repository:
        def get(self, requested: str) -> dict[str, object] | None:
            return row if requested == job_id else None

        def upsert(self, value: dict[str, object]) -> dict[str, object]:
            row.update(value)
            for key in ("parameters_json", "metrics_json", "artifacts_json", "error_json"):
                if isinstance(row.get(key), dict):
                    row[key] = jobs.json_dumps(row[key])
            return row

    repository = Repository()
    monkeypatch.setattr(jobs, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(jobs, "_runtime_root", lambda: tmp_path)
    first = jobs.cancel_unstarted_model_development_work(
        object(), lab.EXPECTED_PROJECT_ID, job_id, actor_user_id="scientist"
    )
    requested_at = first["job"]["progress"]["cancelRequestedAt"]
    second = jobs.cancel_unstarted_model_development_work(
        object(), lab.EXPECTED_PROJECT_ID, job_id, actor_user_id="scientist"
    )
    assert second["job"]["idempotentReplay"] is True
    assert second["job"]["progress"]["cancelRequestedAt"] == requested_at
    assert second["job"]["progress"]["cancelUnstartedRequested"] is True


class _MemoryRunRepository:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.history: list[dict[str, object]] = []

    def get(self, requested: str) -> dict[str, object] | None:
        return self.row if requested == self.row["run_id"] else None

    def list_for_project(self, project_id: str) -> list[dict[str, object]]:
        return [self.row] if project_id == self.row["project_id"] else []

    def upsert(self, value: dict[str, object]) -> dict[str, object]:
        self.row.update(value)
        for key in ("parameters_json", "metrics_json", "artifacts_json", "error_json"):
            if isinstance(self.row.get(key), dict):
                self.row[key] = jobs.json_dumps(self.row[key])
        self.history.append(deepcopy(self.row))
        return dict(self.row)


def _job_row(
    job_id: str,
    *,
    status: str = "RUNNING",
    total_fits: int = 10,
) -> dict[str, object]:
    return {
        "run_id": job_id,
        "project_id": lab.EXPECTED_PROJECT_ID,
        "run_type": jobs.MODEL_DEVELOPMENT_JOB_TYPE,
        "workflow_type": "sports_stage3_model_development",
        "status": status,
        "started_at": "2026-09-02T08:00:00Z",
        "completed_at": None,
        "parameters_json": jobs.json_dumps({"planId": "plan"}),
        "metrics_json": jobs.json_dumps(
            {
                "state": status,
                "completedFits": 0,
                "failedFits": 0,
                "totalFits": total_fits,
                "completedCandidateReceipts": [],
            }
        ),
        "artifacts_json": jobs.json_dumps(
            {"coordinatorProcessId": os.getpid(), "completedCandidateReceipts": []}
        ),
        "error_json": jobs.json_dumps({}),
        "created_by": "scientist",
    }


def test_orphaned_job_fails_closed_and_preserves_completed_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    row = _job_row("stage3-model-job-orphan", total_fits=20)
    row["metrics_json"] = jobs.json_dumps(
        {
            "state": "RUNNING",
            "completedFits": 5,
            "failedFits": 0,
            "totalFits": 20,
            "pendingFits": 10,
            "activeCandidates": [{"taskId": "active:1", "fold": 2}],
            "completedCandidateReceipts": [{"candidateReceiptSha256": "a" * 64}],
        }
    )
    row["artifacts_json"] = jobs.json_dumps(
        {
            "coordinatorProcessId": 987654,
            "completedCandidateReceipts": [{"candidateReceiptSha256": "a" * 64}],
        }
    )
    repository = _MemoryRunRepository(row)
    monkeypatch.setattr(jobs, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(jobs, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(jobs, "_process_is_alive", lambda _pid: False)

    reconciled = jobs._reconcile_orphaned_job(object(), row)
    progress = jobs.json_loads(reconciled["metrics_json"], {})
    artifacts = jobs.json_loads(reconciled["artifacts_json"], {})
    error = jobs.json_loads(reconciled["error_json"], {})
    assert reconciled["status"] == "INTERRUPTED"
    assert progress["state"] == "INTERRUPTED"
    assert progress["unstartedFits"] == 10
    assert progress["unresolvedFits"] == 5
    assert progress["pendingFits"] == 0
    assert progress["cancellationPendingFits"] == 0
    assert progress["drainingActiveCandidates"] == 0
    assert progress["interruptedCandidates"] == [{"taskId": "active:1", "fold": 2}]
    assert progress["activeCandidates"] == []
    assert progress["completedCandidateReceipts"] == [
        {"candidateReceiptSha256": "a" * 64}
    ]
    assert artifacts["interruptedCoordinatorProcessId"] == 987654
    assert error["code"] == "MODEL_DEVELOPMENT_COORDINATOR_INTERRUPTED"


def test_failure_terminal_write_wins_cancel_race_and_preserves_audit_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    row = _job_row(
        "stage3-model-job-failure", status="CANCEL_REQUESTED", total_fits=25
    )
    row["metrics_json"] = jobs.json_dumps(
        {
            "state": "CANCEL_REQUESTED",
            "completedFits": 5,
            "failedFits": 0,
            "totalFits": 25,
            "cancelUnstartedRequested": True,
            "cancelRequestedAt": "2026-09-02T09:00:00Z",
        }
    )
    repository = _MemoryRunRepository(row)
    monkeypatch.setattr(jobs, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(jobs, "_runtime_root", lambda: tmp_path)

    jobs._finish_failed_job(
        object(),
        str(row["run_id"]),
        lab.EXPECTED_PROJECT_ID,
        "scientist",
        {"totalFits": 25},
        "TEST_FAILURE",
        "bounded failure",
    )
    progress = jobs.json_loads(row["metrics_json"], {})
    assert row["status"] == "FAILED"
    assert progress["state"] == "FAILED"
    assert progress["cancelUnstartedRequested"] is True
    assert progress["cancelRequestedAt"] == "2026-09-02T09:00:00Z"
    assert progress["unstartedFits"] == 20
    assert progress["activeCandidates"] == []
    assert progress["pendingFits"] == 0
    assert progress["cancellationPendingFits"] == 0
    assert progress["drainingActiveCandidates"] == 0


def test_coordinator_identity_rejects_pid_reuse_and_bounds_registration_grace() -> None:
    job_id = "stage3-model-job-coordinator-identity"
    with jobs._COORDINATOR_GUARD:
        jobs._COORDINATOR_FUTURES.pop(job_id, None)
    assert (
        jobs._coordinator_is_alive(
            job_id,
            os.getpid(),
            "different-backend-instance",
            jobs.now_iso(),
        )
        is False
    )
    assert (
        jobs._coordinator_is_alive(
            job_id,
            os.getpid(),
            jobs._COORDINATOR_INSTANCE_ID,
            jobs.now_iso(),
        )
        is True
    )
    assert (
        jobs._coordinator_is_alive(
            job_id,
            os.getpid(),
            jobs._COORDINATOR_INSTANCE_ID,
            "2000-01-01T00:00:00+00:00",
        )
        is False
    )


def test_queued_coordinator_cancellation_terminalizes_without_model_activity(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    job_id = "stage3-model-job-cancelled-before-start"
    row = _job_row(job_id, status="CANCEL_REQUESTED", total_fits=15)
    repository = _MemoryRunRepository(row)
    monkeypatch.setattr(jobs, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(jobs, "_runtime_root", lambda: tmp_path)
    plan = {"totalFits": 15, "totalConfigurations": 3}
    jobs._finish_cancelled_before_start(
        object(), job_id, lab.EXPECTED_PROJECT_ID, "scientist", plan
    )
    progress = jobs.json_loads(row["metrics_json"], {})
    assert row["status"] == "CANCELLED"
    assert progress["completedFits"] == 0
    assert progress["cancelledFits"] == 15
    assert progress["cancelledConfigurations"] == 3
    assert progress["activeCandidates"] == []
    assert "no model fit began" in progress["message"]


def test_execute_job_heartbeats_and_isolates_one_candidate_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    job_id = "stage3-model-job-execute"
    row = _job_row(job_id)
    repository = _MemoryRunRepository(row)
    authority = _authority()
    authority.eda_authority.registration_id = "registration"
    authority.eda_authority.dataset_version_id = "dataset-version"
    monkeypatch.setattr(jobs, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(jobs, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(
        jobs, "resolve_model_lab_authority", lambda _database, _project: authority
    )
    monkeypatch.setattr(
        jobs,
        "build_model_eligibility",
        lambda _resolved: {"featureSetId": "FULL", "checksum": "f" * 64},
    )
    monkeypatch.setattr(jobs, "_assert_plan_current", lambda *_args: None)
    monkeypatch.setattr(jobs, "_fold_frame", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        jobs,
        "_persist_run",
        lambda _receipt: {"runId": "run", "runReceiptSha256": "r" * 64},
    )

    def evaluate(
        _frame,
        *,
        model_family,
        feature_set,
        hyperparameters,
        progress_callback,
        **_kwargs,
    ):
        if model_family == "broken_family":
            time.sleep(0.02)
            raise lab.Stage3ModelLaboratoryError(
                "BOUNDED_CANDIDATE_FAILURE", "one candidate failed"
            )
        # The timeout-based coordinator heartbeat must run while this candidate
        # remains inside a fold with no milestone callback.
        time.sleep(2.1)
        for fold in range(1, 6):
            progress_callback({"event": "FOLD_COMPLETED", "fold": fold})
        return {
            "candidateId": "candidate-ok",
            "modelFamily": model_family,
            "hyperparameters": dict(hyperparameters),
            "featureSetId": feature_set["featureSetId"],
            "featureSetName": feature_set["name"],
            "featureSetChecksum": feature_set["checksum"],
            "featureCount": 1,
            "status": "COMPLETE",
            "foldsCompleted": 5,
            "meanOofLogLoss": 1.4,
            "summedBrier": 0.7,
            "ece": 0.01,
            "accuracyDiagnostic": 0.5,
            "macroF1Diagnostic": 0.1,
            "folds": [],
            "runtimeMs": 2100,
        }

    monkeypatch.setattr(jobs, "_evaluate_candidate", evaluate)

    actual_upsert = jobs._upsert_job
    terminal_attempts = 0

    def transient_terminal_failure(database, value):
        nonlocal terminal_attempts
        if value.get("status") == "PARTIAL":
            terminal_attempts += 1
            if terminal_attempts == 1:
                raise RuntimeError("transient terminal row write")
        return actual_upsert(database, value)

    monkeypatch.setattr(jobs, "_upsert_job", transient_terminal_failure)

    def experiment(identifier: str) -> dict[str, object]:
        feature_set = {
            "featureSetId": f"feature-{identifier}",
            "name": f"Feature {identifier}",
            "checksum": identifier[0] * 64,
            "orderedFeatures": ["eligible_000"],
        }
        return {
            "experimentId": f"experiment-{identifier}",
            "candidateSpecificationTemplateSha256": identifier[0] * 64,
            "algorithmId": identifier,
            "algorithmLabel": identifier,
            "featureUniverseId": feature_set["featureSetId"],
            "featureUniverseName": feature_set["name"],
            "featureUniverseChecksum": feature_set["checksum"],
            "featureCount": 1,
            "featureSetContract": feature_set,
            "seed": 7,
            "executionResources": {
                "exclusiveCandidate": False,
                "nativeWorkers": 1,
            },
            "tuning": {
                "tuningMode": "FIXED",
                "gridPreset": "FIXED",
                "configurationCount": 1,
                "fitsPerConfiguration": 5,
                "configurations": [{"value": 1}],
            },
        }

    plan = {
        "planId": "plan",
        "checksum": "p" * 64,
        "totalFits": 10,
        "parallelism": {"effectiveCandidateWorkers": 2},
        "experiments": [experiment("good_family"), experiment("broken_family")],
    }
    jobs._execute_job(
        str(tmp_path / "ignored.db"),
        job_id,
        lab.EXPECTED_PROJECT_ID,
        "scientist",
        plan,
    )

    progress = jobs.json_loads(row["metrics_json"], {})
    assert row["status"] == "PARTIAL"
    assert progress["completedConfigurations"] == 1
    assert progress["failedConfigurations"] == 1
    assert progress["completedFits"] == 5
    assert progress["failedFits"] == 5
    assert terminal_attempts == 2
    assert len(progress["completedCandidateReceipts"]) == 2
    assert any(
        jobs.json_loads(item["metrics_json"], {}).get("activeCandidates")
        and float(
            jobs.json_loads(item["metrics_json"], {})["activeCandidates"][0][
                "elapsedSeconds"
            ]
        )
        >= 1.5
        for item in repository.history
    )
    failed_receipt = next(
        receipt
        for receipt in progress["completedCandidateReceipts"]
        if receipt["status"] == "FAILED"
    )
    failed_payload = jobs.json_loads(
        (
            tmp_path
            / "candidate-attempts"
            / "objects"
            / "sha256"
            / f"{failed_receipt['candidateReceiptSha256']}.json"
        ).read_text(encoding="utf-8"),
        {},
    )
    assert failed_payload["candidate"]["runtimeMs"] > 0
    assert failed_payload["candidate"]["errorCode"] == "BOUNDED_CANDIDATE_FAILURE"
