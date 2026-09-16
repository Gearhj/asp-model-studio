"""Seal additive boundary diagnostics without rerunning any model or simulator."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/mlb-v18-population-diagnostics-v1"
HELPER = ROOT / "server/sports_current_statcast/mlb_v18_population_boundaries.py"
HELPER_SHA = "f65f9d243ca5af9911016f873c620fa055a26712d5afc41d5dfadf15ffe6ac4b"
CASES = ("824630", "823496", "824870")
N = 5000


def utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("AWARE_UTC_CLOCK_REQUIRED")
    return result.astimezone(timezone.utc)


def now():
    return datetime.now(timezone.utc)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def bound_bytes(descriptor):
    raw = Path(descriptor["path"]).read_bytes()
    if len(raw) != descriptor["bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
        raise ValueError("BOUND_FILE_MISMATCH: " + descriptor["path"])
    return raw


def read_ref(descriptor):
    return json.loads(bound_bytes(descriptor))


def persist(path, raw):
    """Write once, flush, then independently verify the retained bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("EXISTING_ARTIFACT_PRESERVED: " + str(path))
    descriptor = ref(path)
    if descriptor["sha256"] != hashlib.sha256(raw).hexdigest() or descriptor["bytes"] != len(raw):
        raise ValueError("PERSISTED_ARTIFACT_MISMATCH")
    return descriptor


def save(name, value):
    raw = value if isinstance(value, bytes) else encoded(value)
    return persist(OUT / "objects/sha256" / hashlib.sha256(raw).hexdigest() / name, raw)


def archive_source(role, descriptor):
    archive_path = OUT / "source-code/sha256" / descriptor["sha256"] / Path(descriptor["path"]).name
    # An earlier seal may have preserved the exact loaded version before a later edit.
    if archive_path.exists():
        archived = ref(archive_path)
        if archived["sha256"] != descriptor["sha256"] or archived["bytes"] != descriptor["bytes"]:
            raise ValueError("SOURCE_ARCHIVE_MISMATCH")
    else:
        archived = persist(archive_path, bound_bytes(descriptor))
    return {"role": role, "original": descriptor, "archive": archived}


def check_arrays(arrays, metadata):
    if metadata["simulationCount"] != N or set(arrays) != set(metadata["arrays"]):
        raise ValueError("ARRAY_COVERAGE_OR_SIMULATION_COUNT_MISMATCH")
    for name, value in arrays.items():
        expected = metadata["arrays"][name]
        if value.ndim < 1 or value.shape[0] != N or value.dtype.kind not in "biuf":
            raise ValueError("INVALID_PER_DRAW_ARRAY: " + name)
        if list(value.shape) != expected["shape"] or str(value.dtype) != expected["dtype"]:
            raise ValueError("ARRAY_DESCRIPTOR_MISMATCH: " + name)
        if not np.isfinite(value).all():
            raise ValueError("NONFINITE_ARRAY: " + name)


def require_checks(value, label):
    if value.get("allPassed") is not True or not value.get("checks") or any(v is not True for v in value["checks"].values()):
        raise ValueError(label)


def check_parent(parent, pk, future):
    if parent.get("schemaVersion") != "MLB_V18_POPULATION_DIAGNOSTIC_SIDECAR_V1" or str(parent["sourceGameId"]) != pk:
        raise ValueError("RAW_PARENT_IDENTITY_MISMATCH")
    expected = "PROSPECTIVE_PREGAME_DIAGNOSTIC_CAPTURE" if future else "RETROSPECTIVE_REPRODUCTION_AFTER_OBSERVED_RESULTS"
    if parent["classification"] != expected or parent["simulationConfiguration"]["n_sims"] != N:
        raise ValueError("RAW_PARENT_SCOPE_MISMATCH")
    for key in ("candidateAuthority", "productionAuthority", "calibrationChanges", "newForecastCreated", "originalForecastModified"):
        if parent.get(key) is not False:
            raise ValueError("AUTHORITY_OR_FORECAST_MUTATION: " + key)
    if parent.get("fits") != 0 or parent.get("providerRequests") != 0:
        raise ValueError("UNSUPPORTED_PARENT_EXECUTION")
    invariant = parent["invariance"]
    if (set(invariant["drawArraysExact"]) != {"homeRuns", "awayRuns", "innings", "paCounts"}
            or any(v is not True for v in invariant["drawArraysExact"].values())
            or not invariant["summaryScalarsExact"]
            or any(v is not True for v in invariant["summaryScalarsExact"].values())
            or invariant["representativeTraceExact"] is not True
            or invariant["mismatchedDraws"] != 0 or invariant["maximumAbsoluteDrawDifference"] != 0):
        raise ValueError("RAW_FORECAST_INVARIANCE_FAILED")
    require_checks(parent["counters"]["accounting"], "RAW_ACCOUNTING_FAILED")


def check_future(parent, pk):
    descriptor = json.loads((OUT / "future-declaration.json").read_bytes())
    if descriptor != parent["futureDeclaration"]:
        raise ValueError("FUTURE_DECLARATION_CHANGED")
    declared = read_ref(descriptor)
    for key in ("gameId", "sourceGameId", "baselineObjectSha256", "baselineForecastId", "forecast", "executionInputs", "scheduledStartUtc", "originalCaptureUtc"):
        if declared[key] != parent[key]:
            raise ValueError("FUTURE_BINDING_MISMATCH: " + key)
    if str(declared["sourceGameId"]) != pk or pk == "824225":
        raise ValueError("FUTURE_GAME_SCOPE_MISMATCH")
    if (declared["originalForecastCreatedAt"] != parent["originalForecastCreatedAtUtc"]
            or declared["simulationCount"] != N
            or declared["masterSeed"] != parent["simulationConfiguration"]["master_seed"]):
        raise ValueError("FUTURE_FORECAST_CONFIGURATION_MISMATCH")
    deadline = utc(declared["deadlineUtc"])
    if deadline != utc(declared["scheduledStartUtc"]) - timedelta(minutes=15):
        raise ValueError("ORIGINAL_DEADLINE_MISMATCH")
    if not (utc(declared["declaredAtUtc"]) <= utc(parent["executionStartedAtUtc"]) <= utc(parent["createdAtUtc"]) < deadline):
        raise ValueError("FUTURE_RAW_CLOCK_ORDER_MISMATCH")
    for key in ("outcomesRead", "mechanicsChanges", "candidateAuthority"):
        if declared[key] is not False:
            raise ValueError("FUTURE_DECLARATION_AUTHORITY_MISMATCH")
    return descriptor, declared["deadlineUtc"]


def capture_status(future, completed, deadline):
    if not future:
        return "RETROSPECTIVE_DIAGNOSTIC_ENRICHMENT", False
    eligible = utc(completed) < utc(deadline)
    return ("PROSPECTIVE_DIAGNOSTIC_CAPTURE_COMPLETE" if eligible else "EXPIRED_DIAGNOSTIC_COMPLETION_RESEARCH_ONLY"), eligible


def seal(pk: str, future: bool = False) -> dict:
    pk = str(pk)
    if not pk.isdigit() or len(pk) != 6 or (not future and pk not in CASES):
        raise ValueError("GAME_OUTSIDE_FIXED_COHORT")
    folder = OUT / ("future" if future else "retrospective") / pk
    raw_pointer = ref(folder / "current.json")
    parent_ref = json.loads(bound_bytes(raw_pointer))
    parent = read_ref(parent_ref)
    check_parent(parent, pk, future)
    future_ref, deadline = check_future(parent, pk) if future else (None, None)
    target = folder / "enriched.json"
    if target.exists():
        completion_ref = json.loads(target.read_bytes())
        receipt = read_ref(completion_ref)
        if receipt["parentSidecar"] != parent_ref or receipt["parentPointer"] != raw_pointer:
            raise ValueError("EXISTING_ENRICHMENT_HAS_DIFFERENT_PARENT")
        for key in ("enrichedSidecar", "enrichedPopulation", "boundaryHelper"):
            bound_bytes(receipt[key])
        return {"completion": completion_ref, "sidecar": receipt["enrichedSidecar"], "population": receipt["enrichedPopulation"],
                "status": receipt["status"], "eligibleProspectiveCapture": receipt["eligibleProspectiveCapture"], "reused": True}

    helper_ref = ref(HELPER)
    if helper_ref["sha256"] != HELPER_SHA:
        raise ValueError("BOUNDARY_HELPER_CHANGED")
    sealer_ref = ref(__file__)
    archives = [archive_source(role, parent[role]) for role in ("driver", "collector", "simulator")]
    archives += [archive_source("boundaryHelper", helper_ref), archive_source("sealer", sealer_ref)]
    helper_archive = next(item["archive"] for item in archives if item["role"] == "boundaryHelper")

    with np.load(io.BytesIO(bound_bytes(parent["population"])), allow_pickle=False) as loaded:
        arrays = {name: loaded[name].copy() for name in loaded.files}
    check_arrays(arrays, parent["counters"])
    # Load the archived helper bytes, avoiding a live-source race or stale module cache.
    helper_namespace = {"__name__": "_sealed_population_boundaries", "__file__": helper_archive["path"]}
    exec(compile(bound_bytes(helper_archive), helper_archive["path"], "exec"), helper_namespace)
    enriched, metadata = helper_namespace["enrich_boundaries"](arrays, parent["counters"])
    check_arrays(enriched, metadata)
    require_checks(metadata["boundaryDerivation"], "BOUNDARY_ACCOUNTING_FAILED")
    if any(not np.array_equal(value, enriched[name]) for name, value in arrays.items()):
        raise ValueError("ORIGINAL_ARRAY_MODIFIED")
    if ref(__file__) != sealer_ref:
        raise ValueError("SEALER_CHANGED_DURING_EXECUTION")

    stream = io.BytesIO()
    np.savez_compressed(stream, **enriched)
    population_ref = save("population-diagnostics-enriched.npz", stream.getvalue())
    shared = {"gameId": parent["gameId"], "sourceGameId": pk, "parentPointer": raw_pointer, "parentSidecar": parent_ref,
              "parentPopulation": parent["population"], "enrichedPopulation": population_ref, "counters": metadata,
              "baselineObjectSha256": parent["baselineObjectSha256"], "baselineForecastId": parent["baselineForecastId"],
              "forecast": parent["forecast"], "executionInputs": parent["executionInputs"], "featureSnapshot": parent["featureSnapshot"],
              "originalSourceCutoff": parent["originalSourceCutoff"], "originalCaptureUtc": parent["originalCaptureUtc"],
              "originalForecastCreatedAtUtc": parent["originalForecastCreatedAtUtc"], "scheduledStartUtc": parent["scheduledStartUtc"],
              "futureDeclaration": future_ref, "deadlineUtc": deadline, "boundaryHelper": helper_archive, "sourceArchives": archives,
              "simulationCount": N, "simulationReruns": 0, "extraRandomDraws": 0, "providerRequests": 0, "fits": 0,
              "candidateAuthority": False, "productionAuthority": False, "newForecastCreated": False, "originalForecastModified": False,
              "originalArraysExact": True, "parentAccountingPassed": True, "parentInvariancePassed": True,
              "publicationStatus": "LOCAL_DIAGNOSTIC_ARTIFACT_ONLY", "consumerImportConfirmed": False}
    sidecar_ref = save("enriched-sidecar.json", shared | {"schemaVersion": "MLB_V18_POPULATION_DIAGNOSTIC_ENRICHED_SIDECAR_V1",
                          "createdAtUtc": now().isoformat(), "eligibilityAuthority": "Completion receipt written after persisted-file verification"})
    # Verify both capture payloads before attesting their actual completion clock.
    bound_bytes(population_ref)
    bound_bytes(sidecar_ref)
    completed = now().isoformat()
    status, eligible = capture_status(future, completed, deadline)
    receipt = shared | {"schemaVersion": "MLB_V18_POPULATION_DIAGNOSTIC_COMPLETION_V1", "enrichedSidecar": sidecar_ref,
                        "artifactsCompletedAtUtc": completed, "completedAtUtc": now().isoformat(), "status": status,
                        "eligibleProspectiveCapture": eligible,
                        "clockMeaning": "artifactsCompletedAtUtc is observed after enriched NPZ and sidecar were flushed and their persisted hashes verified; completedAtUtc is subsequent attestation creation. Original forecast clocks remain unchanged."}
    completion_ref = save("completion-receipt.json", receipt)
    # A receipt finishing after cutoff cannot advertise an eligible future capture.
    if future and eligible and now() >= utc(deadline):
        receipt.update({"completedAtUtc": now().isoformat(), "status": "EXPIRED_DIAGNOSTIC_COMPLETION_RESEARCH_ONLY",
                        "eligibleProspectiveCapture": False, "lateReceiptReason": "Receipt persistence crossed original deadline"})
        completion_ref = save("completion-receipt.json", receipt)
    persist(target, encoded(completion_ref))
    return {"completion": completion_ref, "sidecar": sidecar_ref, "population": population_ref,
            "status": receipt["status"], "eligibleProspectiveCapture": receipt["eligibleProspectiveCapture"], "reused": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True)
    parser.add_argument("--future", action="store_true")
    args = parser.parse_args()
    print(json.dumps(seal(args.game, args.future), indent=2), flush=True)
