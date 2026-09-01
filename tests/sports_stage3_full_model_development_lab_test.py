from __future__ import annotations

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
