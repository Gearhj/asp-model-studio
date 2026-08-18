"""Regression: dataset totals must reference the validated package-file authority.

Engineering integrity audit (2026-08-18): server/sports_datasets/registry.py
previously hard-coded ``"packageFiles": 335`` inside ``_dataset_totals``. That
literal duplicated ``EXPECTED_TOTALS["package_files"]`` -- the exact count the
consumer validates the approved exchange package against before registration is
allowed to run. Two independent sources of truth for the same fact can silently
diverge if the approved package's file count ever changes, so the frontend-facing
``totals.packageFiles`` would then contradict the count the backend actually
validated. This test pins the total to the single validated authority.

It builds a minimal in-memory manifest and never touches the database, the
exchange package, or any model training.
"""

import unittest
from types import SimpleNamespace

from server.sports_datasets.constants import EXPECTED_TOTALS
from server.sports_datasets.registry import _dataset_totals


def _fake_validated_package() -> SimpleNamespace:
    """A minimal object exposing only the ``manifest`` fields _dataset_totals reads."""

    season = {
        "season": 2024,
        "games": 2_430,
        "plate_appearances": 182_449,
        "transitions": 700_000,
        "starter_targets": 4_860,
        "bullpen_appearances": 30_000,
    }
    manifest = {
        "seasons": [season],
        "data_families": [{"family_id": "player_prior", "row_count": 12_345}],
        "totals": {
            "parquet_files": EXPECTED_TOTALS["parquet_files"],
            "rows": EXPECTED_TOTALS["rows"],
            "parquet_bytes": EXPECTED_TOTALS["parquet_bytes"],
        },
        "partitions": [{"partition_id": f"p{i}"} for i in range(3)],
        "identity_coverage": {
            "primary_2023_2025": {"exact_reference_rate": 0.99, "unresolved_references": 1}
        },
    }
    return SimpleNamespace(manifest=manifest)


class DatasetTotalsAuthorityTest(unittest.TestCase):
    def test_package_files_references_validated_authority(self) -> None:
        totals = _dataset_totals(_fake_validated_package())
        self.assertEqual(
            totals["packageFiles"],
            EXPECTED_TOTALS["package_files"],
            "totals.packageFiles must equal the consumer-validated package-file count, "
            "not an independent literal that can drift from the validation gate.",
        )

    def test_other_totals_still_derive_from_manifest(self) -> None:
        totals = _dataset_totals(_fake_validated_package())
        # Guardrail: the fix only changed packageFiles; manifest-derived fields
        # must keep flowing from the manifest, not from EXPECTED_TOTALS.
        self.assertEqual(totals["parquetFiles"], EXPECTED_TOTALS["parquet_files"])
        self.assertEqual(totals["playerPriors"], 12_345)
        self.assertEqual(totals["games"], 2_430)
        self.assertEqual(totals["partitions"], 3)


if __name__ == "__main__":
    unittest.main()
