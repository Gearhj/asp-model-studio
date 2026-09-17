"""Fit and assess the frozen V19 team-defense BIP challenger.

This runner reads only the registered 2023 Development prefix and reused 2024
fold-1 diagnostic population.  It never opens 2025, 2026, or Final OOT rows.
Artifacts are research-only and are written outside Git by default.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_v19_structural_defense import (
    BIP_INDICES, HIT_INDICES, OUT_INDEX, UNCHANGED_INDICES, DefenseConfig,
    apply_defense_shift, conditional_bip_hit_probability,
    defense_log_odds_shift, fit_state,
)
from server.sports_modeling.metrics import PA_CLASS_ORDER


DEFAULT_SOURCE = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-regime-hybrid-ensemble-v1\baseline-cache")
DEFAULT_CONTEXT = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-v19-current-state-specialists-v1\game-context\sha256\b94fa31772a6d79e5f8b80ec414e0ec8b41a2dcf36b65c3fae9dba0e47bcfd9a\game-context.parquet")
DEFAULT_TIMING = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-v19-current-state-specialists-v1\timing-blocker\sha256\5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b\timing-evidence.json")
DEFAULT_OUTPUT = Path(r"C:\Users\james\asp-data-staging\mlb\structural-innovation-v1")
DESIGN = ROOT / "docs/mlb-v19-structural-innovation-v1/FROZEN_STUDY_DESIGN.json"
EXPECTED = {
    "raw-development.parquet": "d5fdb7bcbe058f34334483a21b14e83129d19c1727d20eddb469c18668ff3b82",
    "matched-oof.parquet": "3e816c20f6276837062b97aaa5398984ac0b3660731cc086dfae4aef04f2c8ba",
    "game-context.parquet": "b94fa31772a6d79e5f8b80ec414e0ec8b41a2dcf36b65c3fae9dba0e47bcfd9a",
    "timing-evidence.json": "5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def write_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))
    return ref(path)


def ref(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": digest(path), "bytes": path.stat().st_size}


def checked(path: Path, expected: str) -> None:
    if not path.is_file() or digest(path) != expected:
        raise ValueError(f"Registered source changed: {path}")


def fielding_rows(raw: pd.DataFrame, context: pd.DataFrame, timing: dict[str, Any]) -> pd.DataFrame:
    joined = raw.merge(
        context[["canonicalGameId", "homeTeamId", "awayTeamId"]],
        on="canonicalGameId", how="left", validate="many_to_one",
    )
    if joined[["homeTeamId", "awayTeamId"]].isna().any().any():
        raise ValueError("game/team identity join is incomplete")
    top = joined["context_top_bottom"].to_numpy(dtype=int)
    if not np.isin(top, [0, 1]).all():
        raise ValueError("participant orientation is invalid")
    joined["fieldingTeamId"] = np.where(top == 0, joined["homeTeamId"], joined["awayTeamId"])
    joined["game_date"] = pd.to_datetime(joined["game_date"]).dt.normalize()
    joined["availability_date"] = joined["game_date"]
    completion = {row["canonicalGameId"]: row["completionDateProxy"] for row in timing["knownDelayedGames"]}
    joined["availability_date"] = pd.to_datetime(
        joined["canonicalGameId"].map(completion).fillna(joined["game_date"].dt.strftime("%Y-%m-%d"))
    ).dt.normalize()
    unresolved = {row["canonicalGameId"] for row in timing["unknownFinalizationGames"]}
    joined["unknownFinalization"] = joined["canonicalGameId"].isin(unresolved)
    joined["knownDelayed"] = joined["canonicalGameId"].isin(completion)
    return joined


def bip_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[frame["observedClassIndex"].isin(BIP_INDICES)].copy()


def binary_log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-15, 1 - 1e-15)
    y = np.asarray(y, dtype=float)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def sequential_team_probabilities(history: pd.DataFrame, targets: pd.DataFrame, config: DefenseConfig) -> np.ndarray:
    result = np.empty(len(targets), dtype=np.float64)
    target_dates = targets["game_date"].to_numpy(dtype="datetime64[D]")
    for day in np.unique(target_dates):
        state_rows = history.loc[history["availability_date"].to_numpy(dtype="datetime64[D]") < day]
        state = fit_state(zip(state_rows["fieldingTeamId"], state_rows["observedClassIndex"]))
        position = np.flatnonzero(target_dates == day)
        league_rate = state.league_hits / state.league_bip
        for team in np.unique(targets.iloc[position]["fieldingTeamId"].astype(str)):
            team_pos = position[targets.iloc[position]["fieldingTeamId"].astype(str).to_numpy() == team]
            hits = int(state.team_hits.get(team, 0)); outs = int(state.team_outs.get(team, 0))
            result[team_pos] = (hits + config.prior_strength * league_rate) / (hits + outs + config.prior_strength)
    return result


def select_config(development: pd.DataFrame, design: dict[str, Any]) -> tuple[DefenseConfig, list[dict[str, Any]]]:
    selection_start = pd.Timestamp(design["candidate"]["developmentSelectionStart"])
    selection_end = pd.Timestamp(design["candidate"]["developmentSelectionEnd"])
    clean = bip_rows(development.loc[~development["unknownFinalization"]])
    selection = clean.loc[(clean["game_date"] >= selection_start) & (clean["game_date"] <= selection_end)].reset_index(drop=True)
    if selection.empty:
        raise ValueError("Development selection population is empty")
    y = selection["observedClassIndex"].isin(HIT_INDICES).to_numpy(dtype=int)
    rows = []
    for strength in design["candidate"]["developmentOnlyPriorStrengthCandidates"]:
        config = DefenseConfig(float(strength), float(design["candidate"]["maximumAbsoluteLogOddsShift"]))
        probabilities = sequential_team_probabilities(clean, selection, config)
        rows.append({"priorStrength": config.prior_strength, "rows": len(selection),
                     "dates": int(selection["game_date"].nunique()),
                     "binaryLogLoss": binary_log_loss(y, probabilities),
                     "binaryBrier": float(np.mean((probabilities - y) ** 2))})
    selected = min(rows, key=lambda row: (row["binaryLogLoss"], row["priorStrength"]))
    return DefenseConfig(selected["priorStrength"], float(design["candidate"]["maximumAbsoluteLogOddsShift"])), rows


def calibration(y: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    probabilities = np.clip(probabilities, 1e-9, 1 - 1e-9)
    x = np.log(probabilities / (1 - probabilities))
    y = np.asarray(y, dtype=float)
    def loss(theta: np.ndarray) -> float:
        z = theta[0] + theta[1] * x
        p = 1 / (1 + np.exp(-np.clip(z, -35, 35)))
        return float(-(y * np.log(np.maximum(p, 1e-15)) + (1-y) * np.log(np.maximum(1-p, 1e-15))).mean())
    fitted = minimize(loss, np.array([0.0, 1.0]), method="BFGS")
    edges = np.linspace(0, 1, 11)
    bins = np.minimum(np.digitize(probabilities, edges[1:-1]), 9)
    ece = 0.0
    details = []
    for index in range(10):
        take = bins == index
        if take.any():
            predicted = float(probabilities[take].mean()); observed = float(y[take].mean())
            ece += float(take.mean()) * abs(predicted - observed)
            details.append({"bin": index, "rows": int(take.sum()), "predicted": predicted, "observed": observed})
    return {"intercept": float(fitted.x[0]), "slope": float(fitted.x[1]), "ece": ece,
            "optimizerSuccess": bool(fitted.success), "bins": details}


def metrics(y: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    p = np.asarray(probabilities, dtype=float)
    onehot = np.eye(len(PA_CLASS_ORDER))[y]
    selected = np.clip(p[np.arange(len(y)), y], 1e-15, 1)
    bip = np.isin(y, BIP_INDICES)
    bip_y = np.isin(y[bip], HIT_INDICES).astype(int)
    bip_p = conditional_bip_hit_probability(p[bip])
    return {
        "rows": int(len(y)), "bipRows": int(bip.sum()),
        "multiclassLogLoss": float(-np.log(selected).mean()),
        "summedMulticlassBrier": float(np.square(p - onehot).sum(axis=1).mean()),
        "conditionalBipBinaryLogLoss": binary_log_loss(bip_y, bip_p),
        "conditionalBipBrier": float(np.mean((bip_p - bip_y) ** 2)),
        "conditionalBipCalibration": calibration(bip_y, bip_p),
    }


def bootstrap_by_date(frame: pd.DataFrame, differences: np.ndarray, replicates: int, seed: int) -> dict[str, Any]:
    dates = frame["game_date"].dt.strftime("%Y-%m-%d").to_numpy()
    unique = np.unique(dates)
    sums = np.array([differences[dates == day].sum(axis=0) for day in unique])
    counts = np.array([(dates == day).sum() for day in unique])
    rng = np.random.default_rng(seed)
    values = np.empty((replicates, differences.shape[1]))
    for index in range(replicates):
        draw = rng.integers(0, len(unique), len(unique))
        values[index] = sums[draw].sum(axis=0) / counts[draw].sum()
    names = ["multiclassLogLoss", "summedMulticlassBrier"]
    return {"unit": "calendar_date", "dateBlocks": int(len(unique)), "replicates": replicates, "seed": seed,
            "candidateMinusBaseline": {name: {"mean": float(differences[:, i].mean()),
                "lower95": float(np.quantile(values[:, i], .025)), "upper95": float(np.quantile(values[:, i], .975))}
                for i, name in enumerate(names)}}


def draw_figures(output: Path, assessment: dict[str, Any], profiles: pd.DataFrame,
                 baseline_bip: np.ndarray, candidate_bip: np.ndarray, y_bip: np.ndarray) -> list[Path]:
    figures = output / "figures"; figures.mkdir(parents=True, exist_ok=True)
    paths = []
    path = figures / "proper-scores.png"
    labels = ["Log loss", "Summed Brier"]
    baseline = [assessment["baseline"]["multiclassLogLoss"], assessment["baseline"]["summedMulticlassBrier"]]
    candidate = [assessment["candidate"]["multiclassLogLoss"], assessment["candidate"]["summedMulticlassBrier"]]
    x = np.arange(2); width = .36
    fig, ax = plt.subplots(figsize=(7, 4)); ax.bar(x-width/2, baseline, width, label="V18"); ax.bar(x+width/2, candidate, width, label="Defense")
    ax.set_xticks(x, labels); ax.set_ylabel("Lower is better"); ax.legend(); ax.set_title("Exact V18 vs defense challenger")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig); paths.append(path)

    path = figures / "team-defense-shifts.png"
    plot = profiles.sort_values("logOddsShift")
    fig, ax = plt.subplots(figsize=(9, 6)); ax.barh(plot["fieldingTeamId"].astype(str), plot["logOddsShift"])
    ax.axvline(0, color="black", linewidth=.8); ax.set_xlabel("Shrunk BIP-hit log-odds shift"); ax.set_title("Team defense fallback profiles")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig); paths.append(path)

    path = figures / "defensive-conversion-calibration.png"
    edges = np.linspace(0, 1, 11)
    fig, ax = plt.subplots(figsize=(6, 6)); ax.plot([0,1],[0,1], color="black", linewidth=.8, linestyle="--")
    for values, label in ((baseline_bip, "V18"), (candidate_bip, "Defense")):
        bins = np.minimum(np.digitize(values, edges[1:-1]), 9)
        points = [(values[bins == i].mean(), y_bip[bins == i].mean()) for i in range(10) if (bins == i).any()]
        ax.plot([p[0] for p in points], [p[1] for p in points], marker="o", label=label)
    ax.set_xlabel("Predicted BIP hit probability"); ax.set_ylabel("Observed BIP hit rate"); ax.legend(); ax.set_title("Reused 2024 fold-1 conversion calibration")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig); paths.append(path)
    return paths


def run(args: argparse.Namespace) -> dict[str, Any]:
    design = json.loads(DESIGN.read_bytes())
    if design["authority"]["finalOotAccess"] or design["chronology"]["seasons2025And2026Read"]:
        raise ValueError("Frozen design does not permit protected outcomes")
    raw_path = args.source_root / "raw-development.parquet"
    oof_path = args.source_root / "matched-oof.parquet"
    for path, key in ((raw_path, "raw-development.parquet"), (oof_path, "matched-oof.parquet"),
                      (args.context, "game-context.parquet"), (args.timing, "timing-evidence.json")):
        checked(path, EXPECTED[key])
    timing = json.loads(args.timing.read_bytes())
    columns = ["canonicalPaId", "canonicalGameId", "game_id", "game_date", "season", "foldNumber",
               "context_top_bottom", "observedClassIndex"]
    raw = pd.read_parquet(raw_path, columns=columns, filters=[("foldNumber", "in", [0, 1])])
    if set(raw["season"].unique()) - {2023, 2024}:
        raise ValueError("runner loaded a season outside the frozen 2023/2024 scope")
    context = pd.read_parquet(args.context)
    prepared = fielding_rows(raw, context, timing)
    development = prepared.loc[prepared["foldNumber"] == 0].copy()
    assessment_raw = prepared.loc[prepared["foldNumber"] == 1].copy()
    excluded_delayed_assessment_games = int(
        assessment_raw.loc[
            assessment_raw["knownDelayed"] | assessment_raw["unknownFinalization"],
            "canonicalGameId",
        ].nunique()
    )
    assessment_raw = assessment_raw.loc[~assessment_raw["knownDelayed"] & ~assessment_raw["unknownFinalization"]]
    config, selection = select_config(development, design)

    probability_columns = ["probability_" + name for name in PA_CLASS_ORDER]
    oof_columns = ["canonicalPaId", "canonicalGameId", "game_date", "season", "foldNumber", "observedClassIndex", *probability_columns]
    oof = pd.read_parquet(oof_path, columns=oof_columns, filters=[("foldNumber", "=", 1)])
    if set(oof["season"].unique()) != {2024}:
        raise ValueError("assessment read a non-2024 season")
    assessment = assessment_raw.merge(oof.drop(columns=["canonicalGameId", "game_date", "season", "foldNumber", "observedClassIndex"]),
                                      on="canonicalPaId", how="inner", validate="one_to_one")
    if len(assessment) != len(assessment_raw) or assessment["canonicalPaId"].duplicated().any():
        raise ValueError("exact V18 assessment join is incomplete")
    assessment = assessment.sort_values(["game_date", "canonicalGameId", "canonicalPaId"], kind="stable").reset_index(drop=True)

    history = pd.concat([development.loc[~development["unknownFinalization"]], assessment_raw], ignore_index=True)
    shifts = np.empty(len(assessment), dtype=np.float64)
    dates = assessment["game_date"].to_numpy(dtype="datetime64[D]")
    for day in np.unique(dates):
        state_rows = bip_rows(history.loc[history["availability_date"].to_numpy(dtype="datetime64[D]") < day])
        state = fit_state(zip(state_rows["fieldingTeamId"], state_rows["observedClassIndex"]))
        positions = np.flatnonzero(dates == day)
        shifts[positions] = [defense_log_odds_shift(state, team, config) for team in assessment.iloc[positions]["fieldingTeamId"]]

    baseline = assessment[probability_columns].to_numpy(dtype=np.float64)
    candidate = apply_defense_shift(baseline, shifts)
    y = assessment["observedClassIndex"].to_numpy(dtype=int)
    base_metrics = metrics(y, baseline); candidate_metrics = metrics(y, candidate)
    onehot = np.eye(len(PA_CLASS_ORDER))[y]
    differences = np.column_stack([
        -np.log(np.clip(candidate[np.arange(len(y)), y], 1e-15, 1)) + np.log(np.clip(baseline[np.arange(len(y)), y], 1e-15, 1)),
        np.square(candidate-onehot).sum(axis=1) - np.square(baseline-onehot).sum(axis=1),
    ])
    uncertainty = bootstrap_by_date(assessment, differences, design["metrics"]["bootstrapReplicates"], design["metrics"]["bootstrapSeed"])
    criteria = design["advancementCriteria"]
    primary = uncertainty["candidateMinusBaseline"]["multiclassLogLoss"]
    pass_numerical = (primary["mean"] < 0 and primary["upper95"] < 0 and
                      uncertainty["candidateMinusBaseline"]["summedMulticlassBrier"]["mean"] <= criteria["summedBrierMaterialHarmMaximum"])
    disposition = "PROMISING_REUSED_EVIDENCE_ONLY" if pass_numerical else "NO_INCREMENTAL_VALUE"
    if criteria["inheritedBaselineChronologyDefectBlocksProspectiveAdvancement"]:
        disposition = "PROMISING_REUSED_EVIDENCE_ONLY" if pass_numerical else disposition

    final_state_rows = bip_rows(history.loc[history["availability_date"] < assessment["game_date"].max() + pd.Timedelta(days=1)])
    final_state = fit_state(zip(final_state_rows["fieldingTeamId"], final_state_rows["observedClassIndex"]))
    profiles = pd.DataFrame([{"fieldingTeamId": team,
        "bipHits": int(final_state.team_hits.get(team, 0)), "bipOuts": int(final_state.team_outs.get(team, 0)),
        "logOddsShift": defense_log_odds_shift(final_state, team, config)}
        for team in sorted(set(final_state.team_hits) | set(final_state.team_outs))])

    result = {
        "schemaVersion": "MLB_V19_STRUCTURAL_DEFENSE_ASSESSMENT_V1",
        "candidateIdentity": design["candidate"]["identity"], "design": ref(DESIGN),
        "baseline": base_metrics, "candidate": candidate_metrics,
        "candidateMinusBaseline": {key: candidate_metrics[key] - base_metrics[key] for key in
            ("multiclassLogLoss", "summedMulticlassBrier", "conditionalBipBinaryLogLoss", "conditionalBipBrier")},
        "uncertainty": uncertainty, "coverage": 1.0, "assessmentGames": int(assessment["canonicalGameId"].nunique()),
        "assessmentDates": int(assessment["game_date"].nunique()), "assessmentStart": str(assessment["game_date"].min().date()),
        "assessmentEnd": str(assessment["game_date"].max().date()),
        "excludedDelayedAssessmentGames": excluded_delayed_assessment_games,
        "selectedConfig": asdict(config), "developmentSelection": selection,
        "invariance": {"maximumNonBipAbsoluteDifference": float(np.max(np.abs(candidate[:, UNCHANGED_INDICES]-baseline[:, UNCHANGED_INDICES]))),
            "maximumProbabilityMassError": float(np.max(np.abs(candidate.sum(axis=1)-1))),
            "maximumBipMassDifference": float(np.max(np.abs(candidate[:, BIP_INDICES].sum(axis=1)-baseline[:, BIP_INDICES].sum(axis=1))))},
        "shiftSummary": {"minimum": float(shifts.min()), "median": float(np.median(shifts)), "maximum": float(shifts.max()),
            "meanAbsolute": float(np.mean(np.abs(shifts))), "atCap": int(np.isclose(np.abs(shifts), config.maximum_absolute_log_odds_shift).sum())},
        "disposition": disposition,
        "qualification": "Reused 2024 fold-1 PA evidence. Exact V18 numerical predictions retain inherited suspended-game chronology uncertainty; no promotion or prospective claim.",
        "finalOotPayloadBytesRead": 0, "seasons2025And2026RowsRead": 0, "providerCalls": 0, "providerBytes": 0,
        "providerCostUsd": 0, "aispWrites": 0, "exchangeWrites": 0,
    }
    output = args.output_root.resolve(); output.mkdir(parents=True, exist_ok=True)
    model = {"schemaVersion": "MLB_V19_TEAM_DEFENSE_BIP_EB_MODEL_V1", "candidateIdentity": design["candidate"]["identity"],
             "config": asdict(config), "targetOrder": list(PA_CLASS_ORDER), "bipIndices": list(BIP_INDICES),
             "leagueHits": final_state.league_hits, "leagueOuts": final_state.league_outs,
             "teamHits": dict(final_state.team_hits), "teamOuts": dict(final_state.team_outs),
             "trainingMaximumAvailableDate": str(final_state_rows["availability_date"].max().date()),
             "authority": "RESEARCH_ONLY_NO_FORECAST_OR_PROMOTION_AUTHORITY"}
    write_json(output / "model.json", model)
    write_json(output / "assessment.json", result)
    profiles.to_parquet(output / "team-defense-profiles.parquet", index=False)
    prediction = assessment[["canonicalPaId", "canonicalGameId", "game_date", "fieldingTeamId", "observedClassIndex"]].copy()
    prediction["defenseLogOddsShift"] = shifts
    for index, name in enumerate(PA_CLASS_ORDER):
        prediction["baseline_"+name] = baseline[:, index]; prediction["candidate_"+name] = candidate[:, index]
    prediction.to_parquet(output / "predictions.parquet", index=False)
    bip_mask = np.isin(y, BIP_INDICES); y_bip = np.isin(y[bip_mask], HIT_INDICES).astype(int)
    figures = draw_figures(output, result, profiles, conditional_bip_hit_probability(baseline[bip_mask]),
                           conditional_bip_hit_probability(candidate[bip_mask]), y_bip)
    artifacts = [output / name for name in ("model.json", "assessment.json", "team-defense-profiles.parquet", "predictions.parquet")] + figures
    index = {"schemaVersion": "MLB_V19_STRUCTURAL_INNOVATION_ARTIFACT_INDEX_V1", "root": str(output),
             "artifacts": [ref(path) for path in artifacts], "sourceEvidence": [ref(raw_path), ref(oof_path), ref(args.context), ref(args.timing)],
             "network": {"calls": 0, "bytes": 0, "credits": 0, "costUsd": 0}, "disposition": disposition}
    write_json(output / "artifact-index.json", index)
    return {**result, "artifactIndex": ref(output / "artifact-index.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT)
    parser.add_argument("--timing", type=Path, default=DEFAULT_TIMING)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
