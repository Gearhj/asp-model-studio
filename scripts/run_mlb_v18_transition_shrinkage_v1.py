"""Execute and retain a transition shadow with authenticated frozen-V18 fallback."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast import mlb_v18_daily_slate as daily
from server.sports_current_statcast.mlb_starter_duration_paired_simulation import REFERENCE, simulate_research_arm
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_current_publication import CurrentV18Engine, current_template
from server.sports_current_statcast.mlb_v18_prospective_transform import ProspectiveFrameAuthority, wrap_prospective_pipeline
from server.sports_current_statcast.mlb_v18_whole_game_challenger import V18StateProbabilityProvider, V18WholeGameError
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5.base_out_transition import TransitionModelError
from server.sports_phase5.hierarchical_transition import HierarchicalTransitionModel
OUT = ROOT / "outputs/mlb-v18-transition-shrinkage-v1"
CURRENT = OUT / "current.json"
OBJECTS = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/objects/sha256"
PILOT = "7323d8f3-9b24-464d-903e-fe290913d73b"
FIELDS = ("homeRuns", "awayRuns", "innings", "paCounts")
CONFIGURATION = "V18_PA_FOLD5_PLUS_HIERARCHICAL_TRANSITION_SHRINKAGE_V1"
COMPONENT_SHA256 = "8c91d687c95ff81ad11efa7a5e718aa5bbfeb0aa97cc05795bd26e3954939640"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path), "bytes": path.stat().st_size}

def utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Explicit source timezone required")
    return result.astimezone(timezone.utc)

def put(raw: bytes, name: str, *, output: Path = OUT) -> dict:
    digest = hashlib.sha256(raw).hexdigest()
    path = output / "executions/sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable execution artifact conflict")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return {"path": str(path.resolve()), "sha256": digest, "bytes": len(raw)}

def load_baseline(object_sha: str) -> dict:
    """Authenticate the original population before any fallback is possible."""
    if re.fullmatch(r"[0-9a-f]{64}", object_sha) is None:
        raise ValueError("Exact frozen forecast object SHA-256 required")
    directory = daily._verify_existing_object(OBJECTS.parents[1], {
        "relativePath": f"objects/sha256/{object_sha}", "objectSha256": object_sha})
    forecast, snapshot, execution, manifest = [json.loads((directory / name).read_text(encoding="utf-8"))
        for name in ("forecast.json", "pregame-evidence.json", "execution-inputs.json", "manifest.json")]
    identities = [forecast["gameId"], str(forecast["sourceGameId"])]
    if (not all(final_oot_eligible_key_mask(identities)) or PILOT in identities
            or utc(forecast["scheduledStart"]).date().isoformat() <= "2026-08-27"):
        raise ValueError("Outside authorized post-Final-OOT research population")
    parent = forecast["parentAuthority"]
    if (forecast["gameId"] != snapshot["game"]["game_id"]
            or str(forecast["sourceGameId"]) != str(snapshot["game"]["source_game_id"])
            or manifest["gameId"] != forecast["gameId"]
            or parent["paModelSha256"] != daily.PA_MODEL_SHA256
            or parent["transitionModelSha256"] != daily.TRANSITION_MODEL_SHA256
            or parent["bundleSha256"] != daily.PARENT_BUNDLE_SHA256
            or forecast["simulation"]["seed"] != daily.MASTER_SEED
            or forecast["simulation"]["count"] != daily.SIMULATION_COUNT
            or execution["modelIdentity"]["treatmentManifestSha256"] != daily.TREATMENT_MANIFEST_SHA256
            or forecast["executionInputDigest"] != daily.sha_json(daily.json_safe(execution))):
        raise ValueError("Untrusted frozen V18 baseline identity")
    if any(forecast.get(name) != expected for name, expected in daily.RESEARCH_FLAGS.items()):
        raise ValueError("Frozen baseline authority differs")
    if not utc(forecast["capturedAt"]) <= utc(forecast["forecastCreatedAt"]) < utc(forecast["scheduledStart"]):
        raise ValueError("Frozen baseline publication clock differs")
    baseline = execution["population"]
    for name in FIELDS:
        values = np.asarray(baseline[name])
        if (values.shape != (daily.SIMULATION_COUNT,) or not np.isfinite(values).all()
                or (values < 0).any() or not np.equal(values, np.floor(values)).all()):
            raise ValueError("Invalid frozen baseline population")
    if baseline["illegalStateCount"] or baseline["nonterminationCount"]:
        raise ValueError("Invalid frozen baseline mechanics")
    return {"objectSha256": object_sha, "directory": directory, "forecast": forecast,
            "snapshot": snapshot, "execution": execution, "baseline": baseline,
            "manifest": ref(directory / "manifest.json")}

def prepare_candidate(bundle: dict, now: datetime) -> tuple:
    """Use only the source cutoff and inputs bound to the original forecast."""
    forecast, snapshot, execution = (bundle[name] for name in ("forecast", "snapshot", "execution"))
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    component_ref = current["component"]
    if component_ref["sha256"] != COMPONENT_SHA256:
        raise ValueError("TRANSITION_CONFIGURATION_COMPONENT_IDENTITY_MISMATCH")
    component_path = Path(component_ref["path"])
    if sha(component_path) != component_ref["sha256"] or component_path.stat().st_size != component_ref["bytes"]:
        raise ValueError("TRANSITION_COMPONENT_CHECKSUM_MISMATCH")
    component = HierarchicalTransitionModel.from_dict(json.loads(component_path.read_text(encoding="utf-8")))
    if (not np.isfinite([component.prior_strength, component.legal_floor]).all()
            or component.prior_strength != 20.0 or component.legal_floor != 1e-6
            or component.seasons != (2023, 2024, 2025)):
        raise ValueError("UNSUPPORTED_TRANSITION_COMPONENT")
    for outcome in PA_CLASS_ORDER:
        for outs in range(3):
            for base in range(8):
                component.distribution(outcome, outs, base)
    feature_ref = execution["featureSnapshot"]
    feature_path = Path(feature_ref["path"])
    if sha(feature_path) != feature_ref["sha256"] or feature_path.stat().st_size != feature_ref["bytes"]:
        raise ValueError("FEATURE_SNAPSHOT_CHECKSUM_MISMATCH")
    feature = json.loads(feature_path.read_text(encoding="utf-8"))
    composition, cutoff = feature["composition"], execution["sourceCutoff"]
    if (cutoff != forecast["sourceCutoff"] or cutoff != composition["sourceCutoff"]
            or composition["providerInputs"] != execution["providerInputs"]
            or not composition.get("canSimulate") or composition.get("blockers")):
        raise ValueError("UNSUPPORTED_OR_MISMATCHED_PREGAME_INPUT_EVIDENCE")
    source_clock = cutoff["evidenceAvailableAt"] if isinstance(cutoff, dict) else cutoff
    if not utc(source_clock) <= utc(snapshot["capturedAt"]) <= utc(forecast["forecastCreatedAt"]):
        raise ValueError("SOURCE_CUTOFF_AFTER_FROZEN_FORECAST")
    engine = CurrentV18Engine()
    start = utc(forecast["scheduledStart"])
    deadline = start - timedelta(minutes=15) if now < start else None
    if deadline is not None:
        if now >= deadline:
            raise ValueError("SHADOW_EXECUTION_POLICY_CUTOFF_EXPIRED")
        raw = pd.DataFrame(composition["rows"], columns=engine.contract["rawFeatureColumns"])
        authority = ProspectiveFrameAuthority(
            event_id=str(snapshot["game"]["game_id"]), game_date=str(raw.game_date.iloc[0])[:10],
            evidence_cutoff_utc=str(source_clock), kickoff_utc=str(snapshot["game"]["starts_at"]),
            snapshot_sha256=feature_ref["sha256"], authorized_at_utc=now.isoformat(),
            venue_timezone=composition.get("venueTimezone") or composition["event"]["venueTimezone"])
        authority.validate()
        pipeline = wrap_prospective_pipeline(engine.pipeline, authority)
        actual = np.concatenate([pipeline.predict_proba(raw.iloc[[index]]) for index in range(len(raw))])
        expected = np.asarray(execution["initialPaProbabilities"], dtype=float)
        if actual.shape != expected.shape or not np.array_equal(actual, expected):
            raise ValueError("LIVE_PREGAME_INITIAL_PROBABILITY_MISMATCH")
        inputs = execution["providerInputs"]
        provider = V18StateProbabilityProvider(
            pipeline, away_batters=inputs["awayBatters"], home_batters=inputs["homeBatters"],
            away_starter=inputs["awayStarter"], home_starter=inputs["homeStarter"],
            away_bullpen=inputs["awayBullpen"], home_bullpen=inputs["homeBullpen"],
            temperature=None, template_composer=current_template)
        replay = {"mode": "AUTHORIZED_LIVE_PREGAME_REPLAY", "initialProbabilityMismatches": 0}
    else:
        from server.sports_current_statcast.mlb_v18_ensemble_candidate import build_saved_historical_replay_provider
        provider, replay = build_saved_historical_replay_provider(
            engine, snapshot, composition, execution, snapshot_sha256=feature_ref["sha256"],
            original_forecast_created_at=forecast["forecastCreatedAt"])
    return provider, component, component_ref, replay, deadline

def execute(bundle: dict, simulations: int, seed: int) -> tuple[dict, dict]:
    if simulations <= 0 or seed < 0:
        raise ValueError("Positive simulation budget and nonnegative seed required")
    begun = datetime.now(timezone.utc)
    # Baseline authentication deliberately occurs outside this fallback boundary.
    with threadpool_limits(limits=4):
        try:
            provider, component, component_ref, replay, deadline = prepare_candidate(bundle, begun)
        except (OSError, ValueError, KeyError, TypeError, TransitionModelError, V18WholeGameError) as exc:
            return bundle["baseline"], {
                "mode": "FROZEN_V18_BASELINE_REUSE", "fallbackRequired": True,
                "fallbackReason": f"{type(exc).__name__}: {exc}", "component": None,
                "initialProbabilityMismatches": None, "simulationStartedAtUtc": None,
                "executionStartedAtUtc": begun.isoformat(), "executionCompletedAtUtc": datetime.now(timezone.utc).isoformat(),
                "newSimulations": 0, "masterSeed": daily.MASTER_SEED}
        population = simulate_research_arm(
            game_id=bundle["forecast"]["gameId"], provider=provider, transition_model=component,
            n_sims=simulations, master_seed=seed, arm=REFERENCE,
            regulation=int(bundle["snapshot"]["game"].get("scheduled_innings") or 9), trace_count=0,
            deadline_utc=deadline)
    return population, {**replay, "fallbackRequired": False, "fallbackReason": None,
        "component": component_ref, "simulationStartedAtUtc": begun.isoformat(),
        "executionStartedAtUtc": begun.isoformat(), "executionCompletedAtUtc": datetime.now(timezone.utc).isoformat(),
        "newSimulations": simulations, "masterSeed": seed}

def compact(population: dict) -> dict:
    home, away = np.asarray(population["homeRuns"]), np.asarray(population["awayRuns"])
    return {"homeWinProbability": float((home > away).mean()), "meanHomeRuns": float(home.mean()),
            "meanAwayRuns": float(away.mean()), "meanTotalRuns": float((home + away).mean()),
            "meanRunDifferential": float((home - away).mean()), "simulationCount": len(home),
            "illegalStateCount": int(population["illegalStateCount"]),
            "nonterminationCount": int(population["nonterminationCount"])}

def retain_execution(bundle: dict, change: dict, metadata: dict, simulations: int, seed: int,
                     *, output: Path = OUT) -> dict:
    arrays = {f"{arm}_{name}": np.asarray(population[name], dtype="<i8")
              for arm, population in (("baseline", bundle["baseline"]), ("change", change)) for name in FIELDS}
    archive = io.BytesIO()
    np.savez_compressed(archive, **arrays)
    raw = archive.getvalue()
    with np.load(io.BytesIO(raw), allow_pickle=False) as saved:
        if any(not np.array_equal(saved[name], array) for name, array in arrays.items()):
            raise ValueError("Retained paired population differs")
    population_ref = put(raw, "paired-populations.npz", output=output)
    forecast = bundle["forecast"]
    result = {
        "schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_EXECUTION_V2",
        "requestedConfiguration": CONFIGURATION,
        "configuration": "FROZEN_V18_BASELINE" if metadata["fallbackRequired"] else CONFIGURATION,
        "forecastObjectSha256": bundle["objectSha256"], "sourceManifest": bundle["manifest"],
        "gameId": forecast["gameId"], "sourceGameId": forecast["sourceGameId"],
        "sourceCutoff": bundle["execution"]["sourceCutoff"],
        "baselineForecastCreatedAtUtc": forecast["forecastCreatedAt"],
        "scheduledStartUtc": forecast["scheduledStart"],
        "policyCutoffUtc": (utc(forecast["scheduledStart"]) - timedelta(minutes=15)).isoformat(),
        "requestedSimulationCount": simulations, "requestedMasterSeed": seed,
        "masterSeed": metadata["masterSeed"], **compact(change), "baseline": compact(bundle["baseline"]),
        "population": population_ref, "execution": metadata,
        "pairedMonteCarloCoupling": (len(change["homeRuns"]) == daily.SIMULATION_COUNT
                                      and metadata["masterSeed"] == daily.MASTER_SEED),
        "pairingScheme": "Same game SHA-256 entropy; SeedSequence children PA/TRANSITION/HOOK; draw index and PA step",
        "researchShadowOnly": True, "executionAllowedInAisp": False, "wageringAuthority": False,
        "candidateAuthority": False, "outcomeRead": False,
        "fallback": {"required": metadata["fallbackRequired"], "reason": metadata["fallbackReason"],
                     "whenUnsupported": "AUTHENTICATED_FROZEN_V18_POPULATION"}}
    receipt = put(canonical_json_bytes(result), "execution-receipt.json", output=output)
    return {**result, "executionReceipt": receipt}

def run(object_sha: str, simulations: int, seed: int) -> dict:
    bundle = load_baseline(object_sha)
    population, metadata = execute(bundle, simulations, seed)
    return retain_execution(bundle, population, metadata, simulations, seed)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-object-sha", required=True)
    parser.add_argument("--simulations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260907)
    args = parser.parse_args()
    print(json.dumps(run(args.forecast_object_sha, args.simulations, args.seed), indent=2), flush=True)
