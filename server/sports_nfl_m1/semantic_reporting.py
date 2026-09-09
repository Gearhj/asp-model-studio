"""Post-fit evidence supplement; never fits or changes a completed model run."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost

from server.audit_assurance.canonical import canonical_json_bytes
from .semantic_lab import OUTPUT, SEED, BASELINE_ROOT, digest, immutable_json


def paired(candidate, reference, mask_ids, prefix):
    columns = [f"{prefix}_{value}_probability" for value in ("away", "tie", "home")]
    joined = candidate.loc[candidate.canonical_game_id.isin(mask_ids)].merge(reference, on="canonical_game_id", suffixes=("_candidate", "_reference"), validate="one_to_one")
    if joined.empty:
        return {"games": 0, "status": "NO_SUPPORTED_OBSERVATIONS"}
    truth = joined.outcome_class_candidate.to_numpy(int)
    reference_truth = joined.outcome_class_reference.to_numpy(int)
    if not np.array_equal(truth, reference_truth):
        raise ValueError("PAIRED_SUBGROUP_TRUTH_MISMATCH")
    pc = joined[[c + "_candidate" for c in columns]].to_numpy(float)
    pr = joined[[c + "_reference" for c in columns]].to_numpy(float)
    delta = -np.log(np.clip(pc[np.arange(len(joined)), truth], 1e-12, 1)) + np.log(np.clip(pr[np.arange(len(joined)), truth], 1e-12, 1))
    labels = joined.season_candidate.astype(str) + ":" + joined.week_candidate.astype(str)
    summaries = pd.DataFrame({"block": labels, "delta": delta}).groupby("block").delta.agg(["sum", "size"])
    if len(summaries) < 2:
        return {"games": len(joined), "blocks": len(summaries), "meanPairedLogLossDifference": float(delta.mean()), "status": "DESCRIPTIVE_INSUFFICIENT_TEMPORAL_BLOCKS"}
    choices = np.random.default_rng(SEED).integers(0, len(summaries), size=(1000, len(summaries)))
    sampled = summaries["sum"].to_numpy()[choices].sum(axis=1) / summaries["size"].to_numpy()[choices].sum(axis=1)
    return {"games": len(joined), "blocks": len(summaries), "meanPairedLogLossDifference": float(delta.mean()),
            "seasonWeekClusterBootstrap95Interval": np.quantile(sampled, [.025, .975]).tolist(), "resamples": 1000,
            "status": "EXPLORATORY_DEVELOPMENT_UNCERTAINTY" if len(summaries) >= 8 else "DESCRIPTIVE_FEW_BLOCKS_UNSTABLE_INTERVAL",
            "independentConfirmation": False, "selectedOnDevelopment": True}


def report():
    current = json.loads((OUTPUT / "CURRENT.json").read_text())
    path = Path(current["resultPath"])
    if digest(path) != current["resultSha256"]:
        raise ValueError("RESULT_POINTER_CHECKSUM_MISMATCH")
    result = json.loads(path.read_text())
    run = path.parent
    ledgers = {item["pipelineId"]: pd.read_parquet(item["oofPath"]) for item in result["results"]}
    # Reuse the earlier laboratory's immutable calibrated OOF, not a new fit.
    for name in ("M1_RECIPE_FOLD_REFIT", "HIST_GRADIENT_BOOSTING_B_T2"):
        ledger = ledgers[name]
        if "calibrated_home_probability" not in ledger:
            saved = pd.read_parquet(BASELINE_ROOT / "analysis" / "calibration" / name.lower() / "oof_predictions.parquet")
            aligned = ledger[["canonical_game_id", "raw_home_probability", "raw_tie_probability", "raw_away_probability", "outcome_class"]].merge(saved, on="canonical_game_id", suffixes=("_original", ""), validate="one_to_one")
            if len(aligned) != len(ledger) or any(not np.array_equal(aligned[column], aligned[column + "_original"]) for column in ("raw_home_probability", "raw_tie_probability", "raw_away_probability", "outcome_class")):
                raise ValueError("LEGACY_CALIBRATION_SOURCE_COHORT_MISMATCH")
            ledgers[name] = saved
    reference = ledgers["M1_RECIPE_FOLD_REFIT"]
    rows = []
    subgroup_results = {}
    branches = {}
    for item in result["results"]:
        name = item["pipelineId"]
        ledger = ledgers[name]
        details = [json.loads(p.read_text()) for p in sorted((run / name).glob("fold-*.json"))]
        counts = {key: sum(d.get("validationBranchCounts", {}).get(key, 0) for d in details) for key in ("prior_only_cells", "blended_cells", "source_unknown_cells", "unresolved_native_missing_cells")}
        branches[name] = counts
        expanded = sorted({d["expandedColumns"] for d in details if "expandedColumns" in d})
        rows.append({"pipelineId": name, "sourceFeatureCount": 197 if item["design"] == "LEGACY_MEDIAN_BASELINE" else 197 + (12 if item["design"] in {"C2", "C3"} else 0),
                     "selectedInputCount": 197 if item["design"] == "LEGACY_MEDIAN_BASELINE" else 196 + (12 if item["design"] in {"C2", "C3"} else 0),
                     "expandedColumnCountsByFold": expanded, "definitions": {"C1": "196registeredinputs after roof exclusion; continuous game priors and exposure/uncertainty states", "C2": "C1 plus12strictly-lagged passing-personnel mixture features", "C3": "C2 with fold-local simple exposure/experience peer pooling"}.get(item["design"], item["design"]),
                     "metrics": item["metrics"], "subgroups": item["subgroups"], "oofPath": item["oofPath"], "oofSha256": digest(Path(item["oofPath"]))})
        masks = {"WEEKS_1_4": ledger.week.astype(int).le(4), "WEEKS_1_2": ledger.week.astype(int).le(2)}
        if "home_lagged_low_exposure" in ledger:
            masks["LAGGED_PERSONNEL_LT100_EFFECTIVE_PLAYS_NOT_ACTUAL_ROOKIE"] = ledger.home_lagged_low_exposure.eq(1) | ledger.away_lagged_low_exposure.eq(1)
        subgroup_results[name] = {}
        for group, mask in masks.items():
            ids = ledger.loc[mask, "canonical_game_id"]
            subgroup_results[name][group] = {prefix: paired(ledger, reference, ids, prefix) for prefix in ("raw", "calibrated") if all(f"{prefix}_home_probability" in frame for frame in (ledger, reference))}
    artifacts = [{"label": "Frozen candidate matrix", "path": str(OUTPUT / "candidate-matrix.json"), "sha256": digest(OUTPUT / "candidate-matrix.json")},
                 {"label": "Complete immutable run result", "path": str(path), "sha256": digest(path)},
                 {"label": "Feature policy used by this fitted run", "path": str(run / "feature-treatment-policy.json"), "sha256": digest(run / "feature-treatment-policy.json")},
                 {"label": "Exact estimator fit accounting", "path": str(run / "fit-accounting.jsonl"), "sha256": digest(run / "fit-accounting.jsonl")}]
    for item in result["fittedArtifacts"]:
        artifacts.append({"label": item["pipelineId"] + " complete frozen model system", "path": item["path"], "sha256": item["sha256"]})
    payload = {"contract": "NFL_SEMANTIC_REPORTING_SUPPLEMENT_V1", "parentResultSha256": current["resultSha256"], "modelFitsOccurred": False,
               "rows": rows, "validationBranchCounts": branches, "subgroupPairedAgainstM1": subgroup_results, "artifacts": artifacts,
               "actualStarterSubgroups": {key: "UNSUPPORTED_NO_DEFENSIBLE_PREGAME_IDENTITY" for key in ("rookie", "changed_starter", "backup", "current_team_change")},
               "uncertaintyInterpretation": "Season/week resampling on exact same games. Development-selected comparisons, no independent superiority proof. <8blocks marked unstable descriptive.",
               "calibrationAccounting": {"completedChronologicalCalibrationFits": sum(sum(f["status"] == "CALIBRATED" for f in item.get("calibration", {}).get("folds", [])) for item in result["results"]),
                                         "note": "Completed calibration receipts, not independently instrumented fit-start events. Core fit-accounting logs score estimator starts/completions separately."},
               "runtimeVersions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scikitLearn": sklearn.__version__, "xgboost": xgboost.__version__},
               "effectAttribution": "C1 versus legacy is a semantic treatment package comparison, including roof exclusion and expanded uncertainty/state columns; not isolated causal benefit of a prior. C2-minusC1 isolates added lagged-passing information within a fixed family; C3-minusC2 changes peer pooling. Raw-versus-calibrated comparison changes probability calibration only, not the raw joint score distribution.",
               "researchOnly": True, "wageringAuthority": False}
    sha = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    target = OUTPUT / "reporting" / "sha256" / sha / "supplement.json"
    immutable_json(target, payload)
    (OUTPUT / "reporting" / "CURRENT.json").write_bytes(canonical_json_bytes({"contract": "NFL_SEMANTIC_REPORTING_CURRENT_V1", "status": "COMPLETED", "supplementPath": str(target), "supplementSha256": sha, "parentResultSha256": current["resultSha256"]}))
    return {"path": str(target), "sha256": sha}


if __name__ == "__main__":
    print(json.dumps(report()))
