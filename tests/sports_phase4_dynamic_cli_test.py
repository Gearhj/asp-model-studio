from __future__ import annotations

import os
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.run_mlb_dynamic_player_state import (
    DATASET_VALIDATION_CACHE_RELATIVE,
    DYNAMIC_STAGE_LIMITS,
    REPOSITORY_ROOT,
    _arguments,
    _progress,
    _revision,
    _validated_dataset_cache_path,
    _worker_main,
    main,
)


class SportsPhase4DynamicCliTest(unittest.TestCase):
    def test_cli_freezes_governed_bootstrap_defaults_and_has_preflight(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            parsed = _arguments(["--exchange-root", "X", "--preflight-only"])
        self.assertEqual(parsed.bootstrap_resamples, 500)
        self.assertEqual(parsed.bootstrap_seed, 20_260_817)
        self.assertTrue(parsed.preflight_only)

    def test_cli_rejects_nonrepository_runtime_before_source_access(self) -> None:
        outside = Path(__file__).resolve().parents[1].parent / "outside-dynamic-cli"
        args = _arguments(
            [
                "--exchange-root",
                "not-accessed",
                "--database",
                str(
                    REPOSITORY_ROOT
                    / ".runtime"
                    / "asp-model-studio"
                    / "persistence"
                    / "asp_model_studio.db"
                ),
                "--runtime-root",
                str(outside),
            ]
        )
        with redirect_stderr(StringIO()):
            result = _worker_main(args, progress=lambda _stage, _evidence: None)
        self.assertEqual(result, 2)

    def test_revision_accepts_explicit_content_bound_override(self) -> None:
        with patch.dict(
            os.environ,
            {"ASP_MODEL_STUDIO_CODE_REVISION": "fixture:dynamic-cli"},
        ):
            self.assertEqual(_revision(), "fixture:dynamic-cli")

    def test_preflight_reuses_exact_governed_validation_cache_authority(self) -> None:
        runtime = (
            REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
        )
        database = (
            REPOSITORY_ROOT
            / ".runtime"
            / "asp-model-studio"
            / "persistence"
            / "asp_model_studio.db"
        )
        phase3 = SimpleNamespace(
            feature_table=SimpleNamespace(num_rows=3),
            d0_folds={
                2024: SimpleNamespace(table=SimpleNamespace(num_rows=1)),
                2025: SimpleNamespace(table=SimpleNamespace(num_rows=2)),
            },
        )
        validated_parent = SimpleNamespace(
            partitions=tuple(range(329)),
            cache_hits=329,
            cache_misses=0,
        )
        output = StringIO()
        events: list[str] = []
        args = _arguments(
            [
                "--exchange-root",
                "logical-exchange",
                "--database",
                str(database),
                "--runtime-root",
                str(runtime),
                "--preflight-only",
            ]
        )
        with (
            patch("scripts.run_mlb_dynamic_player_state.Database") as database_class,
            patch("scripts.run_mlb_dynamic_player_state._validate_isolated_database_file"),
            patch(
                "scripts.run_mlb_dynamic_player_state._validated_dataset_cache_path",
                return_value=runtime / DATASET_VALIDATION_CACHE_RELATIVE,
            ) as cache_path,
            patch(
                "scripts.run_mlb_dynamic_player_state.approved_package_root",
                return_value=Path("registered-parent"),
            ),
            patch(
                "scripts.run_mlb_dynamic_player_state.approved_bridge_root",
                return_value=Path("registered-bridge"),
            ),
            patch("scripts.run_mlb_dynamic_player_state.SportsDatasetManifestConsumer") as consumer,
            patch("scripts.run_mlb_dynamic_player_state.SportsIdentityBridgeV1Consumer") as bridge,
            patch(
                "scripts.run_mlb_dynamic_player_state.load_phase3_runtime_inputs",
                return_value=phase3,
            ),
            patch("scripts.run_mlb_dynamic_player_state.SportsPhase4Registry") as registry,
            redirect_stdout(output),
        ):
            database_class.return_value.initialize.side_effect = lambda: events.append("initialize")
            registry.return_value.validate_registered_authorities.side_effect = (
                lambda: events.append("authorities")
            )
            consumer.return_value.validate.side_effect = lambda: (
                events.append("dataset") or validated_parent
            )
            bridge.return_value.validate.return_value = object()
            result = _worker_main(
                args,
                progress=lambda _stage, _evidence: None,
            )
        self.assertEqual(result, 0)
        self.assertEqual(events, ["initialize", "authorities", "dataset"])
        self.assertEqual(
            consumer.call_args.kwargs["cache_path"],
            runtime / DATASET_VALIDATION_CACHE_RELATIVE,
        )
        cache_path.assert_called_once_with(runtime, runtime)
        self.assertEqual(
            DATASET_VALIDATION_CACHE_RELATIVE.as_posix(),
            "dataset-validation/validation-cache.json",
        )
        self.assertIn("cache_hits=329 cache_misses=0", output.getvalue())

    def test_validation_cache_requires_existing_single_link_exact_path(self) -> None:
        root = (
            REPOSITORY_ROOT
            / ".runtime"
            / "asp-model-studio"
            / "sports-modeling"
            / f"dynamic-cli-cache-{uuid.uuid4().hex}"
        )
        cache = root / DATASET_VALIDATION_CACHE_RELATIVE
        with self.assertRaisesRegex(RuntimeError, "warmed"):
            _validated_dataset_cache_path(root, root)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("{}", encoding="utf-8")
        hardlink = cache.with_name("validation-cache-hardlink.json")
        try:
            os.link(cache, hardlink)
        except OSError as exc:
            cache.unlink(missing_ok=True)
            self.skipTest(f"hardlinks unavailable: {exc}")
        try:
            with self.assertRaisesRegex(RuntimeError, "single-link"):
                _validated_dataset_cache_path(root, root)
        finally:
            hardlink.unlink(missing_ok=True)
        try:
            with patch(
                "scripts.run_mlb_dynamic_player_state.reject_reparse_chain",
                side_effect=RuntimeError("fixture reparse point"),
            ):
                with self.assertRaisesRegex(RuntimeError, "reparse"):
                    _validated_dataset_cache_path(root, root)
        finally:
            cache.unlink(missing_ok=True)
            cache.parent.rmdir()
            root.rmdir()

    def test_preflight_rejects_any_cache_miss_before_runtime_read(self) -> None:
        runtime = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
        database = (
            REPOSITORY_ROOT
            / ".runtime"
            / "asp-model-studio"
            / "persistence"
            / "asp_model_studio.db"
        )
        args = _arguments(
            [
                "--exchange-root",
                "logical-exchange",
                "--database",
                str(database),
                "--runtime-root",
                str(runtime),
                "--preflight-only",
            ]
        )
        parent = SimpleNamespace(
            partitions=tuple(range(329)),
            cache_hits=328,
            cache_misses=1,
        )
        with (
            patch("scripts.run_mlb_dynamic_player_state.Database"),
            patch("scripts.run_mlb_dynamic_player_state._validate_isolated_database_file"),
            patch("scripts.run_mlb_dynamic_player_state.SportsPhase4Registry"),
            patch(
                "scripts.run_mlb_dynamic_player_state._validated_dataset_cache_path",
                return_value=runtime / DATASET_VALIDATION_CACHE_RELATIVE,
            ),
            patch(
                "scripts.run_mlb_dynamic_player_state.approved_package_root",
                return_value=Path("registered-parent"),
            ),
            patch("scripts.run_mlb_dynamic_player_state.SportsDatasetManifestConsumer") as consumer,
            patch("scripts.run_mlb_dynamic_player_state.SportsIdentityBridgeV1Consumer") as bridge,
            patch("scripts.run_mlb_dynamic_player_state.load_phase3_runtime_inputs") as phase3,
            redirect_stderr(StringIO()),
        ):
            consumer.return_value.validate.return_value = parent
            result = _worker_main(args, progress=lambda _stage, _evidence: None)
        self.assertEqual(result, 1)
        bridge.assert_not_called()
        phase3.assert_not_called()

    def test_fresh_or_tampered_database_blocks_before_any_source_read(self) -> None:
        runtime = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
        database_path = (
            REPOSITORY_ROOT
            / ".runtime"
            / "asp-model-studio"
            / "persistence"
            / "asp_model_studio.db"
        )
        args = _arguments(
            [
                "--exchange-root",
                "logical-exchange",
                "--database",
                str(database_path),
                "--runtime-root",
                str(runtime),
                "--preflight-only",
            ]
        )
        for label in ("fresh database", "tampered authority"):
            with self.subTest(label=label):
                events: list[str] = []
                with (
                    patch("scripts.run_mlb_dynamic_player_state.Database") as database,
                    patch(
                        "scripts.run_mlb_dynamic_player_state._validate_isolated_database_file"
                    ),
                    patch(
                        "scripts.run_mlb_dynamic_player_state.SportsPhase4Registry"
                    ) as registry,
                    patch(
                        "scripts.run_mlb_dynamic_player_state.SportsDatasetManifestConsumer"
                    ) as consumer,
                    patch(
                        "scripts.run_mlb_dynamic_player_state.SportsIdentityBridgeV1Consumer"
                    ) as bridge,
                    patch(
                        "scripts.run_mlb_dynamic_player_state.load_phase3_runtime_inputs"
                    ) as phase3,
                    redirect_stderr(StringIO()),
                ):
                    database.return_value.initialize.side_effect = (
                        lambda: events.append("initialize")
                    )
                    registry.return_value.validate_registered_authorities.side_effect = (
                        lambda: (events.append("validate") or (_ for _ in ()).throw(RuntimeError(label)))
                    )
                    result = _worker_main(
                        args,
                        progress=lambda _stage, _evidence: None,
                    )
                self.assertEqual(result, 1)
                self.assertEqual(events, ["initialize", "validate"])
                consumer.assert_not_called()
                bridge.assert_not_called()
                phase3.assert_not_called()

    def test_progress_names_milestone_component_throughput_and_honest_eta(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            _progress(
                "FITTING_DYNAMIC_CANDIDATE",
                {
                    "elapsedSeconds": 2.0,
                    "rowsProcessed": 10,
                    "rowsTotal": 20,
                    "candidateId": "D3",
                    "validationSeason": 2024,
                    "errors": 0,
                },
            )
        rendered = output.getvalue()
        self.assertIn("Milestone: Milestone A", rendered)
        self.assertIn("Component: Dynamic Player State", rendered)
        self.assertIn("Throughput: 5 rows/sec", rendered)
        self.assertIn("ETA: unavailable", rendered)

    def test_full_run_registers_complete_component_and_prints_study_graph_ids(self) -> None:
        runtime = (
            REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
        )
        database_path = (
            REPOSITORY_ROOT
            / ".runtime"
            / "asp-model-studio"
            / "persistence"
            / "asp_model_studio.db"
        )
        phase3 = SimpleNamespace(feature_table=SimpleNamespace(num_rows=3), d0_folds={})
        component = {
            "componentId": "fixture-component",
            "selected": {"candidateId": "D4"},
            "decision": {"decision": "DYNAMIC_STATE_RESEARCH_CHALLENGER"},
        }
        artifacts = [{"artifactId": "fixture-artifact"}]
        saved = {
            "phase4": {
                "studyId": "fixture-study",
                "components": {
                    "dynamicState": {"componentId": "fixture-registered-component"}
                },
                "graph": {"graphId": "fixture-graph"},
            }
        }
        parent = SimpleNamespace(
            partitions=tuple(range(329)),
            cache_hits=329,
            cache_misses=0,
        )
        args = _arguments(
            [
                "--exchange-root",
                "logical-exchange",
                "--database",
                str(database_path),
                "--runtime-root",
                str(runtime),
                "--user-id",
                "fixture-user",
            ]
        )
        output = StringIO()
        progress = Mock()
        with (
            patch("scripts.run_mlb_dynamic_player_state.Database") as database,
            patch("scripts.run_mlb_dynamic_player_state._validate_isolated_database_file"),
            patch(
                "scripts.run_mlb_dynamic_player_state._validated_dataset_cache_path",
                return_value=runtime / DATASET_VALIDATION_CACHE_RELATIVE,
            ),
            patch(
                "scripts.run_mlb_dynamic_player_state.approved_package_root",
                return_value=Path("registered-parent"),
            ),
            patch(
                "scripts.run_mlb_dynamic_player_state.approved_bridge_root",
                return_value=Path("registered-bridge"),
            ),
            patch("scripts.run_mlb_dynamic_player_state.SportsDatasetManifestConsumer") as consumer,
            patch("scripts.run_mlb_dynamic_player_state.SportsIdentityBridgeV1Consumer") as bridge,
            patch(
                "scripts.run_mlb_dynamic_player_state.load_phase3_runtime_inputs",
                return_value=phase3,
            ),
            patch(
                "scripts.run_mlb_dynamic_player_state.run_mlb_dynamic_player_state",
                return_value={"component": component, "artifacts": artifacts},
            ) as runner,
            patch(
                "scripts.run_mlb_dynamic_player_state.build_phase4_study_payload",
                return_value={"fixture": "study"},
            ) as build_study,
            patch("scripts.run_mlb_dynamic_player_state.SportsPhase4Registry") as registry,
            patch(
                "scripts.run_mlb_dynamic_player_state._revision",
                return_value="fixture:cli-registration",
            ),
            redirect_stdout(output),
        ):
            consumer.return_value.validate.return_value = parent
            bridge.return_value.validate.return_value = object()
            registry.return_value.register.return_value = saved
            result = _worker_main(
                args,
                progress=progress,
            )
        self.assertEqual(result, 0)
        database.return_value.initialize.assert_called_once_with()
        registry.return_value.validate_registered_authorities.assert_called_once_with()
        self.assertIs(runner.call_args.kwargs["progress"], progress)
        consumer.call_args.kwargs["progress"]({"stage": "DATASET_FIXTURE"})
        bridge.call_args.kwargs["progress"]({"stage": "BRIDGE_FIXTURE"})
        progress.assert_any_call("DATASET_FIXTURE", {"stage": "DATASET_FIXTURE"})
        progress.assert_any_call("BRIDGE_FIXTURE", {"stage": "BRIDGE_FIXTURE"})
        build_call = build_study.call_args.kwargs
        self.assertIs(build_call["dynamic_state"], component)
        self.assertIs(build_call["artifacts"], artifacts)
        self.assertEqual(build_call["code_revision"], "fixture:cli-registration")
        self.assertEqual(build_call["phase3_baseline"]["status"], "RESEARCH_BASELINE")
        registry.return_value.register.assert_called_once_with(
            {"fixture": "study"}, user_id="fixture-user"
        )
        self.assertIn("study_id=fixture-study", output.getvalue())
        self.assertIn("graph_id=fixture-graph", output.getvalue())
        self.assertIn(
            "component_id=fixture-registered-component", output.getvalue()
        )
        self.assertNotIn("component_id=fixture-component ", output.getvalue())

    def test_main_uses_whole_cli_supervisor_and_frozen_fit_limits(self) -> None:
        database_path = (
            REPOSITORY_ROOT
            / ".runtime"
            / "asp-model-studio"
            / "persistence"
            / "asp_model_studio.db"
        )
        forwarded = [
            "--exchange-root",
            "logical-exchange",
            "--database",
            str(database_path),
            "--preflight-only",
        ]
        with patch(
            "scripts.run_mlb_dynamic_player_state._supervise",
            return_value=SimpleNamespace(returncode=0),
        ) as supervise:
            self.assertEqual(main(forwarded), 0)
        supervise.assert_called_once_with(forwarded)
        self.assertEqual(
            DYNAMIC_STAGE_LIMITS,
            {
                "TUNING_DYNAMIC_LOGISTIC_2023": 5400.0,
                "FITTING_DYNAMIC_2023_VALIDATING_2024": 5400.0,
                "REFITTING_DYNAMIC_THROUGH_2024_VALIDATING_2025": 5400.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
