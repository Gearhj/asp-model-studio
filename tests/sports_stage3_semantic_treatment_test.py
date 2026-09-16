"""Synthetic-only checks of successor semantic treatment and artifact reload."""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast import stage3_interaction_recomputation_authority as interactions
from server.sports_current_statcast import stage3_semantic_treatment as semantic


def _manifest():
    return interactions.project_authority_manifest(
        {"projectId": "asp-mtlozhdx", "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
         "goldManifestSha": "6" * 64, "contextualDatasetId": "gold-table:synthetic-contextual",
         "contextualManifestSha": "4" * 64, "reviewDigest": "3" * 64},
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1", treatment_specification_sha256="2" * 64,
        feature_inventory_sha256="1" * 64, compiler_version="MLB_FEATURE_TREATMENT_COMPILER_V1",
        compiler_sha256="5" * 64, contextual_formula_source_sha256="7" * 64)


def _frame(features):
    columns = semantic.required_input_columns(features)
    frame = pd.DataFrame({name: np.zeros(3) for name in columns if name != "game_date"})
    frame["game_date"] = ["2024-04-01", "2024-04-02", "2024-04-03"]
    for name in semantic.RULES:
        if name in frame:
            domain = semantic.RULES[name]["domain"]
            frame[name] = np.log1p(10) if domain == "LOG1P_INTEGER" else 2.0 if domain in {"NONNEGATIVE", "POSITIVE_INTEGER", "NONNEGATIVE_INTEGER", "HOUR"} else 0.0
    for side in ("fielding", "batting"):
        for suffix in ("road_trip_game_number",):
            if f"{side}_{suffix}" in frame: frame[f"{side}_{suffix}"] = [2, 3, 4]
    return frame


def _fit(frame, features, family="histogram_gradient_boosting"):
    return semantic.fit_semantic_treatment(frame, features=features, model_family=family,
        fold={"foldNumber": 1, "trainEnd": "2024-04-03"}, interaction_authority_manifest=_manifest(), seed=71)


@pytest.mark.parametrize("feature,indicator", [("batter_log1p_pa", "batter_prior_missing"), ("pitcher_log1p_bfp", "pitcher_prior_missing")])
def test_verified_no_history_exposure_zero_without_median(feature, indicator):
    frame = _frame([feature])
    frame.loc[0, feature] = np.nan
    frame.loc[0, indicator] = 1
    fitted = _fit(frame, [feature])
    actual, evidence = semantic.transform_semantic_treatment(frame, fitted)
    assert actual.loc[0, feature] == 0.0
    assert actual.loc[1, feature] == frame.loc[1, feature]
    assert evidence["features"][feature]["semanticZeroRows"] == 1
    assert fitted["contextualMedians"] == {}
    frame.loc[0, indicator] = 0
    with pytest.raises(semantic.SemanticTreatmentError, match="unavailable or invalid"):
        semantic.transform_semantic_treatment(frame, fitted)


def test_exposure_indicator_contradiction_is_not_zeroed():
    frame = _frame(["batter_log1p_pa"])
    frame.loc[0, "batter_prior_missing"] = 1
    with pytest.raises(semantic.SemanticTreatmentError) as error:
        _fit(frame, ["batter_log1p_pa"])
    assert error.value.evidence["invalidRows"] == 1


@pytest.mark.parametrize("family,expected", [("histogram_gradient_boosting", None), ("LINEAR", 60.0)])
def test_context_native_missing_or_training_only_contextual_median(family, expected):
    feature = "fielding_travel_distance_miles"
    frame = _frame([feature])
    frame[feature] = [np.nan, 20.0, 100.0]
    frame.loc[0, "fielding_previous_game_missing"] = 1
    frame.loc[0, "fielding_travel_path_missing"] = 1
    fitted = _fit(frame, [feature], family)
    validation = frame.copy()
    validation["game_date"] = "2025-05-01"
    validation.loc[1:, feature] = [8000.0, 12000.0]
    actual, evidence = semantic.transform_semantic_treatment(validation, fitted)
    assert np.isnan(actual.loc[0, feature]) if expected is None else actual.loc[0, feature] == expected
    assert evidence["parametersRefit"] is False
    if expected is not None: assert fitted["contextualMedians"][feature]["fitRows"] == 2


def test_source_flag_overrides_no_history_authorization():
    feature = "fielding_travel_distance_miles"
    frame = _frame([feature])
    frame.loc[0, feature] = np.nan
    frame.loc[0, "fielding_previous_game_missing"] = 1
    frame.loc[0, "fielding_current_venue_coordinates_missing"] = 1
    with pytest.raises(semantic.SemanticTreatmentError) as error:
        _fit(frame, [feature])
    assert error.value.evidence["sourceUnavailableRows"] == 1


@pytest.mark.parametrize("suffix", ["previous_game_extra_innings", "cross_country_travel", "crossed_time_zone", "crossed_two_or_more_time_zones"])
def test_each_structural_rule_requires_reason_and_valid_boolean(suffix):
    feature = f"batting_{suffix}"
    frame = _frame([feature])
    frame.loc[0, feature] = np.nan
    frame.loc[0, "batting_previous_game_missing"] = 1
    actual, evidence = semantic.transform_semantic_treatment(frame, _fit(frame, [feature]))
    assert actual.loc[0, feature] == 0
    assert evidence["features"][feature]["semanticZeroRows"] == 1
    frame.loc[0, feature] = 1
    with pytest.raises(semantic.SemanticTreatmentError): _fit(frame, [feature])


@pytest.mark.parametrize("feature,value", [("series_game_number", np.nan), ("local_start_hour", 24), ("fielding_travel_distance_last_3_days", -1), ("local_start_hour_cos", 1.5)])
def test_currently_complete_future_missing_and_invalid_values_rejected(feature, value):
    frame = _frame([feature])
    fitted = _fit(frame, [feature])
    frame.loc[0, feature] = value
    with pytest.raises(semantic.SemanticTreatmentError): semantic.transform_semantic_treatment(frame, fitted)


def test_matchup_boolean_recomputed_without_a_prior():
    feature = "matchup_platoon_advantage"
    frame = _frame([feature])
    frame["matchup_batter_bats_left"] = [1, 0, 0]
    frame["matchup_batter_bats_switch"] = [0, 1, 0]
    frame["matchup_pitcher_throws_left"] = [0, 1, 0]
    actual, evidence = semantic.transform_semantic_treatment(frame, _fit(frame, [feature]))
    assert actual[feature].tolist() == [1, 1, 0]
    assert evidence["features"][feature]["deterministicRecomputedRows"] == 3
    frame.loc[0, "matchup_batter_hand_missing"] = 1
    with pytest.raises(semantic.SemanticTreatmentError): _fit(frame, [feature])


@pytest.mark.parametrize("side", ["batting", "fielding"])
@pytest.mark.parametrize("days", [7, 14])
def test_repeat_opponent_counts_repaired_to_registered_boolean(side, days):
    feature = f"{side}_repeat_opponent_within_{days}_days"
    frame = _frame([feature])
    frame[feature] = [0.0, 1.0, 2.0]
    fitted = _fit(frame, [feature])
    assert fitted["rules"][feature]["kind"] == "REPEAT_OPPONENT_BOOLEAN"
    actual, evidence = semantic.transform_semantic_treatment(frame, json.loads(json.dumps(fitted)))
    assert actual[feature].tolist() == [0.0, 1.0, 1.0]
    assert frame[feature].tolist() == [0.0, 1.0, 2.0]
    assert evidence["features"][feature]["booleanDomainRepairRows"] == 1
    assert evidence["features"][feature]["deterministicRecomputedRows"] == 3
    assert evidence["features"][feature]["nativeMissingRows"] == 0


@pytest.mark.parametrize("value", [-1.0, 1.5, np.nan, np.inf])
def test_repeat_opponent_repair_never_fills_invalid_source(value):
    feature = "batting_repeat_opponent_within_7_days"
    frame = _frame([feature])
    frame[feature] = [0.0, 1.0, 2.0]
    fitted = _fit(frame, [feature])
    frame.loc[1, feature] = value
    with pytest.raises(semantic.SemanticTreatmentError): _fit(frame, [feature])
    with pytest.raises(semantic.SemanticTreatmentError): semantic.transform_semantic_treatment(frame, fitted)


@pytest.mark.parametrize("family", ["histogram_gradient_boosting", "LINEAR"])
def test_eight_existing_interactions_use_transformed_parents_and_reload(family):
    features = list(semantic.TRAVEL_INTERACTIONS)
    frame = _frame(features)
    for side in ("batting", "fielding"):
        frame[f"{side}_travel_distance_miles"] = [np.nan, 1800, 300]
        frame[f"{side}_eastward_time_zone_change_hours"] = [np.nan, 2, 3]
        frame[f"{side}_previous_game_extra_innings"] = [np.nan, 1, 0]
        frame[f"{side}_short_rest_indicator"] = [0, 1, 0]
        frame[f"{side}_early_start_after_eastward_travel"] = [0, 1, 0]
        frame.loc[0, f"{side}_previous_game_missing"] = 1
        frame.loc[0, f"{side}_travel_path_missing"] = 1
    fitted = _fit(frame, features, family)
    original = copy.deepcopy(fitted)
    first, first_evidence = semantic.transform_semantic_treatment(frame, fitted)
    reloaded = json.loads(json.dumps(fitted))
    second, second_evidence = semantic.transform_semantic_treatment(frame, reloaded)
    pd.testing.assert_frame_equal(first, second)
    assert first_evidence == second_evidence
    assert fitted == original
    for feature in features: assert first_evidence["features"][feature]["parentEqualityPassed"]
    assert first.loc[1, "batting_prior_extra_innings_x_travel"] == 1800
    assert np.isnan(first.loc[0, "batting_prior_extra_innings_x_travel"]) if family != "LINEAR" else first.loc[0, "batting_prior_extra_innings_x_travel"] == 0


def test_four_complete_interactions_recomputed_including_side_orientation():
    features = list(semantic.DETERMINISTIC_INTERACTIONS)
    frame = _frame(features)
    frame["context_top_bottom"] = [1, 0, 1]
    frame["is_weekend"] = [1, 1, 0]
    frame["is_friday"] = [0, 0, 1]
    frame["is_night_game"] = [1, 0, 1]
    actual, evidence = semantic.transform_semantic_treatment(frame, _fit(frame, features))
    assert actual["batting_home_x_weekend"].tolist() == [1, 0, 0]
    assert actual["fielding_home_x_weekend"].tolist() == [0, 1, 0]
    assert actual["batting_home_x_friday_night"].tolist() == [0, 0, 1]
    assert evidence["parentOnlyAblationStatus"] == "DEFERRED_BY_APPROVED_BOUNDED_STUDY"


def test_final_oot_and_later_training_rows_rejected_before_feature_access():
    with pytest.raises(semantic.SemanticTreatmentError) as error:
        _fit(pd.DataFrame({"game_date": ["2026-08-14"]}), ["batter_log1p_pa"])
    assert error.value.code == "SEMANTIC_DATE_OUTSIDE_DEVELOPMENT"
    with pytest.raises(semantic.SemanticTreatmentError) as error:
        _fit(pd.DataFrame({"game_date": ["2024-04-04"]}), ["batter_log1p_pa"])
    assert error.value.code == "SEMANTIC_TRAINING_FRAME_CROSSES_FOLD"


def test_fitted_parameter_tampering_rejected_and_targets_do_not_affect_fit():
    feature = "batting_days_since_previous_game"
    frame = _frame([feature])
    frame["outcome"] = ["A", "B", "C"]
    fitted = _fit(frame, [feature], "LINEAR")
    frame["outcome"] = ["X", "Y", "Z"]
    assert _fit(frame, [feature], "LINEAR")["fittedChecksum"] == fitted["fittedChecksum"]
    fitted["contextualMedians"][feature]["value"] = 999
    with pytest.raises(semantic.SemanticTreatmentError) as error:
        semantic.transform_semantic_treatment(frame, fitted)
    assert error.value.code == "SEMANTIC_FITTED_CHECKSUM_MISMATCH"


def test_complete_registered_nonprior_repair_inventory_runs_with_cold_state():
    features = [*semantic.RULES, *semantic.TRAVEL_INTERACTIONS, *semantic.DETERMINISTIC_INTERACTIONS]
    assert len(features) == 64
    assert sum(rule["kind"] == "NO_PRIOR_CONTEXT" for rule in semantic.RULES.values()) == 22
    assert sum(rule["kind"] == "STRUCTURAL_ZERO" for rule in semantic.RULES.values()) == 8
    assert sum(rule["kind"] == "REQUIRED_COMPLETE" for rule in semantic.RULES.values()) == 15
    assert sum(rule["kind"] == "REPEAT_OPPONENT_BOOLEAN" for rule in semantic.RULES.values()) == 4
    frame = _frame(features)
    for name, rule in semantic.RULES.items():
        if rule["noHistoryIndicator"]:
            frame.loc[0, rule["noHistoryIndicator"]] = 1
            frame.loc[0, name] = np.nan
    fitted = _fit(frame, features)
    actual, evidence = semantic.transform_semantic_treatment(frame, fitted)
    for name, rule in semantic.RULES.items():
        if rule["kind"] == "NO_PRIOR_CONTEXT": assert np.isnan(actual.loc[0, name])
        if rule["kind"] in {"COLD_EXPOSURE", "STRUCTURAL_ZERO"}: assert actual.loc[0, name] == 0
    assert len(evidence["features"]) == 64
    assert fitted["finalOotRowsRead"] == 0


def test_explicit_source_reason_does_not_collapse_into_native_missing():
    feature = "batting_days_since_previous_game"
    frame = _frame([feature])
    frame.loc[0, "batting_previous_game_missing"] = 1
    frame.loc[0, feature] = np.nan
    frame[f"{feature}__missing_reason"] = ["SOURCE_UNAVAILABLE", "", ""]
    with pytest.raises(semantic.SemanticTreatmentError) as error:
        _fit(frame, [feature])
    assert error.value.evidence["sourceUnavailableRows"] == 1


def _model_contract(step_map):
    return {"orderedFeatures": list(step_map), "transformationContracts": {"ordered": [
        {"feature": name, "steps": list(steps)} for name, steps in step_map.items()]}}


def test_model_matrix_guard_checks_validation_only_binary_and_arbitrary_null():
    travel = "batting_travel_distance_miles"
    frame = _frame([travel])
    frame["matchup_pitcher_hand_missing"] = 0.0
    frame["month_sin"] = 0.5
    frame.loc[0, travel] = np.nan
    frame.loc[0, "batting_previous_game_missing"] = 1
    fitted = _fit(frame, [travel])
    treated, _ = semantic.transform_semantic_treatment(frame, fitted)
    contract = _model_contract({travel: ("SEMANTIC_NUMERIC_PASSTHROUGH",),
        "matchup_pitcher_hand_missing": ("SEMANTIC_BOOLEAN_PASSTHROUGH",), "month_sin": ("SEMANTIC_NUMERIC_PASSTHROUGH",)})
    result = semantic.validate_model_frame(treated, feature_set=contract, semantic_fitted=fitted, prior_fitted={})
    assert result["features"][travel]["nativeMissingRows"] == 1
    validation = treated.copy()
    validation.loc[1, "matchup_pitcher_hand_missing"] = 2
    with pytest.raises(semantic.SemanticTreatmentError) as error:
        semantic.validate_model_frame(validation, feature_set=contract, semantic_fitted=fitted, prior_fitted={})
    assert error.value.code == "SEMANTIC_INDICATOR_INVALID"
    for invalid in (np.nan, np.inf, -np.inf):
        validation = treated.copy()
        validation.loc[1, "month_sin"] = invalid
        with pytest.raises(semantic.SemanticTreatmentError) as error:
            semantic.validate_model_frame(validation, feature_set=contract, semantic_fitted=fitted, prior_fitted={})
        assert error.value.code == "SEMANTIC_MODEL_NUMERIC_STATE_INVALID"
    validation = treated.copy()
    validation.loc[0, "batting_previous_game_missing"] = 0
    with pytest.raises(semantic.SemanticTreatmentError):
        semantic.validate_model_frame(validation, feature_set=contract, semantic_fitted=fitted, prior_fitted={})


def test_model_matrix_guard_requires_exact_registered_v1_cold_state():
    feature, state, posterior = "batter_so_per_pa", "registered_history_state", "registered_posterior_mean"
    frame = _frame([])
    frame[feature] = [np.nan, 0.2, 0.3]
    frame[state] = ["TRUE_COLD_START", "SPARSE_HISTORY", "ESTABLISHED_HISTORY"]
    frame[posterior] = [0.1, 0.2, 0.3]
    fitted = _fit(frame, [feature])
    contract = _model_contract({feature: ("SEMANTIC_NUMERIC_PASSTHROUGH",), state: ("CATEGORICAL_UNKNOWN", "ONE_HOT"), posterior: ("SEMANTIC_NUMERIC_PASSTHROUGH",)})
    prior = {"outputSchema": {"wave1Features": [feature], "bindings": {feature: {"derivedOutputs": {"historyState": state}}},
        "additions": [{"name": state, "role": "historyState", "domain": ["TRUE_COLD_START", "SPARSE_HISTORY", "ESTABLISHED_HISTORY"]}]}}
    assert semantic.validate_model_frame(frame, feature_set=contract, semantic_fitted=fitted, prior_fitted=prior)["status"] == "PASS"
    frame.loc[0, state] = "SOURCE_UNAVAILABLE"
    with pytest.raises(semantic.SemanticTreatmentError):
        semantic.validate_model_frame(frame, feature_set=contract, semantic_fitted=fitted, prior_fitted=prior)
    frame.loc[0, state] = "TRUE_COLD_START"
    frame.loc[0, posterior] = np.nan
    with pytest.raises(semantic.SemanticTreatmentError):
        semantic.validate_model_frame(frame, feature_set=contract, semantic_fitted=fitted, prior_fitted=prior)


def test_unwrapped_source_timezone_shift_is_distinct_from_circular_body_clock():
    features = ["batting_time_zone_change_hours", "batting_westward_time_zone_change_hours", "batting_circadian_timezone_component"]
    frame = _frame(features)
    frame[features[0]] = [-16.0, 16.0, 0.0]
    frame[features[1]] = [16.0, 0.0, 0.0]
    frame[features[2]] = [16.0, 16.0, 0.0]
    treated, _ = semantic.transform_semantic_treatment(frame, _fit(frame, features))
    for feature in features: np.testing.assert_array_equal(treated[feature], frame[feature])
    body = _frame(["batting_local_body_clock_offset_hours"])
    body.loc[0, "batting_local_body_clock_offset_hours"] = 16
    with pytest.raises(semantic.SemanticTreatmentError):
        _fit(body, ["batting_local_body_clock_offset_hours"])
