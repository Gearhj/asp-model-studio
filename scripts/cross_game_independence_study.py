"""Leakage-bounded cross-game independence study over retained research ledgers.

The script reads only explicit historical prediction ledgers and schedule identity
metadata.  It has no provider, sportsbook, exchange, AISP, model, or outcome-
acquisition client.  All outputs are deterministic JSON in an explicit directory.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCHEMA = "ASP_CROSS_GAME_INDEPENDENCE_RESULTS_V1"
SEED = 20260916
BOOTSTRAPS = 2_000
SPORT_ORDER = ("CFB", "NBA", "NFL")
RESIDUALS = ("winner_residual", "margin_residual", "total_residual", "home_score_residual", "away_score_residual")
TOLERANCE = {
    "minimumGames": 500, "minimumSlates": 50, "minimumPairs": 1000,
    "maximumAbsoluteJointCalibrationError": .02,
    "maximumRelativeJointCalibrationErrorWhenMeanProbabilityAtLeast0_10": .10,
    "maximumJointCalibrationCiWidth": .05,
    "maximumAbsoluteResidualPearson": .05,
    "maximumAbsoluteResidualSpearman": .05,
    "correlationCiLower": -.10, "correlationCiUpper": .10,
    "minimumReliabilityBinPairs": 200, "minimumReliabilityBinSlates": 20,
    "maximumReliabilityBinAbsoluteError": .03,
}


def json_safe(value: Any) -> Any:
    """Convert non-finite estimates to explicit unavailable values."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
        return None
    if isinstance(value, np.integer):
        return int(value)
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, expected: str) -> dict[str, Any]:
    actual = sha(path)
    if actual != expected:
        raise ValueError(f"PHYSICAL_HASH_MISMATCH: {path} {actual} != {expected}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": actual}


def _date(value: pd.Series) -> pd.Series:
    return pd.to_datetime(value, errors="raise").dt.date.astype(str)


def _finish(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["sport", "game_key", "slate_date", "home_team", "away_team", "p_home", "p_away", "p_tie",
                "actual_home_win", "actual_home", "actual_away", "pred_home", "pred_away"]
    if frame[required].isna().any().any():
        raise ValueError("STANDARDIZED_GAME_FIELDS_MISSING")
    if frame.game_key.duplicated().any():
        raise ValueError("DUPLICATE_STANDARDIZED_GAME_ID")
    mass = frame[["p_home", "p_away", "p_tie"]].sum(axis=1)
    if not np.allclose(mass, 1.0, rtol=0, atol=1e-12) or (frame[["p_home", "p_away", "p_tie"]] < 0).any().any():
        raise ValueError("PROBABILITY_MASS_DIFFERS")
    frame = frame.copy()
    frame["actual_margin"] = frame.actual_home - frame.actual_away
    frame["pred_margin"] = frame.pred_home - frame.pred_away
    frame["actual_total"] = frame.actual_home + frame.actual_away
    frame["pred_total"] = frame.pred_home + frame.pred_away
    frame["winner_residual"] = frame.actual_home_win - frame.p_home
    frame["margin_residual"] = frame.actual_margin - frame.pred_margin
    frame["total_residual"] = frame.actual_total - frame.pred_total
    frame["home_score_residual"] = frame.actual_home - frame.pred_home
    frame["away_score_residual"] = frame.actual_away - frame.pred_away
    home_favorite = frame.p_home >= frame.p_away
    frame["p_favorite"] = np.where(home_favorite, frame.p_home, frame.p_away)
    frame["actual_favorite_win"] = np.where(home_favorite, frame.actual_home_win, 1.0 - frame.actual_home_win - frame.actual_tie)
    frame["favorite_residual"] = frame.actual_favorite_win - frame.p_favorite
    frame["home_leg_class"] = np.where(frame.p_home >= .5, "FAVORITE", "UNDERDOG")
    return frame.sort_values(["slate_date", "sport", "game_key"], kind="mergesort").reset_index(drop=True)


def load_nfl(path: Path, schedule_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = verify(path, "b721e7259403304fea7ac69e391c22cebe27b07b3687f007e5d3420f35b84b99")
    schedule = verify(schedule_path, "18d03fef3b91eb38472ed9f678bb11a9bfbec7b9a664dfce4c60ab247cbee9d3")
    raw = pd.read_parquet(path)
    if len(raw) != 1408 or sorted(raw.season.unique().tolist()) != [2020, 2021, 2022, 2023, 2024]:
        raise ValueError("NFL_DEVELOPMENT_POPULATION_DIFFERS")
    folds = raw.groupby("fold_id").season.unique().map(lambda x: tuple(sorted(x))).to_dict()
    if any(len(values) != 1 for values in folds.values()) or len(folds) != 5:
        raise ValueError("NFL_SEASON_FORWARD_FOLD_IDENTITY_DIFFERS")
    metadata = pd.read_parquet(schedule_path, columns=["game_id", "game_type", "gameday", "gametime", "away_team", "home_team"])
    data = raw.merge(metadata, left_on="canonical_game_id", right_on="game_id", how="left", validate="one_to_one")
    if data[["game_type", "gameday", "away_team", "home_team"]].isna().any().any():
        raise ValueError("NFL_SCHEDULE_METADATA_JOIN_INCOMPLETE")
    time = pd.to_datetime(data.gameday.astype(str) + " " + data.gametime.fillna("00:00").astype(str),
                          errors="raise", format="mixed")
    out = pd.DataFrame({
        "sport": "NFL", "game_key": "NFL:" + data.canonical_game_id.astype(str),
        "slate_date": _date(data.gameday), "start_time": time,
        "start_time_certified": data.gametime.notna(), "home_team": data.home_team.astype(str), "away_team": data.away_team.astype(str),
        "regular_season": data.game_type.eq("REG"), "postseason": data.game_type.ne("REG"),
        "model_configuration": "M1_RECIPE_RAW_CHRONOLOGICAL_OOF",
        "p_home": data.raw_home_probability.astype(float), "p_away": data.raw_away_probability.astype(float),
        "p_tie": data.raw_tie_probability.astype(float), "actual_home_win": data.outcome_class.eq(2).astype(float),
        "actual_tie": data.outcome_class.eq(1).astype(float),
        "actual_home": data.actual_home_points.astype(float), "actual_away": data.actual_away_points.astype(float),
        "pred_home": data.predicted_home_points.astype(float), "pred_away": data.predicted_away_points.astype(float),
        "chronology_verified": True,
    })
    return _finish(out), {"sport": "NFL", "source": source, "scheduleMetadata": schedule, "rows": len(out),
                          "seasonCounts": {str(k): int(v) for k, v in raw.season.value_counts().sort_index().items()},
                          "foldSeasonMap": {key: list(value) for key, value in sorted(folds.items())},
                          "chronology": "One season-forward OOF fold per target season; schedule metadata reads identity/time/type columns only."}


def load_nba(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = verify(path, "1d05622a0f77d504460a89f9b12e715c90b9c1039ef7d7a7ec444ef781b94715")
    raw = pd.read_parquet(path)
    data = raw[raw.model_id.eq("ridge_a100_rest")].copy()
    if len(data) != 3538 or data.game_id.nunique() != len(data):
        raise ValueError("NBA_DEVELOPMENT_POPULATION_DIFFERS")
    target_date = pd.to_datetime(data.game_date, errors="raise")
    history_date = pd.to_datetime(data.history_latest_game_date, errors="raise")
    if not (history_date < target_date).all():
        raise ValueError("NBA_TARGET_OR_LATER_HISTORY_DETECTED")
    out = pd.DataFrame({
        "sport": "NBA", "game_key": "NBA:" + data.game_id.astype(str), "slate_date": _date(data.game_date),
        "start_time": pd.NaT, "start_time_certified": False,
        "home_team": data.home_team_code.astype(str), "away_team": data.away_team_code.astype(str),
        "regular_season": True, "postseason": False,
        "model_configuration": "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1_DEVELOPMENT",
        "p_home": data.p_home_win.astype(float), "p_away": data.p_away_win.astype(float), "p_tie": data.p_tie.astype(float),
        "actual_home_win": (data.home_score > data.away_score).astype(float), "actual_tie": 0.0,
        "actual_home": data.home_score.astype(float), "actual_away": data.away_score.astype(float),
        "pred_home": data.expected_home_score.astype(float), "pred_away": data.expected_away_score.astype(float),
        "chronology_verified": True,
    })
    return _finish(out), {"sport": "NBA", "source": source, "rows": len(out),
                          "seasonCounts": {str(k): int(v) for k, v in data.season_end.value_counts().sort_index().items()},
                          "chronology": "Each row's latest history date is strictly earlier than the target; physical historical publication times remain uncertified."}


def load_cfb(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = verify(path, "b73757c74df42052f766813c35ff46278d42e5f94a658c3051382c068ba6872d")
    raw = pd.read_parquet(path)
    data = raw[raw.role.eq("validation") & raw.season.isin([2023, 2024]) & raw.context_eligible & raw.is_final].copy()
    if len(data) != 1491:
        raise ValueError("CFB_VALIDATION_POPULATION_DIFFERS")
    kickoff = pd.to_datetime(data.scheduled_at, utc=True, errors="raise").dt.tz_convert("America/New_York")
    source_date = pd.to_datetime(data.feature_max_source_game_date, utc=True, errors="coerce")
    chronology_valid = source_date.isna() | (source_date < pd.to_datetime(data.scheduled_at, utc=True, errors="raise"))
    if not chronology_valid.all():
        raise ValueError("CFB_TARGET_OR_LATER_FEATURE_SOURCE_DETECTED")
    probability = data.ridge_alpha100_calibrated_home_win_probability.astype(float)
    out = pd.DataFrame({
        "sport": "CFB", "game_key": "CFB:" + data.game_id.astype(str), "slate_date": kickoff.dt.date.astype(str),
        "start_time": kickoff.dt.tz_localize(None), "start_time_certified": True,
        "home_team": data.home_id.astype(str), "away_team": data.away_id.astype(str),
        "regular_season": ~data.postseason.astype(bool), "postseason": data.postseason.astype(bool),
        "model_configuration": "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1_VALIDATION",
        "p_home": probability, "p_away": 1.0 - probability, "p_tie": 0.0,
        "actual_home_win": data.home_win.astype(float), "actual_tie": 0.0,
        "actual_home": data.home_score.astype(float), "actual_away": data.away_score.astype(float),
        "pred_home": data.ridge_alpha100_pred_home.astype(float), "pred_away": data.ridge_alpha100_pred_away.astype(float),
        "chronology_verified": True,
    })
    return _finish(out), {"sport": "CFB", "source": source, "rows": len(out),
                          "seasonCounts": {str(k): int(v) for k, v in data.season.value_counts().sort_index().items()},
                          "nullFeatureSourceDates": int(source_date.isna().sum()),
                          "chronology": "Development-fixed calibrator assessed on reused 2023-24 Validation; non-null feature source dates are earlier than kickoff. Null marks no prior eligible game in either team state and is governed by season-opener/prior defaults."}


def pair_rows(games: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    indexed = games.reset_index(drop=True).copy()
    indexed["row_id"] = np.arange(len(indexed), dtype=int)
    for slate, slate_games in indexed.groupby("slate_date", sort=True):
        groups = {sport: part for sport, part in slate_games.groupby("sport", sort=True)}
        for sport, part in groups.items():
            for left, right in itertools.combinations(part.row_id.tolist(), 2):
                records.append(_pair(indexed.iloc[left], indexed.iloc[right], slate))
        for sport_a, sport_b in itertools.combinations(sorted(groups), 2):
            for left in groups[sport_a].row_id:
                for right in groups[sport_b].row_id:
                    records.append(_pair(indexed.iloc[int(left)], indexed.iloc[int(right)], slate))
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("NO_CROSS_GAME_PAIRS")
    if frame.pair_id.duplicated().any() or (frame.game_a == frame.game_b).any():
        raise ValueError("PAIR_DUPLICATION_OR_SAME_GAME_DETECTED")
    return frame.sort_values(["slate_date", "pair_id"], kind="mergesort").reset_index(drop=True)


def _pair(left: pd.Series, right: pd.Series, slate: str) -> dict[str, Any]:
    if left.game_key > right.game_key:
        left, right = right, left
    same_sport = left.sport == right.sport
    shared = bool(same_sport and {left.home_team, left.away_team} & {right.home_team, right.away_team})
    exact_time = bool(left.start_time_certified and right.start_time_certified)
    minutes = abs((left.start_time - right.start_time).total_seconds()) / 60 if exact_time else None
    timing = "UNKNOWN"
    if exact_time:
        timing = "SAME_START_WINDOW" if minutes <= 60 else "SEPARATED_START" if minutes > 180 else "INTERMEDIATE_START"
    sport_pair = "+".join(sorted((left.sport, right.sport)))
    row = {
        "pair_id": left.game_key + "|" + right.game_key, "slate_date": slate,
        "game_a": left.game_key, "game_b": right.game_key, "row_a": int(left.row_id), "row_b": int(right.row_id),
        "sport_pair": sport_pair, "same_sport": same_sport, "shared_team": shared,
        "postseason_any": bool(left.postseason or right.postseason), "regular_both": bool(left.regular_season and right.regular_season),
        "timing_class": timing, "start_difference_minutes": minutes,
        "potential_sequential_incentive": bool(same_sport and (left.postseason or right.postseason) and timing == "SEPARATED_START"),
        "home_leg_class": left.home_leg_class + "+" + right.home_leg_class,
    }
    for name in ("p_home", "actual_home_win", "p_favorite", "actual_favorite_win", *RESIDUALS):
        row[name + "_a"] = float(left[name])
        row[name + "_b"] = float(right[name])
    return row


def _cluster_bootstrap(frame: pd.DataFrame, values: np.ndarray, seed: int) -> tuple[float, float, float, float]:
    local = pd.DataFrame({"slate": frame.slate_date.to_numpy(), "value": values})
    grouped = local.groupby("slate", sort=True).value.agg(["sum", "count"])
    estimate = float(values.mean())
    if len(grouped) < 2:
        return estimate, math.nan, math.nan, math.nan
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(grouped), size=(BOOTSTRAPS, len(grouped)))
    sums = grouped["sum"].to_numpy()[indices].sum(axis=1)
    counts = grouped["count"].to_numpy()[indices].sum(axis=1)
    samples = sums / counts
    low, high = np.quantile(samples, [.025, .975])
    return estimate, float(low), float(high), float(samples.std(ddof=1))


def cluster_coverage(frame: pd.DataFrame) -> dict[str, Any]:
    counts = frame.groupby("slate_date", sort=True).size().to_numpy(float)
    kish = float(counts.sum() ** 2 / np.square(counts).sum()) if len(counts) else 0.0
    return {
        "independentSlateClusters": int(len(counts)),
        "kishEffectiveSlatesForPairWeightedEstimate": kish,
        "qualification": "Game pairs within a slate are not independent; uncertainty resamples whole slates.",
    }


def dependence(frame: pd.DataFrame, metric: str, seed: int) -> dict[str, Any]:
    a = frame[metric + "_a"].to_numpy(float)
    b = frame[metric + "_b"].to_numpy(float)
    endpoints = np.concatenate([a, b])
    mean, sd = float(endpoints.mean()), float(endpoints.std(ddof=0))
    if sd == 0:
        return {"metric": metric, "status": "ZERO_VARIANCE", "pairs": len(frame), "slates": frame.slate_date.nunique()}
    pearson_contribution = ((a - mean) / sd) * ((b - mean) / sd)
    covariance_contribution = (a - mean) * (b - mean)
    endpoint_frame = pd.DataFrame({"game": np.concatenate([frame.game_a, frame.game_b]), "value": endpoints})
    if endpoint_frame.groupby("game").value.nunique().max() != 1:
        raise ValueError("GAME_RESIDUAL_DIFFERS_ACROSS_PAIRS")
    unique = endpoint_frame.drop_duplicates("game", keep="first").copy()
    unique["rank"] = unique.value.rank(method="average", pct=True)
    rank_map = dict(zip(unique.game, unique["rank"]))
    ra = frame.game_a.map(rank_map).to_numpy(float); rb = frame.game_b.map(rank_map).to_numpy(float)
    rmean = float(np.concatenate([ra, rb]).mean()); rsd = float(np.concatenate([ra, rb]).std(ddof=0))
    spearman_contribution = ((ra - rmean) / rsd) * ((rb - rmean) / rsd)
    p_est, p_low, p_high, p_se = _cluster_bootstrap(frame, pearson_contribution, seed)
    s_est, s_low, s_high, s_se = _cluster_bootstrap(frame, spearman_contribution, seed + 1)
    c_est, c_low, c_high, _ = _cluster_bootstrap(frame, covariance_contribution, seed + 2)
    p_value = math.erfc(abs(p_est / p_se) / math.sqrt(2)) if p_se and math.isfinite(p_se) else None
    return {"metric": metric, "status": "ESTIMATED", "games": int(len(set(frame.game_a) | set(frame.game_b))),
            "pairs": len(frame), "slates": int(frame.slate_date.nunique()),
            "effectiveSampleSize": cluster_coverage(frame),
            "pearson": p_est, "pearsonCi95": [p_low, p_high], "clusterBootstrapSe": p_se,
            "spearman": s_est, "spearmanCi95": [s_low, s_high],
            "covariance": c_est, "covarianceCi95": [c_low, c_high], "unadjustedPValue": p_value,
            "method": "Exchangeable pair-product correlation; endpoint standardization fixed before whole-slate bootstrap."}


def calibration(frame: pd.DataFrame, *, favorite: bool, seed: int) -> dict[str, Any]:
    prefix = "favorite" if favorite else "home"
    pa = frame["p_favorite_a" if favorite else "p_home_a"].to_numpy(float)
    pb = frame["p_favorite_b" if favorite else "p_home_b"].to_numpy(float)
    ya = frame["actual_favorite_win_a" if favorite else "actual_home_win_a"].to_numpy(float)
    yb = frame["actual_favorite_win_b" if favorite else "actual_home_win_b"].to_numpy(float)
    probability = pa * pb; observed = ya * yb; error = observed - probability
    _, low, high, _ = _cluster_bootstrap(frame, error, seed)
    mean_probability = float(probability.mean()); observed_rate = float(observed.mean()); absolute = abs(float(error.mean()))
    relative = absolute / mean_probability if mean_probability >= .10 else None
    clipped = np.clip(probability, 1e-12, 1 - 1e-12)
    bands = []
    edges = np.linspace(0, 1, 11)
    for index in range(10):
        mask = (probability >= edges[index]) & (probability < edges[index + 1] if index < 9 else probability <= edges[index + 1])
        if not mask.any():
            continue
        part = frame.loc[mask]
        part_error = error[mask]
        _, b_low, b_high, _ = _cluster_bootstrap(part, part_error, seed + 100 + index)
        bands.append({"lower": float(edges[index]), "upper": float(edges[index + 1]), "pairs": int(mask.sum()),
                      "slates": int(part.slate_date.nunique()), "meanProbability": float(probability[mask].mean()),
                      "observedFrequency": float(observed[mask].mean()), "observedMinusIndependence": float(part_error.mean()),
                      "errorCi95": [b_low, b_high]})
    return {"event": prefix.upper() + "_WIN_BOTH", "pairs": len(frame), "slates": int(frame.slate_date.nunique()),
            "effectiveSampleSize": cluster_coverage(frame),
            "meanIndependenceProbability": mean_probability, "observedJointFrequency": observed_rate,
            "observedMinusIndependence": float(error.mean()), "absoluteCalibrationError": absolute,
            "relativeCalibrationError": relative, "calibrationErrorCi95": [low, high], "calibrationErrorCiWidth": high - low,
            "brier": float(np.mean((probability - observed) ** 2)),
            "logLoss": float(np.mean(-(observed * np.log(clipped) + (1 - observed) * np.log(1 - clipped)))),
            "reliabilityBands": bands}


def holm(rows: list[dict[str, Any]]) -> None:
    eligible = [(index, row["unadjustedPValue"]) for index, row in enumerate(rows) if row.get("unadjustedPValue") is not None]
    ordered = sorted(eligible, key=lambda item: item[1])
    running = 0.0; m = len(ordered)
    for rank, (index, p_value) in enumerate(ordered):
        adjusted = min(1.0, (m - rank) * p_value)
        running = max(running, adjusted)
        rows[index]["holmAdjustedPValue"] = running
    for row in rows:
        row.setdefault("holmAdjustedPValue", None)


def game_bands(games: pd.DataFrame, seed: int) -> list[dict[str, Any]]:
    result = []
    for sport, sport_games in games.groupby("sport", sort=True):
        for index, lower in enumerate(np.linspace(0, .9, 10)):
            upper = lower + .1
            part = sport_games[(sport_games.p_home >= lower) & (sport_games.p_home < upper if upper < 1 else sport_games.p_home <= upper)]
            if part.empty:
                continue
            residual = part.winner_residual.to_numpy(float)
            _, low, high, _ = _cluster_bootstrap(part.rename(columns={"slate_date": "slate_date"}), residual, seed + index)
            result.append({"sport": sport, "lower": float(lower), "upper": float(upper), "games": len(part),
                           "slates": int(part.slate_date.nunique()), "meanProbability": float(part.p_home.mean()),
                           "observedHomeWinRate": float(part.actual_home_win.mean()), "meanCalibrationResidual": float(residual.mean()),
                           "residualCi95": [low, high]})
    return result


def systematic_error(games: pd.DataFrame) -> dict[str, Any]:
    metrics = [*RESIDUALS, "favorite_residual"]
    slate = games.groupby(["sport", "slate_date"], sort=True)[metrics].mean().reset_index()
    by_sport = {}
    for sport, part in slate.groupby("sport", sort=True):
        by_sport[sport] = {metric: {"slates": len(part), "meanSlateResidual": float(part[metric].mean()),
                                    "meanAbsoluteSlateResidual": float(part[metric].abs().mean()),
                                    "fractionPositive": float((part[metric] > 0).mean())} for metric in metrics}
    cross = []
    for sport_a, sport_b in itertools.combinations(sorted(games.sport.unique()), 2):
        a = slate[slate.sport.eq(sport_a)].set_index("slate_date")
        b = slate[slate.sport.eq(sport_b)].set_index("slate_date")
        dates = sorted(set(a.index) & set(b.index))
        row = {"sportPair": sport_a + "+" + sport_b, "sharedDates": len(dates), "correlations": {}}
        for metric in metrics:
            if len(dates) >= 3:
                row["correlations"][metric] = float(np.corrcoef(a.loc[dates, metric], b.loc[dates, metric])[0, 1])
            else:
                row["correlations"][metric] = None
        cross.append(row)
    return {"bySport": by_sport, "crossSportSameDateSlateMeanCorrelations": cross,
            "qualification": "Slate means localize common-direction model error; correlations are descriptive and not causal weather/source attribution."}


def game_level_diagnostics(games: pd.DataFrame) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    for sport, part in games.groupby("sport", sort=True):
        clipped = np.clip(part.p_home.to_numpy(float), 1e-12, 1 - 1e-12)
        actual = part.actual_home_win.to_numpy(float)
        diagnostics[sport] = {
            "games": int(len(part)),
            "meanHomeWinProbability": float(part.p_home.mean()),
            "observedHomeWinRate": float(part.actual_home_win.mean()),
            "observedMinusPredictedHomeWin": float(part.winner_residual.mean()),
            "meanFavoriteResidual": float(part.favorite_residual.mean()),
            "winnerBrier": float(np.mean(np.square(clipped - actual))),
            "winnerLogLoss": float(np.mean(-(actual * np.log(clipped) + (1 - actual) * np.log(1 - clipped)))),
            "meanMarginResidualPoints": float(part.margin_residual.mean()),
            "meanTotalResidualPoints": float(part.total_residual.mean()),
        }
    return {
        "bySport": diagnostics,
        "qualification": "Raw joint calibration includes constituent probability calibration error; residual dependence is the separate diagnostic for common cross-game model error.",
    }


def assess_segment(name: str, frame: pd.DataFrame, games: pd.DataFrame, seed: int) -> dict[str, Any]:
    coverage = {"games": int(len(set(frame.game_a) | set(frame.game_b))), "slates": int(frame.slate_date.nunique()),
                "pairs": int(len(frame)), "sportPairs": sorted(frame.sport_pair.unique().tolist())}
    if frame.empty:
        return {"segment": name, "status": "NO_PAIRS", "coverage": coverage}
    dependencies = [dependence(frame, metric, seed + index * 10) for index, metric in enumerate(RESIDUALS)]
    home = calibration(frame, favorite=False, seed=seed + 70)
    favorite = calibration(frame, favorite=True, seed=seed + 80)
    supported_bands = [band for band in home["reliabilityBands"] if band["pairs"] >= TOLERANCE["minimumReliabilityBinPairs"] and band["slates"] >= TOLERANCE["minimumReliabilityBinSlates"]]
    sample_pass = coverage["games"] >= TOLERANCE["minimumGames"] and coverage["slates"] >= TOLERANCE["minimumSlates"] and coverage["pairs"] >= TOLERANCE["minimumPairs"]
    calibration_pass = (home["absoluteCalibrationError"] <= TOLERANCE["maximumAbsoluteJointCalibrationError"] and
                        (home["relativeCalibrationError"] is None or home["relativeCalibrationError"] <= TOLERANCE["maximumRelativeJointCalibrationErrorWhenMeanProbabilityAtLeast0_10"]) and
                        home["calibrationErrorCiWidth"] <= TOLERANCE["maximumJointCalibrationCiWidth"])
    dependence_pass = all(row.get("status") == "ESTIMATED" and abs(row["pearson"]) <= TOLERANCE["maximumAbsoluteResidualPearson"] and
                          abs(row["spearman"]) <= TOLERANCE["maximumAbsoluteResidualSpearman"] and
                          row["pearsonCi95"][0] >= TOLERANCE["correlationCiLower"] and row["pearsonCi95"][1] <= TOLERANCE["correlationCiUpper"]
                          for row in dependencies)
    reliability_pass = len(supported_bands) >= 2 and all(abs(row["observedMinusIndependence"]) <= TOLERANCE["maximumReliabilityBinAbsoluteError"] for row in supported_bands)
    return {"segment": name, "status": "ESTIMATED", "coverage": coverage, "homeHomeJointCalibration": home,
            "modelFavoriteJointCalibration": favorite, "residualDependence": dependencies,
            "practicalGate": {"sampleSize": sample_pass, "jointCalibration": calibration_pass, "residualDependence": dependence_pass,
                              "reliability": reliability_pass, "supportedReliabilityBins": len(supported_bands),
                              "passesAllNumericalCriteria": bool(sample_pass and calibration_pass and dependence_pass and reliability_pass)}}


def run(nfl: Path, nfl_schedule: Path, nba: Path, cfb: Path, created_at_utc: str) -> dict[str, Any]:
    nfl_games, nfl_source = load_nfl(nfl, nfl_schedule)
    nba_games, nba_source = load_nba(nba)
    cfb_games, cfb_source = load_cfb(cfb)
    games = pd.concat([nfl_games, nba_games, cfb_games], ignore_index=True)
    if not games.chronology_verified.all():
        raise ValueError("CHRONOLOGY_NOT_VERIFIED")
    games = games.sort_values(["slate_date", "sport", "game_key"], kind="mergesort").reset_index(drop=True)
    pairs = pair_rows(games)
    primary = pairs[~pairs.shared_team & pairs.regular_both].copy()
    segments: list[tuple[str, pd.DataFrame]] = [("ALL_UNRELATED_REGULAR", primary),
        ("SAME_SPORT_UNRELATED_REGULAR", primary[primary.same_sport]),
        ("CROSS_SPORT_UNRELATED_REGULAR", primary[~primary.same_sport])]
    for sport_pair, part in primary.groupby("sport_pair", sort=True):
        segments.append(("SPORT_PAIR_" + sport_pair.replace("+", "_"), part))
    for timing, part in primary.groupby("timing_class", sort=True):
        segments.append(("TIMING_" + timing, part))
    for leg_class, part in primary.groupby("home_leg_class", sort=True):
        segments.append(("HOME_LEGS_" + leg_class.replace("+", "_"), part))
    segments.extend([("POSTSEASON_ANY", pairs[pairs.postseason_any]), ("SHARED_TEAM", pairs[pairs.shared_team]),
                     ("POTENTIAL_SEQUENTIAL_INCENTIVE", pairs[pairs.potential_sequential_incentive])])
    results = [assess_segment(name, part, games, SEED + index * 1000) for index, (name, part) in enumerate(segments)]
    correlation_family = [row for result in results if result["segment"].startswith("SPORT_PAIR_")
                          for row in result.get("residualDependence", [])]
    holm(correlation_family)
    coverage = {"games": len(games), "slates": int(games.slate_date.nunique()), "pairs": len(pairs),
                "primaryPairs": len(primary), "sameSportPairs": int(pairs.same_sport.sum()),
                "crossSportPairs": int((~pairs.same_sport).sum()), "sharedTeamPairs": int(pairs.shared_team.sum()),
                "postseasonPairs": int(pairs.postseason_any.sum()), "timingCounts": {str(k): int(v) for k, v in pairs.timing_class.value_counts().items()},
                "bySport": {sport: {"games": len(part), "slates": int(part.slate_date.nunique()),
                                     "firstDate": part.slate_date.min(), "lastDate": part.slate_date.max()}
                            for sport, part in games.groupby("sport", sort=True)},
                "bySportPair": {str(k): int(v) for k, v in pairs.sport_pair.value_counts().sort_index().items()}}
    result = {"schemaVersion": SCHEMA, "createdAtUtc": created_at_utc,
              "studyDesignSha256": "5749b2457b52589a612b3a2597341185a5baf9b814d300715ec115a4c8dda87f",
              "methodologyAmendmentApplied": True, "sources": [nfl_source, nba_source, cfb_source], "coverage": coverage,
              "gameLevelDiagnostics": game_level_diagnostics(games),
              "gameCalibrationBands": game_bands(games, SEED + 90000), "segments": results,
              "multipleComparisonControl": {
                  "family": "Five residual-correlation tests within each SPORT_PAIR segment",
                  "method": "Holm adjusted normal-approximation p-values using whole-slate bootstrap standard errors",
                  "tests": int(len(correlation_family)),
                  "scope": "Exploratory significance control only; the predeclared practical gates determine disposition.",
              },
              "systematicModelError": systematic_error(games), "tolerances": TOLERANCE,
              "unsupported": [
                  "MLB: no admitted chronological whole-game Development forecast ledger; Final OOT and sealed data were not opened.",
                  "Totals joint calibration: retained point expectations are not line-event probabilities.",
                  "NBA start-window analysis: Development ledger records dates but not exact tip times.",
                  "Shared weather/geography: no common governed pregame environmental fields across ledgers.",
                  "Standings/tournament incentive causality: identifiers are insufficient to prove absence of changing later-game incentives.",
                  "Prospective certification: all admitted ledgers are reconstructed chronological evidence without physical per-game publication clocks."
              ],
              "accounting": {"providerCalls": 0, "providerBytes": 0, "costUsd": 0, "sportsbookCalls": 0,
                             "aispWrites": 0, "exchangeWrites": 0, "modelRuns": 0, "sealedReads": 0, "finalOotReads": 0}}
    return result


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nfl", type=Path, required=True)
    parser.add_argument("--nfl-schedule", type=Path, required=True)
    parser.add_argument("--nba", type=Path, required=True)
    parser.add_argument("--cfb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created-at-utc", required=True,
                        help="Frozen ISO-8601 creation timestamp retained for deterministic replay.")
    args = parser.parse_args()
    result = run(args.nfl, args.nfl_schedule, args.nba, args.cfb, args.created_at_utc)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output), "sha256": sha(args.output), "coverage": result["coverage"], "accounting": result["accounting"]}, sort_keys=True))


if __name__ == "__main__":
    main()
