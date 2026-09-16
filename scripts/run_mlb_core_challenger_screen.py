"""Run the bounded Development-only MLB Core Challenger screen."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from server.persistence.db import Database
from server.sports_current_statcast.stage3_model_jobs import (
    enqueue_model_development_job,
    get_model_development_job,
    plan_model_development_queue,
)
from server.sports_current_statcast.stage3_model_laboratory import (
    resolve_model_lab_authority,
)


PROJECT_ID = "asp-mtlozhdx"
ACTOR_USER_ID = "user_20e0f4e20ec9434c"
DATABASE_PATH = Path(
    r".runtime\asp-model-studio\persistence\asp_model_studio.db"
)
ALGORITHMS = (
    "class_frequency_null",
    "multinomial_logistic",
    "histogram_gradient_boosting",
    "random_forest",
    "sgd_classifier",
)
TERMINAL = {"COMPLETE", "PARTIAL", "FAILED", "CANCELLED", "CANCELLED_PARTIAL"}


def _requested_algorithms() -> tuple[str, ...]:
    parser = argparse.ArgumentParser(
        description="Run the bounded Development-only MLB Core Challenger screen."
    )
    parser.add_argument(
        "--algorithms",
        nargs="+",
        choices=ALGORITHMS,
        help=(
            "Optional exact subset for a bounded infrastructure repair run. "
            "Omit to run the registered five-family screen."
        ),
    )
    requested = tuple(parser.parse_args().algorithms or ALGORITHMS)
    if len(requested) != len(set(requested)):
        parser.error("Each requested algorithm must appear exactly once.")
    return requested


def main() -> None:
    algorithms = _requested_algorithms()
    database = Database(DATABASE_PATH)
    authority = resolve_model_lab_authority(database, PROJECT_ID)
    feature_set_id = authority.feature_sets[0]["featureSetId"]
    payload = {
        "projectId": PROJECT_ID,
        "authorityKey": authority.authority_key,
        "splitContractId": authority.split["contractId"],
        "seed": 20260906,
        "batchName": "MLB Core Challenger first bounded screen",
        "parallelWorkers": "AUTO",
        "experiments": [
            {
                "algorithmId": algorithm,
                "featureUniverseId": feature_set_id,
                "tuningMode": "FIXED",
            }
            for algorithm in algorithms
        ],
    }
    plan = plan_model_development_queue(
        database, PROJECT_ID, payload, actor_user_id=ACTOR_USER_ID
    )
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
    print(
        json.dumps(
            {
                "event": "ENQUEUED",
                "jobId": job_id,
                "planId": plan["planId"],
                "planChecksum": plan["checksum"],
                "totalFits": plan["totalFits"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
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
            print(json.dumps({"event": "TERMINAL", "job": job}, sort_keys=True), flush=True)
            return
        time.sleep(10)


if __name__ == "__main__":
    main()
