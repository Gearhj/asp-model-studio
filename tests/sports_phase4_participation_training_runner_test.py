from __future__ import annotations

import copy
import hashlib
import json
import shutil
import time
import unittest
import uuid
from pathlib import Path, PurePosixPath

import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_datasets.constants import PROJECT_ID
from server.sports_phase4.participation_runner import (
    COMPONENT_KEYS,
    RUNTIME_NAMESPACE,
    RUNTIME_URI_PREFIX,
    ParticipationRunnerError,
    assemble_participation_run,
    validate_component_shape,
)
from server.sports_phase4 import participation_runner
from server.sports_phase4.participation_training import run_participation_experiments
from server.sports_phase4.registry import semantic_component_sha
from tests.sports_phase4_participation_fixture import build_fixture_views


class ParticipationTrainingRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.views = build_fixture_views()
        cls.progress_events: list[tuple[str, dict[str, object]]] = []
        cls.experiment = run_participation_experiments(
            cls.views,
            fixture_mode=True,
            bootstrap_resamples=8,
            progress=lambda stage, evidence: cls.progress_events.append(
                (stage, dict(evidence))
            ),
        )
        cls.runtime_root = (
            Path.cwd() / ".tmp" / f"participation-unittest-{uuid.uuid4().hex}"
        )
        cls.runtime_root.mkdir(parents=True, exist_ok=False)
        cls.payload = assemble_participation_run(
            project_id=PROJECT_ID,
            views=cls.views,
            experiment=cls.experiment,
            runtime_root=cls.runtime_root,
            code_revision="fixture-code-revision",
            fixture_mode=True,
            created_at="2026-08-17T12:34:56Z",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.runtime_root)

    @classmethod
    def _artifact_path(cls, reference: dict[str, object]) -> Path:
        logical_uri = str(reference["logicalUri"])
        prefix = RUNTIME_URI_PREFIX + "/"
        if not logical_uri.startswith(prefix):
            raise AssertionError("fixture artifact URI escaped its governed namespace")
        suffix = PurePosixPath(logical_uri[len(prefix) :])
        return cls.runtime_root / RUNTIME_NAMESPACE / Path(*suffix.parts)

    def test_candidate_folds_have_full_lineage_and_policy_not_runs(self) -> None:
        expected_complete_2025 = {
            "LINEUP_PROJECTION": {"L0", self.experiment.lineup.selected["candidateId"]},
            "STARTER_DURATION": {"S0", "S1", self.experiment.starter.selected["candidateId"]},
            "BULLPEN_USAGE": {"B0", self.experiment.bullpen.selected["candidateId"]},
        }
        for component in self.experiment.components:
            for candidate in component.candidates:
                folds = candidate["foldMetrics"]
                self.assertEqual([item["validationSeason"] for item in folds], [2024, 2025])
                for fold in folds:
                    self.assertEqual(
                        set(fold),
                        {
                            "foldId",
                            "trainingSeasons",
                            "validationSeason",
                            "trainingRows",
                            "validationRows",
                            "status",
                            "runtimeSeconds",
                            "convergence",
                            "metrics",
                        },
                    )
                expected = (
                    "COMPLETE"
                    if candidate["candidateId"] in expected_complete_2025[component.component_type]
                    else "NOT_RUN_BY_POLICY"
                )
                self.assertEqual(folds[1]["status"], expected)

    def test_2024_selection_recomputes_from_governing_metrics(self) -> None:
        for component in self.experiment.components:
            eligible = [candidate for candidate in component.candidates if candidate["eligible"]]
            if component.component_type in {"LINEUP_PROJECTION", "BULLPEN_USAGE"}:
                chosen = min(
                    eligible,
                    key=lambda candidate: (
                        candidate["foldMetrics"][0]["metrics"]["binaryLogLoss"],
                        candidate["foldMetrics"][0]["metrics"]["brierScore"],
                        int(candidate["candidateId"][1:]),
                    ),
                )
            else:
                chosen = min(
                    eligible,
                    key=lambda candidate: (
                        candidate["foldMetrics"][0]["metrics"]["bfpMae"],
                        candidate["foldMetrics"][0]["metrics"]["bfpRmse"],
                        int(candidate["candidateId"][1:]),
                    ),
                )
            self.assertEqual(component.selected["candidateId"], chosen["candidateId"])

    def test_common_component_shape_and_identity_are_exact(self) -> None:
        self.assertEqual(len(self.payload["components"]), 3)
        for component in self.payload["components"]:
            self.assertEqual(set(component), COMPONENT_KEYS)
            self.assertEqual(validate_component_shape(component), component)
            type_token = component["componentType"].casefold().replace("_", "-")
            self.assertEqual(
                component["componentId"],
                f"sports-phase4-component:{type_token}:sha256:{semantic_component_sha(component)}",
            )
            tampered = copy.deepcopy(component)
            tampered["componentId"] = tampered["componentId"].replace("a", "b", 1)
            with self.assertRaises(ParticipationRunnerError):
                validate_component_shape(tampered)

    def test_artifact_references_and_body_bindings_reconcile(self) -> None:
        references = self.payload["artifacts"]
        self.assertGreaterEqual(len(references), 40)
        self.assertEqual(
            [item["artifactId"] for item in references],
            sorted(item["artifactId"] for item in references),
        )
        owned = {
            artifact_id
            for component in self.payload["components"]
            for artifact_id in component["artifactIds"]
        }
        self.assertEqual(owned, {item["artifactId"] for item in references})
        self.assertTrue(
            all(
                self.payload["finalCheckpointArtifactId"] in component["artifactIds"]
                for component in self.payload["components"]
            )
        )
        for reference in references:
            self.assertEqual(
                set(reference),
                {"artifactId", "artifactType", "logicalUri", "sha256", "byteCount", "mediaType"},
            )
            self.assertNotIn("componentType", reference)
            path = self._artifact_path(reference)
            content = path.read_bytes()
            self.assertEqual(len(content), reference["byteCount"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), reference["sha256"])
            self.assertTrue(str(reference["artifactId"]).endswith(str(reference["sha256"])))
            if reference["mediaType"] == "application/json":
                body = json.loads(content)
                bindings = body["bindings"]
                artifact_binding = body["artifactBinding"]
            else:
                metadata = pq.read_metadata(pa.BufferReader(content)).metadata or {}
                bindings = json.loads(metadata[b"artifactBindings"])
                artifact_binding = json.loads(metadata[b"artifactBinding"])
                self.assertEqual(metadata[b"createdAt"], b"2026-08-17T12:34:56Z")
                self.assertEqual(metadata[b"codeRevision"], b"fixture-code-revision")
                self.assertEqual(
                    json.loads(metadata[b"sourcePartitionIds"]),
                    list(self.views.source_partition_ids),
                )
                self.assertEqual(
                    artifact_binding["componentContract"]["contractSha"],
                    metadata[b"componentContractSha"].decode("ascii"),
                )
            self.assertEqual(bindings["createdAt"], "2026-08-17T12:34:56Z")
            self.assertEqual(bindings["codeRevision"], "fixture-code-revision")
            self.assertEqual(bindings["sourcePartitionIds"], list(self.views.source_partition_ids))
            self.assertEqual(bindings["parent"]["manifestSha"], self.payload["parent"]["manifestSha"])
            self.assertEqual(
                bindings["identityBridge"]["manifestSha"],
                self.payload["identityBridge"]["manifestSha"],
            )
            self.assertEqual(artifact_binding["artifactType"], reference["artifactType"])
            self.assertIn(
                artifact_binding["temporalFold"],
                {"2024", "2025", "MULTI_FOLD", "NOT_APPLICABLE"},
            )

    def test_feature_and_prediction_parquet_have_honest_fold_bindings(self) -> None:
        feature_refs = [
            item for item in self.payload["artifacts"] if str(item["artifactType"]).endswith("FEATURE_VIEW")
        ]
        prediction_refs = [
            item for item in self.payload["artifacts"] if "_FOLD_" in str(item["artifactType"])
        ]
        self.assertEqual(len(feature_refs), 3)
        self.assertEqual(len(prediction_refs), 6)
        for reference in feature_refs:
            metadata = pq.read_metadata(pa.BufferReader(self._artifact_path(reference).read_bytes())).metadata or {}
            self.assertEqual(metadata[b"temporalFold"], b"MULTI_FOLD")
        for reference in prediction_refs:
            metadata = pq.read_metadata(pa.BufferReader(self._artifact_path(reference).read_bytes())).metadata or {}
            expected = b"2024" if "_2024_" in str(reference["artifactType"]) else b"2025"
            self.assertEqual(metadata[b"temporalFold"], expected)
            self.assertIn(b"componentId", metadata)

    def test_feature_preparation_has_an_unconditional_heartbeat(self) -> None:
        observed: list[tuple[str, dict[str, object]]] = []
        reporter = participation_runner._Progress(
            lambda stage, evidence: observed.append((stage, dict(evidence)))
        )
        original_interval = participation_runner.PROGRESS_HEARTBEAT_SECONDS
        participation_runner.PROGRESS_HEARTBEAT_SECONDS = 0.01
        try:
            result = participation_runner._with_progress_heartbeat(
                stage="BUILDING_PARTICIPATION_FEATURE_VIEWS",
                callback=lambda: (time.sleep(0.2), "complete")[1],
                reporter=reporter,
                current_component="MULTI_COMPONENT",
            )
        finally:
            participation_runner.PROGRESS_HEARTBEAT_SECONDS = original_interval
        self.assertEqual(result, "complete")
        self.assertTrue(
            any(
                stage == "BUILDING_PARTICIPATION_FEATURE_VIEWS_HEARTBEAT"
                for stage, _evidence in observed
            )
        )

    def test_each_governed_training_stage_emits_a_bound_finish_event(self) -> None:
        finished = [
            evidence["modelStage"]
            for stage, evidence in self.progress_events
            if stage == "PARTICIPATION_COMPONENT_FIT_FINISHED"
        ]
        self.assertEqual(
            finished,
            [
                "TRAINING_LINEUP_COMPONENT",
                "TRAINING_STARTER_DURATION_COMPONENT",
                "TRAINING_BULLPEN_USAGE_COMPONENT",
            ],
        )
        self.assertEqual(
            [
                self.experiment.lineup.descriptor["componentRuntimeLimitSeconds"],
                self.experiment.starter.descriptor["componentRuntimeLimitSeconds"],
                self.experiment.bullpen.descriptor["componentRuntimeLimitSeconds"],
            ],
            [5_400, 5_400, 7_200],
        )


if __name__ == "__main__":
    unittest.main()
