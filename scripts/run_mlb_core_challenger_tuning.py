"""Plan or execute the frozen compact MLB Core Challenger tuning study."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
os.environ.setdefault("ATLAS_SECURITY_ROOT", str(RUNTIME_ROOT / "security"))
os.environ.setdefault(
    "ATLAS_SECURITY_DB_PATH", str(RUNTIME_ROOT / "security" / "asp_model_studio_security.db")
)

from server.persistence.db import Database
from server.sports_current_statcast.mlb_core_challenger_tuning import (
    FIRST_SCREEN_BENCHMARKS,
    NULL_BASELINE,
    PROJECT_ID,
    TUNING_BATCH_NAME,
    TUNING_SEED,
    runtime_estimate,
    tuning_experiments,
)
from server.sports_current_statcast.stage3_candidate_evaluation import (
    project_candidate_evaluation,
)
from server.sports_current_statcast.stage3_model_jobs import (
    enqueue_model_development_job,
    get_model_development_job,
    plan_model_development_queue,
)
from server.sports_current_statcast.stage3_model_laboratory import (
    resolve_model_lab_authority,
)


ACTOR_USER_ID = "user_20e0f4e20ec9434c"
DATABASE_PATH = RUNTIME_ROOT / "persistence" / "asp_model_studio.db"
TERMINAL = {"COMPLETE", "PARTIAL", "FAILED", "CANCELLED", "CANCELLED_PARTIAL"}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Resolve and print the signed queue plan without enqueuing any fit.",
    )
    return parser.parse_args()


def _validated_payload(database: Database) -> tuple[dict[str, object], dict[str, object]]:
    resolved = resolve_model_lab_authority(database, PROJECT_ID)
    treatment = resolved.treatment_specification or {}
    feature_set = resolved.feature_sets[0]
    if int(treatment.get("specificationVersion") or 0) != 14:
        raise RuntimeError("The compact tuning study requires adopted treatment V14.")
    if len(feature_set.get("orderedFeatures") or []) != 218:
        raise RuntimeError("The compact tuning study requires the exact 218-predictor authority.")
    if int(resolved.split["development"]["rows"]) != 683_662:
        raise RuntimeError("The Development population no longer matches 683,662 rows.")
    if int(resolved.split["finalOot"]["rows"]) != 14_067:
        raise RuntimeError("The sealed Final OOT population no longer matches 14,067 rows.")
    evaluation = project_candidate_evaluation(database, PROJECT_ID)
    groups = {str(item["candidateFingerprint"]): item for item in evaluation["currentBatches"]}
    required = [
        NULL_BASELINE["candidateFingerprint"],
        *[
            item["candidateFingerprint"]
            for item in FIRST_SCREEN_BENCHMARKS.values()
        ],
    ]
    if any(fingerprint not in groups for fingerprint in required):
        raise RuntimeError("The exact first-screen null, HGB, and RF receipts are not available.")
    for family, benchmark in FIRST_SCREEN_BENCHMARKS.items():
        group = groups[str(benchmark["candidateFingerprint"])]
        if group.get("modelFamily") != family or abs(
            float(group["meanOofLogLoss"]) - float(benchmark["meanOofLogLoss"])
        ) > 1e-12:
            raise RuntimeError(f"The immutable {family} first-screen benchmark changed.")
    feature_set_id = str(feature_set["featureSetId"])
    payload: dict[str, object] = {
        "projectId": PROJECT_ID,
        "authorityKey": resolved.authority_key,
        "splitContractId": resolved.split["contractId"],
        "seed": TUNING_SEED,
        "batchName": TUNING_BATCH_NAME,
        "parallelWorkers": "AUTO",
        "experiments": tuning_experiments(feature_set_id),
    }
    return payload, runtime_estimate()


def main() -> None:
    args = _arguments()
    database = Database(DATABASE_PATH)
    payload, estimate = _validated_payload(database)
    plan = plan_model_development_queue(
        database, PROJECT_ID, payload, actor_user_id=ACTOR_USER_ID
    )
    if (
        plan["totalConfigurations"] != 5
        or plan["totalFits"] != 25
        or plan["finalOotLocked"] is not True
        or plan["finalOotTargetAccessed"] is not False
    ):
        raise RuntimeError("The planned tuning queue does not match the frozen 5-config/25-fit authority.")
    print(
        json.dumps(
            {
                "event": "PLANNED",
                "planId": plan["planId"],
                "planChecksum": plan["checksum"],
                "runtimeEstimate": estimate,
                "experiments": [
                    {
                        "algorithmId": item["algorithmId"],
                        "configurations": item["tuning"]["configurations"],
                    }
                    for item in plan["experiments"]
                ],
                "totalFits": plan["totalFits"],
                "finalOotTargetAccessed": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if args.plan_only:
        return
    result = enqueue_model_development_job(
        database,
        PROJECT_ID,
        {
            **payload,
            "expectedPlanId": plan["planId"],
            "expectedPlanChecksum": plan["checksum"],
        },
        actor_user_id=ACTOR_USER_ID,
    )
    job_id = result["job"]["jobId"]
    print(json.dumps({"event": "ENQUEUED", "jobId": job_id}, sort_keys=True), flush=True)
    prior_snapshot: tuple[object, ...] | None = None
    while True:
        job = get_model_development_job(database, PROJECT_ID, job_id)["job"]
        progress = job.get("progress") or {}
        snapshot = (
            job.get("status"),
            progress.get("completedFits"),
            progress.get("failedFits"),
            progress.get("message"),
        )
        if snapshot != prior_snapshot:
            print(
                json.dumps(
                    {
                        "event": "PROGRESS",
                        "jobId": job_id,
                        "status": job.get("status"),
                        "completedFits": progress.get("completedFits"),
                        "failedFits": progress.get("failedFits"),
                        "totalFits": progress.get("totalFits"),
                        "message": progress.get("message"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            prior_snapshot = snapshot
        if str(job.get("status") or "").upper() in TERMINAL:
            artifacts = job.get("artifacts") or {}
            print(
                json.dumps(
                    {
                        "event": "TERMINAL",
                        "jobId": job_id,
                        "status": job.get("status"),
                        "completedFits": progress.get("completedFits"),
                        "failedFits": progress.get("failedFits"),
                        "modelRunId": artifacts.get("modelRunId") or artifacts.get("runId"),
                        "modelRunReceiptSha256": artifacts.get("modelRunReceiptSha256")
                        or artifacts.get("runReceiptSha256"),
                        "error": job.get("error") or None,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            return
        time.sleep(10)


if __name__ == "__main__":
    main()
