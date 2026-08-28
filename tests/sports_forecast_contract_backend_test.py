from __future__ import annotations

import shutil
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.persistence.db import Database, json_dumps
from server.persistence.service import PersistenceService
from server.persistence.sports_forecast_contract import (
    CHRONOLOGICAL_VALIDATION_REQUIREMENT,
    CUSTOM_DATES,
    FORECAST_CONTRACT_METADATA_KEY,
    SEASON_ROLES,
    SportsForecastContractError,
    SportsForecastContractStore,
)


TEST_USER = {
    "userId": "forecast-contract-scientist",
    "displayName": "Forecast Contract Scientist",
    "email": "forecast-contract@example.invalid",
    "role": "data_scientist",
    "status": "active",
}


class SportsForecastContractBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        # TemporaryDirectory creates an owner-only Windows ACL that can deny
        # SQLite access under the restricted test token.  An ordinary child of
        # the repository's ignored .tmp authority inherits a usable ACL.
        self.test_root = (
            Path(__file__).resolve().parents[1]
            / ".tmp"
            / f"forecast-contract-{uuid.uuid4().hex}"
        )
        self.test_root.mkdir(parents=True, exist_ok=False)
        self.database = Database(self.test_root / "forecast-contract.db")
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        self.persistence.sync_user(TEST_USER)
        self.persistence.projects.upsert(
            {
                "project_id": "mlb-project",
                "project_name": "MLB Custom Temporal Project",
                "project_type": "custom-workflow",
                "workflow_type": "mlb-forecasting",
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {"ordinarySetting": "preserve-me"},
            }
        )
        self._seed_registered_pa_coverage()
        self.contracts = SportsForecastContractStore(self.database)
        self.contracts.link_evidence_dataset(
            "mlb-project",
            "registration-1",
            user_id=TEST_USER["userId"],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.test_root, ignore_errors=True)

    def _seed_registered_pa_coverage(self) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sports_dataset_registrations (
                  registration_id, dataset_id, dataset_version_id, manifest_id,
                  manifest_sha, package_id, sport, league, evidence_cutoff,
                  published_at, logical_package_root, validation_status,
                  registered_at, last_validated_at, registered_by, rights_status,
                  limitation_count, active, totals_json, seasons_json,
                  evidence_coverage_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VALID', ?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                """,
                (
                    "registration-1",
                    "asp.mlb.open-data.fd1",
                    "dataset-version-1",
                    "manifest-1",
                    "a" * 64,
                    "package-1",
                    "Baseball",
                    "MLB",
                    # This administrative cutoff is intentionally later than
                    # the actual PA coverage and must not authorize 2026.
                    "2026-08-15",
                    "2026-08-16T00:00:00Z",
                    "asp-model-exchange://datasets/mlb-fd1/package-1",
                    "2026-08-16T00:00:00Z",
                    "2026-08-16T00:00:00Z",
                    TEST_USER["userId"],
                    "APPROVED_LOCAL_PRIVATE_USE",
                    json_dumps({}, {}),
                    json_dumps([2021, 2022, 2023, 2024, 2025], []),
                    json_dumps({}, {}),
                    json_dumps({}, {}),
                ),
            )
            for values in (
                (
                    "pa-2021",
                    "plate_appearance",
                    2021,
                    4,
                    "asp-model-exchange://pa/2021-04.parquet",
                    100,
                    "2021-04-01",
                    "2021-10-03",
                ),
                (
                    "pa-2025",
                    "plate_appearance",
                    2025,
                    9,
                    "asp-model-exchange://pa/2025-09.parquet",
                    200,
                    "2025-03-18",
                    "2025-09-28",
                ),
                # Annual prior summaries use Dec 31. They must not extend PA
                # evidence coverage beyond the final registered game date.
                (
                    "prior-2025",
                    "player_prior",
                    2025,
                    None,
                    "asp-model-exchange://prior/2025.parquet",
                    20,
                    "2025-12-31",
                    "2025-12-31",
                ),
            ):
                partition_id, family, season, month, logical_uri, rows, minimum, maximum = values
                connection.execute(
                    """
                    INSERT INTO sports_dataset_partitions (
                      partition_id, registration_id, family, season, month,
                      logical_uri, row_count, byte_count, minimum_date,
                      maximum_date, schema_id, physical_schema_fingerprint,
                      file_sha, source_key, source_version_id,
                      original_source_logical_identity, checkpoint_lineage_id,
                      governance_checksum, target_eligibility_json,
                      temporal_classification_json, rights_ids_json,
                      physical_schema_json
                    ) VALUES (?, 'registration-1', ?, ?, ?, ?, ?, 1, ?, ?,
                              'schema-1', ?, ?, 'source', 'source-v1', NULL,
                              NULL, NULL, '[]', '[]', '[]', '[]')
                    """,
                    (
                        partition_id,
                        family,
                        season,
                        month,
                        logical_uri,
                        rows,
                        minimum,
                        maximum,
                        "b" * 64,
                        "c" * 64,
                    ),
                )

    def _seed_current_statcast_coverage(self) -> None:
        version_id = (
            "asp.mlb.statcast.current-pa.v1:partition-authority-sha256:"
            "6e134d8726587ad88d0807effb6e6b12ad39f39b99acb7f523ae6ae98155df34"
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sports_dataset_registrations (
                  registration_id, dataset_id, dataset_version_id, manifest_id,
                  manifest_sha, package_id, sport, league, evidence_cutoff,
                  published_at, logical_package_root, validation_status,
                  registered_at, last_validated_at, registered_by, rights_status,
                  limitation_count, active, totals_json, seasons_json,
                  evidence_coverage_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'Baseball', 'MLB', ?, ?, ?,
                          'VALID', ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)
                """,
                (
                    "sports-dataset-current-statcast-03ca6dab30e760b2",
                    "asp.mlb.statcast.current-pa.v1",
                    version_id,
                    "current-statcast-manifest",
                    "d" * 64,
                    "current-statcast-package",
                    "2026-08-27",
                    "2026-08-28T00:00:00Z",
                    "asp-model-exchange://datasets/mlb-current-statcast/package",
                    "2026-08-28T00:00:00Z",
                    "2026-08-28T00:00:00Z",
                    TEST_USER["userId"],
                    "APPROVED_LOCAL_PRIVATE_USE",
                    json_dumps({}, {}),
                    json_dumps([2023, 2024, 2025, 2026], []),
                    json_dumps({}, {}),
                    json_dumps(
                        {"datasetKind": "CURRENT_STATCAST_PLATE_APPEARANCE"},
                        {},
                    ),
                ),
            )
            for partition_id, season, minimum, maximum in (
                ("current-pa-2023", 2023, "2023-03-30", "2023-10-01"),
                ("current-pa-2024", 2024, "2024-03-20", "2024-09-29"),
                ("current-pa-2025", 2025, "2025-03-18", "2025-09-28"),
                ("current-pa-2026", 2026, "2026-03-25", "2026-08-27"),
            ):
                connection.execute(
                    """
                    INSERT INTO sports_dataset_partitions (
                      partition_id, registration_id, family, season, month,
                      logical_uri, row_count, byte_count, minimum_date,
                      maximum_date, schema_id, physical_schema_fingerprint,
                      file_sha, source_key, source_version_id,
                      original_source_logical_identity, checkpoint_lineage_id,
                      governance_checksum, target_eligibility_json,
                      temporal_classification_json, rights_ids_json,
                      physical_schema_json
                    ) VALUES (?, ?, 'plate_appearance', ?, NULL, ?, 100, 1, ?, ?,
                              'schema-current', ?, ?, 'source', 'source-current',
                              NULL, NULL, NULL, '[]', '[]', '[]', '[]')
                    """,
                    (
                        partition_id,
                        "sports-dataset-current-statcast-03ca6dab30e760b2",
                        season,
                        f"asp-model-exchange://current/{season}.parquet",
                        minimum,
                        maximum,
                        "e" * 64,
                        "f" * 64,
                    ),
                )

    @staticmethod
    def _custom_payload(*, expected_version: int = 0) -> dict:
        return {
            "expectedVersion": expected_version,
            "contract": {
                "temporalDesignMode": CUSTOM_DATES,
                "target": "Plate-Appearance Outcome",
                "lifecycle": "Pregame — Final",
                "evidenceMode": "STRICT",
                "chronologicalValidation": {"required": True},
                "eligibleEvidenceStart": "2023-03-30",
                "eligibleEvidenceEnd": "2025-09-28",
                "developmentSelectionStart": "2023-03-30",
                "developmentSelectionEnd": "2025-08-31",
                "finalOotStart": "2025-09-01",
                "finalOotEnd": "2025-09-28",
                "intendedOutputs": ["Plate-Appearance Outcome"],
                "researchPurpose": "Evaluate a chronological MLB model.",
                "notes": "Stage 1 defines only the broad temporal boundary.",
            },
        }

    def test_valid_custom_contract_saves_reloads_and_versions_immutably(self) -> None:
        first = self.contracts.save(
            "mlb-project",
            self._custom_payload(),
            user_id=TEST_USER["userId"],
        )
        self.assertEqual(first["currentVersion"], 1)
        self.assertEqual(first["history"], [])
        self.assertEqual(first["current"]["eligibleEvidenceStart"], "2023-03-30")
        self.assertEqual(first["current"]["finalOotEnd"], "2025-09-28")
        self.assertEqual(
            first["current"]["chronologicalValidation"],
            CHRONOLOGICAL_VALIDATION_REQUIREMENT,
        )
        self.assertIsNone(first["current"]["chronologicalValidation"]["exactBoundaries"])
        self.assertFalse(first["current"]["chronologicalValidation"]["shuffle"])
        self.assertNotIn("chronologicalValidationRequired", first["current"])
        self.assertNotIn("developmentSeasons", first["current"])
        self.assertNotIn("validationSeason", first["current"])
        self.assertNotIn("frozenSeason", first["current"])
        self.assertNotIn("prospectiveSeason", first["current"])
        self.assertEqual(first["sourceCoverage"]["earliestDate"], "2021-04-01")
        self.assertEqual(first["sourceCoverage"]["latestDate"], "2025-09-28")
        self.assertEqual(first["sourceCoverage"]["family"], "plate_appearance")
        self.assertEqual(
            first["current"]["coverageAuthority"]["registrationId"],
            "registration-1",
        )
        self.assertEqual(
            first["current"]["coverageAuthority"]["datasetVersionId"],
            "dataset-version-1",
        )

        first_snapshot = dict(first["current"])
        second_payload = self._custom_payload(expected_version=1)
        second_payload["contract"]["notes"] = "A material revision creates version two."
        second = self.contracts.save(
            "mlb-project",
            second_payload,
            user_id=TEST_USER["userId"],
        )
        self.assertEqual(second["currentVersion"], 2)
        self.assertEqual(len(second["history"]), 1)
        self.assertEqual(second["history"][0], first_snapshot)
        self.assertEqual(second["current"]["supersedesContractId"], first_snapshot["contractId"])

        reloaded = self.contracts.get("mlb-project")
        self.assertEqual(reloaded["current"], second["current"])
        self.assertEqual(reloaded["history"], [first_snapshot])
        self.assertEqual(reloaded["sourceCoverage"]["datasetVersionId"], "dataset-version-1")

    def test_reachable_backend_classifies_missing_project_without_legacy_name(self) -> None:
        with self.assertRaises(SportsForecastContractError) as raised:
            self.contracts.get("browser-only-project")
        self.assertEqual(raised.exception.code, "PROJECT_NOT_REGISTERED")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertNotIn("ATLAS", raised.exception.message)

    def test_global_dataset_does_not_authorize_an_unlinked_project(self) -> None:
        self.persistence.projects.upsert(
            {
                "project_id": "unlinked-project",
                "project_name": "Unlinked Sports Project",
                "project_type": "custom-workflow",
                "workflow_type": "mlb-forecasting",
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {},
            }
        )
        with self.assertRaises(SportsForecastContractError) as raised:
            self.contracts.get("unlinked-project")
        self.assertEqual(raised.exception.code, "DATASET_NOT_LINKED")
        self.assertEqual(raised.exception.status_code, 409)

    def test_sports_api_project_not_registered_is_structured_and_not_atlas(self) -> None:
        from server.persistence import persistence_router

        with patch.object(persistence_router, "_service", return_value=self.persistence):
            with self.assertRaises(HTTPException) as raised:
                persistence_router.get_sports_forecast_contract(
                    "browser-only-project",
                    TEST_USER,
                )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail["code"], "PROJECT_NOT_REGISTERED")
        self.assertNotIn("ATLAS", raised.exception.detail["message"])

    def test_sports_evidence_dataset_api_returns_exact_project_linkage(self) -> None:
        from server.persistence import persistence_router

        with (
            patch.object(persistence_router, "_service", return_value=self.persistence),
            patch.object(
                persistence_router,
                "_forecast_contracts",
                return_value=self.contracts,
            ),
            patch.object(persistence_router, "audit_event"),
        ):
            selected = persistence_router.select_sports_evidence_dataset(
                "mlb-project",
                {"registrationId": "registration-1"},
                TEST_USER,
            )
            reopened = persistence_router.get_sports_evidence_dataset(
                "mlb-project",
                TEST_USER,
            )
        self.assertTrue(selected["ok"])
        self.assertEqual(selected, reopened)
        self.assertEqual(selected["linkage"]["registrationId"], "registration-1")
        self.assertEqual(
            selected["linkage"]["coverage"],
            {
                "earliestDate": "2021-04-01",
                "latestDate": "2025-09-28",
                "family": "plate_appearance",
                "rowCount": 300,
                "partitionCount": 2,
            },
        )

    def test_sports_dataset_selection_does_not_rewrite_sports_stage_state(self) -> None:
        self.persistence.projects.upsert(
            {
                "project_id": "sports-stage-project",
                "project_name": "Sports Stage Project",
                "project_type": "custom-workflow",
                "workflow_type": "mlb-forecasting",
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {},
            }
        )
        expected_status = {"sportsStage": 1, "status": "draft"}
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO workflow_state (
                  project_id, current_step_id, completed_steps_json,
                  workflow_status_json, step_evidence_status_json, updated_at
                ) VALUES (?, 'mlb-01', ?, ?, ?, ?)
                """,
                (
                    "sports-stage-project",
                    json_dumps(["mlb-00"], []),
                    json_dumps(expected_status, {}),
                    json_dumps({"mlb-00": "complete"}, {}),
                    "2026-08-28T00:00:00Z",
                ),
            )
        self.contracts.link_evidence_dataset(
            "sports-stage-project",
            "registration-1",
            user_id=TEST_USER["userId"],
        )
        with self.database.connection() as connection:
            state = connection.execute(
                "SELECT * FROM workflow_state WHERE project_id = ?",
                ("sports-stage-project",),
            ).fetchone()
        self.assertEqual(state["current_step_id"], "mlb-01")
        self.assertEqual(state["completed_steps_json"], json_dumps(["mlb-00"], []))
        self.assertEqual(state["workflow_status_json"], json_dumps(expected_status, {}))
        self.assertEqual(
            state["step_evidence_status_json"],
            json_dumps({"mlb-00": "complete"}, {}),
        )

    def test_current_statcast_link_accepts_intended_dates_and_survives_reload(self) -> None:
        self._seed_current_statcast_coverage()
        self.persistence.projects.upsert(
            {
                "project_id": "current-statcast-project",
                "project_name": "MLB 2026 Current-Data Game Forecast Challenger",
                "project_type": "custom-workflow",
                "workflow_type": "mlb-forecasting",
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {},
            }
        )
        linkage = self.contracts.link_evidence_dataset(
            "current-statcast-project",
            "sports-dataset-current-statcast-03ca6dab30e760b2",
            user_id=TEST_USER["userId"],
        )
        self.assertEqual(linkage["coverage"]["earliestDate"], "2023-03-30")
        self.assertEqual(linkage["coverage"]["latestDate"], "2026-08-27")
        self.assertEqual(
            linkage["datasetId"],
            "asp.mlb.statcast.current-pa.v1",
        )

        payload = self._custom_payload()
        payload["contract"].update(
            {
                "eligibleEvidenceEnd": "2026-08-27",
                "developmentSelectionEnd": "2026-08-13",
                "finalOotStart": "2026-08-14",
                "finalOotEnd": "2026-08-27",
            }
        )
        saved = self.contracts.save(
            "current-statcast-project",
            payload,
            user_id=TEST_USER["userId"],
        )
        self.assertEqual(saved["current"]["eligibleEvidenceStart"], "2023-03-30")
        self.assertEqual(saved["current"]["finalOotEnd"], "2026-08-27")
        self.assertEqual(
            saved["current"]["coverageAuthority"]["registrationId"],
            "sports-dataset-current-statcast-03ca6dab30e760b2",
        )

        reopened = SportsForecastContractStore(Database(self.database.path))
        self.assertEqual(
            reopened.get("current-statcast-project")["current"],
            saved["current"],
        )
        self.assertEqual(
            reopened.get_evidence_dataset("current-statcast-project"),
            linkage,
        )

        # Project selection is scoped. The original FD1 project and the
        # workspace catalog-active registration remain unchanged.
        original = self.contracts.get_evidence_dataset("mlb-project")
        self.assertEqual(original["registrationId"], "registration-1")
        with self.database.connection() as connection:
            active = connection.execute(
                "SELECT registration_id FROM sports_dataset_registrations WHERE active = 1"
            ).fetchall()
        self.assertEqual([row["registration_id"] for row in active], ["registration-1"])

    def test_2026_request_is_rejected_with_exact_coverage_and_missing_interval(self) -> None:
        payload = self._custom_payload()
        payload["contract"].update(
            {
                "eligibleEvidenceEnd": "2026-08-27",
                "developmentSelectionEnd": "2026-08-13",
                "finalOotStart": "2026-08-14",
                "finalOotEnd": "2026-08-27",
            }
        )
        with self.assertRaises(SportsForecastContractError) as raised:
            self.contracts.save("mlb-project", payload, user_id=TEST_USER["userId"])
        error = raised.exception
        self.assertEqual(error.code, "SOURCE_COVERAGE_INSUFFICIENT")
        self.assertEqual(error.status_code, 422)
        detail = error.public_detail()
        self.assertEqual(detail["coverage"]["earliestDate"], "2021-04-01")
        self.assertEqual(detail["coverage"]["latestDate"], "2025-09-28")
        self.assertEqual(
            detail["requestedRange"],
            {"start": "2023-03-30", "end": "2026-08-27"},
        )
        self.assertEqual(
            detail["missingIntervals"],
            [{"start": "2025-09-29", "end": "2026-08-27"}],
        )
        self.assertEqual(
            detail["message"],
            "Registered source evidence currently ends on 2025-09-28. "
            "The requested 2026 evaluation period is not available in the Data Warehouse.",
        )
        self.assertIsNone(self.contracts.get("mlb-project")["current"])

    def test_invalid_custom_ranges_fail_closed(self) -> None:
        cases = []
        invalid_date = self._custom_payload()
        invalid_date["contract"]["finalOotEnd"] = "2025-02-30"
        cases.append((invalid_date, "INVALID_TEMPORAL_DATE"))

        reversed_range = self._custom_payload()
        reversed_range["contract"]["eligibleEvidenceStart"] = "2025-09-29"
        cases.append((reversed_range, "INVALID_TEMPORAL_ORDER"))

        development_outside = self._custom_payload()
        development_outside["contract"]["developmentSelectionStart"] = "2022-01-01"
        cases.append((development_outside, "TEMPORAL_RANGE_OUTSIDE_ELIGIBLE_EVIDENCE"))

        overlap = self._custom_payload()
        overlap["contract"]["finalOotStart"] = overlap["contract"]["developmentSelectionEnd"]
        cases.append((overlap, "TEMPORAL_RANGE_OVERLAP"))

        not_chronological = self._custom_payload()
        not_chronological["contract"]["chronologicalValidation"] = {"required": False}
        cases.append((not_chronological, "CHRONOLOGICAL_VALIDATION_REQUIRED"))

        for payload, code in cases:
            with self.subTest(code=code), self.assertRaises(SportsForecastContractError) as raised:
                self.contracts.save("mlb-project", payload, user_id=TEST_USER["userId"])
            self.assertEqual(raised.exception.code, code)
        self.assertIsNone(self.contracts.get("mlb-project")["current"])

    def test_season_roles_remain_backward_compatible(self) -> None:
        payload = {
            "expectedVersion": 0,
            "contract": {
                # Deliberately omitted: legacy payloads default to season roles.
                "target": "Plate-Appearance Outcome",
                "lifecycle": "Pregame — Final",
                "evidenceMode": "ENHANCED",
                "developmentSeasons": [2023],
                "validationSeason": 2024,
                "frozenSeason": 2025,
                "prospectiveSeason": 2026,
                "intendedOutputs": ["Plate-Appearance Outcome"],
                "researchPurpose": "Preserve the existing whole-season contract.",
                "notes": "",
            },
        }
        saved = self.contracts.save(
            "mlb-project",
            payload,
            user_id=TEST_USER["userId"],
        )
        current = saved["current"]
        self.assertEqual(current["temporalDesignMode"], SEASON_ROLES)
        self.assertEqual(current["developmentSeasons"], [2023])
        self.assertEqual(current["validationSeason"], 2024)
        self.assertEqual(current["frozenSeason"], 2025)
        self.assertEqual(current["prospectiveSeason"], 2026)
        self.assertNotIn("eligibleEvidenceStart", current)

    def test_season_role_frozen_year_cannot_exceed_pa_coverage(self) -> None:
        payload = {
            "expectedVersion": 0,
            "contract": {
                "temporalDesignMode": SEASON_ROLES,
                "target": "Plate-Appearance Outcome",
                "lifecycle": "Pregame — Final",
                "evidenceMode": "STRICT",
                "developmentSeasons": [2023, 2024],
                "validationSeason": 2025,
                "frozenSeason": 2026,
                # Prospective may be future, but it cannot make a future
                # frozen evidence season valid.
                "prospectiveSeason": 2027,
                "intendedOutputs": ["Plate-Appearance Outcome"],
                "researchPurpose": "Exercise the whole-season authority boundary.",
                "notes": "",
            },
        }
        with self.assertRaises(SportsForecastContractError) as raised:
            self.contracts.save(
                "mlb-project",
                payload,
                user_id=TEST_USER["userId"],
            )
        detail = raised.exception.public_detail()
        self.assertEqual(raised.exception.code, "SOURCE_COVERAGE_INSUFFICIENT")
        self.assertEqual(detail["coverage"]["latestDate"], "2025-09-28")
        self.assertEqual(
            detail["missingIntervals"],
            [{"start": "2026-01-01", "end": "2026-12-31"}],
        )
        self.assertEqual(
            detail["requestedSeasons"],
            {
                "developmentSeasons": [2023, 2024],
                "validationSeason": 2025,
                "frozenSeason": 2026,
            },
        )
        self.assertEqual(
            detail["message"],
            "Registered source evidence currently ends on 2025-09-28. "
            "The requested 2026 evaluation period is not available in the Data Warehouse.",
        )
        self.assertIsNone(self.contracts.get("mlb-project")["current"])

    def test_concurrent_same_version_saves_allow_exactly_one_writer(self) -> None:
        barrier = threading.Barrier(2)

        def save(note: str) -> tuple[str, str]:
            payload = self._custom_payload()
            payload["contract"]["notes"] = note
            barrier.wait(timeout=5)
            try:
                result = self.contracts.save(
                    "mlb-project",
                    payload,
                    user_id=TEST_USER["userId"],
                )
                return "saved", result["current"]["notes"]
            except SportsForecastContractError as exc:
                return "error", exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save, ("writer-a", "writer-b")))
        self.assertEqual([item[0] for item in results].count("saved"), 1)
        self.assertEqual(
            results.count(("error", "FORECAST_CONTRACT_VERSION_CONFLICT")),
            1,
        )
        reloaded = self.contracts.get("mlb-project")
        self.assertEqual(reloaded["currentVersion"], 1)
        self.assertEqual(reloaded["history"], [])

    def test_generic_project_put_cannot_overwrite_reserved_contract_node(self) -> None:
        saved = self.contracts.save(
            "mlb-project",
            self._custom_payload(),
            user_id=TEST_USER["userId"],
        )
        original_current = saved["current"]

        from server.persistence import persistence_router

        with (
            patch.object(persistence_router, "_service", return_value=self.persistence),
            patch.object(
                persistence_router,
                "_authorize_project",
                return_value=self.persistence.projects.get("mlb-project"),
            ),
            patch.object(
                persistence_router,
                "_project_with_durable_dataset_state",
                side_effect=lambda record, _user: record,
            ),
            patch.object(persistence_router, "audit_event"),
        ):
            persistence_router.update_project(
                "mlb-project",
                {
                    "metadata": {
                        "ordinarySetting": "updated",
                        FORECAST_CONTRACT_METADATA_KEY: {
                            "schemaVersion": "forged",
                            "currentVersion": 999,
                        },
                    }
                },
                TEST_USER,
            )

        reloaded = self.contracts.get("mlb-project")
        self.assertEqual(reloaded["currentVersion"], 1)
        self.assertEqual(reloaded["current"], original_current)
        project = self.persistence.projects.get("mlb-project") or {}
        self.assertEqual(project["metadata_json"]["ordinarySetting"], "updated")
        self.assertEqual(
            project["metadata_json"][FORECAST_CONTRACT_METADATA_KEY]["currentVersion"],
            1,
        )

    def test_racing_generic_project_put_preserves_newly_committed_contract(self) -> None:
        from server.persistence import persistence_router

        generic_writer_entered = threading.Event()
        contract_committed = threading.Event()
        original_atomic_upsert = (
            self.persistence.projects.upsert_preserving_metadata_keys
        )

        def delayed_atomic_upsert(record: dict, *, reserved_metadata_keys: set[str]) -> dict:
            # update_project has already assembled its stale metadata snapshot
            # when it reaches this repository boundary.
            generic_writer_entered.set()
            if not contract_committed.wait(timeout=10):
                raise AssertionError("Contract writer did not commit during the deterministic race.")
            return original_atomic_upsert(
                record,
                reserved_metadata_keys=reserved_metadata_keys,
            )

        def save_generic_project() -> dict:
            with (
                patch.object(persistence_router, "_service", return_value=self.persistence),
                patch.object(
                    persistence_router,
                    "_authorize_project",
                    return_value=self.persistence.projects.get("mlb-project"),
                ),
                patch.object(
                    persistence_router,
                    "_project_with_durable_dataset_state",
                    side_effect=lambda record, _user: record,
                ),
                patch.object(persistence_router, "audit_event"),
                patch.object(
                    self.persistence.projects,
                    "upsert_preserving_metadata_keys",
                    side_effect=delayed_atomic_upsert,
                ),
            ):
                return persistence_router.update_project(
                    "mlb-project",
                    {"metadata": {"ordinarySetting": "racing-update"}},
                    TEST_USER,
                )

        def save_contract() -> dict:
            if not generic_writer_entered.wait(timeout=10):
                raise AssertionError("Generic writer did not reach its stale-snapshot boundary.")
            try:
                return self.contracts.save(
                    "mlb-project",
                    self._custom_payload(),
                    user_id=TEST_USER["userId"],
                )
            finally:
                contract_committed.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            generic_future = executor.submit(save_generic_project)
            contract_future = executor.submit(save_contract)
            generic_future.result(timeout=15)
            saved_contract = contract_future.result(timeout=15)

        reloaded = self.contracts.get("mlb-project")
        self.assertEqual(reloaded["current"], saved_contract["current"])
        self.assertEqual(reloaded["currentVersion"], 1)
        project = self.persistence.projects.get("mlb-project") or {}
        self.assertEqual(project["metadata_json"]["ordinarySetting"], "racing-update")
        self.assertEqual(
            project["metadata_json"][FORECAST_CONTRACT_METADATA_KEY]["currentVersion"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
