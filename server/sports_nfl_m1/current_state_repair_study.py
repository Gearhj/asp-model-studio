"""Bounded successor to the saved V2 study; only affected systems are refitted."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from server.audit_assurance.canonical import canonical_json_bytes
from . import current_state_study as original
from .labs_simulation import file_record, immutable_json

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1"
PREDECESSOR = ROOT / "outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/result.json"
PREDECESSOR_SHA = "29989f3af980fd2cb0fa97096f570ced6950d66b981168d83d97c38243f160e3"
EVIDENCE, AUTHORITY, SEED = original.EVIDENCE, original.AUTHORITY, original.SEED
COMPONENTS = original.COMPONENTS
GROUPS = ("WEEK_1", "WEEKS_1_4", "FULL_SEASON")
PROBABILITIES = [f"raw_{side}_probability" for side in ("away", "tie", "home")]


def checked(ref):
    expected = {key: ref[key] for key in ("path", "sha256", "byteCount")}
    if file_record(Path(ref["path"])) != expected:
        raise ValueError("IMMUTABLE_PREDECESSOR_OR_REPAIR_ARTIFACT_CHANGED")
    return Path(ref["path"])


def metrics(frame):
    result = original.metric_report(frame)
    if not len(frame):
        return result
    home = frame.predicted_home_points - frame.actual_home_points
    away = frame.predicted_away_points - frame.actual_away_points
    result["signedBiasPredictedMinusActual"] = {
        "home": float(home.mean()), "away": float(away.mean()),
        "margin": float((home-away).mean()), "total": float((home+away).mean()),
        "evidenceClass": EVIDENCE}
    return result


def groups(frame):
    masks = original.subgroup_masks(frame)
    return {name: metrics(frame.loc[masks[name]]) for name in GROUPS}


def balanced_mixture(hier, residual, weight, seed):
    from .current_state_repaired_model import mean_preserving_scores
    h = original.normalize_prediction(hier)
    r = original.normalize_prediction(residual)
    mixed = original.mixture(h, r, weight, seed)
    mean = (1-weight)*np.asarray(h["mean"]) + weight*np.asarray(r["mean"])
    mixed["home_draws"] = mean_preserving_scores(mixed["home_draws"], mean[:, 0])
    mixed["away_draws"] = mean_preserving_scores(mixed["away_draws"], mean[:, 1])
    mixed["mean"] = mean
    return mixed


def chronological_calibration(frame, folder, emit):
    """Same fixed recipe as saved M1; no selection or future-season authority."""
    result = frame.copy()
    output_columns = [f"calibrated_{side}_probability" for side in ("away", "tie", "home")]
    result[output_columns] = result[PROBABILITIES].to_numpy()
    result["calibrationDisposition"] = "RAW_INSUFFICIENT_EARLIER_OOF"
    receipts = []
    folder.mkdir(parents=True, exist_ok=True)
    for season in sorted(result.season.unique()):
        training = result.loc[result.season < season]
        mask = result.season.eq(season)
        if training.empty or training.outcome_class.nunique() < 3:
            receipts.append({"validationSeason": int(season), "status": "RAW_INSUFFICIENT_EARLIER_OOF", "evidenceClass": EVIDENCE})
            continue
        model = LogisticRegression(C=1., solver="lbfgs", max_iter=2000, random_state=731001)
        emit({"event": "EVALUATION_CALIBRATOR_FIT_START", "validationSeason": int(season), "trainingGames": len(training)})
        with threadpool_limits(limits=2):
            model.fit(np.log(np.clip(training[PROBABILITIES].to_numpy(), 1e-12, 1.)), training.outcome_class.to_numpy(int))
            p = model.predict_proba(np.log(np.clip(result.loc[mask, PROBABILITIES].to_numpy(), 1e-12, 1.)))
        aligned = np.zeros((int(mask.sum()), 3))
        aligned[:, model.classes_.astype(int)] = p
        result.loc[mask, output_columns] = aligned
        result.loc[mask, "calibrationDisposition"] = "EARLIER_OOF_ONLY_MULTINOMIAL_LOGIT"
        path = folder / f"through{int(season)-1}.joblib"
        joblib.dump(model, path, compress=3)
        restored = joblib.load(path)
        with threadpool_limits(limits=2):
            repeat = restored.predict_proba(np.log(np.clip(result.loc[mask, PROBABILITIES].to_numpy(), 1e-12, 1.)))
        if not np.array_equal(p, repeat):
            raise ValueError("CALIBRATOR_RELOAD_MISMATCH")
        receipt = {"event": "EVALUATION_CALIBRATOR_FIT_COMPLETE", "validationSeason": int(season),
                   "trainingGames": len(training), "trainingSeasons": sorted(training.season.astype(int).unique().tolist()),
                   "trainingObservationIds": training.canonical_game_id.tolist(), "artifact": file_record(path),
                   "reloadMismatch": 0, "evidenceClass": EVIDENCE}
        emit(receipt); receipts.append(receipt)
    immutable_json(folder / "receipts.json", {"evidenceClass": EVIDENCE, "folds": receipts,
        "method": "CHRONOLOGICAL_MULTINOMIAL_LOGIT_ON_LOG_PROBABILITIES", "C": 1., "seed": 731001,
        "currentPublicationApplied": False, "selection": "REPORT_BOTH_RAW_AND_CALIBRATED_NO_SELECTION"})
    return result


def _m1(declaration):
    refs = [ref for ref in declaration["legacyComparators"] if ref["modelId"] == "M1_RECIPE_FOLD_REFIT"]
    raw_ref = next(ref for ref in refs if ref.get("purpose") != "SAVED_CHRONOLOGICAL_CALIBRATION_NO_NEW_FIT")
    calibrated_ref = next(ref for ref in refs if ref.get("purpose") == "SAVED_CHRONOLOGICAL_CALIBRATION_NO_NEW_FIT")
    raw = pd.read_parquet(checked(raw_ref))
    calibrated = pd.read_parquet(checked(calibrated_ref)).set_index("canonical_game_id").reindex(raw.canonical_game_id)
    if not raw.season.between(2020, 2024).all() or not np.array_equal(calibrated.outcome_class.to_numpy(), raw.outcome_class.to_numpy()):
        raise ValueError("M1_SAVED_DEVELOPMENT_COHORT_DIFFERS")
    if not np.array_equal(calibrated[PROBABILITIES].to_numpy(), raw[PROBABILITIES].to_numpy()):
        raise ValueError("SAVED_M1_CALIBRATION_RAW_INPUT_DIFFERS")
    for side in ("away", "tie", "home"):
        raw[f"calibrated_{side}_probability"] = calibrated[f"calibrated_{side}_probability"].to_numpy()
    raw["evidenceClass"] = EVIDENCE
    return raw, refs


def run_repair(output=OUTPUT):
    from .current_state_repaired_model import fit_repaired_current_state_system, MEAN_INPUT_NAMES, UNCERTAINTY_ONLY_NAMES
    predecessor_ref = file_record(PREDECESSOR)
    if predecessor_ref["sha256"] != PREDECESSOR_SHA:
        raise ValueError("PREDECESSOR_RESULT_IDENTITY_DIFFERS")
    old = json.loads(PREDECESSOR.read_bytes())
    for ref in old["artifacts"]:
        checked(ref)
    old_declaration = json.loads(checked(old["declaration"]).read_bytes())
    source_refs = {name: file_record(PREDECESSOR.parent / name) for name in (
        "development-cohort.parquet", "sufficient-statistics-team.parquet", "sufficient-statistics-qb.parquet")}
    games, team, qb = (pd.read_parquet(checked(ref)) for ref in source_refs.values())
    if any(not frame.season.between(1999, 2024).all() for frame in (games, team, qb)):
        raise ValueError("NON_DEVELOPMENT_SOURCE_PARTITION")
    games = games.sort_values(["season", "game_date", "canonical_game_id"]).reset_index(drop=True)
    m1, m1_refs = _m1(old_declaration)
    protocol_ref = file_record(output / "methodology-contract.json")
    code = [file_record(Path(__file__)), file_record(Path(__file__).with_name("current_state_repaired_model.py")),
            *old_declaration["generatingCode"]]
    for ref in code:
        checked(ref)
    identity = {"protocol": protocol_ref, "predecessor": predecessor_ref, "sourceRefs": source_refs, "code": code}
    run_id = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    run = output / "runs" / run_id
    run.mkdir(parents=True, exist_ok=True)
    if (run / "result.json").exists():
        completed = json.loads((run / "result.json").read_bytes())
        for ref in completed["artifacts"]:
            checked(ref)
        print("EXISTING_COMPLETED_REPAIR_REUSED_NO_FITS", flush=True)
        return completed
    receipts_path = run / "fit-receipts.jsonl"
    if receipts_path.exists():
        raise ValueError("PARTIAL_REPAIR_ATTEMPT_REQUIRES_EXPLICIT_DISPOSITION")
    declaration = {"contract": "NFL_UNCERTAINTY_REPAIR_RUN_DECLARATION_V1", **AUTHORITY,
        "evidenceClass": EVIDENCE, "runId": run_id, "declaredAtUtc": original.now(), **identity,
        "sourceEvidence": old_declaration["sourceEvidence"], "m1SavedReferences": m1_refs,
        "meanInputNames": list(MEAN_INPUT_NAMES), "uncertaintyOnlyNames": list(UNCERTAINTY_ONLY_NAMES),
        "meanFitBudget": 66, "varianceFitBudget": 33, "evaluationCalibratorFitBudget": 32,
        "newRetentionSearches": 0, "m1MeanFits": 0, "dynamicMeanFits": 0, "sealed2025Read": False}
    immutable_json(run / "declaration.json", declaration)
    events, all_ledgers, fold_reports, model_refs = [], {}, [], []
    original.CALIBRATION_DIAGNOSTIC_COUNTS.clear()
    started = time.perf_counter()

    def make_emit(tag):
        def emit(event):
            item = {"system": tag, **event}
            events.append(item); original.log_event(receipts_path, item)
        return emit

    for lag in (48, 72):
        previous = {name: [] for name in COMPONENTS}
        for season in (2020, 2021, 2022, 2023, 2024):
            tag = f"lag{lag}-season{season}"
            folder = run / tag; folder.mkdir()
            emit = make_emit(tag)
            old_ref = next(ref for ref in old["fittedModels"] if ref["lagHours"] == lag and ref["validationSeason"] == season)
            parent = joblib.load(checked(old_ref))
            train = games.loc[games.season.between(2000, season-1)].copy()
            valid = games.loc[games.season.eq(season)].copy()
            fitted = fit_repaired_current_state_system(train, team, qb, predecessor=parent,
                predecessor_ref={key: old_ref[key] for key in ("path", "sha256", "byteCount")},
                lag_hours=lag, receipt_callback=emit, artifact_dir=folder)
            path = folder / "system.joblib"; joblib.dump(fitted, path, compress=3)
            immutable_json(folder / "fitted-state.json", fitted.state())
            states_ref = file_record(PREDECESSOR.parent / tag / "feature-states.parquet")
            states = pd.read_parquet(checked(states_ref))
            if states.canonical_game_id.tolist() != valid.canonical_game_id.tolist():
                raise ValueError("SAVED_VALIDATION_STATE_EVENT_ORDER_DIFFERS")
            predicted = fitted.predict_states(states, draws=2000, seed=SEED+season)
            # Complete Week1 avoids changing the original common slate cutoff.
            week1 = valid.loc[valid.week.eq(1)]
            reconstructed = fitted.predict(week1, team, qb, draws=200, seed=SEED)
            saved_week1 = states.loc[states.week.eq(1)].reset_index(drop=True)
            lhs = reconstructed["_states"][list(MEAN_INPUT_NAMES)].to_numpy(float)
            rhs = saved_week1[list(MEAN_INPUT_NAMES)].to_numpy(float)
            if not np.allclose(lhs, rhs, rtol=0, atol=1e-10, equal_nan=True):
                raise ValueError("TRAINING_CURRENT_FEATURE_PARITY_FAILED")
            changed = states.copy()
            for name in (*UNCERTAINTY_ONLY_NAMES, *[name for name in states if name.endswith("__posterior_sd")]):
                changed[name] = 123.0
            before, after = fitted.core.predict(states), fitted.core.predict(changed)
            invariance = sum(int(np.count_nonzero(before[name] != after[name])) for name in COMPONENTS[:3])
            dynamic_change = int(np.count_nonzero(before["DYNAMIC"] != parent.core.predict(states)["DYNAMIC"]))
            if invariance or dynamic_change:
                raise ValueError("UNCERTAINTY_MEAN_INVARIANCE_OR_DYNAMIC_REUSE_FAILED")
            weight, w_receipt = original.ensemble_weight(pd.concat(previous["HIERARCHICAL"], ignore_index=True),
                pd.concat(previous["RESIDUAL"], ignore_index=True)) if previous["HIERARCHICAL"] else (0., {"status": "HIERARCHICAL_WARMUP_NO_EARLIER_OOF"})
            emit({"event": "ENSEMBLE_WEIGHT_DISPOSITION", **w_receipt})
            normalized = {name: original.normalize_prediction(predicted[name]) for name in COMPONENTS[:3]}
            normalized["ENSEMBLE"] = balanced_mixture(predicted["HIERARCHICAL"], predicted["RESIDUAL"], weight, SEED+season+41)
            for name, population in normalized.items():
                frame = original.ledger(valid, population, name, lag, season)
                frame["forecast_cutoff_utc"] = states.forecast_cutoff_utc.to_numpy()
                frame["eligible_history_max_available_at"] = states.eligible_history_max_available_at.to_numpy()
                frame["no_current_history"] = (states.home_current_games.eq(0) | states.away_current_games.eq(0)).to_numpy()
                frame["fitted_home_mean"] = population["mean"][:, 0]
                frame["fitted_away_mean"] = population["mean"][:, 1]
                if np.max(np.abs(frame[["predicted_home_points", "predicted_away_points"]].to_numpy()-population["mean"])) > .5/2000+1e-12:
                    raise ValueError("FINITE_POPULATION_MEAN_MISMATCH")
                frame.to_parquet(folder / f"{name}-predictions.parquet", index=False)
                previous[name].append(frame)
                fold_reports.append({"component": name, "lagHours": lag, "season": season, "evidenceClass": EVIDENCE,
                    "metrics": metrics(frame), "subgroups": groups(frame), "branchCounts": predicted["_coverage"], "decay": fitted.decay})
            restored = joblib.load(path)
            repeat = restored.predict_states(saved_week1, draws=200, seed=SEED)
            expected = fitted.predict_states(saved_week1, draws=200, seed=SEED)
            mismatch = sum(int(np.count_nonzero(repeat[name][field] != expected[name][field]))
                           for name in COMPONENTS[:3] for field in ("homeDraws", "awayDraws", "scoreMeans"))
            if mismatch:
                raise ValueError("REPAIRED_MODEL_RELOAD_MISMATCH")
            verification = {"evidenceClass": EVIDENCE, "stateSource": states_ref, "uncertaintyMeanMismatches": invariance,
                "unchangedDynamicMeanMismatches": dynamic_change, "reloadMismatches": mismatch,
                "week1TrainCurrentFeatureParityMaximumAbsoluteDifference": float(np.nanmax(np.abs(lhs-rhs)))}
            immutable_json(folder / "verification.json", verification)
            emit({"event": "FOLD_COMPLETE", "validationGames": len(valid), **verification})
            model_refs.append({"lagHours": lag, "validationSeason": season, **file_record(path)})
        for name, frames in previous.items():
            combined = pd.concat(frames, ignore_index=True)
            combined = chronological_calibration(combined, run / "evaluation-calibration" / f"{name}-lag{lag}", make_emit(f"calibration-{name}-lag{lag}"))
            combined.to_parquet(run / f"lag{lag}-{name}-oof.parquet", index=False)
            all_ledgers[(lag, name)] = combined

    final_folder = run / "final-through2024-lag48"; final_folder.mkdir()
    final_emit = make_emit("final-through2024-lag48")
    final_parent = joblib.load(checked(old["finalModel"]))
    fitted = fit_repaired_current_state_system(games.loc[games.season.ge(2000)], team, qb,
        predecessor=final_parent, predecessor_ref=old["finalModel"], lag_hours=48,
        receipt_callback=final_emit, artifact_dir=final_folder)
    final_path = final_folder / "system.joblib"; joblib.dump(fitted, final_path, compress=3)
    immutable_json(final_folder / "fitted-state.json", fitted.state())
    fixture = pd.read_parquet(PREDECESSOR.parent / "lag48-season2024/feature-states.parquet").head(2)
    expected, actual = fitted.predict_states(fixture, draws=200, seed=SEED), joblib.load(final_path).predict_states(fixture, draws=200, seed=SEED)
    mismatch = sum(int(np.count_nonzero(expected[name][field] != actual[name][field])) for name in COMPONENTS[:3] for field in ("homeDraws", "awayDraws", "scoreMeans"))
    if mismatch:
        raise ValueError("FINAL_MODEL_RELOAD_MISMATCH")
    final_emit({"event": "FINAL_MODEL_RELOAD_VERIFIED", "mismatchCount": mismatch})
    weight, disposition = original.ensemble_weight(all_ledgers[(48, "HIERARCHICAL")], all_ledgers[(48, "RESIDUAL")])
    final_emit({"event": "FINAL_ENSEMBLE_WEIGHT_DISPOSITION", **disposition})
    leaderboard, comparisons, saved_results = [], {}, {}
    calibrated_m1 = original.legacy_calibrated(m1)
    for (lag, name), frame in all_ledgers.items():
        calibrated = original.legacy_calibrated(frame)
        key = f"{name}_LAG{lag}"
        previous = pd.read_parquet(PREDECESSOR.parent / f"lag{lag}-{name}-oof.parquet")
        previous_dynamic = pd.read_parquet(PREDECESSOR.parent / f"lag{lag}-DYNAMIC-oof.parquet")
        if frame.canonical_game_id.tolist() != previous.canonical_game_id.tolist():
            raise ValueError("REPAIRED_MATCHED_COHORT_CHANGED")
        raw_groups, cal_groups = groups(frame), groups(calibrated)
        leaderboard.append({"pipelineId": key, "component": name, "lagHours": lag, "evidenceClass": EVIDENCE,
            **raw_groups["FULL_SEASON"], "subgroups": raw_groups, "equivalentCalibratedSubgroups": cal_groups,
            "calibratedDistributionMeaning": "Outcome probabilities only; score bias/intervals still describe raw joint law. Not applied to current publication."})
        comparisons[key] = {"rawVsM1Raw": original.compare(frame, m1),
            "calibratedVsM1Calibrated": original.compare(calibrated, calibrated_m1),
            "rawVsOriginalSameComponent": original.compare(frame, previous),
            "rawVsOriginalDynamic": original.compare(frame, previous_dynamic),
            "rawVsRepairedDynamic": original.compare(frame, all_ledgers[(lag, "DYNAMIC")]),
            "calibratedVsRepairedDynamicCalibrated": original.compare(calibrated, original.legacy_calibrated(all_ledgers[(lag, "DYNAMIC")]))}
        saved_results[key] = groups(previous)
    accounting = dict(Counter(item["event"] for item in events))
    if accounting.get("ESTIMATOR_FIT_START") != 66 or accounting.get("ESTIMATOR_FIT_COMPLETE") != 66 or accounting.get("FOLD_COMPLETE") != 10:
        raise ValueError("ACTUAL_BOUNDED_FIT_ACCOUNTING_DIFFERS")
    result = {"contract": "NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2", "repairContract": "NFL_UNCERTAINTY_MEAN_SEPARATION_REPAIR_RESULT_V1",
        **AUTHORITY, "evidenceClass": EVIDENCE, "runId": run_id, "completedAtUtc": original.now(),
        "predecessor": predecessor_ref, "supersedesForCurrentResearch": True, "predecessorArtifactsPreserved": True,
        "methodology": protocol_ref, "declaration": file_record(run / "declaration.json"), "sourceRefs": source_refs,
        "developmentGames": len(games), "validationGamesPerLag": len(all_ledgers[(48, "RESIDUAL")]),
        "foldReports": fold_reports, "leaderboard": leaderboard, "pairedComparisons": comparisons,
        "lag72Minus48": {name: original.lag_sensitivity(all_ledgers[(72, name)], all_ledgers[(48, name)]) for name in COMPONENTS},
        "legacyComparators": {"M1": {"raw": groups(m1), "equivalentCalibrated": groups(calibrated_m1),
            "sourceRefs": m1_refs, "availabilityMethod": "LEGACY_PRIOR_DATE_NOT_48_72_RETRAINED"}},
        "supersededResults": saved_results, "fittedModels": model_refs, "finalModel": file_record(final_path),
        "finalEnsembleResidualWeight": weight, "finalEnsembleDisposition": disposition,
        "actualFitAccounting": accounting, "runtimeSeconds": time.perf_counter()-started,
        "calibrationDiagnosticsAccounting": dict(original.CALIBRATION_DIAGNOSTIC_COUNTS),
        "appliedEvaluationCalibratorFits": accounting.get("EVALUATION_CALIBRATOR_FIT_COMPLETE", 0),
        "currentPublicationCalibratorFits": 0, "genericMedianFallbacks": 0, "genericModeFallbacks": 0,
        "finalOotAccessed": False, "lateCorrections": old["lateCorrections"],
        "currentForecastClassification": "HISTORICAL_PRIOR_BASELINE", "currentRosterDepthNumericallyIncorporated": False,
        "selection": "No champion selection or NFL expansion. Fixed repaired primary RESIDUAL48 remains research-only regardless of result.",
        "artifacts": [file_record(path) for path in sorted(run.rglob("*")) if path.is_file()]}
    immutable_json(run / "result.json", result)
    pointer = {"status": "COMPLETED", "evidenceClass": EVIDENCE, "runId": run_id, "result": file_record(run / "result.json")}
    immutable_json(output / "completed" / run_id / "pointer.json", pointer)
    print(json.dumps(pointer), flush=True)
    return result
