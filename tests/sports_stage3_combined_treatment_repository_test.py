from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from server.persistence.db import Database
from server.persistence.repositories.stage3_treatment_repository import (
    Stage3TreatmentPersistenceError,
    Stage3TreatmentRepository,
)


PROJECT_ID = "asp-combined-spec-test"
AUTHORITY_DIGEST = "5" * 64


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "persistence.db")
    database.initialize()
    return database


def _authority() -> dict[str, Any]:
    return {
        "projectId": PROJECT_ID,
        "registrationId": "registration-current",
        "datasetVersionId": "current-pa-v1",
        "activationRevision": 7,
        "sourceDatasetId": "asp.mlb.statcast.current-pa.v1",
        "sourceManifestSha": "1" * 64,
        "goldManifestSha": "2" * 64,
        "contextualManifestSha": "3" * 64,
        "reviewDigest": AUTHORITY_DIGEST,
        "development": {
            "startDate": "2021-03-01",
            "endDate": "2025-09-28",
            "rows": 683_662,
        },
        "finalOot": {
            "startDate": "2026-03-25",
            "endDate": "2026-09-27",
            "rows": 99_999,
            "identity": "locked-final-oot-fixture",
        },
    }


def _manifest() -> dict[str, Any]:
    return {
        "manifestId": "MLB_FEATURE_TREATMENT_SPEC_V1:sha256:example",
        "manifestName": "MLB Feature Treatment Specification",
        "compilerVersion": "MLB_FEATURE_TREATMENT_COMPILER_V1",
        "reviewLabel": "Jos\u00e9 \u2014 deterministic UTF-8",
        "features": [
            {
                "featureName": "batter_prior_missing",
                "reviewStatus": "REVIEW_REQUIRED",
            }
        ],
    }


def _manifest_checksum(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _kwargs(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "authority": _authority(),
        "source_workbook_filename": "ASP_MLB_Feature_Treatment_Specification.xlsx",
        "source_workbook_sha256": "a" * 64,
        "feature_inventory_sha256": "b" * 64,
        "manifest": manifest,
        "manifest_checksum": _manifest_checksum(manifest),
        "outlier_draft": {
            "globalMethod": "IQR_1_5",
            "policy": {
                "globalTreatment": "RETAIN",
                "overrides": {},
                "thresholdAuthority": "FITTING_RULE_ONLY",
            },
            "fittingRule": {"fitScope": "TRAINING_ROWS_ONLY"},
            "notes": "compiled outlier proposal",
        },
        "missing_draft": {
            "globalMethod": "DATA_TYPE_AWARE",
            "policy": {
                "overrides": {},
                "sourceFailureDefault": "REVIEW_REQUIRED",
            },
            "fittingRule": {"fitScope": "TRAINING_ROWS_ONLY"},
            "notes": "compiled missing-value proposal",
        },
        "notes": "one deterministic combined review draft",
        "actor_user_id": "user-1",
    }


def _counts(database: Database) -> tuple[int, int, int, int]:
    with database.connection() as connection:
        return tuple(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "stage3_treatment_policy_versions",
                "stage3_treatment_policy_events",
                "stage3_feature_treatment_spec_versions",
                "stage3_feature_treatment_spec_events",
            )
        )


def test_combined_spec_draft_atomically_binds_children_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = Stage3TreatmentRepository(database)
    manifest = _manifest()
    first = repository.save_combined_spec_draft(**_kwargs(manifest))

    assert first["status"] == "DRAFT"
    assert first["specificationVersion"] == 1
    assert first["projectId"] == PROJECT_ID
    assert first["sourceWorkbookSha256"] == "a" * 64
    assert first["featureInventorySha256"] == "b" * 64
    assert first["manifestChecksum"] == _manifest_checksum(manifest)
    assert first["manifest"] == manifest
    assert first["authorityReviewDigest"] == AUTHORITY_DIGEST
    assert first["goldManifestSha"] == "2" * 64
    assert first["finalOot"]["identity"] == "locked-final-oot-fixture"
    assert first["finalOot"]["locked"] is True
    assert first["finalOot"]["targetsAccessed"] is False
    assert first["linkedPolicies"]["outlier"]["status"] == "DRAFT"
    assert first["linkedPolicies"]["outlier"]["policyKind"] == "OUTLIER"
    assert first["linkedPolicies"]["missing"]["status"] == "DRAFT"
    assert first["linkedPolicies"]["missing"]["policyKind"] == "IMPUTATION"
    assert first["checksum"] == first["contentSha256"]
    assert first["immutable"] is True
    assert _counts(database) == (2, 2, 1, 1)

    repeated = repository.save_combined_spec_draft(**_kwargs(manifest))
    assert repeated["specificationId"] == first["specificationId"]
    assert repeated["linkedPolicies"]["outlier"]["policyId"] == first["linkedPolicies"]["outlier"]["policyId"]
    assert repeated["linkedPolicies"]["missing"]["policyId"] == first["linkedPolicies"]["missing"]["policyId"]
    assert _counts(database) == (2, 2, 1, 1)

    state = repository.combined_spec_state(PROJECT_ID, AUTHORITY_DIGEST)
    assert state["latestDraft"]["specificationId"] == first["specificationId"]
    assert state["adopted"] is None
    assert [row["specificationVersion"] for row in state["history"]] == [1]


def test_changed_inventory_appends_receipt_and_receipts_are_immutable(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = Stage3TreatmentRepository(database)
    manifest = _manifest()
    first = repository.save_combined_spec_draft(**_kwargs(manifest))
    revised_kwargs = _kwargs(manifest)
    revised_kwargs["feature_inventory_sha256"] = "c" * 64
    second = repository.save_combined_spec_draft(**revised_kwargs)

    assert second["specificationId"] != first["specificationId"]
    assert second["specificationVersion"] == 2
    assert second["priorSpecificationId"] == first["specificationId"]
    # The child proposal content did not change, so its immutable drafts are reused.
    assert second["linkedPolicies"]["outlier"]["policyId"] == first["linkedPolicies"]["outlier"]["policyId"]
    assert second["linkedPolicies"]["missing"]["policyId"] == first["linkedPolicies"]["missing"]["policyId"]
    assert _counts(database) == (2, 2, 2, 2)

    with database.connection() as connection:
        event_id = connection.execute(
            """
            SELECT feature_treatment_spec_event_id
            FROM stage3_feature_treatment_spec_events
            ORDER BY created_at LIMIT 1
            """
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE stage3_feature_treatment_spec_versions SET notes = 'changed' WHERE feature_treatment_spec_id = ?",
                (first["specificationId"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM stage3_feature_treatment_spec_versions WHERE feature_treatment_spec_id = ?",
                (first["specificationId"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE stage3_feature_treatment_spec_events SET payload_json = '{}' WHERE feature_treatment_spec_event_id = ?",
                (event_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM stage3_feature_treatment_spec_events WHERE feature_treatment_spec_event_id = ?",
                (event_id,),
            )


def test_combined_spec_rolls_back_both_children_when_second_child_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path)
    repository = Stage3TreatmentRepository(database)
    original = repository._save_draft_in_connection

    def fail_on_missing(connection: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
        inserted = original(connection, **kwargs)
        if kwargs["policy_kind"] == "IMPUTATION":
            raise RuntimeError("synthetic second-child failure")
        return inserted

    monkeypatch.setattr(repository, "_save_draft_in_connection", fail_on_missing)
    with pytest.raises(RuntimeError, match="second-child"):
        repository.save_combined_spec_draft(**_kwargs(_manifest()))
    assert _counts(database) == (0, 0, 0, 0)


def test_combined_spec_rejects_noncanonical_manifest_checksum_before_writes(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = Stage3TreatmentRepository(database)
    values = _kwargs(_manifest())
    values["manifest_checksum"] = "0" * 64
    with pytest.raises(Stage3TreatmentPersistenceError, match="checksum"):
        repository.save_combined_spec_draft(**values)
    assert _counts(database) == (0, 0, 0, 0)
