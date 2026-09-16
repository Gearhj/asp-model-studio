"""Package an already frozen transition pair for the proposed AISP V2 adapter.

No inference, model loading, outcomes, exchange writes or AISP writes occur here.
V2 adds the TRANSITION role; Claude must implement that consumer extension.
The historical comparison remains separate research evidence, never a forecast.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/mlb-v18-transition-shrinkage-v1"
OUTPUT = SOURCE / "adapter-v2"
DAILY = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/objects/sha256"
AUTHORITY = ROOT / "outputs/mlb-v18-conditional-champion-v1/aisp-handoff/sha256/a3d6ea3fdb9ddecc42e7b5ecac975d0d132931c0ca7bfc0938bdcef205f2d300/champion-handoff.json"
COMPONENT_ID = "MLB_BASE_OUT_TRANSITION_HIERARCHICAL_SHRINKAGE_V1"
FLAGS = {"executionAllowed": False, "wageringAuthority": False, "activatesModel": False,
         "executionAllowedInAISP": False, "candidateAuthority": False}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def reference(path):
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def verify_ref(item):
    path = Path(item["path"]).resolve(strict=True)
    actual = reference(path)
    if actual["sha256"] != item["sha256"] or actual["bytes"] != int(item["bytes"]):
        raise ValueError("SOURCE_REFERENCE_MISMATCH:" + str(path))
    return path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def aware(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("AWARE_SOURCE_CLOCK_REQUIRED")
    return result.astimezone(timezone.utc)


def immutable(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("IMMUTABLE_COLLISION:" + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(data)
    return reference(path)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
        stream.write(canonical(value))
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _distribution(values):
    return {str(int(value)): int(count) / len(values)
            for value, count in sorted(Counter(values.tolist()).items())}


def _summary(home, away):
    return {"homeWinProbability": float(np.mean(home > away)), "meanHomeRuns": float(home.mean()),
            "meanAwayRuns": float(away.mean()), "meanTotalRuns": float((home + away).mean()),
            "meanRunDifferential": float((home - away).mean())}


def _same_summary(actual, expected, label):
    for key, value in actual.items():
        if key not in expected or not np.isclose(value, expected[key], rtol=0, atol=1e-12):
            raise ValueError("RETAINED_POPULATION_SUMMARY_MISMATCH:" + label + ":" + key)


def _baseline_authority(forecast):
    if reference(AUTHORITY)["sha256"] != AUTHORITY.parent.name:
        raise ValueError("AUTHORITY_HANDOFF_HASH_MISMATCH")
    authority = read_json(AUTHORITY)
    identity = authority["modelIdentity"]
    parent = forecast["parentAuthority"]
    if (identity["artifactSha256"] != parent["paModelSha256"]
            or identity["parentLogicalBundleSha256"] != parent["bundleSha256"]
            or identity["parentBundleId"] != parent["bundleId"]):
        raise ValueError("BASELINE_AUTHORITY_IDENTITY_MISMATCH")
    binding = {"engineId": "MLB_V18_WHOLE_GAME", "engineVersion": parent["bundleId"],
               "modelArtifactSha256": identity["artifactSha256"],
               "parentBundleId": identity["parentBundleId"], "trainingRunId": identity["trainingRunId"]}
    refs = {"authority-handoff.json": reference(AUTHORITY)}
    for key, destination in (("championManifest", "championManifestSha256"),
                             ("frozenBindings", "frozenBindingsSha256"),
                             ("developmentIntegrity", "developmentIntegritySha256"),
                             ("registrationReceipt", "registrationReceiptSha256")):
        verify_ref(authority[key])
        binding[destination] = authority[key]["sha256"]
        refs[key + ".json"] = authority[key]
    return binding, refs


def build(pair_pointer=SOURCE / "prospective-pair-current.json"):
    pointer = read_json(pair_pointer)
    pair_ref = {"path": pointer["path"], "sha256": pointer["pairSha256"], "bytes": pointer["bytes"]}
    pair_path = verify_ref(pair_ref)
    pair = read_json(pair_path)
    if (pair.get("schemaVersion") != "MLB_V18_TRANSITION_SHRINKAGE_PROSPECTIVE_PAIR_V2"
            or pair.get("pairStatus") not in {"DEADLINE_VALID_PROSPECTIVE_RESEARCH_SHADOW", "DEADLINE_VALID_FROZEN_V18_FALLBACK"}
            or pair.get("outcomeRead") is not False or pair.get("candidateAuthority") is not False
            or pair.get("identicalPregameInputs") is not True
            or pair.get("paModelChanged") is not False or pair.get("starterUsageChanged") is not False):
        raise ValueError("AUTHENTICATED_UNCHANGED_PA_PROSPECTIVE_PAIR_REQUIRED")
    if "population" not in pair or "executionReceipt" not in pair:
        raise ValueError("RETAINED_PAIRED_POPULATION_REQUIRED_COMPACT_SUMMARY_IS_INSUFFICIENT")
    population_path = verify_ref(pair["population"])
    execution_receipt_path = verify_ref(pair["executionReceipt"])
    execution_receipt = read_json(execution_receipt_path)
    transition_ran = not pair["fallback"]["required"]
    fallback_reason = pair["fallback"]["reason"]
    if not transition_ran and not fallback_reason:
        raise ValueError("EXPLICIT_BASELINE_FALLBACK_REASON_REQUIRED")
    if (execution_receipt.get("outcomeRead") is not False
            or execution_receipt.get("candidateAuthority") is not False
            or execution_receipt.get("executionAllowedInAisp") is not False
            or execution_receipt.get("wageringAuthority") is not False):
        raise ValueError("EXECUTION_RECEIPT_RESEARCH_AUTHORITY_REQUIRED")
    begun = pair["changeSimulationStartedAtUtc"] if transition_ran else execution_receipt["execution"]["executionStartedAtUtc"]
    if not (aware(begun) <= aware(pair["pairFrozenAtUtc"])
            < aware(pair["policyCutoffUtc"]) < aware(pair["scheduledStartUtc"])):
        raise ValueError("PROSPECTIVE_PAIR_CLOCKS_INVALID")
    if not aware(pair["pairFrozenAtUtc"]) <= aware(pointer["pairPersistedAtUtc"]) < aware(pair["policyCutoffUtc"]):
        raise ValueError("PROSPECTIVE_PAIR_PERSISTENCE_CLOCK_INVALID")
    sha = pair["sourceForecastObjectSha256"]
    if not re.fullmatch("[0-9a-f]{64}", sha):
        raise ValueError("BASELINE_OBJECT_SHA_INVALID")
    directory = DAILY / sha
    manifest = read_json(directory / "manifest.json")
    if manifest["objectSha256"] != sha:
        raise ValueError("BASELINE_OBJECT_ADDRESS_MISMATCH")
    source_files = {}
    for name in ("forecast.json", "execution-inputs.json"):
        descriptor = next(x for x in manifest["artifacts"] if x["relativePath"] == name)
        source_files[name] = {"path": str(directory / name), "sha256": descriptor["sha256"], "bytes": descriptor["bytes"]}
        verify_ref(source_files[name])
    baseline = read_json(directory / "forecast.json")
    # Execution data contains saved simulation draws and pregame inputs, no game outcomes.
    execution = read_json(directory / "execution-inputs.json")
    if (str(pair["gameId"]) != str(baseline["gameId"])
            or str(pair["sourceGameId"]) != str(baseline["sourceGameId"])
            or pair["teams"] != baseline["teams"]
            or aware(pair["scheduledStartUtc"]) != aware(baseline["scheduledStart"])
            or pair["baselineForecastCreatedAtUtc"] != baseline["forecastCreatedAt"]):
        raise ValueError("PER_FORECAST_BASELINE_IDENTITY_OR_CLOCK_MISMATCH")
    if (pair["sourceCutoff"] != baseline["sourceCutoff"]
            or pair["sourceCutoff"] != execution["sourceCutoff"]
            or pair["sourceCutoff"] != execution_receipt["sourceCutoff"]
            or execution_receipt["forecastObjectSha256"] != sha
            or execution_receipt["population"] != pair["population"]
            or execution_receipt["fallback"] != pair["fallback"]):
        raise ValueError("EXECUTION_RECEIPT_OR_ORIGINAL_SOURCE_CUTOFF_MISMATCH")
    count, seed = pair["simulationCountPerConfiguration"], pair["masterSeed"]
    if count != 5000 or baseline["simulation"]["count"] != count or baseline["simulation"]["seed"] != seed:
        raise ValueError("COMMON_SIMULATION_BUDGET_OR_SEED_MISMATCH")
    arrays = {}
    with np.load(population_path, allow_pickle=False) as population:
        for arm in ("baseline", "change"):
            for side in ("home", "away"):
                key = arm + "_" + side + "Runs"
                values = np.asarray(population[key])
                if (values.shape != (count,) or not np.isfinite(values).all()
                        or np.any(values < 0) or np.any(values != values.astype(np.int64))):
                    raise ValueError("ILLEGAL_RETAINED_POPULATION:" + key)
                arrays[key] = values.astype(np.int64)
        for side in ("home", "away"):
            if not np.array_equal(arrays["baseline_" + side + "Runs"], execution["population"][side + "Runs"]):
                raise ValueError("ORIGINAL_BASELINE_DRAW_IDENTITY_MISMATCH:" + side)
            if not transition_ran and not np.array_equal(arrays["baseline_" + side + "Runs"], arrays["change_" + side + "Runs"]):
                raise ValueError("FALLBACK_MUST_REUSE_EXACT_BASELINE_DRAWS:" + side)
        for arm in ("baseline", "change"):
            home, away = arrays[arm + "_homeRuns"], arrays[arm + "_awayRuns"]
            if np.any(home == away):
                raise ValueError("TERMINAL_GAME_TIE_UNSUPPORTED")
            _same_summary(_summary(home, away), pair[arm], arm)
    baseline_authority, authority_refs = _baseline_authority(baseline)
    configured_component = read_json(SOURCE / "current.json")["component"]
    component_sha = pair["componentSha256"] if transition_ran else configured_component["sha256"]
    component = Path(configured_component["path"])
    if transition_ran and (configured_component["sha256"] != component_sha or reference(component)["sha256"] != component_sha):
        raise ValueError("TRANSITION_COMPONENT_HASH_MISMATCH")
    if transition_ran and execution_receipt["execution"]["component"]["sha256"] != component_sha:
        raise ValueError("EXECUTED_TRANSITION_COMPONENT_IDENTITY_MISMATCH")
    code_paths = [Path(__file__), ROOT / "server/sports_phase5/hierarchical_transition.py",
                  ROOT / "scripts/run_mlb_v18_transition_shrinkage_v1.py",
                  ROOT / "scripts/freeze_mlb_v18_transition_shadow_v1.py"]
    code_refs = {p.name: reference(p) for p in code_paths}
    config = {"schemaVersion": "MLB_V18_TRANSITION_ADAPTER_CONFIGURATION_V2",
              "configurationId": "mlb-v18-transition-shrinkage-v1", "baseline": baseline_authority,
              "component": {"componentId": COMPONENT_ID, "role": "TRANSITION", "sha256": component_sha},
              "fallback": "FROZEN_V18_BASELINE", "calibrationEnabled": False, "durationChanged": False,
              "simulationCount": count, "seed": seed, "code": code_refs,
              "runnable": {"workspace": str(ROOT),
                  "simulateCommand": ".\\.venv\\Scripts\\python.exe scripts/run_mlb_v18_transition_shrinkage_v1.py --forecast-object-sha <immutable-object-sha> --simulations 5000 --seed 20260907",
                  "freezeFutureCommand": ".\\.venv\\Scripts\\python.exe scripts/freeze_mlb_v18_transition_shadow_v1.py --forecast-object-sha <eligible-future-object-sha>",
                  "packageCommand": ".\\.venv\\Scripts\\python.exe scripts/package_mlb_v18_transition_adapter_v2.py"}, **FLAGS}
    config_bytes = canonical(config)
    config_sha = hashlib.sha256(config_bytes).hexdigest()
    package_key = hashlib.sha256(canonical({"pairSha256": pair_ref["sha256"], "configurationSha256": config_sha})).hexdigest()
    package_root = OUTPUT / "packages/sha256" / package_key
    configuration_ref = immutable(package_root / "configuration.json", config_bytes)
    components = [{"componentId": "MLB_V18_HGB_PA", "role": "BASE",
                   "sha256": baseline_authority["modelArtifactSha256"], "status": "FROZEN"},
                  {"componentId": COMPONENT_ID, "role": "TRANSITION",
                   "sha256": component_sha, "status": "SHADOW_ONLY"}]
    parent = baseline["parentAuthority"]
    home, away = arrays["change_homeRuns"], arrays["change_awayRuns"]
    summary = _summary(home, away)
    candidate_forecast = {
        "schemaVersion": "MLB_ENSEMBLE_CANDIDATE_GAME_FORECAST_V1", "artifactType": "PROSPECTIVE",
        "forecastId": "mlb-v18-transition-" + pair_ref["sha256"],
        "baselineForecastId": "mlb-v18-daily-" + sha,
        "canonicalGameId": baseline["gameId"], "eventId": baseline["gameId"],
        "sourceGameId": baseline["sourceGameId"], "season": aware(baseline["scheduledStart"]).year,
        "homeTeam": baseline["teams"]["HOME"]["uuid"], "awayTeam": baseline["teams"]["AWAY"]["uuid"],
        "capturedAt": baseline["capturedAt"], "publishedAt": pair["pairFrozenAtUtc"],
        "scheduledStart": baseline["scheduledStart"], "policyCutoffUtc": pair["policyCutoffUtc"],
        "publicationClockMeaning": "ORIGINAL_IMMUTABLE_PREGAME_PAIR_FREEZE_NOT_ADAPTER_PACKAGING_TIME",
        "sourceCutoff": baseline["sourceCutoff"], "featureVectorSha256": baseline["snapshotContentSha256"],
        "baselineBinding": {"parentBundleSha256": parent["bundleSha256"],
            "acceptanceProtocolSha256": parent["acceptanceProtocolV2Sha256"], "numericalArtifactSha256": sha,
            "featureVectorSha256": baseline["snapshotContentSha256"], "simulatorId": "V18_WHOLE_GAME_MONTE_CARLO",
            "simulatorVersion": baseline["schemaVersion"], "simulatorSeed": baseline["simulation"]["seed"],
            "simulationCount": baseline["simulation"]["count"], "sourceCutoffUtc": baseline["capturedAt"]},
        "probabilities": {"homeWin": summary["homeWinProbability"], "awayWin": 1-summary["homeWinProbability"]},
        "expectations": {"homeRuns": summary["meanHomeRuns"], "awayRuns": summary["meanAwayRuns"],
                         "totalRuns": summary["meanTotalRuns"], "homeMinusAwayRuns": summary["meanRunDifferential"]},
        "distributions": {"homeRunDistribution": _distribution(home), "awayRunDistribution": _distribution(away),
            "totalRunDistribution": _distribution(home+away), "runDifferentialDistribution": _distribution(home-away)},
        "simulation": {"simulatorId": "V18_WHOLE_GAME_TRANSITION_SHRINKAGE_RESEARCH", "simulatorVersion": config_sha,
            "seed": seed, "simulationCount": count, "pairedPopulationFile": "paired-populations.npz",
            "monteCarloStandardError": float(np.sqrt(summary["homeWinProbability"]*(1-summary["homeWinProbability"])/count)),
            "seedPolicy": "SeedSequence([masterSeed, first8BytesBigEndianSHA256(canonicalGameId)]).spawn(3): PA,transition,hook",
            "predictiveImprovementEstablished": False},
        "componentsApplied": [{"componentId": "MLB_V18_HGB_PA", "ran": True},
            {"componentId": COMPONENT_ID, "ran": transition_ran, **({"fallbackReason": fallback_reason} if not transition_ran else {})}],
        "eligibility": {"eligible": True, "status": "PREGAME_RESEARCH_SHADOW", "outcomesRead": False},
        "sourcePairSha256": pair_ref["sha256"], "knownLimitations": [
            "Frozen V18 training and feature chronology remains qualified.",
            "Finite simulation noise is not evidence of predictive improvement.",
            "V2 consumer support and actual import remain unconfirmed."], **FLAGS}
    files = {"forecast.json": canonical(candidate_forecast), "pair.json": pair_path.read_bytes(),
             "paired-populations.npz": population_path.read_bytes(), "baseline-forecast.json": (directory / "forecast.json").read_bytes(),
             "execution-receipt.json": execution_receipt_path.read_bytes(), "configuration.json": config_bytes}
    if transition_ran:
        files["transition.json"] = component.read_bytes()
    artifacts = [{"relativePath": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                 for name, data in sorted(files.items())]
    object_body = {"schemaVersion": "MLB_ENSEMBLE_CANDIDATE_OBJECT_MANIFEST_V1", "artifacts": artifacts,
                   "sourcePairSha256": pair_ref["sha256"], "configurationSha256": config_sha}
    object_sha = hashlib.sha256(canonical(object_body)).hexdigest()
    object_root = package_root / "objects/sha256" / object_sha
    for name, data in files.items():
        immutable(object_root / name, data)
    immutable(object_root / "manifest.json", canonical({**object_body, "objectSha256": object_sha}))
    for name, item in code_refs.items():
        immutable(package_root / "code" / name, verify_ref(item).read_bytes())
    for name, item in authority_refs.items():
        immutable(package_root / "baseline-authority" / name, verify_ref(item).read_bytes())
    handoff = {"schemaVersion": "AISP_MLB_ENSEMBLE_CANDIDATE_HANDOFF_V2", "artifactType": "PROSPECTIVE",
        "candidate": {"engineId": "MLB_ENSEMBLE_CANDIDATE", "engineVersion": "mlb-v18-transition-shrinkage-v1",
            "modelArtifactSha256": config_sha, "manifestSha256": config_sha}, "baseline": baseline_authority,
        "components": components, "forecasts": [{"sourceGameId": baseline["sourceGameId"], "objectSha256": object_sha,
            "relativePath": object_root.relative_to(package_root).as_posix(), "manifestFile": "manifest.json", "forecastFile": "forecast.json"}],
        "contractExtensionRequired": True, "consumerSupportConfirmed": False,
        "historicalComparisonRole": "SEPARATE_EXPLORATORY_REPLAY_EVIDENCE_ONLY_NOT_FORECAST",
        "sourcePair": pair_ref, "configuration": {"relativePath": "configuration.json", "sha256": config_sha, "bytes": len(config_bytes)},
        "publicationClockNote": "Child forecast retains original pair freeze. This envelope creates no new prospective simulation.", **FLAGS}
    handoff["handoffSha256"] = hashlib.sha256(canonical(handoff)).hexdigest()
    handoff_ref = immutable(package_root / "aisp-handoff.json", canonical(handoff))
    receipt = {"schemaVersion": "MLB_V18_TRANSITION_ADAPTER_PACKAGE_RECEIPT_V2", "packageRoot": str(package_root),
        "handoff": handoff_ref, "logicalHandoffSha256": handoff["handoffSha256"],
        "configuration": configuration_ref, "sourcePair": pair_ref, "objects": 1,
        "baselineDrawIdentityExact": True, "retainedDrawSummariesReconciled": True,
        "outcomeReads": 0, "simulationsRun": 0, "modelLoads": 0, "aispWrites": 0,
        "consumerSupportConfirmed": False, "contractExtensionRequired": True, "componentId": COMPONENT_ID, **FLAGS}
    receipt_ref = immutable(package_root / "package-receipt.json", canonical(receipt))
    validation_paths = [OUTPUT / "verification/focused-contract-checks.json",
                        OUTPUT / "verification" / ("actual-package-check-" + handoff["handoffSha256"] + ".json")]
    current = {**receipt, "receipt": receipt_ref, "artifacts": [
        {**reference(p), "relativePath": p.relative_to(OUTPUT).as_posix()}
        for p in [*sorted(package_root.rglob("*")), *validation_paths] if p.is_file()]}
    atomic_json(OUTPUT / "current.json", current)
    return current


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair-pointer", type=Path, default=SOURCE / "prospective-pair-current.json")
    args = parser.parse_args()
    print(json.dumps(build(args.pair_pointer), indent=2))
