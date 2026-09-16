"""Twenty-game V19 oracle-mechanics comparison, never a pregame skill backtest.

Run only after all global/meta folds and matched PA evaluation are complete.
The process-local observer delegates to the accepted simulator unchanged, saves
its actual populations and computes empirical CRPS without a second simulation.
No fitted estimator, transition fit, provider, AISP or OOT source is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast import mlb_regime_simulation as simulation
from server.sports_current_statcast.mlb_regime_baseline import sha_file
from server.sports_current_statcast.mlb_v19_evaluation import compare_game_mechanics

OUT = ROOT / "outputs/mlb-v19-current-state-specialists-v1"
BASE = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/baseline-reproduction-0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9.json"
BASE_SHA = "0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9"
TRUTH = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/game-context/sha256/90dc14c30b5c0b0279730ce716af13e6d3fd23527c36289c3778e8286ee77c02/game-context.parquet"
TRUTH_SHA = "1c694e7b8bf185e6fd7366461295290c15a406fb8f527d725e4fbb6d08313adf"
CANDIDATES = ("SEMANTIC_HGB", "SEMANTIC_EXTRA_TREES", "REGIME_HGB", "REGIME_CLUSTER_HGB", "GLOBAL_ENSEMBLE", "SPECIALIST_MIXTURE")
N_SIMS = 500
N_GAMES = 20
TRACK = "ORACLE_MECHANICS_SENSITIVITY_NONPREGAME"


def ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha_file(path), "bytes": path.stat().st_size}


def verified(entry: dict, *, allowed_root: Path = OUT) -> Path:
    path = Path(entry["path"]).resolve()
    if not path.is_relative_to(allowed_root.resolve()):
        raise ValueError("Unexpected source authority root")
    if path.stat().st_size != entry.get("bytes", entry.get("byteCount")) or sha_file(path) != entry["sha256"]:
        raise ValueError("Source bytes or checksum differ")
    return path


def put(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable game-comparison artifact conflict")
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def empirical_crps(draws: np.ndarray, observed: float) -> float:
    """Exact empirical E|X-y| - 0.5 E|X-X'|; no bins/smoothing or refitting."""
    values = np.sort(np.asarray(draws, dtype=float))
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or not np.isfinite(observed):
        raise ValueError("Finite population and observed score required for empirical CRPS")
    n = len(values)
    pair_half = np.dot(2 * np.arange(1, n + 1) - n - 1, values) / n ** 2
    score = float(np.mean(np.abs(values - observed)) - pair_half)
    if score < -1e-12:
        raise ValueError("Empirical CRPS cannot be negative")
    return max(score, 0.)


def completed_meta_authority() -> tuple[dict, dict, dict]:
    package_path = OUT / "evaluation/meta-study-package.json"
    if not package_path.is_file():
        raise ValueError("META_AND_MATCHED_PA_EVALUATION_NOT_COMPLETED; no simulation launched")
    package = json.loads(package_path.read_bytes())
    if (package.get("schemaVersion") != "MLB_V19_MATCHED_STUDY_META_PACKAGE_V1"
            or package.get("matchedRows") != 494432 or package.get("matchedGames") != 6570
            or package.get("finalOotPayloadBytesRead") != 0
            or package.get("wageringAuthority") is not False or package.get("executionAllowedInAISP") is not False):
        raise ValueError("Matched Development meta-package authority differs")
    global_folds, meta_folds, fold5 = set(), set(), None
    for item in package.get("globalAuthorities", []):
        complete = json.loads(verified(item["globalCompletion"]).read_bytes())
        number = complete.get("fold")
        if number not in range(1, 6) or number in global_folds or complete.get("globalFitsCompleted") != 4:
            raise ValueError("Twenty global fits across the five original folds must be completed")
        global_folds.add(number)
    for item in package.get("metaFoldCompletions", []):
        complete = json.loads(verified(item).read_bytes())
        number = complete.get("fold")
        if (number not in range(1, 6) or number in meta_folds or complete.get("reloadMismatchCount") != 0
                or complete.get("fullFoldReloadComparedRows") != complete.get("validationRows")
                or complete.get("outcomeAndRealizedContextGateInvariance") is not True
                or complete.get("noFinalOotPayloadRead") is not True):
            raise ValueError("Complete, exact meta-fold replay and pregame routing verification required")
        meta_folds.add(number)
        if number == 5:
            fold5 = complete
    if global_folds != set(range(1, 6)) or meta_folds != set(range(1, 6)):
        raise ValueError("Global/meta study is incomplete; no simulation launched")
    required = {"raw", "calibrated", "actualSpecialistRouting", "incrementalClusterComparison", "developmentDecision"}
    if required - set(package.get("evaluationArtifacts", {})):
        raise ValueError("Final matched PA comparison is incomplete; no simulation launched")
    for item in package["evaluationArtifacts"].values():
        verified(item)
    return package, ref(package_path), fold5


def run(candidate: str, scale: str, disposition: str) -> dict:
    package, package_ref, fold5 = completed_meta_authority()
    if candidate not in CANDIDATES or scale not in {"raw", "calibrated"}:
        raise ValueError("A saved V19 branch and explicit equivalent probability scale are required")
    request = {"schemaVersion": "MLB_V19_ORACLE_MECHANICS_REQUEST_V1", "evidenceTrack": TRACK,
               "candidate": candidate, "probabilityScale": scale, "selectionDisposition": disposition,
               "retainedOfficialModel": "V18", "games": N_GAMES, "simulationsPerBranchPerGame": N_SIMS,
               "masterSeed": 20260910, "metaPackage": package_ref, "scoreSource": {"path": str(TRUTH), "sha256": TRUTH_SHA},
               "gameSelection": "EXACT_TWENTY_PREVIOUSLY_DECLARED_DATE_ID_GAMES_WITH_SAVED_SCORE_DIAGNOSTICS",
               "runner": ref(Path(__file__)), "simulationImplementation": ref(Path(simulation.__file__)),
               "finalOotPayloadBytesRead": 0, "modelFits": 0, "providerCalls": 0}
    request_bytes = canonical_json_bytes(request)
    request_sha = hashlib.sha256(request_bytes).hexdigest()
    receipt_path = OUT / f"game-comparison/requests/sha256/{request_sha}/receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_bytes())
        if receipt["requestSha256"] != request_sha:
            raise ValueError("Existing request receipt differs")
        for entry in receipt["files"].values():
            verified(entry)
        return {**receipt, "status": "REUSED_WITHOUT_SIMULATION", "simulatorCallsThisInvocation": 0}
    if sha_file(BASE) != BASE_SHA or sha_file(TRUTH) != TRUTH_SHA:
        raise ValueError("Original physically safe baseline or game-score authority differs")
    baseline = json.loads(BASE.read_bytes())
    raw_path = verified(baseline["artifacts"]["rawDevelopment"], allowed_root=BASE.parent)
    oof_path = verified(baseline["artifacts"]["matchedOof"], allowed_root=BASE.parent)
    truths = pd.read_parquet(TRUTH, columns=["canonicalGameId", "game_date", "actualAway", "actualHome", "scoreAuthority"])
    truths = truths.dropna(subset=["actualAway", "actualHome"]).sort_values(["game_date", "canonicalGameId"], kind="stable").reset_index(drop=True)
    if (len(truths) != N_GAMES or truths.canonicalGameId.duplicated().any()
            or set(truths.game_date.astype(str)) != {"2026-05-02", "2026-05-03"}
            or not truths.scoreAuthority.eq("FINAL_GAME_LAST_ORDERED_RAW_PITCH_POST_SCORE_DIAGNOSTIC").all()):
        raise ValueError("The exact original twenty score-diagnostic games differ")
    oof = pd.read_parquet(oof_path, columns=["canonicalPaId", "canonicalGameId", "game_date", "foldNumber"])
    oof = oof[oof.foldNumber.eq(5)].reset_index(drop=True)
    if len(oof) != 94157:
        raise ValueError("Frozen fold-five matched observation count differs")
    inputs = pd.read_parquet(raw_path, columns=["canonicalPaId", "canonicalGameId", "game_date", "foldNumber", "context_top_bottom"])
    frame = inputs.set_index("canonicalPaId", drop=False).loc[oof.canonicalPaId].reset_index(drop=True)
    if (not np.array_equal(frame.canonicalGameId, oof.canonicalGameId)
            or not frame.game_date.astype(str).between("2026-05-02", "2026-08-06").all()):
        raise ValueError("Fold-five PA identity, order or Development date differs")
    predictions_ref = next(item for item in fold5["artifacts"] if Path(item["path"]).name == scale + "-predictions.joblib")
    predictions = joblib.load(verified(predictions_ref))
    for name in ("V18", candidate):
        if np.asarray(predictions[name]).shape != (len(frame), 8):
            raise ValueError("Saved matched probability shape differs")
    wanted = frame.canonicalGameId.isin(truths.canonicalGameId).to_numpy()
    frame = frame.loc[wanted].reset_index(drop=True)
    p_base, p_candidate = predictions["V18"][wanted], predictions[candidate][wanted]
    transition, transition_ref = simulation.load_accepted_transition(ROOT)
    populations = {}
    calls = {}
    original_simulate = simulation.simulate_game

    def observe_population(*args, **kwargs):
        if kwargs.get("n_sims") != N_SIMS:
            raise ValueError("The declared simulation bound changed")
        result = original_simulate(*args, **kwargs)
        game = str(kwargs["game_id"])
        occurrence = calls.get(game, 0)
        if game not in set(truths.canonicalGameId) or occurrence > 1:
            raise ValueError("Unexpected game or repeated population simulation")
        branch = "baseline" if occurrence == 0 else "challenger"
        calls[game] = occurrence + 1
        populations[(game, branch)] = {name: np.asarray(getattr(result, name), dtype="<i8").copy()
                                       for name in ("away_runs", "home_runs", "innings", "pa_counts")}
        return result

    # A local observation hook only: original arguments/results/RNG pass through
    # unchanged. No imported source file, scheduled process or model is modified.
    with patch.object(simulation, "simulate_game", observe_population):
        comparison = compare_game_mechanics(frame, p_base, p_candidate, transition_model=transition,
            transition_training_end=transition_ref["trainingEnd"], transition_model_sha256=transition_ref["sha256"],
            game_truth=truths[["canonicalGameId", "actualAway", "actualHome"]], n_sims=N_SIMS, maximum_games=N_GAMES)
    if comparison["completedGames"] != N_GAMES or comparison["evidenceTrack"] != TRACK or len(populations) != N_GAMES * 2:
        raise ValueError("All twenty exact paired game populations must complete")
    observed = truths.set_index("canonicalGameId")
    arrays, crps = {}, []
    for index, game in enumerate(comparison["games"]):
        game_id = game["canonicalGameId"]
        truth = observed.loc[game_id]
        actual = {"away": float(truth.actualAway), "home": float(truth.actualHome),
                  "margin": float(truth.actualHome - truth.actualAway), "total": float(truth.actualHome + truth.actualAway)}
        for branch in ("baseline", "challenger"):
            population = populations[(game_id, branch)]
            digest = hashlib.sha256()
            for name, values in population.items():
                digest.update(values.tobytes(order="C"))
                arrays[f"game_{index:02d}_{branch}_{name}"] = values
            if digest.hexdigest() != game[branch]["simulationArraySha256"]:
                raise ValueError("Observed populations do not reproduce the accepted helper's exact array hash")
            draws = {"away": population["away_runs"], "home": population["home_runs"],
                     "margin": population["home_runs"] - population["away_runs"],
                     "total": population["home_runs"] + population["away_runs"]}
            scores = {name: empirical_crps(value, actual[name]) for name, value in draws.items()}
            game[branch]["empiricalCRPS"] = scores
            crps.append({"canonicalGameId": game_id, "branch": branch, **scores})
    arrays["canonical_game_ids"] = np.asarray([row["canonicalGameId"] for row in comparison["games"]], dtype="U128")
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    population_bytes = buffer.getvalue()
    with np.load(io.BytesIO(population_bytes), allow_pickle=False) as restored:
        if any(not np.array_equal(restored[name], value) for name, value in arrays.items()):
            raise ValueError("Saved population reload differs")
    comparison.update({"schemaVersion": "MLB_V19_ORACLE_GAME_COMPARISON_V1", "evidenceTrack": TRACK,
        "requestSha256": request_sha, "candidate": candidate, "probabilityScale": scale,
        "selectionDisposition": disposition, "retainedOfficialModel": "V18",
        "baselineProbabilityDefinition": "ORIGINAL_FROZEN_V18_RAW_OOF" if scale == "raw" else "FROZEN_V18_OOF_WITH_EARLIER_OOF_CHRONOLOGICAL_TEMPERATURE",
        "supportiveOnlyNeverUsedForPaCandidateSelection": True, "simulatorCalls": sum(calls.values()),
        "populationHashMismatches": 0, "populationReloadMismatches": 0,
        "empiricalCRPSDefinition": "MEAN_ABS_DRAW_MINUS_OBSERVED_MINUS_HALF_MEAN_PAIRWISE_ABS_DRAW_DIFFERENCE",
        "empiricalCRPSByGame": crps,
        "empiricalCRPS": {branch: {name: float(np.mean([row[name] for row in crps if row["branch"] == branch]))
                                    for name in ("away", "home", "margin", "total")} for branch in ("baseline", "challenger")},
        "transitionAuthority": transition_ref, "paPredictionAuthority": predictions_ref,
        "scoreAuthority": ref(TRUTH), "matchedFrameRows": len(frame),
        "providerCalls": 0, "modelFits": 0, "transitionFits": 0, "finalOotPayloadBytesRead": 0,
        "unsupportedClaims": ["PREGAME_GAME_PREDICTIVE_SKILL", "HISTORICAL_PREGAME_PARTICIPANT_VINTAGES",
                              "PREGAME_GAME_CALIBRATION", "MARKET_RELATIVE_SKILL", "WAGERING_EDGE"],
        "uncertaintyInterpretation": "SIMULATED_PREDICTION_INTERVALS_AND_EMPIRICAL_CRPS_ARE_ORACLE_MECHANICS_ONLY_NOT_INDEPENDENT_FORECAST_EVALUATION"})
    payloads = {"comparison.json": canonical_json_bytes(comparison), "populations.npz": population_bytes,
                "request.json": request_bytes}
    manifest = {"schemaVersion": "MLB_V19_ORACLE_MECHANICS_MANIFEST_V1", "evidenceTrack": TRACK,
                "requestSha256": request_sha, "games": N_GAMES, "simulatorCalls": N_GAMES * 2,
                "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in payloads.items()},
                "researchStatus": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
                "wageringAuthority": False, "executionAllowedInAISP": False, "finalOotPayloadBytesRead": 0}
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    directory = OUT / f"game-comparison/objects/sha256/{manifest_sha}"
    for name, raw in {**payloads, "manifest.json": manifest_bytes}.items():
        put(directory / name, raw)
    receipt = {"status": "ORACLE_MECHANICS_COMPLETE_NOT_PREGAME_SKILL", "requestSha256": request_sha,
               "evidenceTrack": TRACK, "candidate": candidate, "probabilityScale": scale,
               "selectionDisposition": disposition, "games": N_GAMES, "simulationsPerBranchPerGame": N_SIMS,
               "completedAtUtc": datetime.now(timezone.utc).isoformat(),
               "files": {name: ref(directory / name) for name in (*payloads, "manifest.json")}}
    put(receipt_path, canonical_json_bytes(receipt))
    return {**receipt, "simulatorCallsThisInvocation": N_GAMES * 2}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=CANDIDATES, required=True)
    parser.add_argument("--probability-scale", choices=("raw", "calibrated"), default="calibrated")
    parser.add_argument("--selection-disposition", choices=("SELECTED_RESEARCH_CHALLENGER", "REJECTED_DIAGNOSTIC_ONLY"), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.candidate, args.probability_scale, args.selection_disposition), indent=2), flush=True)
