from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from server.sports_gold import recent_state_charts as Charts
from server.sports_gold import recent_state_components as Components
from server.sports_gold import recent_state_ensemble as Ensembles
from server.sports_gold import recent_state_study as Study
from server.sports_gold.contracts import GOLD_FEATURES
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix


def _state_fixture() -> tuple[pd.DataFrame, np.ndarray, pd.DataFrame, np.ndarray]:
    """Small, deterministic history with six-plus distinct role profiles."""

    training_rows: list[dict[str, object]] = []
    for repetition in range(12):
        day = pd.Timestamp("2022-01-01") + pd.Timedelta(days=repetition)
        for player_index in range(12):
            outcome_index = (
                player_index + repetition % ((player_index % 4) + 1)
            ) % len(PA_CLASS_ORDER)
            training_rows.append(
                {
                    "game_date": day,
                    "outcome": PA_CLASS_ORDER[outcome_index],
                    "batterCanonicalPlayerId": f"b{player_index}",
                    "pitcherCanonicalPlayerId": f"p{(player_index * 5) % 12}",
                    "plate_appearance_id": f"train-{repetition}-{player_index}",
                }
            )
    training = pd.DataFrame(training_rows)
    training_direct = validate_probability_matrix(
        np.full((len(training), len(PA_CLASS_ORDER)), 1.0 / len(PA_CLASS_ORDER))
    )

    target = pd.DataFrame(
        {
            "game_date": [pd.Timestamp("2022-02-01")] * 3,
            "outcome": ["STRIKEOUT", "BIP_OUT", "SINGLE"],
            "batterCanonicalPlayerId": ["b0", "b0", "unseen-batter"],
            "pitcherCanonicalPlayerId": ["p0", "p0", "unseen-pitcher"],
            "plate_appearance_id": ["target-1", "target-2", "target-3"],
        }
    )
    target_direct = validate_probability_matrix(
        np.asarray(
            [
                [0.20, 0.12, 0.08, 0.16, 0.10, 0.04, 0.22, 0.08],
                [0.18, 0.13, 0.09, 0.15, 0.11, 0.04, 0.22, 0.08],
                [0.16, 0.14, 0.08, 0.18, 0.10, 0.04, 0.20, 0.10],
            ],
            dtype=np.float64,
        )
    )
    return training, training_direct, target, target_direct


def _ensemble_fixture(
    rows: int = 80,
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, dict[str, np.ndarray]]]:
    encoded = np.arange(rows, dtype=np.int64) % len(PA_CLASS_ORDER)
    labels = np.asarray(PA_CLASS_ORDER, dtype=object)[encoded]
    probabilities: dict[str, np.ndarray] = {}
    reliability: dict[str, dict[str, np.ndarray]] = {}
    row_index = np.arange(rows, dtype=np.int64)
    for component_index, component in enumerate(Ensembles.COMPONENT_ORDER):
        matrix = np.full((rows, len(PA_CLASS_ORDER)), 0.03, dtype=np.float64)
        skill = 0.42 - 0.02 * component_index
        matrix[np.arange(rows), encoded] += skill
        distractor = (encoded + component_index + 1) % len(PA_CLASS_ORDER)
        matrix[np.arange(rows), distractor] += 0.015 * (component_index + 1)
        probabilities[component] = validate_probability_matrix(
            matrix / matrix.sum(axis=1, keepdims=True)
        )
        if component != Ensembles.DIRECT_MODEL:
            count = ((row_index + 3 * component_index) % 19 + 1).astype(np.float64)
            missing = (row_index + component_index) % 17 == 0
            reliability[component] = {
                "observationCount": count,
                "effectiveSampleSize": 0.75 * count,
                "missingHistoryFlag": missing,
                "daysSincePriorAppearance": np.where(
                    missing, np.nan, 1.0 + row_index % 31
                ),
                "entropy": np.full(rows, 1.4 + 0.01 * component_index),
                "deviationFromLongTerm": (
                    (row_index % 7) / 20.0 + 0.005 * component_index
                ),
            }
    return labels, probabilities, reliability


def _chart_results() -> dict[str, object]:
    candidates = [
        {
            "candidate": "DIRECT_MODEL",
            "logLoss": 1.48,
            "components": ["DIRECT_MODEL"],
        },
        {
            "candidate": "E1",
            "logLoss": 1.47,
            "components": ["DIRECT_MODEL", "RECENT_14_DAY_STATE"],
        },
        {
            "candidate": "E2",
            "logLoss": 1.465,
            "components": [
                "DIRECT_MODEL",
                "RECENT_14_DAY_STATE",
                "RECENT_42_DAY_STATE",
            ],
        },
        {
            "candidate": "E3",
            "logLoss": 1.462,
            "components": [
                "DIRECT_MODEL",
                "LONG_TERM_STATE",
                "RECENT_14_DAY_STATE",
                "RECENT_42_DAY_STATE",
            ],
        },
        {
            "candidate": "E10",
            "logLoss": 1.455,
            "components": list(Ensembles.COMPONENT_ORDER),
        },
    ]
    months = ("2024-04", "2024-05")
    monthly = [
        {
            "month": month,
            "candidate": candidate,
            "logLoss": 1.48 - 0.004 * candidate_index + 0.002 * month_index,
        }
        for month_index, month in enumerate(months)
        for candidate_index, candidate in enumerate(
            ("DIRECT_MODEL", "E1", "E2", "E3", "E10")
        )
    ]
    return {
        "direct2024LogLoss": 1.48,
        "candidate2024": candidates,
        "topFourCandidates": ["E1", "E2", "E3", "E10"],
        "bestCandidate": "E10",
        "monthly2024": monthly,
        "calibration2024": {
            "directCandidate": "DIRECT_MODEL",
            "bestCandidate": "E10",
            "curves": {
                "DIRECT_MODEL": [
                    {"meanConfidence": 0.2, "observedAccuracy": 0.19, "count": 50},
                    {"meanConfidence": 0.5, "observedAccuracy": 0.47, "count": 50},
                ],
                "E10": [
                    {"meanConfidence": 0.2, "observedAccuracy": 0.20, "count": 50},
                    {"meanConfidence": 0.5, "observedAccuracy": 0.49, "count": 50},
                ],
            },
        },
        "ensembleWeights": {
            "optimizedStatic": {"DIRECT_MODEL": 0.7, "RECENT_14_DAY_STATE": 0.3},
            "averageGated": {"DIRECT_MODEL": 0.6, "RECENT_14_DAY_STATE": 0.4},
        },
        "disagreement2024": [
            {
                "bin": "LOW",
                "directLogLoss": 1.46,
                "bestLogLoss": 1.45,
                "count": 60,
            },
            {
                "bin": "HIGH",
                "directLogLoss": 1.52,
                "bestLogLoss": 1.47,
                "count": 40,
            },
        ],
    }


def test_fixed_rolling_origin_folds_are_exact_and_reject_2024() -> None:
    folds = Ensembles.rolling_origin_folds()
    assert [fold.record() for fold in folds] == [
        {
            "foldId": "FOLD_1",
            "trainRule": "game_date <= 2022-04-30",
            "trainEnd": "2022-04-30",
            "validationStart": "2022-05-01",
            "validationEnd": "2022-06-30",
            "uses2024": False,
        },
        {
            "foldId": "FOLD_2",
            "trainRule": "game_date <= 2022-06-30",
            "trainEnd": "2022-06-30",
            "validationStart": "2022-07-01",
            "validationEnd": "2022-08-31",
            "uses2024": False,
        },
        {
            "foldId": "FOLD_3",
            "trainRule": "game_date <= 2022-08-31",
            "trainEnd": "2022-08-31",
            "validationStart": "2022-09-01",
            "validationEnd": "2022-12-31",
            "uses2024": False,
        },
        {
            "foldId": "FOLD_4",
            "trainRule": "game_date <= 2023-04-30",
            "trainEnd": "2023-04-30",
            "validationStart": "2023-05-01",
            "validationEnd": "2023-06-30",
            "uses2024": False,
        },
        {
            "foldId": "FOLD_5",
            "trainRule": "game_date <= 2023-06-30",
            "trainEnd": "2023-06-30",
            "validationStart": "2023-07-01",
            "validationEnd": "2023-08-31",
            "uses2024": False,
        },
        {
            "foldId": "FOLD_6",
            "trainRule": "game_date <= 2023-08-31",
            "trainEnd": "2023-08-31",
            "validationStart": "2023-09-01",
            "validationEnd": "2023-12-31",
            "uses2024": False,
        },
    ]
    dates = pd.to_datetime(
        [
            "2021-01-01",
            "2022-05-01",
            "2022-07-01",
            "2022-09-01",
            "2023-05-01",
            "2023-07-01",
            "2023-09-01",
        ]
    )
    masks = Ensembles.rolling_origin_fold_masks(dates)
    assert len(masks) == 6
    assert all(not (training & validation).any() for _, training, validation in masks)
    assert all(
        dates[training].max() < dates[validation].min()
        for _, training, validation in masks
    )
    with pytest.raises(Ensembles.RecentStateEnsembleError, match="2021--2023 only"):
        Ensembles.rolling_origin_fold_masks(pd.to_datetime(["2021-01-01", "2024-01-01"]))


def test_state_scoring_is_strictly_prior_and_excludes_same_day_rows() -> None:
    training, training_direct, target, target_direct = _state_fixture()
    authority = Components.fit_state_authority(training, training_direct)
    bundle = Components.score_state_components(authority, target, target_direct)

    exact = bundle.components[Components.SHRUNK_EXACT_BVP]
    assert exact.observation_count[:2].tolist() == [12.0, 12.0]
    assert np.array_equal(exact.probabilities[0], exact.probabilities[1])
    assert np.all(
        exact.days_since_prior_appearance[np.isfinite(exact.days_since_prior_appearance)]
        >= 1.0
    )

    same_day = target.copy()
    same_day["game_date"] = pd.Timestamp(authority.training_end_day)
    with pytest.raises(
        Components.RecentStateComponentError,
        match="not strictly earlier than the complete target block",
    ):
        Components.score_state_components(authority, same_day, target_direct)


def test_all_nine_component_and_reliability_contracts_are_probability_safe() -> None:
    training, training_direct, target, target_direct = _state_fixture()
    authority = Components.fit_state_authority(training, training_direct)
    bundle = Components.score_state_components(authority, target, target_direct)

    assert tuple(bundle.probability_matrices) == Components.COMPONENT_ORDER
    assert tuple(bundle.components) == Components.COMPONENT_ORDER
    assert tuple(bundle.reliability) == Components.EMPIRICAL_COMPONENT_ORDER
    assert bundle.class_order == PA_CLASS_ORDER
    assert bundle.row_ids == ("target-1", "target-2", "target-3")
    for name, component in bundle.components.items():
        matrix = component.probabilities
        assert matrix.shape == (3, len(PA_CLASS_ORDER)), name
        assert np.isfinite(matrix).all(), name
        assert np.all(matrix >= 0.0), name
        assert np.allclose(matrix.sum(axis=1), 1.0, rtol=0.0, atol=1e-12), name
        assert np.all(
            component.effective_sample_size <= component.observation_count + 1e-10
        ), name
        finite_days = component.days_since_prior_appearance[
            np.isfinite(component.days_since_prior_appearance)
        ]
        assert np.all(finite_days >= 1.0), name
    for fields in bundle.reliability.values():
        assert tuple(fields) == (
            "observationCount",
            "effectiveSampleSize",
            "missingHistoryFlag",
            "daysSincePriorAppearance",
            "entropy",
            "deviationFromLongTerm",
        )
        assert all(np.asarray(value).shape == (3,) for value in fields.values())


def test_soft_cluster_and_exact_bvp_use_the_frozen_shrinkage_contract() -> None:
    training, training_direct, target, target_direct = _state_fixture()
    authority = Components.fit_state_authority(training, training_direct)
    bundle = Components.score_state_components(authority, target, target_direct)
    cluster = bundle.components[Components.CLUSTER_MATCHUP]
    exact = bundle.components[Components.SHRUNK_EXACT_BVP]

    batter_membership = cluster.role_diagnostics["batter_memberships"]
    pitcher_membership = cluster.role_diagnostics["pitcher_memberships"]
    assert batter_membership.shape == pitcher_membership.shape == (3, 6)
    assert np.allclose(batter_membership.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)
    assert np.allclose(pitcher_membership.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)
    assert np.all(batter_membership > 0.0)
    assert np.all(pitcher_membership > 0.0)
    manual_cluster = np.einsum(
        "ni,nj,ijk->nk",
        batter_membership,
        pitcher_membership,
        authority.cluster_matchup_probabilities,
        optimize=True,
    )
    manual_cluster /= manual_cluster.sum(axis=1, keepdims=True)
    assert np.allclose(cluster.probabilities, manual_cluster, rtol=0.0, atol=1e-12)

    pair_labels = authority._pair_history[("b0", "p0")].labels
    pair_counts = np.bincount(pair_labels, minlength=len(PA_CLASS_ORDER)).astype(float)
    expected = (pair_counts + 50.0 * cluster.probabilities[0]) / (
        len(pair_labels) + 50.0
    )
    assert authority.config.exact_bvp_prior_strength == 50.0
    assert exact.role_diagnostics["exact_pair_weight"][0] == pytest.approx(12.0 / 62.0)
    assert np.allclose(exact.probabilities[0], expected, rtol=0.0, atol=1e-12)
    assert np.allclose(
        exact.probabilities[2], cluster.probabilities[2], rtol=0.0, atol=1e-15
    )


def test_fixed_e1_through_e8_definitions_and_predictions_are_exact() -> None:
    _, probabilities, _ = _ensemble_fixture(rows=16)
    definitions = Ensembles.fixed_ensemble_definitions()
    assert tuple(definitions) == tuple(f"E{index}" for index in range(1, 9))
    assert {
        ensemble_id: tuple(record["memberIds"])
        for ensemble_id, record in definitions.items()
    } == dict(Ensembles.FIXED_ENSEMBLE_MEMBERS)
    predictions = Ensembles.build_fixed_ensembles(probabilities)
    assert tuple(predictions) == tuple(definitions)
    for ensemble_id, members in Ensembles.FIXED_ENSEMBLE_MEMBERS.items():
        expected = np.mean(
            np.stack([probabilities[name] for name in members], axis=0), axis=0
        )
        assert np.allclose(predictions[ensemble_id], expected, rtol=0.0, atol=1e-15)
        assert sum(definitions[ensemble_id]["weights"].values()) == pytest.approx(1.0)


def test_e9_is_a_static_nonnegative_convex_oof_blend() -> None:
    labels, probabilities, _ = _ensemble_fixture()
    fitted = Ensembles.fit_convex_blend(labels, probabilities)
    weights = np.asarray(fitted.weights)
    prediction = fitted.predict_proba(probabilities)
    assert fitted.component_ids == Ensembles.COMPONENT_ORDER
    assert np.all(weights >= 0.0)
    assert weights.sum() == pytest.approx(1.0, abs=1e-10)
    assert np.allclose(prediction.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)
    assert fitted.record()["uses2024"] is False
    assert fitted.record()["fitPopulation"] == "DEVELOPMENT_ROLLING_ORIGIN_OOF_ONLY"


def test_e10_feature_contract_and_regularized_multinomial_fit_are_fixed() -> None:
    labels, probabilities, reliability = _ensemble_fixture()
    features, names = Ensembles.build_stacker_features(probabilities, reliability)
    assert features.shape == (len(labels), 152)
    assert len(names) == len(set(names)) == 152
    assert names[: len(PA_CLASS_ORDER)] == tuple(
        f"DIRECT_MODEL__log_probability__{name}" for name in PA_CLASS_ORDER
    )
    assert np.isfinite(features).all()

    fitted = Ensembles.fit_reliability_gated_stacker(
        labels, probabilities, reliability
    )
    prediction = fitted.predict_proba(probabilities, reliability)
    record = fitted.record()
    assert fitted.feature_names == names
    assert prediction.shape == (len(labels), len(PA_CLASS_ORDER))
    assert np.allclose(prediction.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)
    assert record["configuration"] == dict(Ensembles.STACKER_CONFIG)
    assert record["uses2024"] is False
    assert record["featureCount"] == 152


def test_compact_bootstrap_is_seeded_and_resamples_whole_games() -> None:
    labels, probabilities, _ = _ensemble_fixture(rows=32)
    direct = probabilities[Ensembles.DIRECT_MODEL]
    selected = direct.copy()
    encoded = np.arange(32) % len(PA_CLASS_ORDER)
    selected[np.arange(32), encoded] += 0.02
    selected /= selected.sum(axis=1, keepdims=True)
    games = np.asarray([f"game-{row // 4}" for row in range(32)], dtype=object)
    first = Ensembles.compact_game_bootstrap(
        labels, selected, direct, games, n_resamples=50, seed=73
    )
    second = Ensembles.compact_game_bootstrap(
        labels, selected, direct, games, n_resamples=50, seed=73
    )
    permutation = np.random.default_rng(9).permutation(len(labels))
    permuted = Ensembles.compact_game_bootstrap(
        labels[permutation],
        selected[permutation],
        direct[permutation],
        games[permutation],
        n_resamples=50,
        seed=73,
    )
    assert first == second == permuted
    assert first["resamplingUnit"] == "game_id"
    assert first["rowsSampledIndependently"] is False
    assert first["gameCount"] == 8
    assert first["resampleCount"] == 50


def test_history_direct_crossfit_scores_every_row_without_splitting_games(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game_ids_by_fold: dict[int, list[str]] = {0: [], 1: []}
    candidate = 0
    while min(len(values) for values in game_ids_by_fold.values()) < 4:
        game_id = f"synthetic-game-{candidate}"
        assignment = hashlib.sha256(game_id.encode("utf-8")).digest()[0] & 1
        if len(game_ids_by_fold[assignment]) < 4:
            game_ids_by_fold[assignment].append(game_id)
        candidate += 1

    rows: list[dict[str, object]] = []
    ordered_games = game_ids_by_fold[0] + game_ids_by_fold[1]
    categorical = {
        "context_top_bottom",
        "context_outs_before",
        "context_base_mask_before",
    }
    for game_index, game_id in enumerate(ordered_games):
        for class_index, outcome in enumerate(PA_CLASS_ORDER):
            row: dict[str, object] = {"game_id": game_id, "outcome": outcome}
            for feature_index, feature in enumerate(GOLD_FEATURES):
                if feature == "context_top_bottom":
                    value = class_index % 2
                elif feature == "context_outs_before":
                    value = class_index % 3
                elif feature == "context_base_mask_before":
                    value = class_index % 8
                else:
                    value = (
                        (game_index + 1) * (feature_index + 3) + 2 * class_index
                    ) % 17 / 10.0
                row[feature] = int(value) if feature in categorical else float(value)
            rows.append(row)
    frame = pd.DataFrame(rows)
    training_mask = np.ones(len(frame), dtype=np.bool_)

    observed_fit_masks: list[np.ndarray] = []
    original_fit = Study._fit_fold_direct

    def tracked_fit(
        fit_frame: pd.DataFrame, fit_mask: np.ndarray
    ) -> tuple[object, dict[str, object]]:
        observed_fit_masks.append(fit_mask.copy())
        return original_fit(fit_frame, fit_mask)

    monkeypatch.setattr(Study, "_fit_fold_direct", tracked_fit)
    combined, records, artifacts = Study._cross_fitted_history_direct(
        frame, training_mask
    )

    assert len(observed_fit_masks) == len(records) == len(artifacts) == 2
    assert sum(int(record["heldOutRows"]) for record in records) == len(frame)
    held_out_count = np.zeros(len(frame), dtype=np.int8)
    games = frame["game_id"].to_numpy(dtype=object)
    for held_out_fold, fit_mask in enumerate(observed_fit_masks):
        held_out = training_mask & ~fit_mask
        held_out_count += held_out.astype(np.int8)
        assert set(games[fit_mask]).isdisjoint(set(games[held_out]))
        assert records[held_out_fold]["assignmentUnit"] == "game_id"
        assert records[held_out_fold]["fitRows"] == int(fit_mask.sum())
        assert records[held_out_fold]["heldOutRows"] == int(held_out.sum())

        fold_probabilities = artifacts[
            f"history-crossfit-{held_out_fold}"
        ].predict_proba(frame.loc[held_out].reset_index(drop=True))
        assert fold_probabilities.shape == (int(held_out.sum()), len(PA_CLASS_ORDER))
        validate_probability_matrix(fold_probabilities, class_order=PA_CLASS_ORDER)
        assert np.allclose(
            combined[held_out], fold_probabilities, rtol=0.0, atol=1e-15
        )

    assert np.array_equal(held_out_count, np.ones(len(frame), dtype=np.int8))
    assert combined.shape == (len(frame), len(PA_CLASS_ORDER))
    validate_probability_matrix(combined, class_order=PA_CLASS_ORDER)


def test_all_six_review_charts_are_complete_and_byte_deterministic(tmp_path: Path) -> None:
    results = _chart_results()
    first = Charts.generate_review_charts(
        results, tmp_path / "first", include_svg=True, dpi=72
    )
    second = Charts.generate_review_charts(
        results, tmp_path / "second", include_svg=True, dpi=72
    )
    assert len(first) == len(second) == 6
    assert [row["chartId"] for row in first] == [
        "01_2024_log_loss_improvement",
        "02_candidate_component_heatmap",
        "03_monthly_stability",
        "04_calibration_reliability",
        "05_ensemble_weights",
        "06_disagreement_performance",
    ]
    for first_chart, second_chart in zip(first, second, strict=True):
        assert [item["format"] for item in first_chart["files"]] == ["png", "svg"]
        assert [item["sha256"] for item in first_chart["files"]] == [
            item["sha256"] for item in second_chart["files"]
        ]
        assert all(Path(item["path"]).is_file() for item in first_chart["files"])
        assert all(item["bytes"] > 0 for item in first_chart["files"])
