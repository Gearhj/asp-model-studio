from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import call, patch

from server.persistence.db import Database, json_dumps
from server.sports_datasets.access import (
    QueryCancellationRegistry,
    SportsDataAccessError,
    SportsDatasetAccessService,
    approved_package_root,
)
from server.sports_datasets.constants import LOGICAL_PACKAGE_ROOT, PACKAGE_RELATIVE_ROOT, REGISTRATION_ID
from server.sports_datasets.constants import PARTITION_AUTHORITY_SHA, PA_CLASS_ORDER
from server.sports_datasets.consumer import (
    VALIDATION_CACHE_LOCK,
    canonical_json_bytes,
    raw_absolute_path,
    sha256_file,
)
from server.sports_datasets.registry import SportsDatasetRegistry
from tests.sports_dataset_test_fixture import golden_package


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPOSITORY_ROOT / ".tmp"


@unittest.skipUnless(os.getenv("ASP_MODEL_EXCHANGE_ROOT"), "ASP_MODEL_EXCHANGE_ROOT is required for registered data-access tests")
class SportsDatasetRegistryAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch = SCRATCH_ROOT / f"sports-registry-access-{uuid.uuid4().hex}"
        cls.scratch.mkdir(parents=True, exist_ok=False)
        cls.exchange_root = Path(os.environ["ASP_MODEL_EXCHANGE_ROOT"])
        validated, package_root, shared_cache_path = golden_package()
        cls.validated = validated
        cls.package_root = package_root
        cls.cache_path = cls.scratch / "validation-cache.json"
        shutil.copy2(shared_cache_path, cls.cache_path)
        cls.database = Database(cls.scratch / "sports-test.db")
        cls.database.initialize()
        cls.registry = SportsDatasetRegistry(cls.database)
        cls.first = cls.registry.register(validated, user_id="test-admin")
        cls.access = SportsDatasetAccessService(
            cls.registry,
            exchange_root=cls.exchange_root,
            validation_cache_path=cls.cache_path,
        )

    def test_registration_is_idempotent_and_unique(self) -> None:
        with self.database.connection() as connection:
            original_project = connection.execute(
                "SELECT created_by, created_at FROM sports_research_projects WHERE registration_id = ?",
                (REGISTRATION_ID,),
            ).fetchone()
            partition = connection.execute(
                "SELECT partition_id, row_count FROM sports_dataset_partitions WHERE registration_id = ? ORDER BY partition_id LIMIT 1",
                (REGISTRATION_ID,),
            ).fetchone()
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE sports_dataset_partitions SET row_count = ? WHERE partition_id = ?",
                (partition["row_count"] + 7, partition["partition_id"]),
            )
            connection.execute(
                "UPDATE sports_research_projects SET primary_target = 'CORRUPT' WHERE registration_id = ?",
                (REGISTRATION_ID,),
            )

        second = self.registry.register(self.validated, user_id="different-admin")
        self.assertEqual(self.first["registration_id"], second["registration_id"])
        self.assertEqual(self.first["registration_disposition"], "CREATED")
        self.assertEqual(second["registration_disposition"], "REUSED")
        with self.database.connection() as connection:
            registrations = connection.execute("SELECT COUNT(*) FROM sports_dataset_registrations").fetchone()[0]
            partitions = connection.execute("SELECT COUNT(*) FROM sports_dataset_partitions").fetchone()[0]
            projects = connection.execute("SELECT COUNT(*) FROM sports_research_projects").fetchone()[0]
            repaired_partition = connection.execute(
                "SELECT row_count FROM sports_dataset_partitions WHERE partition_id = ?",
                (partition["partition_id"],),
            ).fetchone()
            repaired_project = connection.execute(
                "SELECT primary_target, created_by, created_at FROM sports_research_projects WHERE registration_id = ?",
                (REGISTRATION_ID,),
            ).fetchone()
        self.assertEqual(registrations, 1)
        self.assertEqual(partitions, 329)
        self.assertEqual(projects, 1)
        self.assertEqual(repaired_partition["row_count"], partition["row_count"])
        self.assertEqual(repaired_project["primary_target"], "Plate-Appearance Outcome")
        self.assertEqual(repaired_project["created_by"], original_project["created_by"])
        self.assertEqual(repaired_project["created_at"], original_project["created_at"])

    def test_metadata_only_registration_and_project_binding(self) -> None:
        dataset = self.registry.public_dataset(self.registry.get_active())
        self.assertEqual(dataset["totals"]["rows"], 3_738_096)
        self.assertEqual(dataset["project"]["projectId"], "sports-project-mlb-fd1-1b58d5d1def2")
        self.assertEqual(dataset["project"]["primaryTarget"], "Plate-Appearance Outcome")
        self.assertEqual(dataset["project"]["workflowId"], "mlb-forecasting")
        self.assertEqual(dataset["partitionAuthoritySha"], PARTITION_AUTHORITY_SHA)
        self.assertEqual(dataset["project"]["status"], "REGISTERED_MODELING_BLOCKED")
        self.assertTrue(dataset["modelingBlockers"])
        self.assertEqual(dataset["folds"][0]["trainingRows"], 184_104)
        self.assertEqual(dataset["folds"][1]["validationRows"], 182_926)

    def test_only_logical_uris_are_persisted_or_exposed(self) -> None:
        partitions = self.registry.list_partitions(REGISTRATION_ID)
        self.assertTrue(all(item["logical_uri"].startswith(LOGICAL_PACKAGE_ROOT) for item in partitions))
        payload = self.registry.public_dataset(self.registry.get_active())
        serialized = json_dumps(payload, {})
        self.assertNotIn("C:\\\\Users", serialized)
        self.assertNotIn(str(self.exchange_root), serialized)

    def test_family_season_aggregation_uses_registered_metadata(self) -> None:
        result = self.access.family_season_counts(REGISTRATION_ID, user_id="test-user")
        self.assertEqual(len(result["counts"]), 50)
        self.assertEqual(sum(item["rows"] for item in result["counts"]), 3_738_096)

    def test_schema_and_feature_eligibility_are_allowlisted(self) -> None:
        schema = self.access.schema_preview(REGISTRATION_ID, "plate_appearance", user_id="test-user")
        eligibility = self.access.feature_eligibility(REGISTRATION_ID, "plate_appearance", user_id="test-user")
        self.assertIn("outcome", {item["name"] for item in schema["fields"]})
        target = next(item for item in eligibility["fields"] if item["field"] == "outcome")
        self.assertEqual(target["identityClassification"], "TARGET")
        with self.assertRaises(SportsDataAccessError) as raised:
            self.access.preview(REGISTRATION_ID, "plate_appearance", user_id="test-user", fields=["not_registered"], limit=1)
        self.assertEqual(raised.exception.code, "FIELD_NOT_ALLOWLISTED")
        for seasons in ([2025, 2025], [2020], [2021, 2022, 2023, 2024, 2025, 2026]):
            with self.subTest(seasons=seasons), self.assertRaises(SportsDataAccessError) as season_error:
                self.access.preview(
                    REGISTRATION_ID,
                    "plate_appearance",
                    user_id="test-user",
                    seasons=seasons,
                    fields=["outcome"],
                    limit=1,
                )
            self.assertEqual(season_error.exception.code, "INVALID_SEASON_SCOPE")

    def test_bounded_preview_and_read_only_package(self) -> None:
        partition = self.registry.list_partitions(REGISTRATION_ID, family="plate_appearance", seasons=[2025])[0]
        relative = partition["logical_uri"][len(LOGICAL_PACKAGE_ROOT) + 1 :]
        physical = approved_package_root(self.exchange_root) / Path(*relative.split("/"))
        before = (physical.stat().st_size, physical.stat().st_mtime_ns)
        preview = self.access.preview(
            REGISTRATION_ID,
            "plate_appearance",
            user_id="test-user",
            seasons=[2025],
            fields=["game_id", "outcome"],
            limit=3,
        )
        after = (physical.stat().st_size, physical.stat().st_mtime_ns)
        self.assertEqual(len(preview["rows"]), 3)
        self.assertEqual(before, after)
        self.assertNotIn(str(self.exchange_root), str(preview))

    def test_preview_materializes_nulls_for_an_absent_physical_variant_field(self) -> None:
        schema = self.registry.get_schema(REGISTRATION_ID, "plate_appearance")
        field = next(item["name"] for item in schema["fields_json"] if item["nullable"])
        partition = {
            "partition_id": "synthetic-optional-field-variant",
            "family": "plate_appearance",
            "season": 2025,
            "row_count": 7,
            "physical_schema_json": [],
        }
        resolved = self.package_root / "synthetic-optional-field-variant.parquet"
        with (
            patch.object(self.registry, "list_partitions", return_value=[partition]),
            patch.object(self.access, "_resolve_partition", return_value=resolved) as resolve_partition,
            patch.object(self.access, "_verify_partition_authority") as verify_partition,
        ):
            preview = self.access.preview(
                REGISTRATION_ID,
                "plate_appearance",
                user_id="test-user",
                seasons=[partition["season"]],
                fields=[field],
                limit=3,
            )
        resolve_partition.assert_called_once_with(partition)
        verify_partition.assert_called_once_with(partition, resolved)
        self.assertEqual(len(preview["rows"]), 3)
        self.assertTrue(all(row[field] is None for row in preview["rows"]))
        self.assertGreaterEqual(preview["rowsScanned"], 3)

    def test_class_distribution_and_missingness_scan_exact_2025_rows(self) -> None:
        distribution = self.access.class_distribution(
            REGISTRATION_ID,
            "plate_appearance",
            "outcome",
            user_id="test-user",
            seasons=[2025],
        )
        missingness = self.access.missingness(
            REGISTRATION_ID,
            "plate_appearance",
            ["outcome"],
            user_id="test-user",
            seasons=[2025],
        )
        self.assertEqual(distribution["rowsScanned"], 182_926)
        self.assertEqual(sum(item["count"] for item in distribution["distribution"]), 182_926)
        self.assertEqual(len(distribution["distribution"]), 8)
        self.assertEqual([item["value"] for item in distribution["distribution"]], list(PA_CLASS_ORDER))
        self.assertEqual(missingness["fields"][0]["missing"], 0)

    def test_fold_scan_plan_contains_only_logical_registered_partitions(self) -> None:
        result = self.access.fold_scan_plan(REGISTRATION_ID, "train-through-2024-validate-2025", user_id="test-user")
        self.assertEqual(result["trainingRows"], 366_553)
        self.assertEqual(result["validationRows"], 182_926)
        self.assertTrue(all(item["logicalUri"].startswith(LOGICAL_PACKAGE_ROOT) for item in result["partitions"]))

    def test_query_cancellation_is_checked_before_read(self) -> None:
        cancellations = QueryCancellationRegistry()
        event = cancellations.begin("cancel-me", user_id="owner")
        with self.assertRaises(SportsDataAccessError) as forbidden:
            cancellations.cancel("cancel-me", user_id="different-user")
        self.assertEqual(forbidden.exception.code, "QUERY_CANCELLATION_FORBIDDEN")
        self.assertTrue(cancellations.cancel("cancel-me", user_id="owner"))
        partition = self.registry.list_partitions(REGISTRATION_ID, family="plate_appearance", seasons=[2025])[:1]
        with self.assertRaises(SportsDataAccessError) as raised:
            next(self.access._iter_batches(partition, fields=["outcome"], cancel_event=event, max_rows=1_000_000))
        self.assertEqual(raised.exception.code, "QUERY_CANCELLED")
        cancellations.finish("cancel-me")
        cancellations.begin("admin-cancel", user_id="owner")
        self.assertTrue(cancellations.cancel("admin-cancel", user_id="administrator", is_admin=True))
        cancellations.finish("admin-cancel")

    def test_shared_cache_lock_and_every_read_authority_checks(self) -> None:
        second_access = SportsDatasetAccessService(
            self.registry,
            exchange_root=self.exchange_root,
            validation_cache_path=self.cache_path,
        )
        self.assertIs(self.access._cache_lock, VALIDATION_CACHE_LOCK)
        self.assertIs(second_access._cache_lock, VALIDATION_CACHE_LOCK)

        partition = self.registry.list_partitions(
            REGISTRATION_ID, family="plate_appearance", seasons=[2025]
        )[0]
        path = self.access._resolve_partition(partition)
        with patch(
            "server.sports_datasets.access.parquet_physical_schema",
            return_value=(partition["physical_schema_json"], partition["row_count"] + 1),
        ):
            with self.assertRaises(SportsDataAccessError) as changed_footer:
                self.access._verify_partition_authority(partition, path)
        self.assertEqual(changed_footer.exception.code, "PARTITION_ROW_COUNT_MISMATCH")

        original_cache = self.cache_path.read_bytes()
        relative = partition["logical_uri"][len(LOGICAL_PACKAGE_ROOT) + 1 :]
        try:
            cache = json.loads(original_cache.decode("utf-8"))
            cache["entries"][relative]["mtimeNs"] = 0
            self.cache_path.write_bytes(canonical_json_bytes(cache))
            with patch("server.sports_datasets.access.sha256_file", wraps=sha256_file) as rehashed:
                self.access._verify_partition_authority(partition, path)
            rehashed.assert_called_once()

            rebound_cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            rebound_cache["rootIdentity"] = "0" * 64
            self.cache_path.write_bytes(canonical_json_bytes(rebound_cache))
            with self.assertRaises(SportsDataAccessError) as switched_root:
                self.access._verify_partition_authority(partition, path)
            self.assertEqual(switched_root.exception.code, "VALIDATION_CACHE_IDENTITY_MISMATCH")
        finally:
            self.cache_path.write_bytes(original_cache)

    def test_approved_root_checks_each_unresolved_component(self) -> None:
        exchange_root = Path("C:/configured-exchange")
        expected_root = raw_absolute_path(exchange_root)
        expected_components = []
        current = expected_root
        for component in PACKAGE_RELATIVE_ROOT.parts:
            current = current / component
            expected_components.append(current)
        with (
            patch("server.sports_datasets.access.reject_reparse_chain") as reject_chain,
            patch("server.sports_datasets.access.reject_reparse_boundary") as reject_boundary,
        ):
            result = approved_package_root(exchange_root)
        self.assertEqual(result, expected_components[-1])
        reject_chain.assert_called_once_with(expected_root, label="Configured exchange root chain")
        self.assertEqual(
            reject_boundary.call_args_list,
            [
                call(path, label=f"Configured exchange component {component}")
                for path, component in zip(expected_components, PACKAGE_RELATIVE_ROOT.parts, strict=True)
            ],
        )

    def test_row_and_memory_limits_fail_closed(self) -> None:
        with patch("server.sports_datasets.access.MAX_QUERY_ROWS", 10):
            with self.assertRaises(SportsDataAccessError) as raised:
                self.access.class_distribution(
                    REGISTRATION_ID,
                    "plate_appearance",
                    "outcome",
                    user_id="test-user",
                    seasons=[2025],
                )
            self.assertEqual(raised.exception.code, "QUERY_ROW_LIMIT_EXCEEDED")
        with patch("server.sports_datasets.access.MAX_QUERY_MEMORY_BYTES", 1):
            with self.assertRaises(SportsDataAccessError) as raised:
                self.access.preview(
                    REGISTRATION_ID,
                    "plate_appearance",
                    user_id="test-user",
                    seasons=[2025],
                    fields=["outcome"],
                    limit=1,
                )
            self.assertEqual(raised.exception.code, "QUERY_MEMORY_LIMIT_EXCEEDED")
        with patch("server.sports_datasets.access.MAX_AGGREGATE_CATEGORIES", 1):
            with self.assertRaises(SportsDataAccessError) as raised:
                self.access.class_distribution(
                    REGISTRATION_ID,
                    "plate_appearance",
                    "outcome",
                    user_id="test-user",
                    seasons=[2025],
                )
            self.assertEqual(raised.exception.code, "AGGREGATE_CARDINALITY_LIMIT_EXCEEDED")

    def test_missingness_counts_a_wholly_absent_physical_variant(self) -> None:
        schema = self.registry.get_schema(REGISTRATION_ID, "plate_appearance")
        field = next(item["name"] for item in schema["fields_json"] if item["nullable"])
        partition = {
            "partition_id": "synthetic-absent-field-partition",
            "family": "plate_appearance",
            "season": 2025,
            "row_count": 7,
            "physical_schema_json": [],
        }
        resolved = self.package_root / "synthetic-absent-field-partition.parquet"
        with (
            patch.object(self.registry, "list_partitions", return_value=[partition]),
            patch.object(self.access, "_resolve_partition", return_value=resolved) as resolve_partition,
            patch.object(self.access, "_verify_partition_authority") as verify_partition,
        ):
            result = self.access.missingness(
                REGISTRATION_ID,
                "plate_appearance",
                [field],
                user_id="test-user",
                seasons=[partition["season"]],
            )
        resolve_partition.assert_called_once_with(partition)
        verify_partition.assert_called_once_with(partition, resolved)
        self.assertEqual(result["rowsScanned"], partition["row_count"])
        self.assertEqual(result["fields"][0]["missing"], partition["row_count"])
        self.assertEqual(result["fields"][0]["missingRate"], 1.0)


if __name__ == "__main__":
    unittest.main()
