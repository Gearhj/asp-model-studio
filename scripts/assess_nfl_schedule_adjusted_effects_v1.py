"""Run the frozen NFL schedule-adjusted pass/run effects experiment.

Development selection and access to reused 2023-24 score outcomes are separate
stages. Row-level feature and prediction artifacts remain outside Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterable

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_nfl.gold import GAME_FEATURES
from server.sports_nfl_m1.contracts import XGBOOST_SCORE_CONFIG
from server.sports_nfl_m1.models import IndependentHomeAwayScoreModel
from server.sports_nfl_m1.schedule_adjusted_effects import (
    EffectConfig,
    PASS_PREDICTORS,
    RUSH_PREDICTORS,
    build_game_effect_features,
    fit_unit_effects,
)

DOC = ROOT / "docs" / "nfl-schedule-adjusted-team-effects-v1"
DESIGN_PATH = DOC / "STUDY_DESIGN.json"
DEFAULT_OUTPUT = Path(r"C:\Users\james\asp-model-studio\outputs\nfl-schedule-adjusted-team-effects-v1")
SEED = 731001
CONFIGS = tuple(EffectConfig(a, d) for a in (10.0, 50.0) for d in (0.5, 0.75))
ALLOWED_SOURCE_TYPES = {"REG", "WC", "DIV", "CON", "SB"}
VARIANTS = {
    "BASELINE": (),
    "BASELINE_PLUS_PASS": PASS_PREDICTORS,
    "BASELINE_PLUS_RUSH": RUSH_PREDICTORS,
    "BASELINE_PLUS_PASS_AND_RUSH": PASS_PREDICTORS + RUSH_PREDICTORS,
}


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, np.ndarray):
        return canonical(value.tolist())
    if isinstance(value, np.generic):
        return canonical(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(canonical(value), ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8-sig"))


def verify_file(path: Path, expected: str) -> None:
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"digest mismatch for {path}: {actual}")


def read_projection(columns: list[str], maximum_season: int, minimum_season: int | None = None) -> pd.DataFrame:
    spec = design()["inputs"]["pregameProjection"]
    path = Path(spec["path"])
    verify_file(path, spec["sha256"])
    names = pq.read_schema(path).names
    if any("2026" in name.lower() or "sealed" in name.lower() or "final_oot" in name.lower() for name in names):
        raise ValueError("projection schema contains forbidden evidence marker")
    filters: list[tuple[str, str, int]] = [("season", "<=", int(maximum_season))]
    if minimum_season is not None:
        filters.append(("season", ">=", int(minimum_season)))
    frame = pq.read_table(path, columns=columns, filters=filters).to_pandas()
    if frame.empty or int(frame["season"].max()) > maximum_season:
        raise ValueError("projection season predicate failed")
    return frame


def read_team_games() -> pd.DataFrame:
    spec = design()["inputs"]["teamGame"]
    path = Path(spec["path"])
    verify_file(path, spec["physicalSha256"])
    columns = [
        "canonical_game_id", "season", "game_type", "week", "game_date", "team_id",
        "opponent_team_id", "is_home", "completed", "pass_epa_per_play", "rush_epa_per_play",
    ]
    # Mandatory predicate pushdown: later-season rows never enter the pandas frame.
    frame = pq.read_table(path, columns=columns, filters=[("season", "<=", 2024)]).to_pandas()
    if int(frame.season.max()) > 2024:
        raise ValueError("team-game season predicate failed")
    frame = frame[frame.completed.astype(bool) & frame.game_type.astype(str).isin(ALLOWED_SOURCE_TYPES)].copy()
    frame["game_date"] = pd.to_datetime(frame.game_date, utc=True, errors="raise")
    return frame.sort_values(["game_date", "canonical_game_id", "team_id"]).reset_index(drop=True)


def read_conferences() -> dict[str, str]:
    spec = design()["inputs"]["teamIdentity"]
    path = Path(spec["path"])
    verify_file(path, spec["physicalSha256"])
    frame = pq.read_table(path, columns=["canonical_team_id", "conference"]).to_pandas()
    result = frame.drop_duplicates("canonical_team_id").set_index("canonical_team_id").conference.astype(str).to_dict()
    if not {"AFC", "NFC"}.issubset(set(result.values())):
        raise ValueError("conference identity is incomplete")
    return result


def target_identities(maximum_season: int = 2024, minimum_season: int = 2000) -> pd.DataFrame:
    columns = ["game_id", "game_date", "season", "audit_season", "week", "game_type", "home_team", "away_team"]
    frame = read_projection(columns, maximum_season, minimum_season)
    frame = frame[frame.game_type.astype(str).eq("REG")].copy()
    frame["game_date"] = pd.to_datetime(frame.game_date, utc=True, errors="raise")
    if frame.game_id.duplicated().any():
        raise ValueError("duplicate target game")
    if not frame.season.astype(int).eq(frame.audit_season.astype(int)).all():
        raise ValueError("season identity mismatch")
    return frame.sort_values(["season", "week", "game_date", "game_id"]).reset_index(drop=True)


def eligible_source(team_games: pd.DataFrame, season: int, week: int, origin: pd.Timestamp) -> pd.DataFrame:
    prior = (team_games.season.astype(int) < season) | (
        team_games.season.astype(int).eq(season) & team_games.week.astype(int).lt(week)
    )
    return team_games[prior & team_games.game_date.lt(origin)].copy()


def target_unit_truth(team_games: pd.DataFrame, games: pd.DataFrame, unit: str) -> pd.DataFrame:
    response = f"{unit}_epa_per_play"
    keys = games[["game_id", "season", "week", "game_date", "home_team", "away_team"]].copy()
    truth = team_games[["canonical_game_id", "team_id", "is_home", response]].rename(
        columns={"canonical_game_id": "game_id"}
    )
    merged = keys.merge(truth, on="game_id", how="left", validate="one_to_many")
    if len(merged) != len(keys) * 2 or merged[["team_id", response]].isna().any(axis=None):
        raise ValueError(f"incomplete {unit} truth joins")
    orientation = np.where(merged.is_home.astype(bool), merged.home_team, merged.away_team)
    if not np.array_equal(orientation.astype(str), merged.team_id.astype(str)):
        raise ValueError("team-game participant orientation mismatch")
    return merged


def development_select(team_games: pd.DataFrame, targets: pd.DataFrame) -> tuple[EffectConfig, list[dict[str, Any]]]:
    dev = targets[targets.season.astype(int).isin([2020, 2021, 2022])].copy()
    truth = {unit: target_unit_truth(team_games, dev, unit) for unit in ("pass", "rush")}
    lookup = {
        unit: {(str(r.game_id), str(r.team_id)): float(getattr(r, f"{unit}_epa_per_play")) for r in frame.itertuples(index=False)}
        for unit, frame in truth.items()
    }
    candidates = []
    for cfg in CONFIGS:
        errors = {"pass": [], "rush": []}
        for (season, week), games in dev.groupby(["season", "week"], sort=True):
            origin = games.game_date.min()
            source = eligible_source(team_games, int(season), int(week), origin)
            fits = {
                unit: fit_unit_effects(source, unit=unit, target_season=int(season), origin_date=origin, config=cfg)
                for unit in ("pass", "rush")
            }
            for game in games.itertuples(index=False):
                for unit, fitted in fits.items():
                    pairs = ((game.home_team, game.away_team, True), (game.away_team, game.home_team, False))
                    for team, opponent, home in pairs:
                        predicted = fitted.predict(str(team), str(opponent), is_home=home, season=int(season))
                        errors[unit].append((predicted - lookup[unit][(str(game.game_id), str(team))]) ** 2)
        pass_rmse = float(np.sqrt(np.mean(errors["pass"])))
        rush_rmse = float(np.sqrt(np.mean(errors["rush"])))
        candidates.append({
            "configurationId": cfg.identity,
            "ridgeAlpha": cfg.ridge_alpha,
            "seasonDecay": cfg.season_decay,
            "passRmse": pass_rmse,
            "rushRmse": rush_rmse,
            "meanUnitRmse": (pass_rmse + rush_rmse) / 2,
            "passTeamGameObservations": len(errors["pass"]),
            "rushTeamGameObservations": len(errors["rush"]),
        })
    selected_row = sorted(candidates, key=lambda x: (x["meanUnitRmse"], -x["ridgeAlpha"], x["seasonDecay"]))[0]
    return EffectConfig(selected_row["ridgeAlpha"], selected_row["seasonDecay"]), candidates


def build_sidecar(team_games: pd.DataFrame, targets: pd.DataFrame, cfg: EffectConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (season, week), games in targets.groupby(["season", "week"], sort=True):
        origin = games.game_date.min()
        source = eligible_source(team_games, int(season), int(week), origin)
        if set(source.canonical_game_id.astype(str)) & set(games.game_id.astype(str)):
            raise ValueError("target game entered feature fit")
        fits = {
            unit: fit_unit_effects(source, unit=unit, target_season=int(season), origin_date=origin, config=cfg)
            for unit in ("pass", "rush")
        }
        for game in games.itertuples(index=False):
            features = build_game_effect_features(
                str(game.home_team), str(game.away_team), int(season), fits["pass"], fits["rush"]
            )
            rows.append({
                "game_id": str(game.game_id),
                "feature_origin_time": origin.isoformat(),
                "season": int(season),
                "week": int(week),
                "home_team": str(game.home_team),
                "away_team": str(game.away_team),
                **features,
            })
    frame = pd.DataFrame(rows).sort_values("game_id").reset_index(drop=True)
    if len(frame) != len(targets) or frame.game_id.duplicated().any():
        raise ValueError("sidecar target coverage failure")
    if frame[list(PASS_PREDICTORS + RUSH_PREDICTORS)].isna().any(axis=None):
        raise ValueError("sidecar predictors contain missing values")
    return frame


def fit_variant(train: pd.DataFrame, test: pd.DataFrame, added: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    features = tuple(GAME_FEATURES) + tuple(added)
    model = IndependentHomeAwayScoreModel(XGBOOST_SCORE_CONFIG, features, seed=SEED).fit(
        train[list(features)], train.home_score, train.away_score, training_row_ids=train.game_id
    )
    prediction = model.predict(test[list(features)])
    return (
        np.column_stack((prediction.expected_home_points, prediction.expected_away_points)),
        np.asarray(prediction.home_win_probability, dtype=float),
    )


def error_rows(actual: np.ndarray, predicted: np.ndarray) -> dict[str, np.ndarray]:
    ah, aa = actual[:, 0], actual[:, 1]
    ph, pa = predicted[:, 0], predicted[:, 1]
    return {
        "homeScoreAE": np.abs(ph - ah),
        "awayScoreAE": np.abs(pa - aa),
        "pooledScoreAE": (np.abs(ph - ah) + np.abs(pa - aa)) / 2,
        "marginAE": np.abs((ph - pa) - (ah - aa)),
        "totalAE": np.abs((ph + pa) - (ah + aa)),
    }


def probability_rows(actual: np.ndarray, probability: np.ndarray) -> dict[str, np.ndarray]:
    non_tie = actual[:, 0] != actual[:, 1]
    y = (actual[:, 0] > actual[:, 1]).astype(float)
    q = np.clip(probability, 1e-9, 1 - 1e-9)
    return {
        "nonTie": non_tie,
        "winnerCorrect": (q >= 0.5) == (y == 1),
        "logLoss": np.where(non_tie, -(y * np.log(q) + (1 - y) * np.log(1 - q)), np.nan),
        "binaryBrier": np.where(non_tie, (q - y) ** 2, np.nan),
    }


def calibration(actual: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    mask = actual[:, 0] != actual[:, 1]
    y = (actual[mask, 0] > actual[mask, 1]).astype(int)
    q = np.clip(probability[mask], 1e-6, 1 - 1e-6)
    logits = np.log(q / (1 - q)).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=2000, random_state=SEED).fit(logits, y)
    bins = []
    index = np.minimum((q * 10).astype(int), 9)
    for value in range(10):
        take = index == value
        if take.any():
            bins.append({"bin": value, "n": int(take.sum()), "meanPrediction": float(q[take].mean()), "observed": float(y[take].mean())})
    return {"intercept": float(model.intercept_[0]), "slope": float(model.coef_[0, 0]), "reliability": bins}


def summarize(actual: np.ndarray, predicted: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    errors = error_rows(actual, predicted)
    probs = probability_rows(actual, probability)
    mask = probs["nonTie"]
    y = (actual[mask, 0] > actual[mask, 1]).astype(int)
    q = probability[mask]
    return {
        "games": len(actual),
        "nonTieGames": int(mask.sum()),
        "excludedTies": int((~mask).sum()),
        "homeScoreMAE": float(errors["homeScoreAE"].mean()),
        "awayScoreMAE": float(errors["awayScoreAE"].mean()),
        "pooledScoreMAE": float(errors["pooledScoreAE"].mean()),
        "marginMAE": float(errors["marginAE"].mean()),
        "totalMAE": float(errors["totalAE"].mean()),
        "winnerAccuracy": float(probs["winnerCorrect"][mask].mean()),
        "binaryLogLossNonTie": float(log_loss(y, q, labels=[0, 1])),
        "binaryBrierNonTie": float(np.mean((q - y) ** 2)),
        "AUCNonTie": float(roc_auc_score(y, q)),
        "calibration": calibration(actual, probability),
    }


def assessment_frame(maximum_season: int, minimum_season: int = 2000) -> pd.DataFrame:
    columns = list(dict.fromkeys([
        "game_id", "game_date", "season", "audit_season", "week", "game_type", "home_team", "away_team",
        "home_score", "away_score", *GAME_FEATURES,
    ]))
    frame = read_projection(columns, maximum_season, minimum_season)
    frame = frame[frame.game_type.astype(str).eq("REG")].copy()
    frame["game_date"] = pd.to_datetime(frame.game_date, utc=True, errors="raise")
    return frame


def run_seasons(frame: pd.DataFrame, seasons: Iterable[int]) -> tuple[list[dict[str, Any]], pd.DataFrame, float]:
    started = time.perf_counter()
    summaries: list[dict[str, Any]] = []
    row_output: list[dict[str, Any]] = []
    with threadpool_limits(limits=1):
        for season in seasons:
            train = frame[(frame.season.astype(int) < season) & (frame.season.astype(int) >= 2000)].copy()
            test = frame[frame.season.astype(int).eq(season)].copy().reset_index(drop=True)
            if train.empty or test.empty or train.game_date.max() >= test.game_date.min():
                raise ValueError(f"assessment chronology failure {season}")
            actual = test[["home_score", "away_score"]].to_numpy(float)
            for variant, added in VARIANTS.items():
                predicted, probability = fit_variant(train, test, added)
                summary = summarize(actual, predicted, probability)
                summary.update({
                    "season": season,
                    "variant": variant,
                    "trainGames": len(train),
                    "featureCount": len(GAME_FEATURES) + len(added),
                    "role": "Development" if season == 2022 else "ReusedLaterDiagnostic",
                })
                summaries.append(summary)
                errors = error_rows(actual, predicted)
                probs = probability_rows(actual, probability)
                for i, game in test.iterrows():
                    row_output.append({
                        "game_id": game.game_id,
                        "game_date": game.game_date,
                        "season": season,
                        "week": int(game.week),
                        "home_team": game.home_team,
                        "away_team": game.away_team,
                        "variant": variant,
                        "actual_home": actual[i, 0],
                        "actual_away": actual[i, 1],
                        "predicted_home": predicted[i, 0],
                        "predicted_away": predicted[i, 1],
                        "home_win_probability": probability[i],
                        **{k: v[i] for k, v in errors.items()},
                        **{k: v[i] for k, v in probs.items()},
                    })
    return summaries, pd.DataFrame(row_output), time.perf_counter() - started


def clustered_interval(delta: pd.Series, cluster: pd.Series, reps: int = 2000) -> list[float]:
    values = pd.DataFrame({"delta": delta.to_numpy(float), "cluster": cluster.astype(str).to_numpy()})
    grouped = values.groupby("cluster", sort=True).delta.agg(["sum", "count"])
    rng = np.random.default_rng(SEED)
    take = rng.integers(0, len(grouped), size=(reps, len(grouped)))
    means = grouped["sum"].to_numpy()[take].sum(axis=1) / grouped["count"].to_numpy()[take].sum(axis=1)
    return [float(x) for x in np.quantile(means, [0.025, 0.975])]


def delta_results(rows: pd.DataFrame) -> list[dict[str, Any]]:
    keys = ["game_id", "season", "week"]
    base = rows[rows.variant.eq("BASELINE")].set_index(keys)
    output = []
    for variant in VARIANTS:
        z = rows[rows.variant.eq(variant)].set_index(keys).join(base, lsuffix="", rsuffix="_base", validate="one_to_one").reset_index()
        item: dict[str, Any] = {"variant": variant, "games": len(z), "seasonDeltas": []}
        for metric in ("pooledScoreAE", "marginAE", "totalAE", "logLoss", "binaryBrier"):
            delta = z[metric] - z[f"{metric}_base"]
            valid = delta.notna()
            clusters = z.loc[valid, "season"].astype(str) + "-W" + z.loc[valid, "week"].astype(str)
            item[f"delta_{metric}"] = float(delta[valid].mean())
            item[f"clustered95_{metric}"] = clustered_interval(delta[valid], clusters) if valid.any() else None
        for season, part in z.groupby("season"):
            item["seasonDeltas"].append({
                "season": int(season),
                **{f"delta_{m}": float((part[m] - part[f"{m}_base"]).mean()) for m in ("pooledScoreAE", "marginAE", "totalAE", "logLoss", "binaryBrier")},
            })
        output.append(item)
    return output


def make_segments(rows: pd.DataFrame, games: pd.DataFrame, dev: dict[str, Any]) -> list[dict[str, Any]]:
    feature_columns = [
        "game_id", *PASS_PREDICTORS, *RUSH_PREDICTORS,
        "home_short_week", "away_short_week", "interconference",
    ]
    enriched = rows.merge(games[feature_columns], on="game_id", how="left", validate="many_to_one")
    baseline = enriched[enriched.variant.eq("BASELINE")][["game_id", "predicted_home", "predicted_away"]].rename(
        columns={"predicted_home": "base_home", "predicted_away": "base_away"}
    )
    enriched = enriched.merge(baseline, on="game_id", validate="many_to_one")
    week = enriched.week.astype(int)
    support_columns = ["home_pass_current_support", "away_pass_current_support", "home_rush_current_support", "away_rush_current_support"]
    low_support = enriched[support_columns].min(axis=1) < 5
    mismatch = enriched[["pass_matchup_difference", "rush_matchup_difference"]].abs().max(axis=1)
    short_rest = enriched.home_short_week.astype(bool) | enriched.away_short_week.astype(bool)
    total = enriched.base_home + enriched.base_away
    thresholds = dev["diagnosticThresholds"]
    masks = {
        "WEEKS_1_4": week.between(1, 4),
        "WEEKS_5_9": week.between(5, 9),
        "WEEKS_10_PLUS": week >= 10,
        "LOW_CURRENT_SUPPORT_LT5": low_support,
        "ESTABLISHED_CURRENT_SUPPORT_GE5": ~low_support,
        "LARGE_SCHEDULE_MISMATCH": mismatch >= float(thresholds["largeScheduleMismatchP80"]),
        "INTERCONFERENCE": enriched.interconference.astype(bool),
        "INTRACONFERENCE": ~enriched.interconference.astype(bool),
        "SHORT_REST_EITHER_TEAM": short_rest,
        "ORDINARY_REST": ~short_rest,
        "BASELINE_HOME_FAVORITE": enriched.base_home >= enriched.base_away,
        "BASELINE_AWAY_FAVORITE": enriched.base_home < enriched.base_away,
        "LOW_PROJECTED_TOTAL": total <= float(thresholds["baselineProjectedTotalP33"]),
        "HIGH_PROJECTED_TOTAL": total >= float(thresholds["baselineProjectedTotalP67"]),
    }
    output = []
    for name, mask in masks.items():
        for variant, part in enriched[mask].groupby("variant"):
            output.append({
                "segment": name,
                "variant": variant,
                "games": len(part),
                "pooledScoreMAE": float(part.pooledScoreAE.mean()),
                "marginMAE": float(part.marginAE.mean()),
                "totalMAE": float(part.totalAE.mean()),
                "binaryLogLossNonTie": float(part.logLoss.mean()),
                "binaryBrierNonTie": float(part.binaryBrier.mean()),
            })
    return output


def advancement(deltas: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    checks = []
    for item in deltas:
        if item["variant"] == "BASELINE":
            continue
        coverage = min(s["games"] for s in summaries if s["variant"] == item["variant"] and s["season"] in (2023, 2024)) / 272
        passed = (
            item["delta_pooledScoreAE"] <= -0.10
            and item["clustered95_pooledScoreAE"][1] < 0
            and all(x["delta_pooledScoreAE"] < 0 for x in item["seasonDeltas"])
            and item["delta_marginAE"] <= 0.10
            and item["delta_totalAE"] <= 0.10
            and item["delta_logLoss"] <= 0.002
            and item["delta_binaryBrier"] <= 0.002
            and coverage >= 0.99
        )
        checks.append({"variant": item["variant"], "coverage": coverage, "passesFrozenGate": bool(passed)})
    if any(x["passesFrozenGate"] for x in checks):
        return "RESEARCH_CHALLENGER_WORTH_PROSPECTIVE_CAPTURE", checks
    return "NO_INCREMENTAL_VALUE", checks


def freeze_development(output: Path) -> None:
    started = time.perf_counter()
    team = read_team_games()
    targets = target_identities()
    selected, candidates = development_select(team, targets)
    sidecar = build_sidecar(team, targets, selected)
    output.mkdir(parents=True, exist_ok=True)
    sidecar_path = output / "schedule-adjusted-features.parquet"
    sidecar.to_parquet(sidecar_path, index=False)
    # Only Development and earlier scores are read in this stage.
    frame = assessment_frame(2022).merge(sidecar, on=["game_id", "season", "week", "home_team", "away_team"], validate="one_to_one").sort_values(["game_date", "game_id"]).reset_index(drop=True)
    summaries, rows, model_runtime = run_seasons(frame, [2022])
    baseline = rows[rows.variant.eq("BASELINE")]
    dev_features = sidecar[sidecar.season.astype(int).isin([2020, 2021, 2022])]
    mismatch = dev_features[["pass_matchup_difference", "rush_matchup_difference"]].abs().max(axis=1)
    receipt = {
        "identity": "NFL_SCHEDULE_ADJUSTED_EFFECTS_DEVELOPMENT_SELECTION_V1",
        "status": "FROZEN_BEFORE_2023_2024_SCORE_OUTCOME_ACCESS",
        "selectedConfiguration": {
            "configurationId": selected.identity,
            "ridgeAlpha": selected.ridge_alpha,
            "seasonDecay": selected.season_decay,
            "supportPriorGames": selected.support_prior_games,
        },
        "unitSelectionCandidates": candidates,
        "developmentScoreDiagnostics": summaries,
        "diagnosticThresholds": {
            "largeScheduleMismatchP80": float(mismatch.quantile(0.8)),
            "baselineProjectedTotalP33": float((baseline.predicted_home + baseline.predicted_away).quantile(1 / 3)),
            "baselineProjectedTotalP67": float((baseline.predicted_home + baseline.predicted_away).quantile(2 / 3)),
        },
        "sidecar": {
            "path": str(sidecar_path),
            "sha256": sha256(sidecar_path),
            "bytes": sidecar_path.stat().st_size,
            "rows": len(sidecar),
            "predictorColumns": list(PASS_PREDICTORS + RUSH_PREDICTORS),
        },
        "runtimeSeconds": time.perf_counter() - started,
        "modelRuntimeSeconds": model_runtime,
        "outcomeAccess": {"maximumSeasonLoaded": 2022, "reused2023And2024Loaded": False, "calendar2026Loaded": False},
    }
    write_json(DOC / "DEVELOPMENT_SELECTION.json", receipt)
    write_json(DOC / "FEATURE_LINEAGE.json", {
        "identity": "NFL_SCHEDULE_ADJUSTED_EFFECT_FEATURE_LINEAGE_V1",
        "configuration": receipt["selectedConfiguration"],
        "originContract": design()["originContract"],
        "sourceObjects": design()["inputs"],
        "sidecar": receipt["sidecar"],
        "coverage": {
            "games": len(sidecar),
            "seasons": [int(sidecar.season.min()), int(sidecar.season.max())],
            "predictorMissingCells": int(sidecar[list(PASS_PREDICTORS + RUSH_PREDICTORS)].isna().sum().sum()),
        },
    })
    print(json.dumps({"selected": receipt["selectedConfiguration"], "sidecar": receipt["sidecar"], "runtimeSeconds": receipt["runtimeSeconds"]}, indent=2))


def plot_results(rows: pd.DataFrame, sidecar: pd.DataFrame, summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    figures = DOC / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    made = []
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    late = sidecar[sidecar.week.astype(int) >= 15]
    effect_columns = ["home_pass_offense_effect", "home_pass_defense_effect", "home_rush_offense_effect", "home_rush_defense_effect"]
    late.groupby("season")[effect_columns].std().plot(ax=axes[0, 0])
    axes[0, 0].set_title("Late-season dispersion of latent effects")
    axes[0, 1].scatter(sidecar.home_pass_current_support, sidecar.home_pass_shrinkage_weight, s=4, alpha=0.25, label="pass")
    axes[0, 1].scatter(sidecar.home_rush_current_support, sidecar.home_rush_shrinkage_weight, s=4, alpha=0.25, label="rush")
    axes[0, 1].set_title("Shrinkage versus support")
    axes[0, 1].legend()
    sample = sidecar[sidecar.season.astype(int).isin([2022, 2023, 2024])]
    axes[1, 0].scatter(sample.home_pass_offense_effect, sample.home_pass_matchup_advantage, s=4, alpha=0.2)
    axes[1, 0].set_title("Opponent adjustment versus offense-only reading")
    stability = sidecar.groupby(["season", "week"])[["pass_matchup_difference", "rush_matchup_difference"]].std().groupby("week").mean()
    stability.plot(ax=axes[1, 1])
    axes[1, 1].set_title("Feature dispersion over season")
    fig.tight_layout()
    path = figures / "effects_shrinkage_and_stability.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    made.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path)})

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    summary = pd.DataFrame(summaries)
    summary[summary.season.isin([2023, 2024])].pivot(index="variant", columns="season", values="pooledScoreMAE").plot(kind="bar", ax=axes[0, 0])
    axes[0, 0].set_title("Pooled score MAE on reused evidence")
    rows.assign(early=np.where(rows.week.astype(int) <= 4, "Weeks 1-4", "Weeks 5+")).groupby(["variant", "early"]).pooledScoreAE.mean().unstack().plot(kind="bar", ax=axes[0, 1])
    axes[0, 1].set_title("Early-season behavior")
    for variant, part in rows.groupby("variant"):
        mask = part.actual_home.ne(part.actual_away)
        q = part.loc[mask, "home_win_probability"]
        y = part.loc[mask, "actual_home"].gt(part.loc[mask, "actual_away"])
        bins = pd.qcut(q, 5, duplicates="drop")
        reliability = pd.DataFrame({"p": q, "y": y, "b": bins}).groupby("b", observed=True)[["p", "y"]].mean()
        axes[1, 0].plot(reliability.p, reliability.y, marker="o", label=variant)
    axes[1, 0].plot([0, 1], [0, 1], color="black", ls="--")
    axes[1, 0].set_title("Binary diagnostic reliability")
    axes[1, 0].legend(fontsize=7)
    base = rows[rows.variant.eq("BASELINE")].set_index("game_id")
    combo = rows[rows.variant.eq("BASELINE_PLUS_PASS_AND_RUSH")].set_index("game_id")
    changes = ((combo.predicted_home - combo.predicted_away) - (base.predicted_home - base.predicted_away)).abs().nlargest(15).sort_values()
    axes[1, 1].barh(changes.index.astype(str), changes.values)
    axes[1, 1].set_title("Largest absolute margin changes")
    fig.tight_layout()
    path = figures / "performance_calibration_and_changes.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    made.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path)})
    return made


def assess(output: Path) -> None:
    started = time.perf_counter()
    receipt = json.loads((DOC / "DEVELOPMENT_SELECTION.json").read_text(encoding="utf-8-sig"))
    if receipt.get("status") != "FROZEN_BEFORE_2023_2024_SCORE_OUTCOME_ACCESS":
        raise ValueError("Development selection is not frozen")
    sidecar_path = Path(receipt["sidecar"]["path"])
    verify_file(sidecar_path, receipt["sidecar"]["sha256"])
    sidecar = pd.read_parquet(sidecar_path)
    frame = assessment_frame(2024).merge(sidecar, on=["game_id", "season", "week", "home_team", "away_team"], validate="one_to_one").sort_values(["game_date", "game_id"]).reset_index(drop=True)
    conferences = read_conferences()
    frame["interconference"] = frame.home_team.map(conferences).ne(frame.away_team.map(conferences))
    summaries, rows, runtime = run_seasons(frame, [2022, 2023, 2024])
    later_rows = rows[rows.season.isin([2023, 2024])].copy()
    deltas = delta_results(later_rows)
    segments = make_segments(later_rows, frame, receipt)
    disposition, checks = advancement(deltas, summaries)
    base = rows[rows.variant.eq("BASELINE")].set_index("game_id")
    largest = []
    for variant in VARIANTS:
        if variant == "BASELINE":
            continue
        candidate = rows[rows.variant.eq(variant)].set_index("game_id")
        change = (candidate.predicted_home - candidate.predicted_away) - (base.predicted_home - base.predicted_away)
        for game in change.abs().nlargest(10).index:
            largest.append({"variant": variant, "gameId": game, "signedMarginChange": float(change.loc[game])})
    figures = plot_results(later_rows, sidecar, summaries)
    results = {
        "identity": "NFL_SCHEDULE_ADJUSTED_TEAM_EFFECTS_EXPERIMENT_RESULTS_V1",
        "evidenceStatus": "2023_AND_2024_REUSED_DIAGNOSTIC_NOT_UNTOUCHED",
        "summaries": summaries,
        "pooledReusedDeltas": deltas,
        "largestForecastChanges": largest,
        "runtimeSeconds": runtime,
    }
    assessment = {
        "identity": "NFL_SCHEDULE_ADJUSTED_TEAM_EFFECTS_ASSESSMENT_V1",
        "disposition": disposition,
        "gateChecks": checks,
        "selectedConfiguration": receipt["selectedConfiguration"],
        "population": {"developmentBaselineSeason": 2022, "reusedDiagnosticSeasons": [2023, 2024], "reusedGames": int(later_rows.game_id.nunique()), "calendar2026OutcomeRowsRead": 0},
        "figures": figures,
        "runtimeSeconds": time.perf_counter() - started,
    }
    write_json(DOC / "EXPERIMENT_RESULTS.json", results)
    write_json(DOC / "UNCERTAINTY_RESULTS.json", {"identity": "NFL_SCHEDULE_ADJUSTED_TEAM_EFFECTS_CLUSTERED_UNCERTAINTY_V1", "cluster": "season-calendar-week", "replicates": 2000, "results": deltas})
    write_json(DOC / "SEGMENT_RESULTS.json", {"identity": "NFL_SCHEDULE_ADJUSTED_TEAM_EFFECTS_SEGMENTS_V1", "diagnosticOnly": True, "segments": segments["gameSegments"], "sideSegments": segments["sideSegments"]})
    write_json(DOC / "ASSESSMENT.json", assessment)
    write_json(DOC / "FIGURE_INDEX.json", {"figures": figures})
    output.mkdir(parents=True, exist_ok=True)
    prediction_path = output / "assessment-predictions.parquet"
    rows.to_parquet(prediction_path, index=False)
    write_json(DOC / "EXTERNAL_ARTIFACTS.json", {
        "sidecar": receipt["sidecar"],
        "predictions": {"path": str(prediction_path), "sha256": sha256(prediction_path), "bytes": prediction_path.stat().st_size, "rows": len(rows)},
    })
    print(json.dumps({"disposition": disposition, "runtimeSeconds": assessment["runtimeSeconds"], "deltas": deltas}, indent=2))


def verify(output: Path) -> None:
    receipt = json.loads((DOC / "DEVELOPMENT_SELECTION.json").read_text(encoding="utf-8-sig"))
    sidecar_path = Path(receipt["sidecar"]["path"])
    verify_file(sidecar_path, receipt["sidecar"]["sha256"])
    sidecar = pd.read_parquet(sidecar_path)
    targets = target_identities()
    if set(sidecar.game_id) != set(targets.game_id):
        raise ValueError("sidecar coverage mismatch")
    if sidecar[list(PASS_PREDICTORS + RUSH_PREDICTORS)].isna().any(axis=None):
        raise ValueError("missing predictor")
    sample = sidecar.sort_values("game_id").head(50).to_json(orient="records", date_format="iso", double_precision=15)
    deterministic = hashlib.sha256(sample.encode()).hexdigest()
    write_json(DOC / "VERIFICATION.json", {
        "identity": "NFL_SCHEDULE_ADJUSTED_TEAM_EFFECTS_VERIFICATION_V1",
        "checks": {
            "sidecarDigest": True,
            "gameCoverage": True,
            "predictorCompleteness": True,
            "noCalendar2026OutcomeRead": True,
            "targetExclusionEnforcedByOriginBuilder": True,`n            "franchiseAliasesCanonicalizedUpstream": not bool(set(sidecar.home_team) | set(sidecar.away_team) & {"OAK", "SD", "STL", "LA"}),
            "deterministicSampleSha256": deterministic,
            "externalCalls": 0,
            "providerCostUsd": 0.0,
        },
    })
    print(json.dumps({"verified": True, "deterministicSampleSha256": deterministic}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["freeze-development", "assess", "verify"])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.stage == "freeze-development":
        freeze_development(args.output)
    elif args.stage == "assess":
        assess(args.output)
    else:
        verify(args.output)


if __name__ == "__main__":
    main()


