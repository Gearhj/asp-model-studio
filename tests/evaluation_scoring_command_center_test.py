from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import uuid

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.evaluation.eval_service import EVAL
from server.persistence.db import Database
from server.persistence.service import PersistenceService
from evaluation_exact_lineage_test import ALGORITHM_ID, LINEAGE, seed_exact_candidate


@contextmanager
def isolated_governance_database():
    temporary_root = Path(".tmp")
    temporary_root.mkdir(parents=True, exist_ok=True)
    database_path = temporary_root / (
        f"evaluation-command-center-{uuid.uuid4().hex}.db"
    )
    database = Database(database_path)
    database.initialize()
    previous = EVAL._persistence_service
    EVAL._persistence_service = PersistenceService(database)
    try:
        yield
    finally:
        EVAL._persistence_service = previous
        for suffix in ("", "-wal", "-shm"):
            Path(str(database_path) + suffix).unlink(missing_ok=True)


def run_checks() -> None:
    y_true = np.asarray(([0] * 70) + ([1] * 30), dtype=float)
    y_score = np.asarray(
        [0.01 + (index * 0.006) for index in range(70)]
        + [0.48 + (index * 0.017) for index in range(30)],
        dtype=float,
    )
    context = seed_exact_candidate()
    from server.core.result_store import RESULTS

    summary = RESULTS.get_last_summary()
    summary["ranked"][0].update(
        {
            "best_score": 0.88,
            "calibration_applied": True,
            "calibration_method": "sigmoid",
        }
    )
    summary["raw"][ALGORITHM_ID] = {
        "task": "classification",
        "y_true": y_true.tolist(),
        "y_score": y_score.tolist(),
        "metrics": {
            "auc": 0.94,
            "pr_auc": 0.90,
            "precision": 0.81,
            "recall": 0.84,
            "f1": 0.825,
            "confusion_matrix": [[65, 5], [5, 25]],
        },
    }

    command = EVAL.get_evaluation_command_center(
        LINEAGE["candidate_id"],
        threshold=0.55,
        review_capacity=0.10,
        context=context,
    )
    assert command["ok"] is True
    governed_holdout_rows = 4
    assert command["observation_count"] == governed_holdout_rows
    assert command["observation_count"] != len(y_true)
    assert (
        sum(sum(row) for row in command["threshold"]["confusion"])
        == governed_holdout_rows
    )
    assert (
        sum(row["n"] for row in command["lift"]["deciles"])
        == governed_holdout_rows
    )
    assert command["test_status"] == "Available - final holdout (reporting only)"
    assert command["final_holdout_role"] == "reporting_only"
    assert command["oot_status"] == "Not loaded"
    assert command["calibration"]["method"] == "sigmoid"
    assert command["stability"]["internal_validation_score"] == 0.88
    assert command["presets"] == {"current_governed": 0.5}
    assert command["threshold_policy"]["recommendations_derived_from_final_holdout"] is False

    missing_context = {**context, "candidate_id": "candidate-not-fitted"}
    missing = EVAL.get_evaluation_command_center("candidate-not-fitted", context=missing_context)
    assert missing["ok"] is False
    assert "not uniquely present" in missing["error"]

    RESULTS.clear_model_artifacts()
    print("Evaluation command-center backend diagnostics passed.")


def main() -> None:
    with isolated_governance_database():
        run_checks()


if __name__ == "__main__":
    main()
