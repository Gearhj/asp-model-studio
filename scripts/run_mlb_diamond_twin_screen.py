"""Run the frozen, chronology-qualified MLB Diamond Twin value screen.

The screen is retrospective and research-only.  It reads exact V18 OOF
probabilities plus quarantined Silver participant/result evidence, never Final
OOT or 2025/2026 outcomes, and writes only to the private staging root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_diamond_twin_screen import (
    POSITIONS,
    POSITION_GROUPS,
    apply_identity_effects,
    fit_identity_effects,
    lineup_shifts,
)
from server.sports_current_statcast.mlb_v19_structural_defense import (
    BIP_INDICES,
    HIT_INDICES,
    conditional_bip_hit_probability,
)
from server.sports_modeling.metrics import PA_CLASS_ORDER


DESIGN = ROOT / "docs/mlb-diamond-twin-screen-v1/FROZEN_SCREEN_DESIGN.json"
V18_ROOT = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-regime-hybrid-ensemble-v1\baseline-cache")
CONTEXT = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-v19-current-state-specialists-v1\game-context\sha256\b94fa31772a6d79e5f8b80ec414e0ec8b41a2dcf36b65c3fae9dba0e47bcfd9a\game-context.parquet")
TIMING = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-v19-current-state-specialists-v1\timing-blocker\sha256\5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b\timing-evidence.json")
LINEUP_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-silver-v1\partitioned\65a013c18bf8db0f1efe12217230f173d13068c6c232aff287fbf202b9325187")
LINEUP = LINEUP_ROOT / "children/6ff93c27639cfc5cf5a61be9681b395583e77a6aebc420a5456c2c980ad21200.parquet"
TEAM_GAME_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-silver-v1\partitioned\acfb279779e7ddd5ee64081faf358e69155c6d947bfa5ba8458e8f8e2d0fa8bd")
TEAM_GAME = TEAM_GAME_ROOT / "children/d40baea90636a4e5644a22d6445c3d7986d3cb1003ad517cbb98fbee9481b9ff.parquet"
DEFAULT_OUTPUT = Path(r"C:\Users\james\asp-data-staging\mlb\diamond-twin-screen-v1")

EXPECTED = {
    "raw": "d5fdb7bcbe058f34334483a21b14e83129d19c1727d20eddb469c18668ff3b82",
    "oof": "3e816c20f6276837062b97aaa5398984ac0b3660731cc086dfae4aef04f2c8ba",
    "context": "9a642b0f373ef27bb684f46304661929843e9d60bef8188d2341c6373790296d",
    "timing": "5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b",
    "lineup": "6ff93c27639cfc5cf5a61be9681b395583e77a6aebc420a5456c2c980ad21200",
    "team_game": "d40baea90636a4e5644a22d6445c3d7986d3cb1003ad517cbb98fbee9481b9ff",
}
PROBABILITY_COLUMNS = [f"probability_{name}" for name in PA_CLASS_ORDER]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def reference(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}


def write_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))
    return reference(path)


def verify(path: Path, expected: str) -> None:
    if not path.is_file() or sha256(path) != expected:
        raise RuntimeError(f"registered evidence changed: {path}")


def assert_quarantined(manifest: Path) -> None:
    value = json.loads(manifest.read_bytes())
    if value.get("status") != "SILVER_NORMALIZED":
        raise RuntimeError(f"unexpected Silver status: {manifest}")
    if value.get("modelEligible") is not False or value.get("approvedForTraining") is not False:
        raise RuntimeError(f"Silver authority barrier changed: {manifest}")


def binary_log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-15, 1 - 1e-15)
    y = np.asarray(y, dtype=float)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def multiclass_metrics(y: np.ndarray, probabilities: np.ndarray) -> dict[str, float | int]:
    probabilities = np.asarray(probabilities, dtype=float)
    onehot = np.eye(len(PA_CLASS_ORDER))[y]
    selected = np.clip(probabilities[np.arange(len(y)), y], 1e-15, 1)
    bip = np.isin(y, BIP_INDICES)
    bip_y = np.isin(y[bip], HIT_INDICES).astype(int)
    bip_p = conditional_bip_hit_probability(probabilities[bip])
    return {
        "rows": int(len(y)),
        "bipRows": int(bip.sum()),
        "multiclassLogLoss": float(-np.log(selected).mean()),
        "summedMulticlassBrier": float(np.square(probabilities - onehot).sum(axis=1).mean()),
        "conditionalBipBinaryLogLoss": binary_log_loss(bip_y, bip_p),
        "conditionalBipBrier": float(np.square(bip_p - bip_y).mean()),
    }


def lineup_table(lineup: pd.DataFrame, team_games: pd.DataFrame, timing: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    lineup = lineup.copy()
    lineup["fieldPosition"] = pd.to_numeric(lineup["fieldPosition"], errors="coerce")
    rows = lineup.loc[(lineup["recordType"] == "start") & lineup["fieldPosition"].isin(POSITIONS)].copy()
    rows = rows.loc[rows["playerCanonicalPlayerId"].notna() & (rows["playerCanonicalPlayerId"].astype(str).str.len() > 0)]
    duplicates = rows.duplicated(["canonicalGameId", "homeAway", "fieldPosition"], keep=False)
    duplicate_keys = int(rows.loc[duplicates, ["canonicalGameId", "homeAway", "fieldPosition"]].drop_duplicates().shape[0])
    rows = rows.sort_values(["canonicalGameId", "homeAway", "fieldPosition", "sourceLine"], kind="stable")
    rows = rows.drop_duplicates(["canonicalGameId", "homeAway", "fieldPosition"], keep="first")
    pivot = rows.pivot(index=["canonicalGameId", "homeAway"], columns="fieldPosition", values="playerCanonicalPlayerId")
    for position in POSITIONS:
        if position not in pivot:
            pivot[position] = pd.NA
    pivot = pivot[list(POSITIONS)].rename(columns={position: f"player_{position}" for position in POSITIONS}).reset_index()
    teams = team_games[["canonicalGameId", "homeAway", "canonicalTeamId", "gameDate", "runsScored"]].copy()
    teams["gameDate"] = pd.to_datetime(teams["gameDate"]).dt.normalize()
    pivot = pivot.merge(teams, on=["canonicalGameId", "homeAway"], how="left", validate="one_to_one")
    completion = {row["canonicalGameId"]: row["completionDateProxy"] for row in timing["knownDelayedGames"]}
    pivot["availabilityDate"] = pd.to_datetime(
        pivot["canonicalGameId"].map(completion).fillna(pivot["gameDate"].dt.strftime("%Y-%m-%d"))
    ).dt.normalize()
    player_columns = [f"player_{position}" for position in POSITIONS]
    pivot["completeStartingDefense"] = pivot[player_columns].notna().all(axis=1)
    return pivot, {
        "sourceRows": int(len(lineup)),
        "startingPositionRows": int(len(rows)),
        "duplicatePositionKeysResolvedByFirstSourceLine": duplicate_keys,
        "teamGames": int(pivot["canonicalGameId"].nunique()),
        "completeTeamGameLineups": int(pivot["completeStartingDefense"].sum()),
    }


def add_carry_forward(lineups: pd.DataFrame) -> pd.DataFrame:
    """Attach the latest strictly earlier calendar-date starting defense."""
    player_columns = [f"player_{position}" for position in POSITIONS]
    result = lineups.copy()
    for column in player_columns:
        result[f"carry_{column}"] = pd.NA
    for _, group in result.groupby("canonicalTeamId", dropna=False):
        indices = group.sort_values(["gameDate", "canonicalGameId", "homeAway"], kind="stable").index
        history: list[tuple[pd.Timestamp, list[Any]]] = []
        for index in indices:
            day = result.at[index, "gameDate"]
            eligible = [entry for entry in history if entry[0] < day]
            if eligible:
                values = eligible[-1][1]
                for column, value in zip(player_columns, values):
                    result.at[index, f"carry_{column}"] = value
            if bool(result.at[index, "completeStartingDefense"]):
                history.append((result.at[index, "availabilityDate"], [result.at[index, column] for column in player_columns]))
                history.sort(key=lambda value: value[0])
    carry_columns = [f"carry_player_{position}" for position in POSITIONS]
    result["completeCarryDefense"] = result[carry_columns].notna().all(axis=1)
    return result


def attach_context(pa: pd.DataFrame, context: pd.DataFrame, lineups: pd.DataFrame, timing: dict[str, Any]) -> pd.DataFrame:
    joined = pa.merge(context[["canonicalGameId", "homeTeamId", "awayTeamId"]], on="canonicalGameId", how="left", validate="many_to_one")
    if joined[["homeTeamId", "awayTeamId"]].isna().any().any():
        raise RuntimeError("game context join is incomplete")
    top = joined["context_top_bottom"].to_numpy(dtype=int)
    if not np.isin(top, [0, 1]).all():
        raise RuntimeError("invalid batting orientation")
    joined["fieldingHomeAway"] = np.where(top == 0, "home", "away")
    joined["battingHomeAway"] = np.where(top == 0, "away", "home")
    joined["game_date"] = pd.to_datetime(joined["game_date"]).dt.normalize()
    lookup_columns = ["canonicalGameId", "homeAway", "canonicalTeamId", "gameDate", "runsScored", "completeStartingDefense", "completeCarryDefense", *[f"player_{p}" for p in POSITIONS], *[f"carry_player_{p}" for p in POSITIONS]]
    joined = joined.merge(lineups[lookup_columns], left_on=["canonicalGameId", "fieldingHomeAway"], right_on=["canonicalGameId", "homeAway"], how="left", validate="many_to_one")
    delayed = {row["canonicalGameId"] for row in timing["knownDelayedGames"]}
    unknown = {row["canonicalGameId"] for row in timing["unknownFinalizationGames"]}
    joined["chronologyExcluded"] = joined["canonicalGameId"].isin(delayed | unknown)
    return joined


def fit_and_apply(dev: pd.DataFrame, assessment: pd.DataFrame, design: dict[str, Any], *, actual: bool, positions: Iterable[int] = POSITIONS) -> tuple[Any, np.ndarray, np.ndarray]:
    source_columns = [f"player_{position}" for position in POSITIONS]
    apply_columns = source_columns if actual else [f"carry_player_{position}" for position in POSITIONS]
    dev_bip = dev.loc[dev["observedClassIndex"].isin(BIP_INDICES) & dev["completeStartingDefense"]].copy()
    baseline_dev = dev_bip[PROBABILITY_COLUMNS].to_numpy(dtype=float)
    baseline_hit = conditional_bip_hit_probability(baseline_dev)
    observed_hit = dev_bip["observedClassIndex"].isin(HIT_INDICES).to_numpy(dtype=int)
    model = fit_identity_effects(
        baseline_hit,
        observed_hit,
        dev_bip[source_columns].astype(str).to_numpy(dtype=object),
        penalty=float(design["candidate"]["ridgePenalty"]),
    )
    supported = assessment[apply_columns].notna().all(axis=1).to_numpy()
    shifts = np.zeros(len(assessment), dtype=float)
    shifts[supported] = lineup_shifts(
        model,
        assessment.loc[supported, apply_columns].astype(str).to_numpy(dtype=object),
        included_positions=tuple(positions),
        maximum_absolute_shift=float(design["candidate"]["maximumAbsoluteLineupShift"]),
    )
    baseline = assessment[PROBABILITY_COLUMNS].to_numpy(dtype=float)
    return model, apply_identity_effects(baseline, shifts), supported


def pa_loss_differences(y: np.ndarray, baseline: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    onehot = np.eye(len(PA_CLASS_ORDER))[y]
    selected_base = np.clip(baseline[np.arange(len(y)), y], 1e-15, 1)
    selected_candidate = np.clip(candidate[np.arange(len(y)), y], 1e-15, 1)
    bip = np.isin(y, BIP_INDICES)
    bip_y = np.isin(y, HIT_INDICES).astype(int)
    base_bip = conditional_bip_hit_probability(baseline)
    candidate_bip = conditional_bip_hit_probability(candidate)
    binary_base = -(bip_y * np.log(np.clip(base_bip, 1e-15, 1)) + (1 - bip_y) * np.log(np.clip(1 - base_bip, 1e-15, 1)))
    binary_candidate = -(bip_y * np.log(np.clip(candidate_bip, 1e-15, 1)) + (1 - bip_y) * np.log(np.clip(1 - candidate_bip, 1e-15, 1)))
    binary_difference = (binary_candidate - binary_base) * bip
    brier_difference = (np.square(candidate_bip - bip_y) - np.square(base_bip - bip_y)) * bip
    return np.column_stack([
        binary_difference,
        brier_difference,
        -np.log(selected_candidate) + np.log(selected_base),
        np.square(candidate - onehot).sum(axis=1) - np.square(baseline - onehot).sum(axis=1),
        bip.astype(float),
    ])


def bootstrap_dates(dates: np.ndarray, differences: np.ndarray, names: list[str], replicates: int, seed: int, mask_column: int | None = None) -> dict[str, Any]:
    labels = pd.to_datetime(dates).strftime("%Y-%m-%d").to_numpy()
    unique = np.unique(labels)
    sums = np.asarray([differences[labels == day].sum(axis=0) for day in unique])
    counts = np.asarray([(labels == day).sum() for day in unique], dtype=float)
    if mask_column is not None:
        counts = sums[:, mask_column]
    rng = np.random.default_rng(seed)
    values = np.empty((replicates, len(names)))
    for index in range(replicates):
        sampled = rng.integers(0, len(unique), len(unique))
        denominator = counts[sampled].sum()
        values[index] = sums[sampled, :len(names)].sum(axis=0) / denominator
    point_denominator = counts.sum()
    return {
        "unit": "calendar_date",
        "dateBlocks": int(len(unique)),
        "replicates": int(replicates),
        "seed": int(seed),
        "candidateMinusBaseline": {
            name: {
                "pointEstimate": float(sums[:, metric].sum() / point_denominator),
                "lower95": float(np.quantile(values[:, metric], 0.025)),
                "upper95": float(np.quantile(values[:, metric], 0.975)),
            }
            for metric, name in enumerate(names)
        },
    }


def fit_score_mapping(rows: pd.DataFrame, run_weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    expected = rows[PROBABILITY_COLUMNS].to_numpy(dtype=float) @ run_weights
    per_team = pd.DataFrame({"canonicalGameId": rows["canonicalGameId"], "side": rows["battingHomeAway"], "raw": expected}).groupby(["canonicalGameId", "side"], as_index=False)["raw"].sum()
    outcomes = rows[["canonicalGameId", "battingHomeAway"]].drop_duplicates().rename(columns={"battingHomeAway": "side"})
    # runsScored belongs to the fielding-side lineup joined to each PA; resolve
    # batting outcomes later from the team-game table in game_proxy.
    del outcomes
    return per_team, expected


def logistic_fit(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        eta = theta[0] + theta[1] * x
        p = 1 / (1 + np.exp(-np.clip(eta, -35, 35)))
        loss = float(np.logaddexp(0, eta).sum() - np.dot(y, eta) + 1e-6 * np.dot(theta, theta))
        gradient = np.asarray([(p - y).sum(), np.dot(p - y, x)]) + 2e-6 * theta
        return loss, gradient
    result = minimize(objective, np.asarray([0.0, 0.1]), jac=True, method="L-BFGS-B")
    if not result.success:
        raise RuntimeError(f"game mapping fit failed: {result.message}")
    return np.asarray(result.x)


def game_proxy(dev: pd.DataFrame, assess: pd.DataFrame, baseline: np.ndarray, candidate: np.ndarray, team_games: pd.DataFrame, weights: dict[str, float]) -> tuple[pd.DataFrame, dict[str, Any]]:
    run_weights = np.asarray([weights[name] for name in PA_CLASS_ORDER], dtype=float)
    outcome_source = team_games[["canonicalGameId", "homeAway", "runsScored"]].copy()
    outcome_source["runsScored"] = pd.to_numeric(outcome_source["runsScored"], errors="coerce")
    outcomes = outcome_source.pivot(index="canonicalGameId", columns="homeAway", values="runsScored").rename(columns={"away": "actualAway", "home": "actualHome"}).reset_index()

    def aggregate(rows: pd.DataFrame, probabilities: np.ndarray, prefix: str) -> pd.DataFrame:
        values = probabilities @ run_weights
        table = pd.DataFrame({"canonicalGameId": rows["canonicalGameId"].to_numpy(), "side": rows["battingHomeAway"].to_numpy(), "value": values})
        table = table.groupby(["canonicalGameId", "side"], as_index=False)["value"].sum()
        table = table.pivot(index="canonicalGameId", columns="side", values="value").rename(columns={"away": f"{prefix}AwayRaw", "home": f"{prefix}HomeRaw"}).reset_index()
        return table

    dev_base = aggregate(dev, dev[PROBABILITY_COLUMNS].to_numpy(dtype=float), "baseline")
    dev_games = dev_base.merge(outcomes, on="canonicalGameId", how="inner", validate="one_to_one").dropna()
    x_scores = np.concatenate([dev_games["baselineAwayRaw"], dev_games["baselineHomeRaw"]])
    y_scores = np.concatenate([dev_games["actualAway"], dev_games["actualHome"]]).astype(float)
    score_map = np.linalg.lstsq(np.column_stack([np.ones(len(x_scores)), x_scores]), y_scores, rcond=None)[0]
    dev_margin = dev_games["baselineHomeRaw"].to_numpy() - dev_games["baselineAwayRaw"].to_numpy()
    home_win = (dev_games["actualHome"].to_numpy() > dev_games["actualAway"].to_numpy()).astype(float)
    win_map = logistic_fit(dev_margin, home_win)

    assess_base = aggregate(assess, baseline, "baseline")
    assess_candidate = aggregate(assess, candidate, "candidate")
    games = assess_base.merge(assess_candidate, on="canonicalGameId", validate="one_to_one").merge(outcomes, on="canonicalGameId", how="inner", validate="one_to_one").dropna()
    for arm in ("baseline", "candidate"):
        for side in ("Away", "Home"):
            games[f"{arm}Expected{side}"] = score_map[0] + score_map[1] * games[f"{arm}{side}Raw"]
        raw_margin = games[f"{arm}HomeRaw"] - games[f"{arm}AwayRaw"]
        games[f"{arm}HomeWinProbability"] = 1 / (1 + np.exp(-np.clip(win_map[0] + win_map[1] * raw_margin, -35, 35)))
        games[f"{arm}ExpectedTotal"] = games[f"{arm}ExpectedHome"] + games[f"{arm}ExpectedAway"]
        games[f"{arm}ExpectedMargin"] = games[f"{arm}ExpectedHome"] - games[f"{arm}ExpectedAway"]
    actual_home_win = (games["actualHome"] > games["actualAway"]).astype(int).to_numpy()
    actual_total = games["actualHome"].to_numpy() + games["actualAway"].to_numpy()
    actual_margin = games["actualHome"].to_numpy() - games["actualAway"].to_numpy()

    def metrics(arm: str) -> dict[str, float | int]:
        p = games[f"{arm}HomeWinProbability"].to_numpy()
        return {
            "games": int(len(games)),
            "winnerLogLoss": binary_log_loss(actual_home_win, p),
            "winnerBrier": float(np.square(p - actual_home_win).mean()),
            "homeScoreMae": float(np.abs(games[f"{arm}ExpectedHome"] - games["actualHome"]).mean()),
            "awayScoreMae": float(np.abs(games[f"{arm}ExpectedAway"] - games["actualAway"]).mean()),
            "totalMae": float(np.abs(games[f"{arm}ExpectedTotal"] - actual_total).mean()),
            "marginMae": float(np.abs(games[f"{arm}ExpectedMargin"] - actual_margin).mean()),
        }

    delta_win = games["candidateHomeWinProbability"] - games["baselineHomeWinProbability"]
    delta_away = games["candidateExpectedAway"] - games["baselineExpectedAway"]
    delta_home = games["candidateExpectedHome"] - games["baselineExpectedHome"]
    base_p = games["baselineHomeWinProbability"].to_numpy()
    candidate_p = games["candidateHomeWinProbability"].to_numpy()
    game_differences = np.column_stack([
        -(actual_home_win * np.log(np.clip(candidate_p, 1e-15, 1)) + (1 - actual_home_win) * np.log(np.clip(1 - candidate_p, 1e-15, 1)))
        + (actual_home_win * np.log(np.clip(base_p, 1e-15, 1)) + (1 - actual_home_win) * np.log(np.clip(1 - base_p, 1e-15, 1))),
        np.square(candidate_p - actual_home_win) - np.square(base_p - actual_home_win),
        np.abs(games["candidateExpectedHome"].to_numpy() - games["actualHome"].to_numpy()) - np.abs(games["baselineExpectedHome"].to_numpy() - games["actualHome"].to_numpy()),
        np.abs(games["candidateExpectedAway"].to_numpy() - games["actualAway"].to_numpy()) - np.abs(games["baselineExpectedAway"].to_numpy() - games["actualAway"].to_numpy()),
        np.abs(games["candidateExpectedTotal"].to_numpy() - actual_total) - np.abs(games["baselineExpectedTotal"].to_numpy() - actual_total),
        np.abs(games["candidateExpectedMargin"].to_numpy() - actual_margin) - np.abs(games["baselineExpectedMargin"].to_numpy() - actual_margin),
    ])
    game_dates = games["canonicalGameId"].map(assess.groupby("canonicalGameId")["game_date"].first())
    result = {
        "status": "RETROSPECTIVE_FIXED_REALIZED_PA_EXPOSURE_PROXY_NOT_PREGAME_FORECAST",
        "developmentGamesForMapping": int(len(dev_games)),
        "scoreMapping": {"intercept": float(score_map[0]), "slope": float(score_map[1])},
        "homeWinMapping": {"intercept": float(win_map[0]), "slope": float(win_map[1])},
        "baseline": metrics("baseline"),
        "candidate": metrics("candidate"),
        "pairedUncertainty": bootstrap_dates(
            game_dates.to_numpy(),
            game_differences,
            ["winnerLogLoss", "winnerBrier", "homeScoreMae", "awayScoreMae", "totalMae", "marginMae"],
            2000,
            20260927,
        ),
        "materiality": {
            "meanAbsoluteTeamExpectedRunChange": float(np.mean(np.abs(np.concatenate([delta_away, delta_home])))),
            "meanAbsoluteGameExpectedTotalChange": float(np.abs(delta_away + delta_home).mean()),
            "meanAbsoluteGameExpectedMarginChange": float(np.abs(delta_home - delta_away).mean()),
            "meanAbsoluteWinProbabilityChange": float(np.abs(delta_win).mean()),
            "gamesMovingAtLeast0_5PercentagePoints": int((np.abs(delta_win) >= 0.005).sum()),
            "fractionMovingAtLeast0_5PercentagePoints": float((np.abs(delta_win) >= 0.005).mean()),
            "gamesMovingAtLeast1_0PercentagePoints": int((np.abs(delta_win) >= 0.01).sum()),
            "fractionMovingAtLeast1_0PercentagePoints": float((np.abs(delta_win) >= 0.01).mean()),
            "gamesMovingAtLeast2_0PercentagePoints": int((np.abs(delta_win) >= 0.02).sum()),
            "fractionMovingAtLeast2_0PercentagePoints": float((np.abs(delta_win) >= 0.02).mean()),
            "maximumAbsoluteWinProbabilityChange": float(np.abs(delta_win).max()),
        },
        "jointDistributionMetrics": None,
    }
    games["gameDate"] = game_dates
    return games, result


def artifact_index(output: Path, sources: list[Path], disposition: str) -> dict[str, Any]:
    members = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "artifact-index.json")
    return {
        "schemaVersion": "MLB_DIAMOND_TWIN_SCREEN_ARTIFACT_INDEX_V1",
        "disposition": disposition,
        "root": str(output.resolve()),
        "artifacts": [reference(path) for path in members],
        "sourceEvidence": [reference(path) for path in sources],
        "network": {"calls": 0, "bytes": 0, "credits": 0, "costUsd": 0},
        "writes": {"aisp": 0, "exchange": 0, "provider": 0},
    }


def weighted_quantile(values: np.ndarray, weights: np.ndarray, probability: float) -> float:
    order = np.argsort(values)
    ordered_values = values[order]
    ordered_weights = weights[order]
    cumulative = np.cumsum(ordered_weights) - 0.5 * ordered_weights
    cumulative = cumulative / ordered_weights.sum()
    return float(np.interp(probability, cumulative, ordered_values))


def counterfactual_materiality(
    assessment: pd.DataFrame,
    baseline: np.ndarray,
    model: Any,
    games: pd.DataFrame,
    game_result: dict[str, Any],
    run_weight_mapping: dict[str, float],
    maximum_shift: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply frozen realistic effect quantiles to fixed realized PA exposure.

    This is a noncausal magnitude calculation, not an assessment or forecast.
    """
    run_weights = np.asarray([run_weight_mapping[name] for name in PA_CLASS_ORDER], dtype=float)
    score_slope = float(game_result["scoreMapping"]["slope"])
    win_intercept = float(game_result["homeWinMapping"]["intercept"])
    win_slope = float(game_result["homeWinMapping"]["slope"])
    game_lookup = games.set_index("canonicalGameId")

    actual_lineups = assessment[["canonicalGameId", "fieldingHomeAway", *[f"player_{position}" for position in POSITIONS]]].drop_duplicates(["canonicalGameId", "fieldingHomeAway"])
    observed_full = lineup_shifts(
        model,
        actual_lineups[[f"player_{position}" for position in POSITIONS]].astype(str).to_numpy(dtype=object),
        maximum_absolute_shift=maximum_shift,
    )
    concepts: dict[str, tuple[float, float]] = {}
    for label, position in (("SHORTSTOP", 6), ("CENTER_FIELD", 8), ("CATCHER_IDENTITY", 2)):
        keys = [key for key in model.coefficients if key.startswith(f"P{position}:")]
        values = np.asarray([model.coefficients[key] for key in keys], dtype=float)
        exposures = np.asarray([model.exposures[key] for key in keys], dtype=float)
        concepts[label] = (weighted_quantile(values, exposures, 0.10), weighted_quantile(values, exposures, 0.90))
    concepts["FULL_DEFENSIVE_UNIT"] = (float(np.quantile(observed_full, 0.10)), float(np.quantile(observed_full, 0.90)))

    rows: list[dict[str, Any]] = []
    for concept, (elite_shift, poor_shift) in concepts.items():
        for scenario, shift in (("AVERAGE_TO_ELITE", elite_shift), ("AVERAGE_TO_POOR", poor_shift)):
            for (game_id, fielding_side), positions in assessment.groupby(["canonicalGameId", "fieldingHomeAway"], sort=False).indices.items():
                if game_id not in game_lookup.index:
                    continue
                take = np.asarray(positions, dtype=int)
                base = baseline[take]
                changed = apply_identity_effects(base, np.full(len(take), np.clip(shift, -maximum_shift, maximum_shift)))
                raw_run_delta = float(((changed - base) @ run_weights).sum())
                expected_run_delta = score_slope * raw_run_delta
                game = game_lookup.loc[game_id]
                baseline_raw_margin = float(game["baselineHomeRaw"] - game["baselineAwayRaw"])
                changed_raw_margin = baseline_raw_margin - raw_run_delta if fielding_side == "home" else baseline_raw_margin + raw_run_delta
                baseline_home_win = 1 / (1 + np.exp(-np.clip(win_intercept + win_slope * baseline_raw_margin, -35, 35)))
                changed_home_win = 1 / (1 + np.exp(-np.clip(win_intercept + win_slope * changed_raw_margin, -35, 35)))
                rows.append({
                    "concept": concept,
                    "scenario": scenario,
                    "canonicalGameId": game_id,
                    "fieldingSide": fielding_side,
                    "logOddsShift": float(shift),
                    "expectedOpposingRunsChange": expected_run_delta,
                    "homeWinProbabilityChange": float(changed_home_win - baseline_home_win),
                })
    table = pd.DataFrame(rows)
    summaries: dict[str, Any] = {}
    for (concept, scenario), group in table.groupby(["concept", "scenario"]):
        absolute_win = group["homeWinProbabilityChange"].abs()
        absolute_runs = group["expectedOpposingRunsChange"].abs()
        summaries[f"{concept}:{scenario}"] = {
            "teamGames": int(len(group)),
            "logOddsShift": float(group["logOddsShift"].iloc[0]),
            "meanExpectedOpposingRunsChange": float(group["expectedOpposingRunsChange"].mean()),
            "meanAbsoluteExpectedOpposingRunsChange": float(absolute_runs.mean()),
            "p90AbsoluteExpectedOpposingRunsChange": float(absolute_runs.quantile(0.90)),
            "meanAbsoluteWinProbabilityChange": float(absolute_win.mean()),
            "fractionAtLeast0_5PercentagePoints": float((absolute_win >= 0.005).mean()),
            "fractionAtLeast1_0PercentagePoints": float((absolute_win >= 0.01).mean()),
            "fractionAtLeast2_0PercentagePoints": float((absolute_win >= 0.02).mean()),
        }
    return table, {
        "status": "NONCAUSAL_FIXED_REALIZED_PA_EXPOSURE_MAGNITUDE_SCREEN",
        "effectDefinition": "Development-exposure-weighted 10th/90th percentile for named positions; assessment-lineup 10th/90th percentile for full unit.",
        "summaries": summaries,
    }


def run(output: Path) -> dict[str, Any]:
    design = json.loads(DESIGN.read_bytes())
    if design["authority"]["finalOotAccess"] or not design["authority"]["researchOnly"]:
        raise RuntimeError("frozen authority is invalid")
    raw_path = V18_ROOT / "raw-development.parquet"
    oof_path = V18_ROOT / "matched-oof.parquet"
    for path, key in ((raw_path, "raw"), (oof_path, "oof"), (CONTEXT, "context"), (TIMING, "timing"), (LINEUP, "lineup"), (TEAM_GAME, "team_game")):
        verify(path, EXPECTED[key])
    assert_quarantined(LINEUP_ROOT / "manifest.json")
    assert_quarantined(TEAM_GAME_ROOT / "manifest.json")
    timing = json.loads(TIMING.read_bytes())

    lineup = pd.read_parquet(LINEUP)
    team_games = pd.read_parquet(TEAM_GAME)
    if set(lineup["season"].astype(str).unique()) != {"2024"} or set(team_games["season"].astype(str).unique()) != {"2024"}:
        raise RuntimeError("participant/result read escaped the frozen 2024 partition")
    lineups, lineup_audit = lineup_table(lineup, team_games, timing)
    lineups = add_carry_forward(lineups)

    raw_columns = ["canonicalPaId", "canonicalGameId", "game_date", "season", "foldNumber", "context_top_bottom", "observedClassIndex"]
    raw = pd.read_parquet(raw_path, columns=raw_columns, filters=[("foldNumber", "=", 1)])
    if set(raw["season"].unique()) != {2024}:
        raise RuntimeError("PA read escaped fold-1 2024")
    oof_columns = ["canonicalPaId", *PROBABILITY_COLUMNS]
    oof = pd.read_parquet(oof_path, columns=oof_columns, filters=[("foldNumber", "=", 1)])
    pa = raw.merge(oof, on="canonicalPaId", how="inner", validate="one_to_one")
    if len(pa) != len(raw):
        raise RuntimeError("exact V18 OOF join is incomplete")
    context = pd.read_parquet(CONTEXT)
    pa = attach_context(pa, context, lineups, timing)
    before = len(pa)
    pa = pa.loc[~pa["chronologyExcluded"]].copy()
    dates = pa["game_date"]
    development = pa.loc[(dates >= pd.Timestamp(design["chronology"]["developmentStart"])) & (dates <= pd.Timestamp(design["chronology"]["developmentEnd"]))].copy()
    assessment = pa.loc[(dates >= pd.Timestamp(design["chronology"]["assessmentStart"])) & (dates <= pd.Timestamp(design["chronology"]["assessmentEnd"]))].copy()
    if development.empty or assessment.empty:
        raise RuntimeError("frozen population is empty")
    baseline = assessment[PROBABILITY_COLUMNS].to_numpy(dtype=float)
    y = assessment["observedClassIndex"].to_numpy(dtype=int)

    model, oracle, oracle_supported = fit_and_apply(development, assessment, design, actual=True)
    _, carry, carry_supported = fit_and_apply(development, assessment, design, actual=False)
    if not oracle_supported.all():
        assessment_oracle = assessment.loc[oracle_supported].copy()
        baseline_oracle = baseline[oracle_supported]
        oracle_values = oracle[oracle_supported]
        y_oracle = y[oracle_supported]
    else:
        assessment_oracle, baseline_oracle, oracle_values, y_oracle = assessment, baseline, oracle, y

    pa_differences = pa_loss_differences(y_oracle, baseline_oracle, oracle_values)
    bootstrap_bip = bootstrap_dates(
        assessment_oracle["game_date"].to_numpy(),
        pa_differences[:, [0, 1, 4]],
        ["conditionalBipBinaryLogLoss", "conditionalBipBrier"],
        int(design["metrics"]["bootstrapReplicates"]),
        int(design["metrics"]["bootstrapSeed"]),
        mask_column=2,
    )
    bootstrap_multiclass = bootstrap_dates(
        assessment_oracle["game_date"].to_numpy(),
        pa_differences[:, 2:4],
        ["multiclassLogLoss", "summedMulticlassBrier"],
        int(design["metrics"]["bootstrapReplicates"]),
        int(design["metrics"]["bootstrapSeed"]) + 10,
    )
    bootstrap = {**bootstrap_bip, "candidateMinusBaseline": {**bootstrap_bip["candidateMinusBaseline"], **bootstrap_multiclass["candidateMinusBaseline"]}, "multiclassSeed": bootstrap_multiclass["seed"]}

    variants: dict[str, Any] = {
        "ACTUAL_TARGET_STARTERS_RETROSPECTIVE_ORACLE": {
            "authority": "QUARANTINED_RETROSPECTIVE_ORACLE",
            "coverage": float(oracle_supported.mean()),
            "baseline": multiclass_metrics(y_oracle, baseline_oracle),
            "candidate": multiclass_metrics(y_oracle, oracle_values),
            "uncertainty": bootstrap,
        }
    }
    carry_assessment = assessment.loc[carry_supported].copy()
    carry_y = y[carry_supported]
    carry_base = baseline[carry_supported]
    carry_candidate = carry[carry_supported]
    carry_diff = pa_loss_differences(carry_y, carry_base, carry_candidate)
    carry_bip_bootstrap = bootstrap_dates(carry_assessment["game_date"].to_numpy(), carry_diff[:, [0, 1, 4]], ["conditionalBipBinaryLogLoss", "conditionalBipBrier"], int(design["metrics"]["bootstrapReplicates"]), int(design["metrics"]["bootstrapSeed"]) + 1, mask_column=2)
    carry_multiclass_bootstrap = bootstrap_dates(carry_assessment["game_date"].to_numpy(), carry_diff[:, 2:4], ["multiclassLogLoss", "summedMulticlassBrier"], int(design["metrics"]["bootstrapReplicates"]), int(design["metrics"]["bootstrapSeed"]) + 11)
    carry_bootstrap = {**carry_bip_bootstrap, "candidateMinusBaseline": {**carry_bip_bootstrap["candidateMinusBaseline"], **carry_multiclass_bootstrap["candidateMinusBaseline"]}, "multiclassSeed": carry_multiclass_bootstrap["seed"]}
    variants["PRIOR_GAME_STARTERS_CARRY_FORWARD_RESEARCH_PROXY"] = {
        "authority": "RECONSTRUCTED_PRIOR_DATE_PROXY_WITH_UNCERTIFIED_HISTORICAL_PUBLICATION_TIMING",
        "coverage": float(carry_supported.mean()),
        "baseline": multiclass_metrics(carry_y, carry_base),
        "candidate": multiclass_metrics(carry_y, carry_candidate),
        "uncertainty": carry_bootstrap,
    }
    for offset, (name, positions) in enumerate((("ORACLE_CATCHER_ONLY_ABLATION", POSITION_GROUPS["CATCHER"]), ("ORACLE_INFIELD_ONLY_ABLATION", POSITION_GROUPS["INFIELD"]), ("ORACLE_OUTFIELD_ONLY_ABLATION", POSITION_GROUPS["OUTFIELD"]))):
        _, candidate, supported = fit_and_apply(development, assessment, design, actual=True, positions=positions)
        values = candidate[supported]
        base = baseline[supported]
        target = y[supported]
        variants[name] = {
            "authority": "QUARANTINED_RETROSPECTIVE_ORACLE_ABLATION",
            "coverage": float(supported.mean()),
            "baseline": multiclass_metrics(target, base),
            "candidate": multiclass_metrics(target, values),
        }

    dev_model, dev_candidate, dev_supported = fit_and_apply(development, development, design, actual=True)
    del dev_model
    common_games = set(assessment_oracle["canonicalGameId"].unique())
    game_assessment = assessment_oracle.loc[assessment_oracle["canonicalGameId"].isin(common_games)].copy()
    game_baseline = game_assessment[PROBABILITY_COLUMNS].to_numpy(dtype=float)
    game_candidate_values = oracle_values[assessment_oracle["canonicalGameId"].isin(common_games).to_numpy()]
    dev_game = development.loc[dev_supported].copy()
    games, game_result = game_proxy(dev_game, game_assessment, game_baseline, game_candidate_values, team_games, design["gameProxy"]["linearRunWeights"])
    counterfactual_rows, counterfactual_result = counterfactual_materiality(
        game_assessment,
        game_baseline,
        model,
        games,
        game_result,
        design["gameProxy"]["linearRunWeights"],
        float(design["candidate"]["maximumAbsoluteLineupShift"]),
    )

    oracle_primary = bootstrap["candidateMinusBaseline"]["conditionalBipBinaryLogLoss"]
    material = game_result["materiality"]
    oracle_gate = oracle_primary["pointEstimate"] < 0 and oracle_primary["upper95"] < 0
    material_gate = material["fractionMovingAtLeast0_5PercentagePoints"] >= 0.10 or material["meanAbsoluteTeamExpectedRunChange"] >= 0.05
    if not oracle_gate or not material_gate:
        overall = "NO_MATERIAL_INCREMENTAL_VALUE"
    else:
        overall = "DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT"

    concept_dispositions = {
        "aggregateDefense": {"disposition": "NO_MATERIAL_INCREMENTAL_VALUE", "basis": "Previously completed and rejected MLB_V19_TEAM_DEFENSE_BIP_EB_V1; not rerun."},
        "namedDefense": {"disposition": overall, "basis": "Named-position oracle proper-score and game-proxy materiality gates."},
        "spatialMatchupDefense": {"disposition": "DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT", "basis": "Exact common population lacks governed pitcher GB/FB and batter spray/contact-direction evidence; no value claim made."},
        "catcher": {"disposition": "INSUFFICIENT_ADMISSIBLE_EVIDENCE", "basis": "Catcher identity ablation is not catcher quality, framing, blocking or game-calling evidence."},
        "bullpen": {"disposition": "DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT", "basis": "Named reliever availability and point-in-time usage policy are absent; inherited chronology gate remains open."},
        "managerPolicy": {"disposition": "DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT", "basis": "Retained manager identity is retrospective and no point-in-time policy state is certified."},
        "archetypeSpecialists": {"disposition": "DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT", "basis": "Required interaction evidence is absent from the exact common population; missingness is not incremental-value evidence."},
    }
    result = {
        "schemaVersion": "MLB_DIAMOND_TWIN_INCREMENTAL_VALUE_ASSESSMENT_V1",
        "disposition": overall,
        "candidateIdentity": design["candidate"]["identity"],
        "baselineIdentity": design["chronology"]["baselineIdentity"],
        "chronology": {
            "status": "INHERITED_V18_TRAINING_CHRONOLOGY_DEFECT_NOT_REPAIRED; TARGET_DELAYED_GAMES_ISOLATED",
            "claimsLimitedTo": "RETROSPECTIVE_UPPER_BOUND_AND_RESEARCH_PROXY",
            "rowsBeforeTargetExclusion": int(before),
            "rowsAfterTargetExclusion": int(len(pa)),
            "developmentRows": int(len(development)),
            "developmentGames": int(development["canonicalGameId"].nunique()),
            "assessmentRows": int(len(assessment)),
            "assessmentGames": int(assessment["canonicalGameId"].nunique()),
            "excludedTargetRows": int(before - len(pa)),
        },
        "lineupAudit": lineup_audit,
        "identityModel": {
            "optimizerSuccess": model.optimizer_success,
            "iterations": model.iterations,
            "coefficientCount": len(model.coefficients),
            "penalty": model.penalty,
            "maximumAbsoluteCoefficient": float(max(abs(value) for value in model.coefficients.values())),
        },
        "variants": variants,
        "gameProxy": game_result,
        "counterfactualMateriality": counterfactual_result,
        "decisionGates": {
            "oracleProperScoreGatePassed": bool(oracle_gate),
            "practicalMaterialityGatePassed": bool(material_gate),
            "chronologyGatePassed": False,
            "deployableEvidenceAuthorityGatePassed": False,
        },
        "conceptDispositions": concept_dispositions,
        "unsupportedInputs": {
            "pitcherBipTendency": "NOT_GOVERNED_IN_EXACT_COMMON_POPULATION",
            "batterDirectionOrContactTendency": "NOT_GOVERNED_IN_EXACT_COMMON_POPULATION",
            "spatialAlignment": "NOT_RETAINED",
            "catcherQuality": "NOT_RETAINED",
            "namedRelieverAvailability": "NOT_RETAINED_POINT_IN_TIME",
        },
        "authority": design["authority"],
        "network": {"calls": 0, "bytes": 0, "credits": 0, "costUsd": 0},
    }

    output.mkdir(parents=True, exist_ok=True)
    effects = pd.DataFrame([{"playerPositionKey": key, "logOddsEffect": value, "developmentBipExposure": model.exposures[key]} for key, value in sorted(model.coefficients.items())])
    effects.to_parquet(output / "player-position-effects.parquet", index=False)
    games.to_parquet(output / "game-proxy.parquet", index=False)
    counterfactual_rows.to_parquet(output / "counterfactual-materiality.parquet", index=False)
    assessment_output = assessment_oracle[["canonicalPaId", "canonicalGameId", "game_date", "observedClassIndex"]].copy()
    assessment_output["oracleLineupShift"] = lineup_shifts(model, assessment_oracle[[f"player_{p}" for p in POSITIONS]].astype(str).to_numpy(dtype=object), maximum_absolute_shift=float(design["candidate"]["maximumAbsoluteLineupShift"]))
    assessment_output.to_parquet(output / "pa-screen.parquet", index=False)
    write_json(output / "identity-model.json", {"schemaVersion": "MLB_DIAMOND_TWIN_IDENTITY_EFFECT_MODEL_V1", "model": {"coefficients": dict(model.coefficients), "exposures": dict(model.exposures), "penalty": model.penalty, "positions": list(model.positions), "optimizerSuccess": model.optimizer_success, "iterations": model.iterations}, "authority": "QUARANTINED_RETROSPECTIVE_ORACLE_ONLY"})
    write_json(output / "assessment.json", result)

    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    delta = (games["candidateHomeWinProbability"] - games["baselineHomeWinProbability"]) * 100
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(delta, bins=25, color="#295c8a", alpha=0.85)
    for threshold in (-2, -1, -0.5, 0.5, 1, 2):
        ax.axvline(threshold, color="#777777", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Named-defense oracle change in home-win probability (percentage points)")
    ax.set_ylabel("Games")
    ax.set_title("Retrospective realized-PA exposure proxy")
    fig.tight_layout()
    fig.savefig(figures / "win-probability-materiality.png", dpi=160)
    plt.close(fig)

    sources = [DESIGN, raw_path, oof_path, CONTEXT, TIMING, LINEUP_ROOT / "manifest.json", LINEUP, TEAM_GAME_ROOT / "manifest.json", TEAM_GAME]
    index = artifact_index(output, sources, overall)
    write_json(output / "artifact-index.json", index)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    result = run(arguments.output)
    print(json.dumps({"disposition": result["disposition"], "assessment": str((arguments.output / "assessment.json").resolve()), "assessmentSha256": sha256(arguments.output / "assessment.json"), "artifactIndexSha256": sha256(arguments.output / "artifact-index.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
