from __future__ import annotations

import copy
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from server.persistence.db import Database
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes, sha256_file
from server.sports_datasets.current_statcast import (
    CURRENT_STATCAST_DATASET_ID,
    CURRENT_STATCAST_MANIFEST_VERSION,
    CurrentStatcastDatasetRegistry,
    build_current_statcast_warehouse_manifest,
    current_statcast_partition_authority_sha,
    current_statcast_partition_descriptor,
    parquet_physical_schema,
    validate_current_statcast_manifest,
    write_content_addressed_current_statcast_manifest,
)
from server.sports_datasets.registry import SportsDatasetRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPOSITORY_ROOT / ".tmp"


class CurrentStatcastDatasetRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / f"current-statcast-registry-{uuid.uuid4().hex}"
        self.package_root = self.scratch / "package"
        children = self.package_root / "children"
        children.mkdir(parents=True, exist_ok=False)
        self.parquet_path = children / "pa-2026-08-27.parquet"
        pq.write_table(
            pa.table(
                {
                    "gameDate": ["2026-08-27", "2026-08-27"],
                    "gamePk": [822694, 822694],
                    "atBatNumber": [1, 2],
                    "paOutcome": ["BIP_OUT", "SINGLE"],
                }
            ),
            self.parquet_path,
        )
        physical_schema = parquet_physical_schema(self.parquet_path)
        partition = {
            "byteCount": self.parquet_path.stat().st_size,
            "family": "plate_appearance",
            "fileSha256": sha256_file(self.parquet_path, logical_uri="children/pa-2026-08-27.parquet"),
            "maximumDate": "2026-08-27",
            "minimumDate": "2026-08-27",
            "month": 8,
            "partitionId": "current-statcast-pa-2026-08-27",
            "physicalSchema": physical_schema,
            "physicalSchemaFingerprint": sha256_bytes(canonical_json_bytes(physical_schema)),
            "relativePath": "children/pa-2026-08-27.parquet",
            "rowCount": 2,
            "schemaId": "CURRENT_STATCAST_PA_SCHEMA_V1",
            "season": 2026,
            "sourceLineage": [{"sha256": "1" * 64, "sourceId": "statcast:regular:2026-08-27"}],
            "sourceRightsIds": ["MLB_STATCAST"],
            "targetEligibility": ["EVIDENCE_ONLY"],
            "temporalClassification": ["CURRENT_SEASON_POINT_IN_TIME"],
        }
        partition_authority_sha = current_statcast_partition_authority_sha([partition])
        payload = {
            "canonicalizationVersion": "SPORTS_CANONICAL_JSON_V1",
            "datasetId": CURRENT_STATCAST_DATASET_ID,
            "datasetVersionId": f"{CURRENT_STATCAST_DATASET_ID}:partition-authority-sha256:{partition_authority_sha}",
            "dateCoverage": {
                "earliestDate": "2026-08-27",
                "latestDate": "2026-08-27",
                "partitionCount": 1,
                "rowCount": 2,
            },
            "family": "plate_appearance",
            "league": "MLB",
            "limitations": [
                {
                    "description": "Current evidence is quarantined and is not a fitted model.",
                    "limitationId": "CURRENT_STATCAST_EVIDENCE_ONLY",
                    "scope": "MODELING",
                }
            ],
            "manifestId": f"current-statcast-pa-dataset-manifest:partition-authority-sha256:{partition_authority_sha}",
            "metadata": {
                "bronzeManifestSha256": "2" * 64,
                "modelFitOccurred": False,
                "modelPromotionOccurred": False,
                "normalizationContract": "CURRENT_STATCAST_PA_NORMALIZATION_V1",
                "publicationManifestSha256": "3" * 64,
                "quarantineStatus": "QUARANTINED",
                "targetClassOrder": [
                    "STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE",
                    "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH",
                ],
                "targetEventMap": {
                    "catcher_interf": "WALK_HBP_CI",
                    "double": "DOUBLE",
                    "field_error": "OTHER_REACH",
                    "field_out": "BIP_OUT",
                    "home_run": "HOME_RUN",
                    "single": "SINGLE",
                    "strikeout": "STRIKEOUT",
                    "triple": "TRIPLE",
                },
                "temporalContract": {
                    "featureCutoffRule": "source.gameDate < target.gameDate; same-date history excluded",
                    "intendedCombinedDevelopmentSelection": ["2023-03-30", "2026-08-13"],
                    "intendedCombinedEligibleEvidence": ["2023-03-30", "2026-08-27"],
                    "intendedCombinedFinalOot": ["2026-08-14", "2026-08-27"],
                },
                "trainingApproval": "NOT_APPROVED",
            },
            "partitions": [partition],
            "publishedAt": "2026-08-28T12:00:00+00:00",
            "rights": [
                {
                    "allowedUses": ["LOCAL_PRIVATE_RESEARCH"],
                    "attribution": "MLB Statcast current-season evidence.",
                    "controls": {"redistribution": "PROHIBITED"},
                    "displayName": "MLB Statcast",
                    "metadata": {"evidenceType": "CURRENT_SEASON"},
                    "prohibitedUses": ["RAW_REDISTRIBUTION"],
                    "rightsControlId": "MLB_STATCAST",
                    "sourceName": "MLB Statcast",
                    "status": "GOVERNED_LOCAL_RESEARCH_ONLY",
                }
            ],
            "schemaVersion": CURRENT_STATCAST_MANIFEST_VERSION,
            "sport": "Baseball",
        }
        self.payload = payload
        self.manifest_path = write_content_addressed_current_statcast_manifest(self.scratch, payload)
        self.database = Database(self.scratch / "registry.db")
        self.database.initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self.scratch)

    def _validated(self):
        return validate_current_statcast_manifest(self.manifest_path, package_root=self.package_root)

    def test_registers_only_current_plate_appearance_evidence_idempotently(self) -> None:
        registry = CurrentStatcastDatasetRegistry(self.database)
        first = registry.register(self._validated(), user_id="test-admin")
        second = registry.register(self._validated(), user_id="different-admin")
        self.assertEqual(first["registration_id"], second["registration_id"])
        self.assertEqual(first["registration_disposition"], "CREATED")
        self.assertEqual(second["registration_disposition"], "REUSED")
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_dataset_registrations").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_dataset_partitions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_dataset_temporal_folds").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_dataset_populations").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_research_projects").fetchone()[0], 0)
            family = connection.execute("SELECT family FROM sports_dataset_partitions").fetchone()[0]
        self.assertEqual(family, "plate_appearance")

    def test_complete_empty_current_dates_advance_immutable_registration_without_rows(self) -> None:
        registry = CurrentStatcastDatasetRegistry(self.database)
        prior = registry.register(self._validated(), user_id="test-admin")
        empty_path = self.package_root / "children" / "pa-2026-08-28-empty.parquet"
        pq.write_table(pq.read_table(self.parquet_path).slice(0, 0), empty_path)
        empty_sha = sha256_file(
            empty_path, logical_uri="children/pa-2026-08-28-empty.parquet"
        )
        empty_schema = parquet_physical_schema(empty_path)
        empty_partition = {
            "byteCount": empty_path.stat().st_size,
            "family": "plate_appearance",
            "fileSha256": empty_sha,
            "maximumDate": "2026-08-28",
            "minimumDate": "2026-08-28",
            "month": 8,
            "partitionId": f"current-statcast-pa:2026-08-28:sha256:{empty_sha}",
            "physicalSchema": empty_schema,
            "physicalSchemaFingerprint": sha256_bytes(canonical_json_bytes(empty_schema)),
            "relativePath": "children/pa-2026-08-28-empty.parquet",
            "rowCount": 0,
            "schemaId": "CURRENT_STATCAST_PA_SCHEMA_V1",
            "season": 2026,
            "sourceLineage": [
                {"sha256": "7" * 64, "sourceId": "statcast/regular/year=2026/2026-08-28"},
                {"sha256": "8" * 64, "sourceId": "current-statcast-bronze-manifest"},
                {"sha256": "9" * 64, "sourceId": "mlb-stats-api-schedule-final-authority"},
                {"sha256": "a" * 64, "sourceId": "governed-player-identity-registration"},
            ],
            "sourceRightsIds": ["MLB_STATCAST"],
            "targetEligibility": ["EVIDENCE_ONLY"],
            "temporalClassification": [
                "POINT_IN_TIME_DATE_EXCLUSIVE",
                "CURRENT_SEASON",
                "COMPLETE_EMPTY_DATE",
            ],
        }
        second_empty_partition = copy.deepcopy(empty_partition)
        second_empty_partition.update(
            {
                "maximumDate": "2026-08-29",
                "minimumDate": "2026-08-29",
                "partitionId": f"current-statcast-pa:2026-08-29:sha256:{empty_sha}",
            }
        )
        second_empty_partition["sourceLineage"][0]["sourceId"] = (
            "statcast/regular/year=2026/2026-08-29"
        )
        payload = copy.deepcopy(self.payload)
        payload["partitions"].extend([empty_partition, second_empty_partition])
        payload["dateCoverage"] = {
            "earliestDate": "2026-08-27",
            "latestDate": "2026-08-29",
            "partitionCount": 3,
            "rowCount": 2,
        }
        authority = current_statcast_partition_authority_sha(payload["partitions"])
        payload["datasetVersionId"] = (
            f"{CURRENT_STATCAST_DATASET_ID}:partition-authority-sha256:{authority}"
        )
        payload["manifestId"] = (
            "current-statcast-pa-dataset-manifest:"
            f"partition-authority-sha256:{authority}"
        )
        payload["metadata"]["temporalContract"]["intendedCombinedEligibleEvidence"] = [
            "2023-03-30",
            "2026-08-29",
        ]
        next_path = write_content_addressed_current_statcast_manifest(self.scratch, payload)
        current = registry.register(
            validate_current_statcast_manifest(next_path, package_root=self.package_root),
            user_id="test-admin",
        )

        self.assertNotEqual(current["registration_id"], prior["registration_id"])
        self.assertEqual(current["evidence_cutoff"], "2026-08-29")
        self.assertEqual(current["totals_json"]["rows"], 2)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT registration_id, row_count FROM sports_dataset_partitions "
                "WHERE registration_id = ? ORDER BY row_count",
                (current["registration_id"],),
            ).fetchall()
        self.assertEqual([int(row["row_count"]) for row in rows], [0, 0, 2])
        self.assertIsNotNone(SportsDatasetRegistry(self.database).get(prior["registration_id"]))

    def test_public_projection_is_exact_and_does_not_leak_fd1_bridge(self) -> None:
        registration = CurrentStatcastDatasetRegistry(self.database).register(
            self._validated(), user_id="test-admin"
        )
        self.assertIsNone(SportsDatasetRegistry(self.database).get_active())
        with patch(
            "server.sports_identity_bridges.registry.SportsIdentityBridgeRegistry.public_active",
            side_effect=AssertionError("current projection must not inspect an unrelated identity bridge"),
        ), patch(
            "server.sports_modeling.registry.SportsPAResearchRegistry.public_active",
            side_effect=AssertionError("current projection must not inspect an unrelated PA model"),
        ), patch(
            "server.sports_phase4.registry.SportsPhase4Registry.public_active",
            side_effect=AssertionError("current projection must not inspect an unrelated Phase 4 study"),
        ):
            public = SportsDatasetRegistry(self.database).public_dataset(registration)
        self.assertEqual(public["datasetId"], CURRENT_STATCAST_DATASET_ID)
        self.assertEqual(
            public["dateCoverage"],
            {"earliestDate": "2026-08-27", "latestDate": "2026-08-27", "partitionCount": 1, "rowCount": 2},
        )
        self.assertEqual(public["modelingStatus"], "EVIDENCE_REGISTERED_NO_FIT")
        self.assertIs(public["modelFitOccurred"], False)
        self.assertNotIn("identityBridge", public)
        self.assertNotIn("project", public)
        self.assertEqual(public["folds"], [])
        self.assertEqual(public["limitationDetails"][0]["source"], "CURRENT_STATCAST_MANIFEST")

    def test_catalog_lists_current_evidence_and_manual_activation_is_explicit(self) -> None:
        current_registry = CurrentStatcastDatasetRegistry(self.database)
        registration = current_registry.register(self._validated(), user_id="test-admin")
        registry = SportsDatasetRegistry(self.database)

        catalog = registry.list_valid()
        self.assertEqual([item["registration_id"] for item in catalog], [registration["registration_id"]])
        self.assertIsNone(registry.get_active())

        selected = registry.activate(registration["registration_id"])
        self.assertEqual(selected["registration_id"], registration["registration_id"])
        self.assertEqual(registry.get_active()["registration_id"], registration["registration_id"])

        # Revalidation repairs metadata but must not undo an explicit operator
        # selection of this same immutable registration.
        current_registry.register(self._validated(), user_id="test-admin")
        self.assertEqual(registry.get_active()["registration_id"], registration["registration_id"])
        self.assertIsNone(registry.activate("missing-registration"))

    def test_inactive_catalog_projection_does_not_load_active_child_authorities(self) -> None:
        registration = CurrentStatcastDatasetRegistry(self.database).register(
            self._validated(), user_id="test-admin"
        )
        # This row is deliberately shaped as a non-current inactive catalog
        # entry; optional child studies can only belong to the active parent.
        inactive = {**registration, "active": 0, "metadata_json": {}}
        with patch(
            "server.sports_identity_bridges.registry.SportsIdentityBridgeRegistry.public_active",
            side_effect=AssertionError("inactive catalog rows must not load active child evidence"),
        ), patch(
            "server.sports_modeling.registry.SportsPAResearchRegistry.public_active",
            side_effect=AssertionError("inactive catalog rows must not load active child evidence"),
        ), patch(
            "server.sports_phase4.registry.SportsPhase4Registry.public_active",
            side_effect=AssertionError("inactive catalog rows must not load active child evidence"),
        ):
            public = SportsDatasetRegistry(self.database).public_dataset(inactive)
        self.assertIs(public["active"], False)
        self.assertNotIn("phase4", public)

    def test_manifest_hash_and_partition_bytes_are_revalidated(self) -> None:
        self._validated()
        with self.parquet_path.open("ab") as handle:
            handle.write(b"tampered")
        with self.assertRaisesRegex(Exception, "byte count differs"):
            self._validated()

    def test_adapter_builds_complete_byte_addressed_manifest_from_nonempty_receipt(self) -> None:
        publication = {
            "approvedForTraining": False,
            "datasetId": CURRENT_STATCAST_DATASET_ID,
            "manifestContract": "MLB_CURRENT_STATCAST_SILVER_V1",
            "manifestVersion": 1,
            "modelEligible": False,
            "modelsFitted": 0,
            "normalizerContract": "CURRENT_STATCAST_PA_NORMALIZATION_V1",
            "targetClassOrder": [
                "STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE",
                "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH",
            ],
            "targetEventMap": {
                "catcher_interf": "WALK_HBP_CI",
                "double": "DOUBLE",
                "field_error": "OTHER_REACH",
                "field_out": "BIP_OUT",
                "home_run": "HOME_RUN",
                "single": "SINGLE",
                "strikeout": "STRIKEOUT",
                "triple": "TRIPLE",
            },
            "partitions": [
                {
                    "objects": {
                        "plate_appearance": {
                            "byteCount": self.parquet_path.stat().st_size,
                            "relativePath": "children/pa-2026-08-27.parquet",
                            "rowCount": 2,
                            "sha256": sha256_file(self.parquet_path, logical_uri="children/pa-2026-08-27.parquet"),
                        }
                    },
                    "partitionDate": "2026-08-27",
                    "request": {
                        "identityRegistrationSha256": "4" * 64,
                        "scheduleManifestSha256": "5" * 64,
                        "sourceManifestSha256": "2" * 64,
                        "sourcePartitionId": "statcast:regular:2026-08-27",
                        "sourcePartitionSha256": "1" * 64,
                    },
                    "season": 2026,
                }
            ],
            "quarantine": "QUARANTINED",
            "rights": {
                "allowedUses": ["LOCAL_PRIVATE_MODEL_DEVELOPMENT", "READ_ONLY_REGISTRATION"],
                "classification": ["PUBLIC RESEARCH SOURCE", "ATTRIBUTION REQUIRED"],
                "prohibitedUses": ["PUBLIC_RAW_REDISTRIBUTION"],
                "source": "MLB Advanced Media / Baseball Savant",
            },
            "selectable": False,
            "sourceAuthorities": {"currentBronzeManifestSha256": "2" * 64},
            "status": "COMPLETE",
            "temporalContract": {
                "featureCutoffRule": "source.gameDate < target.gameDate; same-date history excluded",
                "intendedCombinedDevelopmentSelection": ["2023-03-30", "2026-08-13"],
                "intendedCombinedEligibleEvidence": ["2023-03-30", "2026-08-27"],
                "intendedCombinedFinalOot": ["2026-08-14", "2026-08-27"],
            },
        }
        body = canonical_json_bytes(publication)
        publication_sha = sha256_bytes(body)
        publication_path = self.package_root / "publications" / "sha256" / publication_sha / "manifest.json"
        publication_path.parent.mkdir(parents=True)
        publication_path.write_bytes(body)

        historical_path = self.package_root / "children" / "pa-2023.parquet"
        pq.write_table(
            pa.table(
                {
                    "gameDate": ["2023-03-30", "2023-10-01"],
                    "gamePk": [700001, 700999],
                    "atBatNumber": [1, 1],
                    "paOutcome": ["BIP_OUT", "HOME_RUN"],
                }
            ),
            historical_path,
        )
        historical = current_statcast_partition_descriptor(
            package_root=self.package_root,
            relative_path="children/pa-2023.parquet",
            partition_id="legacy-current-statcast-pa:2023",
            source_lineage=[
                {"sha256": "6" * 64, "sourceId": "legacy-statcast-pa:2023"},
            ],
            temporal_classification=("POINT_IN_TIME_DATE_EXCLUSIVE", "HISTORICAL_REUSED"),
        )
        self.assertIsNone(historical["month"])

        first = build_current_statcast_warehouse_manifest(
            self.package_root,
            publication_path,
            extra_partitions=[historical],
        )
        second = build_current_statcast_warehouse_manifest(
            self.package_root,
            publication_path,
            extra_partitions=[historical],
        )
        self.assertEqual(first.manifest_path, second.manifest_path)
        self.assertEqual(first.manifest["manifestSha256"], second.manifest["manifestSha256"])
        stored = first.manifest_path.read_bytes()
        self.assertEqual(first.manifest_path.stem, sha256_bytes(stored))
        self.assertNotIn("manifestSha256", first.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(first.manifest["dateCoverage"]["rowCount"], 4)
        self.assertEqual(first.manifest["dateCoverage"]["partitionCount"], 2)
        self.assertEqual(first.manifest["dateCoverage"]["earliestDate"], "2023-03-30")
        self.assertEqual(first.manifest["dateCoverage"]["latestDate"], "2026-08-27")
        self.assertEqual(first.manifest["datasetVersionId"], f"{CURRENT_STATCAST_DATASET_ID}:partition-authority-sha256:{first.partition_authority_sha}")


if __name__ == "__main__":
    unittest.main()
