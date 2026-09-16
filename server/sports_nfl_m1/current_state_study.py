"""Bounded reconstructed NFL study; no provider, OOT or AISP execution path."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar

from .labs_simulation import immutable_json, file_record
from .overnight_lab import _metrics, _loss_vector
from .research_benchmarks import block_interval

EVIDENCE = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1"
SEED = 739031
COMPONENTS = ("DYNAMIC", "HIERARCHICAL", "RESIDUAL", "ENSEMBLE")
CALIBRATION_DIAGNOSTIC_COUNTS = Counter()
AUTHORITY = dict(status="RESEARCH_SHADOW", promotionStatus="NOT_PROMOTED",
                 wageringAuthority=False, executionAllowedInAISP=False)


def now():
    return datetime.now(timezone.utc).isoformat()


def publish_json(folder: Path, name: str, value: dict):
    from server.audit_assurance.canonical import canonical_json_bytes
    payload = canonical_json_bytes(value)
    sha = hashlib.sha256(payload).hexdigest()
    return immutable_json(folder / "sha256" / sha / name, value)


def log_event(path, event):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"recordedAtUtc": now(), "evidenceClass": EVIDENCE, **event}, default=str) + "\n")
    print(json.dumps(event, default=str), flush=True)


def crps(draws, truth):
    draws = np.sort(np.asarray(draws, float), axis=1)
    count = draws.shape[1]
    return np.mean(np.abs(draws - np.asarray(truth)[:, None]), axis=1) - np.sum(
        draws * (2 * np.arange(1, count + 1) - count - 1), axis=1) / count ** 2


def ledger(events, predicted, component, lag, fold):
    home, away = predicted["home_draws"], predicted["away_draws"]
    probability = np.column_stack(((home < away).mean(1), (home == away).mean(1), (home > away).mean(1)))
    result = events[["canonical_game_id", "season", "week", "game_date"]].copy().reset_index(drop=True)
    result["evidenceClass"], result["component"], result["lagHours"], result["fold"] = EVIDENCE, component, lag, fold
    result["actual_home_points"] = events.home_points.to_numpy(float)
    result["actual_away_points"] = events.away_points.to_numpy(float)
    result["outcome_class"] = np.where(result.actual_home_points > result.actual_away_points, 2,
                                      np.where(result.actual_home_points < result.actual_away_points, 0, 1))
    # Score metrics use the same empirical distribution as published probabilities.
    result["predicted_home_points"], result["predicted_away_points"] = home.mean(1), away.mean(1)
    for index, side in enumerate(("away", "tie", "home")):
        result[f"raw_{side}_probability"] = probability[:, index]
    actual_h, actual_a = result.actual_home_points.to_numpy(), result.actual_away_points.to_numpy()
    for name, samples, truth in (("home", home, actual_h), ("away", away, actual_a),
                                 ("margin", home-away, actual_h-actual_a), ("total", home+away, actual_h+actual_a)):
        result[f"{name}_q05"], result[f"{name}_q95"] = np.quantile(samples, [.05, .95], axis=1)
        result[f"{name}_crps"] = crps(samples, truth)
        result[f"{name}_pit_mid"] = ((samples < truth[:, None]).mean(1) + (samples <= truth[:, None]).mean(1)) / 2
        result[f"{name}_sd"] = samples.std(1)
    for number in (-14, -10, -7, -3, 0, 3, 7, 10, 14):
        result[f"margin_mass_{number}"] = ((home-away) == number).mean(1)
    result["genericFallbackCount"] = 0
    return result


def calibration(frame):
    output = {}
    for index, label in enumerate(("away", "tie", "home")):
        p = frame[f"raw_{label}_probability"].to_numpy(float)
        y = frame.outcome_class.eq(index).to_numpy(float)
        clipped = np.clip(p, 1e-6, 1-1e-6)
        x = np.log(clipped / (1-clipped))
        bands = []
        # Integer assignment puts every probability, including exact decimals
        # and p=1, in exactly one diagnostic band.
        bins = np.minimum(np.floor(p * 10).astype(int), 9)
        for index_bin in range(10):
            lower = index_bin / 10
            mask = bins == index_bin
            if mask.any():
                bands.append({"lower": float(lower), "count": int(mask.sum()), "predicted": float(p[mask].mean()),
                              "observed": float(y[mask].mean()), "evidenceClass": EVIDENCE})
        record = {"evidenceClass": EVIDENCE, "positiveGames": int(y.sum()), "meanPredicted": float(p.mean()),
                  "observedRate": float(y.mean()), "reliability": bands, "use": "DIAGNOSTIC_ONLY_NOT_APPLIED_TO_FORECAST"}
        if min(y.sum(), len(y)-y.sum()) < 2 or x.std() < 1e-9:
            CALIBRATION_DIAGNOSTIC_COUNTS["insufficientClassSupport"] += 1
            record.update(status="INSUFFICIENT_CLASS_SUPPORT", intercept=None, slope=None)
        else:
            def objective(ab):
                z = ab[0] + ab[1]*x
                return np.mean(np.logaddexp(0, z) - y*z)
            CALIBRATION_DIAGNOSTIC_COUNTS["optimizerStarts"] += 1
            fitted = minimize(objective, [0., 1.], method="L-BFGS-B", bounds=[(-20,20),(-20,20)])
            CALIBRATION_DIAGNOSTIC_COUNTS["optimizerSuccesses" if fitted.success else "optimizerFailures"] += 1
            record.update(status="DESCRIPTIVE_DIAGNOSTIC" if fitted.success else "DIAGNOSTIC_OPTIMIZER_FAILED",
                          intercept=float(fitted.x[0]), slope=float(fitted.x[1]), boundedDiagnostic=True)
        output[label] = record
    return output


def metric_report(frame):
    if not len(frame):
        return {"evidenceClass": EVIDENCE, "games": 0, "status": "EMPTY_COHORT"}
    result = {**_metrics(frame), "evidenceClass": EVIDENCE, "calibration": calibration(frame)}
    result["distribution"] = {}
    for name, truth in (("home", frame.actual_home_points), ("away", frame.actual_away_points),
                        ("margin", frame.actual_home_points-frame.actual_away_points),
                        ("total", frame.actual_home_points+frame.actual_away_points)):
        if f"{name}_q05" in frame:
            result["distribution"][name] = {"evidenceClass": EVIDENCE,
                "coverage90": float(((truth >= frame[f"{name}_q05"]) & (truth <= frame[f"{name}_q95"])).mean()),
                "sharpness90": float((frame[f"{name}_q95"]-frame[f"{name}_q05"]).mean()),
                "crps": float(frame[f"{name}_crps"].mean()) if f"{name}_crps" in frame else None,
                "meanSd": float(frame[f"{name}_sd"].mean()) if f"{name}_sd" in frame else None}
    result["keyNumbers"] = {str(k): {"evidenceClass": EVIDENCE, "predictedMass": float(frame[f"margin_mass_{k}"].mean()),
        "observedMass": float((frame.actual_home_points-frame.actual_away_points).eq(k).mean())}
        for k in (-14,-10,-7,-3,0,3,7,10,14) if f"margin_mass_{k}" in frame}
    blocks = frame.season.astype(str) + ":" + frame.week.astype(str)
    result["independentSeasonWeekBlocks"] = int(blocks.nunique())
    result["inferenceStatus"] = "DESCRIPTIVE_FEW_BLOCKS" if blocks.nunique() < 8 else "EXPLORATORY_RECONSTRUCTED_DEVELOPMENT"
    return result


def subgroup_masks(frame):
    week = frame.week.astype(int)
    masks = {"WEEK_1": week.eq(1), "WEEKS_1_4": week.between(1,4), "WEEKS_5_8": week.between(5,8), "FULL_SEASON": np.ones(len(frame), bool)}
    for field, label in (("no_current_history", "NO_CURRENT_SEASON_HISTORY"), ("low_qb_exposure", "LAGGED_LOW_QB_EXPOSURE_PROXY")):
        if field in frame:
            masks[label] = frame[field].astype(bool)
    return masks


def ensemble_weight(hier, residual):
    if len(hier) != len(residual) or hier.canonical_game_id.tolist() != residual.canonical_game_id.tolist():
        raise ValueError("ensemble component event order differs")
    if hier.season.nunique() < 2:
        return 0., {"status": "HIERARCHICAL_WARMUP_FEWER_THAN_TWO_EARLIER_OOF_SEASONS", "rows": len(hier)}
    cols = [f"raw_{s}_probability" for s in ("away", "tie", "home")]
    h, r = hier[cols].to_numpy(), residual[cols].to_numpy()
    actual = hier[["actual_home_points", "actual_away_points"]].to_numpy()
    hs = hier[["predicted_home_points", "predicted_away_points"]].to_numpy()-actual
    rs = residual[["predicted_home_points", "predicted_away_points"]].to_numpy()-actual
    corr = float(np.corrcoef(hs.ravel(), rs.ravel())[0,1])
    variation = float((h-r).std())
    if not np.isfinite(corr) or corr >= .999 or variation <= 1e-6:
        return 0., {"status": "HIERARCHICAL_COMPONENT_DIVERSITY_INSUFFICIENT", "correlation": corr, "probabilityDeltaStd": variation}
    truth = hier.outcome_class.to_numpy(int)
    obj = lambda weight: float(_loss_vector((1-weight)*h+weight*r, truth).mean())
    opt = minimize_scalar(obj, bounds=(0.,1.), method="bounded", options={"xatol":1e-6})
    if not opt.success:
        raise ValueError("ensemble weight optimizer failed")
    choices = [(obj(w),w) for w in (0.,float(opt.x),1.)]
    weight = min(choices)[1]
    return weight, {"status": "EARLIER_OOF_ONLY_WEIGHT_FITTED", "residualWeight": weight, "rows": len(hier),
                    "maximumTrainingSeason": int(hier.season.max()), "correlation": corr, "probabilityDeltaStd": variation,
                    "evidenceClass": EVIDENCE}


def mixture(hier, residual, weight, seed):
    if not 0 <= weight <= 1:
        raise ValueError("invalid joint mixture weight")
    choose = np.random.default_rng(seed).random(hier["home_draws"].shape) < weight
    # One component choice for BOTH scores preserves the joint measure.
    home = np.where(choose, residual["home_draws"], hier["home_draws"])
    away = np.where(choose, residual["away_draws"], hier["away_draws"])
    return {"home_draws": home, "away_draws": away, "mean": np.column_stack((home.mean(1),away.mean(1))),
            "coverage": hier.get("coverage", {})}


def compare(candidate, reference):
    matched = candidate.merge(reference, on="canonical_game_id", suffixes=("", "_ref"), validate="one_to_one")
    if not len(matched):
        return {"status": "NO_MATCHING_GAMES", "evidenceClass": EVIDENCE}
    cols = [f"raw_{s}_probability" for s in ("away", "tie", "home")]
    losses = _loss_vector(matched[cols].to_numpy(), matched.outcome_class.to_numpy())
    reference_losses = _loss_vector(matched[[c+"_ref" for c in cols]].to_numpy(), matched.outcome_class.to_numpy())
    if (not np.array_equal(matched.outcome_class, matched.outcome_class_ref)
            or any(not np.array_equal(matched[f"actual_{side}_points"], matched[f"actual_{side}_points_ref"])
                   for side in ("home", "away"))):
        raise ValueError("comparison outcome mismatch")
    report = {}
    for name, mask in subgroup_masks(matched).items():
        if not np.asarray(mask).any():
            report[name] = {"evidenceClass":EVIDENCE,"status":"EMPTY_COHORT","events":0}
            continue
        interval = block_interval(losses[np.asarray(mask)]-reference_losses[np.asarray(mask)], matched.loc[mask], seed=SEED)
        interval.update(evidenceClass=EVIDENCE, status="DESCRIPTIVE_FEW_BLOCKS" if interval["seasonWeekBlocks"] < 8 else "EXPLORATORY_ONLY")
        report[name] = interval
    return report


def legacy_ledgers():
    base = Path(r"C:\Users\james\asp-data-staging\nfl\overnight-model-laboratory-v1\runs\matrix-fcc3cd9a5446-foundation-ebb6912919a5\pipelines")
    semantic = ROOT / "outputs/nfl-semantic-lab-v1/runs/7a651ec80b3b77106b018dd6739f55e26e45cbcf5e1f8811d6557f039d372f69"
    paths = {"M1_RECIPE_FOLD_REFIT": base / "m1_recipe_fold_refit/oof_predictions.parquet",
             "HGB_T2": base / "hist_gradient_boosting_b_t2/oof_predictions.parquet",
             "C2": semantic / "XGBOOST_C2/oof_predictions.parquet", "C3": semantic / "XGBOOST_C3/oof_predictions.parquet"}
    result, refs = {}, []
    for label, path in paths.items():
        frame = pd.read_parquet(path, filters=[("season", ">=", 2020), ("season", "<=", 2024)])
        if not frame.season.between(2020,2024).all():
            raise ValueError("legacy OOF is not the predeclared Development cohort")
        calibration_path = base.parent / "analysis/calibration" / path.parent.name / "oof_predictions.parquet"
        if label in ("M1_RECIPE_FOLD_REFIT", "HGB_T2") and calibration_path.is_file():
            saved = pd.read_parquet(calibration_path, filters=[("season", ">=", 2020), ("season", "<=", 2024)])
            saved = saved.set_index("canonical_game_id").reindex(frame.canonical_game_id)
            if (saved.outcome_class.to_numpy() != frame.outcome_class.to_numpy()).any():
                raise ValueError("saved calibration cohort differs")
            for side in ("away", "tie", "home"):
                column = f"calibrated_{side}_probability"
                frame[column] = saved[column].to_numpy()
            refs.append({"modelId":label,"purpose":"SAVED_CHRONOLOGICAL_CALIBRATION_NO_NEW_FIT",
                         **file_record(calibration_path),"evidenceClass":EVIDENCE})
        frame["evidenceClass"] = EVIDENCE
        frame["availabilityMethod"] = "LEGACY_PRIOR_DATE_NOT_48_OR_72_HOUR_RETRAINED"
        result[label] = frame
        refs.append({"modelId": label, **file_record(path), "evidenceClass": EVIDENCE,
                     "availabilityMethod": "LEGACY_PRIOR_DATE_NOT_48_OR_72_HOUR_RETRAINED"})
    return result, refs


def normalize_prediction(pred):
    return {**pred, "home_draws": pred.get("home_draws", pred.get("homeDraws")),
            "away_draws": pred.get("away_draws", pred.get("awayDraws")),
            "mean": pred.get("mean", pred.get("scoreMeans"))}


def lag_sensitivity(candidate, reference):
    matched = candidate.merge(reference, on="canonical_game_id", suffixes=("", "_ref"), validate="one_to_one")
    columns = [f"raw_{side}_probability" for side in ("away", "tie", "home")]
    delta = matched[columns].to_numpy() - matched[[c+"_ref" for c in columns]].to_numpy()
    output = {"evidenceClass":EVIDENCE,"matchedGames":len(matched),
              "probabilityChangedGames":int(np.any(delta != 0, axis=1).sum()),
              "meanAbsoluteClassProbabilityChange":float(np.abs(delta).mean()),
              "maximumAbsoluteClassProbabilityChange":float(np.abs(delta).max()),
              "lossComparisons":compare(candidate,reference),
              "lateCorrectionBiasEstimated":False}
    if "eligible_history_max_available_at" in matched:
        output["latestEligibleHistoryTimestampChangedGames"] = int((matched.eligible_history_max_available_at != matched.eligible_history_max_available_at_ref).sum())
    return output


def legacy_calibrated(frame):
    result = frame.copy()
    for side in ("away", "tie", "home"):
        column = f"calibrated_{side}_probability"
        if column not in frame:
            return None
        result[f"raw_{side}_probability"] = frame[column]
    return result


def run_study(output: Path = OUTPUT):
    from .current_state_features import load_reconstructed_sources, treatment_inventory
    from .current_state_model import fit_current_state_system
    from server.audit_assurance.canonical import canonical_json_bytes
    output = Path(output).resolve()
    protocol_ref = file_record(output / "methodology-contract.json")
    warmup_ref = file_record(output / "warmup-clarification.json")
    implementation_ref = file_record(output / "pre-fit-implementation-clarifications.json")
    print("LOADING_PHYSICALLY_SEPARATED_DEVELOPMENT_ONLY", flush=True)
    games, team, qb, source = load_reconstructed_sources(Path(r"C:\Users\james\asp-data-staging\nfl\bronze-v1"), cache_root=output / "cache")
    games = games.sort_values(["season", "game_date", "canonical_game_id"]).reset_index(drop=True)
    if not games.season.between(1999,2024).all() or games.canonical_game_id.duplicated().any():
        raise ValueError("invalid Development partition/identity")
    code = [file_record(Path(__file__)), file_record(Path(__file__).with_name("current_state_features.py")),
            file_record(Path(__file__).with_name("current_state_model.py"))]
    run_id = hashlib.sha256(canonical_json_bytes({"protocol":protocol_ref, "warmup":warmup_ref,
                           "implementationClarifications":implementation_ref,"source":source, "code":code})).hexdigest()
    run = output / "runs" / run_id
    run.mkdir(parents=True, exist_ok=True)
    completed = run / "result.json"
    if completed.exists():
        result = json.loads(completed.read_text())
        for ref in result["artifacts"]:
            if file_record(Path(ref["path"])) != {k:ref[k] for k in ("path","sha256","byteCount")}:
                raise ValueError("completed study artifact changed")
        print("REUSED_COMPLETED_STUDY_NO_FITS", flush=True)
        return result
    receipt_path = run / "fit-receipts.jsonl"
    if receipt_path.exists():
        raise ValueError(f"PARTIAL_ATTEMPT_REQUIRES_EXPLICIT_RECOVERY_DISPOSITION:{run}")
    legacy, legacy_refs = legacy_ledgers()
    declaration = {"contract":"NFL_CURRENT_STATE_STUDY_DECLARATION_V2", "declaredAtUtc":now(), "runId":run_id,
                   "evidenceClass":EVIDENCE, "methodology":protocol_ref, "sourceEvidence":source, "generatingCode":code,
                   "developmentGames":len(games), "sourceOnlyWarmupGames":int(games.season.eq(1999).sum()),
                   "modelTrainingStartSeason":2000,"warmupClarification":warmup_ref,
                   "implementationClarifications":implementation_ref,
                   "validationGames":int(games.season.ge(2020).sum()),
                   "validationSeasonCounts":{str(k):int(v) for k,v in games.loc[games.season.ge(2020)].groupby("season").size().items()},
                   "legacyComparators":legacy_refs, "sealedOotAccessed":False, **AUTHORITY}
    immutable_json(run / "declaration.json", declaration)
    cohort = games.copy()
    cohort["modelTrainingEligible"] = cohort.season.ge(2000)
    cohort["validationEligible"] = cohort.season.ge(2020)
    cohort["role"] = np.where(cohort.season.eq(1999), "SOURCE_ONLY_WARMUP", "DEVELOPMENT")
    cohort.to_parquet(run / "development-cohort.parquet", index=False)
    team.to_parquet(run / "sufficient-statistics-team.parquet", index=False)
    qb.to_parquet(run / "sufficient-statistics-qb.parquet", index=False)
    inventory = treatment_inventory()
    immutable_json(run / "treatment-inventory.json", inventory if isinstance(inventory,dict) else {"evidenceClass":EVIDENCE,"rows":inventory})
    all_ledgers, fold_reports, models, events = {}, [], [], []
    CALIBRATION_DIAGNOSTIC_COUNTS.clear()
    start = time.perf_counter()
    for lag in (48,72):
        prior = {name:[] for name in COMPONENTS}
        for year in (2020,2021,2022,2023,2024):
            tag = f"lag{lag}-season{year}"
            folder = run / tag
            folder.mkdir()
            train = games.loc[games.season.between(2000,year-1)].copy()
            validation = games.loc[games.season == year].copy()
            def emit(event):
                event = {"system":tag, **event}
                events.append(event)
                log_event(receipt_path,event)
            fitted = fit_current_state_system(train,team,qb,lag_hours=lag,receipt_callback=emit)
            model_path = folder / "system.joblib"
            joblib.dump(fitted,model_path,compress=3)
            state = fitted.state()
            immutable_json(folder / "fitted-state.json",state)
            prediction = fitted.predict(validation,team,qb,draws=2000,seed=SEED+year)
            normalized = {name:normalize_prediction(prediction[name]) for name in COMPONENTS[:3]}
            weight, weight_receipt = ensemble_weight(pd.concat(prior["HIERARCHICAL"],ignore_index=True),pd.concat(prior["RESIDUAL"],ignore_index=True)) if prior["HIERARCHICAL"] else (0.,{"status":"HIERARCHICAL_WARMUP_NO_EARLIER_OOF"})
            emit({"event":"ENSEMBLE_WEIGHT_DISPOSITION", **weight_receipt})
            # Independent of the model's residual-index and rounding stream.
            normalized["ENSEMBLE"] = mixture(normalized["HIERARCHICAL"],normalized["RESIDUAL"],weight,SEED+year+41)
            states = prediction["_states"]
            states.to_parquet(folder / "feature-states.parquet",index=False)
            for name, pred in normalized.items():
                frame = ledger(validation,pred,name,lag,year)
                frame["no_current_history"] = (states.home_current_games.eq(0) | states.away_current_games.eq(0)).to_numpy()
                frame["low_qb_exposure"] = (states.home_qb_effective_exposure.lt(100) | states.away_qb_effective_exposure.lt(100)).to_numpy()
                frame["forecast_cutoff_utc"] = states.forecast_cutoff_utc.to_numpy()
                if "eligible_history_max_available_at" in states:
                    frame["eligible_history_max_available_at"] = states.eligible_history_max_available_at.to_numpy()
                frame.to_parquet(folder / f"{name}-predictions.parquet",index=False)
                prior[name].append(frame)
                fold_reports.append({"lagHours":lag,"season":year,"component":name,"evidenceClass":EVIDENCE,
                                     "metrics":metric_report(frame),"branchCounts":prediction["_coverage"],"decay":fitted.decay})
            # Exact reload check uses identical event batch and seed, no refit.
            reloaded = joblib.load(model_path)
            fixture = validation.head(1)
            before = fitted.predict(fixture,team,qb,draws=200,seed=SEED)
            after = reloaded.predict(fixture,team,qb,draws=200,seed=SEED)
            mismatch = sum(int(np.count_nonzero(before[n][k] != after[n][k])) for n in COMPONENTS[:3] for k in ("homeDraws","awayDraws"))
            if mismatch:
                raise ValueError("RELOAD_MISMATCH")
            emit({"event":"FOLD_COMPLETE","validationGames":len(validation),"reloadMismatch":mismatch})
            models.append({"lagHours":lag,"validationSeason":year,**file_record(model_path)})
        for name in COMPONENTS:
            combined = pd.concat(prior[name],ignore_index=True)
            all_ledgers[(lag,name)] = combined
            combined.to_parquet(run / f"lag{lag}-{name}-oof.parquet",index=False)
    leaderboard, comparisons, calibrated_comparisons = [], {}, {}
    for (lag,name), frame in all_ledgers.items():
        groups = {label:metric_report(frame.loc[mask]) for label,mask in subgroup_masks(frame).items()}
        leaderboard.append({"pipelineId":f"{name}_LAG{lag}","component":name,"lagHours":lag,"evidenceClass":EVIDENCE,
                            **groups["FULL_SEASON"],"subgroups":groups})
        comparisons[f"{name}_LAG{lag}"] = {label:compare(frame,ref) for label,ref in legacy.items()}
        calibrated_comparisons[f"{name}_LAG{lag}"] = {
            label:compare(frame,calibrated) for label,ref in legacy.items()
            if (calibrated := legacy_calibrated(ref)) is not None}
    sensitivity = {name:lag_sensitivity(all_ledgers[(72,name)],all_ledgers[(48,name)]) for name in COMPONENTS}
    # Classifying the entire finalized-archive population is not estimating correction bias.
    limitation = {"evidenceClass":EVIDENCE,"rowsSubjectToUnverifiedLateCorrections":len(games),"fraction":1.0,
                  "correctionBiasMagnitude":None,"reason":"Correction vintages absent;48/72lag sensitivity is not an estimate of revision bias."}
    final_tag = "final-through2024-lag48"
    final_folder = run / final_tag
    final_folder.mkdir()
    def final_emit(event):
        event = {"system":final_tag,**event}
        events.append(event)
        log_event(receipt_path,event)
    fitted = fit_current_state_system(games.loc[games.season.ge(2000)].copy(),team,qb,lag_hours=48,receipt_callback=final_emit)
    final_path = final_folder / "system.joblib"
    joblib.dump(fitted,final_path,compress=3)
    immutable_json(final_folder / "fitted-state.json",fitted.state())
    fixture_states = pd.read_parquet(run / "lag48-season2024/feature-states.parquet").head(1)
    expected_means = fitted.core.predict(fixture_states)
    restored = joblib.load(final_path)
    restored_means = restored.core.predict(fixture_states)
    mismatches = sum(int(np.count_nonzero(expected_means[name] != restored_means[name])) for name in COMPONENTS[:3])
    if mismatches:
        raise ValueError("FINAL_MODEL_RELOAD_MISMATCH")
    final_emit({"event":"FINAL_MODEL_RELOAD_VERIFIED","mismatchCount":mismatches,
                "fixtureMeaning":"Same stored Development input state; serialization verification, not a new historical forecast"})
    weight, weight_receipt = ensemble_weight(all_ledgers[(48,"HIERARCHICAL")],all_ledgers[(48,"RESIDUAL")])
    final_emit({"event":"FINAL_ENSEMBLE_WEIGHT_DISPOSITION",**weight_receipt})
    counts = {event:sum(item["event"]==event for item in events) for event in sorted({item["event"] for item in events})}
    legacy_summaries = {}
    for name,frame in legacy.items():
        calibrated = legacy_calibrated(frame)
        legacy_summaries[name] = {"evidenceClass":EVIDENCE,"availabilityMethod":"LEGACY_PRIOR_DATE_NOT_48_OR_72_RETRAINED",
            "subgroups":{key:metric_report(frame.loc[mask]) for key,mask in subgroup_masks(frame).items()},
            "savedCalibratedSubgroups":{key:metric_report(calibrated.loc[mask]) for key,mask in subgroup_masks(calibrated).items()} if calibrated is not None else None}
    report = {"contract":"NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2",**AUTHORITY,"evidenceClass":EVIDENCE,
              "completedAtUtc":now(),"runId":run_id,"methodology":protocol_ref,"declaration":file_record(run / "declaration.json"),
              "developmentGames":len(games),"validationGamesPerLag":len(all_ledgers[(48,"RESIDUAL")]),"foldReports":fold_reports,
              "leaderboard":leaderboard,"pairedComparisons":comparisons,"lag72Minus48":sensitivity,"legacyComparators":legacy_summaries,
              "pairedComparisonsAgainstSavedCalibratedLegacy":calibrated_comparisons,
              "fittedModels":models,"finalModel":file_record(final_path),"finalEnsembleResidualWeight":weight,
              "finalEnsembleDisposition":weight_receipt,"actualFitAccounting":counts,"runtimeSeconds":time.perf_counter()-start,
              "calibrationDiagnosticsAccounting":dict(CALIBRATION_DIAGNOSTIC_COUNTS),"appliedCalibratorFits":0,
              "genericMedianFallbacks":0,"genericModeFallbacks":0,"finalOotAccessed":False,"lateCorrections":limitation,
              "unsupportedHistoricalSubgroups":["actual target starter/rookie","coach change","injury","high roster turnover","weather","travel/timezone"],
              "selection":"RESIDUAL_LAG48 remains research challenger regardless of result; no promotion authorized.",
              "artifacts":[file_record(path) for path in sorted(run.rglob("*")) if path.is_file()]}
    immutable_json(completed,report)
    pointer = {"status":"COMPLETED","evidenceClass":EVIDENCE,"result":file_record(completed),"runId":run_id}
    immutable_json(output / "completed" / run_id / "pointer.json",pointer)
    print(json.dumps(pointer),flush=True)
    return report
