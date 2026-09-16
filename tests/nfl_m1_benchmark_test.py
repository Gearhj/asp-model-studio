from __future__ import annotations

from datetime import date
from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from server.sports_nfl_m1.benchmark import (
    DistributionCandidateResult,
    EnsembleSelection,
    SelectedCandidate,
    _american_probability,
    _atomic_simulation_archive,
    _complete_seasons_from_foundation_manifest,
    _development_frame,
    _load_development_gold,
    _load_temporal_identity_rows,
    _oof_selection_receipt,
    _per_game_distribution_ledger,
    _persist_simulation_bundle,
    _slice_metrics,
    _tilt_simulation,
    bootstrap_comparisons,
    build_oof_ensemble,
    market_comparison_table,
    run_benchmark,
)
from server.sports_nfl_m1.data_authority import FoundationPaths
from server.sports_nfl_m1.distributions import SimulatedScores, reconcile_score_simulation
from server.sports_nfl_m1.temporal import build_temporal_design


def test_american_probability_handles_standard_prices_without_branch_warnings() -> None:
    probability = _american_probability(pd.Series([-110, -100, 100, 130], dtype=float))
    np.testing.assert_allclose(
        probability,
        np.array([110 / 210, 0.5, 0.5, 100 / 230], dtype=float),
    )


def _games() -> pd.DataFrame:
    rows = []
    for season in range(2018, 2026):
        for day in (1, 8):
            rows.append(
                {
                    "canonical_game_id": f"{season}_{day:02d}_AWAY_HOME",
                    "season": season,
                    "game_date": date(season, 9, day),
                    "home_points": 999.0 if season == 2025 else 24.0,
                    "away_points": 998.0 if season == 2025 else 20.0,
                    "home_win": 1,
                }
            )
    return pd.DataFrame(rows)


def _design(frame: pd.DataFrame):
    return build_temporal_design(
        frame.to_dict(orient="records"),
        complete_seasons=tuple(range(2018, 2026)),
    )


def test_development_population_excludes_every_final_oot_identity_and_label() -> None:
    frame = _games()
    design = _design(frame)
    development = _development_frame(frame, design)

    assert development["season"].min() == 2018
    assert development["season"].max() == 2024
    assert len(development) == 14
    assert set(development["canonical_game_id"]).isdisjoint(design.final_oot_game_ids)
    assert 999.0 not in set(development["home_points"])
    assert 998.0 not in set(development["away_points"])


def test_joint_win_mass_tilt_is_finite_nonnegative_reconciled_and_tracks_target() -> None:
    draws = 1_000
    base_home = np.vstack(
        (
            np.tile(np.array([24, 17], dtype=np.int32), draws // 2),
            np.tile(np.array([31, 14], dtype=np.int32), draws // 2),
        )
    )
    base_away = np.vstack(
        (
            np.tile(np.array([17, 24], dtype=np.int32), draws // 2),
            np.tile(np.array([14, 31], dtype=np.int32), draws // 2),
        )
    )
    base = SimulatedScores(
        home=base_home,
        away=base_away,
        predicted_home_mean=base_home.mean(axis=1),
        predicted_away_mean=base_away.mean(axis=1),
        residual_authority_sha256="a" * 64,
        seed=123,
    )
    targets = np.array([0.731, 0.269], dtype=float)

    tilted = _tilt_simulation(base, targets, seed=456)
    reconciliation = reconcile_score_simulation(tilted)
    realized = np.mean(tilted.home > tilted.away, axis=1)

    assert reconciliation["finite"] is True
    assert reconciliation["nonnegative"] is True
    assert reconciliation["minimumJointMass"] == 1.0
    assert reconciliation["maximumJointMass"] == 1.0
    assert np.isfinite(tilted.home).all() and np.isfinite(tilted.away).all()
    assert np.all(tilted.home >= 0) and np.all(tilted.away >= 0)
    np.testing.assert_allclose(realized, targets, atol=1.0 / draws, rtol=0.0)


def _paths() -> FoundationPaths:
    return FoundationPaths(
        foundation_root=Path("foundation"),
        dataset_id="asp.nfl.test",
        dataset_version_id="asp.nfl.test:sha256:" + "a" * 64,
        foundation_manifest_sha256="a" * 64,
        game_gold_id="gold-table:gold_nfl_game_pregame_v1",
        game_manifest_sha256="b" * 64,
        game_path=Path("game.parquet"),
        game_row_count=16,
        game_ordered_predictors=("season", "home_points_for_last_4"),
        play_gold_id="gold-table:gold_nfl_play_state_v1",
        play_manifest_sha256="c" * 64,
        play_path=Path("play.parquet"),
        play_row_count=100,
        schedule_manifest_sha256="d" * 64,
        schedule_path=Path("schedule.parquet"),
        schedule_row_count=16,
        market_manifest_sha256="e" * 64,
        market_path=Path("market.parquet"),
        market_row_count=16,
        feature_families={"LONG_HISTORY_CORE": ("season", "home_points_for_last_4")},
    )


def test_selection_receipt_and_runner_source_freeze_before_oot_and_reject_market_inputs() -> None:
    frame = _games()
    design = _design(frame)
    selected = SelectedCandidate(
        family="HGB_SCORE",
        candidate_id="hgb-score-test",
        recency_strategy="ALL_HISTORY",
        parameters={"max_iter": 50},
    )
    score_result = DistributionCandidateResult(
        selected=selected,
        folds={},
        ledger=pd.DataFrame(),
        summary={
            "jointScoreNegativeLogLikelihood": 5.1,
            "logLoss": 0.67,
            "meanTeamPointsMae": 7.4,
        },
    )
    ensemble_selected = SelectedCandidate(
        family="ENSEMBLE",
        candidate_id="ensemble-test",
        recency_strategy="COMPONENT_SPECIFIC_OOF_SELECTED",
        parameters={"components": ["HGB_SCORE"]},
    )
    ensemble_result = DistributionCandidateResult(
        selected=ensemble_selected,
        folds={},
        ledger=pd.DataFrame(),
        summary={
            "jointScoreNegativeLogLikelihood": 5.0,
            "logLoss": 0.66,
            "meanTeamPointsMae": 7.3,
        },
    )
    ensemble_selection = EnsembleSelection(
        score_families=("HGB_SCORE",),
        chronological_score_weights={"FOLD_1": (1.0,)},
        final_score_weights=(1.0,),
        chronological_probability_weights={"FOLD_1": (1.0, 0.0)},
        final_probability_weights=(1.0, 0.0),
        calibration_method="NONE",
        chronological_platt={"FOLD_1": None},
        final_platt=None,
    )
    receipt = _oof_selection_receipt(
        paths=_paths(),
        design=design,
        selected={"HGB_SCORE": selected},
        distribution_results={"HGB_SCORE": score_result},
        ensemble=ensemble_result,
        ensemble_selection=ensemble_selection,
        feature_tiers=pd.DataFrame(
            [{"feature_tier": "LONG_HISTORY_CORE", "status": "MATERIALIZED"}]
        ),
        point_ledger_sha256="1" * 64,
        distribution_ledger_sha256="2" * 64,
        simulation_manifest_sha256="3" * 64,
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert receipt["finalOotOutcomeValuesMaterialized"] is False
    assert receipt["foundationObjectBytesCryptographicallyVerified"] is True
    assert receipt["ootUsedForSelection"] is False
    assert receipt["marketUsedForSelection"] is False
    assert receipt["promotionAuthorized"] is False
    assert receipt["distributionOofSimulationManifestSha256"] == "3" * 64
    assert receipt["researchChallengerCandidateId"] == "ensemble-test"
    assert receipt["researchChallengerFamily"] == "ENSEMBLE"
    assert receipt["overallRanking"][0]["candidateId"] == "ensemble-test"
    assert "999.0" not in serialized and "998.0" not in serialized
    for forbidden in (
        "home_points",
        "away_points",
        "home_win",
        "home_moneyline",
        "away_moneyline",
        "spread_line",
        "total_line",
        "market_probability",
    ):
        assert forbidden not in serialized

    source = inspect.getsource(run_benchmark)
    predictor_guard = source.index("assert_no_market_predictors(paths.game_ordered_predictors)")
    selection = source.index("receipt = _oof_selection_receipt")
    population_audit = source.index("population = audit_game_population(paths)")
    oot_open = source.index("oot = _load_final_oot")
    assert predictor_guard < selection < population_audit < oot_open
    assert "_load_game_frame" not in source


def test_ensemble_meta_weights_use_pure_score_probability_in_every_oof_stage() -> None:
    source = inspect.getsource(build_oof_ensemble)
    assert 'prior_ledger["score_only_home_win_probability"]' in source
    assert 'ordered_raw["score_only_home_win_probability"]' in source
    assert 'prior_ledger["predicted_home_win_probability"]' not in source


def test_preselection_loaders_do_not_materialize_final_oot_outcomes() -> None:
    temporal_source = inspect.getsource(_load_temporal_identity_rows)
    assert 'columns = ["canonical_game_id", "season", "game_date"]' in temporal_source
    for outcome in ("home_points", "away_points", "home_win", "total_points"):
        assert outcome not in temporal_source
    development_source = inspect.getsource(_load_development_gold)
    assert 'filters=[("season", "<", int(design.final_oot_season))]' in development_source


def test_completed_seasons_verify_foundation_canonical_identity_not_file_bytes(
    tmp_path: Path,
) -> None:
    body = {
        "manifestContract": "ASP_NFL_FOUNDATION_MANIFEST_V1",
        "datasetId": "asp.nfl.test",
        "quality": {
            "scheduleBySeasonAndGameType": [
                {"season": 2024, "scheduledGames": 285, "completedGames": 285},
                {"season": 2025, "scheduledGames": 285, "completedGames": 285},
                {"season": 2026, "scheduledGames": 272, "completedGames": 0},
            ]
        },
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    version = f"asp.nfl.test:sha256:{digest}"
    manifest = {**body, "manifestSha256": digest, "datasetVersionId": version}
    root = tmp_path / "foundation"
    path = root / "manifests" / "sha256" / digest / "foundation-manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    paths = replace(
        _paths(),
        foundation_root=root,
        dataset_version_id=version,
        foundation_manifest_sha256=digest,
    )

    assert _complete_seasons_from_foundation_manifest(paths) == (2024, 2025)


def _partial_market_fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    oot = pd.DataFrame(
        [
            {
                "canonical_game_id": game_id,
                "game_date": date(2025, 9, day),
                "home_points": home,
                "away_points": away,
                "week": day,
                "game_type": "REG",
                "division_game": day == 1,
                "roof": "outdoors",
                "home_short_week": False,
                "away_short_week": False,
                "home_bye_or_long_rest": False,
                "away_bye_or_long_rest": False,
            }
            for game_id, day, home, away in (
                ("g1", 1, 24, 17),
                ("g2", 2, 20, 23),
                ("g3", 3, 27, 21),
            )
        ]
    )
    ledger = pd.DataFrame(
        {
            "canonical_game_id": oot["canonical_game_id"],
            "game_date": oot["game_date"].astype(str),
            "season": 2025,
            "game_type": "REG",
            "week": oot["week"],
            "fold_id": "FINAL_OOT_2025",
            "candidate_id": "candidate",
            "family": "TEST",
            "feature_tier": "LONG_HISTORY_CORE",
            "recency_strategy": "ALL_AVAILABLE_HISTORY",
            "actual_home_points": oot["home_points"].astype(float),
            "actual_away_points": oot["away_points"].astype(float),
            "actual_home_win": np.array([1, 0, 1]),
            "predicted_home_points": np.array([23.0, 21.0, 25.0]),
            "predicted_away_points": np.array([18.0, 22.0, 20.0]),
            "predicted_home_win_probability": np.array([0.60, 0.45, 0.65]),
            "joint_score_nll": 5.0,
            "home_points_crps": 4.0,
            "away_points_crps": 4.0,
            "score_differential_crps": 6.0,
            "total_points_crps": 7.0,
            "home_interval_90_covered": 1,
            "away_interval_90_covered": 1,
            "margin_interval_90_covered": 1,
            "total_interval_90_covered": 1,
            "fit_seconds": np.array([1.0, 0.0, 0.0]),
            "score_seconds": np.array([0.1, 0.0, 0.0]),
        }
    )
    market = pd.DataFrame(
        [
            {
                "canonical_game_id": "g1",
                "home_moneyline": -110.0,
                "away_moneyline": 100.0,
                # Source contract: projected home margin, so +3 means home -3.
                "spread_line": 3.0,
                "home_spread_price": -110.0,
                "away_spread_price": -110.0,
                "total_line": 41.5,
                "over_price": -110.0,
                "under_price": -110.0,
                "timing_semantics": "MARKET_SNAPSHOT_TIMING_UNPROVEN",
            },
            {
                "canonical_game_id": "g2",
                "home_moneyline": -105.0,
                "away_moneyline": np.nan,
                "spread_line": np.nan,
                "home_spread_price": np.nan,
                "away_spread_price": np.nan,
                "total_line": 42.5,
                "over_price": -105.0,
                "under_price": -115.0,
                "timing_semantics": "MARKET_SNAPSHOT_TIMING_UNPROVEN",
            },
        ]
    )
    return oot, ledger, market


def _partial_market_simulation() -> tuple[list[str], SimulatedScores]:
    # Intentionally reverse the identity order to prove that market evaluation
    # aligns by canonical game ID rather than assigning draws positionally.
    game_ids = ["g3", "g2", "g1"]
    home = np.asarray(
        [
            [24, 24, 27, 27, 21, 21, 17, 17],
            [20, 20, 21, 21, 24, 24, 17, 17],
            [24, 24, 23, 23, 21, 21, 20, 20],
        ],
        dtype=np.int32,
    )
    away = np.asarray(
        [
            [17, 17, 20, 20, 24, 24, 21, 21],
            [24, 24, 17, 17, 21, 21, 20, 20],
            [17, 17, 20, 20, 24, 24, 21, 21],
        ],
        dtype=np.int32,
    )
    return game_ids, SimulatedScores(
        home=home,
        away=away,
        predicted_home_mean=home.mean(axis=1),
        predicted_away_mean=away.mean(axis=1),
        residual_authority_sha256="f" * 64,
        seed=20260829,
    )


def test_partial_market_authority_uses_only_complete_prices_and_preserves_oot(
    tmp_path: Path,
) -> None:
    oot, ledger, market = _partial_market_fixture()
    market_path = tmp_path / "market.parquet"
    market.to_parquet(market_path, index=False)
    paths = replace(_paths(), market_path=market_path, market_row_count=len(market))

    simulation_ids, simulation = _partial_market_simulation()
    summary, detail = market_comparison_table(
        paths,
        oot,
        {"candidate": ledger},
        {"candidate": (simulation_ids, simulation)},
    )

    assert len(detail) == len(oot) == 3
    assert detail["market_row_available"].tolist() == [True, True, False]
    assert detail["complete_moneyline"].tolist() == [True, False, False]
    assert detail["complete_spread"].tolist() == [True, False, False]
    assert detail["complete_total"].tolist() == [True, True, False]
    assert detail["market_home_probability_no_vig"].notna().sum() == 1
    assert set(summary["rows"]) == {1}

    market_probability = (110.0 / 210.0) / ((110.0 / 210.0) + 0.5)
    sportsbook = summary[summary["candidateId"] == "SPORTSBOOK_NO_VIG"].iloc[0]
    np.testing.assert_allclose(sportsbook["logLoss"], -np.log(market_probability))
    model = summary[summary["candidateId"] == "candidate"].iloc[0]
    assert model["moneylineProbabilitySemantics"].startswith(
        "SIMULATED_HOME_WIN_CONDITIONAL_ON_NONPUSH"
    )
    np.testing.assert_allclose(model["logLoss"], -np.log(0.5))
    np.testing.assert_allclose(
        detail.loc[
            detail["canonical_game_id"] == "g1",
            "candidate_market_conditional_home_probability",
        ].iat[0],
        0.5,
    )
    assert model["homeCoverRows"] == 1
    assert model["overRows"] == 2
    assert np.isfinite(model["homeCoverLogLoss"])
    assert np.isfinite(model["overLogLoss"])
    assert np.isfinite(sportsbook["homeCoverLogLoss"])
    assert np.isfinite(sportsbook["overLogLoss"])
    assert detail["candidate_conditional_home_cover_probability"].notna().sum() == 1
    assert detail["candidate_conditional_over_probability"].notna().sum() == 2
    assert detail["candidate_spread_push_probability"].between(0.0, 1.0).sum() == 1
    assert detail["candidate_total_push_probability"].between(0.0, 1.0).sum() == 2

    slices = _slice_metrics(ledger, oot, detail)
    assert slices.loc[slices["slice_family"] == "WEEK", "rows"].sum() == 3
    favorite = slices[slices["slice_family"] == "FAVORITE_UNDERDOG"].set_index(
        "slice_value"
    )
    assert int(favorite.loc["MARKET_NOT_AVAILABLE", "rows"]) == 2

    bootstrap = bootstrap_comparisons(
        ensemble=ledger,
        best_single=ledger,
        elo=ledger,
        rolling=ledger,
        market_detail=detail,
        resamples=20,
        seed=123,
    )
    assert bootstrap["best_single_vs_market"]["homeWinLogLoss"]["games"] == 1


def test_moneyline_comparison_conditions_on_non_tie_and_reports_actual_push(
    tmp_path: Path,
) -> None:
    oot, ledger, market = _partial_market_fixture()
    oot.loc[oot["canonical_game_id"] == "g1", ["home_points", "away_points"]] = 20
    ledger.loc[
        ledger["canonical_game_id"] == "g1",
        ["actual_home_points", "actual_away_points", "actual_home_win"],
    ] = [20.0, 20.0, 0]
    market_path = tmp_path / "market-moneyline-push.parquet"
    market.to_parquet(market_path, index=False)
    paths = replace(_paths(), market_path=market_path, market_row_count=len(market))
    simulation_ids, simulation = _partial_market_simulation()

    summary, detail = market_comparison_table(
        paths,
        oot,
        {"candidate": ledger},
        {"candidate": (simulation_ids, simulation)},
    )

    assert detail["complete_moneyline"].sum() == 1
    assert detail["actual_moneyline_push"].sum() == 1
    assert detail["moneyline_evaluation_eligible"].sum() == 0
    for candidate_id in ("SPORTSBOOK_NO_VIG", "candidate"):
        row = summary[summary["candidateId"] == candidate_id].iloc[0]
        assert row["rows"] == 0
        assert row["moneylineActualPushRows"] == 1
        assert pd.isna(row["logLoss"])

    bootstrap = bootstrap_comparisons(
        ensemble=ledger,
        best_single=ledger,
        elo=ledger,
        rolling=ledger,
        market_detail=detail,
        resamples=20,
        seed=123,
    )
    assert bootstrap["best_single_vs_market"]["homeWinLogLoss"]["games"] == 0


def test_no_complete_market_price_is_explicitly_unavailable_not_zero(
    tmp_path: Path,
) -> None:
    oot, ledger, market = _partial_market_fixture()
    market.loc[:, ["home_moneyline", "away_moneyline"]] = np.nan
    market.loc[:, ["home_spread_price", "away_spread_price", "over_price", "under_price"]] = 0.0
    market_path = tmp_path / "market-none.parquet"
    market.to_parquet(market_path, index=False)
    paths = replace(_paths(), market_path=market_path, market_row_count=len(market))

    summary, detail = market_comparison_table(paths, oot, {"candidate": ledger})
    assert len(detail) == 3
    assert not detail["complete_moneyline"].any()
    assert not detail["complete_spread"].any()
    assert not detail["complete_total"].any()
    assert set(summary["rows"]) == {0}
    assert summary["logLoss"].isna().all()

    bootstrap = bootstrap_comparisons(
        ensemble=ledger,
        best_single=ledger,
        elo=ledger,
        rolling=ledger,
        market_detail=detail,
        resamples=20,
        seed=123,
    )
    market_bootstrap = bootstrap["best_single_vs_market"]["homeWinLogLoss"]
    assert market_bootstrap["games"] == 0
    assert market_bootstrap["pointEstimate"] is None
    assert market_bootstrap["status"] == "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE"


def test_complete_spread_actual_push_is_excluded_and_reported(
    tmp_path: Path,
) -> None:
    oot, ledger, market = _partial_market_fixture()
    market.loc[market["canonical_game_id"] == "g1", "spread_line"] = 7.0
    market_path = tmp_path / "market-push.parquet"
    market.to_parquet(market_path, index=False)
    paths = replace(_paths(), market_path=market_path, market_row_count=len(market))
    simulation_ids, simulation = _partial_market_simulation()

    summary, detail = market_comparison_table(
        paths,
        oot,
        {"candidate": ledger},
        {"candidate": (simulation_ids, simulation)},
    )

    assert detail["complete_spread"].sum() == 1
    for candidate_id in ("SPORTSBOOK_NO_VIG", "candidate"):
        row = summary[summary["candidateId"] == candidate_id].iloc[0]
        assert row["homeCoverRows"] == 0
        assert row["homeCoverActualPushRows"] == 1
        assert pd.isna(row["homeCoverLogLoss"])
        assert (
            row["homeCoverCalibrationStatus"]
            == "NOT_AVAILABLE_ALL_COMPLETE_LINE_ROWS_PUSH"
        )


def test_exact_simulation_archive_is_atomic_nonpickle_and_checksum_verified(
    tmp_path: Path,
) -> None:
    game_ids, simulation = _partial_market_simulation()
    archive = _atomic_simulation_archive(
        tmp_path / "draws.npz",
        candidate_id="candidate",
        scope="TEST",
        game_ids=game_ids,
        simulation=simulation,
    )
    assert archive["gameRows"] == 3
    assert archive["drawsPerGame"] == 8
    assert archive["pickleUsed"] is False
    assert archive["storageFormat"] == "NUMPY_NPZ_ALLOW_PICKLE_FALSE"
    assert len(archive["archiveSha256"]) == 64
    with np.load(archive["archivePath"], allow_pickle=False) as loaded:
        assert loaded["canonical_game_id"].astype(str).tolist() == game_ids
        np.testing.assert_array_equal(loaded["home_score_draws"], simulation.home)
        np.testing.assert_array_equal(loaded["away_score_draws"], simulation.away)

    bundle = _persist_simulation_bundle(
        tmp_path / "external",
        scope="TEST",
        candidates={"candidate": (game_ids, simulation)},
        candidate_fold_lineage={
            "candidate": [
                {
                    "foldId": "FOLD_1",
                    "rowStartInclusive": 0,
                    "rowStopExclusive": 3,
                    "gameRows": 3,
                    "gameIdSha256": "a" * 64,
                    "residualAuthoritySha256": "f" * 64,
                    "seed": 20260829,
                }
            ]
        },
    )
    assert bundle["candidateCount"] == 1
    assert bundle["marketUsedForSelection"] is False
    assert Path(bundle["manifestPath"]).is_file()
    assert len(bundle["manifestSha256"]) == 64
    record = bundle["archives"][0]
    assert record["residualAuthorityStatus"] == "MULTIPLE_FOLD_LOCAL_AUTHORITIES_ENUMERATED"
    assert record["foldLineage"][0]["foldId"] == "FOLD_1"
    assert "residualAuthoritySha256" not in record


def test_per_game_ledger_has_compact_distribution_summary_and_unsupported_overtime() -> None:
    game_ids, simulation = _partial_market_simulation()
    validation = pd.DataFrame(
        {
            "canonical_game_id": game_ids,
            "game_date": [date(2025, 9, 3), date(2025, 9, 2), date(2025, 9, 1)],
            "season": 2025,
            "game_type": "REG",
            "week": [3, 2, 1],
            "home_points": [27, 20, 24],
            "away_points": [21, 23, 17],
        }
    )
    ledger = _per_game_distribution_ledger(
        validation,
        simulation,
        fold_id="TEST",
        candidate_id="candidate",
        family="TEST",
        recency_strategy="ALL_AVAILABLE_HISTORY",
        fit_seconds=1.0,
        score_seconds=0.5,
    )
    assert len(ledger) == 3
    assert set(ledger["overtime_probability_status"]) == {
        "NOT_SUPPORTED_BY_FINAL_SCORE_RESIDUAL_MODEL"
    }
    assert ledger["overtime_probability"].isna().all()
    for payload in ledger["most_likely_final_scores_json"]:
        scores = json.loads(payload)
        assert 1 <= len(scores) <= 5
        assert sum(row["probability"] for row in scores) <= 1.0
    assert ledger["fit_seconds"].sum() == 1.0
    assert ledger["score_seconds"].sum() == 0.5
