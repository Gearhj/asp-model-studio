"""Hermetic state-aware adapter tests for the executable Stage 3 pipeline."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from server.sports_current_statcast import stage3_game_probability_adapter as ga
from server.sports_current_statcast.stage3_game_inputs import (
    SIMULATION_STATE_FEATURES,
    build_stage3_game_inputs,
)
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5.whole_game_monte_carlo import SimulatedPAStateBatch
from tests.sports_stage3_game_inputs_test import evidence, feature_order


PROBABILITIES = np.array([0.22, 0.09, 0.04, 0.14, 0.05, 0.01, 0.42, 0.03])


class RecordingPipeline:
    def __init__(self, *, probabilities=PROBABILITIES):
        self.ordered_features = feature_order()
        self.target_order = PA_CLASS_ORDER
        self.probabilities = probabilities
        self.frames = []

    def predict_proba(self, frame):
        self.frames.append(frame.copy(deep=True))
        raw = np.asarray(self.probabilities)
        if raw.ndim == 1:
            return np.repeat(raw[None, :], len(frame), axis=0)
        return raw


def inputs():
    return build_stage3_game_inputs(evidence(), ordered_features=feature_order())


def binding(pipeline=None, **changes):
    values = {
        "artifact_id": "stage3-artifact-verified",
        "manifest_sha256": "d" * 64,
        "model_sha256": "e" * 64,
        "feature_set_checksum": "f" * 64,
        "ordered_features": feature_order(),
        "target_order": PA_CLASS_ORDER,
        "pipeline": pipeline or RecordingPipeline(),
        "model_role": ga.FINAL_DEVELOPMENT_MODEL,
        "training_end_date": "2026-08-13",
    }
    values.update(changes)
    return ga.VerifiedStage3ArtifactBinding(**values)


def state():
    return SimulatedPAStateBatch(
        inning=np.array([1, 7, 10], dtype=np.int64),
        is_top=np.array([True, False, True], dtype=bool),
        outs_before=np.array([0, 2, 1], dtype=np.int64),
        base_mask_before=np.array([0, 7, 2], dtype=np.int64),
        away_score_before=np.array([0, 3, 5], dtype=np.int64),
        home_score_before=np.array([0, 4, 4], dtype=np.int64),
        batting_score_diff_before=np.array([0, 1, 1], dtype=np.int64),
        batting_team_pa_ordinal=np.array([0, 8, 10], dtype=np.int64),
        active=np.array([True, True, False], dtype=bool),
    )


def manifest(pipeline):
    return {
        "schemaVersion": "fixture",
        "artifactId": "stage3-artifact-verified",
        "orderedFeatures": list(pipeline.ordered_features),
        "targetOrder": list(PA_CLASS_ORDER),
        "candidate": {"featureSetChecksum": "f" * 64},
        "training": {"scope": "DEVELOPMENT_ONLY", "rows": 683_662, "cutoff": "2026-08-13"},
        "files": {"model": {"relativePath": "pipeline.joblib", "sha256": "e" * 64}},
        "verification": {"status": "PASS"},
        "safety": {
            "modelStatus": "RESEARCH_CHALLENGER",
            "promotionStatus": "NOT_PROMOTED",
            "finalOotLocked": True,
            "finalOotTargetAccessed": False,
            "providerCalls": 0,
        },
    }


def test_verified_manifest_and_pipeline_are_bound_by_canonical_checksum():
    pipeline = RecordingPipeline()
    artifact_manifest = manifest(pipeline)
    checksum = hashlib.sha256(canonical_json_bytes(artifact_manifest)).hexdigest()

    bound = ga.bind_verified_stage3_artifact(
        SimpleNamespace(manifest=artifact_manifest, pipeline=pipeline),
        expected_manifest_sha256=checksum,
    )

    assert bound.manifest_sha256 == checksum
    assert bound.ordered_features == feature_order()
    assert bound.target_order == PA_CLASS_ORDER
    assert bound.model_role == ga.FINAL_DEVELOPMENT_MODEL


def test_manifest_tamper_and_unsafe_authority_are_rejected():
    pipeline = RecordingPipeline()
    artifact_manifest = manifest(pipeline)
    checksum = hashlib.sha256(canonical_json_bytes(artifact_manifest)).hexdigest()
    artifact_manifest["training"]["cutoff"] = "2026-08-14"

    with pytest.raises(ga.Stage3GameProbabilityAdapterError) as raised:
        ga.bind_verified_stage3_artifact(
            SimpleNamespace(manifest=artifact_manifest, pipeline=pipeline),
            expected_manifest_sha256=checksum,
        )
    assert raised.value.code == "STAGE3_ARTIFACT_MANIFEST_CHECKSUM_MISMATCH"

    unsafe = manifest(pipeline)
    unsafe["safety"]["promotionStatus"] = "PROMOTED"
    unsafe_sha = hashlib.sha256(canonical_json_bytes(unsafe)).hexdigest()
    with pytest.raises(ga.Stage3GameProbabilityAdapterError) as raised:
        ga.bind_verified_stage3_artifact(
            SimpleNamespace(manifest=unsafe, pipeline=pipeline),
            expected_manifest_sha256=unsafe_sha,
        )
    assert raised.value.code == "STAGE3_ARTIFACT_SAFETY_AUTHORITY_INVALID"


def test_historical_binding_uses_the_selected_fold_pipeline_checksum():
    pipeline = RecordingPipeline()
    artifact_manifest = manifest(pipeline)
    artifact_manifest["files"]["foldModels"] = [
        {
            "relativePath": f"fold-models/fold-{number}.joblib",
            "sha256": str(number) * 64,
            "foldNumber": number,
            "trainEnd": f"2026-0{number}-01",
            "validationStart": f"2026-0{number}-02",
            "validationEnd": f"2026-0{number}-28",
        }
        for number in range(1, 6)
    ]
    artifact_manifest["oof"] = {
        "folds": [
            {
                "foldNumber": number,
                "trainEnd": f"2026-0{number}-01",
                "validationStart": f"2026-0{number}-02",
                "validationEnd": f"2026-0{number}-28",
            }
            for number in range(1, 6)
        ]
    }
    checksum = hashlib.sha256(canonical_json_bytes(artifact_manifest)).hexdigest()

    bound = ga.bind_verified_stage3_artifact(
        SimpleNamespace(manifest=artifact_manifest, pipeline=pipeline, fold_number=5),
        expected_manifest_sha256=checksum,
        model_role=ga.FOLD_VALIDATION_MODEL,
        fold_number=5,
    )

    assert bound.model_sha256 == "5" * 64
    assert bound.fold_number == 5
    assert bound.training_end_date == "2026-05-01"
    assert bound.validation_start_date == "2026-05-02"
    assert bound.validation_end_date == "2026-05-28"


def test_historical_binding_rejects_fold_boundaries_that_differ_across_manifest_records():
    pipeline = RecordingPipeline()
    artifact_manifest = manifest(pipeline)
    artifact_manifest["files"]["foldModels"] = [
        {
            "relativePath": "fold-models/fold-5.joblib",
            "sha256": "5" * 64,
            "foldNumber": 5,
            "trainEnd": "2026-05-01",
            "validationStart": "2026-05-02",
            "validationEnd": "2026-08-13",
        }
    ]
    artifact_manifest["oof"] = {
        "folds": [
            {
                "foldNumber": 5,
                "trainEnd": "2026-05-01",
                "validationStart": "2026-05-03",
                "validationEnd": "2026-08-13",
            }
        ]
    }
    checksum = hashlib.sha256(canonical_json_bytes(artifact_manifest)).hexdigest()

    with pytest.raises(ga.Stage3GameProbabilityAdapterError) as raised:
        ga.bind_verified_stage3_artifact(
            SimpleNamespace(manifest=artifact_manifest, pipeline=pipeline, fold_number=5),
            expected_manifest_sha256=checksum,
            model_role=ga.FOLD_VALIDATION_MODEL,
            fold_number=5,
        )
    assert raised.value.code == "STAGE3_FOLD_MODEL_AUTHORITY_MISMATCH"


def test_historical_binding_rejects_loaded_pipeline_from_another_fold():
    pipeline = RecordingPipeline()
    artifact_manifest = manifest(pipeline)
    artifact_manifest["files"]["foldModels"] = [
        {
            "relativePath": "fold-models/fold-5.joblib",
            "sha256": "5" * 64,
            "foldNumber": 5,
            "trainEnd": "2026-05-01",
            "validationStart": "2026-05-02",
            "validationEnd": "2026-08-13",
        }
    ]
    artifact_manifest["oof"] = {
        "folds": [
            {
                "foldNumber": 5,
                "trainEnd": "2026-05-01",
                "validationStart": "2026-05-02",
                "validationEnd": "2026-08-13",
            }
        ]
    }
    checksum = hashlib.sha256(canonical_json_bytes(artifact_manifest)).hexdigest()

    with pytest.raises(ga.Stage3GameProbabilityAdapterError) as raised:
        ga.bind_verified_stage3_artifact(
            SimpleNamespace(manifest=artifact_manifest, pipeline=pipeline, fold_number=4),
            expected_manifest_sha256=checksum,
            model_role=ga.FOLD_VALIDATION_MODEL,
            fold_number=5,
        )
    assert raised.value.code == "STAGE3_FOLD_MODEL_AUTHORITY_MISMATCH"


def test_lineup_ordinal_and_exactly_five_simulated_fields_drive_model_frame():
    pipeline = RecordingPipeline()
    game_inputs = inputs()
    provider = ga.build_stage3_probability_adapter(game_inputs, binding(pipeline))

    probabilities = provider(state())
    frame = pipeline.frames[-1]

    assert probabilities.shape == (3, 8)
    assert probabilities.flags.writeable is False
    assert tuple(frame.columns) == feature_order()
    assert frame["batter_identity"].tolist() == [
        "player:away:1",
        "player:home:9",
        "player:away:2",
    ]
    assert frame["pitcher_identity"].tolist() == [
        "player:home:starter",
        "player:away:starter",
        "player:home:starter",
    ]
    expected_state = {
        "context_inning": [1, 7, 10],
        "context_top_bottom": [0, 1, 0],
        "context_outs_before": [0, 2, 1],
        "context_base_mask_before": [0, 7, 2],
        "context_batting_score_diff_before": [0, 1, 1],
    }
    assert set(expected_state) == set(SIMULATION_STATE_FEATURES)
    for name, values in expected_state.items():
        assert frame[name].tolist() == values

    selected = (game_inputs.templates[0], game_inputs.templates[17], game_inputs.templates[1])
    for position, name in enumerate(game_inputs.non_simulation_features):
        assert frame[name].tolist() == [row.frozen_predictor_values[position] for row in selected]


def test_long_extra_inning_state_supported_by_simulator_crosses_adapter_boundary():
    pipeline = RecordingPipeline()
    provider = ga.build_stage3_probability_adapter(inputs(), binding(pipeline))
    long_game = state()
    object.__setattr__(long_game, "inning", np.array([31, 50, 99], dtype=np.int64))

    probabilities = provider(long_game)

    assert probabilities.shape == (3, 8)
    assert pipeline.frames[-1]["context_inning"].tolist() == [31, 50, 99]


@pytest.mark.parametrize(
    "probabilities",
    [
        np.full((3, 7), 1 / 7),
        np.full((3, 8), np.nan),
        np.full((3, 8), 0.1),
        np.tile(np.array([-0.1, 1.1, 0, 0, 0, 0, 0, 0]), (3, 1)),
    ],
)
def test_invalid_probability_matrices_fail_closed(probabilities):
    provider = ga.build_stage3_probability_adapter(
        inputs(), binding(RecordingPipeline(probabilities=probabilities))
    )
    with pytest.raises(ga.Stage3GameProbabilityAdapterError) as raised:
        provider(state())
    assert raised.value.code in {
        "STAGE3_PIPELINE_PROBABILITY_INVALID",
        "STAGE3_PIPELINE_PROBABILITY_SHAPE_INVALID",
    }


def test_illegal_simulated_state_is_rejected_before_pipeline_invocation():
    pipeline = RecordingPipeline()
    provider = ga.build_stage3_probability_adapter(inputs(), binding(pipeline))
    bad = state()
    object.__setattr__(bad, "outs_before", np.array([0, 3, 1], dtype=np.int64))

    with pytest.raises(ga.Stage3GameProbabilityAdapterError) as raised:
        provider(bad)
    assert raised.value.code == "SIMULATED_STATE_BATCH_INVALID"
    assert pipeline.frames == []
