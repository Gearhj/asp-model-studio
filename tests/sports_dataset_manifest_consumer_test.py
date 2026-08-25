from __future__ import annotations

import copy
import json
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from server.sports_datasets.access import approved_package_root
from server.sports_datasets.constants import (
    MANIFEST_SHA,
    PARTITION_AUTHORITY_SHA,
    PA_CLASS_ORDER,
)
from server.sports_datasets.consumer import (
    ManifestValidationError,
    SportsDatasetManifestConsumer,
    canonical_json_bytes,
    load_strict_json,
    partition_authority_sha,
    reject_reparse_chain,
    semantic_manifest_sha,
    validate_package_relative_uri,
)
from tests.sports_dataset_test_fixture import golden_corpus_available, golden_package


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPOSITORY_ROOT / ".tmp"


def _scratch(name: str) -> Path:
    path = SCRATCH_ROOT / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class StrictJsonAndPathTests(unittest.TestCase):
    def test_duplicate_keys_are_rejected(self) -> None:
        root = _scratch("sports-duplicate-json")
        path = root / "duplicate.json"
        path.write_text('{"a":1,"a":2}', encoding="utf-8")
        with self.assertRaisesRegex(ManifestValidationError, "Duplicate JSON key"):
            load_strict_json(path, logical_uri="duplicate.json")

    def test_invalid_utf8_is_rejected(self) -> None:
        root = _scratch("sports-invalid-utf8")
        path = root / "invalid.json"
        path.write_bytes(b'{"a":"\xff"}')
        with self.assertRaises(ManifestValidationError) as raised:
            load_strict_json(path, logical_uri="invalid.json")
        self.assertEqual(raised.exception.code, "INVALID_UTF8")

    def test_nan_and_infinity_are_rejected(self) -> None:
        for token in ("NaN", "Infinity", "-Infinity"):
            root = _scratch("sports-non-finite")
            path = root / "invalid.json"
            path.write_text(f'{{"a":{token}}}', encoding="utf-8")
            with self.assertRaises(ManifestValidationError) as raised:
                load_strict_json(path, logical_uri="invalid.json")
            self.assertEqual(raised.exception.code, "NON_FINITE_JSON_NUMBER")

    def test_absolute_unc_file_and_traversal_paths_are_rejected(self) -> None:
        unsafe = (
            "C:/exchange/part.parquet",
            "C:\\exchange\\part.parquet",
            "//server/share/part.parquet",
            "file:///exchange/part.parquet",
            "parquet/../part.parquet",
            "/parquet/part.parquet",
        )
        for value in unsafe:
            with self.subTest(value=value), self.assertRaises(ManifestValidationError):
                validate_package_relative_uri(value)
        self.assertEqual(validate_package_relative_uri("parquet/plate_appearance/season=2025/part.parquet"), "parquet/plate_appearance/season=2025/part.parquet")

    def test_reparse_chain_rejects_an_intermediate_boundary(self) -> None:
        root = _scratch("sports-reparse-chain")
        intermediate = root / "datasets"
        leaf = intermediate / "mlb-fd1"
        leaf.mkdir(parents=True)
        with patch(
            "server.sports_datasets.consumer._is_reparse_point",
            side_effect=lambda path: path == intermediate,
        ):
            with self.assertRaises(ManifestValidationError) as raised:
                reject_reparse_chain(leaf, label="Configured exchange root chain")
        self.assertEqual(raised.exception.code, "REPARSE_BOUNDARY_REJECTED")

    def test_validation_cache_rejects_a_descendant_reparse_before_writing(self) -> None:
        root = _scratch("sports-cache-reparse-chain")
        package_root = root / "package"
        package_root.mkdir()
        cache_parent = root / "runtime" / "dataset-validation"
        cache_parent.mkdir(parents=True)
        cache_path = cache_parent / "validation-cache.json"
        with patch(
            "server.sports_datasets.consumer._is_reparse_point",
            side_effect=lambda path: path == cache_parent,
        ):
            with self.assertRaises(ManifestValidationError) as raised:
                SportsDatasetManifestConsumer(package_root, cache_path=cache_path)
        self.assertEqual(raised.exception.code, "REPARSE_BOUNDARY_REJECTED")
        self.assertFalse(cache_path.exists())


@unittest.skipUnless(golden_corpus_available(), "ASP_MODEL_EXCHANGE_ROOT is required for golden exchange tests")
class GoldenManifestConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.exchange_root = Path(os.environ["ASP_MODEL_EXCHANGE_ROOT"])
        cls.validated, cls.package_root, cls.cache_path = golden_package()
        cls.consumer = SportsDatasetManifestConsumer(cls.package_root, cache_path=cls.cache_path)

    def test_exact_golden_package_validates(self) -> None:
        self.assertEqual(self.validated.manifest["manifest_sha256"], MANIFEST_SHA)
        self.assertEqual(self.validated.partition_authority_sha, PARTITION_AUTHORITY_SHA)
        self.assertEqual(len(self.validated.partitions), 329)
        self.assertEqual(sum(item["row_count"] for item in self.validated.partitions), 3_738_096)
        self.assertEqual(self.validated.cache_hits, 0)
        self.assertEqual(self.validated.cache_misses, 329)
        cache = load_strict_json(self.cache_path, logical_uri="target-local://test-validation-cache")
        self.assertEqual(cache["rootIdentity"], self.validated.root_identity)
        self.assertEqual(len(cache["entries"]), 329)
        self.assertTrue(
            all(
                item.get("rootIdentity") == self.validated.root_identity
                and isinstance(item.get("fileIdentity"), str)
                and len(item["fileIdentity"]) == 64
                for item in cache["entries"].values()
            )
        )

    def test_semantic_digest_and_partition_authority_are_independent(self) -> None:
        self.assertEqual(semantic_manifest_sha(self.validated.manifest), MANIFEST_SHA)
        self.assertEqual(partition_authority_sha(self.validated.partitions), PARTITION_AUTHORITY_SHA)
        reversed_partitions = list(reversed(self.validated.partitions))
        self.assertEqual(partition_authority_sha(reversed_partitions), PARTITION_AUTHORITY_SHA)

    def test_second_validation_reuses_only_fully_bound_cache_entries(self) -> None:
        repeated = SportsDatasetManifestConsumer(self.package_root, cache_path=self.cache_path).validate()
        self.assertEqual(repeated.cache_hits, 329)
        self.assertEqual(repeated.cache_misses, 0)

    def test_superseded_package_identity_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.validated.manifest)
        manifest["manifest_sha256"] = "6c6cde" + "0" * 58
        manifest["package_id"] = "sha256-6c6cde" + "0" * 58
        with self.assertRaises(ManifestValidationError) as raised:
            self.consumer.validate_manifest_contract(manifest)
        self.assertEqual(raised.exception.code, "SUPERSEDED_PACKAGE")

    def test_class_order_mismatch_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.validated.manifest)
        target = next(item for item in manifest["target_definitions"] if item["target_id"] == "plate_appearance_outcome")
        target["ordered_classes"] = sorted(PA_CLASS_ORDER)
        with self.assertRaises(ManifestValidationError):
            self.consumer.validate_manifest_contract(manifest)

    def test_rights_mismatch_is_rejected(self) -> None:
        rights = copy.deepcopy(self.validated.source_rights)
        rights["package_controls"]["raw_redistribution_authorized"] = True
        with self.assertRaises(ManifestValidationError) as raised:
            self.consumer.validate_source_rights(rights, self.validated.manifest)
        self.assertEqual(raised.exception.code, "RIGHTS_CONTROL_MISMATCH")

    def test_limitation_mismatch_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.validated.manifest)
        manifest["known_limitations"].pop()
        with self.assertRaises(ManifestValidationError):
            self.consumer.validate_manifest_contract(manifest)

    def test_schema_registry_change_is_rejected(self) -> None:
        registry = copy.deepcopy(self.validated.schema_registry)
        registry["families"][0]["physical_variants"][0]["fields"][0]["name"] = "changed_source_key"
        with self.assertRaises(ManifestValidationError) as raised:
            self.consumer.validate_schema_registry(registry, self.validated.manifest)
        self.assertEqual(raised.exception.code, "SCHEMA_VARIANT_FINGERPRINT_MISMATCH")

    def test_missing_file_inventory_is_rejected(self) -> None:
        root = _scratch("sports-missing-inventory")
        consumer = SportsDatasetManifestConsumer(root, cache_path=root.parent / f"cache-{uuid.uuid4().hex}.json")
        with self.assertRaises(ManifestValidationError) as raised:
            consumer._inventory({"parquet/missing.parquet"})
        self.assertEqual(raised.exception.code, "FILE_INVENTORY_MISMATCH")

    def test_changed_partition_hash_schema_and_row_count_are_rejected(self) -> None:
        partition = self.validated.partitions[0]
        path = self.package_root / Path(*partition["package_relative_uri"].split("/"))
        mutations = (
            ("file_sha256", "0" * 64, "PARTITION_HASH_MISMATCH"),
            ("physical_schema", [{"name": "changed", "dtype": "String"}], "PARTITION_SCHEMA_MISMATCH"),
            ("row_count", partition["row_count"] + 1, "PARTITION_ROW_COUNT_MISMATCH"),
        )
        for field, value, expected_code in mutations:
            changed = copy.deepcopy(partition)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ManifestValidationError) as raised:
                self.consumer._validate_partition(changed, path, {"entries": {}})
            self.assertEqual(raised.exception.code, expected_code)

    def test_manifest_does_not_coerce_scalar_types(self) -> None:
        manifest = copy.deepcopy(self.validated.manifest)
        manifest["totals"]["rows"] = str(manifest["totals"]["rows"])
        with self.assertRaises(ManifestValidationError):
            self.consumer.validate_manifest_contract(manifest)
        for value in (True, 1786857668, "2026-08-16", "arbitrary"):
            changed = copy.deepcopy(self.validated.manifest)
            changed["published_at"] = value
            with self.subTest(published_at=value), self.assertRaises(ManifestValidationError) as raised:
                self.consumer.validate_manifest_contract(changed)
            self.assertEqual(raised.exception.code, "PUBLICATION_TIME_MISMATCH")


if __name__ == "__main__":
    unittest.main()
