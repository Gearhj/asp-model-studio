"""Freeze one deadline-valid transition shadow with retained paired populations."""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from run_mlb_v18_transition_shrinkage_v1 import OUT, compact, execute, load_baseline, retain_execution, utc
from server.sports_datasets.consumer import canonical_json_bytes


def freeze(object_sha: str) -> dict:
    bundle = load_baseline(object_sha)
    forecast = bundle["forecast"]
    start = utc(forecast["scheduledStart"])
    cutoff = start - timedelta(minutes=15)
    begun = datetime.now(timezone.utc)
    if begun >= cutoff:
        raise ValueError("SHADOW_PAIR_CUTOFF_EXPIRED")
    change, metadata = execute(bundle, 5000, 20260907)
    if datetime.now(timezone.utc) >= cutoff:
        raise ValueError("SHADOW_PAIR_COMPLETED_AFTER_CUTOFF")
    execution = retain_execution(bundle, change, metadata, 5000, 20260907)
    completed = datetime.now(timezone.utc)
    if completed >= cutoff:
        raise ValueError("SHADOW_PAIR_PERSISTED_AFTER_CUTOFF")
    fallback = metadata["fallbackRequired"]
    pair = {
        "schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_PROSPECTIVE_PAIR_V2",
        "pairStatus": "DEADLINE_VALID_FROZEN_V18_FALLBACK" if fallback else "DEADLINE_VALID_PROSPECTIVE_RESEARCH_SHADOW",
        "gameId": forecast["gameId"], "sourceGameId": forecast["sourceGameId"], "teams": forecast["teams"],
        "scheduledStartUtc": start.isoformat(), "policyCutoffUtc": cutoff.isoformat(),
        "baselineForecastCreatedAtUtc": forecast["forecastCreatedAt"],
        "changeSimulationStartedAtUtc": metadata["simulationStartedAtUtc"], "pairFrozenAtUtc": completed.isoformat(),
        "sourceForecastObjectSha256": object_sha,
        "sourceCutoff": bundle["execution"]["sourceCutoff"],
        "componentSha256": metadata["component"]["sha256"] if metadata["component"] else None,
        "simulationCountPerConfiguration": 5000, "masterSeed": 20260907,
        "identicalPregameInputs": True, "paModelChanged": False, "starterUsageChanged": False,
        "baseline": compact(bundle["baseline"]), "change": compact(change),
        "population": execution["population"], "executionReceipt": execution["executionReceipt"],
        "initialPaProbabilityMismatches": metadata["initialProbabilityMismatches"],
        "fallback": execution["fallback"],
        "researchShadowOnly": True, "executionAllowedInAisp": False, "wageringAuthority": False,
        "candidateAuthority": False, "outcomeRead": False}
    raw = canonical_json_bytes(pair)
    digest = hashlib.sha256(raw).hexdigest()
    path = OUT / f"prospective-pairs/sha256/{digest}/pair.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable prospective pair conflict")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    persisted = datetime.now(timezone.utc)
    if persisted >= cutoff:
        raise ValueError("SHADOW_PAIR_RECORD_PERSISTED_AFTER_CUTOFF")
    pointer = {"schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_PAIR_POINTER_V2",
               "pairSha256": digest, "path": str(path.resolve()), "bytes": len(raw),
               "population": execution["population"], "executionReceipt": execution["executionReceipt"],
               "gameId": pair["gameId"], "sourceGameId": pair["sourceGameId"],
               "policyCutoffUtc": pair["policyCutoffUtc"], "pairPersistedAtUtc": persisted.isoformat(),
               "candidateAuthority": False}
    temporary = OUT / "prospective-pair-current.json.tmp"
    temporary.write_bytes(canonical_json_bytes(pointer))
    temporary.replace(OUT / "prospective-pair-current.json")
    return pointer


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-object-sha", required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.forecast_object_sha), indent=2), flush=True)
