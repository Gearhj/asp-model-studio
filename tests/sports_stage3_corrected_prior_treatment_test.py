from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast import stage3_corrected_prior_treatment as corrected
from server.sports_current_statcast import stage3_player_prior_authority as prior_v1
from server.sports_current_statcast import stage3_player_prior_authority_v2 as prior_v2
from sports_stage3_player_prior_authority_v2_test import (
    _definition, _fold_record, _synthetic_fit_frame, _v1_manifest,
)


@pytest.fixture(scope="module")
def synthetic_authorities():
    training = _synthetic_fit_frame().iloc[:10].copy()
    v2 = prior_v2.fit_fold_authority(
        training, _definition(), _fold_record(),
        fold_contract_id="FOLD_CONTRACT:test", fold_contract_checksum="f" * 64,
    )
    validation = training.iloc[-1:].copy()
    validation["game_date"] = "2024-02-01"
    validation["canonicalPaId"] = "validation-1"
    validation["canonicalGameId"] = "validation-game"
    frame = pd.concat([training, validation], ignore_index=True)
    for feature in prior_v1.SUPPORTED_PRIOR_FEATURES:
        binding = prior_v1.feature_binding(feature)
        exposure = 100.0 if binding["exposureTransform"] == "EXPM1_VALIDATE_INTEGER" else float(binding["establishedThreshold"])
        frame[binding["exposureFeature"]] = np.log1p(exposure) if binding["exposureTransform"] == "EXPM1_VALIDATE_INTEGER" else exposure
        frame[feature] = (np.arange(len(frame)) % 5 + 5) / exposure
    for feature in prior_v2.WAVE2_FEATURES:
        frame[feature] = 93.0 if "velocity" in feature else 1.2 if feature == "pitcher_whip" else 0.2
    frame["outcome"] = "POISON_TARGET_NOT_AN_ENGINE_INPUT"
    runtime = {
        "v1Authority": _v1_manifest(), "v2FittedByFold": {1: v2},
        "v1Features": sorted(prior_v1.SUPPORTED_PRIOR_FEATURES),
        "v2Features": sorted(prior_v2.WAVE2_FEATURES),
        "companionAuthenticationChecksum": "a" * 64,
    }
    return frame, runtime


def _pair(synthetic_authorities, sources=None):
    original, runtime = synthetic_authorities
    frame = original.copy()
    frame.attrs["governedPriorRuntime"] = copy.deepcopy(runtime)
    sources = list(sources or sorted(prior_v1.SUPPORTED_PRIOR_FEATURES | set(prior_v2.WAVE2_FEATURES)))
    schema = corrected.build_prior_output_schema(sources, runtime)
    feature_set = {
        "featureSetId": "synthetic-successor", "orderedFeatures": schema["orderedFeatures"],
        "transformationContracts": {"sourceOrderedFeatures": sources},
    }
    train = np.arange(len(frame)) < 10
    return frame, feature_set, train, ~train


def _fit(args):
    frame, features, train, validation = args
    return corrected.fit_transform_prior_pair(
        frame, train_mask=train, validation_mask=validation,
        fold=_fold_record(), feature_set=features,
    )


def test_schema_registers_required_v1_outputs_and_no_optional_v2_candidates():
    source = sorted(prior_v1.SUPPORTED_PRIOR_FEATURES | set(prior_v2.WAVE2_FEATURES)) + [f"ordinary_{n}" for n in range(197)]
    schema = corrected.build_prior_output_schema(source)
    assert len(source) == 218
    assert schema["featureCount"] == 273
    assert len(schema["additions"]) == 55
    assert len([r for r in schema["additions"] if r["dtype"] == "string"]) == 11
    assert {r["role"] for r in schema["additions"]} == set(corrected.V1_MODEL_OUTPUT_ROLES)
    assert schema["optionalWave2OutputsAdded"] == []
    assert schema["orderedFeatures"][:218] == source


def test_full_raw_plus_derived_representation_and_json_reload_without_fit(synthetic_authorities, monkeypatch):
    args = _pair(synthetic_authorities)
    original, _, train_mask, validation_mask = args
    train, validation, evidence, payload = _fit(args)
    for feature in prior_v1.SUPPORTED_PRIOR_FEATURES:
        pd.testing.assert_series_equal(train[feature], original.loc[train_mask, feature])
        pd.testing.assert_series_equal(validation[feature], original.loc[validation_mask, feature])
        names = prior_v1.feature_binding(feature)["derivedOutputs"]
        assert all(names[role] in train for role in corrected.V1_MODEL_OUTPUT_ROLES)
    assert len(payload["wave1FittedAuthority"]["parameters"]) == 11
    assert len(payload["wave2FittedAuthority"]["parameters"]) == 7
    assert evidence["fitRows"] == 10
    assert evidence["validationRowsUsedForFit"] == 0
    assert evidence["targetColumnsRead"] == []
    for item in evidence["validation"]["features"]:
        if item["wave"] == 1:
            assert item["preservedRawRows"] == 1
            assert item["requiredDerivedOutputColumnsAdded"] == 5
            assert item["trueColdRawMissingRetainedRows"] == 0
    for feature in prior_v2.WAVE2_FEATURES:
        assert not any(name.startswith(feature + "__prior_v2__") for name in validation.columns)
    frozen = json.loads(json.dumps(payload))
    monkeypatch.setattr(prior_v1, "fit_prior_authority", lambda *a, **k: pytest.fail("Reload refitted V1"))
    monkeypatch.setattr(prior_v2, "fit_fold_authority", lambda *a, **k: pytest.fail("Reload refitted V2"))
    replay, replay_evidence = corrected.transform_prior_frame(original.loc[validation_mask], frozen)
    pd.testing.assert_frame_equal(validation, replay)
    assert replay_evidence["fittingPerformed"] is False
    assert replay_evidence == evidence["validation"]


def test_verified_cold_raw_stays_nan_but_posterior_and_effective_n_are_valid(synthetic_authorities):
    args = _pair(synthetic_authorities, ["batter_so_per_pa"])
    frame = args[0]
    frame.loc[10, ["batter_so_per_pa", "batter_log1p_pa"]] = np.nan
    frame.loc[10, "batter_prior_missing"] = 1
    _, transformed, evidence, _ = _fit(args)
    names = prior_v1.feature_binding("batter_so_per_pa")["derivedOutputs"]
    assert pd.isna(transformed.loc[10, "batter_so_per_pa"])
    assert np.isfinite(transformed.loc[10, names["posteriorMean"]])
    assert transformed.loc[10, names["effectiveN"]] == 0
    assert transformed.loc[10, names["posteriorReliability"]] == 0
    assert transformed.loc[10, names["historyState"]] == "TRUE_COLD_START"
    assert evidence["validation"]["features"][0]["ordinaryMedianOrModeFallbackRows"] == 0
    assert evidence["validation"]["features"][0]["trueColdRawMissingRetainedRows"] == 1
    assert evidence["validation"]["features"][0]["preservedRawRows"] == 0


def test_sparse_history_preserves_observed_raw_and_positive_exposure(synthetic_authorities):
    feature = "batter_last100_strikeout_rate"
    args = _pair(synthetic_authorities, [feature])
    args[0].loc[10, feature] = 0.2
    args[0].loc[10, "batter_last100_pa_count"] = 10
    args[0].loc[10, "batter_last100_insufficient"] = 1
    _, transformed, _, _ = _fit(args)
    names = prior_v1.feature_binding(feature)["derivedOutputs"]
    assert transformed.loc[10, feature] == 0.2
    assert transformed.loc[10, names["effectiveN"]] == 10
    assert transformed.loc[10, names["historyState"]] == "SPARSE_HISTORY"


@pytest.mark.parametrize("case", ["source", "invalid_raw", "invalid_posterior", "insufficient_missing_exposure"])
def test_v1_failed_evidence_never_receives_ordinary_imputation(synthetic_authorities, monkeypatch, case):
    feature = "batter_last100_strikeout_rate" if case == "insufficient_missing_exposure" else "batter_so_per_pa"
    args = _pair(synthetic_authorities, [feature])
    if case == "source":
        args[0].loc[10, feature] = np.nan
    elif case == "invalid_raw":
        args[0].loc[10, feature] = 1.5
    elif case == "insufficient_missing_exposure":
        args[0].loc[10, [feature, "batter_last100_pa_count"]] = np.nan
        args[0].loc[10, "batter_last100_insufficient"] = 1
    else:
        original_transform = prior_v1.transform_prior_features
        def poison(*a, **k):
            result = original_transform(*a, **k)
            result[prior_v1.feature_binding(feature)["derivedOutputs"]["posteriorMean"]] = np.nan
            return result
        monkeypatch.setattr(prior_v1, "transform_prior_features", poison)
    with pytest.raises(corrected.CorrectedPriorTreatmentError, match="no ordinary imputation"):
        _fit(args)


def test_v2_source_unavailable_posterior_is_rejected_before_median(synthetic_authorities):
    args = _pair(synthetic_authorities, ["pitcher_gs_per_g"])
    args[0].loc[10, "pitcher_prior_gs"] = np.nan
    with pytest.raises(corrected.CorrectedPriorTreatmentError) as raised:
        _fit(args)
    assert raised.value.code == "CORRECTED_PRIOR_OUTPUT_REQUIRES_REVIEW"
    assert raised.value.evidence["historyStateCounts"] == {"SOURCE_UNAVAILABLE": 1}


def test_v2_existing_explicit_whip_fallback_is_preserved_and_counted(synthetic_authorities):
    args = _pair(synthetic_authorities, ["pitcher_whip"])
    args[0].loc[10, "pitcher_prior_ipouts"] = 0
    _, transformed, evidence, _ = _fit(args)
    assert np.isfinite(transformed.loc[10, "pitcher_whip"])
    row = evidence["validation"]["features"][0]
    assert row["governedWhipFallbackRows"] == 1
    assert row["historyStateCounts"] == {"COMPUTATION_FAILURE": 1}
    assert row["ordinaryMedianOrModeFallbackRows"] == 0


def test_fit_receives_only_exact_training_rows_and_no_targets(synthetic_authorities, monkeypatch):
    args = _pair(synthetic_authorities, ["batter_so_per_pa"])
    original_fit = prior_v1.fit_prior_authority
    observed = {}
    def capture(frame, **kwargs):
        observed["rows"] = len(frame)
        observed["date_max"] = frame["game_date"].max()
        observed["columns"] = set(frame)
        return original_fit(frame, **kwargs)
    monkeypatch.setattr(prior_v1, "fit_prior_authority", capture)
    _, _, _, payload = _fit(args)
    assert observed["rows"] == 10
    assert observed["date_max"] == "2024-01-02"
    assert "outcome" not in observed["columns"]
    assert payload["wave1FittedAuthority"]["rowsAfterTrainingCutoffExcluded"] == 0
    baseline_checksum = payload["wave1FittedAuthority"]["fittedChecksum"]
    args[0].loc[10, "batter_so_per_pa"] = 0.42
    assert _fit(args)[3]["wave1FittedAuthority"]["fittedChecksum"] == baseline_checksum


def test_fitted_tamper_and_oot_date_rejected_before_prior_input_access(synthetic_authorities, monkeypatch):
    args = _pair(synthetic_authorities, ["batter_so_per_pa"])
    payload = _fit(args)[3]
    altered = copy.deepcopy(payload)
    altered["wave1FittedAuthority"]["parameters"]["batter_so_per_pa"]["alpha"] += 1
    with pytest.raises(corrected.CorrectedPriorTreatmentError, match="authenticated"):
        corrected.transform_prior_frame(args[0].iloc[-1:], altered)
    oot_date_only = pd.DataFrame({"game_date": ["2026-08-14"]})
    monkeypatch.setattr(prior_v1, "transform_prior_features", lambda *a, **k: pytest.fail("Read OOT inputs"))
    with pytest.raises(corrected.CorrectedPriorTreatmentError) as raised:
        corrected.transform_prior_frame(oot_date_only, payload)
    assert raised.value.code == "CORRECTED_PRIOR_FINAL_OOT_SEALED"


def test_registered_schema_cannot_omit_required_prior_outputs(synthetic_authorities):
    args = _pair(synthetic_authorities, ["batter_so_per_pa"])
    args[1]["orderedFeatures"] = ["batter_so_per_pa"]
    with pytest.raises(corrected.CorrectedPriorTreatmentError) as raised:
        _fit(args)
    assert raised.value.code == "CORRECTED_PRIOR_REGISTERED_SCHEMA_MISMATCH"
