from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_phase4.dynamic_contract import (
    COMMON_COMPONENT_FIELDS,
    validate_dynamic_component_evidence,
)
from server.sports_phase4.dynamic_runner import (
    DynamicRunnerError,
    Phase3RuntimeInputs,
    _ArtifactWriter,
    _artifact_path,
    _validated_runtime_root,
    assemble_dynamic_player_state_component,
    persist_dynamic_materialization_checkpoint,
    verify_dynamic_artifact_body,
)
from server.sports_phase4.dynamic_state import (
    DynamicStateIntegrityError,
    build_dynamic_player_state_from_tables,
    build_historical_dynamic_index,
    build_historical_outcome_index,
    dynamic_state_table_content_sha,
)
from server.sports_phase4.dynamic_training import (
    evaluate_dynamic_experiment,
    run_dynamic_training_experiment,
)
from tests.sports_phase4_dynamic_training_test import (
    BATTER_UUID,
    PITCHER_UUID,
    _d0_fold,
    _feature_table,
    _history_table,
)


class SportsPhase4DynamicRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.feature = _feature_table()
        cls.state = build_dynamic_player_state_from_tables(
            [_history_table()],
            cls.feature,
            alias_rows={"batter-key": BATTER_UUID, "pitcher-key": PITCHER_UUID},
            dimension_uuids=frozenset({BATTER_UUID, PITCHER_UUID}),
            code_revision="fixture:runner-a",
            source_partition_ids=("fixture-pa-history",),
        )
        history = build_historical_outcome_index(
            [_history_table()],
            alias_rows={"batter-key": BATTER_UUID, "pitcher-key": PITCHER_UUID},
            dimension_uuids=frozenset({BATTER_UUID, PITCHER_UUID}),
            source_partition_ids=("fixture-pa-history",),
        )
        cls.history = build_historical_dynamic_index(
            history,
            code_revision="fixture:runner-a",
        )
        cls.d0 = {
            2024: _d0_fold(cls.feature, 2024, sha_character="a"),
            2025: _d0_fold(cls.feature, 2025, sha_character="b"),
        }
        cls.experiment = run_dynamic_training_experiment(
            cls.feature,
            cls.state.table,
            policy=cls.state.policy,
            dynamic_content_sha=cls.state.content_sha,
            d0_folds=cls.d0,
        )
        cls.evidence = evaluate_dynamic_experiment(
            cls.experiment,
            bootstrap_resamples=20,
        )
        cls.boundary = (
            Path(__file__).resolve().parents[1]
            / ".runtime"
            / "asp-model-studio"
            / "sports-modeling"
        )

    def setUp(self) -> None:
        if os.getenv("ASP_REQUIRE_ISOLATED_RUNTIME", "").strip().lower() in ("1", "true", "yes"):
            self.skipTest("legacy runner exercises the shared .runtime governed boundary; not run under the isolated gate")
        self.runtime_root = self.boundary / f"dynamic-runner-test-{uuid.uuid4().hex}"
        self.runtime_root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def _phase3(self) -> Phase3RuntimeInputs:
        feature_sha = "f" * 64
        refs = {
            season: {
                "artifactId": f"sports-pa-artifact:fold_{season}_predictions:sha256:{fold.artifact_sha}",
                "artifactType": f"FOLD_{season}_PREDICTIONS",
                "logicalUri": f"asp-model-studio-runtime://sports-modeling/mlb-pa-v1/{season}",
                "sha256": fold.artifact_sha,
                "byteCount": 1,
                "mediaType": "application/vnd.apache.parquet",
            }
            for season, fold in self.d0.items()
        }
        return Phase3RuntimeInputs(
            feature_table=self.feature,
            feature_artifact={
                "artifactId": f"sports-pa-artifact:feature_view:sha256:{feature_sha}",
                "artifactType": "FEATURE_VIEW",
                "logicalUri": "asp-model-studio-runtime://sports-modeling/mlb-pa-v1/feature",
                "sha256": feature_sha,
                "byteCount": 1,
                "mediaType": "application/vnd.apache.parquet",
            },
            prediction_artifacts=refs,
            d0_folds=self.d0,
            source_partition_ids=("1" * 64,),
            feature_bindings={},
            prediction_bindings={2024: {}, 2025: {}},
        )

    def test_checkpoint_reuse_is_byte_exact_and_cross_revision(self) -> None:
        first = persist_dynamic_materialization_checkpoint(
            self.state,
            self.history,
            runtime_root=self.runtime_root,
            code_revision="fixture:runner-a",
        )
        repeated = persist_dynamic_materialization_checkpoint(
            self.state,
            self.history,
            runtime_root=self.runtime_root,
            code_revision="fixture:runner-b",
        )
        self.assertEqual(first.checkpoint_id, repeated.checkpoint_id)
        self.assertEqual(first.state_artifact, repeated.state_artifact)
        self.assertEqual(first.history_artifact, repeated.history_artifact)
        self.assertEqual(repeated.code_revision, "fixture:runner-a")
        self.assertEqual(repeated.state_table.num_rows, self.state.row_count)
        self.assertEqual(
            dynamic_state_table_content_sha(repeated.state_table, policy=self.state.policy),
            self.state.content_sha,
        )

        rebuilt = build_dynamic_player_state_from_tables(
            [_history_table()],
            self.feature,
            alias_rows={"batter-key": BATTER_UUID, "pitcher-key": PITCHER_UUID},
            dimension_uuids=frozenset({BATTER_UUID, PITCHER_UUID}),
            code_revision="fixture:runner-b",
            source_partition_ids=("fixture-pa-history",),
        )
        self.assertEqual(rebuilt.parquet_bytes, self.state.parquet_bytes)

    def test_new_checkpoint_validates_parquet_read_before_pointer_is_valid(self) -> None:
        with mock.patch(
            "server.sports_phase4.dynamic_runner.dynamic_state_table_content_sha",
            return_value="0" * 64,
        ):
            with self.assertRaisesRegex(DynamicRunnerError, "new dynamic state semantic"):
                persist_dynamic_materialization_checkpoint(
                    self.state,
                    self.history,
                    runtime_root=self.runtime_root,
                    code_revision="fixture:runner-new-check",
                )
        checkpoint_root = self.runtime_root / "mlb-dynamic-player-state-v1" / "checkpoints"
        self.assertEqual(list(checkpoint_root.rglob("checkpoint.json")), [])

    def test_new_checkpoint_validates_history_before_pointer_is_valid(self) -> None:
        with mock.patch(
            "server.sports_phase4.dynamic_runner.load_historical_dynamic_index",
            side_effect=DynamicStateIntegrityError("fixture history semantic content differs"),
        ):
            with self.assertRaisesRegex(DynamicRunnerError, "history semantic content"):
                persist_dynamic_materialization_checkpoint(
                    self.state,
                    self.history,
                    runtime_root=self.runtime_root,
                    code_revision="fixture:runner-new-history-check",
                )
        checkpoint_root = self.runtime_root / "mlb-dynamic-player-state-v1" / "checkpoints"
        self.assertEqual(list(checkpoint_root.rglob("checkpoint.json")), [])

    def test_self_consistent_stale_checkpoint_artifact_is_rejected_against_fresh_bytes(self) -> None:
        checkpoint = persist_dynamic_materialization_checkpoint(
            self.state,
            self.history,
            runtime_root=self.runtime_root,
            code_revision="fixture:runner-a",
        )
        changed_feature = self.feature.set_column(
            self.feature.schema.get_field_index("context_inning"),
            "context_inning",
            pa.array([2] * self.feature.num_rows),
        )
        stale = build_dynamic_player_state_from_tables(
            [_history_table()],
            changed_feature,
            alias_rows={"batter-key": BATTER_UUID, "pitcher-key": PITCHER_UUID},
            dimension_uuids=frozenset({BATTER_UUID, PITCHER_UUID}),
            code_revision="fixture:stale",
            source_partition_ids=("fixture-pa-history",),
        )
        # Context does not change target keys/state; alter one target date instead.
        if stale.parquet_bytes == self.state.parquet_bytes:
            rows = self.feature.to_pylist()
            for row in rows[:8]:
                row["game_date"] = "2023-05-06"
                row["game_id"] = "2023-game-stale"
            stale_feature = pa.Table.from_pylist(rows)
            stale = build_dynamic_player_state_from_tables(
                [_history_table()],
                stale_feature,
                alias_rows={"batter-key": BATTER_UUID, "pitcher-key": PITCHER_UUID},
                dimension_uuids=frozenset({BATTER_UUID, PITCHER_UUID}),
                code_revision="fixture:stale",
                source_partition_ids=("fixture-pa-history",),
            )
        writer = _ArtifactWriter.create(
            self.runtime_root,
            base_bindings=checkpoint.materialization_bindings,
        )
        stale_reference = writer.parquet(
            "DYNAMIC_PLAYER_STATE",
            "mlb-dynamic-player-state-v1.parquet",
            stale.parquet_bytes,
            temporal_fold="NOT_APPLICABLE",
        )
        pointer = (
            self.runtime_root
            / "mlb-dynamic-player-state-v1"
            / "checkpoints"
            / f"sha256-{checkpoint.checkpoint_id.rsplit(':', 1)[-1]}"
            / "checkpoint.json"
        )
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        payload["stateArtifact"] = stale_reference
        pointer.write_bytes(canonical_json_bytes(payload))
        with self.assertRaisesRegex(DynamicRunnerError, "freshly materialized"):
            persist_dynamic_materialization_checkpoint(
                self.state,
                self.history,
                runtime_root=self.runtime_root,
                code_revision="fixture:runner-c",
            )

    def test_checkpoint_rejects_hardlinked_artifact(self) -> None:
        checkpoint = persist_dynamic_materialization_checkpoint(
            self.state,
            self.history,
            runtime_root=self.runtime_root,
            code_revision="fixture:runner-a",
        )
        state_path = _artifact_path(self.runtime_root, checkpoint.state_artifact)
        link_path = state_path.with_name("second-hardlink.parquet")
        try:
            os.link(state_path, link_path)
        except OSError as exc:
            self.skipTest(f"hardlinks unavailable: {exc}")
        try:
            with self.assertRaisesRegex(DynamicRunnerError, "link"):
                persist_dynamic_materialization_checkpoint(
                    self.state,
                    self.history,
                    runtime_root=self.runtime_root,
                    code_revision="fixture:runner-b",
                )
        finally:
            link_path.unlink(missing_ok=True)

    def test_runtime_root_must_use_raw_repository_owned_spelling(self) -> None:
        outside = Path(__file__).resolve().parents[1].parent / "outside-dynamic-runtime"
        with self.assertRaisesRegex(DynamicRunnerError, "must remain inside"):
            _validated_runtime_root(outside)

    def test_assembly_returns_exact_common_component_and_separate_artifacts(self) -> None:
        checkpoint = persist_dynamic_materialization_checkpoint(
            self.state,
            self.history,
            runtime_root=self.runtime_root,
            code_revision="fixture:runner-a",
        )
        result = assemble_dynamic_player_state_component(
            state=self.state,
            history=self.history,
            checkpoint=checkpoint,
            phase3=self._phase3(),
            experiment=self.experiment,
            evidence=self.evidence,
            runtime_root=self.runtime_root,
            code_revision="fixture:runner-a",
        )
        self.assertEqual(set(result), {"component", "artifacts"})
        component = result["component"]
        self.assertEqual(set(component), set(COMMON_COMPONENT_FIELDS))
        self.assertEqual(component["componentType"], "DYNAMIC_PLAYER_STATE")
        self.assertEqual(
            [row["validationSeason"] for row in component["folds"]],
            [2024, 2025],
        )
        self.assertIn("logisticByCandidate", component["descriptor"]["tuning"])
        self.assertIn("historyIndex", component["descriptor"])
        posterior = component["metrics"]["statePosteriorPredictive"]
        self.assertEqual(len(posterior["byRoleStateFold"]), 12)
        self.assertFalse(posterior["selectionUses2024Or2025"])
        self.assertEqual(
            component["descriptor"]["historyIndex"]["artifactId"],
            checkpoint.history_artifact["artifactId"],
        )
        validate_dynamic_component_evidence(
            component,
            artifact_references=result["artifacts"],
        )
        body_bindings = []
        for artifact in result["artifacts"]:
            binding = verify_dynamic_artifact_body(self.runtime_root, artifact)
            self.assertEqual(binding["artifactType"], artifact["artifactType"])
            body_bindings.append(binding)
        self.assertTrue(
            all(
                binding["componentContractSha"] == self.state.contract_sha
                and binding["classOrder"] == binding["targetOrder"]
                and binding["datasetManifestSha"]
                and binding["identityBridgeManifestSha"]
                and binding["phase3FeatureContractSha"]
                for binding in body_bindings
            )
        )
        run_bindings = body_bindings[2:]
        self.assertEqual({row["createdAt"] for row in run_bindings}, {
            component["descriptor"]["runtime"]["runCreatedAt"]
        })
        self.assertEqual({row["codeRevision"] for row in run_bindings}, {
            "fixture:runner-a"
        })

        by_type = {row["artifactType"]: row for row in result["artifacts"]}
        posterior_envelope = json.loads(
            _artifact_path(
                self.runtime_root,
                by_type["DYNAMIC_STATE_POSTERIOR_PREDICTIVE"],
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(posterior_envelope["payload"], posterior)
        model_card_envelope = json.loads(
            _artifact_path(
                self.runtime_root,
                by_type["DYNAMIC_MODEL_CARD"],
            ).read_text(encoding="utf-8")
        )
        model_card = model_card_envelope["payload"]
        self.assertEqual(model_card["decision"], component["decision"])
        self.assertEqual(model_card["descriptor"], component["descriptor"])
        self.assertEqual(model_card["metrics"], component["metrics"])
        self.assertEqual(
            model_card["lineage"]["state"]["artifact"],
            checkpoint.state_artifact,
        )
        self.assertTrue(model_card["selfReferenceOmittedToAvoidCircularDigest"])
        final_envelope = json.loads(
            _artifact_path(
                self.runtime_root,
                by_type["DYNAMIC_FINAL_CHECKPOINT"],
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(final_envelope["payload"]["decision"], component["decision"])

    def test_parquet_artifact_type_cannot_be_relabelled(self) -> None:
        if os.getenv("ASP_REQUIRE_ISOLATED_RUNTIME", "").strip().lower() in ("1", "true", "yes"):
            self.skipTest("legacy runner exercises the shared .runtime governed boundary; not run under the isolated gate")
        checkpoint = persist_dynamic_materialization_checkpoint(
            self.state,
            self.history,
            runtime_root=self.runtime_root,
            code_revision="fixture:runner-a",
        )
        reference = dict(checkpoint.state_artifact)
        path = _artifact_path(self.runtime_root, reference)
        metadata = pq.ParquetFile(path).schema_arrow.metadata or {}
        self.assertEqual(metadata[b"artifactType"], b"DYNAMIC_PLAYER_STATE")
        reference["artifactType"] = "DYNAMIC_HISTORY_INDEX"
        reference["artifactId"] = (
            "sports-phase4-artifact:dynamic_history_index:sha256:"
            + reference["sha256"]
        )
        with self.assertRaisesRegex(DynamicRunnerError, "type binding"):
            verify_dynamic_artifact_body(self.runtime_root, reference)

    def test_artifact_body_verifier_rejects_tampered_bytes(self) -> None:
        checkpoint = persist_dynamic_materialization_checkpoint(
            self.state,
            self.history,
            runtime_root=self.runtime_root,
            code_revision="fixture:runner-a",
        )
        reference = checkpoint.state_artifact
        verify_dynamic_artifact_body(self.runtime_root, reference)
        artifact_path = _artifact_path(self.runtime_root, reference)
        artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(DynamicRunnerError, "reference/body integrity"):
            verify_dynamic_artifact_body(self.runtime_root, reference)


if __name__ == "__main__":
    unittest.main()
