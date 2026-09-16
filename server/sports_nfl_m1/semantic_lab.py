"""Bounded semantic NFL Development experiment and frozen research artifact."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from server.audit_assurance.canonical import canonical_json_bytes
from .data_authority import DEFAULT_NFL_STAGING_ROOT
from .distributions import PairedResidualAuthority, make_common_random_numbers, simulate_joint_scores
from .overnight_lab import _metrics, _outcome_class, _probabilities, _chronological_calibration, _paired_block_uncertainty, _plain_json
from .semantic_features import load_sources, make_history_features, SemanticTreatment, feature_policy

OUTPUT = Path("outputs/nfl-semantic-lab-v1")
SEED = 731001
DRAWS = 2000
BASELINE_ROOT = DEFAULT_NFL_STAGING_ROOT / "overnight-model-laboratory-v1/runs/matrix-fcc3cd9a5446-foundation-ebb6912919a5"
HGB = {"learning_rate": .05, "max_iter": 120, "max_leaf_nodes": 15, "min_samples_leaf": 20, "l2_regularization": 1.0}
XGB = {"n_estimators": 200, "max_depth": 3, "learning_rate": .03, "min_child_weight": 5.0, "subsample": .9, "colsample_bytree": .8, "reg_lambda": 5.0}
MATRIX = {"contract": "NFL_SEMANTIC_CANDIDATE_MATRIX_V1", "declaredBeforeFit": True,
          "developmentSeasons": [1999, 2024], "validationSeasons": [2020, 2021, 2022, 2023, 2024],
          "sealedSeason": 2025, "designs": {"C1": "team continuous priors, offseason regression, game-exposure shrinkage",
          "C2": "C1 + prior-game passing-personnel mixture; NOT known target starter",
          "C3": "C2 with fold-local experience/exposure prior pooling instead of league-only QB prior"},
          "families": {"XGBOOST": XGB, "HGB": HGB}, "transparentBaseline": "DYNAMIC_TEAM_SCORE_BLEND",
          "seed": SEED, "draws": DRAWS, "maximumNativeThreads": 2,
          "primarySelection": "raw three-way OOF log loss; top2 supported pipelines",
          "calibration": "multinomial logistic log-probability fitted on earlier OOF seasons only; first season RAW",
          "tuning": {"maximumFinalists": 2, "configurationsPerFinalist": 2, "selection": "one latest-season inner validation within each outer training period",
          "HGB": [HGB, {**HGB, "max_leaf_nodes": 7, "l2_regularization": 5.0}],
          "XGBOOST": [XGB, {**XGB, "max_depth": 2, "reg_lambda": 10.0}]},
          "commonRandomNumbers": "same seed per evaluation season, draw count and ordered event cohort for every candidate",
          "restrictions": {"researchOnly": True, "wageringAuthority": False, "executionAllowedInAISP": False, "finalOotRead": False},
          "missingSubgroups": "actual rookie, changed-target-starter, backup and current team-change labels are not pregame proven; only lagged exposure proxies"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def immutable_json(path: Path, value: Any) -> str:
    data = canonical_json_bytes(_plain_json(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"IMMUTABLE_COLLISION:{path}")
    else:
        with path.open("xb") as stream:
            stream.write(data)
    return hashlib.sha256(data).hexdigest()


def receipt(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(_plain_json({"time": datetime.now(timezone.utc).isoformat(), **value}), sort_keys=True) + "\n")


@dataclass
class SemanticScoreModel:
    treatment: SemanticTreatment
    family: str
    parameters: dict
    home: Any = None
    away: Any = None
    dynamic_offset: tuple[float, float] = (0., 0.)

    def predict(self, frame: pd.DataFrame):
        x, counts = self.treatment.transform(frame)
        if self.family == "DYNAMIC":
            names = list(self.treatment.names)
            home = .5 * (x[:, names.index("home_points_for_season_to_date")] + x[:, names.index("away_points_against_season_to_date")]) + self.dynamic_offset[0]
            away = .5 * (x[:, names.index("away_points_for_season_to_date")] + x[:, names.index("home_points_against_season_to_date")]) + self.dynamic_offset[1]
        else:
            home, away = self.home.predict(x), self.away.predict(x)
        return np.maximum(home, 0), np.maximum(away, 0), counts


@dataclass
class SemanticForecastArtifact:
    """Complete score and residual authority; calibrator is separately labeled."""
    model: SemanticScoreModel
    residual: PairedResidualAuthority
    calibrator: Any
    pipeline_id: str
    authority: dict

    def predict(self, frame: pd.DataFrame, *, seed: int = SEED, draws: int = DRAWS):
        home, away, counts = self.model.predict(frame)
        simulation = simulate_joint_scores(predicted_home_mean=home, predicted_away_mean=away,
            residual_authority=self.residual, draws=draws, seed=seed,
            common_random_numbers=make_common_random_numbers(n_games=len(frame), draws=draws, seed=seed))
        raw = _probabilities(simulation)
        calibrated = self.calibrator.predict_proba(np.log(raw)) if self.calibrator is not None else raw.copy()
        return {"scoreMeans": np.column_stack([home, away]), "simulation": simulation,
                "rawProbability": raw, "separateCalibratedProbability": calibrated,
                "calibratedProbabilityIsJointDistribution": False, "branchCounts": counts}


def fit_model(design, family, params, train, team, qb, log, tag):
    treatment = SemanticTreatment(design).fit(train, team, qb)
    x, counts = treatment.transform(train)
    model = SemanticScoreModel(treatment, family, params)
    if family == "DYNAMIC":
        h, a, _ = model.predict(train)
        model.dynamic_offset = (float((train.home_points - h).mean()), float((train.away_points - a).mean()))
        receipt(log, {"event": "DYNAMIC_PARAMETER_FIT", "tag": tag, "trainingRows": len(train)})
    else:
        def estimator():
            if family == "HGB":
                return HistGradientBoostingRegressor(**params, random_state=SEED, early_stopping=False)
            from xgboost import XGBRegressor
            return XGBRegressor(**params, objective="reg:squarederror", tree_method="hist", n_jobs=2, random_state=SEED, verbosity=0)
        model.home, model.away = estimator(), estimator()
        for target, instance in (("home_points", model.home), ("away_points", model.away)):
            receipt(log, {"event": "ESTIMATOR_FIT_START", "tag": tag, "target": target, "trainingRows": len(train)})
            instance.fit(x, train[target].to_numpy(float))
            receipt(log, {"event": "ESTIMATOR_FIT_COMPLETE", "tag": tag, "target": target})
    return model, counts


def fit_predict(design, family, params, train, validation, team, qb, log, tag):
    residual_season = int(train.season.max())
    rtrain, rval = train[train.season < residual_season], train[train.season == residual_season]
    residual_model, _ = fit_model(design, family, params, rtrain, team, qb, log, tag + ":residual")
    ph, pa, _ = residual_model.predict(rval)
    residual = PairedResidualAuthority.fit(actual_home=rval.home_points.to_numpy(float), actual_away=rval.away_points.to_numpy(float),
        predicted_home=ph, predicted_away=pa, row_ids=rval.canonical_game_id.astype(str).tolist(), row_dates=rval.game_date.tolist(), training_end=rval.game_date.max())
    model, counts = fit_model(design, family, params, train, team, qb, log, tag + ":main")
    artifact = SemanticForecastArtifact(model, residual, None, tag, {"trainingEnd": str(train.game_date.max().date()), "sourceCutoff": "STRICT_PRIOR_DATE"})
    run_seed = SEED + 20000 + int(validation.season.min())
    result = artifact.predict(validation, seed=run_seed)
    probability = result["rawProbability"]
    simulation = result["simulation"]
    scores = result["scoreMeans"]
    ledger = pd.DataFrame({"canonical_game_id": validation.canonical_game_id.to_numpy(), "season": validation.season.to_numpy(),
        "week": validation.week.astype(str).to_numpy(), "game_date": validation.game_date.dt.strftime("%Y-%m-%d").to_numpy(),
        "actual_home_points": validation.home_points.to_numpy(float), "actual_away_points": validation.away_points.to_numpy(float),
        "outcome_class": _outcome_class(validation), "predicted_home_points": scores[:, 0], "predicted_away_points": scores[:, 1],
        "raw_away_probability": probability[:, 0], "raw_tie_probability": probability[:, 1], "raw_home_probability": probability[:, 2],
        "home_prior_season_games": validation.home_prior_season_games.to_numpy(), "away_prior_season_games": validation.away_prior_season_games.to_numpy()})
    for name, draws_array in (("home", simulation.home), ("away", simulation.away), ("margin", simulation.home - simulation.away), ("total", simulation.home + simulation.away)):
        ledger[f"{name}_q05"], ledger[f"{name}_q95"] = np.quantile(draws_array, [.05, .95], axis=1)
    for side in ("home", "away"):
        ledger[f"{side}_lagged_low_exposure"] = [int(not (mix := json.loads(value)) or sum(v["n"] * v["weight"] for v in mix) / sum(v["weight"] for v in mix) < 100) for value in validation[f"{side}__lagged_passer_mixture"]]
    return ledger, artifact, {"trainingBranchCounts": counts, "validationBranchCounts": result["branchCounts"], "residualRows": residual.row_count,
                             "residualSha256": residual.sha256, "commonSeed": run_seed, "expandedColumns": len(model.treatment.names)}


def metric_report(ledger):
    report = {"raw": _metrics(ledger), "calibrated": _metrics(ledger, probability_prefix="calibrated")}
    actual = {"home": ledger.actual_home_points, "away": ledger.actual_away_points,
              "margin": ledger.actual_home_points - ledger.actual_away_points, "total": ledger.actual_home_points + ledger.actual_away_points}
    report["rawDistribution90IntervalCoverage"] = {key: float(((value >= ledger[f"{key}_q05"]) & (value <= ledger[f"{key}_q95"])).mean()) for key, value in actual.items() if f"{key}_q05" in ledger}
    return report


def subgroup_report(ledger):
    masks = {"FULL_SEASON": np.ones(len(ledger), bool), "WEEKS_1_4": ledger.week.astype(int).le(4), "WEEKS_1_2": ledger.week.astype(int).le(2),
             "ZERO_CURRENT_SEASON_GAMES": ledger.home_prior_season_games.eq(0) | ledger.away_prior_season_games.eq(0),
             "LOW_CURRENT_SEASON_EXPOSURE_LT4": ledger.home_prior_season_games.lt(4) | ledger.away_prior_season_games.lt(4)}
    if "home_lagged_low_exposure" in ledger:
        masks["LAGGED_PASSER_LOW_EXPOSURE_PROXY_NOT_ACTUAL_ROOKIE"] = ledger.home_lagged_low_exposure.eq(1) | ledger.away_lagged_low_exposure.eq(1)
    return {key: metric_report(ledger.loc[mask]) if np.asarray(mask).any() else {"games": 0, "status": "INSUFFICIENT_COHORT"} for key, mask in masks.items()}


def run_lab(output: Path = OUTPUT):
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=True)
    matrix_sha = immutable_json(output / "candidate-matrix.json", MATRIX)
    code_sha = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("semantic_features.py").read_bytes()).hexdigest()
    authority, games, team, qb, refs = load_sources()
    identity = hashlib.sha256(canonical_json_bytes({"matrix": matrix_sha, "code": code_sha, "foundation": authority.foundation_manifest_sha256})).hexdigest()
    run = output / "runs" / identity
    run.mkdir(parents=True, exist_ok=True)
    completed = run / "result.json"
    if completed.exists():
        result = json.loads(completed.read_text())
        for item in result["inventory"]:
            path = run / item["path"]
            if digest(path) != item["sha256"] or path.stat().st_size != item["byteCount"]:
                raise ValueError(f"SAVED_RUN_CHECKSUM_MISMATCH:{path}")
        return result
    declaration = {"runIdentity": identity, "matrixSha256": matrix_sha, "implementationSha256": code_sha,
                   "foundationSha256": authority.foundation_manifest_sha256, "sourceObjects": refs,
                   "developmentRows": len(games), "physicalFilter": "season<2025", "researchOnly": True}
    immutable_json(run / "declaration.json", declaration)
    history_path = run / "pregame_feature_states.parquet"
    if history_path.exists():
        history = pd.read_parquet(history_path)
    else:
        history = make_history_features(games, team, qb)
        history.to_parquet(history_path, index=False)
    policy = feature_policy(games, history, authority, refs)
    immutable_json(run / "feature-treatment-policy.json", policy)
    # This discoverable input specification is complete before any fit. It is
    # separate from CURRENT, which is published only after all result artifacts.
    if not (output / "feature-treatment-policy.json").exists():
        immutable_json(output / "feature-treatment-policy.json", policy)
    immutable_json(output / f"feature-treatment-policy-{identity[:12]}.json", policy)
    print(json.dumps({"event": "SEMANTIC_INPUTS_READY", "run": str(run), "games": len(history), "registered": 197, "added": 12}), flush=True)
    log = run / "fit-accounting.jsonl"
    results, ledgers = [], {}
    specifications = [(f"{family}_{design}", design, family, params) for design in ("C1", "C2", "C3") for family, params in (("XGBOOST", XGB), ("HGB", HGB))]
    specifications.append(("DYNAMIC_TEAM_SCORE_BLEND", "C1", "DYNAMIC", {}))
    with threadpool_limits(limits=2):
        for pipeline_id, design, family, params in specifications:
            folder = run / pipeline_id
            folder.mkdir(exist_ok=True)
            folds = []
            for season in MATRIX["validationSeasons"]:
                fold_path = folder / f"fold-{season}.parquet"
                details_path = folder / f"fold-{season}.json"
                if fold_path.exists() and details_path.exists():
                    details = json.loads(details_path.read_text())
                    if digest(fold_path) != details["predictionSha256"]:
                        raise ValueError("FOLD_CHECKSUM_MISMATCH")
                    ledger = pd.read_parquet(fold_path)
                else:
                    train, val = history[history.season < season], history[history.season == season]
                    fold_start = time.perf_counter()
                    ledger, artifact, details = fit_predict(design, family, params, train, val, team, qb, log, f"{pipeline_id}:{season}")
                    joblib.dump(artifact, folder / f"fold-{season}.joblib", compress=3)
                    ledger.to_parquet(fold_path, index=False)
                    details.update({"pipelineId": pipeline_id, "season": season, "trainRows": len(train), "validationRows": len(val),
                                    "predictionSha256": digest(fold_path), "artifactSha256": digest(folder / f"fold-{season}.joblib"), "elapsedSeconds": time.perf_counter() - fold_start})
                    immutable_json(details_path, details)
                    receipt(log, {"event": "OUTER_FOLD_COMPLETE", "pipeline": pipeline_id, "season": season})
                    print(json.dumps({"event": "FOLD_COMPLETE", "pipeline": pipeline_id, "season": season, "raw": _metrics(ledger), "seconds": details["elapsedSeconds"]}), flush=True)
                folds.append(ledger)
            combined, calibration = _chronological_calibration(pd.concat(folds, ignore_index=True))
            ledgers[pipeline_id] = combined
            combined.to_parquet(folder / "oof_predictions.parquet", index=False)
            item = {"pipelineId": pipeline_id, "design": design, "family": family, "parameters": params, "status": "COMPLETED",
                    "metrics": metric_report(combined), "subgroups": subgroup_report(combined), "calibration": calibration,
                    "oofPath": str(folder / "oof_predictions.parquet"), "foldCount": 5}
            immutable_json(folder / "result.json", item)
            results.append(item)
        # Saved legacy baselines keep their true historical simulations/seeds;
        # candidates have common draws amongst themselves, not falsely with old.
        for baseline in ("M1_RECIPE_FOLD_REFIT", "HIST_GRADIENT_BOOSTING_B_T2"):
            path = BASELINE_ROOT / "pipelines" / baseline.lower() / "oof_predictions.parquet"
            saved = pd.read_parquet(path)
            expected = history.loc[history.season.between(2020, 2024)]
            if set(saved.canonical_game_id) != set(expected.canonical_game_id):
                raise ValueError("BASELINE_COHORT_MISMATCH")
            truth = saved.merge(expected[["canonical_game_id", "home_points", "away_points", "home_prior_season_games", "away_prior_season_games"]], on="canonical_game_id", validate="one_to_one")
            if not np.array_equal(truth.actual_home_points, truth.home_points) or not np.array_equal(truth.actual_away_points, truth.away_points):
                raise ValueError("BASELINE_TRUTH_MISMATCH")
            truth, calibration = _chronological_calibration(truth)
            ledgers[baseline] = truth
            results.append({"pipelineId": baseline, "design": "LEGACY_MEDIAN_BASELINE", "family": "XGBOOST" if baseline.startswith("M1") else "HGB", "status": "REUSED_SAVED_OOF",
                            "metrics": metric_report(truth), "subgroups": subgroup_report(truth), "calibration": calibration, "oofPath": str(path), "sourceSha256": digest(path), "sameSimulationDrawsAsNewCandidates": False})
        finalists = sorted([item for item in results if item["pipelineId"] in {s[0] for s in specifications if s[2] != "DYNAMIC"}], key=lambda r: r["metrics"]["raw"]["multiclassLogLoss"])[:2]
        for base in finalists:
            pipeline_id = base["pipelineId"] + "_TUNED"
            folder = run / pipeline_id
            folder.mkdir(exist_ok=True)
            grids = MATRIX["tuning"][base["family"]]
            folds = []
            for season in MATRIX["validationSeasons"]:
                fold_path, details_path = folder / f"fold-{season}.parquet", folder / f"fold-{season}.json"
                if fold_path.exists() and details_path.exists():
                    details = json.loads(details_path.read_text())
                    if digest(fold_path) != details["predictionSha256"]:
                        raise ValueError("TUNED_FOLD_CHECKSUM_MISMATCH")
                    ledger = pd.read_parquet(fold_path)
                else:
                    train, val = history[history.season < season], history[history.season == season]
                    inner_season = season - 1
                    inner_train, inner_val = train[train.season < inner_season], train[train.season == inner_season]
                    evaluations = []
                    for j, params in enumerate(grids):
                        inner, _, _ = fit_predict(base["design"], base["family"], params, inner_train, inner_val, team, qb, log, f"{pipeline_id}:{season}:inner{j}")
                        evaluations.append(_metrics(inner)["multiclassLogLoss"])
                    chosen = int(np.argmin(evaluations))
                    ledger, artifact, details = fit_predict(base["design"], base["family"], grids[chosen], train, val, team, qb, log, f"{pipeline_id}:{season}:selected")
                    joblib.dump(artifact, folder / f"fold-{season}.joblib", compress=3)
                    ledger.to_parquet(fold_path, index=False)
                    details.update({"season": season, "chosenConfiguration": chosen, "innerLogLosses": evaluations, "innerValidationSeason": inner_season,
                                    "predictionSha256": digest(fold_path), "artifactSha256": digest(folder / f"fold-{season}.joblib")})
                    immutable_json(details_path, details)
                    receipt(log, {"event": "OUTER_FOLD_COMPLETE", "pipeline": pipeline_id, "season": season})
                    print(json.dumps({"event": "TUNED_FOLD_COMPLETE", "pipeline": pipeline_id, "season": season, "chosen": chosen}), flush=True)
                folds.append(ledger)
            combined, calibration = _chronological_calibration(pd.concat(folds, ignore_index=True))
            combined.to_parquet(folder / "oof_predictions.parquet", index=False)
            ledgers[pipeline_id] = combined
            item = {"pipelineId": pipeline_id, "design": base["design"], "family": base["family"], "status": "COMPLETED_BOUNDED_TUNING",
                    "metrics": metric_report(combined), "subgroups": subgroup_report(combined), "calibration": calibration,
                    "oofPath": str(folder / "oof_predictions.parquet"), "configurations": len(grids), "foldCount": 5}
            immutable_json(folder / "result.json", item)
            results.append(item)
        fitted_artifacts = []
        for base in finalists:
            # Save the fixed screen recipe so its exact five-fold validation
            # design is clear. Tuning results remain a separate research study.
            final_dir = run / "fitted" / base["pipelineId"]
            final_dir.mkdir(parents=True, exist_ok=True)
            final_path = final_dir / "forecast-system.joblib"
            if final_path.exists():
                artifact = joblib.load(final_path)
            else:
                _, artifact, _ = fit_predict(base["design"], base["family"], base["parameters"], history, history.tail(16), team, qb, log, base["pipelineId"] + ":final_development")
                ledger = ledgers[base["pipelineId"]]
                calibrator = LogisticRegression(C=1., max_iter=2000, random_state=SEED)
                receipt(log, {"event": "CALIBRATOR_FIT_START", "pipeline": base["pipelineId"], "rows": len(ledger)})
                calibrator.fit(np.log(ledger[["raw_away_probability", "raw_tie_probability", "raw_home_probability"]].to_numpy(float)), ledger.outcome_class)
                artifact.calibrator = calibrator
                artifact.authority.update(declaration)
                artifact.authority.update({"trainingSeasons": [1999, 2024], "status": "RESEARCH_SHADOW", "promotion": "NOT_PROMOTED", "wageringAuthority": False, "executionAllowedInAISP": False,
                                           "currentPublicationLimitation": "No protected2025 initialization authority for new semantic candidates; do not relabel2024 histories as current2026"})
                artifact.pipeline_id = base["pipelineId"]
                joblib.dump(artifact, final_path, compress=3)
            probe = history.tail(16)
            before = artifact.predict(probe)
            reloaded = joblib.load(final_path)
            after = reloaded.predict(probe)
            for key in ("scoreMeans", "rawProbability", "separateCalibratedProbability"):
                if not np.array_equal(before[key], after[key]):
                    raise ValueError("FROZEN_RELOAD_MISMATCH:" + key)
            if not np.array_equal(before["simulation"].home, after["simulation"].home) or not np.array_equal(before["simulation"].away, after["simulation"].away):
                raise ValueError("FROZEN_DRAW_RELOAD_MISMATCH")
            immutable_json(final_dir / "treatment-state.json", artifact.model.treatment.state())
            fitted_artifacts.append({"pipelineId": base["pipelineId"], "path": str(final_path), "sha256": digest(final_path), "reloadProbeRows": 16,
                                     "reloadMismatch": 0, "includes": ["semanticPreprocessing", "scoreEstimators", "pairedResidualAuthority", "separateCalibrator"], "expandedColumns": len(artifact.model.treatment.names)})
    reference = ledgers["M1_RECIPE_FOLD_REFIT"]
    paired = {}
    for name, ledger in ledgers.items():
        if name == "M1_RECIPE_FOLD_REFIT":
            continue
        paired[name] = {prefix: _paired_block_uncertainty(ledger, reference, resamples=1000, seed=SEED, candidate_prefix=prefix, reference_prefix=prefix) for prefix in ("raw", "calibrated")}
        paired[name]["weeks1to4"] = _paired_block_uncertainty(ledger.loc[ledger.week.astype(int).le(4)], reference.loc[reference.week.astype(int).le(4)], resamples=1000, seed=SEED)
    effects = {}
    for family in ("XGBOOST", "HGB"):
        for lhs, rhs, label in (("C2", "C1", "laggedPassingPersonnel"), ("C3", "C2", "peerPooling")):
            effects[f"{family}_{label}"] = _paired_block_uncertainty(ledgers[f"{family}_{lhs}"], ledgers[f"{family}_{rhs}"], resamples=1000, seed=SEED)
    events = [json.loads(line) for line in log.read_text().splitlines()]
    accounting = {name: sum(e["event"] == name for e in events) for name in ("ESTIMATOR_FIT_START", "ESTIMATOR_FIT_COMPLETE", "OUTER_FOLD_COMPLETE", "DYNAMIC_PARAMETER_FIT", "CALIBRATOR_FIT_START")}
    inventory = [{"path": str(path.relative_to(run)), "sha256": digest(path), "byteCount": path.stat().st_size} for path in sorted(run.rglob("*")) if path.is_file()]
    result = {"contract": "NFL_SEMANTIC_LAB_RESULT_V1", "runIdentity": identity, "status": "COMPLETED_RESEARCH_ONLY", "modelRetained": "NFL_M1_XGBOOST",
              "createdAt": datetime.now(timezone.utc).isoformat(), "elapsedSeconds": time.perf_counter() - started,
              "developmentRows": len(history), "validationRows": len(reference), "registeredFeatures": 197, "implementedRegisteredFeatures": 196, "excludedRegisteredFeatures": ["roof"],
              "additionalLaggedPersonnelFeatures": 12, "sourceFeaturePolicyPath": str(run / "feature-treatment-policy.json"),
              "results": results, "pairedAgainstM1": paired, "incrementalEffects": effects, "fittedArtifacts": fitted_artifacts,
              "actualFitAccounting": accounting, "matrixSha256": matrix_sha, "implementationSha256": code_sha, "inventory": inventory,
              "limitations": ["Development selection is exploratory, not independent proof", "QB designs use prior-game passing-personnel mixtures, not known starters",
              "No identified actual rookie/backup/changed-starter performance claim", "game-average rate normal approximation, not binomial exposure model",
              "Legacy baseline simulation random streams differ; new candidates use common draws", "Calibration probabilities remain separately labeled, not adjusted score distributions",
              "New current candidate forecasts require permitted2025 operational history authority; no sealed rows read"],
              "researchOnly": True, "wageringAuthority": False, "executionAllowedInAISP": False, "finalOotRead": False}
    result_sha = immutable_json(completed, result)
    # Only the discovery pointer is mutable, and only after immutable artifacts
    # and their inventory have all completed.
    (output / "CURRENT.json").write_bytes(canonical_json_bytes({"contract": "NFL_SEMANTIC_LAB_CURRENT_V1", "status": "COMPLETED", "resultPath": str(completed), "resultSha256": result_sha, "runIdentity": identity}))
    print(json.dumps({"event": "COMPLETE", "resultPath": str(completed), "resultSha256": result_sha, "accounting": accounting}), flush=True)
    return result
