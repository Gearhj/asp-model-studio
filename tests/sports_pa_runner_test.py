from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_datasets.constants import PROJECT_ID
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling.feature_contract import (
    FEATURE_NAMES,
    feature_contract_payload,
    feature_contract_sha,
)
from server.sports_modeling.feature_view import (
    FeatureViewIntegrityError,
    _bridge_authorities_match,
    build_feature_view_from_tables,
)
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_modeling.runner import (
    RUNTIME_URI_PREFIX,
    SportsPARunnerError,
    assemble_mlb_pa_research_run,
    persist_feature_materialization_checkpoint,
)
from server.sports_modeling.training import FoldPreprocessor, run_training_experiment
from scripts.run_mlb_pa_baseline import _revision, _validate_isolated_database_file


CODE_REVISION = "test:phase3-pa-fixture"
BATTER_UUID = "00000000-0000-4000-8000-000000000001"
PITCHER_UUID = "00000000-0000-4000-8000-000000000002"


def _batting_metrics(multiplier: int) -> str:
    return json.dumps(
        {
            "2B": 20 * multiplier,
            "3B": 3 * multiplier,
            "AB": 400 * multiplier,
            "BB": 45 * multiplier,
            "H": 110 * multiplier,
            "HBP": 5 * multiplier,
            "HR": 18 * multiplier,
            "SF": 4 * multiplier,
            "SH": 1 * multiplier,
            "SO": 90 * multiplier,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _pitching_metrics(multiplier: int, *, bfp: int | None = None) -> str:
    return json.dumps(
        {
            "BB": 30 * multiplier,
            "BFP": 600 * multiplier if bfp is None else bfp,
            "ER": 55 * multiplier,
            "G": 30 * multiplier,
            "GIDP": None,
            "GS": 25 * multiplier,
            "H": 140 * multiplier,
            "HBP": 4 * multiplier,
            "HR": 16 * multiplier,
            "IPouts": 500 * multiplier,
            "SO": 150 * multiplier,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _prior_table() -> pa.Table:
    rows: list[dict[str, object]] = []
    for source_season in (2022, 2023, 2024):
        multiplier = source_season - 2021
        for canonical, domain, metrics in (
            (BATTER_UUID, "BATTING", _batting_metrics(multiplier)),
            (PITCHER_UUID, "PITCHING", _pitching_metrics(multiplier)),
        ):
            rows.append(
                {
                    "canonical_player_id": canonical,
                    "identity_resolution_status": "EXACT",
                    "season": source_season,
                    "domain": domain,
                    "eligible_from_season": source_season + 1,
                    "same_season_predictor_eligible": False,
                    "metrics_json": metrics,
                }
            )
    return pa.Table.from_pylist(rows)


def _pa_table() -> pa.Table:
    rows: list[dict[str, object]] = []
    sequence = 0
    for season, date_count in ((2023, 4), (2024, 2), (2025, 2)):
        for date_index in range(date_count):
            game_id = f"{season}-game-{date_index}"
            game_date = f"{season}-04-{date_index + 1:02d}"
            for within_game in range(8):
                sequence += 1
                top_bottom = (within_game + date_index) % 2
                visiting_score = (within_game + date_index) % 5
                home_score = (within_game * 2 + date_index) % 5
                rows.append(
                    {
                        "plate_appearance_id": f"pa-{sequence:04d}",
                        "game_id": game_id,
                        "game_date": game_date,
                        "season": season,
                        "population_category": "GEN2_PRIMARY_2023_2025",
                        "strict_population": "GEN2_STRICT_DEPLOYABLE_RECONSTRUCTION",
                        # The frozen parent predates the registered companion bridge.
                        # Exact canonical resolution is established by the bridge join below.
                        "canonical_identity_resolved": False,
                        "visiting_team_id": "VIS",
                        "home_team_id": "HOM",
                        "batting_team_id": "VIS" if top_bottom == 0 else "HOM",
                        "batter_id": "batter-key",
                        "pitcher_id": "pitcher-key",
                        "outcome": PA_CLASS_ORDER[(within_game + 3 * date_index) % 8],
                        "inning": 1 + ((within_game + date_index) % 9),
                        "top_bottom": top_bottom,
                        "outs_before": (within_game + 2 * date_index) % 3,
                        "base_mask_before": (within_game + date_index) % 8,
                        "visiting_score_before": visiting_score,
                        "home_score_before": home_score,
                        "timing_risk_label": "RETROSPECTIVE_EVENT_OUTCOME_TIMING_RISK",
                        "target_only_not_pregame_feature": True,
                        "strict_same_game_pregame_eligible": False,
                        "enhanced_research_eligible": True,
                    }
                )
    return pa.Table.from_pylist(rows)


def _built_view(
    pa_table: pa.Table | None = None,
    prior_table: pa.Table | None = None,
):
    return build_feature_view_from_tables(
        [pa_table or _pa_table()],
        prior_table or _prior_table(),
        retrosheet_aliases={
            "batter-key": BATTER_UUID,
            "pitcher-key": PITCHER_UUID,
        },
        dimension_uuids=frozenset({BATTER_UUID, PITCHER_UUID}),
        code_revision=CODE_REVISION,
    )


class SportsPAFeatureViewTest(unittest.TestCase):
    def test_bridge_authorities_use_the_versioned_nested_manifest_contract(self) -> None:
        manifest = {
            "bridge_manifest_sha256": (
                "6b69e7dcf4c5db7615420ee9f6f6f797b0335e31ab475646291f3a4cf90c52cf"
            ),
            "parent_binding": {
                "parent_dataset_manifest_sha256": (
                    "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
                ),
                "parent_partition_authority_sha256": (
                    "8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437"
                ),
            },
            "totals": {
                "alias_authority_sha256": (
                    "ddb828aee391b2f725ba4540a874865963313e6c210f246eacd7bbcf28025661"
                ),
                "dimension_authority_sha256": (
                    "6f30e1b30ca41002d6cbb2dea8b90da5abfad4f62f96237e780fbee518005acf"
                ),
            },
        }
        self.assertTrue(_bridge_authorities_match(manifest))
        manifest["totals"]["alias_authority_sha256"] = "0" * 64
        self.assertFalse(_bridge_authorities_match(manifest))

    def test_contract_audits_every_feature_and_full_exclusions(self) -> None:
        contract = feature_contract_payload()
        definitions = contract["fieldDefinitions"]
        self.assertEqual([item["featureName"] for item in definitions], list(FEATURE_NAMES))
        self.assertEqual([item["featureOrder"] for item in definitions], list(range(len(FEATURE_NAMES))))
        required = {
            "featureName",
            "sourceFamily",
            "physicalFields",
            "semanticRole",
            "included",
            "reason",
            "dtype",
            "transformation",
            "missingnessPolicy",
            "temporalRule",
            "joinRule",
            "featureOrder",
        }
        self.assertTrue(all(set(item) == required for item in definitions))
        self.assertTrue(all(set(item) == required for item in contract["consideredExclusions"]))
        excluded = {item["featureName"] for item in contract["consideredExclusions"]}
        self.assertTrue(
            {
                "terminal_outcome", "post_terminal_state", "source_provenance",
                "identity_fields", "actual_participants", "actual_weather",
                "batter_side", "pitcher_hand", "platoon",
            }.issubset(excluded)
        )
        self.assertEqual(feature_contract_sha(contract), feature_contract_sha())

    def test_feature_view_is_sorted_content_addressed_and_uses_latest_prior(self) -> None:
        source = _pa_table()
        reversed_source = source.take(pa.array(list(reversed(range(source.num_rows)))))
        first = _built_view(source)
        second = _built_view(reversed_source)
        self.assertEqual(first.content_sha, second.content_sha)
        self.assertEqual(first.parquet_bytes, second.parquet_bytes)
        self.assertEqual(first.row_count, 64)
        self.assertEqual(first.season_rows, {2023: 32, 2024: 16, 2025: 16})
        self.assertEqual(first.table["batter_prior_season"].to_pylist()[-1], 2024)
        self.assertEqual(first.table["pitcher_prior_season"].to_pylist()[0], 2022)
        self.assertFalse(any(first.table["batter_prior_missing"].to_pylist()))
        parquet = pq.ParquetFile(pa.BufferReader(first.parquet_bytes))
        self.assertEqual(parquet.schema_arrow.metadata[b"codeRevision"], CODE_REVISION.encode())

    def test_feature_view_rejects_top_bottom_team_conflict(self) -> None:
        rows = _pa_table().to_pylist()
        rows[0]["batting_team_id"] = "HOM"
        with self.assertRaisesRegex(FeatureViewIntegrityError, "top_bottom convention"):
            _built_view(pa.Table.from_pylist(rows))

    def test_legitimate_missing_prior_is_explicit_and_rates_remain_missing(self) -> None:
        pitching_only = pa.Table.from_pylist(
            [row for row in _prior_table().to_pylist() if row["domain"] == "PITCHING"]
        )
        view = _built_view(prior_table=pitching_only)
        self.assertTrue(all(view.table["batter_prior_missing"].to_pylist()))
        self.assertTrue(all(value is None for value in view.table["batter_avg"].to_pylist()))
        batter_coverage = [row for row in view.prior_coverage if row["role"] == "BATTER"]
        self.assertTrue(
            all(
                row["legitimateMissingPriorRows"] == row["referenceRows"]
                and row["unresolvedIdentityRows"] == 0
                for row in batter_coverage
            )
        )

    def test_future_prior_is_ignored_and_invalid_prior_grain_fails(self) -> None:
        rows = _prior_table().to_pylist()
        rows.append({**rows[0], "season": 2025, "eligible_from_season": 2026})
        view = _built_view(prior_table=pa.Table.from_pylist(rows))
        self.assertEqual(view.table["batter_prior_season"].to_pylist()[-1], 2024)

        duplicated = _prior_table().to_pylist()
        duplicated.append(dict(duplicated[0]))
        with self.assertRaisesRegex(FeatureViewIntegrityError, "duplicate player_prior"):
            _built_view(prior_table=pa.Table.from_pylist(duplicated))

        same_season = _prior_table().to_pylist()
        same_season.append(
            {**same_season[0], "season": 2024, "eligible_from_season": 2024}
        )
        with self.assertRaisesRegex(FeatureViewIntegrityError, "temporal eligibility"):
            _built_view(prior_table=pa.Table.from_pylist(same_season))

    def test_unused_null_prior_metric_is_allowed_but_required_metric_is_not(self) -> None:
        self.assertEqual(_built_view().row_count, 64)
        rows = _prior_table().to_pylist()
        pitching_index = next(
            index for index, row in enumerate(rows) if row["domain"] == "PITCHING"
        )
        pitching = json.loads(rows[pitching_index]["metrics_json"])
        pitching["BFP"] = None
        rows[pitching_index]["metrics_json"] = json.dumps(
            pitching, sort_keys=True, separators=(",", ":")
        )
        with self.assertRaisesRegex(
            FeatureViewIntegrityError, "missing or nonnumeric: BFP"
        ):
            _built_view(prior_table=pa.Table.from_pylist(rows))


class SportsPATrainingRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.view = _built_view()
        cls.experiment = run_training_experiment(cls.view.table)

    def test_frozen_training_policy_and_convergence(self) -> None:
        result = self.experiment
        self.assertIn(result.selected_candidate_id, {"C1", "C2", "C3", "C4"})
        self.assertEqual([item["candidateId"] for item in result.candidates], ["C0", "C1", "C2", "C3", "C4"])
        self.assertEqual(result.split_evidence["lastTrainingDate"], "2023-04-03")
        for candidate in result.candidates:
            self.assertEqual(candidate["foldMetrics"][0]["status"], "COMPLETE")
            if candidate["candidateId"] == "C0":
                self.assertEqual(candidate["convergence"]["status"], "NOT_APPLICABLE")
            else:
                self.assertEqual(candidate["convergence"]["status"], "CONVERGED")
                self.assertEqual(candidate["convergence"]["solver"], "lbfgs")
                self.assertEqual(candidate["config"]["maxIter"], 2_000)
                self.assertEqual(candidate["config"]["tolerance"], 1e-7)
            expected_final = candidate["candidateId"] in {"C0", "C1", result.selected_candidate_id}
            self.assertEqual(
                candidate["foldMetrics"][1]["status"],
                "COMPLETE" if expected_final else "NOT_RUN_BY_POLICY",
            )
            if expected_final and candidate["candidateId"] != "C0":
                final_model = result.models[(2025, candidate["candidateId"])]
                self.assertEqual(final_model.c_value, candidate["config"]["selectedC"])

    def test_preprocessor_uses_only_training_rows_and_fixed_encoding(self) -> None:
        values = {
            "context_inning": np.asarray([1.0, np.nan, 999.0]),
            "context_top_bottom": np.asarray([0.0, 1.0, 1.0]),
        }
        training = np.asarray([True, True, False])
        validation = ~training
        fitted = FoldPreprocessor.fit(
            values,
            ("context_inning", "context_top_bottom"),
            training,
        )
        self.assertEqual(fitted.numeric_state["context_inning"]["imputationMean"], 1.0)
        self.assertEqual(
            fitted.state()["expandedFeatureNames"],
            ["context_inning", "context_top_bottom=0", "context_top_bottom=1"],
        )
        self.assertEqual(fitted.transform(values, validation).shape, (1, 3))

    def test_scientific_fit_and_model_state_are_deterministic(self) -> None:
        repeated = run_training_experiment(self.view.table)
        self.assertEqual(repeated.selected_candidate_id, self.experiment.selected_candidate_id)
        for key in sorted(self.experiment.models):
            self.assertEqual(
                canonical_json_bytes(self.experiment.models[key].state()),
                canonical_json_bytes(repeated.models[key].state()),
            )
        for season in (2024, 2025):
            for candidate_id in self.experiment.folds[season].probabilities:
                np.testing.assert_array_equal(
                    self.experiment.folds[season].probabilities[candidate_id],
                    repeated.folds[season].probabilities[candidate_id],
                )

    def test_assembly_writes_content_addressed_artifacts_and_exact_payload(self) -> None:
        if os.getenv("ASP_REQUIRE_ISOLATED_RUNTIME", "").strip().lower() in ("1", "true", "yes"):
            self.skipTest("legacy runner exercises the shared .runtime governed boundary; not run under the isolated gate")
        repository_root = Path(__file__).resolve().parents[1]
        boundary = repository_root / ".runtime" / "asp-model-studio" / "sports-modeling"
        boundary.mkdir(parents=True, exist_ok=True)
        runtime_root = boundary / f"pa-runner-test-{uuid.uuid4().hex}"
        runtime_root.mkdir()
        try:
            checkpoint = persist_feature_materialization_checkpoint(
                project_id=PROJECT_ID,
                join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                feature_view=self.view,
                runtime_root=runtime_root,
                code_revision=CODE_REVISION,
                protected_roots=(repository_root / "server", repository_root / "tests"),
            )
            reused = persist_feature_materialization_checkpoint(
                project_id=PROJECT_ID,
                join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                feature_view=self.view,
                runtime_root=runtime_root,
                code_revision=CODE_REVISION + "+downstream-fix",
                protected_roots=(repository_root / "server", repository_root / "tests"),
            )
            self.assertEqual(checkpoint, reused)
            progress_events: list[tuple[str, dict[str, object]]] = []
            payload = assemble_mlb_pa_research_run(
                project_id=PROJECT_ID,
                join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                feature_view=self.view,
                experiment=self.experiment,
                runtime_root=runtime_root,
                code_revision=CODE_REVISION,
                protected_roots=(repository_root / "server", repository_root / "tests"),
                progress=lambda stage, evidence: progress_events.append((stage, evidence)),
                feature_checkpoint=checkpoint,
            )
            expected_top = {
                "schemaVersion", "runId", "runSha", "projectId", "parent",
                "identityBridge", "classOrder", "featureView", "experiment",
                "candidates", "selected", "calibration", "bootstrapComparisons",
                "artifacts", "graph", "decision",
                "runIdentity",
            }
            self.assertEqual(set(payload), expected_top)
            semantic = dict(payload)
            semantic.pop("runId")
            semantic.pop("runSha")
            self.assertEqual(payload["runSha"], sha256_bytes(canonical_json_bytes(semantic)))
            self.assertTrue(payload["runId"].endswith(payload["runIdentity"]["coreSha"]))
            self.assertEqual(progress_events[-1][0], "RESEARCH_RUN_COMPLETE")
            self.assertEqual(len(payload["bootstrapComparisons"]), 4)
            self.assertEqual(
                {(row["validationSeason"], row["baselineCandidateId"]) for row in payload["bootstrapComparisons"]},
                {(2024, "C0"), (2024, "C1"), (2025, "C0"), (2025, "C1")},
            )
            self.assertTrue(payload["decision"]["researchOnly"])
            self.assertFalse(payload["decision"]["deploymentAuthorized"])
            self.assertTrue(all(row["artifactId"].endswith(row["sha256"]) for row in payload["artifacts"]))
            artifact_types = {row["artifactType"] for row in payload["artifacts"]}
            self.assertTrue(
                {
                    "FEATURE_VIEW", "FEATURE_VIEW_RUN_BINDING", "CLASS_ORDER",
                    "MODEL_STATE", "PREPROCESSOR_STATE", "CONFUSION_MATRICES",
                }.issubset(artifact_types)
            )
            binding_json = None
            for artifact in payload["artifacts"]:
                suffix = artifact["logicalUri"].removeprefix(RUNTIME_URI_PREFIX + "/")
                physical = runtime_root / "mlb-pa-v1" / suffix
                if artifact["artifactType"] == "FEATURE_VIEW":
                    metadata = pq.ParquetFile(physical).schema_arrow.metadata or {}
                    materialization_bindings = json.loads(metadata[b"artifactBindings"])
                    self.assertEqual(materialization_bindings["runId"], checkpoint.materialization_id)
                    continue
                if artifact["mediaType"] == "application/json":
                    envelope = json.loads(physical.read_text(encoding="utf-8"))
                    bindings = envelope["bindings"]
                else:
                    metadata = pq.ParquetFile(physical).schema_arrow.metadata or {}
                    bindings = json.loads(metadata[b"artifactBindings"])
                self.assertEqual(bindings["runId"], payload["runId"])
                self.assertEqual(bindings["runCreatedAt"], payload["runIdentity"]["createdAt"])
                self.assertEqual(bindings["codeRevision"], CODE_REVISION)
                if artifact["artifactType"] == "FEATURE_VIEW_RUN_BINDING":
                    binding_json = envelope["payload"]
            self.assertEqual(binding_json["materializationId"], checkpoint.materialization_id)
            labels = {node["label"]: node["status"] for node in payload["graph"]["nodes"]}
            self.assertEqual(labels["MLB FD1 Dataset Manifest"], "COMPLETE")
            self.assertEqual(labels["Retrospective Evaluation Evidence"], "COMPLETE")
            self.assertEqual(labels["Standalone ASP Bundle"], "NOT_CONFIGURED")
        finally:
            shutil.rmtree(runtime_root)

    def test_runtime_escape_is_rejected_before_writes(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(SportsPARunnerError, "runtime_root"):
            assemble_mlb_pa_research_run(
                project_id=PROJECT_ID,
                join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                feature_view=self.view,
                experiment=self.experiment,
                runtime_root=repository_root / ".runtime" / "outside-governed-boundary",
                code_revision=CODE_REVISION,
                protected_roots=(repository_root / "server", repository_root / "tests"),
            )

    def test_descendant_chain_is_rejected_before_directory_creation(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        boundary = repository_root / ".runtime" / "asp-model-studio" / "sports-modeling"
        boundary.mkdir(parents=True, exist_ok=True)
        runtime_root = boundary / f"pa-runner-descendant-test-{uuid.uuid4().hex}"
        runtime_root.mkdir()
        from server.sports_modeling import runner as runner_module

        original_reject = runner_module.reject_reparse_chain

        def simulated_descendant_junction(path: Path, *, label: str) -> None:
            candidate = Path(path)
            if "objects" in candidate.parts:
                if candidate.exists():
                    self.fail("artifact directory was created before its chain was validated")
                raise SportsPARunnerError("simulated descendant junction")
            original_reject(candidate, label=label)

        try:
            with (
                patch(
                    "server.sports_modeling.runner.reject_reparse_chain",
                    side_effect=simulated_descendant_junction,
                ),
                self.assertRaisesRegex(SportsPARunnerError, "simulated descendant junction"),
            ):
                persist_feature_materialization_checkpoint(
                    project_id=PROJECT_ID,
                    join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                    feature_view=self.view,
                    runtime_root=runtime_root,
                    code_revision=CODE_REVISION,
                    protected_roots=(repository_root / "server", repository_root / "tests"),
                )
            self.assertFalse((runtime_root / "mlb-pa-v1" / "objects").exists())
        finally:
            shutil.rmtree(runtime_root)

    def test_tampered_checkpoint_absolute_artifact_uri_is_rejected(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        boundary = repository_root / ".runtime" / "asp-model-studio" / "sports-modeling"
        boundary.mkdir(parents=True, exist_ok=True)
        runtime_root = boundary / f"pa-runner-path-test-{uuid.uuid4().hex}"
        runtime_root.mkdir()
        try:
            persist_feature_materialization_checkpoint(
                project_id=PROJECT_ID,
                join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                feature_view=self.view,
                runtime_root=runtime_root,
                code_revision=CODE_REVISION,
                protected_roots=(repository_root / "server", repository_root / "tests"),
            )
            pointer = (
                runtime_root
                / "mlb-pa-v1"
                / "feature-materializations"
                / f"sha256-{self.view.content_sha}"
                / "checkpoint.json"
            )
            tampered = json.loads(pointer.read_text(encoding="utf-8"))
            tampered["featureArtifact"]["logicalUri"] = (
                RUNTIME_URI_PREFIX + "/C:/outside-governed-runtime.parquet"
            )
            pointer.write_bytes(canonical_json_bytes(tampered))
            with self.assertRaisesRegex(SportsPARunnerError, "logical URI is unsafe"):
                persist_feature_materialization_checkpoint(
                    project_id=PROJECT_ID,
                    join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                    feature_view=self.view,
                    runtime_root=runtime_root,
                    code_revision=CODE_REVISION,
                    protected_roots=(repository_root / "server", repository_root / "tests"),
                )
        finally:
            shutil.rmtree(runtime_root)

    def test_self_consistently_rehashed_tampered_feature_artifact_is_rejected(self) -> None:
        if os.getenv("ASP_REQUIRE_ISOLATED_RUNTIME", "").strip().lower() in ("1", "true", "yes"):
            self.skipTest("legacy runner exercises the shared .runtime governed boundary; not run under the isolated gate")
        repository_root = Path(__file__).resolve().parents[1]
        boundary = repository_root / ".runtime" / "asp-model-studio" / "sports-modeling"
        boundary.mkdir(parents=True, exist_ok=True)
        runtime_root = boundary / f"pa-runner-content-test-{uuid.uuid4().hex}"
        runtime_root.mkdir()
        try:
            persist_feature_materialization_checkpoint(
                project_id=PROJECT_ID,
                join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                feature_view=self.view,
                runtime_root=runtime_root,
                code_revision=CODE_REVISION,
                protected_roots=(repository_root / "server", repository_root / "tests"),
            )
            pointer = (
                runtime_root
                / "mlb-pa-v1"
                / "feature-materializations"
                / f"sha256-{self.view.content_sha}"
                / "checkpoint.json"
            )
            stored = json.loads(pointer.read_text(encoding="utf-8"))

            feature_suffix = stored["featureArtifact"]["logicalUri"].removeprefix(
                RUNTIME_URI_PREFIX + "/"
            )
            feature_path = runtime_root / "mlb-pa-v1" / feature_suffix
            tampered_table = pq.read_table(feature_path)
            innings = tampered_table["context_inning"].to_pylist()
            innings[0] = 2 if innings[0] == 1 else 1
            tampered_table = tampered_table.set_column(
                tampered_table.schema.get_field_index("context_inning"),
                "context_inning",
                pa.array(innings, type=pa.int16()),
            )
            sink = pa.BufferOutputStream()
            pq.write_table(
                tampered_table,
                sink,
                compression="zstd",
                compression_level=9,
                use_dictionary=False,
                write_statistics=True,
                version="2.6",
                data_page_version="1.0",
                row_group_size=65_536,
            )
            tampered_bytes = sink.getvalue().to_pybytes()
            tampered_sha = sha256_bytes(tampered_bytes)
            tampered_relative = (
                Path("objects")
                / "sha256"
                / tampered_sha[:2]
                / tampered_sha
                / "mlb-pa-feature-view-v1.parquet"
            )
            tampered_path = runtime_root / "mlb-pa-v1" / tampered_relative
            tampered_path.parent.mkdir(parents=True)
            tampered_path.write_bytes(tampered_bytes)
            stored["featureArtifact"].update(
                {
                    "artifactId": f"sports-pa-artifact:feature_view:sha256:{tampered_sha}",
                    "logicalUri": f"{RUNTIME_URI_PREFIX}/{tampered_relative.as_posix()}",
                    "sha256": tampered_sha,
                    "byteCount": len(tampered_bytes),
                }
            )

            manifest_suffix = stored["manifestArtifact"]["logicalUri"].removeprefix(
                RUNTIME_URI_PREFIX + "/"
            )
            manifest_path = runtime_root / "mlb-pa-v1" / manifest_suffix
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["payload"]["featureArtifact"] = dict(stored["featureArtifact"])
            manifest_bytes = canonical_json_bytes(manifest)
            manifest_sha = sha256_bytes(manifest_bytes)
            manifest_relative = (
                Path("objects")
                / "sha256"
                / manifest_sha[:2]
                / manifest_sha
                / "feature-materialization.json"
            )
            rebound_manifest_path = runtime_root / "mlb-pa-v1" / manifest_relative
            rebound_manifest_path.parent.mkdir(parents=True)
            rebound_manifest_path.write_bytes(manifest_bytes)
            stored["manifestArtifact"].update(
                {
                    "artifactId": (
                        "sports-pa-artifact:feature_materialization_manifest:sha256:"
                        + manifest_sha
                    ),
                    "logicalUri": f"{RUNTIME_URI_PREFIX}/{manifest_relative.as_posix()}",
                    "sha256": manifest_sha,
                    "byteCount": len(manifest_bytes),
                }
            )
            pointer.write_bytes(canonical_json_bytes(stored))

            with self.assertRaisesRegex(
                SportsPARunnerError,
                "Parquet content differs from rebuilt feature view",
            ):
                persist_feature_materialization_checkpoint(
                    project_id=PROJECT_ID,
                    join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                    feature_view=self.view,
                    runtime_root=runtime_root,
                    code_revision=CODE_REVISION + "+downstream-fix",
                    protected_roots=(repository_root / "server", repository_root / "tests"),
                )
        finally:
            shutil.rmtree(runtime_root)

    def test_stale_rebuilt_table_with_reused_declared_sha_is_rejected(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        boundary = repository_root / ".runtime" / "asp-model-studio" / "sports-modeling"
        boundary.mkdir(parents=True, exist_ok=True)
        runtime_root = boundary / f"pa-runner-stale-view-test-{uuid.uuid4().hex}"
        runtime_root.mkdir()
        try:
            persist_feature_materialization_checkpoint(
                project_id=PROJECT_ID,
                join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                feature_view=self.view,
                runtime_root=runtime_root,
                code_revision=CODE_REVISION,
                protected_roots=(repository_root / "server", repository_root / "tests"),
            )
            stale_table = self.view.table
            innings = stale_table["context_inning"].to_pylist()
            innings[0] = 2 if innings[0] == 1 else 1
            stale_table = stale_table.set_column(
                stale_table.schema.get_field_index("context_inning"),
                "context_inning",
                pa.array(innings, type=pa.int16()),
            )
            stale_view = replace(self.view, table=stale_table)
            with self.assertRaisesRegex(
                SportsPARunnerError,
                "Parquet content differs from rebuilt feature view",
            ):
                persist_feature_materialization_checkpoint(
                    project_id=PROJECT_ID,
                    join_audit_id="sports-identity-join-audit:sha256:" + "a" * 64,
                    feature_view=stale_view,
                    runtime_root=runtime_root,
                    code_revision=CODE_REVISION + "+downstream-fix",
                    protected_roots=(repository_root / "server", repository_root / "tests"),
                )
        finally:
            shutil.rmtree(runtime_root)


class SportsPACommandProvenanceTest(unittest.TestCase):
    def test_explicit_code_revision_is_preserved(self) -> None:
        with patch.dict(
            os.environ,
            {"ASP_MODEL_STUDIO_CODE_REVISION": "source:sha256:" + "a" * 64},
        ):
            self.assertEqual(_revision(), "source:sha256:" + "a" * 64)

    def test_missing_git_provenance_fails_closed(self) -> None:
        with (
            patch.dict(os.environ, {"ASP_MODEL_STUDIO_CODE_REVISION": ""}),
            patch(
                "scripts.run_mlb_pa_baseline.subprocess.run",
                side_effect=FileNotFoundError("git unavailable"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "content-bound source provenance"):
                _revision()

    def test_hardlinked_database_is_rejected_before_initialization(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        boundary = repository_root / ".runtime" / "asp-model-studio" / "sports-modeling"
        boundary.mkdir(parents=True, exist_ok=True)
        scratch = boundary / f"pa-database-link-test-{uuid.uuid4().hex}"
        scratch.mkdir()
        source = scratch / "source.db"
        linked = scratch / "asp_model_studio.db"
        try:
            source.write_bytes(b"not-a-live-database")
            try:
                os.link(source, linked)
            except OSError as exc:
                self.skipTest(f"hardlinks are unavailable: {exc}")
            with self.assertRaisesRegex(RuntimeError, "single-link regular file"):
                _validate_isolated_database_file(linked, label="Test database chain")
        finally:
            shutil.rmtree(scratch)


if __name__ == "__main__":
    unittest.main()
