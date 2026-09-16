from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from scripts.run_mlb_participation_usage import (
    DATASET_VALIDATION_CACHE_RELATIVE,
    PARTICIPATION_STAGE_LIMITS,
    PARTICIPATION_SUPERVISION_LIMITS,
    REPOSITORY_ROOT,
    SUPERVISED_WORKER_ARGUMENT,
    _artifact_union,
    _progress,
    _validate_runtime_roots,
    main,
)
from server.sports_phase4.supervision import (
    SupervisedWorkerResult,
    WORKER_ENVIRONMENT_FLAG,
)


class ParticipationCliTest(unittest.TestCase):
    def test_main_is_hard_retired_before_any_estimate_or_live_work(self) -> None:
        # Gate 12 (Phase 7D.4): run_mlb_participation_usage.main is hard-retired (its live path scored the sealed
        # 2025 season), so it exits with code 2 before any estimate / live / data work.
        with self.assertRaises(SystemExit) as cm:
            main(["--estimate-only"])
        self.assertEqual(cm.exception.code, 2)

    def test_progress_surface_has_every_required_operational_field(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            _progress(
                "FIXTURE_STAGE",
                {
                    "currentComponent": "LINEUP_PROJECTION",
                    "elapsedSeconds": 10.0,
                    "currentSeason": 2024,
                    "partitionsProcessed": 2,
                    "partitionsTotal": 3,
                    "rowsProcessed": 100,
                    "rowsTotal": 200,
                    "candidateId": "L1",
                    "etaSeconds": 10.0,
                    "errors": 0,
                },
            )
        rendered = output.getvalue()
        for label in (
            "Milestone:",
            "Current component:",
            "Elapsed:",
            "Seasons/fold:",
            "Partitions:",
            "Rows:",
            "Candidate:",
            "Throughput:",
            "ETA:",
            "Memory:",
            "Errors:",
        ):
            self.assertIn(label, rendered)

    def test_dynamic_and_output_runtime_roots_cannot_be_swapped_or_aliased(self) -> None:
        dynamic = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
        output = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-phase4"
        _validate_runtime_roots(dynamic, output)
        with self.assertRaises(RuntimeError):
            _validate_runtime_roots(output, dynamic)
        with self.assertRaises(RuntimeError):
            _validate_runtime_roots(dynamic, dynamic)
        self.assertEqual(
            dynamic / DATASET_VALIDATION_CACHE_RELATIVE,
            REPOSITORY_ROOT
            / ".runtime"
            / "asp-model-studio"
            / "sports-modeling"
            / "dataset-validation"
            / "validation-cache.json",
        )
        self.assertNotEqual(
            output / DATASET_VALIDATION_CACHE_RELATIVE,
            dynamic / DATASET_VALIDATION_CACHE_RELATIVE,
        )

    def test_artifact_union_rejects_same_id_with_contradictory_reference(self) -> None:
        artifact = {
            "artifactId": "sports-phase4-artifact:test:sha256:" + "a" * 64,
            "artifactType": "TEST",
            "logicalUri": "asp-model-studio-runtime://sports-phase4/test",
            "sha256": "a" * 64,
            "byteCount": 1,
            "mediaType": "application/json",
        }
        self.assertEqual(_artifact_union([artifact], [dict(artifact)]), [artifact])
        contradiction = dict(artifact)
        contradiction["byteCount"] = 2
        with self.assertRaises(RuntimeError):
            _artifact_union([artifact], [contradiction])

    def test_live_cli_uses_the_whole_worker_hard_stop_boundary(self) -> None:
        result = SupervisedWorkerResult(
            command=(sys.executable, "worker"),
            returncode=0,
            elapsed_seconds=1.0,
            peak_tree_rss_bytes=1,
            stdout="",
            stderr="",
            events=(),
        )
        with mock.patch(
            "scripts.run_mlb_participation_usage.run_supervised_worker",
            return_value=result,
        ) as supervised:
            with self.assertRaises(SystemExit) as cm:
                main(["--exchange-root", "fixture", "--database", "fixture.db"])
        self.assertEqual(cm.exception.code, 2)
        supervised.assert_not_called()   # Gate 12: retired BEFORE any supervised worker / data work

    def test_hidden_worker_mode_is_also_hard_retired(self) -> None:
        # The hidden worker entry runs the actual 2025-touching pipeline; it is retired (exit 2) too.
        arguments = [
            "--exchange-root",
            "fixture",
            "--database",
            "fixture.db",
            SUPERVISED_WORKER_ARGUMENT,
        ]
        with mock.patch.dict(os.environ, {WORKER_ENVIRONMENT_FLAG: "0"}):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main(arguments)
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
