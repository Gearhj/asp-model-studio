"""Freeze and run exactly one corrected-treatment HGB configuration, five folds.

--plan-only is a preview with no enqueue or study-file mutation. Execution
freezes its complete study before enqueue. Later invocations only monitor an
existing study job, including terminal failures; they never retry model fits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
os.environ.setdefault("ATLAS_SECURITY_ROOT", str(RUNTIME_ROOT / "security"))
os.environ.setdefault("ATLAS_SECURITY_DB_PATH", str(RUNTIME_ROOT / "security" / "asp_model_studio_security.db"))

from server.persistence.db import Database
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_corrected_hgb_study import (
    ACTOR_USER_ID, BASELINE_CANDIDATE_ID, BASELINE_CANDIDATE_SHA, BASELINE_RUN_SHA,
    BATCH_NAME, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, FEATURE_SET_KEY, PROJECT_ID,
    STUDY_SCHEMA, SUBGROUPS, baseline_authority, content_sha, exact_experiment, execution_resource_comparison,
    fold_population, matching_job, model_fold_populations, probe_threading_infrastructure, validate_eligibility_receipt, validate_single_plan,
)
from server.sports_current_statcast.stage3_model_jobs import (
    enqueue_model_development_job, get_model_development_job,
    list_model_development_jobs, plan_model_development_queue,
)
from server.sports_current_statcast.stage3_model_laboratory import resolve_model_lab_authority, _runtime_root

DATABASE_PATH = RUNTIME_ROOT / "persistence" / "asp_model_studio.db"
TERMINAL = {"COMPLETE", "PARTIAL", "FAILED", "CANCELLED", "CANCELLED_PARTIAL"}


def study_directory() -> Path:
    return _runtime_root() / "corrected-hgb-study"


def _append_exact(path: Path, payload: dict[str, Any]) -> None:
    raw = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError(f"Append-only study object already exists with different contents: {path}")
        return
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != raw:
            raise RuntimeError(f"Concurrent study object conflicts: {path}")


def validated_study(database: Database, eligibility_receipt: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_run, baseline, seed = baseline_authority()
    resolved = resolve_model_lab_authority(database, PROJECT_ID)
    selected = [row for row in resolved.feature_sets if row.get("featureSetKey") == FEATURE_SET_KEY]
    if len(selected) != 1:
        raise RuntimeError("Exactly one registered corrected HGB feature set is required.")
    feature_set = selected[0]
    contract = feature_set.get("transformationContracts") or {}
    if (contract.get("semanticTreatmentVersion") != "MLB_SEMANTIC_TREATMENT_V1"
            or len(feature_set.get("orderedFeatures") or []) != 273
            or len(contract.get("sourceOrderedFeatures") or []) != 218):
        raise RuntimeError("Corrected treatment must bind its actual 273-column schema and original 218 source fields.")
    if contract["sourceOrderedFeatures"] != baseline.get("orderedFeatures"):
        raise RuntimeError("Corrected source feature identity/order differs from the exact immutable V14 baseline; no planning or fits are permitted.")
    treatment = resolved.treatment_specification or {}
    if treatment.get("status") != "ADOPTED" or int(treatment.get("specificationVersion") or 0) <= 14:
        raise RuntimeError("An adopted immutable successor to V14 is required.")
    split = resolved.split
    if (int(split["development"]["rows"]) != 683662 or int(split["finalOot"]["rows"]) != 14067
            or split["finalOot"].get("locked") is not True):
        raise RuntimeError("The frozen Development or sealed Final OOT population changed.")
    if fold_population(split["contract"]["folds"]) != fold_population(baseline["folds"]):
        raise RuntimeError("Corrected and baseline chronological game-grouped fold populations differ.")
    evidence_raw = eligibility_receipt.read_bytes()
    row_eligibility = json.loads(evidence_raw)
    validate_eligibility_receipt(row_eligibility, feature_set)
    import hashlib
    eligibility_reference = {"path": str(eligibility_receipt.resolve()), "fileSha256": hashlib.sha256(evidence_raw).hexdigest(), "eligibilityChecksum": row_eligibility["eligibilityChecksum"]}
    payload = {
        "projectId": PROJECT_ID, "authorityKey": resolved.authority_key,
        "splitContractId": split["contractId"], "seed": seed, "batchName": BATCH_NAME,
        "parallelWorkers": 1,
        "experiments": [exact_experiment(str(feature_set["featureSetId"]), baseline, seed)],
    }
    plan = plan_model_development_queue(database, PROJECT_ID, payload, actor_user_id=ACTOR_USER_ID)
    validate_single_plan(plan, hyperparameters=baseline["hyperparameters"], seed=seed, feature_set_id=feature_set["featureSetId"])
    resources = execution_resource_comparison(baseline_run, baseline, plan)
    content = {
        "schemaVersion": STUDY_SCHEMA, "projectId": PROJECT_ID,
        "authorization": "ONE_CORRECTED_HGB_CONFIGURATION_FIVE_REGISTERED_FOLDS_EXPLICIT_FROZEN_QUARANTINE_NO_RETRY_NO_RETUNING",
        "baseline": {"runReceiptSha256": BASELINE_RUN_SHA, "candidateId": BASELINE_CANDIDATE_ID, "candidateReceiptSha256": BASELINE_CANDIDATE_SHA, "meanOofLogLoss": baseline["meanOofLogLoss"], "evaluationEvidence": baseline["evaluationEvidence"], "experimentId": baseline["experimentId"], "featureSetChecksum": baseline["featureSetChecksum"], "orderedFeatures": baseline["orderedFeatures"]},
        "authority": {"authorityKey": resolved.authority_key, "treatmentSpecificationId": treatment["specificationId"], "treatmentVersion": treatment["specificationVersion"], "treatmentChecksum": treatment["checksum"], "featureSetId": feature_set["featureSetId"], "featureSetChecksum": feature_set["checksum"], "featureCount": 273, "sourceFeatureCount": 218, "orderedFeatures": feature_set["orderedFeatures"], "sourceOrderedFeatures": contract["sourceOrderedFeatures"], "splitContractId": split["contractId"], "splitChecksum": split["checksum"]},
        "development": split["development"], "finalOot": {**split["finalOot"], "payloadAccessAuthorized": False},
        "folds": fold_population(baseline["folds"]), "targetOrder": baseline_run["identity"]["targetOrder"],
        "modelFoldPopulations": model_fold_populations(baseline["folds"], row_eligibility),
        "rowEligibility": row_eligibility, "rowEligibilityReceipt": eligibility_reference,
        "sourceFeatureOrderMatchesBaselineExactly": True, "executionResourceComparison": resources,
        "hyperparameters": baseline["hyperparameters"], "seed": seed,
        "foldSeeds": [{"foldNumber": int(row["foldNumber"]), "seed": seed + int(row["foldNumber"])} for row in baseline["folds"]],
        "metricAggregation": "POOLED_OOF_OBSERVATION_WEIGHTED_EQUALS_EXISTING_MEAN_OOF_LOG_LOSS_FIELD",
        "comparison": {"direction": "CORRECTED_MINUS_V14", "matchingKeys": ["canonicalPaId", "canonicalGameId", "foldNumber", "observedClassIndex"], "bootstrapMethod": "PAIRED_NONPARAMETRIC_BOOTSTRAP_CLUSTERED_BY_CANONICAL_GAME_ID", "bootstrapReplicates": BOOTSTRAP_REPLICATES, "bootstrapSeed": BOOTSTRAP_SEED, "weighting": "SUM_PA_LOSSES_DIV_SUM_PA_COUNTS_WITHIN_RESAMPLED_GAMES", "changedCoverage": "REPORT_BOTH_ORIGINAL_POPULATIONS_AND_OUTCOME_INDEPENDENT_EXCLUSION_REASONS_PLUS_MATCHED_COMPARISON"},
        "subgroups": list(SUBGROUPS), "parentOnlyAblations": "DEFERRED_BY_EXPLICIT_USER_DECISION",
        "nextPriority": "BET_READINESS_AND_QUALIFICATION_AFTER_CHALLENGER_FINALIZATION",
        "plan": plan,
    }
    return payload, {**content, "studyChecksum": content_sha(content)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--eligibility-receipt", type=Path, help="Required on initial planning: full Development-only preflight eligibility JSON, frozen before fits.")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if not 1 <= args.poll_seconds <= 30:
        raise ValueError("Polling interval must be 1–30 seconds.")
    database = Database(DATABASE_PATH)
    root = study_directory()
    frozen_path = root / "study.json"
    payload = None
    if frozen_path.exists():
        study = json.loads(frozen_path.read_bytes())
        if content_sha({key: value for key, value in study.items() if key != "studyChecksum"}) != study.get("studyChecksum"):
            raise RuntimeError("Saved study checksum does not reconcile.")
    else:
        if args.eligibility_receipt is None:
            raise RuntimeError("Initial planning requires --eligibility-receipt from the completed preprocessing-only preflight.")
        payload, study = validated_study(database, args.eligibility_receipt)
    jobs = list_model_development_jobs(database, PROJECT_ID)["jobs"]
    job = matching_job(jobs, study)
    print(json.dumps({"event": "PLAN_PREVIEW" if args.plan_only else "STUDY_VALIDATED", "studyChecksum": study["studyChecksum"], "planId": study["plan"]["planId"], "planChecksum": study["plan"]["checksum"], "totalConfigurations": 1, "totalFits": 5, "featureCount": 273, "existingJobId": job.get("jobId") if job else None, "hyperparameters": study["hyperparameters"], "seed": study["seed"], "finalOotLocked": True}, sort_keys=True), flush=True)
    if args.plan_only:
        return
    _append_exact(frozen_path, study)
    _append_exact(root / "objects" / f"{study['studyChecksum']}.json", study)
    if job is None:
        # Durable intent closes the crash gap between enqueue and job-id
        # recording. A later invocation may discover the ledger job, but may
        # never blindly re-enqueue an uncertain submission.
        intent_path = root / "submission-intent.json"
        if intent_path.exists():
            raise RuntimeError("An earlier bounded-study submission is uncertain and has no discoverable job. Refusing to launch another five fits.")
        if payload is None:
            payload, proposed = validated_study(database, Path(study["rowEligibilityReceipt"]["path"]))
            if proposed != study:
                raise RuntimeError("Current proposal differs from the already frozen study; no new fits are permitted.")
        # This primitive-only permission check precedes the first durable
        # submission intent. Existing jobs, including terminal failures, never
        # enter this branch and are never retried by the probe.
        try:
            probe = probe_threading_infrastructure()
        except Exception as exc:
            print(json.dumps({"event": "INFRASTRUCTURE_PREFLIGHT_FAILED_BEFORE_SUBMISSION", "error": str(exc), "estimatorFits": 0, "sportsDataRows": 0, "additionalSubmissions": 0}, sort_keys=True), flush=True)
            raise
        print(json.dumps({"event": "INFRASTRUCTURE_PREFLIGHT_PASS_BEFORE_SUBMISSION", **probe}, sort_keys=True), flush=True)
        intent = {"studyChecksum": study["studyChecksum"], "planChecksum": study["plan"]["checksum"], "atMostOneSubmission": True}
        try:
            with intent_path.open("xb") as stream:
                stream.write(canonical_json_bytes(intent))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise RuntimeError("Another process already claimed this bounded submission; resume its ledger job instead.") from exc
        result = enqueue_model_development_job(database, PROJECT_ID, {**payload, "expectedPlanId": study["plan"]["planId"], "expectedPlanChecksum": study["plan"]["checksum"]}, actor_user_id=ACTOR_USER_ID)
        job = result["job"]
        _append_exact(root / "submission.json", {"studyChecksum": study["studyChecksum"], "jobId": job["jobId"], "planChecksum": study["plan"]["checksum"]})
    print(json.dumps({"event": "MONITORING", "jobId": job["jobId"], "noAutomaticRetry": True}, sort_keys=True), flush=True)
    previous = None
    while True:
        job = get_model_development_job(database, PROJECT_ID, job["jobId"])["job"]
        progress = job.get("progress") or {}
        snapshot = (job["status"], progress.get("completedFits"), progress.get("failedFits"), progress.get("message"))
        if snapshot != previous:
            print(json.dumps({"event": "PROGRESS", "jobId": job["jobId"], "status": job["status"], "completedFits": progress.get("completedFits"), "failedFits": progress.get("failedFits"), "totalFits": progress.get("totalFits"), "message": progress.get("message")}, sort_keys=True), flush=True)
            previous = snapshot
        if job["status"] in TERMINAL:
            terminal = {"studyChecksum": study["studyChecksum"], "jobId": job["jobId"], "status": job["status"], "progress": progress, "artifacts": job.get("artifacts") or {}, "error": job.get("error") or {}}
            _append_exact(root / "terminal.json", terminal)
            print(json.dumps({"event": "TERMINAL", **terminal}, sort_keys=True), flush=True)
            if job["status"] != "COMPLETE":
                raise SystemExit(2)
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
