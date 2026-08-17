from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from server.persistence.db import Database, json_dumps
from server.sports_datasets.constants import (
    DATASET_ID,
    DATASET_VERSION_ID,
    MANIFEST_ID,
    MANIFEST_SHA,
    PACKAGE_ID,
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    PROJECT_NAME,
    REGISTRATION_ID,
)
from server.sports_identity_bridges.constants import (
    BRIDGE_MANIFEST_SHA,
    BRIDGE_REGISTRATION_ID,
    EXPECTED_JOIN_REFERENCES,
)
from server.sports_identity_bridges.registry import (
    IdentityBridgeRegistrationError,
    SportsIdentityBridgeRegistry,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPOSITORY_ROOT / ".tmp"


def _coverage() -> list[dict[str, object]]:
    values = {
        (2023, "BATTER"): (184_104, 169_005, 15_099, 2022),
        (2023, "PITCHER"): (184_104, 159_568, 24_536, 2022),
        (2024, "BATTER"): (182_449, 170_594, 11_855, 2023),
        (2024, "PITCHER"): (182_449, 160_914, 21_535, 2023),
        (2025, "BATTER"): (182_926, 167_720, 15_206, 2024),
        (2025, "PITCHER"): (182_926, 164_678, 18_248, 2024),
    }
    return [
        {
            "target_season": season,
            "role": role,
            "reference_rows": reference_rows,
            "rows_with_eligible_prior": eligible,
            "legitimate_missing_prior_rows": missing,
            "eligible_prior_rate": eligible / reference_rows,
            "unresolved_identity_rows": 0,
            "ambiguous_identity_rows": 0,
            "multiply_mapped_identity_rows": 0,
            "maximum_eligible_prior_season": maximum,
        }
        for (season, role), (reference_rows, eligible, missing, maximum) in values.items()
    ]


def _validated() -> SimpleNamespace:
    coverage = _coverage()
    return SimpleNamespace(
        manifest={
            "bridge_manifest_sha256": BRIDGE_MANIFEST_SHA,
            "totals": {},
            "identity_namespaces": [
                {"namespace": namespace, "alias_rows": 2_692}
                for namespace in (
                    "RETROSHEET",
                    "LAHMAN",
                    "CHADWICK",
                    "MLBAM",
                    "BASEBALL_REFERENCE",
                )
            ],
            "y_minus_1_prior_eligibility": coverage,
            "limitations": [
                {
                    "limitation_id": "PARENT_PHYSICAL_SCOPE_OMITS_ONE_GOVERNED_ROSTER_IDENTITY",
                    "description": "One governed roster-only identity has zero downstream impact.",
                    "scope": "IDENTITY_BRIDGE",
                }
            ],
            "source_rights": {
                "allowed_purposes": ["READ_ONLY_REGISTRATION"],
                "prohibited_purposes": ["PUBLIC_RAW_REDISTRIBUTION"],
            },
        },
        source_rights={},
    )


def _audit() -> dict[str, object]:
    return {
        "status": "PASS",
        "totalReferences": EXPECTED_JOIN_REFERENCES,
        "resolvedReferences": EXPECTED_JOIN_REFERENCES,
        "unresolvedReferences": 0,
        "ambiguousReferences": 0,
        "multiplyMappedReferences": 0,
        "joins": [
            {
                "joinContractId": "plate_appearance.batter_id.retrosheet-to-canonical",
                "referenceCount": 913_349,
                "resolvedReferenceCount": 913_349,
                "mappingRate": 1.0,
            }
        ],
        "yMinus1Coverage": _coverage(),
    }


class SportsIdentityBridgeRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = SCRATCH_ROOT / f"sports-identity-registry-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=False)
        self.database = Database(self.root / "registry.db")
        self.database.initialize()
        metadata = {
            "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
            "modelingBlockers": [
                {
                    "limitationId": "MLB_PA_PLAYER_PRIOR_IDENTITY_BRIDGE_ABSENT",
                    "description": "identity bridge required",
                },
                {
                    "limitationId": "UNRELATED_BLOCKER_MUST_SURVIVE",
                    "description": "preserve unrelated evidence",
                },
            ],
            "featureAudit": {
                "contractVersion": "MLB_PA_FEATURE_VIEW_V1",
                "status": "BLOCKED",
            },
        }
        workflow = {
            "objective_forecast_contract": {"status": "COMPLETE"},
            "identity_coverage_leakage": {"status": "BLOCKED"},
            "player_team_state": {"status": "BLOCKED"},
        }
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
                ) VALUES (?, ?, ?, ?, ?, ?, 'Baseball', 'MLB', '2026-08-15',
                  '2026-08-16T05:21:08.171241Z', ?, 'VALID', ?, ?, ?, 'PASS',
                  12, 1, '{}', '[]', '{}', ?)
                """,
                (
                    REGISTRATION_ID,
                    DATASET_ID,
                    DATASET_VERSION_ID,
                    MANIFEST_ID,
                    MANIFEST_SHA,
                    PACKAGE_ID,
                    "asp-model-exchange://datasets/mlb-fd1/exact",
                    "2026-08-16T00:00:00+00:00",
                    "2026-08-16T00:00:00+00:00",
                    "phase-2-admin",
                    json_dumps(metadata, {}),
                ),
            )
            connection.execute(
                """
                INSERT INTO sports_research_projects (
                  project_id, registration_id, project_name, sport, league,
                  development_period, prior_history, forecast_lifecycle,
                  primary_target, secondary_targets_json, baseline_population,
                  upper_bound_population, research_purpose, workflow_evidence_json,
                  created_by, created_at, updated_at
                ) VALUES (?, ?, ?, 'Baseball', 'MLB', '2023-2025', '2021-2022',
                  'Pregame - Final', 'Plate-Appearance Outcome', '[]',
                  'Strict Deployable', 'Enhanced Research', 'Research baseline', ?,
                  'phase-2-admin', ?, ?)
                """,
                (
                    PROJECT_ID,
                    REGISTRATION_ID,
                    PROJECT_NAME,
                    json_dumps(workflow, {}),
                    "2026-08-16T00:00:00+00:00",
                    "2026-08-16T00:00:00+00:00",
                ),
            )
        self.registry = SportsIdentityBridgeRegistry(self.database)

    def test_metadata_only_registration_is_exact_idempotent_and_logical(self) -> None:
        first = self.registry.register(
            _validated(),
            _audit(),
            runtime_root=self.root / "runtime",
            user_id="phase-3-admin",
            code_revision="worktree-sha256:test",
        )
        second = self.registry.register(
            _validated(),
            _audit(),
            runtime_root=self.root / "runtime",
            user_id="different-admin",
            code_revision="worktree-sha256:test",
        )
        self.assertEqual(first["registrationId"], BRIDGE_REGISTRATION_ID)
        self.assertEqual(first["registrationDisposition"], "CREATED")
        self.assertEqual(second["registrationDisposition"], "REUSED")
        self.assertEqual(first["joinAudit"]["totalReferences"], EXPECTED_JOIN_REFERENCES)
        self.assertEqual(first["joinAudit"]["mappingRate"], 1.0)
        self.assertTrue(first["joinAudit"]["logicalUri"].startswith("asp-model-studio-runtime://"))
        self.assertTrue(first["logicalRoot"].startswith("asp-model-exchange://"))
        serialized = json.dumps(first, sort_keys=True)
        self.assertNotIn("C:\\\\Users", serialized)
        self.assertNotIn(str(self.root), serialized)

        with self.database.connection() as connection:
            counts = (
                connection.execute("SELECT COUNT(*) FROM sports_identity_bridge_registrations").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM sports_identity_join_audits").fetchone()[0],
            )
            registered_by = connection.execute(
                "SELECT registered_by FROM sports_identity_bridge_registrations"
            ).fetchone()[0]
            parent_metadata = json.loads(
                connection.execute(
                    "SELECT metadata_json FROM sports_dataset_registrations WHERE registration_id = ?",
                    (REGISTRATION_ID,),
                ).fetchone()[0]
            )
            project_workflow = json.loads(
                connection.execute(
                    "SELECT workflow_evidence_json FROM sports_research_projects WHERE project_id = ?",
                    (PROJECT_ID,),
                ).fetchone()[0]
            )
        self.assertEqual(counts, (1, 1))
        self.assertEqual(registered_by, "phase-3-admin")
        self.assertEqual(
            [item["limitationId"] for item in parent_metadata["modelingBlockers"]],
            ["UNRELATED_BLOCKER_MUST_SURVIVE"],
        )
        self.assertEqual(parent_metadata["featureAudit"]["status"], "IDENTITY_BRIDGE_VALIDATED")
        self.assertEqual(project_workflow["identity_coverage_leakage"]["status"], "COMPLETE")
        self.assertEqual(project_workflow["event_models"]["status"], "READY_FOR_BASELINE")
        self.assertEqual(project_workflow["game_simulation"]["status"], "NOT_CONFIGURED")
        self.assertEqual(project_workflow["export_to_asp"]["status"], "NOT_CONFIGURED")

    def test_parent_partition_authority_mismatch_fails_closed(self) -> None:
        with self.database.transaction() as connection:
            registration = connection.execute(
                "SELECT metadata_json FROM sports_dataset_registrations WHERE registration_id = ?",
                (REGISTRATION_ID,),
            ).fetchone()
            metadata = json.loads(registration[0])
            metadata["partitionAuthoritySha"] = "0" * 64
            connection.execute(
                "UPDATE sports_dataset_registrations SET metadata_json = ? WHERE registration_id = ?",
                (json_dumps(metadata, {}), REGISTRATION_ID),
            )
        with self.assertRaises(IdentityBridgeRegistrationError):
            self.registry.register(
                _validated(),
                _audit(),
                runtime_root=self.root / "runtime",
                user_id="phase-3-admin",
                code_revision="test",
            )

    def test_failed_join_audit_cannot_clear_the_blocker(self) -> None:
        audit = _audit()
        audit["unresolvedReferences"] = 1
        audit["resolvedReferences"] = EXPECTED_JOIN_REFERENCES - 1
        with self.assertRaises(IdentityBridgeRegistrationError):
            self.registry.register(
                _validated(),
                audit,
                runtime_root=self.root / "runtime",
                user_id="phase-3-admin",
                code_revision="test",
            )
        with self.database.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM sports_identity_bridge_registrations").fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
