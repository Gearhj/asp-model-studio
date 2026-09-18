"""Bounded private CFB score-strength research; no operational entry points."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from . import pipeline as baseline

GRID = (4.0, 12.0)
ACTUAL_ARMS = ("baseline", "A", "B", "U_A", "U_B")
EXTRA_FEATURES = ["strength_pred_margin", "strength_pred_total"]
METRICS = ["jointEnergyScore", "jointWinnerLogLoss", "jointBinaryBrier", "marginCrps", "totalCrps",
           "scoreAbsoluteError", "marginAbsoluteError", "totalAbsoluteError"]


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2), encoding="utf-8")
    return binding(path)


def binding(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def reject_future(frame):
    if not frame.empty and (frame.season > 2025).any():
        raise ValueError("2026 and later outcomes are excluded")


def eligible_history(games, origin, target_season, primary_only=True):
    """A reconstruction gate, never a claimed genuine completion timestamp."""
    reject_future(games)
    origin = pd.Timestamp(origin)
    if origin.tzinfo is None:
        raise ValueError("UTC-aware origin required")
    origin = origin.tz_convert("UTC").floor("D")
    final = games.is_final.fillna(False).astype(bool)
    scores = np.isfinite(games[["home_score", "away_score"]].to_numpy(float)).all(axis=1)
    mask = final & scores & games.season.le(int(target_season)) & games.scheduled_at.le(origin-pd.Timedelta(hours=48))
    if primary_only:
        mask &= games.primary.astype(bool)
    return games.loc[mask].sort_values(["scheduled_at", "game_id"]).copy()


def prior_oof(predictions, season):
    reject_future(predictions)
    if predictions.empty:
        return predictions.copy()
    return predictions.loc[predictions.season.lt(int(season))].sort_values(["scheduled_at", "game_id"]).copy()


def choose_lambda(grid_scores, season):
    if grid_scores.empty:
        return 12.0
    eligible = grid_scores.loc[grid_scores.season.lt(season) & grid_scores.season.le(2022)]
    if eligible.season.nunique() < 2:
        return 12.0
    means = eligible.groupby("lambda_prior").jointEnergyScore.mean()
    if not all(value in means.index for value in GRID):
        raise ValueError("incomplete earlier Development grid")
    best = float(means.min())
    return 12.0 if float(means.loc[12.0]) <= best + .005 else 4.0


def checked_baseline_features(games):
    reject_future(games)
    if games.game_id.duplicated().any():
        raise ValueError("duplicate game identity")
    context = games.loc[games.context_eligible]
    if not context.is_final.all() or not np.isfinite(context[["home_score", "away_score"]].to_numpy(float)).all():
        raise ValueError("baseline context must be source-declared final with scores")
    result = baseline.build_features(games)
    result["research_origin"] = result.scheduled_at.dt.floor("D")
    source = result.feature_max_source_game_date
    valid = source.isna() | source.le(result.research_origin-pd.Timedelta(hours=48))
    if not valid.all():
        raise ValueError("original baseline features violate the common 48-hour reconstruction gate")
    return result


def config_id(mode, penalty):
    return f"{mode}_lambda{int(penalty)}"


def strength_features(games, features, mode, penalty, out):
    from .opponent_strength import fit_strength, predict_strength
    target = features.loc[features.primary & features.is_final].copy()
    path = out / "features" / f"{config_id(mode, penalty)}-through-{int(games.season.max())}.parquet"
    if path.exists():
        cached = pd.read_parquet(path)
        if not set(cached.game_id) == set(target.game_id):
            raise ValueError("cached feature population mismatch")
        return cached
    pieces, snapshots = [], {}
    earlier_caches = sorted((out / "features").glob(f"{config_id(mode, penalty)}-through-*.parquet")) if (out / "features").exists() else []
    for cache in reversed(earlier_caches):
        old_max = int(cache.stem.split("-through-")[-1])
        if old_max < int(games.season.max()):
            old = pd.read_parquet(cache)
            old_ids = set(old.game_id)
            expected = set(target.loc[target.season.le(old_max), "game_id"])
            if old_ids != expected:
                raise ValueError("feature-prefix identity mismatch")
            pieces.append(old)
            snapshots.update(joblib.load(out / "models" / f"strength-{config_id(mode, penalty)}-through-{old_max}.joblib"))
            target = target.loc[~target.game_id.isin(old_ids)]
            break
    for counter, (origin, rows) in enumerate(target.groupby("research_origin", sort=True)):
        if counter % 100 == 0:
            print(f"FEATURES {mode} lambda={penalty:g}: origin {counter} {origin.date()}", flush=True)
        seasons = rows.season.unique()
        if len(seasons) != 1:
            raise ValueError("mixed-season primary UTC origin")
        season = int(seasons[0])
        history = eligible_history(games, origin, season)
        artifact = fit_strength(history, season, penalty, mode.endswith("B"), not mode.startswith("U_"))
        predicted = predict_strength(artifact, rows.drop(columns=["home_score", "away_score", "home_margin", "total_points", "home_win"]))
        predicted = predicted.reset_index(drop=True)
        predicted["game_id"] = rows.game_id.to_numpy()
        predicted["origin"] = origin
        predicted["eligible_history_games"] = len(history)
        predicted["history_latest_kickoff"] = history.scheduled_at.max() if len(history) else pd.NaT
        pieces.append(predicted)
        snapshots[str(origin)] = {"artifact": artifact, "historyGameIds": history.game_id.to_list(),
                                  "origin": origin, "reconstructedEmbargoHours": 48,
                                  "certifiedCompletionAvailability": False}
    result = pd.concat(pieces, ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(path, index=False)
    (out / "models").mkdir(exist_ok=True)
    joblib.dump(snapshots, out / "models" / f"strength-{config_id(mode, penalty)}-through-{int(games.season.max())}.joblib", compress=3)
    return result


def fit_predict(features, sidecar, season, arm, previous, out, penalty=None):
    reject_future(features)
    if int(season) > 2025:
        raise ValueError("2026 and later targets excluded")
    primary = features.loc[features.primary & features.is_final].copy()
    columns = list(baseline.FEATURE_COLUMNS)
    if sidecar is not None:
        keep = [col for col in sidecar.columns if col == "game_id" or col not in primary.columns]
        primary = primary.merge(sidecar[keep], on="game_id", validate="one_to_one")
        columns += EXTRA_FEATURES
    train, target = primary.loc[primary.season.lt(season)], primary.loc[primary.season.eq(season)].copy()
    if train.empty or target.empty:
        raise ValueError("empty fold")
    if target.game_id.duplicated().any() or not train.scheduled_at.lt(target.scheduled_at.min()).all():
        raise ValueError("fold identity or chronological origin violation")
    models = {key: baseline.make_model("ridge", {"alpha": 100.0}).fit(train[columns], train[label])
              for key, label in (("margin", "home_margin"), ("total", "total_points"))}
    for key, model in models.items():
        target[f"pred_{key}"] = model.predict(target[columns])
    target["pred_home"] = (target.pred_total + target.pred_margin)/2
    target["pred_away"] = (target.pred_total - target.pred_margin)/2
    earlier = prior_oof(previous, season)
    if len(earlier) and not earlier.scheduled_at.lt(target.scheduled_at.min()).all():
        raise ValueError("calibration chronology violation")
    calibrator = None
    target["calibratedHomeWinProbability"] = np.nan
    if len(earlier) and earlier.home_win.nunique() == 2:
        calibrator = LogisticRegression(C=1.0, solver="lbfgs", random_state=baseline.SEED).fit(
            earlier[["pred_margin"]].to_numpy(), earlier.home_win.astype(int).to_numpy())
        target["calibratedHomeWinProbability"] = calibrator.predict_proba(target[["pred_margin"]].to_numpy())[:, 1]
    target["arm"] = arm
    target["lambda_prior"] = penalty if penalty is not None else np.nan
    target["trainingGames"] = len(train)
    target["trainingThroughSeason"] = int(train.season.max())
    target["calibrationDonorGames"] = len(earlier)
    target["calibrationThroughSeason"] = int(earlier.season.max()) if len(earlier) else np.nan
    artifact = {"schema": "CFB_STRENGTH_RESEARCH_FOLD_V1", "arm": arm, "targetSeason": season,
                "trainingGameIds": train.game_id.to_list(), "trainingThroughSeason": int(train.season.max()),
                "columns": columns, "models": models, "calibrator": calibrator,
                "calibrationGameIds": earlier.game_id.to_list(), "lambda": penalty,
                "researchOnly": True, "productionAuthority": False}
    model_path = out / "models" / f"fold-{season}-{arm}.joblib"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path, compress=3)
    return target.reset_index(drop=True)


def score_predictions(targets, previous, draw_count=10000):
    if targets.empty:
        return pd.DataFrame()
    reject_future(targets)
    if targets.game_id.duplicated().any():
        raise ValueError("duplicate target identity")
    season = int(targets.season.iloc[0])
    if targets.season.nunique() != 1:
        raise ValueError("score one chronological season at a time")
    donors = prior_oof(previous, season)
    if len(donors) and not donors.scheduled_at.lt(targets.scheduled_at.min()).all():
        raise ValueError("donor chronology violation")
    if len(donors) < 500:
        return pd.DataFrame()
    if donors.game_id.duplicated().any() or set(targets.game_id) & set(donors.game_id):
        raise ValueError("donor identity violation")
    # A fixed model label gives all arms exactly the baseline random-number seed.
    label = "ridge_alpha100"
    donor_view = donors.copy()
    for side in ("home", "away"):
        donor_view[f"{label}_pred_{side}"] = donors[f"pred_{side}"].to_numpy()
    rows = []
    for _, original in targets.iterrows():
        row = original.copy()
        for side in ("home", "away"):
            row[f"{label}_pred_{side}"] = row[f"pred_{side}"]
        draws, accounting = baseline.simulate_paired_residuals(row, donor_view, label, draw_count=draw_count)
        scores = baseline.score_distribution(draws, row)
        scores.update({"arm": row.arm, "lambda_prior": row.lambda_prior,
                       "low_support": bool(row.low_support), "opener": bool(row.opener),
                       "zero_prior_support": bool(row.zero_prior_support),
                       "home_current_support": int(row.home_current_support), "away_current_support": int(row.away_current_support),
                       "home_id": int(row.home_id), "away_id": int(row.away_id),
                       "donorCount": len(donors), "donorMaximumSeason": int(donors.season.max()),
                       "donorIdentitySha256": hashlib.sha256(baseline.canonical_json(donors.game_id.to_list())).hexdigest(),
                       "initialRoundedTieCount": accounting["initialRoundedTieCount"],
                       "rawNegativeHomeCount": accounting["rawNegativeHomeCount"], "rawNegativeAwayCount": accounting["rawNegativeAwayCount"],
                       "calibratedHomeWinProbability": row.calibratedHomeWinProbability,
                       "jointFinalHomeMean": float(draws.home_score.mean()), "jointFinalAwayMean": float(draws.away_score.mean())})
        for key, prediction, observed in (("home", row.pred_home, row.home_score), ("away", row.pred_away, row.away_score),
                                          ("margin", row.pred_margin, row.home_margin), ("total", row.pred_total, row.total_points)):
            error = float(prediction-observed)
            scores.update({f"{key}Prediction": float(prediction), f"{key}Error": error,
                           f"{key}AbsoluteError": abs(error), f"{key}SquaredError": error**2})
        scores["scoreAbsoluteError"] = (scores["homeAbsoluteError"]+scores["awayAbsoluteError"])/2
        scores["scoreSquaredError"] = (scores["homeSquaredError"]+scores["awaySquaredError"])/2
        p = row.calibratedHomeWinProbability
        if np.isfinite(p):
            p = np.clip(p, 1e-12, 1-1e-12)
            scores["calibratedWinnerLogLoss"] = float(-row.home_win*np.log(p)-(1-row.home_win)*np.log(1-p))
            scores["calibratedBrier"] = float((p-row.home_win)**2)
        rows.append(scores)
    return pd.DataFrame(rows)


def paired_effects(base, candidate, repetitions=2000):
    b, c = base.set_index("game_id").sort_index(), candidate.set_index("game_id").sort_index()
    if not b.index.equals(c.index):
        raise ValueError("different common population")
    if not len(b):
        return {"games": 0, "blocks": 0, "metrics": {}}
    delta = c[METRICS].to_numpy(float)-b[METRICS].to_numpy(float)
    block = b.scheduled_at.dt.strftime("%G-W%V")
    rng = np.random.default_rng(20260918)
    total = np.zeros((repetitions, len(METRICS)))
    total_n = np.zeros(repetitions)
    block_count = 0
    for season in sorted(b.season.unique()):
        mask = b.season.eq(season)
        keys = sorted(block[mask].unique())
        sums = np.array([delta[(mask & block.eq(k)).to_numpy()].sum(axis=0) for k in keys])
        counts = np.array([(mask & block.eq(k)).sum() for k in keys])
        picks = rng.integers(0, len(keys), (repetitions, len(keys)))
        total += sums[picks].sum(axis=1)
        total_n += counts[picks].sum(axis=1)
        block_count += len(keys)
    draws = total / total_n[:, None]
    return {"games": len(b), "blocks": block_count, "bootstrapReplicates": repetitions,
            "method": "PAIRED_CALENDAR_WEEK_BLOCK_BOOTSTRAP_STRATIFIED_BY_SEASON", "direction": "CANDIDATE_MINUS_BASELINE",
            "metrics": {metric: {"delta": float(delta[:, j].mean()), "low95": float(np.quantile(draws[:, j], .025)),
                                   "high95": float(np.quantile(draws[:, j], .975))} for j, metric in enumerate(METRICS)}}


def aggregate_scores(rows):
    result = {"games": len(rows), "blocks": rows.scheduled_at.dt.strftime("%G-W%V").nunique()}
    for name in METRICS + ["calibratedWinnerLogLoss", "calibratedBrier"]:
        result[name] = float(rows[name].mean())
    for key in ("home", "away", "score", "margin", "total"):
        result[key+"Mae"] = float(rows[key+"AbsoluteError"].mean())
        result[key+"Rmse"] = float(np.sqrt(rows[key+"SquaredError"].mean()))
        if key != "score":
            result[key+"Bias"] = float(rows[key+"Error"].mean())
            for level in (80, 90):
                result[f"{key}Coverage{level}"] = float(rows[f"{key}Coverage{level}"].mean())
                result[f"{key}Width{level}"] = float(rows[f"{key}Width{level}"].mean())
    return result


def assess(all_scores, frozen, out):
    summaries, effects = [], []
    periods = {"development": list(range(2017, 2023)), "reused_validation": [2023, 2024], "reused_2025": [2025],
               "all_reused": [2023, 2024, 2025], **{str(s): [s] for s in range(2017, 2026)}}
    for period, seasons in periods.items():
        population = all_scores.loc[all_scores.season.isin(seasons)]
        for subgroup in ("overall", "low_support", "ordinary_support", "opener", "zero_prior_support"):
            subset = population
            if subgroup == "ordinary_support":
                subset = subset.loc[~subset.low_support]
            elif subgroup != "overall":
                subset = subset.loc[subset[subgroup]]
            if subset.empty:
                continue
            for arm, rows in subset.groupby("arm"):
                summaries.append({"period": period, "subgroup": subgroup, "arm": arm, **aggregate_scores(rows)})
            comparisons = [("baseline", arm) for arm in ACTUAL_ARMS[1:]] + [("U_A", "A"), ("U_B", "B"), ("A", "B"), ("U_A", "U_B")]
            for reference, arm in comparisons:
                result = paired_effects(subset.loc[subset.arm.eq(reference)], subset.loc[subset.arm.eq(arm)])
                effects.append({"period": period, "subgroup": subgroup, "reference": reference, "arm": arm, **result})
    summary = pd.DataFrame(summaries)
    summary.to_csv(out / "COMPARISON.csv", index=False)
    write_json(out / "PAIRED_EFFECTS.json", effects)
    selected = frozen["selectedArm"]
    def delta(period, subgroup="overall"):
        return next(x for x in effects if x["period"] == period and x["subgroup"] == subgroup and x["arm"] == selected and x["reference"] == "baseline")
    dev, val, later, low = delta("development"), delta("reused_validation"), delta("reused_2025"), delta("reused_validation", "low_support")
    e = "jointEnergyScore"
    gates = {"developmentEnergyAtLeast005": dev["metrics"][e]["delta"] <= -.05,
             "validationEnergyAtLeast010": val["metrics"][e]["delta"] <= -.10,
             "validationEnergyUpper95BelowZero": val["metrics"][e]["high95"] < 0,
             "bothValidationSeasonsImprove": all(delta(str(s))["metrics"][e]["delta"] < 0 for s in (2023, 2024)),
             "secondary2025NoMaterialHarm": later["metrics"][e]["delta"] <= .05,
             "lowSupportAdequate": low["games"] >= 100 and low["blocks"] >= 15,
             "lowSupportMeanNoMaterialHarm": low["metrics"][e]["delta"] <= .05,
             "lowSupportUpper95NoMaterialHarm": low["metrics"][e]["high95"] <= .15}
    for metric, tolerance in (("jointWinnerLogLoss", .005), ("jointBinaryBrier", .002), ("marginCrps", .05), ("totalCrps", .05)):
        gates[metric+"Guardrail"] = val["metrics"][metric]["delta"] <= tolerance
    decision = {"selectedArm": selected, "gates": gates, "allPass": all(gates.values()),
                "disposition": "PROPOSE_FROZEN_PROSPECTIVE_SHADOW" if all(gates.values()) else "DO_NOT_ADVANCE_UNDER_FROZEN_GATE",
                "productionChanged": False, "validationIsReused": True, "2025IsReused": True}
    write_json(out / "DECISION.json", decision)
    return summary, effects, decision
