"""Capture and compare layered, read-only protected-authority snapshots.

This utility is intentionally independent from ATLAS application imports.  It
opens SQLite databases in read-only/query-only mode and hashes fixed safe
projections.  Sensitive payload columns, credentials, message bodies, row
memberships, and holdout contents are never queried.  A whole-database-file
hash is retained only as supplementary evidence; logical and audit projections
are the authoritative comparison layers.

Manifest shape::

    {
      "schema_version": "1.0",
      "immutable_files": [
        {"authority_id": "registry", "path": "...", "required": true}
      ],
      "sqlite_authorities": [
        {
          "authority_id": "catalog-registry",
          "path": "...",
          "profile": "bureau_catalog_registry",
          "required": true,
          "scope": {"catalog_version_id": "catalog-version-id"}
        }
      ]
    }

The emitted snapshot never contains physical paths or raw scope identities.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote


SNAPSHOT_SCHEMA_VERSION = "1.0"
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
_MAX_IDENTITY_LENGTH = 256
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AUTHORITY_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_PUBLIC_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:/ -]{1,96}$")
_PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_TIMESTAMP_RE = re.compile(r"^[0-9TZtz:+. -]{1,64}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFETY_CONTRACT: Mapping[str, bool] = {
    "physical_paths_emitted": False,
    "credentials_selected": False,
    "message_bodies_selected": False,
    "row_memberships_selected": False,
    "holdout_data_selected": False,
    "sqlite_whole_file_authoritative": False,
}


class ProtectedAuthorityError(RuntimeError):
    """A safe validation or capture failure."""


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ProtectedAuthorityError("Command arguments are incomplete or invalid.")


@dataclass(frozen=True, slots=True)
class ProjectionSpec:
    table: str
    safe_columns: tuple[str, ...]
    scope_keys: tuple[str, ...] = ()
    status_columns: tuple[str, ...] = ()
    revision_columns: tuple[str, ...] = ()
    checksum_columns: tuple[str, ...] = ()
    timestamp_columns: tuple[str, ...] = ()
    null_state_columns: tuple[tuple[str, str, str], ...] = ()
    required: bool = False


@dataclass(frozen=True, slots=True)
class AuditSpec:
    table: str
    id_column: str
    timestamp_column: str
    action_column: str
    actor_column: str
    project_column: str | None = None
    entity_type_column: str | None = None
    entity_id_column: str | None = None
    status_column: str | None = None
    required: bool = False


@dataclass(frozen=True, slots=True)
class RelationshipSpec:
    name: str
    child_table: str
    parent_table: str
    child_columns: tuple[str, ...]
    parent_columns: tuple[str, ...]
    scope_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    projections: tuple[ProjectionSpec, ...]
    audits: tuple[AuditSpec, ...]
    relationships: tuple[RelationshipSpec, ...]
    allowed_scope_keys: frozenset[str]


_ATLAS_PRIMARY = ProfileSpec(
    projections=(
        ProjectionSpec(
            "projects",
            (
                "project_id",
                "project_type",
                "workflow_type",
                "template_id",
                "status",
                "owner_user_id",
                "created_at",
                "updated_at",
            ),
            scope_keys=("project_id",),
            status_columns=("status",),
            timestamp_columns=("created_at", "updated_at"),
            required=True,
        ),
        ProjectionSpec(
            "workflow_state",
            (
                "project_id",
                "current_step_id",
                "completed_steps_json",
                "workflow_status_json",
                "step_evidence_status_json",
                "updated_at",
            ),
            scope_keys=("project_id",),
            timestamp_columns=("updated_at",),
        ),
        ProjectionSpec(
            "run_records",
            (
                "run_id",
                "project_id",
                "run_type",
                "workflow_type",
                "status",
                "started_at",
                "completed_at",
            ),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
            status_columns=("status",),
            timestamp_columns=("started_at", "completed_at"),
        ),
        ProjectionSpec(
            "datasets",
            ("dataset_id", "project_id", "source_type", "created_at"),
            scope_keys=("project_id", "dataset_id"),
            timestamp_columns=("created_at",),
        ),
        ProjectionSpec(
            "dataset_versions",
            (
                "dataset_version_id",
                "dataset_id",
                "row_count",
                "column_count",
                "dataset_hash",
                "created_at",
            ),
            scope_keys=("dataset_id", "dataset_version_id"),
            checksum_columns=("dataset_hash",),
            timestamp_columns=("created_at",),
        ),
        ProjectionSpec(
            "project_dataset_links",
            (
                "project_id",
                "dataset_id",
                "link_status",
                "linked_by",
                "linked_at",
                "updated_at",
            ),
            scope_keys=("project_id", "dataset_id"),
            status_columns=("link_status",),
            timestamp_columns=("linked_at", "updated_at"),
        ),
        ProjectionSpec(
            "active_modeling_dataset_versions",
            (
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "activation_revision",
                "activation_status",
                "activated_by",
                "activated_at",
                "updated_at",
            ),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
            status_columns=("activation_status",),
            revision_columns=("activation_revision",),
            timestamp_columns=("activated_at", "updated_at"),
        ),
        ProjectionSpec(
            "predictor_authorization_manifests",
            (
                "predictor_authorization_id",
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "target_contract_id",
                "target_column",
                "authorized_predictors_json",
                "excluded_predictors_json",
                "manifest_json",
                "artifact_hash",
                "status",
                "created_by",
                "created_at",
                "updated_at",
                "superseded_by_id",
            ),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
            status_columns=("status",),
            checksum_columns=("artifact_hash",),
            timestamp_columns=("created_at", "updated_at"),
        ),
        ProjectionSpec(
            "analysis_partitions",
            (
                "analysis_partition_id",
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "target_contract_id",
                "target_column",
                "predictor_authorization_id",
                "development_partition_id",
                "sealed_holdout_partition_id",
                "development_share",
                "holdout_share",
                "random_seed",
                "stratification_policy",
                "stratification_field",
                "population_count",
                "development_count",
                "holdout_count",
                "assignment_hash",
                "population_fingerprint",
                "artifact_hash",
                "status",
                "revision",
                "final_holdout_status",
                "holdout_isolation_status",
                "problem_type",
                "partition_method",
                "preview_fingerprint",
                "evidence_status",
                "mdd_status",
                "created_by",
                "created_at",
                "sealed_at",
                "updated_at",
                "superseded_by_partition_id",
            ),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
            status_columns=(
                "status",
                "final_holdout_status",
                "holdout_isolation_status",
                "evidence_status",
                "mdd_status",
            ),
            revision_columns=("revision",),
            checksum_columns=(
                "assignment_hash",
                "population_fingerprint",
                "artifact_hash",
                "preview_fingerprint",
            ),
            timestamp_columns=("created_at", "sealed_at", "updated_at"),
        ),
        ProjectionSpec(
            "special_value_reviews",
            (
                "special_value_review_id",
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "activation_revision",
                "predictor_authorization_id",
                "target_contract_id",
                "detection_fingerprint",
                "detection_json",
                "decisions_json",
                "status",
                "detected_count",
                "reviewed_count",
                "open_count",
                "blocks_confirmation",
                "blocks_continuation",
                "revision",
                "created_by",
                "updated_by",
                "confirmed_by",
                "created_at",
                "updated_at",
                "confirmed_at",
            ),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
            status_columns=("status",),
            revision_columns=("activation_revision", "revision"),
            checksum_columns=("detection_fingerprint",),
            timestamp_columns=("created_at", "updated_at", "confirmed_at"),
        ),
        ProjectionSpec(
            "evidence_artifacts",
            (
                "evidence_id",
                "project_id",
                "workflow_type",
                "step_id",
                "artifact_type",
                "status",
                "source_ref",
                "artifact_hash",
                "created_by",
                "created_at",
                "captured_at",
                "approved_at",
            ),
            scope_keys=("project_id",),
            status_columns=("status",),
            checksum_columns=("artifact_hash",),
            timestamp_columns=("created_at", "captured_at", "approved_at"),
        ),
        ProjectionSpec(
            "mdd_documents",
            (
                "mdd_document_id",
                "project_id",
                "template_version_id",
                "current_validated_version_id",
                "created_by_user_id",
                "created_at",
                "updated_at",
            ),
            scope_keys=("project_id",),
            timestamp_columns=("created_at", "updated_at"),
        ),
        ProjectionSpec(
            "model_versions",
            (
                "model_version_id",
                "model_id",
                "project_id",
                "status",
                "version_number",
                "dataset_version_id",
                "feature_manifest_id",
                "training_run_id",
                "artifact_hash",
                "created_by_user_id",
                "created_at",
                "updated_at",
            ),
            scope_keys=("project_id", "dataset_version_id"),
            status_columns=("status",),
            revision_columns=("version_number",),
            checksum_columns=("artifact_hash",),
            timestamp_columns=("created_at", "updated_at"),
        ),
        ProjectionSpec(
            "candidate_selection_decisions",
            (
                "candidate_decision_id",
                "decision_status",
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "feature_manifest_id",
                "feature_manifest_hash",
                "treatment_manifest_id",
                "treatment_manifest_hash",
                "materialization_id",
                "validation_design_id",
                "validation_design_version_id",
                "split_id",
                "training_job_id",
                "training_run_id",
                "candidate_id",
                "selection_partition_id",
                "fold_definition_id",
                "fold_count",
                "out_of_fold_prediction_artifact_id",
                "threshold_source",
                "calibration_source",
                "ranking_snapshot_hash",
                "selection_locked_at",
                "actor",
                "selection_integrity_status",
                "holdout_isolation_status",
                "integrity_classified_at",
                "integrity_classified_by",
                "decision_contract_hash",
                "created_at",
            ),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
            status_columns=(
                "decision_status",
                "selection_integrity_status",
                "holdout_isolation_status",
            ),
            checksum_columns=(
                "feature_manifest_hash",
                "treatment_manifest_hash",
                "ranking_snapshot_hash",
                "decision_contract_hash",
            ),
            timestamp_columns=(
                "selection_locked_at",
                "integrity_classified_at",
                "created_at",
            ),
        ),
    ),
    audits=(
        AuditSpec(
            "audit_log",
            "audit_id",
            "created_at",
            "action_type",
            "user_id",
            project_column="project_id",
            entity_type_column="entity_type",
            entity_id_column="entity_id",
            required=True,
        ),
        AuditSpec(
            "project_dataset_activation_events",
            "activation_event_id",
            "created_at",
            "event_type",
            "actor_user_id",
            project_column="project_id",
            entity_type_column=None,
            entity_id_column="dataset_version_id",
            status_column="event_status",
        ),
        AuditSpec(
            "analysis_partition_events",
            "analysis_partition_event_id",
            "created_at",
            "event_type",
            "actor_user_id",
            project_column="project_id",
            entity_type_column=None,
            entity_id_column="analysis_partition_id",
            status_column="event_status",
        ),
        AuditSpec(
            "dataset_library_maintenance_events",
            "maintenance_event_id",
            "created_at",
            "operation_type",
            "actor_user_id",
            project_column="project_id",
            entity_type_column=None,
            entity_id_column="dataset_version_id",
            status_column="event_status",
        ),
        AuditSpec(
            "analysis_partition_reset_operations",
            "reset_operation_id",
            "committed_at",
            "operation_kind",
            "actor_user_id",
            project_column="project_id",
            entity_type_column=None,
            entity_id_column="prior_analysis_partition_id",
            status_column="operation_status",
        ),
        AuditSpec(
            "analysis_partition_derivative_invalidations",
            "derivative_invalidation_id",
            "invalidated_at",
            "artifact_type",
            "actor_user_id",
            project_column="project_id",
            entity_type_column="source_authority",
            entity_id_column="artifact_id",
            status_column="invalidation_status",
        ),
        AuditSpec(
            "special_value_review_events",
            "special_value_review_event_id",
            "created_at",
            "event_type",
            "actor_user_id",
            project_column="project_id",
            entity_type_column=None,
            entity_id_column="special_value_review_id",
        ),
    ),
    relationships=(
        RelationshipSpec(
            "dataset_to_project",
            "datasets",
            "projects",
            ("project_id",),
            ("project_id",),
            scope_keys=("project_id", "dataset_id"),
        ),
        RelationshipSpec(
            "run_record_to_project",
            "run_records",
            "projects",
            ("project_id",),
            ("project_id",),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
        ),
        RelationshipSpec(
            "version_to_dataset",
            "dataset_versions",
            "datasets",
            ("dataset_id",),
            ("dataset_id",),
            scope_keys=("dataset_id", "dataset_version_id"),
        ),
        RelationshipSpec(
            "link_to_project",
            "project_dataset_links",
            "projects",
            ("project_id",),
            ("project_id",),
            scope_keys=("project_id", "dataset_id"),
        ),
        RelationshipSpec(
            "active_version_to_link",
            "active_modeling_dataset_versions",
            "project_dataset_links",
            ("project_id", "dataset_id"),
            ("project_id", "dataset_id"),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
        ),
        RelationshipSpec(
            "partition_to_project",
            "analysis_partitions",
            "projects",
            ("project_id",),
            ("project_id",),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
        ),
        RelationshipSpec(
            "partition_to_predictor_authorization",
            "analysis_partitions",
            "predictor_authorization_manifests",
            ("predictor_authorization_id",),
            ("predictor_authorization_id",),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
        ),
        RelationshipSpec(
            "special_value_review_to_predictor_authorization",
            "special_value_reviews",
            "predictor_authorization_manifests",
            ("predictor_authorization_id",),
            ("predictor_authorization_id",),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
        ),
        RelationshipSpec(
            "candidate_decision_to_project",
            "candidate_selection_decisions",
            "projects",
            ("project_id",),
            ("project_id",),
            scope_keys=("project_id", "dataset_id", "dataset_version_id"),
        ),
    ),
    allowed_scope_keys=frozenset(
        {"project_id", "dataset_id", "dataset_version_id"}
    ),
)


_ATLAS_SECURITY = ProfileSpec(
    projections=(
        ProjectionSpec(
            "users",
            (
                "user_id",
                "role",
                "status",
                "created_at",
                "updated_at",
                "last_login_at",
                "failed_login_count",
                "locked_until",
            ),
            status_columns=("role", "status"),
            timestamp_columns=(
                "created_at",
                "updated_at",
                "last_login_at",
                "locked_until",
            ),
            required=True,
        ),
        ProjectionSpec(
            "project_access",
            (
                "project_id",
                "user_id",
                "permission",
                "granted_by_user_id",
                "granted_at",
            ),
            status_columns=("permission",),
            timestamp_columns=("granted_at",),
            required=True,
        ),
        ProjectionSpec(
            "sessions",
            (
                "session_id",
                "user_id",
                "created_at",
                "expires_at",
                "last_seen_at",
                "revoked_at",
            ),
            timestamp_columns=(
                "created_at",
                "expires_at",
                "last_seen_at",
                "revoked_at",
            ),
            null_state_columns=(("revoked_at", "not_revoked", "revoked"),),
            required=True,
        ),
    ),
    audits=(
        AuditSpec(
            "audit_events",
            "audit_id",
            "timestamp",
            "action",
            "user_id",
            project_column=None,
            entity_type_column="resource_type",
            entity_id_column="resource_id",
            status_column="outcome",
            required=True,
        ),
    ),
    relationships=(
        RelationshipSpec(
            "project_access_to_user",
            "project_access",
            "users",
            ("user_id",),
            ("user_id",),
        ),
        RelationshipSpec(
            "session_to_user",
            "sessions",
            "users",
            ("user_id",),
            ("user_id",),
        ),
    ),
    allowed_scope_keys=frozenset(),
)


_BUREAU_CATALOG = ProfileSpec(
    projections=(
        ProjectionSpec(
            "catalog_registry_metadata",
            ("schema_version", "created_at"),
            timestamp_columns=("created_at",),
            required=True,
        ),
        ProjectionSpec(
            "bureau_catalog_versions",
            (
                "catalog_version_id",
                "catalog_id",
                "provider_id",
                "product_id",
                "edition",
                "country_or_region",
                "source_release_version",
                "source_checksum",
                "normalized_catalog_checksum",
                "record_count",
                "special_value_definition_count",
                "parser_build_version",
                "schema_version",
                "installation_status",
                "integrity_status",
                "entitlement_classification",
                "created_by",
                "created_at",
                "updated_at",
                "supersession_status",
                "retired_status",
                "registry_revision",
            ),
            status_columns=(
                "installation_status",
                "integrity_status",
                "entitlement_classification",
                "supersession_status",
                "retired_status",
            ),
            revision_columns=("registry_revision",),
            checksum_columns=("source_checksum", "normalized_catalog_checksum"),
            timestamp_columns=("created_at", "updated_at"),
            required=True,
        ),
        ProjectionSpec(
            "bureau_catalog_entitlements",
            (
                "entitlement_id",
                "principal_id",
                "tenant_id",
                "catalog_version_id",
                "catalog_checksum",
                "status",
                "expires_at",
                "granted_by",
                "granted_at",
                "revoked_by",
                "revoked_at",
            ),
            status_columns=("status",),
            checksum_columns=("catalog_checksum",),
            timestamp_columns=("expires_at", "granted_at", "revoked_at"),
            required=True,
        ),
    ),
    audits=(
        AuditSpec(
            "bureau_catalog_access_audit",
            "audit_id",
            "server_timestamp",
            "action",
            "actor",
            project_column="project_id",
            entity_type_column=None,
            entity_id_column="catalog_version_id",
            status_column="result_status",
            required=True,
        ),
    ),
    relationships=(
        RelationshipSpec(
            "entitlement_to_catalog_version",
            "bureau_catalog_entitlements",
            "bureau_catalog_versions",
            ("catalog_version_id",),
            ("catalog_version_id",),
        ),
    ),
    allowed_scope_keys=frozenset({"catalog_version_id"}),
)


_BUREAU_CROSSWALK_GOVERNANCE = ProfileSpec(
    projections=(
        ProjectionSpec(
            "bureau_crosswalk_revisions",
            (
                "governance_id",
                "revision",
                "revision_json",
                "revision_checksum",
                "previous_revision_checksum",
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "catalog_checksum",
                "created_at",
            ),
            scope_keys=(
                "governance_id",
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "catalog_checksum",
            ),
            revision_columns=("revision",),
            checksum_columns=(
                "revision_checksum",
                "previous_revision_checksum",
                "catalog_checksum",
            ),
            timestamp_columns=("created_at",),
            required=True,
        ),
        ProjectionSpec(
            "bureau_crosswalk_heads",
            ("governance_id", "current_revision", "current_checksum"),
            scope_keys=("governance_id",),
            revision_columns=("current_revision",),
            checksum_columns=("current_checksum",),
            required=True,
        ),
    ),
    audits=(),
    relationships=(
        RelationshipSpec(
            "crosswalk_head_to_current_revision",
            "bureau_crosswalk_heads",
            "bureau_crosswalk_revisions",
            ("governance_id", "current_revision"),
            ("governance_id", "revision"),
            scope_keys=("governance_id",),
        ),
    ),
    allowed_scope_keys=frozenset(
        {
            "governance_id",
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "catalog_checksum",
        }
    ),
)


_PROFILES: Mapping[str, ProfileSpec] = {
    "atlas_primary": _ATLAS_PRIMARY,
    "atlas_security": _ATLAS_SECURITY,
    "bureau_catalog_registry": _BUREAU_CATALOG,
    "bureau_crosswalk_governance": _BUREAU_CROSSWALK_GOVERNANCE,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size


def _read_json(path: Path, *, max_bytes: int) -> Mapping[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ProtectedAuthorityError("Required input is unavailable.") from exc
    if size > max_bytes:
        raise ProtectedAuthorityError("Required input exceeds the safe size limit.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProtectedAuthorityError("Required input is not valid safe JSON.") from exc
    if not isinstance(value, Mapping):
        raise ProtectedAuthorityError("Required input must be a JSON object.")
    return value


def _required_id(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not _AUTHORITY_ID_RE.fullmatch(text):
        raise ProtectedAuthorityError(f"{field} is invalid.")
    return text


def _required_path(value: object) -> Path:
    text = str(value or "").strip()
    if not text or len(text) > 4096:
        raise ProtectedAuthorityError("Authority path is invalid.")
    return Path(text).expanduser().resolve(strict=False)


def _safe_label(value: object) -> str:
    text = "null" if value is None else str(value).strip()
    if _PUBLIC_LABEL_RE.fullmatch(text):
        return text
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _safe_public_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if _PUBLIC_ID_RE.fullmatch(text):
        return text
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]}"


def _safe_timestamp(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if _TIMESTAMP_RE.fullmatch(text):
        return text
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]}"


def _normal(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value == float("inf"):
            return "infinity"
        if value == float("-inf"):
            return "-infinity"
        return value
    if isinstance(value, bytes):
        return {"byte_length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    return str(value)


def _quoted(identifier: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ProtectedAuthorityError("Internal projection identifier is invalid.")
    return f'"{identifier}"'


def _table_names(connection: sqlite3.Connection) -> frozenset[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


def _table_columns(connection: sqlite3.Connection, table: str) -> frozenset[str]:
    return frozenset(
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({_quoted(table)})").fetchall()
    )


def _scope_predicate(
    *,
    columns: frozenset[str],
    scope_keys: Sequence[str],
    scope: Mapping[str, str],
    alias: str | None = None,
) -> tuple[str, tuple[str, ...]]:
    prefix = f"{_quoted(alias)}." if alias else ""
    selected = [key for key in scope_keys if key in columns and key in scope]
    if not selected:
        return "", ()
    sql = " WHERE " + " AND ".join(
        f"{prefix}{_quoted(key)} = ?" for key in selected
    )
    return sql, tuple(scope[key] for key in selected)


def _counter_output(counter: Counter[str]) -> Mapping[str, int]:
    return {key: int(counter[key]) for key in sorted(counter)}


def _numeric_stats(values: Iterable[object]) -> Mapping[str, object]:
    numbers: list[float | int] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            numbers.append(int(value))
        elif isinstance(value, (int, float)):
            numbers.append(value)
        else:
            try:
                numbers.append(float(str(value)))
            except ValueError:
                continue
    return {
        "non_null": len(numbers),
        "distinct": len(set(numbers)),
        "minimum": min(numbers) if numbers else None,
        "maximum": max(numbers) if numbers else None,
    }


def _timestamp_stats(values: Iterable[object]) -> Mapping[str, object]:
    safe = sorted(
        timestamp
        for value in values
        if (timestamp := _safe_timestamp(value)) is not None
    )
    return {
        "non_null": len(safe),
        "minimum": safe[0] if safe else None,
        "maximum": safe[-1] if safe else None,
    }


def _checksum_stats(values: Iterable[object]) -> Mapping[str, object]:
    normalized = sorted(str(value).lower() for value in values if value is not None)
    return {
        "non_null": len(normalized),
        "distinct": len(set(normalized)),
        "valid_sha256": sum(1 for value in normalized if _SHA256_RE.fullmatch(value)),
        "set_digest": _digest(sorted(set(normalized))),
    }


def _capture_projection(
    connection: sqlite3.Connection,
    spec: ProjectionSpec,
    *,
    scope: Mapping[str, str],
    tables: frozenset[str],
) -> Mapping[str, object]:
    if spec.table not in tables:
        return {"available": False, "required": spec.required}
    table_columns = _table_columns(connection, spec.table)
    selected = tuple(column for column in spec.safe_columns if column in table_columns)
    if not selected:
        return {
            "available": False,
            "required": spec.required,
            "safe_projection_unavailable": True,
        }
    predicate, parameters = _scope_predicate(
        columns=table_columns,
        scope_keys=spec.scope_keys,
        scope=scope,
    )
    query = (
        "SELECT "
        + ", ".join(_quoted(column) for column in selected)
        + f" FROM {_quoted(spec.table)}"
        + predicate
    )
    row_hashes: list[str] = []
    status_counts: dict[str, Counter[str]] = {
        column: Counter() for column in spec.status_columns if column in selected
    }
    revision_values: dict[str, list[object]] = {
        column: [] for column in spec.revision_columns if column in selected
    }
    timestamp_values: dict[str, list[object]] = {
        column: [] for column in spec.timestamp_columns if column in selected
    }
    checksum_values: dict[str, list[object]] = {
        column: [] for column in spec.checksum_columns if column in selected
    }
    null_state_counts: dict[str, Counter[str]] = {
        column: Counter()
        for column, _null_label, _present_label in spec.null_state_columns
        if column in selected
    }
    row_count = 0
    with closing(connection.execute(query, parameters)) as cursor:
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                normalized = [_normal(value) for value in row]
                row_hashes.append(_digest(normalized))
                row_count += 1
                indexed = dict(zip(selected, row))
                for column, counter in status_counts.items():
                    counter[_safe_label(indexed[column])] += 1
                for column, values in revision_values.items():
                    values.append(indexed[column])
                for column, values in timestamp_values.items():
                    values.append(indexed[column])
                for column, values in checksum_values.items():
                    values.append(indexed[column])
                for column, null_label, present_label in spec.null_state_columns:
                    if column in null_state_counts:
                        null_state_counts[column][
                            null_label if indexed[column] is None else present_label
                        ] += 1
    return {
        "available": True,
        "required": spec.required,
        "selected_columns": list(selected),
        "selected_columns_digest": _digest(selected),
        "scope_applied": bool(predicate),
        "row_count": row_count,
        "row_digest": _digest(sorted(row_hashes)),
        "status_counts": {
            column: _counter_output(counter)
            for column, counter in sorted(status_counts.items())
        },
        "derived_status_counts": {
            column: _counter_output(counter)
            for column, counter in sorted(null_state_counts.items())
        },
        "revision_stats": {
            column: _numeric_stats(values)
            for column, values in sorted(revision_values.items())
        },
        "checksum_stats": {
            column: _checksum_stats(values)
            for column, values in sorted(checksum_values.items())
        },
        "timestamp_stats": {
            column: _timestamp_stats(values)
            for column, values in sorted(timestamp_values.items())
        },
    }


def _actor_classification(
    actor: object,
    *,
    user_roles: Mapping[str, str],
) -> str:
    if actor is None or not str(actor).strip():
        return "anonymous"
    text = str(actor).strip()
    if text in user_roles:
        return f"role:{_safe_label(user_roles[text])}"
    lowered = text.casefold()
    if any(
        marker in lowered
        for marker in ("system", "service", "scheduler", "migration", "internal")
    ):
        return "system_or_service"
    return "registered_or_external"


def _security_user_roles(
    connection: sqlite3.Connection, *, tables: frozenset[str]
) -> Mapping[str, str]:
    if "users" not in tables:
        return {}
    columns = _table_columns(connection, "users")
    if not {"user_id", "role"}.issubset(columns):
        return {}
    return {
        str(row[0]): str(row[1])
        for row in connection.execute("SELECT user_id, role FROM users").fetchall()
    }


def _capture_audit(
    connection: sqlite3.Connection,
    spec: AuditSpec,
    *,
    tables: frozenset[str],
    scope: Mapping[str, str],
    user_roles: Mapping[str, str],
) -> Mapping[str, object]:
    if spec.table not in tables:
        return {"available": False, "required": spec.required}
    columns = _table_columns(connection, spec.table)
    requested = [
        spec.id_column,
        spec.timestamp_column,
        spec.action_column,
        spec.actor_column,
        spec.project_column,
        spec.entity_type_column,
        spec.entity_id_column,
        spec.status_column,
    ]
    selected = tuple(column for column in requested if column and column in columns)
    mandatory = {
        spec.id_column,
        spec.timestamp_column,
        spec.action_column,
        spec.actor_column,
    }
    if not mandatory.issubset(selected):
        return {
            "available": False,
            "required": spec.required,
            "safe_projection_unavailable": True,
        }
    query = (
        "SELECT "
        + ", ".join(_quoted(column) for column in selected)
        + f" FROM {_quoted(spec.table)}"
    )
    row_hashes: list[str] = []
    actor_binding_hashes: list[str] = []
    entity_binding_hashes: list[str] = []
    action_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    actor_counts: Counter[str] = Counter()
    binding_counts: Counter[str] = Counter()
    raw_ids: list[str] = []
    safe_timestamps: list[str] = []
    total = 0
    with closing(connection.execute(query)) as cursor:
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                indexed = dict(zip(selected, row))
                normalized = [_normal(indexed[column]) for column in selected]
                row_hashes.append(_digest(normalized))
                total += 1
                audit_id = indexed[spec.id_column]
                timestamp = indexed[spec.timestamp_column]
                raw_ids.append(str(audit_id))
                safe_timestamp = _safe_timestamp(timestamp)
                if safe_timestamp is not None:
                    safe_timestamps.append(safe_timestamp)
                action_counts[_safe_label(indexed[spec.action_column])] += 1
                if spec.status_column and spec.status_column in indexed:
                    status_counts[_safe_label(indexed[spec.status_column])] += 1
                actor_class = _actor_classification(
                    indexed[spec.actor_column], user_roles=user_roles
                )
                actor_counts[actor_class] += 1
                actor_binding_hashes.append(
                    _digest([indexed[spec.actor_column], actor_class])
                )
                project = (
                    indexed.get(spec.project_column) if spec.project_column else None
                )
                entity_type = (
                    indexed.get(spec.entity_type_column)
                    if spec.entity_type_column
                    else None
                )
                entity_id = (
                    indexed.get(spec.entity_id_column) if spec.entity_id_column else None
                )
                project_bound = project is not None and bool(str(project).strip())
                entity_bound = entity_id is not None and bool(str(entity_id).strip())
                binding_counts[
                    "project_bound" if project_bound else "project_unbound"
                ] += 1
                binding_counts[
                    "entity_bound" if entity_bound else "entity_unbound"
                ] += 1
                if project_bound and scope.get("project_id") == str(project):
                    binding_counts["scope_project_bound"] += 1
                entity_binding_hashes.append(
                    _digest([project, entity_type, entity_id])
                )
    return {
        "available": True,
        "required": spec.required,
        "total_rows": total,
        "max_id": _safe_public_id(max(raw_ids)) if raw_ids else None,
        "max_server_timestamp": max(safe_timestamps) if safe_timestamps else None,
        "row_digest": _digest(sorted(row_hashes)),
        "action_counts": _counter_output(action_counts),
        "status_counts": _counter_output(status_counts),
        "actor_classification": _counter_output(actor_counts),
        "binding_counts": _counter_output(binding_counts),
        "actor_binding_digest": _digest(sorted(actor_binding_hashes)),
        "entity_binding_digest": _digest(sorted(entity_binding_hashes)),
    }


def _capture_relationship(
    connection: sqlite3.Connection,
    spec: RelationshipSpec,
    *,
    tables: frozenset[str],
    scope: Mapping[str, str],
) -> Mapping[str, object]:
    if spec.child_table not in tables or spec.parent_table not in tables:
        return {"available": False}
    child_columns = _table_columns(connection, spec.child_table)
    parent_columns = _table_columns(connection, spec.parent_table)
    if not set(spec.child_columns).issubset(child_columns) or not set(
        spec.parent_columns
    ).issubset(parent_columns):
        return {"available": False, "safe_projection_unavailable": True}
    join = " AND ".join(
        f'c.{_quoted(child)} = p.{_quoted(parent)}'
        for child, parent in zip(spec.child_columns, spec.parent_columns)
    )
    predicate, parameters = _scope_predicate(
        columns=child_columns,
        scope_keys=spec.scope_keys,
        scope=scope,
        alias="c",
    )
    child_select = ", ".join(f'c.{_quoted(column)}' for column in spec.child_columns)
    parent_probe = f'p.{_quoted(spec.parent_columns[0])}'
    query = (
        f"SELECT {child_select}, {parent_probe} IS NOT NULL AS parent_present "
        f"FROM {_quoted(spec.child_table)} AS c "
        f"LEFT JOIN {_quoted(spec.parent_table)} AS p ON {join}{predicate}"
    )
    relationship_hashes: list[str] = []
    child_rows = 0
    matched_rows = 0
    with closing(connection.execute(query, parameters)) as cursor:
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                child_rows += 1
                present = bool(row[-1])
                matched_rows += int(present)
                relationship_hashes.append(
                    _digest([*(_normal(value) for value in row[:-1]), present])
                )
    return {
        "available": True,
        "scope_applied": bool(predicate),
        "child_rows": child_rows,
        "matched_rows": matched_rows,
        "orphan_rows": child_rows - matched_rows,
        "relationship_digest": _digest(sorted(relationship_hashes)),
    }


def _capture_foreign_key_schema(
    connection: sqlite3.Connection, *, tables: frozenset[str]
) -> Mapping[str, object]:
    relationships: list[list[object]] = []
    for table in sorted(tables):
        if not _IDENTIFIER_RE.fullmatch(table):
            continue
        for row in connection.execute(f"PRAGMA foreign_key_list({_quoted(table)})"):
            relationships.append(
                [
                    table,
                    _safe_label(row[2]),
                    _safe_label(row[3]),
                    _safe_label(row[4]),
                    _safe_label(row[5]),
                    _safe_label(row[6]),
                    _safe_label(row[7]),
                ]
            )
    relationships.sort(key=lambda row: _canonical_bytes(row))
    return {
        "relationship_count": len(relationships),
        "relationship_digest": _digest(relationships),
    }


def _open_read_only(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    connection.execute("PRAGMA temp_store = MEMORY")
    return connection


def _capture_database(
    *,
    authority_id: str,
    path: Path,
    profile_name: str,
    scope: Mapping[str, str],
    required: bool,
) -> Mapping[str, object]:
    path_fingerprint = hashlib.sha256(str(path).casefold().encode("utf-8")).hexdigest()
    base: dict[str, object] = {
        "authority_id": authority_id,
        "profile": profile_name,
        "required": required,
        "path_fingerprint": path_fingerprint,
        "scope_digest": _digest(scope),
    }
    if not path.is_file():
        return {**base, "available": False, "capture_error": "database_unavailable"}
    whole_file: dict[str, object] = {
        "available": False,
        "comparison_policy": "supplementary",
        "scope": "main_database_file_only",
    }
    try:
        file_hash, file_size = _file_sha256(path)
        whole_file.update(
            {"available": True, "sha256": file_hash, "size_bytes": file_size}
        )
    except OSError:
        whole_file["capture_error"] = "file_read_failed"
    try:
        profile = _PROFILES[profile_name]
        with closing(_open_read_only(path)) as connection:
            connection.execute("BEGIN")
            tables = _table_names(connection)
            projections = {
                spec.table: _capture_projection(
                    connection, spec, scope=scope, tables=tables
                )
                for spec in profile.projections
            }
            user_roles = (
                _security_user_roles(connection, tables=tables)
                if profile_name == "atlas_security"
                else {}
            )
            audits = {
                spec.table: _capture_audit(
                    connection,
                    spec,
                    tables=tables,
                    scope=scope,
                    user_roles=user_roles,
                )
                for spec in profile.audits
            }
            relationships = {
                spec.name: _capture_relationship(
                    connection, spec, tables=tables, scope=scope
                )
                for spec in profile.relationships
            }
            foreign_keys = _capture_foreign_key_schema(connection, tables=tables)
            connection.rollback()
    except (OSError, sqlite3.Error, ProtectedAuthorityError) as exc:
        return {
            **base,
            "available": False,
            "capture_error": "read_only_capture_failed",
            "error_class": type(exc).__name__,
        }
    required_tables_ok = all(
        bool(value.get("available"))
        for value in (*projections.values(), *audits.values())
        if bool(value.get("required"))
    )
    integrity_ok = all(
        not value.get("available") or int(value.get("orphan_rows", 0)) == 0
        for value in relationships.values()
    )
    logical_payload = {
        "projections": projections,
        "relationships": relationships,
        "foreign_key_schema": foreign_keys,
    }
    audit_total = sum(
        int(value.get("total_rows", 0))
        for value in audits.values()
        if value.get("available")
    )
    return {
        **base,
        "available": True,
        "required_tables_ok": required_tables_ok,
        "integrity_ok": integrity_ok,
        "whole_file": whole_file,
        "logical": {
            **logical_payload,
            "digest": _digest(logical_payload),
        },
        "audit": {
            "tables": audits,
            "total_rows": audit_total,
            "digest": _digest(audits),
        },
    }


def _validate_manifest(manifest: Mapping[str, Any]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if manifest.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ProtectedAuthorityError("Manifest schema version is unsupported.")
    immutable_raw = manifest.get("immutable_files", [])
    databases_raw = manifest.get("sqlite_authorities", [])
    if not isinstance(immutable_raw, list) or not isinstance(databases_raw, list):
        raise ProtectedAuthorityError("Manifest authority collections are invalid.")
    immutable: list[dict[str, object]] = []
    databases: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in immutable_raw:
        if not isinstance(raw, Mapping):
            raise ProtectedAuthorityError("Immutable authority entry is invalid.")
        authority_id = _required_id(raw.get("authority_id"), field="authority_id")
        if authority_id in seen:
            raise ProtectedAuthorityError("Authority identifiers must be unique.")
        seen.add(authority_id)
        immutable.append(
            {
                "authority_id": authority_id,
                "path": _required_path(raw.get("path")),
                "required": bool(raw.get("required", True)),
            }
        )
    for raw in databases_raw:
        if not isinstance(raw, Mapping):
            raise ProtectedAuthorityError("SQLite authority entry is invalid.")
        authority_id = _required_id(raw.get("authority_id"), field="authority_id")
        if authority_id in seen:
            raise ProtectedAuthorityError("Authority identifiers must be unique.")
        seen.add(authority_id)
        profile_name = str(raw.get("profile") or "").strip()
        if profile_name not in _PROFILES:
            raise ProtectedAuthorityError("SQLite authority profile is unsupported.")
        scope_raw = raw.get("scope", {})
        if not isinstance(scope_raw, Mapping):
            raise ProtectedAuthorityError("SQLite authority scope is invalid.")
        profile = _PROFILES[profile_name]
        extra = set(str(key) for key in scope_raw) - profile.allowed_scope_keys
        if extra:
            raise ProtectedAuthorityError("SQLite authority scope is unsupported.")
        scope: dict[str, str] = {}
        for key, value in scope_raw.items():
            text = str(value or "").strip()
            if not text or len(text) > _MAX_IDENTITY_LENGTH:
                raise ProtectedAuthorityError("SQLite authority scope is invalid.")
            scope[str(key)] = text
        databases.append(
            {
                "authority_id": authority_id,
                "path": _required_path(raw.get("path")),
                "profile": profile_name,
                "scope": scope,
                "required": bool(raw.get("required", True)),
            }
        )
    if not immutable and not databases:
        raise ProtectedAuthorityError("Manifest contains no protected authorities.")
    return immutable, databases


def capture_snapshot(manifest: Mapping[str, Any]) -> Mapping[str, object]:
    """Capture one layered snapshot without mutating any authority."""

    immutable_specs, database_specs = _validate_manifest(manifest)
    immutable_results: dict[str, Mapping[str, object]] = {}
    for spec in immutable_specs:
        authority_id = str(spec["authority_id"])
        path = spec["path"]
        assert isinstance(path, Path)
        required = bool(spec["required"])
        path_fingerprint = hashlib.sha256(
            str(path).casefold().encode("utf-8")
        ).hexdigest()
        if not path.is_file():
            immutable_results[authority_id] = {
                "authority_id": authority_id,
                "required": required,
                "available": False,
                "path_fingerprint": path_fingerprint,
            }
            continue
        try:
            sha256, size = _file_sha256(path)
        except OSError:
            immutable_results[authority_id] = {
                "authority_id": authority_id,
                "required": required,
                "available": False,
                "path_fingerprint": path_fingerprint,
                "capture_error": "file_read_failed",
            }
            continue
        immutable_results[authority_id] = {
            "authority_id": authority_id,
            "required": required,
            "available": True,
            "path_fingerprint": path_fingerprint,
            "sha256": sha256,
            "size_bytes": size,
        }
    database_results = {
        str(spec["authority_id"]): _capture_database(
            authority_id=str(spec["authority_id"]),
            path=spec["path"],  # type: ignore[arg-type]
            profile_name=str(spec["profile"]),
            scope=spec["scope"],  # type: ignore[arg-type]
            required=bool(spec["required"]),
        )
        for spec in database_specs
    }
    required_files_ok = all(
        bool(value.get("available"))
        for value in immutable_results.values()
        if value.get("required")
    )
    required_databases_ok = all(
        bool(value.get("available")) and bool(value.get("required_tables_ok"))
        for value in database_results.values()
        if value.get("required")
    )
    manifest_identity = {
        "immutable": [
            {
                "authority_id": str(spec["authority_id"]),
                "path_fingerprint": hashlib.sha256(
                    str(spec["path"]).casefold().encode("utf-8")
                ).hexdigest(),
                "required": bool(spec["required"]),
            }
            for spec in immutable_specs
        ],
        "sqlite": [
            {
                "authority_id": str(spec["authority_id"]),
                "path_fingerprint": hashlib.sha256(
                    str(spec["path"]).casefold().encode("utf-8")
                ).hexdigest(),
                "profile": str(spec["profile"]),
                "scope_digest": _digest(spec["scope"]),
                "required": bool(spec["required"]),
            }
            for spec in database_specs
        ],
    }
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "captured_at": _utc_now(),
        "capture_mode": "read_only_layered_authority",
        "manifest_digest": _digest(manifest_identity),
        "capture_complete": required_files_ok and required_databases_ok,
        "safety_contract": dict(_SAFETY_CONTRACT),
        "immutable_files": immutable_results,
        "sqlite_authorities": database_results,
    }


def _change(
    changes: list[dict[str, object]],
    *,
    code: str,
    authority_id: str | None = None,
    table: str | None = None,
) -> None:
    item: dict[str, object] = {"code": code}
    if authority_id is not None:
        item["authority_id"] = authority_id
    if table is not None:
        item["table"] = table
    changes.append(item)


def compare_snapshots(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> Mapping[str, object]:
    """Compare two snapshots and fail on authoritative or audit changes."""

    authoritative: list[dict[str, object]] = []
    supplementary: list[dict[str, object]] = []
    baseline_warnings: list[dict[str, object]] = []
    if (
        before.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
        or after.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
    ):
        _change(authoritative, code="snapshot_schema_mismatch")
    if before.get("manifest_digest") != after.get("manifest_digest"):
        _change(authoritative, code="manifest_identity_changed")
    if before.get("safety_contract") != _SAFETY_CONTRACT:
        _change(authoritative, code="baseline_safety_contract_invalid")
    if after.get("safety_contract") != _SAFETY_CONTRACT:
        _change(authoritative, code="current_safety_contract_invalid")
    if not bool(before.get("capture_complete")):
        _change(authoritative, code="baseline_capture_incomplete")
    if not bool(after.get("capture_complete")):
        _change(authoritative, code="current_capture_incomplete")

    before_files = before.get("immutable_files", {})
    after_files = after.get("immutable_files", {})
    if not isinstance(before_files, Mapping) or not isinstance(after_files, Mapping):
        _change(authoritative, code="immutable_snapshot_invalid")
        before_files, after_files = {}, {}
    for authority_id in sorted(set(before_files) | set(after_files)):
        old = before_files.get(authority_id)
        new = after_files.get(authority_id)
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            _change(
                authoritative,
                code="immutable_authority_set_changed",
                authority_id=str(authority_id),
            )
            continue
        if old.get("path_fingerprint") != new.get("path_fingerprint"):
            _change(
                authoritative,
                code="immutable_authority_path_changed",
                authority_id=str(authority_id),
            )
        if old.get("available") != new.get("available"):
            _change(
                authoritative,
                code="immutable_authority_availability_changed",
                authority_id=str(authority_id),
            )
        if old.get("sha256") != new.get("sha256") or old.get("size_bytes") != new.get(
            "size_bytes"
        ):
            _change(
                authoritative,
                code="immutable_file_changed",
                authority_id=str(authority_id),
            )

    before_databases = before.get("sqlite_authorities", {})
    after_databases = after.get("sqlite_authorities", {})
    if not isinstance(before_databases, Mapping) or not isinstance(
        after_databases, Mapping
    ):
        _change(authoritative, code="sqlite_snapshot_invalid")
        before_databases, after_databases = {}, {}
    for authority_id in sorted(set(before_databases) | set(after_databases)):
        old = before_databases.get(authority_id)
        new = after_databases.get(authority_id)
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            _change(
                authoritative,
                code="sqlite_authority_set_changed",
                authority_id=str(authority_id),
            )
            continue
        for field in ("profile", "path_fingerprint", "scope_digest"):
            if old.get(field) != new.get(field):
                _change(
                    authoritative,
                    code=f"sqlite_{field}_changed",
                    authority_id=str(authority_id),
                )
        old_available = bool(old.get("available"))
        new_available = bool(new.get("available"))
        if old_available != new_available:
            _change(
                authoritative,
                code="sqlite_authority_availability_changed",
                authority_id=str(authority_id),
            )
        required_authority = bool(new.get("required", old.get("required", False)))
        if not new_available:
            if required_authority:
                _change(
                    authoritative,
                    code="required_sqlite_authority_unavailable",
                    authority_id=str(authority_id),
                )
            elif not old_available:
                baseline_warnings.append(
                    {
                        "code": "optional_sqlite_authority_unavailable",
                        "authority_id": str(authority_id),
                    }
                )
            continue
        if not bool(new.get("required_tables_ok", False)):
            _change(
                authoritative,
                code="required_projection_unavailable",
                authority_id=str(authority_id),
            )
        if bool(old.get("integrity_ok", False)) and not bool(
            new.get("integrity_ok", False)
        ):
            _change(
                authoritative,
                code="relationship_integrity_regressed",
                authority_id=str(authority_id),
            )
        old_logical = old.get("logical")
        new_logical = new.get("logical")
        if not isinstance(old_logical, Mapping) or not isinstance(new_logical, Mapping):
            _change(
                authoritative,
                code="logical_projection_unavailable",
                authority_id=str(authority_id),
            )
        elif old_logical.get("digest") != new_logical.get("digest"):
            _change(
                authoritative,
                code="critical_logical_authority_changed",
                authority_id=str(authority_id),
            )
            old_projections = old_logical.get("projections", {})
            new_projections = new_logical.get("projections", {})
            if isinstance(old_projections, Mapping) and isinstance(
                new_projections, Mapping
            ):
                for table in sorted(set(old_projections) | set(new_projections)):
                    if old_projections.get(table) != new_projections.get(table):
                        _change(
                            authoritative,
                            code="critical_projection_changed",
                            authority_id=str(authority_id),
                            table=str(table),
                        )
            old_relationships = old_logical.get("relationships", {})
            new_relationships = new_logical.get("relationships", {})
            if isinstance(old_relationships, Mapping) and isinstance(
                new_relationships, Mapping
            ):
                for relationship in sorted(
                    set(old_relationships) | set(new_relationships)
                ):
                    if old_relationships.get(relationship) != new_relationships.get(
                        relationship
                    ):
                        _change(
                            authoritative,
                            code="critical_relationship_changed",
                            authority_id=str(authority_id),
                            table=str(relationship),
                        )
            if old_logical.get("foreign_key_schema") != new_logical.get(
                "foreign_key_schema"
            ):
                _change(
                    authoritative,
                    code="foreign_key_schema_changed",
                    authority_id=str(authority_id),
                )

        if isinstance(old_logical, Mapping) and isinstance(new_logical, Mapping):
            old_relationships = old_logical.get("relationships", {})
            new_relationships = new_logical.get("relationships", {})
            if isinstance(old_relationships, Mapping) and isinstance(
                new_relationships, Mapping
            ):
                for relationship in sorted(
                    set(old_relationships) | set(new_relationships)
                ):
                    old_relationship = old_relationships.get(relationship)
                    new_relationship = new_relationships.get(relationship)
                    if not isinstance(old_relationship, Mapping) or not isinstance(
                        new_relationship, Mapping
                    ):
                        continue
                    old_orphans = int(old_relationship.get("orphan_rows", 0))
                    new_orphans = int(new_relationship.get("orphan_rows", 0))
                    if old_relationship != new_relationship:
                        _change(
                            authoritative,
                            code="critical_relationship_changed",
                            authority_id=str(authority_id),
                            table=str(relationship),
                        )
                    if new_orphans > old_orphans:
                        _change(
                            authoritative,
                            code="relationship_orphan_count_increased",
                            authority_id=str(authority_id),
                            table=str(relationship),
                        )
                    elif (
                        old_orphans > 0
                        and new_orphans == old_orphans
                        and old_relationship == new_relationship
                    ):
                        baseline_warnings.append(
                            {
                                "code": "preexisting_relationship_orphans",
                                "authority_id": str(authority_id),
                                "table": str(relationship),
                                "orphan_rows": old_orphans,
                            }
                        )

        old_audit = old.get("audit")
        new_audit = new.get("audit")
        if not isinstance(old_audit, Mapping) or not isinstance(new_audit, Mapping):
            _change(
                authoritative,
                code="audit_projection_unavailable",
                authority_id=str(authority_id),
            )
        else:
            old_tables = old_audit.get("tables", {})
            new_tables = new_audit.get("tables", {})
            if isinstance(old_tables, Mapping) and isinstance(new_tables, Mapping):
                for table in sorted(set(old_tables) | set(new_tables)):
                    old_table = old_tables.get(table)
                    new_table = new_tables.get(table)
                    if not isinstance(old_table, Mapping) or not isinstance(
                        new_table, Mapping
                    ):
                        _change(
                            authoritative,
                            code="audit_table_set_changed",
                            authority_id=str(authority_id),
                            table=str(table),
                        )
                        continue
                    old_total = int(old_table.get("total_rows", 0))
                    new_total = int(new_table.get("total_rows", 0))
                    if new_total > old_total:
                        _change(
                            authoritative,
                            code="new_live_audit_rows",
                            authority_id=str(authority_id),
                            table=str(table),
                        )
                    if old_table != new_table:
                        _change(
                            authoritative,
                            code="audit_semantics_changed",
                            authority_id=str(authority_id),
                            table=str(table),
                        )
            if old_audit.get("digest") != new_audit.get("digest"):
                _change(
                    authoritative,
                    code="audit_authority_changed",
                    authority_id=str(authority_id),
                )
        old_whole = old.get("whole_file")
        new_whole = new.get("whole_file")
        if isinstance(old_whole, Mapping) and isinstance(new_whole, Mapping):
            if old_whole.get("available") != new_whole.get("available"):
                _change(
                    supplementary,
                    code="sqlite_whole_file_availability_changed",
                    authority_id=str(authority_id),
                )
            elif bool(old_whole.get("available")) and (
                old_whole.get("sha256") != new_whole.get("sha256")
                or old_whole.get("size_bytes") != new_whole.get("size_bytes")
            ):
                _change(
                    supplementary,
                    code="sqlite_whole_file_changed",
                    authority_id=str(authority_id),
                )
    unique_authoritative = [
        dict(item)
        for item in {
            _canonical_bytes(item): item for item in authoritative
        }.values()
    ]
    unique_authoritative.sort(key=lambda item: _canonical_bytes(item))
    supplementary.sort(key=lambda item: _canonical_bytes(item))
    unique_warnings = [
        dict(item)
        for item in {
            _canonical_bytes(item): item for item in baseline_warnings
        }.values()
    ]
    unique_warnings.sort(key=lambda item: _canonical_bytes(item))
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "comparison_mode": "logical_and_audit_authoritative",
        "passed": not unique_authoritative,
        "authoritative_change_count": len(unique_authoritative),
        "authoritative_changes": unique_authoritative,
        "baseline_warning_count": len(unique_warnings),
        "baseline_warnings": unique_warnings,
        "supplementary_change_count": len(supplementary),
        "supplementary_changes": supplementary,
        "whole_sqlite_hash_authoritative": False,
    }


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.parent.is_dir():
        raise ProtectedAuthorityError("Output parent directory is unavailable.")
    try:
        with resolved.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
    except FileExistsError as exc:
        raise ProtectedAuthorityError("Output already exists; refusing overwrite.") from exc
    except OSError as exc:
        raise ProtectedAuthorityError("Output could not be written safely.") from exc


def _parser() -> argparse.ArgumentParser:
    parser = _RedactingArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--manifest", required=True)
    capture.add_argument("--output", required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)
    compare.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        output = _required_path(args.output)
        if args.command == "capture":
            manifest_path = _required_path(args.manifest)
            manifest = _read_json(manifest_path, max_bytes=_MAX_MANIFEST_BYTES)
            snapshot = capture_snapshot(manifest)
            _write_json_exclusive(output, snapshot)
            print(
                json.dumps(
                    {
                        "operation": "capture",
                        "capture_complete": snapshot["capture_complete"],
                        "immutable_authorities": len(snapshot["immutable_files"]),
                        "sqlite_authorities": len(snapshot["sqlite_authorities"]),
                    },
                    sort_keys=True,
                )
            )
            return 0 if snapshot["capture_complete"] else 2
        before_path = _required_path(args.before)
        after_path = _required_path(args.after)
        before = _read_json(before_path, max_bytes=_MAX_SNAPSHOT_BYTES)
        after = _read_json(after_path, max_bytes=_MAX_SNAPSHOT_BYTES)
        comparison = compare_snapshots(before, after)
        _write_json_exclusive(output, comparison)
        print(
            json.dumps(
                {
                    "operation": "compare",
                    "passed": comparison["passed"],
                    "authoritative_change_count": comparison[
                        "authoritative_change_count"
                    ],
                    "supplementary_change_count": comparison[
                        "supplementary_change_count"
                    ],
                },
                sort_keys=True,
            )
        )
        return 0 if comparison["passed"] else 3
    except ProtectedAuthorityError as exc:
        print(
            json.dumps(
                {"operation": "protected_authority", "ok": False, "error": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "operation": "protected_authority",
                    "ok": False,
                    "error": "Protected-authority operation failed safely.",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
