from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import uuid

import pandas as pd
import pytest

from server.sports_nfl_m1.reporting import (
    CHART_NAMES,
    CSV_NAMES,
    write_m1_research_outputs,
)


@pytest.fixture
def reporting_tmp() -> Path:
    path = Path(".tmp") / f"nfl-m1-reporting-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _frames() -> dict[str, pd.DataFrame]:
    return {
        "temporal_splits": pd.DataFrame(
            [
                {"fold_id": "FOLD_2", "train_count": 5852, "validation_count": 285},
                {"fold_id": "FOLD_1", "train_count": 5583, "validation_count": 269},
            ]
        ),
        "fold_metrics": pd.DataFrame(
            [
                {
                    "fold_id": "FOLD_2",
                    "candidate_id": "score_hgb",
                    "scope": "OOF_FOLD",
                    "rows": 285,
                    "home_win_log_loss": 0.674,
                },
                {
                    "fold_id": "FOLD_1",
                    "candidate_id": "score_hgb",
                    "scope": "OOF_FOLD",
                    "rows": 269,
                    "home_win_log_loss": 0.665,
                },
            ]
        ),
        "fold_calibration": pd.DataFrame(
            [
                {
                    "fold_id": "FOLD_1",
                    "candidate_id": "score_hgb",
                    "bin": 1,
                    "mean_probability": 0.3,
                    "event_rate": 0.31,
                },
                {
                    "fold_id": "FOLD_1",
                    "candidate_id": "score_hgb",
                    "bin": 2,
                    "mean_probability": 0.7,
                    "event_rate": 0.69,
                },
            ]
        ),
        "feature_tiers": pd.DataFrame(
            [
                {"feature_tier": "LONG_HISTORY_CORE", "status": "MATERIALIZED", "home_win_log_loss": 0.675},
                {"feature_tier": "RECENT_RICH", "status": "SOURCE_TABLE_ONLY", "home_win_log_loss": None},
            ]
        ),
        "recency_leaderboard": pd.DataFrame(
            [
                {
                    "candidate_id": "score_hgb",
                    "family": "HIST_GRADIENT_BOOSTING",
                    "recency_strategy": "ALL_HISTORY",
                    "mean_team_points_mae": 7.5,
                },
                {
                    "candidate_id": "score_hgb",
                    "family": "HIST_GRADIENT_BOOSTING",
                    "recency_strategy": "RECENT_5",
                    "mean_team_points_mae": 7.4,
                },
                {
                    "candidate_id": "score_ridge",
                    "family": "RIDGE",
                    "recency_strategy": "ALL_HISTORY",
                    "mean_team_points_mae": 7.7,
                },
                {
                    "candidate_id": "score_ridge",
                    "family": "RIDGE",
                    "recency_strategy": "RECENT_5",
                    "mean_team_points_mae": 7.6,
                },
            ]
        ),
        "candidate_leaderboard": pd.DataFrame(
            [
                {"candidate_id": "elo", "scope": "OOF", "home_win_log_loss": 0.681, "home_points_mae": 8.0, "away_points_mae": 7.8},
                {"candidate_id": "score_hgb", "scope": "OOF", "home_win_log_loss": 0.669, "home_points_mae": 7.5, "away_points_mae": 7.4},
                {"candidate_id": "elo", "scope": "FINAL_OOT", "home_win_log_loss": 0.684, "home_points_mae": 8.1, "away_points_mae": 7.9},
                {"candidate_id": "score_hgb", "scope": "FINAL_OOT", "home_win_log_loss": 0.672, "home_points_mae": 7.6, "away_points_mae": 7.5},
            ]
        ),
        "calibration": pd.DataFrame(
            [
                {"candidate_id": "elo", "scope": "OOF", "bin": 1, "mean_probability": 0.3, "event_rate": 0.32},
                {"candidate_id": "elo", "scope": "OOF", "bin": 2, "mean_probability": 0.7, "event_rate": 0.68},
                {"candidate_id": "score_hgb", "scope": "OOF", "bin": 1, "mean_probability": 0.3, "event_rate": 0.31},
                {"candidate_id": "score_hgb", "scope": "OOF", "bin": 2, "mean_probability": 0.7, "event_rate": 0.69},
            ]
        ),
        "market": pd.DataFrame(
            [
                {"candidate_id": "score_hgb", "spread_projection_error": -1.5, "total_projection_error": 3.0, "model_probability": 0.58, "no_vig_market_probability": 0.55},
                {"candidate_id": "score_hgb", "spread_projection_error": 2.0, "total_projection_error": -4.0, "model_probability": 0.42, "no_vig_market_probability": 0.45},
            ]
        ),
        "slices": pd.DataFrame(
            [
                {"candidate_id": "score_hgb", "slice_family": "week", "slice_value": 1, "home_win_log_loss": 0.66},
                {"candidate_id": "score_hgb", "slice_family": "week", "slice_value": 2, "home_win_log_loss": 0.68},
            ]
        ),
        "game_predictions": pd.DataFrame(
            [
                {"candidate_id": "score_hgb", "game_date": "2024-09-08", "model_log_loss": 0.62, "baseline_log_loss": 0.69},
                {"candidate_id": "score_hgb", "game_date": "2024-09-15", "model_log_loss": 0.73, "baseline_log_loss": 0.70},
            ]
        ),
        "distribution_coverage": pd.DataFrame(
            [
                {"candidate_id": "score_hgb", "nominal_coverage": 0.5, "empirical_coverage": 0.52},
                {"candidate_id": "score_hgb", "nominal_coverage": 0.8, "empirical_coverage": 0.78},
                {"candidate_id": "score_hgb", "nominal_coverage": 0.95, "empirical_coverage": 0.93},
            ]
        ),
        "feature_coefficients": pd.DataFrame(
            [
                {
                    "candidate_id": "home_win_logistic",
                    "expanded_feature": "numeric__home_recent_epa",
                    "coefficient": 0.25,
                }
            ]
        ),
        "missingness_source_era": pd.DataFrame(
            [
                {
                    "feature": "home_recent_epa",
                    "development_missing_pct": 0.1,
                    "final_oot_missing_pct": 0.08,
                    "source_era_status": "AVAILABLE",
                }
            ]
        ),
        "missing_reason_summary": pd.DataFrame(
            [
                {
                    "feature": "home_recent_epa",
                    "missing_reason": "MISSING_HISTORY",
                    "scope": "DEVELOPMENT",
                    "rows": 12,
                }
            ]
        ),
    }


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reporting_bundle_writes_reviewable_tables_and_all_requested_charts(reporting_tmp: Path) -> None:
    frames = _frames()
    result = write_m1_research_outputs(reporting_tmp / "first", **frames)

    assert set(result.csv_paths) == set(CSV_NAMES)
    assert set(result.chart_paths) == set(CHART_NAMES)
    assert set(result.chart_status.values()) == {"RENDERED"}
    assert result.chart_status["recencyStrategy"] == "RENDERED"
    for path in result.csv_paths.values():
        assert path.is_file()
    for path in result.chart_paths.values():
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    # Stable sorting puts FOLD_1 before FOLD_2 despite input order.
    temporal = pd.read_csv(result.csv_paths["temporalSplits"])
    assert temporal["fold_id"].tolist() == ["FOLD_1", "FOLD_2"]
    fold_metrics = pd.read_csv(result.csv_paths["foldMetrics"])
    assert fold_metrics["fold_id"].tolist() == ["FOLD_1", "FOLD_2"]
    tiers = pd.read_csv(result.csv_paths["featureTiers"])
    assert tiers.loc[tiers["feature_tier"] == "RECENT_RICH", "status"].item() == "SOURCE_TABLE_ONLY"
    assert pd.isna(tiers.loc[tiers["feature_tier"] == "RECENT_RICH", "home_win_log_loss"].item())

    expected_extended_csv = {
        "foldMetrics",
        "foldCalibration",
        "featureCoefficients",
        "missingnessSourceEra",
        "missingReasonSummary",
    }
    assert expected_extended_csv.issubset(result.csv_paths)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["contract"] == "ASP_NFL_M1_REPORTING_BUNDLE_V1"
    assert manifest["unavailableMeansZero"] is False
    assert manifest["modelsFittedByReporting"] == 0
    assert manifest["modelsScoredByReporting"] == 0
    assert expected_extended_csv.issubset(manifest["csv"])
    for key in expected_extended_csv:
        assert manifest["csv"][key]["sha256"] == _digest(result.csv_paths[key])


def test_reporting_is_byte_deterministic_for_identical_inputs(reporting_tmp: Path) -> None:
    frames = _frames()
    first = write_m1_research_outputs(reporting_tmp / "one", **frames)
    second = write_m1_research_outputs(reporting_tmp / "two", **frames)
    assert {
        key: _digest(path) for key, path in first.csv_paths.items()
    } == {
        key: _digest(path) for key, path in second.csv_paths.items()
    }
    assert {
        key: _digest(path) for key, path in first.chart_paths.items()
    } == {
        key: _digest(path) for key, path in second.chart_paths.items()
    }


def test_sparse_optional_inputs_are_not_rendered_as_zero(reporting_tmp: Path) -> None:
    empty = pd.DataFrame()
    result = write_m1_research_outputs(
        reporting_tmp / "sparse",
        temporal_splits=pd.DataFrame([{"fold_id": "FOLD_1", "validation_count": 1}]),
        feature_tiers=pd.DataFrame([{"feature_tier": "RECENT_RICH", "status": "SOURCE_TABLE_ONLY"}]),
        candidate_leaderboard=empty,
        calibration=empty,
        market=pd.DataFrame([{"timing_semantics": "MARKET_SNAPSHOT_TIMING_UNPROVEN"}]),
        slices=empty,
    )
    assert set(result.chart_status.values()) == {"NOT_AVAILABLE"}
    assert all(path.is_file() and path.stat().st_size > 0 for path in result.chart_paths.values())
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert all(value["status"] == "NOT_AVAILABLE" for value in manifest["charts"].values())
    assert manifest["unavailableMeansZero"] is False
