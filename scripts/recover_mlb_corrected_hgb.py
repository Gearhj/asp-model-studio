"""One explicitly authorized Windows recovery; no automatic or implicit retry.

Run with the repository .venv through the supported Windows approval context.
--verify-only authenticates metadata and the target-free Development mask only.
The exclusive submission intent permanently prohibits a second enqueue here.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import run_mlb_corrected_hgb as original
from server.persistence.db import Database
from server.sports_current_statcast import stage3_model_jobs as jobs
from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_current_statcast.mlb_corrected_hgb_study import (
    ACTOR_USER_ID, PROJECT_ID, content_sha, model_fold_populations,
    probe_threading_infrastructure, read_immutable_json,
)
from server.sports_current_statcast.stage3_corrected_eligibility import eligibility_mask
from server.sports_datasets.consumer import canonical_json_bytes

RECOVERY_FOLDER = "corrected-hgb-recovery-1"
RECOVERY_BATCH = "MLB corrected treatment bounded HGB recovery 1"
FAILED_STUDY = "94ce59613407da613b40c1fb7357e148b1053fc064977eeec6efb32acea7e4d0"
FAILED_JOB = "stage3-model-job-86b72c0cee694779bb3cab64eb28cc45"
FAILED_RUN = "cf308ac9f910073a170f5ab6fa5e4adfd969b2eed2ec8e5ff3d17c54ee77cbc8"
FAILED_CANDIDATE = "f9abd8c13bc57d741d6d2758e4491d002684147758e2b9c9d5717ca93067ffea"
ELIGIBILITY_SHA = "04547a356104206a904f38dfa2049f9c67ee2d1822ef39d67cae9d585d6fb985"
V18_ID = "stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638"
V18_MANIFEST = "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3"
SCHEMA_SHA = "357cdf0176098217f51e0451433921e33bf8ebb94f5cbef21898ba53d45212ad"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(event: str, **kwargs) -> None:
    print(json.dumps({"event": event, **kwargs}, sort_keys=True), flush=True)


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recovery_implementation_snapshot(root: Path) -> dict:
    paths = [Path(__file__), ROOT / "scripts" / "run_mlb_corrected_hgb.py",
             ROOT / "scripts" / "verify_mlb_hgb_recovery_authority.py",
             ROOT / "server" / "sports_current_statcast" / "mlb_hgb_recovery_telemetry.py"]
    content = {"schemaVersion": "MLB_HGB_RECOVERY_OBSERVATIONAL_SOURCE_SNAPSHOT_V1",
               "scope": "COORDINATION_AND_TELEMETRY_ONLY_FROZEN_V18_SCIENTIFIC_IMPLEMENTATION_UNMODIFIED",
               "files": [{"path": str(path.resolve()), "sha256": sha_file(path),
                          "sourceBytesBase64": base64.b64encode(path.read_bytes()).decode("ascii")} for path in paths]}
    checksum = content_sha(content)
    path = root / "objects" / f"{checksum}.json"
    original._append_exact(path, content)
    return {"path": str(path.resolve()), "sha256": checksum, "sourceFiles": [{k: v for k, v in row.items() if k != "sourceBytesBase64"} for row in content["files"]]}


def immutable_predecessor(database: Database) -> dict:
    root = lab._runtime_root()
    old = json.loads((root / "corrected-hgb-study" / "study.json").read_bytes())
    if old.get("studyChecksum") != FAILED_STUDY or content_sha({k: v for k, v in old.items() if k != "studyChecksum"}) != FAILED_STUDY:
        raise RuntimeError("Failed study identity changed; recovery prohibited.")
    run_path = root / "objects" / "sha256" / f"{FAILED_RUN}.json"
    candidate_path = root / "candidate-attempts" / "objects" / "sha256" / f"{FAILED_CANDIDATE}.json"
    read_immutable_json(run_path, FAILED_RUN)
    read_immutable_json(candidate_path, FAILED_CANDIDATE)
    job = jobs.get_model_development_job(database, PROJECT_ID, FAILED_JOB)["job"]
    if job["status"] != "PARTIAL" or job["artifacts"].get("runReceiptSha256") != FAILED_RUN:
        raise RuntimeError("Failed study job is not the preserved terminal predecessor.")
    files = sorted((root / "corrected-hgb-study").rglob("*.json")) + [run_path, candidate_path]
    return {"studyChecksum": FAILED_STUDY, "jobId": FAILED_JOB,
            "runReceiptSha256": FAILED_RUN, "candidateReceiptSha256": FAILED_CANDIDATE,
            "jobStateChecksum": content_sha(job),
            "immutableFiles": [{"path": str(path.resolve()), "sha256": sha_file(path)} for path in files],
            "priorScheduledFitSlots": 5, "priorCompletedFolds": 0,
            "priorActualEstimatorFitStarts": None,
            "priorActualEstimatorFitStartsReason": "NOT_INSTRUMENTED_DO_NOT_INFER_FROM_FIVE_SCHEDULED_SLOTS"}


def verify_workers(database: Database) -> dict:
    """Read-only Windows process and queue check; never kills or reclaims locks."""
    if os.name != "nt":
        raise RuntimeError("This recovery is authorized only in the supported Windows context.")
    command = "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], check=True, capture_output=True, text=True)
    processes = json.loads(result.stdout)
    failed_ids = {61036}
    while True:
        children = {int(p["ProcessId"]) for p in processes if int(p["ParentProcessId"]) in failed_ids}
        if children <= failed_ids:
            break
        failed_ids |= children
    survivors = [p for p in processes if int(p["ProcessId"]) in failed_ids]
    active = [j for j in jobs.list_model_development_jobs(database, PROJECT_ID)["jobs"] if j["status"] in {"QUEUED", "RUNNING", "CANCELLING", "CANCEL_REQUESTED"}]
    locks = sorted((lab._runtime_root() / "locks").glob(f"{PROJECT_ID}.model-development*.lock"))
    if survivors or active or locks:
        raise RuntimeError("RECOVERY_WORKERS_NOT_CLEAR: " + json.dumps({"failedProcessTreeSurvivors": survivors, "activeJobs": [j["jobId"] for j in active], "locks": [str(p) for p in locks]}))
    return {"checkedAt": now(), "failedCoordinatorProcessId": 61036,
            "failedProcessTreeSurvivors": survivors, "activeProjectJobs": [], "modelDevelopmentLocks": [],
            "nativeWorkerImplementation": "IN_PROCESS_HGB_OPENMP_AND_JOBLIB_THREAD_POOL_NO_DETACHED_FAILED_MODEL_WORKER",
            "status": "NO_FAILED_ATTEMPT_WORKERS_ACTIVE", "processesTerminated": 0, "locksRemoved": 0}


def verify_development_mask(database: Database, study: dict) -> dict:
    resolved = lab.resolve_model_lab_authority(database, PROJECT_ID)
    feature_set = next(f for f in resolved.feature_sets if f["featureSetId"] == study["authority"]["featureSetId"])
    frame = lab._fold_frame(resolved, feature_set["orderedFeatures"], include_oof_identity=True, include_target=False)
    if {"target", "outcome", "label", "observedClassIndex"}.intersection(frame.columns):
        raise RuntimeError("Target-free recovery eligibility scan unexpectedly contains a target column.")
    mask, receipt = eligibility_mask(frame, feature_set)
    if receipt != study["rowEligibility"] or (len(frame), int(mask.sum()), int((~mask).sum())) != (683662, 683606, 56):
        raise RuntimeError("Actual Development eligibility differs from the exact frozen 56-row hold.")
    folds = []
    for fold in study["folds"]:
        train = lab._date_mask(frame, fold["trainStart"], fold["trainEnd"])
        valid = lab._date_mask(frame, fold["validationStart"], fold["validationEnd"])
        folds.append({"foldNumber": fold["foldNumber"], "registeredTrainRows": int(train.sum()),
                      "registeredValidationRows": int(valid.sum()), "modelTrainRows": int((train & mask).sum()),
                      "modelValidationRows": int((valid & mask).sum()), "heldTrainRows": int((train & ~mask).sum()),
                      "heldValidationRows": int((valid & ~mask).sum())})
    expected = model_fold_populations(study["folds"], receipt)
    for actual, frozen in zip(folds, expected, strict=True):
        if (actual["modelTrainRows"], actual["modelValidationRows"], actual["heldTrainRows"], actual["heldValidationRows"]) != (frozen["trainRows"], frozen["validationRows"], frozen["quarantinedTrainRows"], frozen["quarantinedValidationRows"]):
            raise RuntimeError("Actual chronological masks do not reconcile to the frozen hold ledger.")
    if sum(f["heldValidationRows"] for f in folds) != 51 or sum(f["modelValidationRows"] for f in folds) != 501539:
        raise RuntimeError("Actual OOF population differs from expected 501539 / 51 held.")
    return {"status": "ACTUAL_TARGET_FREE_MASKS_MATCH_FROZEN_FINAL_V18_ELIGIBILITY", "eligibilityChecksum": receipt["eligibilityChecksum"],
            "sourceRows": len(frame), "eligibleRows": int(mask.sum()), "heldRows": int((~mask).sum()), "folds": folds,
            "commonOofRowsExpectedFromMasks": 501539, "heldValidationRows": 51, "targetValuesRead": 0,
            "finalOotPayloadRowsRead": 0, "predictiveEstimatorFits": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    expected_executable = ROOT / ".venv" / "Scripts" / "python.exe"
    if Path(sys.executable).resolve() != expected_executable.resolve() or Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        raise RuntimeError("Recovery requires the repository's intended .venv/Scripts/python.exe.")
    subprocess.run(["git", "merge-base", "--is-ancestor", "227f1a8", "HEAD"], cwd=ROOT, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    database = Database(original.DATABASE_PATH)
    root = lab._runtime_root() / RECOVERY_FOLDER
    root.mkdir(parents=True, exist_ok=True)
    if (root / "submission-intent.json").exists():
        raise RuntimeError("RECOVERY_ATTEMPT_ALREADY_CLAIMED: no second submission or automatic retry is authorized. Inspect this recovery's existing job/receipts.")
    if any((j.get("plan") or {}).get("batchName") == RECOVERY_BATCH for j in jobs.list_model_development_jobs(database, PROJECT_ID)["jobs"]):
        raise RuntimeError("RECOVERY_JOB_ALREADY_EXISTS: no further enqueue permitted.")
    predecessor = immutable_predecessor(database)
    worker_verification = verify_workers(database)
    emit("FAILED_WORKERS_VERIFIED_ABSENT", **worker_verification)
    probe = probe_threading_infrastructure()
    emit("SUPPORTED_WINDOWS_THREAD_POOL_PROBE_PASS", **probe)
    from scripts.verify_mlb_hgb_recovery_authority import verify_authority
    authority_verification = verify_authority(database)
    eligibility_path = lab._runtime_root() / "objects" / "corrected-preprocessing" / "sha256" / f"{ELIGIBILITY_SHA}.json"
    read_immutable_json(eligibility_path, ELIGIBILITY_SHA)
    payload, study = original.validated_study(database, eligibility_path, batch_name=RECOVERY_BATCH)
    if study["authority"]["treatmentSpecificationId"] != V18_ID or study["authority"]["treatmentVersion"] != 18:
        raise RuntimeError("The actual registered training authority is not the frozen adopted V18.")
    study["authority"].update(treatmentManifestChecksum=V18_MANIFEST, modelFeatureSchemaChecksum=SCHEMA_SHA)
    mask_verification = verify_development_mask(database, study)
    emit("FINAL_V18_AND_ACTUAL_MASKS_VERIFIED", treatmentSpecificationId=V18_ID, manifest=V18_MANIFEST, registeredInputs=273, **mask_verification)
    if args.verify_only:
        emit("RECOVERY_VERIFY_ONLY_COMPLETE", authorityVerification=authority_verification, estimatorFits=0, submissionCount=0)
        return
    recovery_id = "mlb-corrected-hgb-recovery-1-" + uuid.uuid4().hex
    # Recheck immediately before claiming the one permitted submission.
    worker_verification = verify_workers(database)
    recovery = {"recoveryId": recovery_id, "recoveryAttemptNumber": 1, "createdAt": now(), "checkoutHead": head,
                "predecessor": predecessor, "failedStudyChecksum": FAILED_STUDY,
                "authorityVerification": authority_verification, "preflightCompatibility": authority_verification,
                "actualDevelopmentMaskVerification": mask_verification, "workerVerification": worker_verification,
                "executionContext": "SUPPORTED_WINDOWS_REQUIRE_ESCALATED_REPOSITORY_VENV",
                "pythonExecutable": sys.executable, "pythonPrefix": sys.prefix,
                "observationalImplementationSnapshot": recovery_implementation_snapshot(root),
                "infrastructureProbe": probe,
                "actualFitTelemetry": {"path": str((root / "fit-events.jsonl").resolve()), "accountingPath": str((root / "fit-accounting.json").resolve())},
                "noAutomaticRetry": True, "maximumEstimatorFits": 5, "nativeWorkers": 4}
    study["recovery"] = recovery
    study["authorization"] = "ONE_EXPLICIT_RECOVERY_OF_FAILED_STUDY_EXACT_SAVED_HGB_FIVE_FOLDS_NO_RETRY_NO_RETUNING"
    study["studyChecksum"] = content_sha({k: v for k, v in study.items() if k != "studyChecksum"})
    original._append_exact(root / "study.json", study)
    original._append_exact(root / "objects" / f"{study['studyChecksum']}.json", study)
    from server.sports_current_statcast.mlb_hgb_recovery_telemetry import observe_recovery
    entry_authority = lab.resolve_model_lab_authority(database, PROJECT_ID)
    if entry_authority.split["contractId"] != study["authority"]["splitContractId"] or entry_authority.split["checksum"] != study["authority"]["splitChecksum"]:
        raise RuntimeError("Registered chronological split changed before recovery submission.")
    expected = {"recoveryId": recovery_id, "treatmentManifestChecksum": V18_MANIFEST,
                "featureSetId": study["authority"]["featureSetId"], "featureSetChecksum": study["authority"]["featureSetChecksum"],
                "modelFeatureSchemaChecksum": SCHEMA_SHA, "sourceOrderedFeatures": study["authority"]["sourceOrderedFeatures"],
                "orderedFeatures": study["authority"]["orderedFeatures"], "folds": entry_authority.split["contract"]["folds"],
                "splitContractId": study["authority"]["splitContractId"], "splitChecksum": study["authority"]["splitChecksum"],
                "baseSeed": study["seed"], "hyperparameters": study["hyperparameters"], "nativeWorkers": 4,
                "targetOrder": study["targetOrder"],
                "eligibilityChecksum": study["rowEligibility"]["eligibilityChecksum"],
                "sourceRows": 683662, "eligibleRows": 683606, "heldRows": 56,
                "boundSourceHashes": authority_verification["boundSourceHashesPhysical"],
                "estimatorParametersByFold": {str(f["foldNumber"]): lab._model("histogram_gradient_boosting", study["seed"] + int(f["foldNumber"]), hyperparameters=study["hyperparameters"], native_workers=4).get_params(deep=False) for f in study["folds"]}}
    started = time.perf_counter()
    job = None
    with observe_recovery(event_path=root / "fit-events.jsonl", expected=expected, lab_module=lab, jobs_module=jobs) as observer:
        try:
            # Exclusive, durable intent closes the enqueue/receipt crash gap.
            with (root / "submission-intent.json").open("xb") as stream:
                stream.write(canonical_json_bytes({"recoveryId": recovery_id, "studyChecksum": study["studyChecksum"], "planChecksum": study["plan"]["checksum"], "atMostOneSubmission": True}))
                stream.flush()
                os.fsync(stream.fileno())
            emit("RECOVERY_SINGLE_SUBMISSION", recoveryId=recovery_id, studyChecksum=study["studyChecksum"], scheduledFitSlots=5, actualEstimatorFitStarts=0, completedFolds=0)
            job = jobs.enqueue_model_development_job(database, PROJECT_ID, {**payload, "expectedPlanId": study["plan"]["planId"], "expectedPlanChecksum": study["plan"]["checksum"]}, actor_user_id=ACTOR_USER_ID)["job"]
            original._append_exact(root / "submission.json", {"recoveryId": recovery_id, "studyChecksum": study["studyChecksum"], "jobId": job["jobId"], "planChecksum": study["plan"]["checksum"]})
            previous = None
            while True:
                job = jobs.get_model_development_job(database, PROJECT_ID, job["jobId"])["job"]
                accounting = observer.summary()
                progress = job.get("progress") or {}
                snapshot = (job["status"], progress.get("completedFits"), progress.get("failedFits"), progress.get("message"), accounting.get("actualFitStarts"))
                if snapshot != previous:
                    emit("RECOVERY_PROGRESS", jobId=job["jobId"], status=job["status"], progress=progress, actualFitAccounting=accounting)
                    previous = snapshot
                if job["status"] in original.TERMINAL:
                    break
                time.sleep(10)
        except BaseException as exc:
            original._append_exact(root / "coordinator-failure.json", {"recoveryId": recovery_id, "errorType": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc(), "actualFitAccounting": observer.summary(), "noRetry": True})
            raise
        finally:
            # Never restore observational wrappers while a dispatched worker
            # may still be fitting. The executor is a single bounded job.
            jobs._EXECUTOR.shutdown(wait=True)
    accounting = observer.summary()
    original._append_exact(root / "fit-accounting.json", accounting)
    preservation = immutable_predecessor(database)
    if preservation != predecessor:
        raise RuntimeError("Preserved failed study/attempt/receipts changed during recovery.")
    terminal = {"recoveryId": recovery_id, "studyChecksum": study["studyChecksum"], "jobId": job["jobId"],
                "status": job["status"], "progress": job.get("progress") or {}, "artifacts": job.get("artifacts") or {},
                "error": job.get("error") or {}, "actualFitAccounting": accounting, "recoveryRuntimeSeconds": time.perf_counter() - started,
                "predecessorUnchangedVerified": True}
    original._append_exact(root / "terminal.json", terminal)
    emit("RECOVERY_TERMINAL", **terminal)
    if job["status"] != "COMPLETE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
