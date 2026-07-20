from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.core.result_store import RESULTS
from server.evaluation.eval_service import EVAL


def main() -> None:
    y_true = np.asarray(([0] * 70) + ([1] * 30), dtype=float)
    y_score = np.asarray(
        [0.01 + (index * 0.006) for index in range(70)]
        + [0.48 + (index * 0.017) for index in range(30)],
        dtype=float,
    )
    RESULTS.clear_model_artifacts()
    RESULTS.set_last_summary(
        {
            "problem_type": "classification",
            "ranked": [
                {
                    "key": "logreg",
                    "name": "Logistic Regression",
                    "best_score": 0.88,
                    "calibration_applied": True,
                    "calibration_method": "sigmoid",
                }
            ],
            "raw": {
                "logreg": {
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
            },
        }
    )

    command = EVAL.get_evaluation_command_center("logreg", threshold=0.55, review_capacity=0.10)
    assert command["ok"] is True
    assert command["observation_count"] == len(y_true)
    assert sum(sum(row) for row in command["threshold"]["confusion"]) == len(y_true)
    assert sum(row["n"] for row in command["lift"]["deciles"]) == len(y_true)
    assert command["test_status"] == "Available - governed holdout"
    assert command["oot_status"] == "Not loaded"
    assert command["calibration"]["method"] == "sigmoid"
    assert command["stability"]["internal_validation_score"] == 0.88
    for preset in command["presets"].values():
        assert 0.0 <= float(preset) <= 1.0

    missing = EVAL.get_evaluation_command_center("not-fitted")
    assert missing["ok"] is False
    assert "No fitted results" in missing["error"]

    RESULTS.clear_model_artifacts()
    print("Evaluation command-center backend diagnostics passed.")


if __name__ == "__main__":
    main()
