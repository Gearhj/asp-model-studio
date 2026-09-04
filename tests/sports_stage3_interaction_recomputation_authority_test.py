from __future__ import annotations

import copy
import hashlib

import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast import (
    stage3_interaction_recomputation_authority as interactions,
)
from server.sports_datasets.consumer import canonical_json_bytes


EXPECTED_INTERACTIONS = (
    "fielding_road_trip_length_x_travel",
    "fielding_prior_extra_innings_x_travel",
    "fielding_long_travel_x_short_rest",
    "fielding_eastward_travel_x_early_start",
    "batting_road_trip_length_x_travel",
    "batting_prior_extra_innings_x_travel",
    "batting_long_travel_x_short_rest",
    "batting_eastward_travel_x_early_start",
)

EXPECTED_FORMULAS = {
    "fielding_road_trip_length_x_travel": (
        "fielding_road_trip_game_number * fielding_travel_distance_miles"
    ),
    "fielding_prior_extra_innings_x_travel": (
        "fielding_previous_game_extra_innings * fielding_travel_distance_miles"
    ),
    "fielding_long_travel_x_short_rest": (
        "int(fielding_travel_distance_miles >= 1500) * "
        "fielding_short_rest_indicator"
    ),
    "fielding_eastward_travel_x_early_start": (
        "fielding_eastward_time_zone_change_hours * "
        "fielding_early_start_after_eastward_travel"
    ),
    "batting_road_trip_length_x_travel": (
        "batting_road_trip_game_number * batting_travel_distance_miles"
    ),
    "batting_prior_extra_innings_x_travel": (
        "batting_previous_game_extra_innings * batting_travel_distance_miles"
    ),
    "batting_long_travel_x_short_rest": (
        "int(batting_travel_distance_miles >= 1500) * "
        "batting_short_rest_indicator"
    ),
    "batting_eastward_travel_x_early_start": (
        "batting_eastward_time_zone_change_hours * "
        "batting_early_start_after_eastward_travel"
    ),
}


def _manifest() -> dict[str, object]:
    return interactions.project_authority_manifest(
        {
            "projectId": "asp-mtlozhdx",
            "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
            "goldManifestSha": "6" * 64,
            "contextualDatasetId": "gold-table:synthetic-contextual",
            "contextualManifestSha": "4" * 64,
            "reviewDigest": "3" * 64,
        },
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_specification_sha256="2" * 64,
        feature_inventory_sha256="1" * 64,
        compiler_version="MLB_FEATURE_TREATMENT_COMPILER_V1",
        compiler_sha256="5" * 64,
        contextual_formula_source_sha256="7" * 64,
    )


def _resign_manifest(manifest: dict[str, object]) -> None:
    content = {
        key: value
        for key, value in manifest.items()
        if key not in {"authorityChecksum", "authorityId"}
    }
    checksum = hashlib.sha256(canonical_json_bytes(content)).hexdigest()
    manifest["authorityChecksum"] = checksum
    manifest["authorityId"] = f"{interactions.AUTHORITY_NAME}:sha256:{checksum}"


def _frame() -> pd.DataFrame:
    rows = 4
    frame = pd.DataFrame(
        {
            "game_date": ["2024-04-01", "2024-04-02", "2025-05-01", "2024-04-03"],
            # Forbidden distractors must never affect fit or transform.
            "outcome": ["out", "single", "home_run", "walk"],
            "target": [0, 1, 1, 0],
        }
    )
    for side, multiplier in (("fielding", 1.0), ("batting", 2.0)):
        frame[f"{side}_road_trip_game_number"] = [2, 3, 4, 0]
        frame[f"{side}_travel_distance_miles"] = np.array(
            [1000.0, 1600.0, 2000.0, np.nan]
        ) * multiplier
        frame[f"{side}_previous_game_extra_innings"] = [1.0, 0.0, 1.0, np.nan]
        frame[f"{side}_short_rest_indicator"] = [1, 1, 0, 0]
        frame[f"{side}_eastward_time_zone_change_hours"] = [2.0, 3.0, 4.0, np.nan]
        frame[f"{side}_early_start_after_eastward_travel"] = [1, 0, 1, 0]
        frame[f"{side}_previous_game_missing"] = [0, 0, 0, 1]
        frame[f"{side}_travel_path_missing"] = [0, 0, 0, 1]
        frame[f"{side}_current_venue_coordinates_missing"] = [0, 0, 0, 0]
        frame[f"{side}_previous_venue_coordinates_missing"] = [0, 0, 0, 1]
        frame[f"{side}_previous_game_innings_missing"] = [0, 0, 0, 1]
        frame[f"{side}_current_start_missing"] = [0] * rows
        frame[f"{side}_current_venue_timezone_missing"] = [0, 0, 0, 0]
        frame[f"{side}_previous_venue_timezone_missing"] = [0, 0, 0, 1]
    return frame


def _fit(
    frame: pd.DataFrame | None = None,
    *,
    family: str = "LINEAR",
    scale: bool = False,
) -> dict[str, object]:
    return interactions.fit_interaction_authority(
        _frame() if frame is None else frame,
        training_end="2024-12-31",
        authority_manifest=_manifest(),
        fold_id="fold-1",
        model_family=family,
        scale_interactions=scale,
    )


def _stable_fit(fitted: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in fitted.items() if key != "fitDurationMs"}


def test_registry_is_exact_explicit_and_never_selected_by_name_pattern() -> None:
    assert interactions.INTERACTION_FEATURES == EXPECTED_INTERACTIONS
    assert interactions.feature_binding("invented_x_feature") is None
    with pytest.raises(interactions.InteractionAuthorityError) as error:
        interactions.required_input_columns(["invented_x_feature"])
    assert error.value.code == "INTERACTION_FEATURE_NOT_REGISTERED"

    for feature in EXPECTED_INTERACTIONS:
        binding = interactions.feature_binding(feature)
        assert binding is not None
        assert binding["backendFeatureIdentity"] == feature
        assert binding["formula"] == EXPECTED_FORMULAS[feature]
        assert len(binding["orderedParents"]) == 2
        assert binding["orderedParents"] == [
            parent["backendFeatureIdentity"] for parent in binding["parents"]
        ]
        assert all(parent["pointInTimeStatus"] == "PASS" for parent in binding["parents"])
        assert binding["operationOrder"] == list(interactions.OPERATION_ORDER)
        assert binding["independentImputation"] == "PROHIBITED"
        assert binding["independentCapping"] == "PROHIBITED"
        assert binding["executableStatus"] == "READY_GOVERNED_INTERACTION_V1"
        assert binding["blockedReason"] is None


def test_project_manifest_is_deterministic_and_binds_every_authority_layer() -> None:
    first = _manifest()
    second = _manifest()
    assert first == second
    assert first["authorityId"].endswith(first["authorityChecksum"])
    assert first["projectId"] == "asp-mtlozhdx"
    assert first["goldDatasetId"] == "gold-table:gold_mlb_current_pa_v1"
    assert first["goldManifestSha"] == "6" * 64
    assert first["contextualManifestSha"] == "4" * 64
    assert first["featureInventorySha256"] == "1" * 64
    assert first["treatmentSpecificationSource"]["sourceContentSha256"] == "2" * 64
    assert first["compiler"]["sha256"] == "5" * 64
    assert first["contextualFormulaSource"]["sha256"] == "7" * 64
    assert first["development"] == {
        "rows": 683_662,
        "start": "2023-03-30",
        "end": "2026-08-13",
    }
    assert first["finalOot"] == {
        "rows": 14_067,
        "start": "2026-08-14",
        "end": "2026-08-27",
        "status": "LOCKED_UNOPENED",
        "accessCount": 0,
    }
    assert all(value == 0 for value in first["modelActivity"].values())


def test_all_eight_literal_formulas_match_independent_fixture_calculations() -> None:
    frame = _frame().iloc[:3].copy()
    fitted = _fit(family="TREE")
    actual = interactions.transform_interactions(frame, fitted)

    for side, multiplier in (("fielding", 1.0), ("batting", 2.0)):
        travel = np.array([1000.0, 1600.0, 2000.0]) * multiplier
        np.testing.assert_allclose(
            actual[f"{side}_road_trip_length_x_travel"],
            np.array([2.0, 3.0, 4.0]) * travel,
        )
        np.testing.assert_allclose(
            actual[f"{side}_prior_extra_innings_x_travel"],
            np.array([1.0, 0.0, 1.0]) * travel,
        )
        np.testing.assert_allclose(
            actual[f"{side}_long_travel_x_short_rest"],
            (travel >= 1500.0).astype(float) * np.array([1.0, 1.0, 0.0]),
        )
        np.testing.assert_allclose(
            actual[f"{side}_eastward_travel_x_early_start"],
            np.array([2.0, 3.0, 4.0]) * np.array([1.0, 0.0, 1.0]),
        )


def test_dense_parent_medians_and_scalers_fit_training_only_after_recomputation() -> None:
    frame = _frame()
    fitted = _fit(frame, family="LINEAR", scale=True)
    assert fitted["parentParameters"]["fielding_travel_distance_miles"]["value"] == 1300.0
    assert fitted["parentParameters"]["batting_travel_distance_miles"]["value"] == 2600.0
    assert fitted["parentParameters"]["fielding_eastward_time_zone_change_hours"]["value"] == 2.5
    assert fitted["rowsAfterTrainingCutoffExcluded"] == 1
    assert fitted["fitEvidence"]["validationFeatureValuesRead"] is False
    assert fitted["fitEvidence"]["targetColumnRead"] is False

    feature = "fielding_road_trip_length_x_travel"
    # Training semantic outputs are 2000, 4800, and governed cold-state 0.
    # Scaling remains downstream of semantic recomputation.
    assert fitted["scalerParameters"][feature]["mean"] == pytest.approx(
        2266.6666666666665
    )
    assert fitted["scalerParameters"][feature]["scale"] == pytest.approx(
        1968.643074697787
    )
    transformed = interactions.transform_interactions(frame, fitted)
    expected_scaled = (
        np.array([2000.0, 4800.0])
        - fitted["scalerParameters"][feature]["mean"]
    ) / fitted["scalerParameters"][feature]["scale"]
    np.testing.assert_allclose(
        transformed.loc[[0, 1], f"{feature}__scaled"], expected_scaled
    )

    changed = frame.copy()
    validation = changed["game_date"] == "2025-05-01"
    for column in interactions.required_input_columns():
        if column != "game_date":
            changed.loc[validation, column] = 999_999
    changed.loc[validation, "outcome"] = "changed"
    changed.loc[validation, "target"] = -999
    repeated = _fit(changed, family="LINEAR", scale=True)
    assert _stable_fit(fitted) == _stable_fit(repeated)
    assert fitted["fittedChecksum"] == repeated["fittedChecksum"]


def test_tree_native_missing_and_authorized_structural_zero_are_distinct() -> None:
    frame = _frame().iloc[[3]].copy()
    fitted = _fit(family="TREE")
    transformed = interactions.transform_interactions(frame, fitted)
    road = "fielding_road_trip_length_x_travel"
    prior = "fielding_prior_extra_innings_x_travel"
    long_rest = "fielding_long_travel_x_short_rest"
    east = "fielding_eastward_travel_x_early_start"
    assert np.isnan(transformed.iloc[0][road])
    assert transformed.iloc[0][f"{road}__state"] == "TRUE_NO_HISTORY_NATIVE_MISSING"
    # Tree-native missing parents remain missing. Zero is produced only when
    # every multiplicand required by the registered formula is known.
    assert np.isnan(transformed.iloc[0][prior])
    assert np.isnan(transformed.iloc[0][long_rest])
    assert np.isnan(transformed.iloc[0][east])
    assert transformed.iloc[0][f"{prior}__state"] == "TRUE_NO_HISTORY_NATIVE_MISSING"


def test_no_history_authority_overrides_prefilled_parents_and_rejects_boolean_conflicts() -> None:
    cold = _frame().iloc[[3]].copy()
    cold["fielding_road_trip_game_number"] = 2
    cold["fielding_travel_distance_miles"] = 9_999.0
    cold["fielding_eastward_time_zone_change_hours"] = 11.0
    cold["fielding_previous_game_extra_innings"] = 0.0

    tree = interactions.transform_interactions(cold, _fit(family="TREE"))
    road = "fielding_road_trip_length_x_travel"
    east = "fielding_eastward_travel_x_early_start"
    assert np.isnan(tree.iloc[0][road])
    assert np.isnan(tree.iloc[0][east])
    assert tree.iloc[0][f"{road}__state"] == "TRUE_NO_HISTORY_NATIVE_MISSING"
    assert tree.iloc[0][f"{east}__state"] == "TRUE_NO_HISTORY_NATIVE_MISSING"

    linear_fit = _fit(family="LINEAR")
    dense = interactions.transform_interactions(cold, linear_fit)
    assert dense.iloc[0][road] == pytest.approx(
        2.0
        * linear_fit["parentParameters"]["fielding_travel_distance_miles"][
            "value"
        ]
    )
    # The raw 9,999-mile and 11-hour payloads are never consumed on a row
    # governed as having no prior game.
    assert dense.iloc[0][road] != 2.0 * 9_999.0
    assert dense.iloc[0][east] == 0.0

    contradictory = cold.copy()
    contradictory["fielding_previous_game_extra_innings"] = 1.0
    conflict = interactions.transform_interaction(
        contradictory,
        linear_fit,
        "fielding_prior_extra_innings_x_travel",
    )
    assert np.isnan(conflict.iloc[0]["fielding_prior_extra_innings_x_travel"])
    assert conflict.iloc[0][
        "fielding_prior_extra_innings_x_travel__state"
    ] == "COMPUTATION_FAILURE"

    for parent, interaction in (
        (
            "fielding_early_start_after_eastward_travel",
            "fielding_eastward_travel_x_early_start",
        ),
        ("fielding_short_rest_indicator", "fielding_long_travel_x_short_rest"),
    ):
        contradictory = cold.copy()
        contradictory[parent] = 1.0
        conflict = interactions.transform_interaction(
            contradictory,
            linear_fit,
            interaction,
        )
        assert np.isnan(conflict.iloc[0][interaction])
        assert conflict.iloc[0][f"{interaction}__state"] == "COMPUTATION_FAILURE"


def test_source_failure_computation_failure_and_unknown_boolean_fail_closed() -> None:
    fitted = _fit(family="LINEAR")
    frame = _frame().iloc[:3].copy()

    source = frame.iloc[[0]].copy()
    source["fielding_travel_path_missing"] = 1
    source_result = interactions.transform_interaction(
        source, fitted, "fielding_long_travel_x_short_rest"
    )
    assert np.isnan(source_result.iloc[0]["fielding_long_travel_x_short_rest"])
    assert source_result.iloc[0]["fielding_long_travel_x_short_rest__state"] == "SOURCE_UNAVAILABLE"

    invalid = frame.iloc[[0]].copy()
    invalid["fielding_travel_distance_miles"] = -1.0
    invalid_result = interactions.transform_interaction(
        invalid, fitted, "fielding_road_trip_length_x_travel"
    )
    assert np.isnan(invalid_result.iloc[0]["fielding_road_trip_length_x_travel"])
    assert invalid_result.iloc[0]["fielding_road_trip_length_x_travel__state"] == "COMPUTATION_FAILURE"

    unknown = frame.iloc[[0]].copy()
    unknown["fielding_short_rest_indicator"] = np.nan
    unknown_result = interactions.transform_interaction(
        unknown, fitted, "fielding_long_travel_x_short_rest"
    )
    assert np.isnan(unknown_result.iloc[0]["fielding_long_travel_x_short_rest"])
    assert unknown_result.iloc[0]["fielding_long_travel_x_short_rest__state"] == "SOURCE_UNAVAILABLE"

    invalid_boolean = frame.iloc[[0]].copy()
    invalid_boolean["fielding_short_rest_indicator"] = 2
    invalid_boolean_result = interactions.transform_interaction(
        invalid_boolean, fitted, "fielding_long_travel_x_short_rest"
    )
    assert np.isnan(
        invalid_boolean_result.iloc[0]["fielding_long_travel_x_short_rest"]
    )
    assert invalid_boolean_result.iloc[0][
        "fielding_long_travel_x_short_rest__state"
    ] == "COMPUTATION_FAILURE"

    invalid_governance_indicator = frame.iloc[[0]].copy()
    invalid_governance_indicator["fielding_travel_path_missing"] = np.nan
    invalid_indicator_result = interactions.transform_interaction(
        invalid_governance_indicator,
        fitted,
        "fielding_long_travel_x_short_rest",
    )
    assert np.isnan(
        invalid_indicator_result.iloc[0]["fielding_long_travel_x_short_rest"]
    )
    assert invalid_indicator_result.iloc[0][
        "fielding_long_travel_x_short_rest__state"
    ] == "COMPUTATION_FAILURE"


def test_explicit_parent_failure_reasons_survive_target_free_slicing() -> None:
    frame = _frame()
    reason = "fielding_travel_distance_miles__missing_reason"
    frame[reason] = ["COMPUTATION_FAILURE", "", "", ""]
    fitted = _fit(frame, family="LINEAR")
    # The finite but explicitly failed first row is excluded from the parent
    # fit, leaving only the second training row as valid evidence.
    assert fitted["parentParameters"]["fielding_travel_distance_miles"]["value"] == 1600.0
    failed = interactions.transform_interaction(
        frame.iloc[[0]], fitted, "fielding_road_trip_length_x_travel"
    )
    assert np.isnan(failed.iloc[0]["fielding_road_trip_length_x_travel"])
    assert failed.iloc[0][
        "fielding_road_trip_length_x_travel__state"
    ] == "COMPUTATION_FAILURE"

    source = frame.iloc[[1]].copy()
    source[reason] = "SOURCE_UNAVAILABLE"
    unavailable = interactions.transform_interaction(
        source, fitted, "fielding_road_trip_length_x_travel"
    )
    assert np.isnan(unavailable.iloc[0]["fielding_road_trip_length_x_travel"])
    assert unavailable.iloc[0][
        "fielding_road_trip_length_x_travel__state"
    ] == "SOURCE_UNAVAILABLE"

    validation_only = _frame()
    validation_only[reason] = ["", "", "COMPUTATION_FAILURE", ""]
    baseline = _fit(_frame(), family="LINEAR")
    repeated = _fit(validation_only, family="LINEAR")
    assert _stable_fit(repeated) == _stable_fit(baseline)


def test_present_malformed_or_infinite_parents_are_computation_failures() -> None:
    fitted = _fit(family="TREE")
    malformed = _frame().iloc[[0]].copy()
    malformed["fielding_short_rest_indicator"] = "garbage"
    malformed_result = interactions.transform_interaction(
        malformed, fitted, "fielding_long_travel_x_short_rest"
    )
    assert np.isnan(malformed_result.iloc[0]["fielding_long_travel_x_short_rest"])
    assert malformed_result.iloc[0][
        "fielding_long_travel_x_short_rest__state"
    ] == "COMPUTATION_FAILURE"

    infinite = _frame().iloc[[0]].copy()
    infinite["fielding_travel_distance_miles"] = np.inf
    infinite_result = interactions.transform_interaction(
        infinite, fitted, "fielding_road_trip_length_x_travel"
    )
    assert np.isnan(infinite_result.iloc[0]["fielding_road_trip_length_x_travel"])
    assert infinite_result.iloc[0][
        "fielding_road_trip_length_x_travel__state"
    ] == "COMPUTATION_FAILURE"


def test_oot_is_rejected_before_parent_columns_and_target_is_never_required() -> None:
    fitted = _fit()
    # No parent columns exist. OOT rejection must still take precedence, proving
    # parent feature values were not requested/read first.
    oot = pd.DataFrame(
        {"game_date": ["2026-08-14"], "outcome": [object()], "target": [object()]}
    )
    with pytest.raises(interactions.InteractionAuthorityError) as transform_error:
        interactions.transform_interactions(oot, fitted)
    assert transform_error.value.code == "INTERACTION_TRANSFORM_CROSSES_FINAL_OOT"
    with pytest.raises(interactions.InteractionAuthorityError) as fit_error:
        interactions.fit_interaction_authority(
            oot,
            training_end="2026-08-13",
            authority_manifest=_manifest(),
            fold_id="forbidden",
            model_family="TREE",
        )
    assert fit_error.value.code == "INTERACTION_FIT_CROSSES_FINAL_OOT"


def test_later_rows_and_current_targets_cannot_change_an_earlier_transform() -> None:
    fitted = _fit(family="LINEAR")
    frame = _frame().iloc[:3].copy()
    earlier = frame.iloc[[0]].copy()
    earlier_result = interactions.transform_interactions(earlier, fitted)

    changed = frame.copy()
    changed.loc[1:, "fielding_travel_distance_miles"] = [10.0, 9999.0]
    changed.loc[1:, "fielding_short_rest_indicator"] = [0, 1]
    changed["outcome"] = ["changed-a", "changed-b", "changed-c"]
    changed["target"] = [100, 200, 300]
    appended_result = interactions.transform_interactions(changed, fitted)
    pd.testing.assert_series_equal(
        earlier_result.iloc[0], appended_result.iloc[0], check_names=False
    )


def test_authority_checksum_is_sensitive_to_each_scientific_identity_dimension() -> None:
    base = interactions.authority_configuration()
    base_checksum = interactions.authority_checksum(configuration=base)
    mutations = []

    formula = copy.deepcopy(base)
    formula["bindings"][0]["formula"] += " + 0"
    mutations.append(formula)

    parent = copy.deepcopy(base)
    parent["bindings"][0]["parents"][0]["backendFeatureIdentity"] = "changed"
    mutations.append(parent)

    order = copy.deepcopy(base)
    order["bindings"][0]["orderedParents"].reverse()
    mutations.append(order)

    treatment = copy.deepcopy(base)
    treatment["bindings"][0]["parents"][0]["parentTreatmentAuthority"] += "::V2"
    mutations.append(treatment)

    propagation = copy.deepcopy(base)
    propagation["bindings"][0]["sourceFailurePropagation"] = "changed"
    mutations.append(propagation)

    execution = copy.deepcopy(base)
    execution["operationOrder"] = list(reversed(execution["operationOrder"]))
    mutations.append(execution)

    family = copy.deepcopy(base)
    family["modelFamilyResolution"]["LINEAR"]["parentMissing"] = "changed"
    mutations.append(family)

    assert all(
        interactions.authority_checksum(configuration=mutation) != base_checksum
        for mutation in mutations
    )
    project_changed = _manifest()
    project_changed["projectId"] = "different-project"
    _resign_manifest(project_changed)
    assert project_changed["authorityChecksum"] != _manifest()["authorityChecksum"]


def test_tampered_manifest_and_fitted_evidence_fail_content_address_checks() -> None:
    tampered_manifest = _manifest()
    tampered_manifest["goldManifestSha"] = "0" * 64
    with pytest.raises(interactions.InteractionAuthorityError) as manifest_error:
        interactions.fit_interaction_authority(
            _frame(),
            training_end="2024-12-31",
            authority_manifest=tampered_manifest,
            fold_id="fold-1",
            model_family="TREE",
        )
    assert manifest_error.value.code == "INTERACTION_AUTHORITY_CHECKSUM_MISMATCH"

    fitted = _fit()
    fitted["parentParameters"]["fielding_travel_distance_miles"]["value"] += 1.0
    with pytest.raises(interactions.InteractionAuthorityError) as fitted_error:
        interactions.transform_interactions(_frame().iloc[:1], fitted)
    assert fitted_error.value.code == "INTERACTION_FITTED_CHECKSUM_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (
            lambda manifest: manifest["compiler"].update({"sha256": ""}),
            "INTERACTION_AUTHORITY_COMPILER_BINDING_INVALID",
        ),
        (
            lambda manifest: manifest["contextualFormulaSource"].update(
                {"version": "UNREGISTERED"}
            ),
            "INTERACTION_AUTHORITY_FORMULA_BINDING_INVALID",
        ),
        (
            lambda manifest: manifest["development"].update({"rows": 1}),
            "INTERACTION_AUTHORITY_DEVELOPMENT_BOUNDARY_INVALID",
        ),
        (
            lambda manifest: manifest["finalOot"].update({"rows": 1}),
            "INTERACTION_AUTHORITY_FINAL_OOT_OPENED",
        ),
    ),
)
def test_resigned_manifest_still_requires_exact_nested_authority_bindings(
    mutation: object, expected_code: str
) -> None:
    manifest = _manifest()
    mutation(manifest)
    _resign_manifest(manifest)
    with pytest.raises(interactions.InteractionAuthorityError) as error:
        interactions.fit_interaction_authority(
            _frame(),
            training_end="2024-12-31",
            authority_manifest=manifest,
            fold_id="fold-1",
            model_family="TREE",
        )
    assert error.value.code == expected_code


def test_preprocessor_identity_records_no_model_or_score_activity() -> None:
    fitted = _fit(family="NEURAL_OR_DISTANCE", scale=True)
    identity = interactions.preprocessing_identity(fitted)
    assert identity["semanticRecomputation"] == "BEFORE_DOWNSTREAM_ENCODING_OR_SCALING"
    assert identity["scalingEnabled"] is True
    assert identity["targetRead"] is False
    assert identity["modelFitCreated"] is False
    assert identity["id"].endswith(identity["checksum"])
