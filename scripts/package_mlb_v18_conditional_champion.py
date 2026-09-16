"""Bounded frozen-reference packaging and explicitly authorized Model Studio registration.

No provider requests, AISP writes, model fitting, simulation, or OOT access.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.model_registry import mlb_v18_conditional as contract

OUT = contract.OUT
FROZEN = OUT / "frozen-model/sha256/6297787b57e7e74436036e75b40cf67339115f0cbf6333406766179c9569a235/model-bindings.json"
TIMING = OUT / "development-integrity/sha256/853fc330c98e56e987905980e06225190cbe8985c4c19f4c2b035c20dba2078f/manifest.json"
OPS = OUT / "operational-readiness/sha256/52f69bf3e78c9657a5fbd169c520f17fb77104f335f43ae9860a033b3f80a0a7/operational-readiness.json"
DB = ROOT / ".runtime/asp-model-studio/persistence/asp_model_studio.db"
BOUNDARY = "2026-09-12T04:00:00Z"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def immutable(section, name, value):
    data = (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    sha = hashlib.sha256(data).hexdigest()
    path = OUT / section / "sha256" / sha / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable collision")
    else:
        with path.open("xb") as handle:
            handle.write(data)
    return contract.descriptor(path)


def prepare(created_at):
    creation = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if creation.utcoffset() is None or creation > datetime.now(timezone.utc):
        raise ValueError("Creation must be an actual observed, timezone-aware timestamp, never future-dated")
    for path in (FROZEN, TIMING, OPS):
        if contract.descriptor(path)["sha256"] != path.parent.name:
            raise ValueError("Input manifest checksum mismatch")
    frozen = read(FROZEN)
    run = read(frozen["modelIdentity"]["trainingRunReceipt"]["path"])
    assets = [contract.descriptor(p) for p in (FROZEN, TIMING, OPS)]
    assets.extend({k: ref[k] for k in ("path", "sha256", "bytes")} for ref in frozen["assets"])
    pa = dict(frozen["paArtifact"], **frozen["modelStore"])
    pa["relativePath"] = frozen["modelStore"]["reference"]["relativePath"]
    manifest = {
        "schemaVersion": "MLB_V18_CONDITIONAL_CHAMPION_V1", "createdAt": created_at,
        "projectId": contract.PROJECT, "modelId": contract.MODEL,
        "status": contract.STATUS, "authority": dict.fromkeys(contract.FLAGS, True),
        "authorization": {"requestSha256": contract.DECISION_SHA, "decisionMaker": "James",
                          "basis": "Explicit conditional prospective selection; not a clean-validation promotion"},
        "modelIdentity": frozen["modelIdentity"], "paArtifact": pa,
        "artifactReferences": list({r["path"]: r for r in assets}.values()),
        "frozenBindings": contract.descriptor(FROZEN),
        "targetContract": dict(frozen["targetContract"], targetName="outcome"),
        "featureContract": frozen["featureContract"],
        "fittedPreprocessor": frozen["fittedPreprocessor"], "calibration": frozen["calibration"],
        "simulation": frozen["simulator"],
        "trainingIdentity": dict(frozen["trainingPopulation"],
            trainingRunId=run["runId"], datasetId=run["identity"]["goldDatasetId"],
            datasetVersionId=run["identity"]["datasetVersionId"],
            originalTrainingTimestamp=run["createdAt"], timestampMeaning="original_run_receipt_not_registration_time",
            registeredSourceIdentity=run["identity"]),
        "exactReload": frozen["exactReload"],
        "historicalIntegrityLimitation": "Delayed/resumed-game completion was mistaken for original event-date availability. Fold 2 includes at least 55 later-played labels in BOS202406260; all five fitted preprocessing states and historical rolling-feature provenance require review. No clean five-fold point-in-time validation claim. Stored numerical results preserved, not repaired or relabeled.",
        "developmentIntegrity": contract.descriptor(TIMING), "operationalReadiness": contract.descriptor(OPS),
        "predecessor": {"name": "GEN1/AISP_BASELINE", "location": "AISP historical operational control",
            "modelStudioPredecessorRegistryRow": None, "reason": "No preexisting MLB Model Studio registry row found; no fabricated predecessor version.",
            "historyUnchanged": True, "v21ForecastingIdentityMustNotBeOverwritten": True},
        "otherResearch": {"V19": "STOPPED_INCOMPLETE_RESEARCH_ARTIFACTS_PRESERVED", "V18_RF": "NON_OPERATIONAL_UNRECOVERED_RF_NO_RECONSTRUCTION"},
        "prospectiveUse": "Primary MLB forecasting identity; per-game publication remains conditional on valid pregame evidence. No forecast means explicit skip.",
        "wageringAuthority": "VIRTUAL_RESEARCH_ONLY_AFTER_AISP_PROSPECTIVE_ACTIVATION_AND_EXISTING_POLICY_GATES",
        "realMoneyExecutionAllowed": False, "executionAllowedInAISP": False,
        "originalResearchManifestsUnchanged": True,
    }
    ref = immutable("champion", "champion-manifest.json", manifest)
    contract.verify_manifest(ref["path"], ref["sha256"])
    return ref


def register(manifest, sha, actor):
    if not DB.is_file():
        raise ValueError("Exact existing Model Studio database missing; no initialization allowed")
    os.environ["ATLAS_SQLITE_PATH"] = str(DB)
    from server.model_registry import model_registry_service as service
    from server.persistence.service import get_persistence_service, PersistenceService
    from server.persistence.db import Database
    project = get_persistence_service().projects.get(contract.PROJECT)
    if not project or project.get("owner_user_id") != actor:
        raise ValueError("Explicit local decision actor must match existing project owner")
    user = {"userId": actor}
    result = service.register_mlb_v18_conditional_champion(user, manifest, sha)
    reused = service.register_mlb_v18_conditional_champion(user, manifest, sha)
    fresh_service = PersistenceService(Database(DB))
    row = fresh_service.model_versions.get(result["modelVersionId"])
    verified = contract.verify_record(fresh_service, row)
    pointer = fresh_service.models.get(contract.MODEL)["current_version_id"]
    if pointer != row["model_version_id"] or reused["operation"] != "EXACT_REUSE":
        raise ValueError("Durable champion pointer or idempotency mismatch")
    recovered = service.get_recovery_status(user, contract.PROJECT, pointer)
    pipeline = service.load_version_artifact(user, pointer, expected_project_id=contract.PROJECT)
    if len(pipeline.ordered_features) != 246 or pipeline.estimator.n_features_in_ != 436:
        raise ValueError("Frozen reload dimensions mismatch")
    resolution = service.resolve_current_version_by_exact_context(user, project_id=contract.PROJECT,
        dataset_id=row["dataset_id"], dataset_version_id=row["dataset_version_id"], target_name=row["target_name"])
    if resolution["modelVersionId"] != pointer or resolution["status"] != contract.STATUS:
        raise ValueError("Exact-context champion resolution mismatch")
    return immutable("registration", "registration-receipt.json", {
        "schemaVersion": "MLB_V18_CONDITIONAL_REGISTRATION_RECEIPT_V1",
        "registeredAt": row["created_at"], "database": str(DB), "actorUserId": actor,
        "modelId": contract.MODEL, "modelVersionId": pointer, "manifest": contract.descriptor(manifest),
        "idempotentExactReuseVerified": True, "newConnectionPointerVerified": True,
        "exactContextResolutionVerified": True, "pipelineReloaded": True,
        "paArtifactSha256": contract.PA_SHA, "recovery": recovered,
        "fits": 0, "inferenceCalls": 0, "aispWrites": 0, "finalOotReads": 0,
        "historicalResultsChanged": False, "registryLifecycle": verified["status"]})


def package(manifest, sha, registration):
    if datetime.now(timezone.utc) >= datetime.fromisoformat(BOUNDARY.replace("Z", "+00:00")):
        raise ValueError("Prospective boundary missed; a separately versioned future-boundary supplement is required")
    contract.verify_manifest(manifest, sha)
    registered = read(registration)
    if registered["manifest"]["sha256"] != sha:
        raise ValueError("Registration references a different champion")
    frozen, ops = read(FROZEN), read(OPS)
    handoff_path = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/handoffs/sha256/8f63f8a4384288a6b90613eedea5c69c698914a922bd2ee607018a4adfcb7dc5/aisp-handoff.json"
    receipt_path = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/slates/2026-09-10/sha256/929c4f012e40884b955c7a3defc4272d03e52f0aecae9786f9f6cf1966ae5da8/slate-result.json"
    command = f'& "C:\\Users\\james\\ai-sports-predictor\\.venv\\Scripts\\python.exe" -m scripts.mlb_v18_daily_slate import --handoff "{handoff_path}" --receipt "{receipt_path}"'
    era = {
        "structure": "NEW_EXPLICIT_V18_EXPERIMENT_IDENTITY",
        "experimentId": "ASP_MLB_V18_CONDITIONAL_VIRTUAL_20260912_V1",
        "effectiveAtUtc": BOUNDARY, "effectiveAtAmericaNewYork": "2026-09-12T00:00:00-04:00",
        "state": "PENDING_CLAUDE_ACTIVATION_NOT_ALREADY_EFFECTIVE",
        "reason": "Existing AISP experiment binds one controlling_engine; decisions reference Gen1 forecasts. No safe immutable model-era contract is presently implemented. Preserve V2.1 and use an explicitly distinct V18 experiment, not an invisible model substitution.",
        "lastGen1EligibleDecision": {"predicate": "MLB only, predecessor ASP PRACTICAL PREGAME BANKROLL — 2026 V2.1 experiment, AISP_BASELINE/Gen1 forecast identity, immutable committed decisionAt < effectiveAtUtc, ordered by (decisionAt, decisionId)", "decisionId": None, "capture": "Claude must record actual predecessor experiment UUID and final decision ID atomically at boundary"},
        "firstV18EligibleDecision": {"predicate": "MLB only, new ASP_MLB_V18_CONDITIONAL_VIRTUAL_20260912_V1 experiment only, first decisionAt >= effectiveAtUtc with exact V18 pregame forecast, matching event, eligible contemporaneous quote and unchanged V2.1 gates", "decisionId": None, "capture": "record only when it actually exists; zero is valid when all games skip"},
        "bankroll": {"boundaryBalance": None, "reservedOpenStakes": None,
            "captureRequired": "Atomic realized bankroll and open-position reserve snapshot at boundary; no fabricated balance and no fresh duplicate $1000.",
            "openingV18Capital": "Explicit transfer/carry-forward of available virtual capital at the boundary, preserving Gen1 open-position liabilities and subsequent settlements in their original experiment. If safe transfer accounting is unavailable, activate forecasting only and keep V18 position creation disabled.",
            "publicReporting": "Do not combine noncontiguous experiments into an apparent clean V18 track. Preserve Gen1, V18 and any reconciled overall totals separately."},
        "activationPreconditions": ["Claude accepts and schedules activation before the exact boundary; if missed, create a new immutable future-boundary supplement, never backdate", "Atomic Gen1 cutoff and distinct V18 identity; Gen1 forecasts may persist as control but no new Gen1 decisions enter the V18 experiment", "Persist boundary capital/last Gen1 decision and preservation fingerprints; keep future V18 decisions disabled until dependencies verified"],
        "recommendationPolicyVersion": "AISP_PRACTICAL_PREGAME_POLICY_V2_1",
        "stakingPolicyVersion": "AISP_QUARTER_KELLY_EVIDENCE_V2", "minimumAdjustedEdge": 0.02,
        "readinessCutoffQuoteAndStakeRules": "UNCHANGED",
        "historicalDecisionUpdatesAllowed": False, "positionBackfillAllowed": False,
        "gen1FallbackAllowedInV18": False, "realMoneyExecutionAllowed": False,
    }
    value = {
        "schemaVersion": "AISP_MLB_V18_CONDITIONAL_CHAMPION_HANDOFF_V1",
        "modelIdentity": frozen["modelIdentity"], "championManifest": contract.descriptor(manifest),
        "registrationReceipt": contract.descriptor(registration), "frozenBindings": contract.descriptor(FROZEN),
        "developmentIntegrity": contract.descriptor(TIMING), "operationalReadiness": contract.descriptor(OPS),
        "targetAndFeatureContract": "Exact contracts in championManifest; WALK_HBP_CI combined, OTHER_REACH separate,246 raw/273 treated/436 encoded",
        "forecastTimestampSemantics": "Original forecastCreatedAt, not import time. evidenceCutoffAt is latest incorporated source availability, never advanced by packaging. Require evidence<=created<=decision<firstPitch and existing earlier cutoff gates. Event-status uncertainty fails closed.",
        "currentSlateCoverage": ops["slateCounts"],
        "currentForecastPackages": [{"slateDate": p["slateDate"], "forecastCount": p["publishedGames"], "localArtifacts": p["localArtifacts"], "importable": False} for p in ops["exchangePackages"]],
        "existingPregameForecastAndSimulationReferences": frozen["legitimateCurrentInferenceEvidence"],
        "lastNonemptyForecastImport": {"slateDate": "2026-09-10", "historicalEvidenceImportOnly": True,
            "handoff": contract.descriptor(handoff_path), "matchingReceipt": contract.descriptor(receipt_path),
            "workingDirectory": "C:\\Users\\james\\ai-sports-predictor\\server", "exactCommand": command,
            "doesNotActivateChampion": True, "doesNotAuthorizeRetroactiveDecisions": True},
        "activation": {"authorized": True, "performedInAisp": False,
            "existingActivationCommand": None,
            "requiredClaudeImplementation": "Import this content-addressed authority supplement into AISP; persist exact frozen identity and conditional historical-review status; select V18 for prospective primary MLB display/forecasts. Existing daily importer only imports research-shadow evidence and cannot enact this decision. Implement prospective experiment linkage and guard before allowing any virtual decisions. AISP must never execute the estimator.",
            "failClosed": "No valid current V18 forecast means no V18 decision or position, never silent Gen1 fallback; current empty handoffs are accounting-only and must not enter forecast importer.",
            "historicalIntegrity": read(manifest)["historicalIntegrityLimitation"]},
        "modelEra": era,
        "idempotencyIdentity": "mlb-v18-conditional-champion:" + sha + ":" + BOUNDARY,
        "guardImplementation": contract.descriptor(ROOT / "server/model_registry/mlb_v18_conditional.py"),
        "realMoneyExecutionAllowed": False, "executionAllowedInAISP": False,
        "priorArtifactsAndResearchMetadataRemainUnchanged": True,
    }
    return immutable("aisp-handoff", "champion-handoff.json", value)


def verify_handoff(path, sha):
    ref = contract.descriptor(path)
    if ref["sha256"] != sha:
        raise ValueError("Handoff checksum mismatch")
    value = read(path)
    if value["schemaVersion"] != "AISP_MLB_V18_CONDITIONAL_CHAMPION_HANDOFF_V1":
        raise ValueError("Wrong schema")
    for key in ("championManifest", "registrationReceipt", "frozenBindings", "developmentIntegrity", "operationalReadiness", "guardImplementation"):
        contract.verify_reference(value[key])
    contract.verify_manifest(value["championManifest"]["path"], value["championManifest"]["sha256"])
    for ref in (value["lastNonemptyForecastImport"]["handoff"], value["lastNonemptyForecastImport"]["matchingReceipt"]):
        contract.verify_reference(ref)
    era = value["modelEra"]
    if (era["minimumAdjustedEdge"] != 0.02 or era["effectiveAtUtc"] != BOUNDARY
            or era["experimentId"] != "ASP_MLB_V18_CONDITIONAL_VIRTUAL_20260912_V1"
            or era["structure"] != "NEW_EXPLICIT_V18_EXPERIMENT_IDENTITY"
            or era["state"] != "PENDING_CLAUDE_ACTIVATION_NOT_ALREADY_EFFECTIVE"
            or any(era[key] is not False for key in ("gen1FallbackAllowedInV18", "positionBackfillAllowed", "historicalDecisionUpdatesAllowed", "realMoneyExecutionAllowed"))
            or value["realMoneyExecutionAllowed"] is not False or value["executionAllowedInAISP"] is not False
            or value["activation"]["performedInAisp"] is not False):
        raise ValueError("Prospective activation safeguards differ from the authorized handoff")
    boundary_future = datetime.now(timezone.utc) < datetime.fromisoformat(BOUNDARY.replace("Z", "+00:00"))
    return {"sha256": sha, "verified": True, "unactivatedBoundaryStillFuture": boundary_future,
            "lateActivationAllowed": False, "aispWrites": 0, "fits": 0, "inferenceCalls": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "register", "package", "verify"))
    parser.add_argument("--manifest")
    parser.add_argument("--sha256")
    parser.add_argument("--registration")
    parser.add_argument("--actor-user-id")
    parser.add_argument("--created-at")
    args = parser.parse_args()
    if args.mode == "prepare":
        result = prepare(args.created_at or datetime.now(timezone.utc).isoformat())
    elif args.mode == "register":
        result = register(args.manifest, args.sha256, args.actor_user_id)
    elif args.mode == "package":
        result = package(args.manifest, args.sha256, args.registration)
    else:
        result = verify_handoff(args.manifest, args.sha256)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
