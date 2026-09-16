"""Synthetic integration through the actual Model Lab fold entry point."""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier

from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_current_statcast import stage3_corrected_prior_treatment as prior
from server.sports_current_statcast import stage3_semantic_treatment as semantic
from server.sports_current_statcast import stage3_player_prior_authority as prior_v1
from server.sports_current_statcast.stage3_corrected_eligibility import registered_policy
from server.sports_current_statcast.stage3_corrected_preprocessing_artifacts import load_research_pipeline
from sports_stage3_semantic_treatment_test import _frame, _manifest
from sports_stage3_corrected_prior_treatment_test import synthetic_authorities, _pair, _fit


def _contract(source):
    schema = prior.build_prior_output_schema(source)
    states = {row["name"] for row in schema["additions"] if row["dtype"] == "string"}
    return {
        "featureSetId": "synthetic-corrected-feature-set", "checksum": "a" * 64,
        "orderedFeatures": schema["orderedFeatures"],
        "transformationContracts": {
            "semanticTreatmentVersion": "MLB_SEMANTIC_TREATMENT_V1",
            "sourceOrderedFeatures": source,
            "ordered": [{"feature": name, "steps": ["CATEGORICAL_UNKNOWN", "ONE_HOT"] if name in states else ["SEMANTIC_NUMERIC_PASSTHROUGH"]} for name in schema["orderedFeatures"]],
        },
    }


def _context_case():
    source = ["pitcher_log1p_bfp", "fielding_travel_distance_miles", "fielding_prior_extra_innings_x_travel",
              "fielding_previous_game_extra_innings", "batting_home_x_weekend", "series_game_number"]
    base = _frame(source)
    frame = base.iloc[np.arange(16) % 3].reset_index(drop=True)
    frame["game_date"] = ["2024-04-01"] * 8 + ["2024-04-02"] * 8
    frame["outcome"] = list(lab.GOLD_CLASS_ORDER) * 2
    frame["canonicalGameId"] = ["train-game"] * 8 + ["validation-game"] * 8
    frame["canonicalPaId"] = [f"synthetic-{i}" for i in range(16)]
    frame.loc[[0, 8], "pitcher_log1p_bfp"] = np.nan
    frame.loc[[0, 8], "pitcher_prior_missing"] = 1
    frame.loc[[0, 8], "fielding_previous_game_missing"] = 1
    frame.loc[[0, 8], ["fielding_travel_distance_miles", "fielding_previous_game_extra_innings"]] = np.nan
    frame["fielding_prior_extra_innings_x_travel"] = -999.0
    frame.attrs["interactionAuthority"] = _manifest()
    fold = {"foldNumber": 1, "trainStart": "2024-04-01", "trainEnd": "2024-04-01", "trainRows": 8, "trainGames": 1,
            "validationStart": "2024-04-02", "validationEnd": "2024-04-02", "validationRows": 8, "validationGames": 1}
    return frame, _contract(source), fold


def _evaluate(frame, feature_set, fold, monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_STAGE3_MODEL_LAB_ROOT", str(tmp_path))
    # A tiny deterministic synthetic estimator exercises integration, not the
    # user's authorized five full-population HGB fits.
    monkeypatch.setattr(lab, "_model", lambda *a, **k: DummyClassifier(strategy="prior"))
    return lab._evaluate_candidate(frame, model_family="histogram_gradient_boosting", feature_set=feature_set,
        split={"contract": {"folds": [fold]}}, seed=42, hyperparameters={"syntheticOnly": True})


def _prior_case(synthetic_authorities, source):
    frame, _, train, validation = _pair(synthetic_authorities, source)
    frame["outcome"] = [lab.GOLD_CLASS_ORDER[i % 8] for i in range(len(frame))]
    fold = {"foldNumber": 1, "trainStart": str(frame.loc[train, "game_date"].min()),
            "trainEnd": str(frame.loc[train, "game_date"].max()), "trainRows": int(train.sum()),
            "trainGames": frame.loc[train, "canonicalGameId"].nunique(),
            "validationStart": "2024-02-01", "validationEnd": "2024-02-01", "validationRows": 1, "validationGames": 1}
    return frame, _contract(source), fold, train, validation


def _loaded_validation(result, frame, validation, tmp_path):
    evidence = result["folds"][0]["preprocessing"]
    loaded = load_research_pipeline(evidence["localResearchArtifact"]["model"], root=tmp_path)
    raw = frame.loc[validation, list(loaded.ordered_features)]
    return loaded, raw, loaded.preprocessor.transform_frame(raw)


def test_actual_fold_entry_orders_treatment_persists_and_reloads(monkeypatch, tmp_path):
    frame, feature_set, fold = _context_case()
    result = _evaluate(frame, feature_set, fold, monkeypatch, tmp_path)
    evidence = result["folds"][0]["preprocessing"]
    branches = evidence["validationBranchCounts"]["features"]
    assert branches["pitcher_log1p_bfp"]["semanticZeroRows"] == 1
    assert branches["fielding_travel_distance_miles"]["nativeMissingRows"] == 1
    assert branches["fielding_prior_extra_innings_x_travel"]["parentEqualityPassed"] is True
    assert evidence["numericMissingTreatment"] == "GOVERNED_REASON_AWARE_NO_GENERIC_FALLBACK"
    assert evidence["localResearchArtifact"]["refitsDuringReload"] == 0
    assert evidence["validationRowsUsedForParameters"] == 0
    assert evidence["finalOotRowsUsedForParameters"] == 0
    reloaded = load_research_pipeline(evidence["localResearchArtifact"]["model"], root=tmp_path)
    monkeypatch.setattr(semantic, "fit_semantic_treatment", lambda *a, **k: pytest.fail("Reload fitted semantics"))
    source = frame.loc[8:, list(reloaded.ordered_features)]
    transformed = reloaded.preprocessor.transform_frame(source)
    assert transformed.iloc[0]["pitcher_log1p_bfp"] == 0.0
    assert pd.isna(transformed.iloc[0]["fielding_travel_distance_miles"])
    assert pd.isna(transformed.iloc[0]["fielding_prior_extra_innings_x_travel"])
    assert reloaded.predict_proba(source).shape == (8, 8)


@pytest.mark.parametrize("mutation", ["source", "invalid", "future_missing"])
def test_actual_entry_rejects_bad_evidence_before_estimator(monkeypatch, tmp_path, mutation):
    frame, feature_set, fold = _context_case()
    if mutation == "source": frame.loc[9, "fielding_current_venue_coordinates_missing"] = 1
    elif mutation == "invalid": frame.loc[9, "fielding_travel_distance_miles"] = -1
    else: frame.loc[9, "series_game_number"] = np.nan
    monkeypatch.setattr(lab, "_model", lambda *a, **k: pytest.fail("Estimator created after invalid evidence"))
    with pytest.raises(semantic.SemanticTreatmentError):
        lab._evaluate_candidate(frame, model_family="histogram_gradient_boosting", feature_set=feature_set,
            split={"contract": {"folds": [fold]}}, seed=42)


def test_actual_entry_preserves_raw_and_registers_prior_outputs(synthetic_authorities, monkeypatch, tmp_path):
    frame, _, train, val = _pair(synthetic_authorities, ["batter_so_per_pa"])
    source = ["batter_so_per_pa"]
    feature_set = _contract(source)
    frame["outcome"] = [lab.GOLD_CLASS_ORDER[i % 8] for i in range(len(frame))]
    fold = {"foldNumber": 1, "trainStart": str(frame.loc[train, "game_date"].min()),
            "trainEnd": str(frame.loc[train, "game_date"].max()), "trainRows": int(train.sum()),
            "trainGames": frame.loc[train, "canonicalGameId"].nunique(),
            "validationStart": "2024-02-01", "validationEnd": "2024-02-01", "validationRows": 1, "validationGames": 1}
    result = _evaluate(frame, feature_set, fold, monkeypatch, tmp_path)
    evidence = result["folds"][0]["preprocessing"]
    loaded = load_research_pipeline(evidence["localResearchArtifact"]["model"], root=tmp_path)
    raw = frame.loc[val, list(loaded.ordered_features)]
    transformed = loaded.preprocessor.transform_frame(raw)
    assert transformed[source[0]].iloc[0] == frame.loc[val, source[0]].iloc[0]
    assert len(transformed.columns) == 6
    state_path = tmp_path / evidence["fittedArtifact"]["relativePath"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["prior"]["wave1FittedAuthority"]["parameters"]
    assert state["targetColumnsReadForTreatment"] == []
    assert state["prior"]["validationRowsUsedForFit"] == 0


def test_corrected_full_development_extra_fit_is_held_closed():
    with pytest.raises(lab.Stage3ModelLaboratoryError, match="registered fold"):
        lab.fit_stage3_pipeline(pd.DataFrame(), model_family="histogram_gradient_boosting", feature_set=_contract(["series_game_number"]), seed=42)


def test_corrected_final_oot_fence_precedes_target_access():
    class TargetTripwire(pd.DataFrame):
        def __getitem__(self, key):
            if isinstance(key, str) and key == "outcome":
                pytest.fail("Final OOT target was accessed")
            return super().__getitem__(key)
    frame = TargetTripwire({"game_date": ["2026-08-14"]})
    with pytest.raises(lab.Stage3ModelLaboratoryError, match="before reading targets"):
        lab._evaluate_candidate(frame, model_family="histogram_gradient_boosting", feature_set=_contract(["series_game_number"]), split={}, seed=42)


def test_corrected_selection_and_other_model_family_are_not_authorized():
    frame = pd.DataFrame({"game_date": ["2024-01-01"]})
    for family, selector in [("random_forest", None), ("histogram_gradient_boosting", {"method": "RFE"})]:
        with pytest.raises(lab.Stage3ModelLaboratoryError, match="without selection"):
            lab._evaluate_candidate(frame, model_family=family, feature_set=_contract(["series_game_number"]), split={}, seed=42, fold_local_selector=selector)


@pytest.mark.parametrize("history", ["cold", "insufficient"])
def test_actual_entry_prior_history_branches_survive_saved_reload(synthetic_authorities, monkeypatch, tmp_path, history):
    feature = "batter_so_per_pa" if history == "cold" else "batter_last100_strikeout_rate"
    frame, feature_set, fold, _, validation = _prior_case(synthetic_authorities, [feature])
    if history == "cold":
        frame.loc[validation, [feature, "batter_log1p_pa"]] = np.nan
        frame.loc[validation, "batter_prior_missing"] = 1
    else:
        frame.loc[validation, feature] = 0.2
        frame.loc[validation, "batter_last100_pa_count"] = 10
        frame.loc[validation, "batter_last100_insufficient"] = 1
    result = _evaluate(frame, feature_set, fold, monkeypatch, tmp_path)
    # Neither prior nor semantic fit is available to the frozen path.
    monkeypatch.setattr(prior_v1, "fit_prior_authority", lambda *a, **k: pytest.fail("Reload fitted a prior"))
    monkeypatch.setattr(semantic, "fit_semantic_treatment", lambda *a, **k: pytest.fail("Reload fitted semantics"))
    loaded, raw, transformed = _loaded_validation(result, frame, validation, tmp_path)
    names = prior_v1.feature_binding(feature)["derivedOutputs"]
    row = transformed.iloc[0]
    assert row[names["historyState"]] == ("TRUE_COLD_START" if history == "cold" else "SPARSE_HISTORY")
    assert row[names["effectiveN"]] == (0 if history == "cold" else 10)
    assert np.isfinite(row[names["posteriorMean"]])
    assert pd.isna(row[feature]) if history == "cold" else row[feature] == 0.2
    assert loaded.predict_proba(raw).shape == (1, 8)


@pytest.mark.parametrize("failure", ["v1_source", "v2_source", "invalid_posterior", "insufficient_missing_exposure"])
def test_actual_entry_prior_failure_cannot_reach_estimator(synthetic_authorities, monkeypatch, failure):
    feature = ("pitcher_gs_per_g" if failure == "v2_source" else
               "batter_last100_strikeout_rate" if failure == "insufficient_missing_exposure" else "batter_so_per_pa")
    frame, feature_set, fold, _, validation = _prior_case(synthetic_authorities, [feature])
    if failure == "v1_source":
        frame.loc[validation, feature] = np.nan
    elif failure == "v2_source":
        frame.loc[validation, "pitcher_prior_gs"] = np.nan
    elif failure == "insufficient_missing_exposure":
        frame.loc[validation, [feature, "batter_last100_pa_count"]] = np.nan
        frame.loc[validation, "batter_last100_insufficient"] = 1
    else:
        original = prior_v1.transform_prior_features
        def poison(*args, **kwargs):
            transformed = original(*args, **kwargs)
            transformed[prior_v1.feature_binding(feature)["derivedOutputs"]["posteriorMean"]] = np.nan
            return transformed
        monkeypatch.setattr(prior_v1, "transform_prior_features", poison)
    monkeypatch.setattr(lab, "_model", lambda *a, **k: pytest.fail("Invalid prior reached estimator"))
    with pytest.raises(prior.CorrectedPriorTreatmentError):
        lab._evaluate_candidate(frame, model_family="histogram_gradient_boosting", feature_set=feature_set,
            split={"contract": {"folds": [fold]}}, seed=42)


@pytest.mark.parametrize("bad_value", [2.0, np.nan, np.inf])
def test_actual_entry_checks_validation_boolean_not_just_training(monkeypatch, bad_value):
    frame, feature_set, fold = _context_case()
    flag = "batter_last100_insufficient"
    frame[flag] = 0.0
    frame.loc[9, flag] = bad_value
    source = feature_set["transformationContracts"]["sourceOrderedFeatures"] + [flag]
    feature_set = _contract(source)
    feature_set["transformationContracts"]["ordered"][-1]["steps"] = ["SEMANTIC_BOOLEAN_PASSTHROUGH"]
    monkeypatch.setattr(lab, "_model", lambda *a, **k: pytest.fail("Invalid Boolean reached estimator"))
    with pytest.raises(semantic.SemanticTreatmentError):
        lab._evaluate_candidate(frame, model_family="histogram_gradient_boosting", feature_set=feature_set,
            split={"contract": {"folds": [fold]}}, seed=42)


def test_actual_entry_keeps_all_nan_column_only_with_verified_history(monkeypatch, tmp_path):
    frame, feature_set, fold = _context_case()
    frame["fielding_previous_game_missing"] = 1
    frame[["fielding_travel_distance_miles", "fielding_previous_game_extra_innings"]] = np.nan
    result = _evaluate(frame, feature_set, fold, monkeypatch, tmp_path)
    loaded, raw, transformed = _loaded_validation(result, frame, np.arange(len(frame)) >= 8, tmp_path)
    for feature in ("fielding_travel_distance_miles", "fielding_prior_extra_innings_x_travel"):
        assert feature in transformed
        assert transformed[feature].isna().all()
        assert any(name.endswith("__" + feature) for name in loaded.preprocessor.get_feature_names_out())
    assert loaded.predict_proba(raw).shape == (8, 8)
    # A saved pipeline must recheck evidence and not merely pass all NaNs on.
    corrupted = raw.copy()
    corrupted["fielding_previous_game_missing"] = 0
    with pytest.raises(semantic.SemanticTreatmentError):
        loaded.predict_proba(corrupted)


def test_actual_entry_rejects_unexplained_all_nan_numeric(monkeypatch):
    frame, feature_set, fold = _context_case()
    frame["month_sin"] = np.nan
    source = feature_set["transformationContracts"]["sourceOrderedFeatures"] + ["month_sin"]
    feature_set = _contract(source)
    monkeypatch.setattr(lab, "_model", lambda *a, **k: pytest.fail("Unexplained all-NaN numeric reached estimator"))
    with pytest.raises(semantic.SemanticTreatmentError):
        lab._evaluate_candidate(frame, model_family="histogram_gradient_boosting", feature_set=feature_set,
            split={"contract": {"folds": [fold]}}, seed=42)


def test_actual_entry_quarantine_preserves_original_fit_boundary(synthetic_authorities, monkeypatch, tmp_path):
    source = ["batter_so_per_pa", "batter_bb_hbp_per_pa", "batter_hr_per_pa"]
    frame, feature_set, fold, train, validation = _prior_case(synthetic_authorities, source)
    feature_set["transformationContracts"]["rowEligibilityPolicy"] = registered_policy()
    # Remove a duplicate-class training observation, retaining all eight classes.
    frame.loc[8, source] = np.nan
    frame.loc[8, "batter_log1p_pa"] = 0.0
    frame.loc[8, "batter_prior_missing"] = 0
    captured = {}
    original_semantic_fit = semantic.fit_semantic_treatment
    def capture_semantics(training, **kwargs):
        captured["semanticRows"] = len(training)
        captured["semanticDates"] = training["game_date"].tolist()
        captured["semanticColumns"] = set(training)
        return original_semantic_fit(training, **kwargs)
    monkeypatch.setattr(semantic, "fit_semantic_treatment", capture_semantics)
    result = _evaluate(frame, feature_set, fold, monkeypatch, tmp_path)
    evidence = result["folds"][0]["preprocessing"]
    state = json.loads((tmp_path / evidence["fittedArtifact"]["relativePath"]).read_text(encoding="utf-8"))
    assert captured["semanticRows"] == int(train.sum()) == 10
    assert captured["semanticDates"] == frame.loc[train, "game_date"].tolist()
    assert "outcome" not in captured["semanticColumns"]
    assert result["folds"][0]["trainRows"] == 9
    assert state["prior"]["fitRows"] == 10
    assert state["prior"]["modelEligibleTrainRows"] == 9
    assert state["prior"]["validationRowsUsedForFit"] == 0
    loaded, raw, transformed = _loaded_validation(result, frame, validation, tmp_path)
    assert len(transformed) == 1
    assert loaded.predict_proba(raw).shape == (1, 8)


def _repeat_case():
    frame, feature_set, fold = _context_case()
    repeats = [f"{side}_repeat_opponent_within_{days}_days" for side in ("batting", "fielding") for days in (7, 14)]
    source = feature_set["transformationContracts"]["sourceOrderedFeatures"] + repeats
    feature_set = _contract(source)
    for feature in repeats:
        frame[feature] = (np.arange(len(frame)) % 3).astype(float)
    for row in feature_set["transformationContracts"]["ordered"]:
        if row["feature"] in repeats: row["steps"] = ["SEMANTIC_BOOLEAN_PASSTHROUGH"]
    return frame, feature_set, fold, repeats


def test_actual_entry_repeat_opponent_domain_repair_and_saved_reload(monkeypatch, tmp_path):
    frame, feature_set, fold, repeats = _repeat_case()
    original = frame[repeats].copy()
    result = _evaluate(frame, feature_set, fold, monkeypatch, tmp_path)
    validation = np.arange(len(frame)) >= 8
    loaded, raw, transformed = _loaded_validation(result, frame, validation, tmp_path)
    for feature in repeats:
        assert transformed[feature].tolist() == (original.loc[validation, feature] > 0).astype(float).tolist()
        assert result["folds"][0]["preprocessing"]["validationBranchCounts"]["features"][feature]["booleanDomainRepairRows"] > 0
    pd.testing.assert_frame_equal(frame[repeats], original)
    for value in (-1.0, 1.5, np.nan):
        malformed = raw.copy()
        malformed.loc[malformed.index[0], repeats[0]] = value
        with pytest.raises(semantic.SemanticTreatmentError): loaded.predict_proba(malformed)


@pytest.mark.parametrize("index", [1, 9])
@pytest.mark.parametrize("value", [-1.0, 1.5, np.nan])
def test_actual_entry_repeat_opponent_invalid_training_or_validation_fails(monkeypatch, index, value):
    frame, feature_set, fold, repeats = _repeat_case()
    frame.loc[index, repeats[0]] = value
    monkeypatch.setattr(lab, "_model", lambda *a, **k: pytest.fail("Invalid repeat-opponent count reached estimator"))
    with pytest.raises(semantic.SemanticTreatmentError):
        lab._evaluate_candidate(frame, model_family="histogram_gradient_boosting", feature_set=feature_set,
            split={"contract": {"folds": [fold]}}, seed=42)
