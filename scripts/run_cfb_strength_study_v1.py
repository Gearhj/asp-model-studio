"""Run only the frozen private historical CFB strength experiment."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_cfb_gen1 import strength_study as study
from server.sports_cfb_gen1 import pipeline as baseline

BASE = Path(r"C:\Users\james\asp-model-studio\outputs\cfb-gen1-v1")
DEFAULT_OUT = Path(r"C:\Users\james\asp-model-studio\outputs\cfb-opponent-adjusted-strength-v1")


def prepare(out, maximum_season):
    design = json.loads((out / "DESIGN.json").read_text())
    if study.binding(design["design"]["path"]) != design["design"]:
        raise ValueError("frozen design text changed")
    if maximum_season > 2025:
        raise ValueError("2026 outcome access excluded")
    source = BASE / "data/admitted-games.parquet"
    # Governed full-object hash is integrity only; row materialization is filtered.
    if study.binding(source) != design["sourcePopulation"]:
        raise ValueError("admitted source hash mismatch")
    games = pd.read_parquet(source, filters=[("season", "<=", maximum_season)])
    study.reject_future(games)
    features = study.checked_baseline_features(games)
    saved = pd.read_parquet(BASE / "data/point-in-time-features.parquet", filters=[("season", "<=", maximum_season)])
    a = features.set_index("game_id").sort_index()[baseline.FEATURE_COLUMNS].to_numpy(float)
    b = saved.set_index("game_id").sort_index()[baseline.FEATURE_COLUMNS].to_numpy(float)
    if not np.array_equal(a, b, equal_nan=True):
        raise ValueError("baseline feature reproduction failed")
    (out / "data").mkdir(exist_ok=True)
    features.to_parquet(out / "data" / f"baseline-features-through-{maximum_season}.parquet", index=False)
    source_latest = features.feature_max_source_game_date.dropna()
    audit = {"loadedAtUtc": datetime.now(timezone.utc).isoformat(), "loadedMaximumSeason": int(games.season.max()),
             "rows": len(games), "primaryGames": int(features.primary.sum()), "source": design["sourcePopulation"],
             "sourceReadPredicate": f"season <= {maximum_season}", "featureReproductionExact": True,
             "finalStatusFiniteScoresAnd48HourGatePassed": True,
             "sourceClass": "A_RECONSTRUCTED_HISTORICAL; NO_GENUINE_COMPLETION_CLOCKS",
             "primaryCountsBySeason": features.loc[features.primary].groupby("season").size().to_dict(),
             "minimumFeatureAgeHoursAtUTCDateOrigin": float(((features.research_origin-features.feature_max_source_game_date).dt.total_seconds()/3600).min()),
             "sourceLatestKickoff": source_latest.max(), "providerCalls": 0}
    study.write_json(out / f"SOURCE_GATE_THROUGH_{maximum_season}.json", audit)
    print(f"SOURCE <= {maximum_season}: {len(games)} rows; {int(features.primary.sum())} primary; exact baseline features", flush=True)
    return games, features


def empty_previous(features):
    return features.iloc[:0].assign(pred_margin=pd.Series(dtype=float), pred_total=pd.Series(dtype=float),
                                    pred_home=pd.Series(dtype=float), pred_away=pd.Series(dtype=float))


def add_support(features, sidecar):
    support = sidecar[["game_id", "home_current_support", "away_current_support", "home_prior_support", "away_prior_support"]]
    features = features.merge(support, on="game_id", how="left", validate="one_to_one")
    features["low_support"] = features.week.le(3) | features.home_current_support.lt(2) | features.away_current_support.lt(2)
    features["opener"] = features.home_current_support.eq(0) | features.away_current_support.eq(0)
    features["zero_prior_support"] = features.home_prior_support.eq(0) | features.away_prior_support.eq(0)
    return features


def concat(parts, empty):
    return pd.concat(parts, ignore_index=True) if parts else empty.copy()


def run_stage(out, stage):
    development = stage == "development"
    maximum = 2022 if development else 2025
    if not development and not (out / "FROZEN_SELECTION.json").exists():
        raise ValueError("freeze Development selection before loading later outcomes")
    if development and (out / "FROZEN_SELECTION.json").exists():
        raise ValueError("Development already frozen; use separate output directory for a replay")
    frozen = None if development else json.loads((out / "FROZEN_SELECTION.json").read_text())
    games, features = prepare(out, maximum)
    # Generate four fixed adjusted representations; two matched ablations share the same grid.
    sidecars = {}
    needed = [(mode, penalty) for mode in ("A", "B", "U_A", "U_B") for penalty in study.GRID]
    if not development:
        needed = [(mode, float(frozen["lambdaPrior"])) for mode in ("A", "B", "U_A", "U_B")]
    for mode, penalty in needed:
        sidecars[(mode, penalty)] = study.strength_features(games, features, mode, penalty, out)
    support_key = ("A", 12.0 if development else float(frozen["lambdaPrior"]))
    features = add_support(features, sidecars[support_key])
    empty = empty_previous(features)
    all_predictions = {arm: [] for arm in study.ACTUAL_ARMS}
    all_scores = []
    grid_predictions = {study.config_id(mode, penalty): [] for mode in ("A", "B") for penalty in study.GRID}
    grid_scores = []
    if not development:
        prior = pd.read_parquet(out / "data/development-predictions.parquet")
        for arm in study.ACTUAL_ARMS:
            all_predictions[arm].append(prior.loc[prior.arm.eq(arm)].copy())
        all_scores.append(pd.read_parquet(out / "data/development-scores.parquet"))
    fold_receipts = []
    seasons = range(2016, 2023) if development else range(2023, 2026)
    retained = pd.read_parquet(BASE / "data/season-forward-predictions.parquet", filters=[("season", "<=", maximum)])
    for season in seasons:
        before = time.monotonic()
        grid_before = concat(grid_scores, pd.DataFrame())
        penalty = study.choose_lambda(grid_before, season) if development else float(frozen["lambdaPrior"])
        print(f"FOLD {season}: selected shared lambda={penalty:g}; all fits exclude target-season outcomes", flush=True)
        if development:
            for mode in ("A", "B"):
                for value in study.GRID:
                    key = study.config_id(mode, value)
                    previous = concat(grid_predictions[key], empty)
                    target = study.fit_predict(features, sidecars[(mode, value)], season, key, previous, out, value)
                    scores = study.score_predictions(target, previous)
                    if not scores.empty:
                        scores["gridMode"] = mode
                        grid_scores.append(scores)
                    grid_predictions[key].append(target)
        receipt = {"targetSeason": season, "lambdaPrior": penalty,
                   "lambdaSelectionMaximumSeason": min(season-1, 2022), "pointPredictionMaximumDifference": {}}
        for arm in study.ACTUAL_ARMS:
            previous = concat(all_predictions[arm], empty)
            sidecar = None if arm == "baseline" else sidecars[(arm, penalty)]
            target = study.fit_predict(features, sidecar, season, arm, previous, out, None if arm == "baseline" else penalty)
            if arm == "baseline":
                saved = retained.loc[retained.season.eq(season)].set_index("game_id").loc[target.game_id]
                for key in ("home", "away", "margin", "total"):
                    error = float(np.max(np.abs(target[f"pred_{key}"].to_numpy()-saved[f"ridge_alpha100_pred_{key}"].to_numpy())))
                    receipt["pointPredictionMaximumDifference"][key] = error
                    if error > 1e-9:
                        raise ValueError(f"baseline OOF reproduction failed {season} {key} {error}")
            scores = study.score_predictions(target, previous)
            if not scores.empty:
                all_scores.append(scores)
            all_predictions[arm].append(target)
            target.to_parquet(out / "data" / f"predictions-{season}-{arm}.parquet", index=False)
            if not scores.empty:
                scores.to_parquet(out / "data" / f"scores-{season}-{arm}.parquet", index=False)
        fold_receipts.append(receipt)
        study.write_json(out / "models" / f"fold-{season}-receipt.json", receipt)
        print(f"FOLD {season} complete ({time.monotonic()-before:.1f}s); baseline exact", flush=True)
    predictions = pd.concat([concat(parts, empty) for parts in all_predictions.values()], ignore_index=True)
    scores = pd.concat(all_scores, ignore_index=True)
    for season, season_rows in scores.groupby("season"):
        populations = [set(x.game_id) for _, x in season_rows.groupby("arm")]
        if any(x != populations[0] for x in populations):
            raise ValueError("arm common-population failure")
        donor_keys = season_rows.groupby("arm").donorIdentitySha256.unique().map(tuple)
        if len(set(donor_keys)) != 1:
            raise ValueError("arm donor identity mismatch")
    if development:
        predictions.to_parquet(out / "data/development-predictions.parquet", index=False)
        scores.to_parquet(out / "data/development-scores.parquet", index=False)
        grid = pd.concat(grid_scores, ignore_index=True)
        grid.to_parquet(out / "data/development-grid-scores.parquet", index=False)
        grid_points = pd.concat([concat(parts, empty) for parts in grid_predictions.values()], ignore_index=True)
        grid_points.to_parquet(out / "data/development-grid-predictions.parquet", index=False)
        final_lambda = study.choose_lambda(grid, 2023)
        means = scores.loc[scores.arm.isin(["A", "B"])].groupby("arm").jointEnergyScore.mean()
        chosen = "B" if means["B"] < means["A"]-.02 else "A"
        frozen = {"schema": "CFB_STRENGTH_FROZEN_SELECTION_V1", "frozenAtUtc": datetime.now(timezone.utc).isoformat(),
                  "maximumOutcomeSeasonRead": 2022, "lambdaPrior": final_lambda, "selectedArm": chosen,
                  "nestedDevelopmentEnergy": means.to_dict(), "gridDevelopmentEnergy": grid.groupby(["lambda_prior", "gridMode"]).jointEnergyScore.mean().to_dict(),
                  "design": study.binding(out / "DESIGN.json"), "gridScores": study.binding(out / "data/development-grid-scores.parquet"),
                  "developmentScores": study.binding(out / "data/development-scores.parquet"),
                  "foldReceipts": fold_receipts, "laterEvidenceOpenedByThisStage": False}
        study.write_json(out / "FROZEN_SELECTION.json", frozen)
        print(json.dumps(study.clean(frozen), indent=2), flush=True)
    else:
        predictions.to_parquet(out / "COMMON_POPULATION_PREDICTIONS.parquet", index=False)
        scores.to_parquet(out / "COMMON_POPULATION_SCORES.parquet", index=False)
        study.assess(scores, frozen, out)
        print((out / "DECISION.json").read_text(), flush=True)
    return predictions, scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["development", "assessment"], required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=1):
        run_stage(args.output, args.stage)


if __name__ == "__main__":
    main()
