"""Execute the predeclared, bounded starter-duration study on reconciled local data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_starter_survival_models import (
    EmpiricalHazard, LearnedHazard, PREGAME_FIELDS, CONDITIONAL_FIELDS, ENDPOINTS,
    target_codes, losses, history_strata, pregame_bf_distribution, duration_metrics,
)
from server.sports_current_statcast.mlb_v18_whole_game_challenger import starter_removal_probability

OUT = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/duration-study"
DECLARATION = ROOT / "docs/MLB_STARTER_SURVIVAL_HIERARCHY_DECLARATION_V1.json"
DECLARATION_SHA = "51b886ecb20137ea7e8ab0ce1abb8601c3f86df0dfe77dae95d07d8ca01bcc9d"


def descriptor(path):
    path = Path(path).resolve()
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def save(name, data):
    digest = hashlib.sha256(data).hexdigest()
    path = OUT / "objects/sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable artifact collision")
    else:
        with path.open("xb") as handle:
            handle.write(data)
    return descriptor(path)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str) + "\n").encode()


def parquet(frame):
    stream = io.BytesIO()
    frame.to_parquet(stream, index=False)
    return stream.getvalue()


def summarize_metrics(frame, model, scale):
    result = {"model": model, "evaluation": scale, "starts": int(frame.startId.nunique()), "games": int(frame.gameId.nunique())}
    for column in frame.select_dtypes(include=["number", "bool"]).columns:
        if column not in {"realizedBf", "realizedOuts"}:
            result[column] = float(frame[column].mean())
    return result


def paired_interval(frame, metric, candidate, reference):
    pivot = frame.pivot(index=["gameId", "startId"], columns="model", values=metric).dropna(subset=[candidate, reference])
    difference = pivot[candidate] - pivot[reference]
    games = difference.groupby(level=0).agg(["sum", "count"])
    rng = np.random.default_rng(20260912)
    indices = rng.integers(0, len(games), size=(500, len(games)))
    means = games["sum"].to_numpy()[indices].sum(1) / games["count"].to_numpy()[indices].sum(1)
    return {"metric": metric, "candidate": candidate, "reference": reference,
            "differenceCandidateMinusReference": float(difference.mean()),
            "ci95": np.quantile(means, [0.025, 0.975]).tolist(), "games": len(games), "starts": len(pivot),
            "resampling": "500_PAIRED_WHOLE_GAME_CLUSTER_BOOTSTRAPS_DESCRIPTIVE"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--risk", required=True)
    parser.add_argument("--starts", required=True)
    parser.add_argument("--data-manifest", required=True)
    parser.add_argument("--data-manifest-sha256", required=True)
    args = parser.parse_args()
    if descriptor(DECLARATION)["sha256"] != DECLARATION_SHA:
        raise ValueError("The pre-fit declaration changed")
    manifest_ref = descriptor(args.data_manifest)
    if manifest_ref["sha256"] != args.data_manifest_sha256:
        raise ValueError("Data manifest mismatch")
    data_manifest = json.loads(Path(args.data_manifest).read_text(encoding="utf-8"))
    # Both inputs are freshly constructed physically separate Development-only outputs.
    for path, name in ((Path(args.risk).resolve(), "risk.parquet"), (Path(args.starts).resolve(), "starts.parquet")):
        if not path.is_relative_to(ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/duration-data"):
            raise ValueError("Only the new isolated duration data is allowed")
        actual, expected = descriptor(path), data_manifest["artifacts"][name]
        if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
            raise ValueError("Risk/start bytes not bound to declared data manifest")
    risk, starts = pd.read_parquet(args.risk), pd.read_parquet(args.starts)
    if not risk.gameDate.between("2023-01-01", "2024-10-31").all() or not starts.gameDate.between("2023-01-01", "2024-10-31").all():
        raise ValueError("Non-Development or mixed-file dates")
    if starts.startId.duplicated().any() or risk.duplicated(["startId", "bf"]).any():
        raise ValueError("Ambiguous risk-set or stint identity")
    all_start_count = len(starts)
    starts = starts.loc[starts.eligible.eq(True)].reset_index(drop=True)
    if set(risk.startId) != set(starts.startId):
        raise ValueError("Risk/start cohort mismatch")
    history_date = risk.latestHistoryCompletionDate
    if (history_date.notna() & (history_date >= risk.gameDate)).any():
        raise ValueError("Future/same-day pregame history")
    indexed_starts = starts.set_index("startId")
    for start_id, frame in risk.groupby("startId", sort=False):
        frame = frame.sort_values("bf")
        stint = indexed_starts.loc[start_id]
        if (frame.bf.tolist() != list(range(1, int(stint.realizedBf) + 1))
                or frame.iloc[-1].endpoint != stint.endpoint
                or stint.endpoint not in {"REMOVAL", "GAME_END"}
                or not frame.iloc[:-1].endpoint.eq("CONTINUE").all()
                or not frame.gameId.eq(stint.gameId).all()):
            raise ValueError("Noncontiguous BF, mismatched terminal endpoint or game identity")
    y = target_codes(risk.endpoint)
    train = risk.gameDate < "2024-01-01"
    calibration = risk.gameDate.between("2024-01-01", "2024-06-30")
    test = risk.gameDate >= "2024-07-01"
    train_frame, cal_frame, test_frame = [risk.loc[m].reset_index(drop=True) for m in (train, calibration, test)]
    test_starts = starts.loc[starts.gameDate >= "2024-07-01"].reset_index(drop=True)
    if any(frame.empty for frame in (train_frame, cal_frame, test_frame, test_starts)):
        raise ValueError("A predeclared temporal window is empty")
    fields = tuple(name for name in PREGAME_FIELDS if name in risk and train_frame[name].notna().any())
    conditional = fields + tuple(name for name in CONDITIONAL_FIELDS if name in risk and train_frame[name].notna().any())
    cohort = {"schemaVersion": "MLB_DURATION_EXECUTION_COHORT_V1", "declaredBeforeModelFitting": True,
              "declaration": descriptor(DECLARATION), "dataManifest": manifest_ref,
              "risk": descriptor(args.risk), "starts": descriptor(args.starts),
              "allAccountedStarts": all_start_count, "excludedStarts": all_start_count - len(starts),
              "windows": {name: {"riskRows": len(frame), "starts": int(frame.startId.nunique()), "games": int(frame.gameId.nunique()),
                        "firstDate": frame.gameDate.min(), "lastDate": frame.gameDate.max()}
                        for name, frame in zip(("training", "calibration", "test"), (train_frame, cal_frame, test_frame))},
              "pregameFeatures": fields, "conditionalFeatures": conditional,
              "omittedUnavailableFields": [name for name in PREGAME_FIELDS + CONDITIONAL_FIELDS if name not in conditional],
              "code": [descriptor(Path(__file__)), descriptor(ROOT / "server/sports_current_statcast/mlb_starter_survival_models.py")]}
    cohort_ref = save("execution-cohort.json", json_bytes(cohort))
    model_specs = [EmpiricalHazard(feature_order=fields), LearnedHazard("LOGISTIC_PREGAME", fields),
                   LearnedHazard("LOGISTIC_CONDITIONAL", conditional), LearnedHazard("HGB_PREGAME", fields)]
    artifacts, calibration_selection, summary, telemetry, predictions, duration_frames, path_frames = [], [], [], [], [], [], []
    distribution_references = []
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=4):
        for model in model_specs:
            stage = time.perf_counter()
            print(json.dumps({"event": "FIT_START", "model": model.model_id, "rows": len(train_frame), "atUtc": datetime.now(timezone.utc).isoformat(), "cohort": cohort_ref["sha256"]}), flush=True)
            model.fit(train_frame, train_frame.endpoint)
            print(json.dumps({"event": "FIT_COMPLETE", "model": model.model_id, "seconds": time.perf_counter() - stage}), flush=True)
            cal_raw = model.predict_proba(cal_frame, calibrated=False)
            cal_nll = losses(cal_raw, target_codes(cal_frame.endpoint))[0]
            per_start = pd.Series(cal_nll).groupby(cal_frame.startId).sum()
            calibration_selection.append({"model": model.model_id, "rawMeanStartPathNll": float(per_start.mean())})
            calibration_result = None
            if isinstance(model, LearnedHazard):
                calibration_result = model.fit_temperature(cal_frame, cal_frame.endpoint)
            model.metadata = {"cohort": cohort_ref, "trainingCutoffExclusive": "2024-01-01",
                              "calibrationCutoffExclusive": "2024-07-01", "endpoints": ENDPOINTS,
                              "featureOrder": model.feature_order, "calibration": calibration_result,
                              "dependencies": {"python": sys.version, "numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__, "joblib": joblib.__version__},
                              "sourceUse": "LOCAL_RESEARCH_RETROSPECTIVE_COMPLETED_GAME_RECONSTRUCTION",
                              "notOptimalManagerPolicy": True, "v18Unchanged": True}
            fixture = cal_frame.head(64).copy()
            expected = model.predict_proba(fixture)
            buffer = io.BytesIO()
            joblib.dump(model, buffer, compress=3)
            artifact = save("fitted-hazard.joblib", buffer.getvalue())
            reloaded = joblib.load(artifact["path"])
            actual = reloaded.predict_proba(fixture)
            if not np.array_equal(actual, expected):
                raise ValueError("Fitted hazard reload mismatch")
            fixture_ref = save("reload-inputs.parquet", parquet(fixture))
            expected_ref = save("reload-probabilities.parquet", parquet(pd.DataFrame(expected, columns=ENDPOINTS)))
            artifacts.append({"model": model.model_id, "artifact": artifact, "fixture": fixture_ref,
                              "expected": expected_ref, "reloadExact": True, "calibration": calibration_result,
                              "featureOrder": model.feature_order})
            telemetry.append({"model": model.model_id, "fitStarted": True, "fitCompleted": True,
                              "fitType": "EMPIRICAL_FREQUENCIES" if isinstance(model, EmpiricalHazard) else "ESTIMATOR_FIT",
                              "calibrationFitCompleted": calibration_result is not None,
                              "fitCalibrationAndReloadSeconds": time.perf_counter() - stage})
        selected = min((row for row in calibration_selection if row["model"] in ("LOGISTIC_PREGAME", "HGB_PREGAME")), key=lambda r: r["rawMeanStartPathNll"])["model"]
        selection_ref = save("earlier-window-selection.json", json_bytes({"selected": selected,
            "criterion": "EARLIER_CALIBRATION_RAW_START_PATH_NLL", "scores": calibration_selection,
            "cohort": cohort_ref, "savedBeforeTestPredictionOrScoring": True}))
        for model in model_specs:
            for calibrated in ([False, True] if isinstance(model, LearnedHazard) else [True]):
                label = model.model_id + ("_CAL" if calibrated else "_RAW")
                probs = model.predict_proba(test_frame, calibrated=calibrated)
                nll, brier = losses(probs, target_codes(test_frame.endpoint))
                pred = test_frame[["startId", "gameId", "gameDate", "bf", "endpoint"]].copy()
                pred["model"] = label
                pred[list(ENDPOINTS)] = probs
                pred["nll"], pred["brier"] = nll, brier
                predictions.append(pred)
                paths = pred.groupby(["gameId", "startId", "gameDate"], as_index=False).agg(pathNll=("nll", "sum"), boundaryNll=("nll", "mean"), boundaryBrier=("brier", "mean"))
                paths["model"] = label
                path_frames.append(paths)
                summary.append(summarize_metrics(paths.drop(columns="model"), label,
                    "CONDITIONAL_IN_GAME_DURATION" if "CONDITIONAL" in label else "REDUCED_STATE_HAZARD_LIKELIHOOD"))
                if "CONDITIONAL" not in label:
                    law = pregame_bf_distribution(model, test_starts, calibrated=calibrated)
                    metrics = duration_metrics(law, test_starts.realizedBf)
                    duration = test_starts[["startId", "gameId", "gameDate", "realizedBf", "realizedOuts"]].copy()
                    duration["historyStratum"] = history_strata(test_starts)
                    duration["model"] = label
                    for key, values in metrics.items():
                        duration[key] = values
                    duration_frames.append(duration)
                    summary.append(summarize_metrics(duration.drop(columns="model"), label, "PREGAME_DURATION_REDUCED_BF_STATE"))
                    distribution_ref = save("test-duration-distributions.parquet", parquet(pd.DataFrame({"startId": np.repeat(test_starts.startId.to_numpy(), 100),
                        "bf": np.tile(np.arange(1, 101), len(test_starts)), "probability": law["pmf"].reshape(-1),
                        "removalMass": law["causeMass"][:, :, 0].reshape(-1), "gameEndMass": law["causeMass"][:, :, 1].reshape(-1)})))
                    distribution_references.append({"model": label, "artifact": distribution_ref})
        warning_text = sorted(set(str(w.message) for w in captured))
    pred = pd.concat(predictions, ignore_index=True)
    duration = pd.concat(duration_frames, ignore_index=True)
    paths = pd.concat(path_frames, ignore_index=True)
    # Exact existing hook uses the next pitching opportunity inning, not later offensive scoring.
    hook = starter_removal_probability(test_frame.nextPitchInning.to_numpy(), test_frame.bf.to_numpy(),
                                       test_frame.runsAllowedSoFar.to_numpy(), test_frame.bf.to_numpy() // 9 + 1)
    opportunities = test_frame.endpoint != "GAME_END"
    hook_scores = []
    actual_removal = (test_frame.endpoint == "REMOVAL").to_numpy()[opportunities]
    for label in ["CURRENT_MECHANISM"] + pred.model.unique().tolist():
        if label == "CURRENT_MECHANISM":
            p = hook[opportunities]
        else:
            matching = pred[pred.model == label]
            p = (matching.REMOVAL / (matching.REMOVAL + matching.CONTINUE)).to_numpy()[opportunities]
        ll = -(actual_removal * np.log(np.clip(p, 1e-12, 1)) + (1 - actual_removal) * np.log(np.clip(1-p, 1e-12, 1)))
        hook_scores.append({"model": label, "evaluation": "NON_GAME_END_OPPORTUNITY_CONDITIONAL_DIAGNOSTIC",
                            "rows": int(opportunities.sum()), "games": int(test_frame.loc[opportunities, "gameId"].nunique()),
                            "logLoss": float(ll.mean()), "brier": float(np.mean((p - actual_removal) ** 2)),
                            "observedRemovalRate": float(actual_removal.mean()), "predictedRemovalRate": float(p.mean())})
    intervals = [paired_interval(paths, "pathNll", label, "EMPIRICAL_POOLED_CAL") for label in paths.model.unique() if label != "EMPIRICAL_POOLED_CAL"]
    intervals += [paired_interval(duration, metric, selected + "_CAL", "EMPIRICAL_POOLED_CAL") for metric in ("bfCappedMeanAbsoluteError", "bfCrpsThrough100", "bfNll")]
    strata = []
    duration["quarter"] = pd.to_datetime(duration.gameDate).dt.to_period("Q").astype(str)
    for group_field in ("historyStratum", "quarter"):
        for (model, group), frame in duration.groupby(["model", group_field]):
            strata.append(dict(summarize_metrics(frame.drop(columns="model"), model, "PREGAME_DURATION_REDUCED_BF_STATE"), groupField=group_field, group=group))
    references = {"riskPredictions": save("heldout-risk-predictions.parquet", parquet(pred)),
                  "durationPredictions": save("heldout-duration-predictions.parquet", parquet(duration)),
                  "pathScores": save("heldout-path-scores.parquet", parquet(paths))}
    result = {"schemaVersion": "MLB_STARTER_DURATION_RESEARCH_RESULT_V1", "cohort": cohort_ref,
              "status": "COMPONENT_ONLY_GAME_VALIDATION_NOT_ESTABLISHED", "models": artifacts,
              "selectionEarlierCalibrationOnly": calibration_selection, "selectedDeployableCandidate": selected,
              "preTestSelectionReceipt": selection_ref,
              "metrics": summary, "currentMechanismComparison": hook_scores, "pairedIntervals": intervals,
              "subgroups": strata, "predictionArtifacts": references, "telemetry": telemetry,
              "durationDistributionArtifacts": distribution_references,
              "runtimeSeconds": time.perf_counter() - started, "warnings": warning_text,
              "durationScoreSupport": {"maximumIntegratedBf": 100, "unresolvedTailMaximum": float(duration.unresolvedTail.max()),
                  "pointMean": "E[min(BF,101)], a lower bound on unrestricted mean, not a removal at101",
                  "crps": "Discrete cumulative-probability score throughBF100 only",
                  "quantiles": "Quantiles beyond100 are represented by lower bound101; interval widths are lower bounds in those cases"},
              "limitations": ["Complete-case historical reconstruction, not archival pregame vintages", "BF>=1 supported starter estimand; unknown observations excluded without IPCW", "BF-only pregame reduced-state process is not full-game propagation or an outs distribution", "Current mechanism diagnostic conditions on a non-game-end opportunity and is not a standalone competing-risk path or pregame duration comparison", "No fitted candidate promotion or optimal managerial policy claim"],
              "boundaries": {"v18Fits": 0, "providerCalls": 0, "costUsd": 0, "aispWrites": 0, "finalOotReads": 0, "fullGameSimulations": 0}}
    reference = save("duration-results.json", json_bytes(result))
    print(json.dumps({"result": reference, "selected": selected, "metrics": summary, "hookDiagnostic": hook_scores}), flush=True)


if __name__ == "__main__":
    main()
