"""Bounded offline verification. No fit, source resolver, publisher or database writes."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_regime_baseline import (
    RF_OOF_SHA, RUNTIME, load_oof, sha_file, verified_json,
)
from server.sports_current_statcast.mlb_rf_operationalization import (
    PROBABILITIES, publication_gate, verify_saved_rf_predictions,
)
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER

RUN_SHA = "c9ffcc867a73eac6c287309f34889390dedf8484244c3bf5c2ed20dacecaf635"
CANDIDATE = "stage3-candidate-5a26360c71194c10b2c101d27f253bdf"
BASELINE_SHA = "0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9"
MANIFEST_SHA = "944a263d004e0e4647acf8510d547cafd304b43f12d651456c05d3efebf848f7"
OUT = ROOT / "outputs/mlb-v18-rf-operationalization-v1"


def reference(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha_file(path), "bytes": path.stat().st_size}


def immutable_json(label: str, payload: dict) -> dict:
    raw = canonical_json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    path = OUT / "sha256" / digest / label
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable operationalization evidence conflict")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return reference(path)


def check() -> dict:
    run_path = RUNTIME / f"objects/sha256/{RUN_SHA}.json"
    run = verified_json(run_path, RUN_SHA)
    candidate = next(row for row in run["candidates"] if row["candidateId"] == CANDIDATE)
    experiment = next(row for row in run["plan"]["experiments"]
                      if row["experimentId"] == candidate["experimentId"])
    if candidate["modelFamily"] != "random_forest" or candidate["evaluationEvidence"]["reloadableArtifactSha256"] != RF_OOF_SHA:
        raise ValueError("Original RF identity differs")
    baseline_path = ROOT / f"outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/baseline-reproduction-{BASELINE_SHA}.json"
    baseline = verified_json(baseline_path, BASELINE_SHA)
    matched_ref = baseline["artifacts"]["matchedOof"]
    matched_path = Path(matched_ref["path"])
    if sha_file(matched_path) != matched_ref["sha256"] or matched_path.stat().st_size != matched_ref["bytes"]:
        raise ValueError("Physically Development-only matched cache differs")
    matched = pd.read_parquet(matched_path)
    if len(matched) != 494432 or matched.canonicalGameId.nunique() != 6570 or matched.game_date.max() > "2026-08-06":
        raise ValueError("Accepted matched Development population differs")
    saved = verify_saved_rf_predictions(matched, load_oof(RF_OOF_SHA, "random_forest"))
    features = candidate["orderedFeatures"]
    if len(features) != 218:
        raise ValueError("RF source ordering differs")
    prior_result_path = OUT / "prior-recovery/result-16e3681739767be33c21b32575011a4b0dfac4164ac0853ef923da77a53c0268.json"
    prior_result = verified_json(prior_result_path, "16e3681739767be33c21b32575011a4b0dfac4164ac0853ef923da77a53c0268")
    if prior_result["status"] != "ALL_FIVE_V1_AUTHORITIES_RECOVERED_EXACTLY":
        raise ValueError("Historical V1 recovery did not match all five authorities")
    for fold in prior_result["folds"]:
        recovered = fold["recoveredAuthority"]
        verified_json(Path(recovered["path"]), recovered["sha256"])
    feature_contract = {
        "schemaVersion": "MLB_ORIGINAL_RF_RECOVERED_CONTRACT_V1",
        "candidateId": CANDIDATE, "sourceReceipt": reference(run_path),
        "featureSetId": candidate["featureSetId"], "featureSetVersion": candidate["featureSetVersion"],
        "featureSetChecksum": candidate["featureSetChecksum"],
        "orderedFeatures": features, "orderedFeaturesSha256": hashlib.sha256(canonical_json_bytes(features)).hexdigest(),
        "targetOrder": list(PA_CLASS_ORDER), "hyperparameters": candidate["hyperparameters"],
        "seed": experiment["seed"], "environment": run["environment"],
        "identity": run["identity"],
        "historicalV1PriorRecovery": reference(prior_result_path),
        "rawSchemaOverlap": {"v18RawFeatureCount": len(baseline["rawFeatureColumns"]),
                             "rfFieldsAbsentFromV18RawNames": sorted(set(features) - set(baseline["rawFeatureColumns"])),
                             "sharedNamesProveTransformationParity": False},
        "prospectiveContextRequirements": {
            "eventSpecificFieldsRequiringNewEvidence": [name for name in features if
                name.startswith(("batting_", "fielding_", "month_", "day_of_week_"))
                or name in ("is_day_game", "is_series_opener", "is_weekend", "is_friday_night")],
            "templateLimitation": "Historical batter/pitcher template copying does not recompute these event-specific fields. No future-game compatibility claimed.",
            "sourceWindow": ["2026-04-01", "2026-08-13"],
            "bullpenTemplateWindow": ["2026-07-15", "2026-08-13"],
            "historicalPriorsAreNotCurrentWorkload": True,
            "requiredLocalExport": ["Next-slate canonical event/team and source-event mapping; UTC first pitch/status; original observed and available timestamps",
                                    "Two timestamped starter identities and ordered nine-player lineups with source authority",
                                    "Event-specific rest/travel/calendar/context values and timestamped frozen-contract player/state evidence"],
        },
        "preprocessingSemantics": {
            "groupOrder": ["numeric", "binary", "binary_mode", "categorical"],
            "numeric": "Governed posterior means replace registered prior fields; then training-fold median. No standardization.",
            "binary": "Registered passthrough; missing values forbidden. Other registered binary fields use training-fold mode.",
            "categorical": "String normalization; null/unseen -> UNKNOWN; sorted observed training categories then UNKNOWN; one-hot, never ordinal.",
            "outliers": "RETAIN", "remainder": "drop", "sparseThreshold": .3,
            "stateAvailability": "SEMANTIC_CONTRACT_AND_HASHES_RECOVERED_NOT_COMPLETE_FITTED_PIPELINE",
            "source": "server/sports_current_statcast/stage3_model_laboratory.py:_preprocessor/_evaluate_candidate",
        },
        "folds": [{"foldNumber": row["foldNumber"], "trainRows": row["trainRows"],
                   "trainEnd": row["trainEnd"], "validationRows": row["validationRows"],
                   "transformedFeatureCount": row["modelComplexity"]["transformedFeatureCount"],
                   "preprocessing": row["preprocessing"],
                   "transformationCounts": dict(Counter(step for item in row["preprocessing"]["registeredOrderedTransformations"] for step in item["steps"]))}
                  for row in candidate["folds"]],
        "missingFrozenObjects": ["Original five RF fold estimators (500-tree learned state each)",
                                 "Original fold preprocessing payloads: numeric medians, binary modes, category levels and ordering",
                                 "An explicitly selected frozen RF deployment artifact and its training cutoff"],
        "warning": "A preprocessing hash and a reloadable OOF parquet are not a reloadable estimator. No replacement RF is authorized.",
    }
    contract_ref = immutable_json("rf-feature-contract.json", feature_contract)
    study_root = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1"
    manifest_path = study_root / f"documents/sha256/{MANIFEST_SHA}/publication-manifest.json"
    manifest = verified_json(manifest_path, MANIFEST_SHA)
    fitted_ref = next(row for row in manifest["files"] if row["label"] == "fitted-research-system.joblib")
    fitted_path = Path(fitted_ref["path"])
    if sha_file(fitted_path) != fitted_ref["sha256"] or fitted_path.stat().st_size != fitted_ref["byteCount"]:
        raise ValueError("Preserved ensemble artifact changed")
    fitted, reloaded = joblib.load(fitted_path), joblib.load(fitted_path)
    weights = fitted["ensemble"].weights
    if not np.array_equal(weights, [0.8920347405861558, 0.10796525941384416, 0.]):
        raise ValueError("Frozen ensemble weights differ")
    if fitted["targetOrder"] != list(PA_CLASS_ORDER):
        raise ValueError("Preserved target taxonomy differs")
    p = matched[PROBABILITIES].to_numpy()
    rf = matched[["rf_" + name for name in PROBABILITIES]].to_numpy()
    # Third branch has exactly zero weight; V18 is a harmless placeholder, not a fitted specialist.
    branches = np.stack([p, rf, p], axis=1)
    first, second = fitted["ensemble"].predict(branches), reloaded["ensemble"].predict(branches)
    if first.tobytes() != second.tobytes():
        raise ValueError("Saved ensemble reload mismatch")
    reload_result = {"artifact": reference(fitted_path), "targetOrder": fitted["targetOrder"],
                     "weights": weights.tolist(), "temperature": fitted["temperatures"]["RF_RESIDUAL_ENSEMBLE"],
                     "perClassCorrectionCap": .03, "rows": len(matched), "bitwiseEqualAfterReload": True,
                     "rfEstimatorReproduced": False, "baseProbabilities": "ARCHIVED_MATCHED_OOF_ONLY",
                     "warning": "The fitted ensemble object does not contain either base estimator; reload does not establish prospective support."}
    accounting_path = OUT / "current-input-accounting.json"
    accounting = verified_json(accounting_path)
    if accounting["nextSlate"]["supportedGameCount"] != 0 or accounting["nextSlate"]["scheduledGameCount"] is not None:
        raise ValueError("Current evidence differs from the bounded no-next-slate determination; reassess instead of publishing")
    inventory_path = OUT / "rf-artifact-inventory.json"
    verified_json(inventory_path)
    reproduction = {"status": "BLOCKED_ORIGINAL_RF_ESTIMATOR_AND_PREPROCESSOR_NOT_RECOVERED",
                    "estimatorInferenceCalls": 0, "estimatorFits": 0,
                    "matchedRows": 494432, "mismatchedProbabilityValues": None,
                    "frozenEstimatorArtifactSha256": None, "frozenPreprocessingArtifactSha256": None}
    result = {
        "schemaVersion": "MLB_V18_RF_OPERATIONALIZATION_RECEIPT_V1",
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "startingBranch": "codex/mlb-regime-hybrid-ensemble-v1", "startingCommit": "d391d274668bc33c0ef64f0881ef0db1fe0b3770",
        "verdict": "NOT_OPERATIONALLY_USABLE_PUBLICATION_BLOCKED",
        "originalRfCandidateId": CANDIDATE, "recoveredFeatureContract": contract_ref,
        "matchedDevelopmentAuthority": reference(baseline_path), "savedRfPredictions": saved,
        "rfEstimatorReproduction": reproduction, "preservedEnsembleReload": reload_result,
        "gameAccounting": reference(accounting_path),
        "registeredArtifactInventory": reference(inventory_path),
        "exactV1PriorRecovery": reference(prior_result_path),
        "nextSlateSupportedGames": 0, "nextSlateScheduledGameCount": None,
        "publicationGate": publication_gate(estimator_reproduction=reproduction, prospective_games=0),
        "newForecasts": 0, "aispHandoff": None,
        "smallestRepair": [
            "Restore the original candidate's serialized fold estimators and fitted preprocessors from an existing backup/run host, with verifiable original lineage; prove exact inference on the 494432 matched IDs. Do not retrain or substitute V18 preprocessing.",
            "Supply a timestamped local next-slate event/team/starter/lineup and event-context snapshot with explicit source-as-of and frozen-contract-compatible player/state inputs; reject expired games and stale historical context."
        ],
        "ifOriginalStateWasNeverSaved": "Exact original RF recovery cannot be achieved from predictions or hashes. A separately authorized newly persisted RF study would be new evidence, not reproduction; not performed here.",
        "safety": {"modelFits": 0, "priorFits": 0, "providerCalls": 0, "finalOotPayloadBytesRead": 0,
                   "aispReads": 0, "aispWrites": 0, "officialV18Changed": False, "policyChanged": False,
                   "positionsChanged": False, "settlementsChanged": False, "wageringAuthority": False},
    }
    prior_dir = OUT / "prior-recovery"
    result["priorRecoveryFiles"] = [reference(path) for path in sorted(prior_dir.rglob("*.json"))] if prior_dir.exists() else []
    return immutable_json("operationalization-result.json", result)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(check(), indent=2))
