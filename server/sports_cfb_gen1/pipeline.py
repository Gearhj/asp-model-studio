from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


SEED = 20260914
SIMULATION_COUNT = 10_000
ROLES = {
    "development": list(range(2014, 2023)),
    "validation": [2023, 2024],
    "historical_holdout": [2025],
    "prospective_current": [2026],
}
POINT_CANDIDATES = {
    "ridge_alpha10": ("ridge", {"alpha": 10.0}),
    "ridge_alpha100": ("ridge", {"alpha": 100.0}),
    "hgb_l2_10": ("hgb", {"l2_regularization": 10.0}),
    "hgb_l2_50": ("hgb", {"l2_regularization": 50.0}),
}
FEATURE_COLUMNS = [
    "neutral_site",
    "conference_competition",
    "week",
    "elo_home",
    "elo_away",
    "elo_difference_with_site",
    "home_rest_days_capped21",
    "away_rest_days_capped21",
    "rest_difference",
    "home_season_opener",
    "away_season_opener",
    "home_long_gap",
    "away_long_gap",
    "home_current_season_games",
    "away_current_season_games",
    "home_points_for_season",
    "away_points_for_season",
    "home_points_allowed_season",
    "away_points_allowed_season",
    "home_margin_trailing5",
    "away_margin_trailing5",
    "home_total_trailing5",
    "away_total_trailing5",
    "home_total_yards_season",
    "away_total_yards_season",
    "home_yards_allowed_season",
    "away_yards_allowed_season",
    "home_turnovers_season",
    "away_turnovers_season",
    "home_takeaways_season",
    "away_takeaways_season",
    "home_prior_margin_shrunk",
    "away_prior_margin_shrunk",
    "home_prior_total_shrunk",
    "away_prior_total_shrunk",
]


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path.resolve()), "bytes": len(raw), "physicalSha256": hashlib.sha256(raw).hexdigest()}


def _read_seasons(root: Path, subdir: str, pattern: str, seasons: Iterable[int]) -> pd.DataFrame:
    frames = []
    for season in seasons:
        path = root / subdir / pattern.format(season=season)
        frame = pd.read_parquet(path)
        frame["_source_path"] = str(path.resolve())
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype("string").str.replace(",", "", regex=False), errors="coerce")


def _float_or_nan(value: Any) -> float:
    return float(value) if pd.notna(value) else float("nan")


def load_population(source_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    schedules = _read_seasons(
        source_root, "espn_cfb_schedules", "cfb_schedule_{season}.parquet", range(2014, 2027)
    )
    teams = _read_seasons(source_root, "espn_cfb_teams", "cfb_teams_{season}.parquet", range(2014, 2027))
    boxes = _read_seasons(source_root, "espn_cfb_team_box", "team_box_{season}.parquet", range(2014, 2026))
    lines = _read_seasons(source_root, "espn_cfb_linescores", "linescores_{season}.parquet", range(2014, 2026))

    schedules["scheduled_at"] = pd.to_datetime(schedules["game_date"], utc=True, errors="coerce")
    schedules["home_score"] = pd.to_numeric(schedules["home_score"], errors="coerce")
    schedules["away_score"] = pd.to_numeric(schedules["away_score"], errors="coerce")
    schedules["is_final"] = schedules["status"].eq("STATUS_FINAL")
    schedules["score_supported"] = schedules["is_final"] & schedules[["home_score", "away_score"]].notna().all(axis=1)
    schedules["home_margin"] = schedules["home_score"] - schedules["away_score"]
    schedules["total_points"] = schedules["home_score"] + schedules["away_score"]
    schedules["home_win"] = (schedules["home_score"] > schedules["away_score"]).astype(float)

    team_cols = [
        "season", "team_id", "display_name", "abbreviation", "is_fbs", "is_exhibition",
        "division", "conference_id", "conference_name", "classification",
    ]
    duplicate_team_keys = int(teams.duplicated(["season", "team_id"], keep=False).sum())
    team_dim = teams[team_cols].drop_duplicates(["season", "team_id"], keep="first")
    home_dim = team_dim.add_prefix("home_")
    away_dim = team_dim.add_prefix("away_")
    games = schedules.merge(
        home_dim, left_on=["season", "home_id"], right_on=["home_season", "home_team_id"], how="left",
        validate="many_to_one",
    ).merge(
        away_dim, left_on=["season", "away_id"], right_on=["away_season", "away_team_id"], how="left",
        validate="many_to_one",
    )

    boxes = boxes.copy()
    boxes["total_yards_num"] = _numeric(boxes["totalYards"])
    boxes["turnovers_num"] = _numeric(boxes["turnovers"])
    box_key_counts = boxes.groupby(["game_id", "team_id"], dropna=False).size().rename("box_key_rows")
    box_unique = boxes.drop_duplicates(["game_id", "team_id"], keep="first")
    home_box = box_unique[["game_id", "team_id", "total_yards_num", "turnovers_num"]].rename(columns={
        "team_id": "home_box_team_id", "total_yards_num": "home_total_yards", "turnovers_num": "home_turnovers"
    })
    away_box = box_unique[["game_id", "team_id", "total_yards_num", "turnovers_num"]].rename(columns={
        "team_id": "away_box_team_id", "total_yards_num": "away_total_yards", "turnovers_num": "away_turnovers"
    })
    games = games.merge(
        home_box, left_on=["game_id", "home_id"], right_on=["game_id", "home_box_team_id"], how="left",
        validate="one_to_one",
    ).merge(
        away_box, left_on=["game_id", "away_id"], right_on=["game_id", "away_box_team_id"], how="left",
        validate="one_to_one",
    )
    games["both_box_rows"] = games["home_box_team_id"].notna() & games["away_box_team_id"].notna()

    lines = lines.copy()
    lines["period"] = pd.to_numeric(lines["period"], errors="coerce")
    lines["period_points"] = _numeric(lines["value"])
    line_team = lines.groupby(["game_id", "team_id"], as_index=False).agg(
        period_count=("period", "count"), max_period=("period", "max"), period_score_sum=("period_points", "sum")
    )
    home_line = line_team.rename(columns={
        "team_id": "home_line_team_id", "period_count": "home_period_count",
        "max_period": "home_max_period", "period_score_sum": "home_period_score_sum",
    })
    away_line = line_team.rename(columns={
        "team_id": "away_line_team_id", "period_count": "away_period_count",
        "max_period": "away_max_period", "period_score_sum": "away_period_score_sum",
    })
    games = games.merge(
        home_line, left_on=["game_id", "home_id"], right_on=["game_id", "home_line_team_id"], how="left",
        validate="one_to_one",
    ).merge(
        away_line, left_on=["game_id", "away_id"], right_on=["game_id", "away_line_team_id"], how="left",
        validate="one_to_one",
    )
    games["period_supported"] = games["home_line_team_id"].notna() & games["away_line_team_id"].notna()
    games["period_reconciles"] = (
        games["period_supported"]
        & games["home_period_score_sum"].eq(games["home_score"])
        & games["away_period_score_sum"].eq(games["away_score"])
    )
    games["overtime"] = games[["home_max_period", "away_max_period"]].max(axis=1).gt(4)

    games["identity_supported"] = games["home_team_id"].notna() & games["away_team_id"].notna()
    games["both_fbs"] = games["home_is_fbs"].fillna(False) & games["away_is_fbs"].fillna(False)
    games["either_exhibition"] = games["home_is_exhibition"].fillna(True) | games["away_is_exhibition"].fillna(True)
    games["tied_final"] = games["score_supported"] & games["home_score"].eq(games["away_score"])
    games["late_regular_unclassified"] = games["score_supported"] & games["season_type"].eq(2) & games["week"].gt(14)
    games["postseason"] = games["score_supported"] & games["season_type"].eq(3)
    games["primary"] = (
        games["score_supported"]
        & games["identity_supported"]
        & games["both_fbs"]
        & ~games["either_exhibition"]
        & games["season_type"].eq(2)
        & games["week"].le(14)
        & ~games["tied_final"]
    )
    games["context_eligible"] = (
        games["score_supported"] & games["identity_supported"] & ~games["either_exhibition"] & ~games["tied_final"]
    )
    games["role"] = "outside"
    for role, seasons in ROLES.items():
        games.loc[games["season"].isin(seasons), "role"] = role

    unordered_date = games.assign(
        low_id=games[["home_id", "away_id"]].min(axis=1),
        high_id=games[["home_id", "away_id"]].max(axis=1),
        calendar_date=games["scheduled_at"].dt.date,
    )
    duplicated_matchups = int(unordered_date.duplicated(["calendar_date", "low_id", "high_id"], keep=False).sum())
    diagnostics = {
        "scheduleRows": int(len(schedules)),
        "duplicateSourceIdRows": int(schedules.duplicated("game_id", keep=False).sum()),
        "duplicateTeamDateMatchupRows": duplicated_matchups,
        "duplicateSeasonTeamIdentityRows": duplicate_team_keys,
        "duplicateTeamBoxKeys": int((box_key_counts > 1).sum()),
        "missingScheduledTimestamps": int(games["scheduled_at"].isna().sum()),
    }
    return games.sort_values(["scheduled_at", "game_id"]).reset_index(drop=True), diagnostics


@dataclass
class TeamState:
    elo: float
    rating_season: int | None = None
    current_season: int | None = None
    current: list[dict[str, float]] = field(default_factory=list)
    trailing: list[dict[str, float]] = field(default_factory=list)
    prior_summary: dict[str, float] = field(default_factory=dict)
    prior_count: int = 0
    prior_season: int | None = None
    last_date: pd.Timestamp | None = None


STAT_DEFAULTS = {
    "points_for": 28.0,
    "points_against": 28.0,
    "margin": 0.0,
    "total": 56.0,
    "yards_for": 375.0,
    "yards_against": 375.0,
    "turnovers": 1.5,
    "takeaways": 1.5,
}


def _mean(records: list[dict[str, float]], key: str) -> float:
    values = [float(row[key]) for row in records if key in row and np.isfinite(row[key])]
    return float(np.mean(values)) if values else float("nan")


def _season_value(state: TeamState, key: str) -> float:
    value = _mean(state.current, key)
    if np.isfinite(value):
        return value
    default = STAT_DEFAULTS[key]
    if state.prior_count and key in state.prior_summary and np.isfinite(state.prior_summary[key]):
        weight = state.prior_count / (state.prior_count + 5.0)
        return float(weight * state.prior_summary[key] + (1.0 - weight) * default)
    return default


def _trailing_value(state: TeamState, key: str) -> float:
    value = _mean(state.trailing[-5:], key)
    return value if np.isfinite(value) else _season_value(state, key)


def _advance_season(state: TeamState, season: int, is_fbs: bool) -> None:
    prior = 1500.0 if is_fbs else 1350.0
    if state.rating_season != season:
        state.elo = prior + (state.elo - prior) * (2.0 / 3.0)
        state.rating_season = season
    if state.current_season != season:
        if state.current and state.current_season == season - 1:
            state.prior_summary = {key: _mean(state.current, key) for key in STAT_DEFAULTS}
            state.prior_count = len(state.current)
            state.prior_season = state.current_season
        elif state.current_season is not None:
            state.prior_summary = {}
            state.prior_count = 0
            state.prior_season = None
        state.current = []
        state.current_season = season
        state.last_date = None


def _rest_features(state: TeamState, when: pd.Timestamp) -> tuple[float, int, int]:
    if state.last_date is None:
        return 14.0, 1, 0
    days = max(0.0, float((when - state.last_date).total_seconds() / 86400.0))
    return min(days, 21.0), 0, int(days > 21.0)


def build_features(games: pd.DataFrame) -> pd.DataFrame:
    states: dict[int, TeamState] = {}
    rows: list[dict[str, Any]] = []
    for scheduled_at, group in games.groupby("scheduled_at", sort=True, dropna=False):
        pending: list[tuple[pd.Series, TeamState, TeamState, float, float]] = []
        for _, game in group.sort_values("game_id").iterrows():
            season = int(game["season"])
            home_id, away_id = int(game["home_id"]), int(game["away_id"])
            home_fbs, away_fbs = bool(game["home_is_fbs"]), bool(game["away_is_fbs"])
            hs = states.setdefault(home_id, TeamState(1500.0 if home_fbs else 1350.0))
            avs = states.setdefault(away_id, TeamState(1500.0 if away_fbs else 1350.0))
            _advance_season(hs, season, home_fbs)
            _advance_season(avs, season, away_fbs)
            home_rest, home_open, home_gap = _rest_features(hs, scheduled_at)
            away_rest, away_open, away_gap = _rest_features(avs, scheduled_at)
            site_points = 0.0 if bool(game["neutral_site"]) else 55.0
            elo_diff = hs.elo - avs.elo + site_points
            elo_prob = 1.0 / (1.0 + 10.0 ** (-elo_diff / 400.0))
            max_source = max([value for value in (hs.last_date, avs.last_date) if value is not None], default=pd.NaT)
            row = {
                "game_id": int(game["game_id"]),
                "season": season,
                "week": int(game["week"]),
                "scheduled_at": scheduled_at,
                "home_id": home_id,
                "away_id": away_id,
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "neutral_site": int(bool(game["neutral_site"])),
                "conference_competition": int(bool(game["conference_competition"])),
                "primary": bool(game["primary"]),
                "context_eligible": bool(game["context_eligible"]),
                "role": game["role"],
                "is_final": bool(game["is_final"]),
                "season_type": int(game["season_type"]),
                "home_is_fbs": home_fbs,
                "away_is_fbs": away_fbs,
                "both_fbs": bool(game["both_fbs"]),
                "postseason": bool(game["postseason"]),
                "late_regular_unclassified": bool(game["late_regular_unclassified"]),
                "overtime": bool(game["overtime"]),
                "home_margin": float(game["home_margin"]) if game["score_supported"] else np.nan,
                "total_points": float(game["total_points"]) if game["score_supported"] else np.nan,
                "home_score": float(game["home_score"]) if game["score_supported"] else np.nan,
                "away_score": float(game["away_score"]) if game["score_supported"] else np.nan,
                "home_win": float(game["home_win"]) if game["score_supported"] else np.nan,
                "elo_home": hs.elo,
                "elo_away": avs.elo,
                "elo_difference_with_site": elo_diff,
                "elo_home_win_probability": elo_prob,
                "home_rest_days_capped21": home_rest,
                "away_rest_days_capped21": away_rest,
                "rest_difference": home_rest - away_rest,
                "home_season_opener": home_open,
                "away_season_opener": away_open,
                "home_long_gap": home_gap,
                "away_long_gap": away_gap,
                "home_current_season_games": len(hs.current),
                "away_current_season_games": len(avs.current),
                "home_points_for_season": _season_value(hs, "points_for"),
                "away_points_for_season": _season_value(avs, "points_for"),
                "home_points_allowed_season": _season_value(hs, "points_against"),
                "away_points_allowed_season": _season_value(avs, "points_against"),
                "home_margin_trailing5": _trailing_value(hs, "margin"),
                "away_margin_trailing5": _trailing_value(avs, "margin"),
                "home_total_trailing5": _trailing_value(hs, "total"),
                "away_total_trailing5": _trailing_value(avs, "total"),
                "home_total_yards_season": _season_value(hs, "yards_for"),
                "away_total_yards_season": _season_value(avs, "yards_for"),
                "home_yards_allowed_season": _season_value(hs, "yards_against"),
                "away_yards_allowed_season": _season_value(avs, "yards_against"),
                "home_turnovers_season": _season_value(hs, "turnovers"),
                "away_turnovers_season": _season_value(avs, "turnovers"),
                "home_takeaways_season": _season_value(hs, "takeaways"),
                "away_takeaways_season": _season_value(avs, "takeaways"),
                "home_prior_margin_shrunk": _season_value(hs, "margin") if not hs.current else (
                    hs.prior_summary.get("margin", 0.0) * hs.prior_count / (hs.prior_count + 5.0)
                ),
                "away_prior_margin_shrunk": _season_value(avs, "margin") if not avs.current else (
                    avs.prior_summary.get("margin", 0.0) * avs.prior_count / (avs.prior_count + 5.0)
                ),
                "home_prior_total_shrunk": _season_value(hs, "total") if not hs.current else (
                    (hs.prior_summary.get("total", 56.0) * hs.prior_count + 56.0 * 5.0) / (hs.prior_count + 5.0)
                ),
                "away_prior_total_shrunk": _season_value(avs, "total") if not avs.current else (
                    (avs.prior_summary.get("total", 56.0) * avs.prior_count + 56.0 * 5.0) / (avs.prior_count + 5.0)
                ),
                "feature_max_source_game_date": max_source,
            }
            rows.append(row)
            pending.append((game, hs, avs, elo_prob, site_points))

        for game, hs, avs, elo_prob, _ in pending:
            if not bool(game["context_eligible"]):
                continue
            home_score, away_score = float(game["home_score"]), float(game["away_score"])
            home_margin = home_score - away_score
            actual = 1.0 if home_margin > 0 else 0.0
            delta = 24.0 * (actual - elo_prob)
            hs.elo += delta
            avs.elo -= delta
            home_record = {
                "points_for": home_score, "points_against": away_score, "margin": home_margin,
                "total": home_score + away_score, "yards_for": _float_or_nan(game["home_total_yards"]),
                "yards_against": _float_or_nan(game["away_total_yards"]), "turnovers": _float_or_nan(game["home_turnovers"]),
                "takeaways": _float_or_nan(game["away_turnovers"]),
            }
            away_record = {
                "points_for": away_score, "points_against": home_score, "margin": -home_margin,
                "total": home_score + away_score, "yards_for": _float_or_nan(game["away_total_yards"]),
                "yards_against": _float_or_nan(game["home_total_yards"]), "turnovers": _float_or_nan(game["away_turnovers"]),
                "takeaways": _float_or_nan(game["home_turnovers"]),
            }
            for state, record in ((hs, home_record), (avs, away_record)):
                state.current.append(record)
                state.trailing.append(record)
                state.trailing = state.trailing[-5:]
                state.last_date = game["scheduled_at"]

    frame = pd.DataFrame(rows).sort_values(["scheduled_at", "game_id"]).reset_index(drop=True)
    valid_source = frame["feature_max_source_game_date"].isna() | (
        frame["feature_max_source_game_date"] < frame["scheduled_at"]
    )
    if not bool(valid_source.all()):
        raise RuntimeError("chronological feature source date reaches or exceeds target kickoff")
    return frame


def make_model(family: str, parameters: dict[str, Any]) -> Pipeline:
    if family == "ridge":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=float(parameters["alpha"]))),
        ])
    if family == "hgb":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                loss="squared_error", learning_rate=0.05, max_iter=200, max_leaf_nodes=15,
                min_samples_leaf=30, l2_regularization=float(parameters["l2_regularization"]),
                early_stopping=False, random_state=SEED,
            )),
        ])
    raise ValueError(family)


def _fit_pair(train: pd.DataFrame, family: str, parameters: dict[str, Any]) -> dict[str, Pipeline]:
    margin = make_model(family, parameters).fit(train[FEATURE_COLUMNS], train["home_margin"])
    total = make_model(family, parameters).fit(train[FEATURE_COLUMNS], train["total_points"])
    return {"margin": margin, "total": total}


def _point_outputs(margin: np.ndarray, total: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (total + margin) / 2.0, (total - margin) / 2.0


def season_forward_predictions(features: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, dict[str, Any]]]:
    primary = features[features["primary"] & features["is_final"]].copy()
    predictions: list[pd.DataFrame] = []
    fitted_by_season: dict[int, dict[str, Any]] = {}
    for season in range(2016, 2026):
        train = primary[(primary["season"] >= 2014) & (primary["season"] < season)]
        target = primary[primary["season"] == season].copy()
        if train.empty or target.empty:
            continue
        base_margin_home = float(train.loc[train["neutral_site"].eq(0), "home_margin"].mean())
        base_margin_neutral = float(train.loc[train["neutral_site"].eq(1), "home_margin"].mean())
        base_total_home = float(train.loc[train["neutral_site"].eq(0), "total_points"].mean())
        base_total_neutral = float(train.loc[train["neutral_site"].eq(1), "total_points"].mean())
        base_home_prob = float(train.loc[train["neutral_site"].eq(0), "home_win"].mean())
        target["league_pred_margin"] = np.where(target["neutral_site"].eq(1), base_margin_neutral, base_margin_home)
        target["league_pred_total"] = np.where(target["neutral_site"].eq(1), base_total_neutral, base_total_home)
        target["league_home_win_probability"] = np.where(target["neutral_site"].eq(1), 0.5, base_home_prob)
        target["league_pred_home"], target["league_pred_away"] = _point_outputs(
            target["league_pred_margin"].to_numpy(), target["league_pred_total"].to_numpy()
        )
        fitted_by_season[season] = {"trainingGames": int(len(train)), "candidates": {}}
        for name, (family, parameters) in POINT_CANDIDATES.items():
            models = _fit_pair(train, family, parameters)
            margin = models["margin"].predict(target[FEATURE_COLUMNS])
            total = models["total"].predict(target[FEATURE_COLUMNS])
            home, away = _point_outputs(margin, total)
            target[f"{name}_pred_margin"] = margin
            target[f"{name}_pred_total"] = total
            target[f"{name}_pred_home"] = home
            target[f"{name}_pred_away"] = away
            fitted_by_season[season]["candidates"][name] = {
                "family": family, "parameters": parameters, "trainingThroughSeason": season - 1,
            }
        predictions.append(target)
    result = pd.concat(predictions, ignore_index=True).sort_values(["scheduled_at", "game_id"])
    dev = result[result["season"].between(2016, 2022)]
    calibrators: dict[str, LogisticRegression] = {}
    for name in ["league", *POINT_CANDIDATES]:
        column = f"{name}_pred_margin"
        calibrator = LogisticRegression(C=1.0, solver="lbfgs", random_state=SEED).fit(
            dev[[column]].to_numpy(), dev["home_win"].astype(int).to_numpy()
        )
        result[f"{name}_calibrated_home_win_probability"] = calibrator.predict_proba(
            result[[column]].to_numpy()
        )[:, 1]
        calibrators[name] = calibrator
    result["elo_home_win_probability"] = result["elo_home_win_probability"].clip(1e-6, 1 - 1e-6)
    result.attrs["calibrators"] = calibrators
    return result, fitted_by_season


def _log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return float(np.mean(-(y * np.log(p) + (1 - y) * np.log(1 - p))))


def score_point_predictions(predictions: pd.DataFrame, model: str, probability: str = "calibrated") -> dict[str, float]:
    y = predictions["home_win"].to_numpy()
    if model == "elo":
        p = predictions["elo_home_win_probability"].to_numpy()
        result: dict[str, float] = {}
    else:
        p_col = f"{model}_{probability}_home_win_probability"
        p = predictions[p_col].to_numpy()
        result = {
            "homeMarginMae": float(np.mean(np.abs(predictions[f"{model}_pred_margin"] - predictions["home_margin"]))),
            "totalPointsMae": float(np.mean(np.abs(predictions[f"{model}_pred_total"] - predictions["total_points"]))),
            "homeScoreMae": float(np.mean(np.abs(predictions[f"{model}_pred_home"] - predictions["home_score"]))),
            "awayScoreMae": float(np.mean(np.abs(predictions[f"{model}_pred_away"] - predictions["away_score"]))),
        }
    result.update({
        "games": int(len(predictions)),
        "winnerLogLoss": _log_loss(y, p),
        "binaryBrier": float(np.mean((p - y) ** 2)),
        "correctWinnerCount": int(np.sum((p >= 0.5) == y.astype(bool))),
        "winnerAccuracy": float(np.mean((p >= 0.5) == y.astype(bool))),
    })
    return result


def calibration_table(predictions: pd.DataFrame, probability_column: str) -> list[dict[str, Any]]:
    frame = predictions[[probability_column, "home_win"]].copy()
    frame["band"] = pd.cut(
        frame[probability_column], bins=[0, .2, .35, .5, .65, .8, 1], include_lowest=True,
        labels=["0-.20", ".20-.35", ".35-.50", ".50-.65", ".65-.80", ".80-1"],
    )
    rows = []
    for band, part in frame.groupby("band", observed=True):
        rows.append({
            "band": str(band), "games": int(len(part)),
            "meanPrediction": float(part[probability_column].mean()),
            "observedHomeWinRate": float(part["home_win"].mean()),
        })
    return rows


def empirical_crps(draws: np.ndarray, observed: float) -> float:
    x = np.sort(np.asarray(draws, dtype=float))
    n = len(x)
    first = np.mean(np.abs(x - observed))
    weights = 2 * np.arange(1, n + 1) - n - 1
    second_half = float(np.sum(weights * x) / (n * n))
    return float(first - second_half)


def energy_score(home: np.ndarray, away: np.ndarray, observed_home: float, observed_away: float) -> float:
    first = np.mean(np.hypot(home - observed_home, away - observed_away))
    paired = np.roll(np.arange(len(home)), len(home) // 2)
    second = np.mean(np.hypot(home - home[paired], away - away[paired]))
    return float(first - 0.5 * second)


def _seed_for(game_id: int, label: str) -> int:
    raw = hashlib.sha256(f"{SEED}|{game_id}|{label}".encode()).digest()
    return int.from_bytes(raw[:8], "big") % (2**32 - 1)


def simulate_paired_residuals(
    target: pd.Series,
    donors: pd.DataFrame,
    model: str,
    draw_count: int = SIMULATION_COUNT,
    low_total_threshold: float | None = None,
    high_total_threshold: float | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if len(donors) < 500:
        raise ValueError("at least 500 earlier chronological donors are required")
    rng = np.random.default_rng(_seed_for(int(target["game_id"]), model))
    rh = (donors["home_score"] - donors[f"{model}_pred_home"]).to_numpy(float)
    ra = (donors["away_score"] - donors[f"{model}_pred_away"]).to_numpy(float)
    pred_home = float(target[f"{model}_pred_home"])
    pred_away = float(target[f"{model}_pred_away"])

    def sample(size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        idx = rng.integers(0, len(donors), size=size)
        raw_home = pred_home + rh[idx]
        raw_away = pred_away + ra[idx]
        floor_home = np.maximum(raw_home, 0.0)
        floor_away = np.maximum(raw_away, 0.0)
        home = np.floor(floor_home) + (rng.random(size) < (floor_home - np.floor(floor_home)))
        away = np.floor(floor_away) + (rng.random(size) < (floor_away - np.floor(floor_away)))
        return raw_home, raw_away, home.astype(np.int16), away.astype(np.int16)

    raw_home, raw_away, home, away = sample(draw_count)
    initial_ties = home == away
    tie_draws = int(initial_ties.sum())
    total_resamples = 0
    remaining = initial_ties.copy()
    rounds = 0
    while remaining.any() and rounds < 50:
        count = int(remaining.sum())
        _, _, repl_home, repl_away = sample(count)
        home[remaining] = repl_home
        away[remaining] = repl_away
        total_resamples += count
        remaining = home == away
        rounds += 1
    if remaining.any():
        raise RuntimeError("tie-conditioned residual resampling did not terminate")
    frame = pd.DataFrame({
        "draw": np.arange(draw_count, dtype=np.int32),
        "home_score": home,
        "away_score": away,
    })
    frame["total"] = frame["home_score"] + frame["away_score"]
    frame["home_margin"] = frame["home_score"] - frame["away_score"]
    accounting = {
        "drawCount": draw_count,
        "donorCount": int(len(donors)),
        "donorLatestKickoff": donors["scheduled_at"].max().isoformat(),
        "rawNegativeHomeCount": int((raw_home < 0).sum()),
        "rawNegativeAwayCount": int((raw_away < 0).sum()),
        "initialRoundedTieCount": tie_draws,
        "tieResampleAttempts": total_resamples,
        "tieResolutionRounds": rounds,
        "finalTieCount": int((home == away).sum()),
        "rawHomeMean": float(raw_home.mean()),
        "rawAwayMean": float(raw_away.mean()),
        "finalHomeMean": float(home.mean()),
        "finalAwayMean": float(away.mean()),
        "homeWinProbability": float((home > away).mean()),
    }
    if low_total_threshold is not None and high_total_threshold is not None:
        raw_total = raw_home + raw_away
        final_total = home + away
        accounting.update({
            "lowTotalThreshold": float(low_total_threshold),
            "highTotalThreshold": float(high_total_threshold),
            "rawLowTotalProbability": float((raw_total <= low_total_threshold).mean()),
            "finalLowTotalProbability": float((final_total <= low_total_threshold).mean()),
            "rawHighTotalProbability": float((raw_total >= high_total_threshold).mean()),
            "finalHighTotalProbability": float((final_total >= high_total_threshold).mean()),
        })
    return frame, accounting


def score_distribution(
    draws: pd.DataFrame,
    target: pd.Series,
    low_total_threshold: float | None = None,
    high_total_threshold: float | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "game_id": int(target["game_id"]), "season": int(target["season"]),
        "week": int(target["week"]), "scheduled_at": target["scheduled_at"],
        "neutral_site": int(target["neutral_site"]),
        "conference_competition": int(target["conference_competition"]),
        "home_margin": float(target["home_margin"]), "total_points": float(target["total_points"]),
        "home_score": float(target["home_score"]), "away_score": float(target["away_score"]),
        "home_win": float(target["home_win"]),
        "jointEnergyScore": energy_score(
            draws["home_score"].to_numpy(), draws["away_score"].to_numpy(),
            float(target["home_score"]), float(target["away_score"]),
        ),
        "homeCrps": empirical_crps(draws["home_score"].to_numpy(), float(target["home_score"])),
        "awayCrps": empirical_crps(draws["away_score"].to_numpy(), float(target["away_score"])),
        "totalCrps": empirical_crps(draws["total"].to_numpy(), float(target["total_points"])),
        "marginCrps": empirical_crps(draws["home_margin"].to_numpy(), float(target["home_margin"])),
        "jointHomeWinProbability": float((draws["home_margin"] > 0).mean()),
    }
    p = np.clip(result["jointHomeWinProbability"], 1e-12, 1 - 1e-12)
    result["jointWinnerLogLoss"] = float(-(target["home_win"] * np.log(p) + (1-target["home_win"]) * np.log(1-p)))
    result["jointBinaryBrier"] = float((p - target["home_win"]) ** 2)
    if low_total_threshold is not None and high_total_threshold is not None:
        low_probability = float((draws["total"] <= low_total_threshold).mean())
        high_probability = float((draws["total"] >= high_total_threshold).mean())
        observed_low = float(target["total_points"] <= low_total_threshold)
        observed_high = float(target["total_points"] >= high_total_threshold)
        result.update({
            "predictedLowTotalProbability": low_probability,
            "observedLowTotal": observed_low,
            "lowTotalBrier": float((low_probability - observed_low) ** 2),
            "predictedHighTotalProbability": high_probability,
            "observedHighTotal": observed_high,
            "highTotalBrier": float((high_probability - observed_high) ** 2),
        })
    for metric, observed in (
        ("home_score", target["home_score"]), ("away_score", target["away_score"]),
        ("total", target["total_points"]), ("home_margin", target["home_margin"]),
    ):
        values = draws[metric].to_numpy()
        for level in (50, 80, 90):
            alpha = (100-level)/200
            low, high = np.quantile(values, [alpha, 1-alpha])
            prefix = {"home_score":"home", "away_score":"away", "total":"total", "home_margin":"margin"}[metric]
            result[f"{prefix}Coverage{level}"] = int(low <= observed <= high)
            result[f"{prefix}Width{level}"] = float(high-low)
    return result


def frequency_rows(game_id: int, draws: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in ("home_score", "away_score", "total", "home_margin"):
        counts = draws[metric].value_counts().sort_index()
        for value, count in counts.items():
            rows.append({
                "game_id": game_id, "metric": metric, "value": int(value),
                "count": int(count), "draw_count": int(len(draws)),
            })
    return pd.DataFrame(rows)


def aggregate_distribution_scores(scores: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {"games": int(len(scores))}
    for col in [
        "jointEnergyScore", "homeCrps", "awayCrps", "totalCrps", "marginCrps",
        "jointWinnerLogLoss", "jointBinaryBrier", "lowTotalBrier", "highTotalBrier",
    ]:
        if col in scores:
            result[col] = float(scores[col].mean())
    for prefix in ("Low", "High"):
        predicted = f"predicted{prefix}TotalProbability"
        observed = f"observed{prefix}Total"
        if predicted in scores:
            result[f"meanPredicted{prefix}TotalProbability"] = float(scores[predicted].mean())
            result[f"observed{prefix}TotalRate"] = float(scores[observed].mean())
    for metric in ("home", "away", "total", "margin"):
        for level in (50, 80, 90):
            result[f"{metric}Coverage{level}"] = float(scores[f"{metric}Coverage{level}"].mean())
            result[f"{metric}AverageWidth{level}"] = float(scores[f"{metric}Width{level}"].mean())
    return result


def fit_selected_artifact(features: pd.DataFrame, selected: str, through_season: int) -> dict[str, Any]:
    train = features[features["primary"] & features["is_final"] & features["season"].between(2014, through_season)]
    family, parameters = POINT_CANDIDATES[selected]
    return {
        "configuration": selected,
        "family": family,
        "parameters": parameters,
        "trainingThroughSeason": through_season,
        "trainingGames": int(len(train)),
        "featureColumns": FEATURE_COLUMNS,
        "models": _fit_pair(train, family, parameters),
    }


def predict_artifact(artifact: dict[str, Any], row: pd.DataFrame) -> dict[str, float]:
    margin = float(artifact["models"]["margin"].predict(row[FEATURE_COLUMNS])[0])
    total = float(artifact["models"]["total"].predict(row[FEATURE_COLUMNS])[0])
    home, away = _point_outputs(np.array([margin]), np.array([total]))
    return {"homeMargin": margin, "totalPoints": total, "homePoints": float(home[0]), "awayPoints": float(away[0])}


def save_artifact(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(value, path)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "physicalSha256": sha256_path(path)}
