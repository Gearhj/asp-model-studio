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
    def test_estimate_only_does_not_require_or_start_live_authorities(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["--estimate-only"])
        self.assertEqual(status, 0)
        estimate = json.loads(output.getvalue())
        self.assertTrue(estimate["estimateOnly"])
        self.assertFalse(estimate["liveRunStarted"])
        self.assertLess(estimate["estimatedSecondsLower"], estimate["estimatedSecondsUpper"])

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
            status = main(["--exchange-root", "fixture", "--database", "fixture.db"])
        self.assertEqual(status, 0)
        command = supervised.call_args.args[0]
        options = supervised.call_args.kwargs
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[-1], SUPERVISED_WORKER_ARGUMENT)
        self.assertEqual(options["stage_limits"], PARTICIPATION_STAGE_LIMITS)
        self.assertEqual(options["limits"], PARTICIPATION_SUPERVISION_LIMITS)
        self.assertEqual(options["limits"].overall_seconds, 8 * 60 * 60)
        self.assertEqual(options["limits"].silence_seconds, 90)
        self.assertEqual(options["limits"].rss_bytes, 8 * 1024**3)
        self.assertEqual(options["env"][WORKER_ENVIRONMENT_FLAG], "1")

    def test_hidden_worker_mode_requires_the_supervisor_environment(self) -> None:
        arguments = [
            "--exchange-root",
            "fixture",
            "--database",
            "fixture.db",
            SUPERVISED_WORKER_ARGUMENT,
        ]
        with mock.patch.dict(os.environ, {WORKER_ENVIRONMENT_FLAG: "0"}):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(arguments), 2)


if __name__ == "__main__":
    unittest.main()
