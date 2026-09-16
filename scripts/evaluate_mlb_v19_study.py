"""Explicit post-global-fit V19 chronological meta study and matched evaluation.

No provider, operational publication, AISP, fitting of global estimators, or
unsealing path exists. Invoke only after all four globals completed all folds.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "4"

import argparse
import json
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from server.sports_current_statcast.mlb_regime_baseline import sha_file
from server.sports_current_statcast.mlb_regime_metrics import metric_contributions, paired_uncertainty
from server.sports_current_statcast.mlb_v19_evaluation import discover_persistent_regimes, evaluate_predictions, regime_masks
from server.sports_current_statcast.mlb_v19_meta import GLOBAL_ORDER, ENSEMBLE_NAMES, fit_meta_system
from server.sports_current_statcast.mlb_v19_launch_guard import require_v19_launch_authority
from server.sports_current_statcast.mlb_regime_models import temperature_transform
from reproduce_mlb_v19_baseline import load_safe_cache, BASE_SHA
from run_mlb_v19_study import OUT, VARIANTS, clean, emit, fitted, join_teams, ref, write_json


def checked_artifact(entry):
    path = Path(entry["path"])
    if not path.is_relative_to(ROOT):
        raise ValueError("Research artifact outside Model Studio")
    if path.stat().st_size != entry["bytes"] or sha_file(path) != entry["sha256"]:
        raise ValueError("Immutable research artifact differs: " + str(path))
    return path


def read_completed_global_folds(frame, baseline_probabilities):
    predictions = {name: [] for name in VARIANTS}
    labels, eligibility, authorities = [], {}, []
    for fold in range(1, 6):
        directory = OUT / f"folds/fold-{fold}"
        complete_path = directory / "complete.json"
        if not complete_path.exists():
            raise ValueError(f"GLOBAL_FOLD_{fold}_NOT_COMPLETED; no meta fit or evaluation launched")
        complete = json.loads(complete_path.read_text())
        count = int(frame.foldNumber.eq(fold).sum())
        if complete["globalFitsCompleted"] != 4 or complete["validationRows"] != count:
            raise ValueError("Global fit completion or matched validation count differs")
        # Eligibility must reproduce the predeclared earlier-fold computation;
        # merely trusting a mutable list of regime names could admit hindsight.
        eligibility_path = directory / "specialist-eligibility.json"
        eligibility[fold] = json.loads(eligibility_path.read_text())
        expected_eligibility = discover_persistent_regimes(frame, baseline_probabilities, before_fold=fold)
        if clean(eligibility[fold]) != clean(expected_eligibility):
            raise ValueError("Pre-fit specialist eligibility differs from declared earlier-fold authority")
        for entry in complete["artifacts"]:
            checked_artifact(entry)
        lookup = {Path(entry["path"]).name: entry for entry in complete["artifacts"]}
        for name in VARIANTS:
            path = checked_artifact(lookup[name + "-probabilities.npy"])
            matrix = np.load(path, allow_pickle=False)
            if matrix.shape != (count, 8):
                raise ValueError("Global eight-class prediction array shape differs")
            predictions[name].append(matrix)
        label = pd.read_parquet(checked_artifact(lookup["cluster-labels.parquet"]))
        if not np.array_equal(label.canonicalPaId, frame.loc[frame.foldNumber.eq(fold), "canonicalPaId"]):
            raise ValueError("Fold cluster labels differ from matched observation order")
        labels.append(label)
        authorities.append({"globalCompletion": ref(complete_path), "specialistEligibility": ref(eligibility_path)})
    return {name: np.vstack(values) for name, values in predictions.items()}, pd.concat(labels, ignore_index=True), eligibility, authorities


def fit_and_reproduce_meta(frame, global_predictions, eligibility, global_authorities):
    raw_folds, calibrated_folds, receipts = [], [], []
    models = {}
    for number in range(1, 6):
        directory = OUT / f"meta/fold-{number}"
        directory.mkdir(parents=True, exist_ok=True)
        complete_path = directory / "complete.json"
        current = frame.foldNumber.eq(number).to_numpy()
        input_authority = {"baselineReceiptSha256": BASE_SHA, "beforeFold": number,
            "selectedRegimes": eligibility[number]["selected"],
            "globalAuthoritiesThroughCurrentFold": global_authorities[:number],
            "metaCode": ref(ROOT / "server/sports_current_statcast/mlb_v19_meta.py"),
            "runnerCode": ref(Path(__file__)),
            "foldSelectionRule": "STRICTLY_EARLIER_OOF_FOLDS_ONLY_CURRENT_FOLD_PREDICTIONS_FOR_REPLAY_ONLY"}
        if complete_path.exists():
            receipt = json.loads(complete_path.read_text())
            if receipt.get("inputAuthority") != input_authority or receipt.get("validationRows") != int(current.sum()):
                raise ValueError("Existing meta authority differs; preserve it and require explicit versioned recovery")
            for entry in receipt["artifacts"]:
                checked_artifact(entry)
            model = joblib.load(directory / "meta-system.joblib")
            raw = joblib.load(directory / "raw-predictions.joblib")
            calibrated = joblib.load(directory / "calibrated-predictions.joblib")
            emit("META_FOLD_REUSED", fold=number)
        else:
            if any((directory / name).exists() for name in ("meta-system.joblib", "raw-predictions.joblib", "calibrated-predictions.joblib")):
                raise ValueError("Incomplete meta attempt retained; explicit recovery review required")
            previous = frame.foldNumber.lt(number).to_numpy()
            history = frame.loc[previous].reset_index(drop=True)
            validation = frame.loc[current].reset_index(drop=True)
            if len(history) and history.game_date.max() >= validation.game_date.min():
                raise ValueError("Meta OOF history is not strictly earlier than this fold")
            model = fit_meta_system(history, {name: matrix[previous] for name, matrix in global_predictions.items()},
                before_fold=number, selected_regimes=eligibility[number]["selected"], run_fit=fitted)
            model_path = directory / "meta-system.joblib"
            joblib.dump(model, model_path, compress=3)
            bases = {name: matrix[current] for name, matrix in global_predictions.items()}
            raw, calibrated = model.predict(validation, bases), model.predict(validation, bases, calibrated=True)
            raw_path, calibrated_path = directory / "raw-predictions.joblib", directory / "calibrated-predictions.joblib"
            joblib.dump(raw, raw_path, compress=3); joblib.dump(calibrated, calibrated_path, compress=3)
            reloaded = joblib.load(model_path)
            replay_raw = reloaded.predict(validation, bases)
            replay_calibrated = reloaded.predict(validation, bases, calibrated=True)
            if any(not np.array_equal(raw[name], replay_raw[name]) or not np.array_equal(calibrated[name], replay_calibrated[name]) for name in raw):
                raise ValueError("Meta full-fold artifact reload mismatch")
            # Perturb targets/realized context: gates must remain outcome independent.
            changed = validation.iloc[:32].copy()
            changed["observedClassIndex"] = (changed.observedClassIndex + 1) % 8
            for name in ("context_inning", "context_outs_before", "context_base_mask_before",
                         "context_batting_score_diff_before", "context_top_bottom"):
                if name in changed:
                    changed[name] = 999
            fixture_bases = {name: matrix[:32] for name, matrix in bases.items()}
            invariant = reloaded.predict(changed, fixture_bases, calibrated=True)
            if any(not np.array_equal(invariant[name], calibrated[name][:32]) for name in calibrated):
                raise ValueError("Meta gate depends on target or realized in-game state")
            fixture_path = directory / "reload-fixture.joblib"
            joblib.dump({"rows": validation.iloc[:32], "baseProbabilities": fixture_bases,
                "rawProbabilities": {name: matrix[:32] for name, matrix in raw.items()},
                "calibratedProbabilities": {name: matrix[:32] for name, matrix in calibrated.items()},
                "targetOrder": list(model.receipt.get("targetOrder", []))}, fixture_path, compress=3)
            fit_receipt = write_json(directory / "meta-fit.json", model.receipt)
            receipt = {"fold": number, "validationRows": len(validation), "actualMetaFits": model.receipt["actualMetaFits"],
                "inputAuthority": input_authority,
                "artifacts": [ref(model_path), ref(raw_path), ref(calibrated_path), ref(fixture_path), fit_receipt],
                "fullFoldReloadComparedRows": len(validation), "reloadMismatchCount": 0,
                "outcomeAndRealizedContextGateInvariance": True, "noFinalOotPayloadRead": True}
            write_json(complete_path, receipt)
            emit("META_FOLD_RELOAD_VERIFIED", fold=number, rows=len(validation), actualMetaFits=receipt["actualMetaFits"])
        models[number] = model
        raw_folds.append(raw); calibrated_folds.append(calibrated); receipts.append(ref(complete_path))
    names = list(GLOBAL_ORDER) + list(ENSEMBLE_NAMES)
    # Per-specialist branches are evaluated in the fold receipts/routing report;
    # the common matrix retains the same seven executable systems in every fold.
    return ({name: np.vstack([fold[name] for fold in raw_folds]) for name in names},
            {name: np.vstack([fold[name] for fold in calibrated_folds]) for name in names}, receipts, models)


def specialist_routing_report(frame, predictions, models, replicates, *, raw_baseline):
    masks, _ = regime_masks(frame)
    routed = np.zeros(len(frame), dtype=bool)
    selections = []
    for fold, model in models.items():
        local = frame.foldNumber.eq(fold).to_numpy()
        eligible_support = np.zeros(len(frame), dtype=bool)
        support = np.zeros(len(frame), dtype=bool)
        active_names = []
        for name in model.specialists:
            eligible_support |= masks[name]
            index = model.specialist_gate.branch_order.index("SPECIALIST:" + name)
            if model.specialist_gate.weights[index] > 0:
                active_names.append(name)
                support |= masks[name]
        routed |= local & support
        selections.append({"fold": fold, "selectedNames": list(model.specialists),
            "positiveWeightNames": active_names, "selectedEligibleSupportObservations": int((local & eligible_support).sum()),
            "routedObservations": int((local & support).sum()), "unroutedObservations": int((local & ~support).sum()),
            "gateWeights": model.specialist_gate.weights.tolist(), "globalGateWeights": model.global_gate.weights.tolist()})
    y = frame.observedClassIndex.to_numpy(dtype=int)
    records = []
    for name, probability in predictions.items():
        if name not in {"V18", "REGIME_HGB", "SPECIALIST_MIXTURE", "GLOBAL_ENSEMBLE"}:
            continue
        contributions = metric_contributions(y, probability)
        for scope, mask in (("ROUTED", routed), ("COMPLEMENT", ~routed)):
            records.append({"model": name, "scope": scope, "observations": int(mask.sum()),
                "games": int(frame.loc[mask, "canonicalGameId"].nunique()),
                "logLoss": float(contributions["logLoss"][mask].mean()) if mask.any() else None,
                "brier": float(contributions["brier"][mask].mean()) if mask.any() else None})
    intervals = {}
    for scope, mask in (("ROUTED", routed), ("COMPLEMENT", ~routed)):
        if mask.sum() >= 100 and frame.loc[mask, "canonicalGameId"].nunique() >= 20:
            intervals[scope] = paired_uncertainty(frame.loc[mask].reset_index(drop=True), y[mask],
                predictions["V18"][mask], predictions["SPECIALIST_MIXTURE"][mask], replicates=replicates)
        else:
            intervals[scope] = {"status": "INSUFFICIENT_ROUTING_SUPPORT"}
    individual = []
    for fold, model in models.items():
        local = frame.foldNumber.eq(fold).to_numpy()
        local_frame = frame.loc[local].reset_index(drop=True)
        local_masks, _ = regime_masks(local_frame)
        local_y = y[local]
        raw_branches = model.specialist_predictions(local_frame, raw_baseline[local])
        base = {"raw": raw_baseline[local], "calibrated": predictions["V18"][local]}
        for name in model.specialists:
            branch = "SPECIALIST:" + name
            raw_probability = raw_branches[branch]
            t = model.temperatures[branch]
            calibrated_probability = temperature_transform(raw_probability, t) if t != 1. else raw_probability.copy()
            support = local_masks[name]
            for scale, probability in (("raw", raw_probability), ("calibrated", calibrated_probability)):
                values = metric_contributions(local_y, probability)
                baseline_values = metric_contributions(local_y, base[scale])
                for scope, mask in (("REGIME", support), ("COMPLEMENT", ~support), ("ALL", np.ones(len(local_frame), dtype=bool))):
                    n = int(mask.sum())
                    individual.append({"fold": fold, "specialist": name, "scale": scale, "scope": scope,
                        "observations": n, "games": int(local_frame.loc[mask, "canonicalGameId"].nunique()),
                        "logLoss": float(values["logLoss"][mask].mean()) if n else None,
                        "brier": float(values["brier"][mask].mean()) if n else None,
                        "deltaLogLossVsV18": float((values["logLoss"] - baseline_values["logLoss"])[mask].mean()) if n else None,
                        "deltaBrierVsV18": float((values["brier"] - baseline_values["brier"])[mask].mean()) if n else None,
                        "learnedMixtureWeight": float(model.specialist_gate.weights[model.specialist_gate.branch_order.index(branch)]),
                        "temperature": float(t) if scale == "calibrated" else 1.,
                        "diagnosticOnlyNotNewSelection": True})
    return {"schemaVersion": "MLB_V19_ACTUAL_ROUTING_EVALUATION_V1", "folds": selections,
        "metrics": records, "pairedIntervals": intervals,
        "individualSpecialistMetrics": individual,
        "complementInterpretation": "Raw specialists are exact V18 off-regime. Independent earlier-OOF scalar temperatures can change calibrated complements; the decision guard compares against equally calibrated V18.",
        "routingDefinition": "FOLD_FROZEN_POSITIVE_GATE_WEIGHT_PREGAME_REGIME_UNION_NOT_POSTHOC_ERROR_GROUP",
        "interpretation": "DESCRIPTIVE_REUSED_DEVELOPMENT_ONLY"}


def decision_report(evaluation, routing):
    metrics = evaluation["metrics"]
    records = []
    for name in (*GLOBAL_ORDER[1:], *ENSEMBLE_NAMES):
        overall = next(row for row in metrics if row["model"] == name and row["dimension"] == "overall")
        folds = [row for row in metrics if row["model"] == name and row["dimension"] == "foldNumber"]
        intervals = evaluation["pairedIntervals"][name]
        interval_pass = all(intervals[key].get("intervals", {}).get("logLoss", {}).get("upper", np.inf) < 0
            for key in ("gameClusterBootstrap", "calendarWeekBlockBootstrap") if intervals[key].get("intervals") is not None)
        interval_pass = interval_pass and all(intervals[key].get("status") == "AVAILABLE"
            for key in ("gameClusterBootstrap", "calendarWeekBlockBootstrap"))
        removal = [row for row in evaluation["removalSensitivity"] if row["model"] == name]
        required = {"month", "team_either_role", "cluster_fold_local", "regime"}
        conditions = {"matchedCalibratedLogLossImproves": overall["deltaLogLossVsV18"] < 0,
            "matchedCalibratedBrierNonworse": overall["deltaBrierVsV18"] <= 0,
            "atLeastThreeImprovingFolds": sum(row["deltaLogLossVsV18"] < 0 for row in folds) >= 3,
            "BothDescriptiveLogLossIntervalUpperBoundsBelowZero": bool(interval_pass),
            "AllRequiredRemovalSensitivitiesImprove": required.issubset({row["removedDimension"] for row in removal})
                and all(row["remainingDeltaLogLoss"] < 0 for row in removal)}
        if name == "SPECIALIST_MIXTURE":
            indexed = {(r["model"], r["scope"]): r for r in routing["metrics"]}
            base, candidate = indexed[("V18", "ROUTED")], indexed[(name, "ROUTED")]
            cb, cc = indexed[("V18", "COMPLEMENT")], indexed[(name, "COMPLEMENT")]
            control = next(row for row in metrics if row["model"] == "REGIME_HGB" and row["dimension"] == "overall")
            eligible = {row["fold"] for row in routing["folds"] if row["selectedNames"]}
            conditions.update(targetRegimeImproves=bool(candidate["observations"] and candidate["logLoss"] < base["logLoss"]),
                complementNoPointEstimateHarm=bool(cc["observations"] and cc["logLoss"] <= cb["logLoss"] and cc["brier"] <= cb["brier"]),
                multipleEligibleFutureFoldsImprove=sum(int(row["group"]) in eligible and row["deltaLogLossVsV18"] < 0 for row in folds) >= 2,
                beatsGlobalRegimeIndicatorControl=overall["logLoss"] < control["logLoss"] and overall["brier"] <= control["brier"])
        records.append({"model": name, "conditions": conditions, "passesDevelopmentResearchRule": all(conditions.values()),
            "logLoss": overall["logLoss"], "brier": overall["brier"], "deltaLogLoss": overall["deltaLogLossVsV18"],
            "improvingFolds": sum(row["deltaLogLossVsV18"] < 0 for row in folds)})
    return {"schemaVersion": "MLB_V19_PREDECLARED_DEVELOPMENT_DECISION_V1", "candidates": records,
        "recommendationAuthority": "RESEARCH_ONLY_NOT_PROSPECTIVE_SOURCE_READINESS_OR_PROMOTION",
        "finalOotRecommendation": "REMAIN_SEALED", "retainedModel": "V18", "wageringAuthority": False}


def main(replicates):
    require_v19_launch_authority("META_FIT_AND_EVALUATION")
    meta, raw, oof = load_safe_cache()
    # Make the chronological concatenation explicit and reject hidden permutations.
    if not oof.foldNumber.is_monotonic_increasing:
        raise ValueError("Saved matched OOF rows are not in registered fold order")
    frame = join_teams(raw).set_index("canonicalPaId", drop=False).loc[oof.canonicalPaId].reset_index(drop=True)
    if not np.array_equal(frame.observedClassIndex, oof.observedClassIndex):
        raise ValueError("Matched raw/OOF target identity differs")
    baseline = oof[["probability_" + name for name in meta["targetOrder"]]].to_numpy()
    globals_only, labels, eligibility, authority = read_completed_global_folds(frame, baseline)
    globals_all = {"V18": baseline, **globals_only}
    with threadpool_limits(limits=4):
        raw_predictions, calibrated_predictions, receipts, models = fit_and_reproduce_meta(frame, globals_all, eligibility, authority)
    clusters = [name for name in labels.columns if name != "canonicalPaId"]
    frame = frame.merge(labels, on="canonicalPaId", how="left", validate="one_to_one", sort=False)
    if not np.array_equal(frame.canonicalPaId, oof.canonicalPaId):
        raise ValueError("Evaluation labels changed matched row ordering")
    selected_regimes = sorted({name for record in eligibility.values() for name in record["selected"]})
    evaluation_directory = OUT / "evaluation"
    evaluation_directory.mkdir(parents=True, exist_ok=True)
    outputs = {}
    evaluation_authority = {"baselineReceiptSha256": BASE_SHA, "globalAuthorities": authority,
        "metaFoldCompletions": receipts, "bootstrapReplicates": replicates,
        "orderedTargetClasses": meta["targetOrder"], "observations": len(frame),
        "evaluatorCode": ref(ROOT / "server/sports_current_statcast/mlb_v19_evaluation.py"),
        "metaCode": ref(ROOT / "server/sports_current_statcast/mlb_v19_meta.py")}
    for scale, predictions in (("raw", raw_predictions), ("calibrated", calibrated_predictions)):
        path = evaluation_directory / (scale + "-evaluation.json")
        if path.exists():
            evaluation = json.loads(path.read_text())
            if evaluation.get("inputAuthority") != evaluation_authority or evaluation.get("probabilityScale") != scale:
                raise ValueError("Existing evaluation authority differs; preserve it and require explicit versioned recovery")
            emit("EVALUATION_REUSED", scale=scale)
        else:
            emit("MATCHED_EVALUATION_STARTED", scale=scale, rows=len(frame), models=len(predictions))
            evaluation = evaluate_predictions(frame, predictions, cluster_columns=clusters,
                interval_regimes=selected_regimes, replicates=replicates)
            evaluation.update(inputAuthority=evaluation_authority, probabilityScale=scale)
            write_json(path, evaluation)
            emit("MATCHED_EVALUATION_COMPLETED", scale=scale, rows=len(frame), models=len(predictions))
        outputs[scale] = ref(path)
        if scale == "calibrated":
            calibrated_evaluation = evaluation
    routing = specialist_routing_report(frame, calibrated_predictions, models, replicates, raw_baseline=raw_predictions["V18"])
    outputs["actualSpecialistRouting"] = write_json(evaluation_directory / "actual-specialist-routing.json", routing)
    y = frame.observedClassIndex.to_numpy(dtype=int)
    cluster_comparison = {scale: paired_uncertainty(frame, y, predictions["REGIME_HGB"], predictions["REGIME_CLUSTER_HGB"],
        replicates=replicates) for scale, predictions in (("raw", raw_predictions), ("calibrated", calibrated_predictions))}
    outputs["incrementalClusterComparison"] = write_json(evaluation_directory / "incremental-cluster-comparison.json", cluster_comparison)
    outputs["developmentDecision"] = write_json(evaluation_directory / "development-decision.json", decision_report(calibrated_evaluation, routing))
    package = {"schemaVersion": "MLB_V19_MATCHED_STUDY_META_PACKAGE_V1", "baselineReceiptSha256": BASE_SHA,
        "declaration": ref(ROOT / "docs/MLB_V19_STUDY_DECLARATION_V1.md"),
        "orderedGlobalBranches": list(GLOBAL_ORDER), "orderedDerivedBranches": list(ENSEMBLE_NAMES),
        "targetOrder": meta["targetOrder"], "matchedRows": len(frame), "matchedGames": int(frame.canonicalGameId.nunique()),
        "globalAuthorities": authority, "metaFoldCompletions": receipts, "evaluationArtifacts": outputs,
        "classicalEstimatorFitsInThisPhase": 0, "actualMetaFits": sum(model.receipt["actualMetaFits"] for model in models.values()),
        "frozenPriorResultsPreserved": True, "finalOotPayloadBytesRead": 0, "providerCalls": 0,
        "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False,
        "executionAllowedInAISP": False, "code": [ref(Path(__file__)), ref(ROOT / "server/sports_current_statcast/mlb_v19_meta.py")]}
    final_ref = write_json(evaluation_directory / "meta-study-package.json", package)
    print(json.dumps(final_ref, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-replicates", type=int, default=500)
    args = parser.parse_args()
    if args.bootstrap_replicates < 200:
        raise ValueError("At least 200 descriptive bootstrap draws required")
    main(args.bootstrap_replicates)
