from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from server.core.dataset_store import DATASTORE
from server.scoring_runs.treatment_replay import (
    GovernedTreatmentReplayError,
    replay_external_scoring_treatments,
)
from server.training.candidate_contract import canonical_contract_hash


PROJECT_ID = "atlas-treatment-replay"
DATASET_ID = "dataset-treatment-replay"
DATASET_VERSION_ID = "version-treatment-replay"
PARTITION_ID = "partition-treatment-replay"
PARTITION_REVISION = 4


def _identity() -> dict[str, object]:
    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION_ID,
        "dataset_version": DATASET_VERSION_ID,
        "analysis_partition_id": PARTITION_ID,
        "analysis_partition_revision": PARTITION_REVISION,
    }


def _fixture() -> tuple[dict[str, object], dict[str, object]]:
    special_step = {
        "step_id": "special-values-executable-1",
        "transformation_type": "special_value_treatment",
        "enabled": True,
        "fit_scope": "training_only",
        "config": {
            "treatments": [
                {
                    "feature": "x",
                    "policy": "convert_to_missing",
                    "values": [-9],
                },
                {
                    "feature": "z",
                    "policy": "preserve_informative",
                    "values": [-9],
                },
            ]
        },
    }
    outlier_application = {
        **_identity(),
        "state": "applied",
        "global_method": "IQR_1_5",
        "treatments": [
            {
                "feature": "x",
                "configured_method": "USE_GLOBAL",
                "applied_method": "IQR_1_5",
                "lower_threshold": 0.0,
                "upper_threshold": 50.0,
                "changed_values": 1,
                "special_values_preserved": 1,
            },
            {
                "feature": "z",
                "configured_method": "USE_GLOBAL",
                "applied_method": "IQR_1_5",
                "lower_threshold": 0.0,
                "upper_threshold": 50.0,
                "changed_values": 1,
                "special_values_preserved": 1,
            },
        ],
    }
    missing_application = {
        **_identity(),
        "source_stage": "outlier_treated",
        "treatments": [
            {"feature": "x", "strategy": "Median", "filled": 2, "value": "10.0"},
            {
                "feature": "segment",
                "strategy": "Mode",
                "filled": 1,
                "value": "A",
            },
        ],
    }
    missing_validation = None
    meta: dict[str, object] = {
        "outlier_application": outlier_application,
        "missing_application": missing_application,
        "missing_validation": missing_validation,
        "special_value_review": {
            "status": "confirmed",
            "variable_decisions": [
                {"variable": "x", "policy": "convert_to_missing"},
                {"variable": "z", "policy": "preserve_informative"},
            ],
        },
    }
    contract: dict[str, object] = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION_ID,
        "analysis_partition_id": PARTITION_ID,
        "analysis_partition_revision": PARTITION_REVISION,
        "target_name": "target",
        "preprocessing_pipeline": [special_step],
    }
    payload = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION_ID,
        "outlier_application": deepcopy(outlier_application),
        "missing_application": deepcopy(missing_application),
        "missing_validation": missing_validation,
        "preprocessing_pipeline": [deepcopy(special_step)],
    }
    digest = canonical_contract_hash(payload)
    contract["treatment_manifest_hash"] = digest
    contract["treatment_manifest_id"] = f"tm-{digest[:20]}"
    return meta, contract


def _replay(
    frame: pd.DataFrame,
    meta: dict[str, object],
    contract: dict[str, object],
):
    return replay_external_scoring_treatments(
        frame,
        datastore_meta=meta,
        candidate_contract=contract,
        expected_project_id=PROJECT_ID,
        expected_dataset_id=DATASET_ID,
        expected_dataset_version_id=DATASET_VERSION_ID,
    )


def _rehash(meta: dict[str, object], contract: dict[str, object]) -> None:
    payload = {
        "project_id": contract["project_id"],
        "dataset_id": contract["dataset_id"],
        "dataset_version_id": contract["dataset_version_id"],
        "outlier_application": deepcopy(meta.get("outlier_application")),
        "missing_application": deepcopy(meta.get("missing_application")),
        "missing_validation": deepcopy(meta.get("missing_validation")),
        "preprocessing_pipeline": deepcopy(contract.get("preprocessing_pipeline") or []),
    }
    digest = canonical_contract_hash(payload)
    contract["treatment_manifest_hash"] = digest
    contract["treatment_manifest_id"] = f"tm-{digest[:20]}"


def test_raw_scoring_rows_reproduce_processed_training_treatments_without_mutation():
    meta, contract = _fixture()
    raw = pd.DataFrame(
        {
            "x": [-9.0, 100.0, 20.0, np.nan],
            "z": [-9.0, 100.0, 25.0, 1.0],
            "segment": ["A", " missing ", "B", "A"],
            "target": [0, 1, 0, 1],
        },
        index=[7, 7, 2, 11],
    )
    expected = pd.DataFrame(
        {
            "x": [10.0, 50.0, 20.0, 10.0],
            "z": [-9.0, 50.0, 25.0, 1.0],
            "segment": ["A", "A", "B", "A"],
            "target": [0, 1, 0, 1],
        },
        index=[7, 7, 2, 11],
    )
    original_frame = raw.copy(deep=True)
    original_meta = deepcopy(meta)
    original_contract = deepcopy(contract)

    result = _replay(raw, meta, contract)

    pdt.assert_frame_equal(result["frame"], expected)
    pdt.assert_frame_equal(raw, original_frame)
    assert meta == original_meta
    assert contract == original_contract
    assert list(result["frame"].index) == [7, 7, 2, 11]
    assert result["holdout_accessed"] is False
    assert result["state_mutated"] is False
    assert result["applied_special_value_treatments"][0] == {
        "feature": "x",
        "policy": "convert_to_missing",
        "changed": 1,
    }
    assert result["applied_outlier_treatments"][0]["changed"] == 1
    assert result["applied_missing_treatments"][0]["filled"] == 2


def test_tampered_cutoff_fails_hash_verification_before_transforming_rows():
    meta, contract = _fixture()
    raw = pd.DataFrame({"x": [100.0], "z": [100.0], "segment": ["A"]})
    original = raw.copy(deep=True)
    meta["outlier_application"]["treatments"][0]["upper_threshold"] = 80.0

    with pytest.raises(GovernedTreatmentReplayError) as error:
        _replay(raw, meta, contract)

    assert error.value.code == "treatment_manifest_hash_mismatch"
    pdt.assert_frame_equal(raw, original)


def test_missing_frozen_treatment_manifest_fails_closed():
    meta, contract = _fixture()
    contract.pop("treatment_manifest_hash")

    with pytest.raises(GovernedTreatmentReplayError) as error:
        _replay(pd.DataFrame({"x": [1.0], "z": [2.0], "segment": ["A"]}), meta, contract)

    assert error.value.code == "treatment_manifest_missing"
    assert "treatment_manifest_hash" in str(error.value)


@pytest.mark.parametrize(
    ("mutator", "expected_fragment"),
    [
        (lambda meta, contract: contract.__setitem__("project_id", "other-project"), "project_id"),
        (
            lambda meta, contract: meta["missing_application"].__setitem__(
                "dataset_version_id", "other-version"
            ),
            "dataset_version_id",
        ),
    ],
)
def test_exact_candidate_and_application_identity_mismatches_fail_closed(
    mutator, expected_fragment
):
    meta, contract = _fixture()
    mutator(meta, contract)

    with pytest.raises(GovernedTreatmentReplayError) as error:
        _replay(pd.DataFrame({"x": [1.0], "z": [2.0], "segment": ["A"]}), meta, contract)

    assert error.value.code == "treatment_identity_mismatch"
    assert expected_fragment in str(error.value)


def test_confirmed_mutating_special_review_without_hash_bound_values_fails_closed():
    meta, contract = _fixture()
    contract["preprocessing_pipeline"] = []
    _rehash(meta, contract)

    with pytest.raises(GovernedTreatmentReplayError) as error:
        _replay(pd.DataFrame({"x": [-9.0], "z": [1.0], "segment": ["A"]}), meta, contract)

    assert error.value.code == "special_value_treatment_not_executable"
    assert "exact values" in str(error.value) or "value-level" in str(error.value)


def test_missing_fill_without_realized_value_fails_closed_even_when_hash_is_current():
    meta, contract = _fixture()
    meta["missing_application"]["treatments"][0].pop("value")
    _rehash(meta, contract)

    with pytest.raises(GovernedTreatmentReplayError) as error:
        _replay(
            pd.DataFrame({"x": [np.nan, 2.0], "z": [1.0, 2.0], "segment": ["A", "B"]}),
            meta,
            contract,
        )

    assert error.value.code == "missing_treatment_not_executable"
    assert "realized fill value" in str(error.value)


def test_replay_never_reads_dataset_splits_or_holdout(monkeypatch):
    meta, contract = _fixture()

    def forbidden_holdout_access(*_args, **_kwargs):
        raise AssertionError("Treatment replay accessed DatasetStore splits or holdout.")

    monkeypatch.setattr(DATASTORE, "get_splits", forbidden_holdout_access)
    result = _replay(
        pd.DataFrame({"x": [1.0], "z": [2.0], "segment": ["A"]}),
        meta,
        contract,
    )

    assert result["holdout_accessed"] is False
    assert result["row_count"] == 1
