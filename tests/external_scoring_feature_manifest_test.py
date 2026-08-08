from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd

from server.evaluation import eval_service
from server.features.feature_service import materialize_external_scoring_frame


PROJECT_ID = "project-scoring-contract"
DATASET_ID = "dataset-scoring-contract"
VERSION_ID = "version-scoring-contract"
MANIFEST_HASH = "fm-scoring-contract"


def _manifest() -> dict:
    def row(name: str, origin: str, sources: list[str], config: dict) -> dict:
        return {
            "feature_name": name,
            "origin": origin,
            "source_features": sources,
            "config": config,
            "selected": True,
            "eligibility_status": "eligible",
        }

    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "manifest_hash": MANIFEST_HASH,
        "confirmation_status": "confirmed",
        "confirmed_manifest_hash": MANIFEST_HASH,
        "materialization_status": "current",
        "materialized_manifest_hash": MANIFEST_HASH,
        "features": [
            row("age_years", "original", ["age_years"], {}),
            row("annual_income", "original", ["annual_income"], {}),
            row("income_correlated", "original", ["income_correlated"], {}),
            row("utilization_pct", "original", ["utilization_pct"], {}),
            row("recent_trade_count", "original", ["recent_trade_count"], {}),
            row("application_date", "original", ["application_date"], {}),
            row(
                "age_income_interaction",
                "interaction",
                ["age_years", "annual_income"],
                {"preserve_bureau_special_values": True},
            ),
            row(
                "income_band",
                "numeric_bin",
                ["annual_income"],
                {
                    "binning_mode": "custom",
                    "cut_points": [40000, 70000],
                    "labels": ["Low", "Medium", "High"],
                    "special_value_label": "Bureau special",
                    "missing_label": "Missing",
                },
            ),
            row(
                "high_utilization_band",
                "categorical_rule",
                ["utilization_pct"],
                {
                    "else_label": "Standard",
                    "rules": [
                        {
                            "op": "greater_than",
                            "value": 80,
                            "then_label": "High",
                        }
                    ],
                    "special_value_label": "Bureau special",
                },
            ),
            row(
                "recent_trade_count_squared",
                "polynomial",
                ["recent_trade_count"],
                {"degree": 2},
            ),
            row(
                "income_pair_product",
                "arithmetic",
                ["annual_income", "income_correlated"],
                {"operation": "multiply"},
            ),
            row(
                "application_month",
                "date-derived",
                ["application_date"],
                {"component": "month"},
            ),
        ],
    }


MODEL_FEATURES = [
    "age_years",
    "annual_income",
    "income_correlated",
    "utilization_pct",
    "recent_trade_count",
    "application_date",
    "age_income_interaction",
    "income_band",
    "high_utilization_band",
    "recent_trade_count_squared",
    "income_pair_product",
    "application_month",
]


def _raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age_years": [30, 50],
            "annual_income": [35000, 90000],
            "income_correlated": [34000, 88000],
            "utilization_pct": [45, 92],
            "recent_trade_count": [3, 7],
            "application_date": ["2026-02-15", "2026-11-03"],
            "bad_flag": [0, 1],
        }
    )


def _materialize(frame: pd.DataFrame) -> dict:
    return materialize_external_scoring_frame(
        frame,
        _manifest(),
        model_features=MODEL_FEATURES,
        expected_project_id=PROJECT_ID,
        expected_dataset_id=DATASET_ID,
        expected_dataset_version_id=VERSION_ID,
        expected_manifest_hash=MANIFEST_HASH,
    )


def test_external_raw_frame_reapplies_all_exact_training_definitions_without_mutation() -> None:
    raw = _raw_frame().drop(columns=["bad_flag"])
    raw["age_income_interaction"] = [-1, -1]
    raw["unknown_upload_column"] = ["ignored", "ignored"]
    before = raw.copy(deep=True)

    result = _materialize(raw)
    transformed = result["frame"]

    pd.testing.assert_frame_equal(raw, before)
    assert transformed["age_income_interaction"].tolist() == [1_050_000, 4_500_000]
    assert transformed["income_band"].astype(str).tolist() == ["Low", "High"]
    assert transformed["high_utilization_band"].tolist() == ["Standard", "High"]
    assert transformed["recent_trade_count_squared"].tolist() == [9, 49]
    assert transformed["income_pair_product"].tolist() == [1_190_000_000, 7_920_000_000]
    assert transformed["application_month"].tolist() == [2, 11]
    assert transformed.columns.tolist() == MODEL_FEATURES
    assert "unknown_upload_column" not in transformed.columns
    assert result["applied_engineered_features"] == MODEL_FEATURES[6:]
    assert result["holdout_accessed"] is False
    assert result["state_mutated"] is False


def test_external_scoring_fails_closed_on_stale_manifest_and_missing_raw_source() -> None:
    raw = _raw_frame().drop(columns=["bad_flag"])
    stale = _manifest()
    stale["manifest_hash"] = "fm-another-contract"
    try:
        materialize_external_scoring_frame(
            raw,
            stale,
            model_features=MODEL_FEATURES,
            expected_project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            expected_manifest_hash=MANIFEST_HASH,
        )
    except ValueError as exc:
        assert "exact training manifest" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("A stale manifest must fail closed.")

    try:
        _materialize(raw.drop(columns=["annual_income"]))
    except ValueError as exc:
        assert "required raw source 'annual_income' is missing" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("A missing governed source must fail closed.")

    try:
        materialize_external_scoring_frame(
            raw,
            _manifest(),
            model_features=[*MODEL_FEATURES, "unregistered_engineered_upload"],
            expected_project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            expected_manifest_hash=MANIFEST_HASH,
        )
    except ValueError as exc:
        assert "does not define final-model features" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("A model feature absent from its exact manifest must fail closed.")


def test_quantile_bins_reuse_frozen_training_cuts_across_shifted_populations() -> None:
    manifest = _manifest()
    quantile = next(
        row for row in manifest["features"] if row["feature_name"] == "income_band"
    )
    quantile["config"] = {
        "binning_mode": "quantile",
        "quantiles": [0.33, 0.67],
        "labels": ["Low", "Medium", "High"],
    }
    quantile["materialization_parameters"] = {
        "fitted_cut_points": [10.0, 20.0],
        "fit_scope": "full_governed_population_target_independent",
        "fit_row_count": 100,
        "source_feature": "annual_income",
    }

    common = {
        "age_years": 40,
        "income_correlated": 15,
        "utilization_pct": 50,
        "recent_trade_count": 4,
        "application_date": "2026-06-01",
    }
    population_a = pd.DataFrame(
        [{**common, "annual_income": value} for value in [1, 2, 15, 16]]
    )
    population_b = pd.DataFrame(
        [{**common, "annual_income": value} for value in [15, 100, 200, 300]]
    )

    def replay(frame: pd.DataFrame) -> pd.DataFrame:
        return materialize_external_scoring_frame(
            frame,
            manifest,
            model_features=MODEL_FEATURES,
            expected_project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            expected_manifest_hash=MANIFEST_HASH,
        )["frame"]

    scored_a = replay(population_a)
    scored_b = replay(population_b)
    assert str(scored_a.loc[2, "income_band"]) == "Medium"
    assert str(scored_b.loc[0, "income_band"]) == "Medium"

    del quantile["materialization_parameters"]
    try:
        replay(population_a)
    except ValueError as exc:
        assert "frozen training cut points are unavailable" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Quantile scoring without frozen training cuts must fail closed.")


def test_engineered_dependencies_are_topologically_replayed_and_case_collisions_block() -> None:
    manifest = _manifest()
    downstream = {
        "feature_name": "interaction_squared",
        "origin": "polynomial",
        "source_features": ["age_income_interaction"],
        "config": {"degree": 2},
        "selected": True,
        "eligibility_status": "eligible",
    }
    # Place the dependency consumer before its producer to prove replay is not
    # accidentally dependent on display/persistence ordering.
    producer_index = next(
        index
        for index, row in enumerate(manifest["features"])
        if row["feature_name"] == "age_income_interaction"
    )
    manifest["features"].insert(producer_index, downstream)
    features = ["interaction_squared", "age_income_interaction"]
    transformed = materialize_external_scoring_frame(
        _raw_frame().drop(columns=["bad_flag"]),
        manifest,
        model_features=features,
        expected_project_id=PROJECT_ID,
        expected_dataset_id=DATASET_ID,
        expected_dataset_version_id=VERSION_ID,
        expected_manifest_hash=MANIFEST_HASH,
    )["frame"]
    assert transformed.columns.tolist() == features
    assert transformed["interaction_squared"].tolist() == [1_102_500_000_000, 20_250_000_000_000]

    collision = _raw_frame().drop(columns=["annual_income", "bad_flag"])
    collision["Annual_Income"] = [35000, 90000]
    collision["ANNUAL_INCOME"] = [35000, 90000]
    try:
        _materialize(collision)
    except ValueError as exc:
        assert "duplicate case-insensitive source columns" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Ambiguous case-insensitive sources must fail closed.")


class _AssertingPipeline:
    calls = 0

    @classmethod
    def predict_proba(cls, frame: pd.DataFrame) -> np.ndarray:
        cls.calls += 1
        assert frame.columns.tolist() == MODEL_FEATURES
        assert frame["age_income_interaction"].tolist() == [1_050_000, 4_500_000]
        assert frame["application_month"].tolist() == [2, 11]
        probabilities = np.asarray([0.2, 0.8], dtype=float)
        return np.column_stack((1.0 - probabilities, probabilities))


def _metadata() -> dict:
    return {
        "model_key": "pipeline",
        "name": "Exact governed pipeline",
        "features": MODEL_FEATURES,
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "feature_manifest_version": MANIFEST_HASH,
        "target": "bad_flag",
    }


def _patch_scoring(monkeypatch, *, train_reference: pd.DataFrame | None) -> None:
    class _Store:
        target = "bad_flag"
        meta = {"feature_manifest": _manifest()}
        X_train = train_reference

        @classmethod
        def current(cls):
            return cls

        @staticmethod
        def get_splits():
            raise AssertionError("External TEST/OOT scoring must not read the sealed holdout tuple.")

    monkeypatch.setattr(
        eval_service.EVAL,
        "_resolve_scoring_model",
        lambda _name: (_AssertingPipeline(), _metadata()),
    )
    monkeypatch.setattr(eval_service.EVAL, "_is_regression_problem", lambda: False)
    monkeypatch.setattr(
        eval_service.EVAL,
        "_default_priors",
        lambda: {
            "original_prior": 0.5,
            "model_prior": 0.5,
            "split_config": {},
            "train_rows": 2,
        },
    )
    monkeypatch.setattr(eval_service, "DATASTORE", _Store)


def test_score_dataset_reapplies_manifest_before_predict_and_reports_lineage(monkeypatch) -> None:
    transformed_reference = _materialize(
        _raw_frame().drop(columns=["bad_flag"])
    )["frame"]
    _patch_scoring(monkeypatch, train_reference=transformed_reference)
    _AssertingPipeline.calls = 0

    uploaded = _raw_frame()
    uploaded["age_income_interaction"] = [-999, -999]
    result = eval_service.EVAL.score_dataset(uploaded, dataset_type="oot")

    assert result["ok"] is True
    assert _AssertingPipeline.calls == 2  # uploaded population + development reference
    diagnostics = result["scoring_diagnostics"]
    assert diagnostics["feature_manifest_status"] == "reapplied"
    assert diagnostics["feature_manifest_version"] == MANIFEST_HASH
    assert diagnostics["applied_engineered_features"] == MODEL_FEATURES[6:]
    assert diagnostics["holdout_accessed_for_feature_materialization"] is False
    assert diagnostics["feature_manifest_replay_scope"] == "engineered_features_only"
    assert diagnostics["upstream_treatment_replay_status"] == "not_verified_by_this_boundary"


def test_score_dataset_missing_source_blocks_before_prediction(monkeypatch) -> None:
    _patch_scoring(monkeypatch, train_reference=None)
    _AssertingPipeline.calls = 0

    result = eval_service.EVAL.score_dataset(
        _raw_frame().drop(columns=["annual_income"]),
        dataset_type="oot",
    )

    assert result["ok"] is False
    assert result["feature_manifest_status"] == "blocked"
    assert "required raw source 'annual_income' is missing" in result["error"]
    assert result["holdout_accessed"] is False
    assert _AssertingPipeline.calls == 0


def test_external_stability_never_falls_back_to_final_holdout(monkeypatch) -> None:
    _patch_scoring(monkeypatch, train_reference=None)
    _AssertingPipeline.calls = 0

    result = eval_service.EVAL.score_dataset(_raw_frame(), dataset_type="oot")

    assert result["ok"] is True
    assert result.get("psi") is None
    assert result.get("vsi") is None
    assert _AssertingPipeline.calls == 1
