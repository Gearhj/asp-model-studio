"""Run the frozen NBA Gen2 team-box comparison from retained local evidence.

No network, exchange, AISP, scheduler, or production activation interface is
present. Large derived data and fitted objects are written beneath ignored
outputs; concise receipts are copied to reviewed documentation separately.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_nba_gen1.distribution import empirical_crps, game_seed, simulate
from server.sports_nba_gen1.joint_residual_scoring import energy_score
from server.sports_nba_gen1.recent_features import recent_feature_contract
from server.sports_nba_gen1.rest_support import learn_rest_support, transform_rest
from server.sports_nba_gen2.team_box_study import build_pregame_box_features, load_governed_population


CONFIGS = {
    "GEN2_RIDGE_A100_TEAM_BOX_V1": {"family": "ridge", "alpha": 100.0},
    "GEN2_HGB_L2_10_TEAM_BOX_V1": {
        "family": "hgb", "learning_rate": 0.05, "max_iter": 150,
        "max_leaf_nodes": 15, "min_samples_leaf": 40, "max_bins": 255,
        "early_stopping": False, "random_state": 731001, "loss": "squared_error",
        "l2_regularization": 10.0,
    },
}
BASELINE_ROOT = Path(r"C:\Users\james\asp-model-studio\outputs")
RECEIPT = Path(r"C:\Users\james\asp-data-staging\nba\gen2-team-box-v1\acquisition-receipt.json")
QUARANTINE = ("401704652",)
DRAW_COUNT = 10_000
MASTER_SEED = 731001


def canonical_hash(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_gen1_features() -> pd.DataFrame:
    path = BASELINE_ROOT / "nba-gen1-long-gap-v1/assessment-2026/features.parquet"
    frame = pd.read_parquet(path).copy()
    frame["game_date"] = pd.to_datetime(frame.game_date).dt.date.astype(str)
    return frame


def load_exact_gen1_predictions() -> pd.DataFrame:
    paths = [
        BASELINE_ROOT / "nba-gen1-long-gap-v1/development/predictions.parquet",
        BASELINE_ROOT / "nba-gen1-long-gap-v1/reused-diagnostics/predictions.parquet",
        BASELINE_ROOT / "nba-gen1-long-gap-v1/assessment-2026/predictions.parquet",
    ]
    rows = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    rows = rows[rows.model_id.eq("ridge_a100_rest")].copy()
    rows["game_date"] = pd.to_datetime(rows.game_date).dt.date.astype(str)
    if rows.duplicated("game_id").any():
        raise RuntimeError("Exact Gen1 point predictions are not unique")
    return rows


def load_exact_gen1_joint() -> pd.DataFrame:
    frames = []
    for season in range(2022, 2027):
        path = BASELINE_ROOT / f"nba-gen1-joint-residual-v1/assessment/{season}/scores.parquet"
        frame = pd.read_parquet(path)
        frame = frame[frame.configuration.eq("paired")].copy()
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True)
    rows["game_date"] = pd.to_datetime(rows.game_date).dt.date.astype(str)
    if rows.duplicated("game_id").any():
        raise RuntimeError("Exact Gen1 joint scores are not unique")
    return rows


def fit_configuration(config_id: str, train: pd.DataFrame, feature_columns: list[str]):
    params = CONFIGS[config_id]
    support = learn_rest_support(train)
    treated, _ = transform_rest(train, support)
    x = treated[feature_columns].to_numpy(float)
    y = np.column_stack((train.home_score - train.away_score, train.home_score + train.away_score))
    if params["family"] == "ridge":
        estimator = Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=params["alpha"], solver="svd")),
        ])
        estimator.fit(x, y)
        estimators = {"margin_total": estimator}
    else:
        estimators = {}
        for index, target in enumerate(("margin", "total")):
            kwargs = {key: value for key, value in params.items() if key != "family"}
            estimator = Pipeline([
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("model", HistGradientBoostingRegressor(**kwargs)),
            ])
            with threadpool_limits(limits=1, user_api="openmp"):
                estimator.fit(x, y[:, index])
            estimators[target] = estimator
    identity = canonical_hash({"configuration": config_id, "featureColumns": feature_columns,
                               "trainingGameIds": train.game_id.astype(str).tolist(),
                               "restSupport": support, "params": params})
    return {"configuration": config_id, "estimators": estimators, "restSupport": support,
            "featureColumns": feature_columns, "identity": identity, "params": params}


def predict_model(model, target: pd.DataFrame) -> np.ndarray:
    treated, _ = transform_rest(target, model["restSupport"])
    x = treated[model["featureColumns"]].to_numpy(float)
    if model["params"]["family"] == "ridge":
        margin_total = model["estimators"]["margin_total"].predict(x)
    else:
        with threadpool_limits(limits=1, user_api="openmp"):
            margin_total = np.column_stack((model["estimators"]["margin"].predict(x),
                                            model["estimators"]["total"].predict(x)))
    return np.column_stack(((margin_total[:, 1] + margin_total[:, 0]) / 2,
                            (margin_total[:, 1] - margin_total[:, 0]) / 2))


def point_scores(rows: pd.DataFrame) -> dict:
    ah, aa = rows.home_score.to_numpy(float), rows.away_score.to_numpy(float)
    ph, pa = rows.expected_home_score.to_numpy(float), rows.expected_away_score.to_numpy(float)
    return {
        "games": int(len(rows)), "homeMae": float(np.mean(abs(ph - ah))),
        "awayMae": float(np.mean(abs(pa - aa))),
        "teamScoreMae": float(np.mean(np.r_[abs(ph - ah), abs(pa - aa)])),
        "marginMae": float(np.mean(abs((ph - pa) - (ah - aa)))),
        "totalMae": float(np.mean(abs((ph + pa) - (ah + aa)))),
        "teamScoreMse": float(np.mean(np.r_[(ph - ah) ** 2, (pa - aa) ** 2])),
    }


def calibration(truth, probability) -> dict:
    truth = np.asarray(truth, int); probability = np.clip(np.asarray(probability, float), 1e-6, 1 - 1e-6)
    logits = np.log(probability / (1 - probability)).reshape(-1, 1)
    fitted = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000).fit(logits, truth)
    bins = np.minimum((probability * 10).astype(int), 9)
    reliability = []
    ece = 0.0
    for index in range(10):
        mask = bins == index
        if not mask.any():
            continue
        predicted, observed, count = probability[mask].mean(), truth[mask].mean(), int(mask.sum())
        ece += count / len(truth) * abs(predicted - observed)
        reliability.append({"bin": index, "games": count, "meanProbability": float(predicted),
                            "observedHomeWinRate": float(observed)})
    return {"intercept": float(fitted.intercept_[0]), "slope": float(fitted.coef_[0, 0]),
            "expectedCalibrationError10Bins": float(ece), "reliability": reliability}


def aggregate_distribution(rows: pd.DataFrame) -> dict:
    result = {"games": int(len(rows))}
    for source, target in [
        ("energy", "jointEnergy"), ("total_crps", "totalCrps"), ("margin_crps", "marginCrps"),
        ("home_crps", "homeCrps"), ("away_crps", "awayCrps"), ("log_loss", "winnerLogLoss"),
        ("binary_brier", "binaryBrier"), ("home_mae", "homeMae"), ("away_mae", "awayMae"),
        ("total_mae", "totalMae"), ("margin_mae", "marginMae")]:
        result[target] = float(rows[source].mean())
    result["teamScoreMae"] = float((rows.home_mae.mean() + rows.away_mae.mean()) / 2)
    result["correctPickRate"] = float(rows.correct_pick.mean())
    for name in ("home", "away", "total", "margin"):
        for level in (50, 80, 90):
            result[f"{name}{level}Coverage"] = float(rows[f"{name}_{level}_coverage"].mean())
            result[f"{name}{level}Width"] = float(rows[f"{name}_{level}_width"].mean())
    result["calibration"] = calibration(rows.actual_home.gt(rows.actual_away).astype(int),
                                         rows.home_win_probability)
    return result


def bootstrap_difference(joined: pd.DataFrame, candidate_col: str, baseline_col: str,
                         replicates=2000, seed=731201) -> dict:
    work = joined.copy()
    work["week"] = pd.to_datetime(work.game_date).dt.to_period("W-SUN").astype(str)
    groups = list(work.groupby("week").groups.values())
    rng = np.random.default_rng(seed)
    differences = np.empty(replicates)
    for index in range(replicates):
        sampled = rng.integers(0, len(groups), size=len(groups))
        indices = np.concatenate([np.asarray(groups[item]) for item in sampled])
        differences[index] = (work.loc[indices, candidate_col] - work.loc[indices, baseline_col]).mean()
    observed = float((work[candidate_col] - work[baseline_col]).mean())
    return {"difference": observed, "interval95": np.quantile(differences, [0.025, 0.975]).tolist(),
            "calendarWeeks": len(groups), "replicates": replicates, "seed": seed}


def candidate_distribution_scores(predictions: pd.DataFrame, population, config_id: str) -> pd.DataFrame:
    residuals = predictions.copy()
    residuals["home_residual"] = residuals.home_score - residuals.expected_home_score
    residuals["away_residual"] = residuals.away_score - residuals.expected_away_score
    overtime = population.overtime_periods.copy()
    output = []
    for row in predictions[predictions.season_end.ge(2022)].itertuples():
        donors = residuals[(residuals.game_date < row.game_date) & (residuals.season_end < row.season_end)]
        ot = overtime[overtime.game_date < row.game_date]
        if len(donors) < 100 or not len(ot):
            raise RuntimeError(f"Insufficient chronological distribution donors for {row.game_id}")
        population_draw = simulate(
            float(row.expected_home_score), float(row.expected_away_score),
            donors[["home_residual", "away_residual"]].to_numpy(float),
            game_seed(str(row.game_id), config_id, MASTER_SEED), DRAW_COUNT,
            ot[["home_points", "away_points"]].to_numpy(int),
        )
        home_draws, away_draws = population_draw["home_runs"], population_draw["away_runs"]
        actual_home, actual_away = int(row.home_score), int(row.away_score)
        p_home = float(np.mean(home_draws > away_draws)); truth = int(actual_home > actual_away)
        record = {
            "game_id": row.game_id, "game_date": row.game_date, "season_end": int(row.season_end),
            "home_team_code": row.home_team_code, "away_team_code": row.away_team_code,
            "actual_home": actual_home, "actual_away": actual_away,
            "configuration": config_id, "draw_count": DRAW_COUNT,
            "donors": int(len(donors)), "latest_donor_date": str(donors.game_date.max()),
            "home_win_probability": p_home, "away_win_probability": 1 - p_home,
            "tie_probability": 0.0,
            "log_loss": float(-np.log(max(p_home if truth else 1 - p_home, 1e-12))),
            "binary_brier": float((p_home - truth) ** 2),
            "energy": energy_score(home_draws, away_draws, actual_home, actual_away),
            "correct_pick": int((p_home > 0.5) == bool(truth)),
            "raw_tie_fraction": population_draw["diagnostics"]["rawTieFraction"],
            "overtime_mean_change_home": population_draw["diagnostics"]["overtimeMeanChangeHomeAway"][0],
            "overtime_mean_change_away": population_draw["diagnostics"]["overtimeMeanChangeHomeAway"][1],
            "actual_overtime": int(row.overtime_periods > 0),
        }
        for name, values, observed in (
                ("home", home_draws, actual_home), ("away", away_draws, actual_away),
                ("total", home_draws + away_draws, actual_home + actual_away),
                ("margin", home_draws - away_draws, actual_home - actual_away)):
            record[f"{name}_mean"] = float(values.mean())
            record[f"{name}_crps"] = empirical_crps(values, observed)
            record[f"{name}_mae"] = float(abs(values.mean() - observed))
            for level in (50, 80, 90):
                lower, upper = np.quantile(values, [(1 - level / 100) / 2, (1 + level / 100) / 2],
                                           method="inverted_cdf")
                record[f"{name}_{level}_coverage"] = int(lower <= observed <= upper)
                record[f"{name}_{level}_width"] = int(upper - lower)
        output.append(record)
    return pd.DataFrame(output)


def exact_common_baseline(exact: pd.DataFrame, candidate: pd.DataFrame) -> pd.DataFrame:
    common = exact.merge(candidate[["game_date", "season_end", "home_team_code", "away_team_code"]].drop_duplicates(),
                         on=["game_date", "season_end", "home_team_code", "away_team_code"], how="inner")
    return common


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/nba-gen2-production-readiness-v1")
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    population = load_governed_population(RECEIPT, excluded_integrity_game_ids=QUARANTINE)
    box_features, feature_audit = build_pregame_box_features(population)
    base = load_gen1_features()
    combined = base.merge(box_features, on=["game_date", "season_end", "home_team_code", "away_team_code"],
                          how="inner", suffixes=("", "_box"), validate="one_to_one")
    if ((combined.home_score != combined.home_score_box) | (combined.away_score != combined.away_score_box)).any():
        raise RuntimeError("Gen1 and retained box scores do not reconcile")
    combined = combined.drop(columns=["home_score_box", "away_score_box"])
    # Preserve the exact Gen1 target contract. Neutral-site and other
    # history-only rows may inform upstream histories but cannot become fitted
    # home/away assessment targets.
    combined = combined[combined.target_eligible.fillna(False).astype(bool)
                        & ~combined.neutral_site.fillna(True).astype(bool)].copy()
    combined = combined.sort_values(["game_date", "game_id"]).reset_index(drop=True)

    gen1_columns = list(recent_feature_contract()["numericFeatures"])
    box_columns = feature_audit["featureColumns"]
    feature_columns = gen1_columns + box_columns
    predictions = []
    model_receipts = []
    models_dir = out / "models"; models_dir.mkdir(exist_ok=True)
    for config_id in CONFIGS:
        for season in range(2021, 2027):
            train = combined[combined.season_end < season].copy()
            target = combined[combined.season_end == season].copy()
            if not len(train) or not len(target):
                continue
            model = fit_configuration(config_id, train, feature_columns)
            values = predict_model(model, target)
            frame = target[["game_id", "game_date", "season_end", "home_team_code", "away_team_code",
                            "home_score", "away_score", "overtime_periods"]].copy()
            frame["configuration"] = config_id
            frame["model_identity"] = model["identity"]
            frame["expected_home_score"] = values[:, 0]
            frame["expected_away_score"] = values[:, 1]
            predictions.append(frame)
            model_path = models_dir / f"{config_id}-{season}.joblib"
            joblib.dump(model, model_path)
            model_receipts.append({"configuration": config_id, "targetSeason": season,
                                   "trainingGames": int(len(train)), "assessmentGames": int(len(target)),
                                   "modelIdentity": model["identity"], "physicalSha256": file_hash(model_path),
                                   "bytes": model_path.stat().st_size})
    predictions = pd.concat(predictions, ignore_index=True)
    predictions.to_parquet(out / "candidate-point-predictions.parquet", index=False)

    exact_points = load_exact_gen1_predictions()
    point_summary = {}
    for season in range(2021, 2027):
        point_summary[str(season)] = {"GEN1_EXACT_RETAINED": point_scores(
            exact_common_baseline(exact_points[exact_points.season_end.eq(season)],
                                  predictions[predictions.season_end.eq(season)]))}
        for config_id in CONFIGS:
            point_summary[str(season)][config_id] = point_scores(
                predictions[(predictions.season_end == season) & (predictions.configuration == config_id)])

    candidate_scores = []
    for config_id in CONFIGS:
        candidate_scores.append(candidate_distribution_scores(
            predictions[predictions.configuration.eq(config_id)].copy(), population, config_id))
    candidate_scores = pd.concat(candidate_scores, ignore_index=True)
    candidate_scores.to_parquet(out / "candidate-joint-scores.parquet", index=False)
    exact_joint = load_exact_gen1_joint()

    results = {}
    paired = {}
    for season in range(2022, 2027):
        season_candidates = candidate_scores[candidate_scores.season_end.eq(season)]
        baseline = exact_common_baseline(exact_joint[exact_joint.season_end.eq(season)], season_candidates)
        results[str(season)] = {"GEN1_EXACT_RETAINED": aggregate_distribution(baseline)}
        for config_id in CONFIGS:
            candidate = season_candidates[season_candidates.configuration.eq(config_id)]
            candidate = candidate.merge(baseline[["game_date", "season_end", "home_team_code", "away_team_code"]],
                                        on=["game_date", "season_end", "home_team_code", "away_team_code"], how="inner")
            results[str(season)][config_id] = aggregate_distribution(candidate)
            joined = candidate.merge(baseline, on=["game_date", "season_end", "home_team_code", "away_team_code"],
                                     suffixes=("_candidate", "_baseline"), validate="one_to_one")
            paired[f"{season}:{config_id}"] = {
                "games": int(len(joined)),
                "jointEnergy": bootstrap_difference(joined, "energy_candidate", "energy_baseline"),
                "candidateMinusBaseline": {
                    metric: float((joined[f"{column}_candidate"] - joined[f"{column}_baseline"]).mean())
                    for metric, column in {
                        "teamScoreMae": "home_mae", "marginCrps": "margin_crps", "totalCrps": "total_crps",
                        "winnerLogLoss": "log_loss", "binaryBrier": "binary_brier",
                        "marginMae": "margin_mae", "totalMae": "total_mae",
                    }.items()
                },
            }
            paired[f"{season}:{config_id}"]["candidateMinusBaseline"]["teamScoreMae"] = float(
                ((joined.home_mae_candidate + joined.away_mae_candidate
                  - joined.home_mae_baseline - joined.away_mae_baseline) / 2).mean())

    gate = {}
    for config_id in CONFIGS:
        validation = paired[f"2024:{config_id}"]
        base_metrics, candidate_metrics = results["2024"]["GEN1_EXACT_RETAINED"], results["2024"][config_id]
        checks = {
            "energyRelativeImprovementAtLeast0.5Pct": ((base_metrics["jointEnergy"] - candidate_metrics["jointEnergy"])
                                                       / base_metrics["jointEnergy"] >= 0.005),
            "energyPaired95UpperBelowZero": validation["jointEnergy"]["interval95"][1] < 0,
            "teamScoreMaeImprovesAtLeast0.05": validation["candidateMinusBaseline"]["teamScoreMae"] <= -0.05,
            "marginCrpsWithin0.5Pct": candidate_metrics["marginCrps"] <= 1.005 * base_metrics["marginCrps"],
            "totalCrpsWithin0.5Pct": candidate_metrics["totalCrps"] <= 1.005 * base_metrics["totalCrps"],
            "winnerLogLossWithin1Pct": candidate_metrics["winnerLogLoss"] <= 1.01 * base_metrics["winnerLogLoss"],
            "binaryBrierWithin1Pct": candidate_metrics["binaryBrier"] <= 1.01 * base_metrics["binaryBrier"],
        }
        for season in (2025, 2026):
            bm, cm = results[str(season)]["GEN1_EXACT_RETAINED"], results[str(season)][config_id]
            checks[f"{season}EnergyWithin1Pct"] = cm["jointEnergy"] <= 1.01 * bm["jointEnergy"]
            checks[f"{season}TeamScoreMaeWithin0.10"] = cm["teamScoreMae"] <= bm["teamScoreMae"] + 0.10
        gate[config_id] = {"checks": checks, "passed": all(checks.values())}

    # Regulation versus observed-overtime sensitivity and simulator tie effects.
    overtime_sensitivity = {}
    for config_id in CONFIGS:
        subset = candidate_scores[candidate_scores.configuration.eq(config_id)]
        overtime_sensitivity[config_id] = {
            label: {"games": int(len(group)), "jointEnergy": float(group.energy.mean()),
                    "totalCrps": float(group.total_crps.mean()), "marginCrps": float(group.margin_crps.mean())}
            for label, group in (("regulation", subset[subset.actual_overtime.eq(0)]),
                                 ("overtime", subset[subset.actual_overtime.eq(1)]))
        }
        overtime_sensitivity[config_id]["tieResolution"] = {
            "meanRawTieFraction": float(subset.raw_tie_fraction.mean()),
            "meanHomeScoreChange": float(subset.overtime_mean_change_home.mean()),
            "meanAwayScoreChange": float(subset.overtime_mean_change_away.mean()),
        }

    advanced = [config_id for config_id, item in gate.items() if item["passed"]]
    disposition = "GEN2_ADVANCES" if advanced else "GEN1_REMAINS_BASELINE"
    summary = {
        "schemaVersion": "nba-gen2-production-readiness-assessment-v1",
        "startedAtUtc": started, "completedAtUtc": datetime.now(timezone.utc).isoformat(),
        "disposition": disposition, "advancedConfigurations": advanced,
        "selectedProductionBaseline": (advanced[0] if len(advanced) == 1 else
                                       "NBA_GEN1_PRODUCTION_BASELINE_V1" if not advanced else None),
        "populationAudit": population.audit, "featureAudit": feature_audit,
        "commonPopulation": {"rows": int(len(combined)), "bySeason": {
            str(int(key)): int(value) for key, value in combined.groupby("season_end").size().items()}},
        "pointResults": point_summary, "jointResults": results, "pairedResults": paired,
        "overtimeSensitivity": overtime_sensitivity, "gate": gate,
        "modelReceipts": model_receipts,
        "authority": {"researchOnly": True, "productionActivated": False,
                      "schedulerInstalled": False, "aispWrites": 0, "exchangeWrites": 0,
                      "providerCallsDuringStudy": 0},
    }
    summary["assessmentIdentitySha256"] = canonical_hash(summary)
    write_json(out / "ASSESSMENT.json", summary)
    write_json(out / "POPULATION_AUDIT.json", population.audit)
    write_json(out / "FEATURE_AUDIT.json", feature_audit)
    write_json(out / "MODEL_RECEIPTS.json", model_receipts)
    print(json.dumps({"disposition": disposition, "advanced": advanced,
                      "assessment": str(out / "ASSESSMENT.json"),
                      "identity": summary["assessmentIdentitySha256"]}, indent=2))


if __name__ == "__main__":
    main()
