"""Read-only Dataset Library reconciliation and integrity reporting.

The scanner compares the JSON catalog, immutable version artifacts, optional
security-user evidence, and optional durable project link/activation rows.  It
never creates a store, repairs a record, writes an audit event, or promotes an
active selection.  Its output is intentionally machine-readable so the same
model can drive a maintenance CLI, a bounded startup check, and an admin-only
diagnostic endpoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from .dataset_storage import (
    DatasetLibraryStorage,
    DatasetStorageError,
    DatasetStoreMalformedError,
    DatasetStoreMissingError,
    read_json_strict,
    sha256_file,
)


class ReconciliationState(str, Enum):
    HEALTHY = "healthy"
    REGISTRY_WITHOUT_ARTIFACT = "registry_without_artifact"
    ARTIFACT_WITHOUT_REGISTRY = "artifact_without_registry"
    DATASET_WITHOUT_VERSION = "dataset_without_version"
    VERSION_WITHOUT_DATASET = "version_without_dataset"
    PROJECT_LINK_WITHOUT_DATASET = "project_link_without_dataset"
    PROJECT_LINK_WITHOUT_VERSION = "project_link_without_version"
    ACTIVE_SELECTION_WITHOUT_LINK = "active_selection_without_link"
    ACTIVE_SELECTION_WITHOUT_VERSION = "active_selection_without_version"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    SCHEMA_MISMATCH = "schema_mismatch"
    OWNERSHIP_UNRESOLVED = "ownership_unresolved"
    ACL_UNRESOLVED = "acl_unresolved"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    LEGACY_LINK_DIVERGENCE = "legacy_link_divergence"
    RECOVERY_JOURNAL_PENDING = "recovery_journal_pending"
    RECOVERABLE = "recoverable"
    RECOVERED = "recovered"
    QUARANTINED = "quarantined"


class EvidenceTier(str, Enum):
    AUTHORITATIVE = "tier_1_authoritative"
    STRONG_CORROBORATION = "tier_2_strong_corroboration"
    SUPPORTING_ONLY = "tier_3_supporting_only"


@dataclass(frozen=True)
class EvidenceSource:
    kind: str
    tier: EvidenceTier
    reference: str
    fields: tuple[str, ...] = ()
    sha256: str | None = None
    notes: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "tier": self.tier.value,
            "reference": self.reference,
            "fields": list(self.fields),
            "sha256": self.sha256,
            "notes": self.notes,
        }


@dataclass
class DatasetReconciliationRecord:
    dataset_id: str | None
    dataset_version_id: str | None
    artifact_path: str | None = None
    content_hash: str | None = None
    schema_hash: str | None = None
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    registry_state: Dict[str, Any] = field(default_factory=dict)
    artifact_state: Dict[str, Any] = field(default_factory=dict)
    owner_evidence: Dict[str, Any] = field(default_factory=dict)
    acl_evidence: Dict[str, Any] = field(default_factory=dict)
    project_link_evidence: List[Dict[str, Any]] = field(default_factory=list)
    active_selection_evidence: List[Dict[str, Any]] = field(default_factory=list)
    confidence_level: str = "low"
    evidence_sources: List[EvidenceSource] = field(default_factory=list)
    recovery_eligibility: bool = False
    blocking_reasons: List[str] = field(default_factory=list)
    states: List[ReconciliationState] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_state(self, state: ReconciliationState) -> None:
        if state not in self.states:
            self.states.append(state)

    def block(self, reason: str) -> None:
        normalized = str(reason or "").strip()
        if normalized and normalized not in self.blocking_reasons:
            self.blocking_reasons.append(normalized)

    def warn(self, message: str) -> None:
        normalized = str(message or "").strip()
        if normalized and normalized not in self.warnings:
            self.warnings.append(normalized)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version_id": self.dataset_version_id,
            "artifact_path": self.artifact_path,
            "content_hash": self.content_hash,
            "schema_hash": self.schema_hash,
            "source_metadata": self.source_metadata,
            "registry_state": self.registry_state,
            "artifact_state": self.artifact_state,
            "owner_evidence": self.owner_evidence,
            "acl_evidence": self.acl_evidence,
            "project_link_evidence": self.project_link_evidence,
            "active_selection_evidence": self.active_selection_evidence,
            "confidence_level": self.confidence_level,
            "evidence_sources": [item.to_dict() for item in self.evidence_sources],
            "recovery_eligibility": self.recovery_eligibility,
            "blocking_reasons": list(self.blocking_reasons),
            "states": [state.value for state in self.states],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ReconciliationLimits:
    max_registry_datasets: int = 10_000
    max_registry_versions: int = 50_000
    max_artifact_dataset_directories: int = 20_000
    max_artifact_version_directories: int = 100_000
    max_checksum_bytes: int = 20 * 1024 * 1024 * 1024
    max_registry_bytes: int = 64 * 1024 * 1024
    max_project_links_bytes: int = 16 * 1024 * 1024
    max_sidecar_bytes: int = 8 * 1024 * 1024
    max_entries_per_directory: int = 100_000


@dataclass
class DatasetLibraryReconciliationReport:
    generated_at: str
    configured_root_name: str
    records: List[DatasetReconciliationRecord] = field(default_factory=list)
    storage_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    scan_truncated: bool = False
    checksummed_bytes: int = 0
    registry_sha256: str | None = None
    project_links_sha256: str | None = None

    @property
    def state_counts(self) -> Dict[str, int]:
        counts = {state.value: 0 for state in ReconciliationState}
        for record in self.records:
            for state in record.states:
                counts[state.value] += 1
        return {key: value for key, value in counts.items() if value}

    @property
    def healthy(self) -> bool:
        unhealthy = {
            ReconciliationState.REGISTRY_WITHOUT_ARTIFACT,
            ReconciliationState.ARTIFACT_WITHOUT_REGISTRY,
            ReconciliationState.DATASET_WITHOUT_VERSION,
            ReconciliationState.VERSION_WITHOUT_DATASET,
            ReconciliationState.PROJECT_LINK_WITHOUT_DATASET,
            ReconciliationState.PROJECT_LINK_WITHOUT_VERSION,
            ReconciliationState.ACTIVE_SELECTION_WITHOUT_LINK,
            ReconciliationState.ACTIVE_SELECTION_WITHOUT_VERSION,
            ReconciliationState.CHECKSUM_MISMATCH,
            ReconciliationState.SCHEMA_MISMATCH,
            ReconciliationState.OWNERSHIP_UNRESOLVED,
            ReconciliationState.ACL_UNRESOLVED,
            ReconciliationState.AMBIGUOUS_IDENTITY,
            ReconciliationState.LEGACY_LINK_DIVERGENCE,
            ReconciliationState.RECOVERY_JOURNAL_PENDING,
            ReconciliationState.QUARANTINED,
        }
        return (
            not self.storage_errors
            and not self.scan_truncated
            and all(not unhealthy.intersection(record.states) for record in self.records)
        )

    def exact_record(
        self,
        dataset_id: str,
        dataset_version_id: str,
    ) -> DatasetReconciliationRecord | None:
        matches = [
            record
            for record in self.records
            if record.dataset_id == dataset_id
            and record.dataset_version_id == dataset_version_id
        ]
        return matches[0] if len(matches) == 1 else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "configured_root_name": self.configured_root_name,
            "healthy": self.healthy,
            "scan_truncated": self.scan_truncated,
            "checksummed_bytes": self.checksummed_bytes,
            "registry_sha256": self.registry_sha256,
            "project_links_sha256": self.project_links_sha256,
            "storage_errors": list(self.storage_errors),
            "warnings": list(self.warnings),
            "state_counts": self.state_counts,
            "record_count": len(self.records),
            "records": [record.to_dict() for record in self.records],
        }


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _safe_relative(path: Path, root: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return None


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            return bool(is_junction())
        except OSError:
            return True
    if os.name == "nt":
        try:
            attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        except OSError:
            return False
        return bool(
            attributes
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
        )
    return False


def _has_linked_component(path: Path, root: Path) -> bool:
    """Return True when a path beneath root traverses a filesystem link."""

    lexical_root = Path(os.path.abspath(str(root)))
    lexical_path = Path(os.path.abspath(str(path)))
    try:
        parts = lexical_path.relative_to(lexical_root).parts
    except ValueError:
        return True
    current = lexical_root
    for part in parts:
        current = current / part
        if _is_link_or_junction(current):
            return True
    return False


def _bounded_directory_listing(
    directory: Path,
    *,
    max_entries: int,
) -> tuple[List[Path], bool]:
    """List at most ``max_entries`` children and report truncation."""

    entries: List[Path] = []
    limit = max(1, int(max_entries))
    iterator = directory.iterdir()
    try:
        for entry in iterator:
            if len(entries) >= limit:
                return sorted(entries, key=lambda item: item.name), True
            entries.append(entry)
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()
    return sorted(entries, key=lambda item: item.name), False


def _canonical_schema_hash(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _public_source_metadata(dataset: Mapping[str, Any], version: Mapping[str, Any]) -> Dict[str, Any]:
    source_info = dataset.get("sourceInfo")
    source_info = source_info if isinstance(source_info, dict) else {}
    return {
        "source_type": dataset.get("sourceType"),
        "dataset_role": dataset.get("datasetRole"),
        "original_filename": version.get("originalFilename"),
        "created_at": version.get("createdAt"),
        "created_by": version.get("createdBy"),
        "target": dataset.get("target") or source_info.get("target"),
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _read_durable_state(
    database: Any,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], bool]:
    """Read SQLite authority through a read-only URI, never Database.connect()."""

    if database is None or not getattr(database, "path", None):
        return [], [], [], False
    path = Path(database.path).expanduser().resolve()
    if not path.exists():
        return (
            [],
            [],
            ["Durable persistence database was unavailable for reconciliation."],
            False,
        )
    warnings: List[str] = []
    links: List[Dict[str, Any]] = []
    selections: List[Dict[str, Any]] = []
    authority_tables_available = False
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            links_table_exists = _table_exists(connection, "project_dataset_links")
            selections_table_exists = _table_exists(
                connection,
                "active_modeling_dataset_versions",
            )
            authority_tables_available = (
                links_table_exists and selections_table_exists
            )
            if not authority_tables_available:
                warnings.append(
                    "Durable dataset authority tables were unavailable for reconciliation."
                )
            if links_table_exists:
                links = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM project_dataset_links ORDER BY project_id, dataset_id"
                    ).fetchall()
                ]
            if selections_table_exists:
                selections = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM active_modeling_dataset_versions ORDER BY project_id"
                    ).fetchall()
                ]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        warnings.append(
            "Durable dataset authority could not be read "
            f"({type(exc).__name__})."
        )
        authority_tables_available = False
    return links, selections, warnings, authority_tables_available


def _sidecar(
    path: Path,
    expected_key: str | None = None,
    *,
    max_bytes: int | None = None,
) -> Dict[str, Any] | None:
    try:
        payload = read_json_strict(
            path,
            expected_key,
            allow_missing=True,
            max_bytes=max_bytes,
        )
    except DatasetStorageError:
        return None
    return payload if isinstance(payload, dict) else None


def _validate_owner_acl(
    record: DatasetReconciliationRecord,
    dataset: Mapping[str, Any],
    user_resolver: Callable[[str], Mapping[str, Any] | None] | None,
) -> None:
    owner_id = _clean(dataset.get("ownerUserId"))
    owner_found: Optional[bool] = None
    owner_status = None
    if owner_id and user_resolver is not None:
        try:
            owner = user_resolver(owner_id)
        except Exception as exc:
            record.warn(
                "Owner directory lookup failed "
                f"({type(exc).__name__})."
            )
            owner = None
        owner_found = bool(owner)
        owner_status = (owner or {}).get("status") if isinstance(owner, Mapping) else None
    record.owner_evidence = {
        "owner_user_id": owner_id or None,
        "directory_checked": user_resolver is not None,
        "directory_record_exists": owner_found,
        "directory_status": owner_status,
    }
    if not owner_id or owner_found is False or (
        owner_status is not None and str(owner_status).casefold() != "active"
    ):
        record.add_state(ReconciliationState.OWNERSHIP_UNRESOLVED)
        record.block("Dataset ownership could not be proven against an active user.")
    elif user_resolver is None:
        record.add_state(ReconciliationState.OWNERSHIP_UNRESOLVED)
        record.block("Owner directory was not supplied; user existence is unresolved.")

    grants = dataset.get("access")
    grants = grants if isinstance(grants, list) else []
    normalized = [
        {
            "user_id": _clean(grant.get("userId")),
            "role": _clean(grant.get("role")).casefold(),
        }
        for grant in grants
        if isinstance(grant, dict)
    ]
    valid_roles = {"owner", "editor", "viewer", "auditor"}
    invalid_grants = [
        grant
        for grant in normalized
        if not grant["user_id"] or grant["role"] not in valid_roles
    ]
    owner_grants = [
        grant
        for grant in normalized
        if grant["user_id"] == owner_id and grant["role"] == "owner"
    ]
    unresolved_users = []
    if user_resolver is not None:
        for grant in normalized:
            try:
                if not user_resolver(grant["user_id"]):
                    unresolved_users.append(grant["user_id"])
            except Exception:
                unresolved_users.append(grant["user_id"])
    record.acl_evidence = {
        "grant_count": len(normalized),
        "owner_grant_present": bool(owner_grants),
        "invalid_grant_count": len(invalid_grants),
        "unresolved_principal_count": len(set(unresolved_users)),
    }
    if (
        not normalized
        or not owner_grants
        or invalid_grants
        or unresolved_users
        or user_resolver is None
    ):
        record.add_state(ReconciliationState.ACL_UNRESOLVED)
        record.block("Dataset ACL evidence is missing, invalid, or unresolved.")


def _attach_artifact_evidence(
    record: DatasetReconciliationRecord,
    *,
    root: Path,
    artifact_path: Path,
    dataset: Mapping[str, Any],
    version: Mapping[str, Any],
    deep_checksums: bool,
    remaining_hash_bytes: int,
    max_sidecar_bytes: int,
) -> int:
    relative = _safe_relative(artifact_path, root)
    if relative is None or _has_linked_component(artifact_path, root):
        record.add_state(ReconciliationState.REGISTRY_WITHOUT_ARTIFACT)
        record.block(
            "Registered artifact path escapes the Dataset Library root or traverses a link."
        )
        return 0
    record.artifact_path = relative
    if not artifact_path.is_file():
        record.add_state(ReconciliationState.REGISTRY_WITHOUT_ARTIFACT)
        record.block("The registered immutable full-data artifact is missing.")
        record.artifact_state = {"exists": False, "relative_path": relative}
        return 0

    size = artifact_path.stat().st_size
    record.artifact_state = {
        "exists": True,
        "relative_path": relative,
        "size_bytes": size,
        "checksum_verified": False,
        "schema_verified": False,
    }
    used = 0

    def evidence_hash(path: Path) -> str | None:
        nonlocal used
        if not deep_checksums:
            return None
        try:
            size_bytes = path.stat().st_size
        except OSError:
            return None
        if size_bytes > max(0, remaining_hash_bytes - used):
            record.artifact_state["checksum_skipped_due_to_budget"] = True
            record.warn("Evidence checksum was not evaluated within this scan budget.")
            return None
        digest = sha256_file(path)
        used += size_bytes
        return digest

    expected_hash = _clean(
        version.get("hash") or version.get("contentHash") or version.get("sha256")
    ).casefold()
    if not expected_hash:
        record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
        record.block("Registered version has no immutable content checksum.")
    elif deep_checksums and size <= remaining_hash_bytes:
        actual_hash = sha256_file(artifact_path).casefold()
        used += size
        record.content_hash = actual_hash
        record.artifact_state["checksum_verified"] = actual_hash == expected_hash
        record.artifact_state["expected_content_hash"] = expected_hash
        if actual_hash != expected_hash:
            record.add_state(ReconciliationState.CHECKSUM_MISMATCH)
            record.block("Immutable artifact checksum does not match the registry.")
    else:
        record.content_hash = expected_hash or None
        if deep_checksums and size > remaining_hash_bytes:
            record.artifact_state["checksum_skipped_due_to_budget"] = True
        record.warn("Full artifact checksum was not evaluated within this scan budget.")

    version_directory = artifact_path.parent
    metadata_path = version_directory / "metadata.json"
    metadata = _sidecar(metadata_path, max_bytes=max_sidecar_bytes)
    if metadata is None:
        record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
        record.block("Exact dataset/version metadata sidecar is missing or malformed.")
    else:
        metadata_dataset = _clean(metadata.get("datasetId"))
        metadata_version = _clean(metadata.get("versionId"))
        if metadata_dataset != record.dataset_id or metadata_version != record.dataset_version_id:
            record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
            record.block("Artifact metadata sidecar contradicts the registered identity.")
        record.evidence_sources.append(
            EvidenceSource(
                kind="artifact_metadata_sidecar",
                tier=EvidenceTier.STRONG_CORROBORATION,
                reference=_safe_relative(metadata_path, root) or metadata_path.name,
                fields=("dataset_id", "dataset_version_id", "original_filename"),
                sha256=evidence_hash(metadata_path),
            )
        )

    lineage_path = version_directory / "lineage.json"
    lineage = _sidecar(lineage_path, max_bytes=max_sidecar_bytes)
    if lineage is not None:
        record.source_metadata.update(
            {
                "lineage_registered_by": lineage.get("registeredBy"),
                "lineage_registered_at": lineage.get("registeredAt"),
                "lineage_source_type": lineage.get("sourceType"),
                "lineage_hash": lineage.get("hash"),
            }
        )
        lineage_hash = _clean(lineage.get("hash")).casefold()
        if expected_hash and lineage_hash and lineage_hash != expected_hash:
            record.add_state(ReconciliationState.CHECKSUM_MISMATCH)
            record.block("Lineage checksum contradicts the registered checksum.")
        record.evidence_sources.append(
            EvidenceSource(
                kind="artifact_lineage_sidecar",
                tier=EvidenceTier.STRONG_CORROBORATION,
                reference=_safe_relative(lineage_path, root) or lineage_path.name,
                fields=("content_hash", "registered_by", "registered_at", "source_type"),
                sha256=evidence_hash(lineage_path),
            )
        )

    schema_path = version_directory / "schema.json"
    schema = _sidecar(
        schema_path,
        "columns",
        max_bytes=max_sidecar_bytes,
    )
    if schema is None:
        record.add_state(ReconciliationState.SCHEMA_MISMATCH)
        record.block("Schema sidecar is missing or malformed.")
    else:
        raw_schema_hash = evidence_hash(schema_path)
        canonical_schema_hash = _canonical_schema_hash(schema)
        record.schema_hash = canonical_schema_hash
        expected_schema = _clean(version.get("schemaHash")).casefold()
        schema_hash_verified = bool(
            not expected_schema
            or (
                raw_schema_hash
                and expected_schema
                in {
                    raw_schema_hash.casefold(),
                    canonical_schema_hash.casefold(),
                }
            )
        )
        schema_ok = schema_hash_verified
        columns = schema.get("columns") or []
        expected_columns = version.get("columnCount")
        if expected_columns is not None:
            try:
                schema_ok = schema_ok and len(columns) == int(expected_columns)
            except (TypeError, ValueError):
                schema_ok = False
        record.artifact_state["schema_verified"] = schema_ok
        record.artifact_state["schema_column_count"] = len(columns)
        if expected_schema:
            record.artifact_state["expected_schema_hash"] = expected_schema
        else:
            record.warn("Registry has no schemaHash; schema content was measured but not cryptographically bound.")
        if expected_schema and raw_schema_hash is None:
            record.warn("Schema checksum was not evaluated within this scan budget.")
        elif not schema_ok:
            record.add_state(ReconciliationState.SCHEMA_MISMATCH)
            record.block("Schema artifact contradicts registered schema metadata.")
        record.evidence_sources.append(
            EvidenceSource(
                kind="artifact_schema_sidecar",
                tier=EvidenceTier.STRONG_CORROBORATION,
                reference=_safe_relative(schema_path, root) or schema_path.name,
                fields=("schema_hash", "column_count"),
                sha256=raw_schema_hash,
            )
        )

    profile_path = version_directory / "profile.json"
    profile = _sidecar(profile_path, max_bytes=max_sidecar_bytes)
    if profile is not None:
        row_ok = True
        column_ok = True
        try:
            if version.get("rowCount") is not None and profile.get("rowCount") is not None:
                row_ok = int(version["rowCount"]) == int(profile["rowCount"])
            if version.get("columnCount") is not None and profile.get("columnCount") is not None:
                column_ok = int(version["columnCount"]) == int(profile["columnCount"])
        except (TypeError, ValueError):
            row_ok = column_ok = False
        if not row_ok or not column_ok:
            record.add_state(ReconciliationState.SCHEMA_MISMATCH)
            record.block("Profile dimensions contradict registered version dimensions.")
        record.evidence_sources.append(
            EvidenceSource(
                kind="artifact_profile_sidecar",
                tier=EvidenceTier.STRONG_CORROBORATION,
                reference=_safe_relative(profile_path, root) or profile_path.name,
                fields=("row_count", "column_count", "profile"),
                sha256=evidence_hash(profile_path),
            )
        )
    return used


def _finalize_record(record: DatasetReconciliationRecord) -> None:
    error_states = {
        ReconciliationState.REGISTRY_WITHOUT_ARTIFACT,
        ReconciliationState.ARTIFACT_WITHOUT_REGISTRY,
        ReconciliationState.DATASET_WITHOUT_VERSION,
        ReconciliationState.VERSION_WITHOUT_DATASET,
        ReconciliationState.PROJECT_LINK_WITHOUT_DATASET,
        ReconciliationState.PROJECT_LINK_WITHOUT_VERSION,
        ReconciliationState.ACTIVE_SELECTION_WITHOUT_LINK,
        ReconciliationState.ACTIVE_SELECTION_WITHOUT_VERSION,
        ReconciliationState.CHECKSUM_MISMATCH,
        ReconciliationState.SCHEMA_MISMATCH,
        ReconciliationState.OWNERSHIP_UNRESOLVED,
        ReconciliationState.ACL_UNRESOLVED,
        ReconciliationState.AMBIGUOUS_IDENTITY,
        ReconciliationState.LEGACY_LINK_DIVERGENCE,
        ReconciliationState.RECOVERY_JOURNAL_PENDING,
        ReconciliationState.QUARANTINED,
    }
    has_tier_one = any(
        evidence.tier == EvidenceTier.AUTHORITATIVE
        for evidence in record.evidence_sources
    )
    has_tier_two = any(
        evidence.tier == EvidenceTier.STRONG_CORROBORATION
        for evidence in record.evidence_sources
    )
    recovery_states = {
        ReconciliationState.ARTIFACT_WITHOUT_REGISTRY,
        ReconciliationState.VERSION_WITHOUT_DATASET,
    }
    non_recovery_errors = error_states - recovery_states
    needs_recovery = bool(recovery_states.intersection(record.states))
    record.recovery_eligibility = bool(
        needs_recovery
        and record.dataset_id
        and record.dataset_version_id
        and record.artifact_state.get("exists")
        and record.artifact_state.get("checksum_verified") is True
        and record.artifact_state.get("schema_verified") is True
        and has_tier_one
        and has_tier_two
        and not non_recovery_errors.intersection(record.states)
    )
    if record.recovery_eligibility:
        record.add_state(ReconciliationState.RECOVERABLE)
        record.confidence_level = "high"
    elif not error_states.intersection(record.states):
        record.add_state(ReconciliationState.HEALTHY)
        record.confidence_level = "high" if has_tier_two else "medium"
    else:
        record.confidence_level = "medium" if has_tier_two else "low"


def scan_dataset_library(
    storage: DatasetLibraryStorage | None = None,
    *,
    database: Any = None,
    user_resolver: Callable[[str], Mapping[str, Any] | None] | None = None,
    deep_checksums: bool = True,
    limits: ReconciliationLimits | None = None,
) -> DatasetLibraryReconciliationReport:
    """Reconcile catalog, artifacts, ACL evidence, links, and active versions.

    ``database`` is optional and must expose a ``path`` attribute.  It is opened
    separately using SQLite ``mode=ro`` so this scan cannot create a database,
    run migrations, switch WAL mode, or update timestamps.
    """

    selected_storage = storage or DatasetLibraryStorage()
    selected_limits = limits or ReconciliationLimits()
    root = selected_storage.paths.root
    report = DatasetLibraryReconciliationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        configured_root_name=root.name,
    )
    try:
        journal = selected_storage.read_recovery_journal(
            required=False,
            max_bytes=selected_limits.max_sidecar_bytes,
        )
    except DatasetStorageError as exc:
        report.storage_errors.append(str(exc))
        journal_record = DatasetReconciliationRecord(None, None)
        journal_record.add_state(ReconciliationState.QUARANTINED)
        journal_record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
        journal_record.block("Recovery journal is malformed and requires operator review.")
        report.records.append(journal_record)
        journal = None
    journal_status = (
        _clean(journal.get("status")).casefold() if journal else ""
    )
    if journal and journal_status in {"prepared", "commit_pending"}:
        journal_record = DatasetReconciliationRecord(
            _clean(journal.get("datasetId")) or None,
            _clean(journal.get("datasetVersionId")) or None,
        )
        journal_record.add_state(ReconciliationState.RECOVERY_JOURNAL_PENDING)
        journal_record.add_state(ReconciliationState.QUARANTINED)
        journal_record.block(
            "A Dataset Library recovery journal at "
            f"{journal_status} requires exact operator resolution."
        )
        journal_record.evidence_sources.append(
            EvidenceSource(
                kind=f"{journal_status}_recovery_journal",
                tier=EvidenceTier.SUPPORTING_ONLY,
                reference=selected_storage.paths.recovery_journal_path.name,
                fields=(
                    "operation_id",
                    "dataset_id",
                    "dataset_version_id",
                    "status",
                ),
                sha256=sha256_file(selected_storage.paths.recovery_journal_path),
            )
        )
        report.records.append(journal_record)
    elif journal and journal_status in {"committed", "aborted"}:
        try:
            selected_storage.assert_no_pending_recovery()
        except DatasetStorageError:
            journal_record = DatasetReconciliationRecord(
                _clean(journal.get("datasetId")) or None,
                _clean(journal.get("datasetVersionId")) or None,
            )
            journal_record.add_state(ReconciliationState.RECOVERY_JOURNAL_PENDING)
            journal_record.add_state(ReconciliationState.QUARANTINED)
            journal_record.block(
                "The terminal recovery journal lacks exact durable audit proof."
            )
            report.records.append(journal_record)
    registry: Dict[str, Any] = {"datasets": []}
    try:
        registry = selected_storage.read_registry(
            max_bytes=selected_limits.max_registry_bytes,
            allow_pending_recovery=True,
        )
        report.registry_sha256 = sha256_file(selected_storage.paths.registry_path)
    except (DatasetStoreMissingError, DatasetStoreMalformedError, DatasetStorageError) as exc:
        report.storage_errors.append(str(exc))

    legacy_links_document: Dict[str, Any] = {"links": []}
    try:
        legacy_links_document = selected_storage.read_links(
            max_bytes=selected_limits.max_project_links_bytes,
            allow_pending_recovery=True,
        )
        report.project_links_sha256 = sha256_file(
            selected_storage.paths.project_links_path
        )
    except DatasetStorageError as exc:
        # project_links.json is a Dataset Library authority projection.  A
        # missing or malformed document cannot be treated as an empty link set:
        # doing so would make startup/admin diagnostics report a false healthy
        # state while project authorization evidence is unavailable.
        report.storage_errors.append(str(exc))

    (
        durable_links,
        active_selections,
        durable_warnings,
        durable_authority_available,
    ) = _read_durable_state(database)
    report.warnings.extend(durable_warnings)

    datasets = registry.get("datasets") if isinstance(registry, dict) else []
    datasets = datasets if isinstance(datasets, list) else []
    if len(datasets) > selected_limits.max_registry_datasets:
        report.scan_truncated = True
        report.warnings.append("Registry dataset limit was reached; report is partial.")
        datasets = datasets[: selected_limits.max_registry_datasets]

    dataset_id_counts = Counter(
        _clean(dataset.get("datasetId"))
        for dataset in datasets
        if isinstance(dataset, dict) and _clean(dataset.get("datasetId"))
    )

    records_by_pair: Dict[tuple[str, str], List[DatasetReconciliationRecord]] = {}
    expected_artifact_directories: Dict[tuple[str, str], set[str]] = {}
    registered_pairs: set[tuple[str, str]] = set()
    registered_dataset_ids: set[str] = set()
    global_version_owners: Dict[str, set[str]] = {}
    version_count = 0
    remaining_hash_bytes = max(0, int(selected_limits.max_checksum_bytes))

    def bounded_evidence_hash(path: Path) -> str | None:
        nonlocal remaining_hash_bytes
        if not deep_checksums:
            return None
        try:
            size_bytes = path.stat().st_size
        except OSError:
            return None
        if size_bytes > remaining_hash_bytes:
            report.scan_truncated = True
            return None
        digest = sha256_file(path)
        remaining_hash_bytes -= size_bytes
        report.checksummed_bytes += size_bytes
        return digest

    for dataset_index, dataset_value in enumerate(datasets):
        if not isinstance(dataset_value, dict):
            record = DatasetReconciliationRecord(None, None)
            record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
            record.block(f"Registry dataset entry {dataset_index} is not an object.")
            report.records.append(record)
            continue
        dataset = dataset_value
        dataset_id = _clean(dataset.get("datasetId"))
        if not dataset_id:
            record = DatasetReconciliationRecord(None, None)
            record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
            record.block("Registry dataset entry has no exact datasetId.")
            report.records.append(record)
            continue
        duplicate_dataset = dataset_id_counts[dataset_id] > 1
        registered_dataset_ids.add(dataset_id)
        versions = dataset.get("versions")
        if not isinstance(versions, list):
            versions = []
        if not versions:
            record = DatasetReconciliationRecord(dataset_id, None)
            record.registry_state = {"registered": True, "version_count": 0}
            record.add_state(ReconciliationState.DATASET_WITHOUT_VERSION)
            record.block("Registered dataset has no immutable version records.")
            record.evidence_sources.append(
                EvidenceSource(
                    kind="live_dataset_registry",
                    tier=EvidenceTier.AUTHORITATIVE,
                    reference="registry.json",
                    fields=("dataset_id", "owner", "acl"),
                    sha256=report.registry_sha256,
                )
            )
            if duplicate_dataset:
                record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                record.block("Dataset identifier occurs more than once in the registry.")
            _validate_owner_acl(record, dataset, user_resolver)
            _finalize_record(record)
            report.records.append(record)
            continue

        for version in versions:
            version_count += 1
            if version_count > selected_limits.max_registry_versions:
                report.scan_truncated = True
                report.warnings.append("Registry version limit was reached; report is partial.")
                break
            if not isinstance(version, dict):
                record = DatasetReconciliationRecord(dataset_id, None)
                record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                record.block("Registered version entry is not an object.")
                report.records.append(record)
                continue
            version_id = _clean(version.get("versionId"))
            record = DatasetReconciliationRecord(dataset_id, version_id or None)
            record.source_metadata = _public_source_metadata(dataset, version)
            record.registry_state = {
                "registered": True,
                "archived": bool(dataset.get("archived")),
                "row_count": version.get("rowCount"),
                "column_count": version.get("columnCount"),
                "content_hash": version.get("hash"),
                "schema_hash": version.get("schemaHash"),
            }
            record.evidence_sources.append(
                EvidenceSource(
                    kind="live_dataset_registry",
                    tier=EvidenceTier.AUTHORITATIVE,
                    reference="registry.json",
                    fields=(
                        "dataset_id",
                        "dataset_version_id",
                        "owner",
                        "acl",
                        "content_hash",
                        "source_metadata",
                    ),
                    sha256=report.registry_sha256,
                )
            )
            if duplicate_dataset or not version_id:
                record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                record.block(
                    "Registered dataset/version identity is missing or duplicated."
                )
            if version_id:
                pair = (dataset_id, version_id)
                registered_pairs.add(pair)
                records_by_pair.setdefault(pair, []).append(record)
                global_version_owners.setdefault(version_id, set()).add(dataset_id)
            _validate_owner_acl(record, dataset, user_resolver)
            relative_path = _clean(version.get("fullDataPath"))
            if not relative_path:
                record.add_state(ReconciliationState.REGISTRY_WITHOUT_ARTIFACT)
                record.block("Registered version has no fullDataPath.")
            else:
                artifact_path = root / relative_path
                if version_id:
                    expected_directory = artifact_path.parent
                    if (
                        _safe_relative(expected_directory, root) is not None
                        and not _has_linked_component(expected_directory, root)
                    ):
                        expected_artifact_directories.setdefault(
                            (dataset_id, version_id),
                            set(),
                        ).add(os.path.normcase(str(expected_directory.resolve())))
                used = _attach_artifact_evidence(
                    record,
                    root=root,
                    artifact_path=artifact_path,
                    dataset=dataset,
                    version=version,
                    deep_checksums=deep_checksums,
                    remaining_hash_bytes=remaining_hash_bytes,
                    max_sidecar_bytes=selected_limits.max_sidecar_bytes,
                )
                remaining_hash_bytes -= used
                report.checksummed_bytes += used
                if record.artifact_state.get("checksum_skipped_due_to_budget"):
                    report.scan_truncated = True
            report.records.append(record)
        if version_count > selected_limits.max_registry_versions:
            break

    for version_id, owner_ids in global_version_owners.items():
        if len(owner_ids) <= 1:
            continue
        for dataset_id in owner_ids:
            for record in records_by_pair.get((dataset_id, version_id), []):
                record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                record.block("Dataset version identifier belongs to multiple datasets.")

    for pair, pair_records in records_by_pair.items():
        if len(pair_records) <= 1:
            continue
        for record in pair_records:
            record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
            record.block(
                "Dataset and version identifiers occur more than once in the registry."
            )

    # Discover orphan directories without trusting directory names as identity.
    artifact_dataset_count = 0
    artifact_version_count = 0
    if root.exists() and root.is_dir():
        root_entries, root_entries_truncated = _bounded_directory_listing(
            root,
            max_entries=selected_limits.max_entries_per_directory,
        )
        if root_entries_truncated:
            report.scan_truncated = True
            report.warnings.append("Artifact root entry limit was reached.")
        for dataset_directory in root_entries:
            if not dataset_directory.is_dir() or dataset_directory.name.startswith("."):
                continue
            if _is_link_or_junction(dataset_directory) or _safe_relative(dataset_directory, root) is None:
                record = DatasetReconciliationRecord(dataset_directory.name, None)
                record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                record.block(
                    "Artifact dataset directory is a link or escapes the configured root."
                )
                _finalize_record(record)
                report.records.append(record)
                continue
            artifact_dataset_count += 1
            if artifact_dataset_count > selected_limits.max_artifact_dataset_directories:
                report.scan_truncated = True
                report.warnings.append("Artifact dataset-directory limit was reached.")
                break
            versions_directory = dataset_directory / "versions"
            if not versions_directory.is_dir():
                if dataset_directory.name not in registered_dataset_ids:
                    record = DatasetReconciliationRecord(dataset_directory.name, None)
                    record.artifact_path = _safe_relative(dataset_directory, root)
                    record.artifact_state = {"exists": True, "directory_only": True}
                    record.add_state(ReconciliationState.ARTIFACT_WITHOUT_REGISTRY)
                    record.block("Artifact directory has no authoritative registry record.")
                    _finalize_record(record)
                    report.records.append(record)
                continue
            if _is_link_or_junction(versions_directory) or _safe_relative(versions_directory, root) is None:
                record = DatasetReconciliationRecord(dataset_directory.name, None)
                record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                record.block(
                    "Artifact versions directory is a link or escapes the configured root."
                )
                _finalize_record(record)
                report.records.append(record)
                continue
            version_entries, version_entries_truncated = _bounded_directory_listing(
                versions_directory,
                max_entries=selected_limits.max_entries_per_directory,
            )
            if version_entries_truncated:
                report.scan_truncated = True
                report.warnings.append(
                    "Artifact version-directory entry limit was reached."
                )
            for version_directory in version_entries:
                if not version_directory.is_dir() or version_directory.name.startswith("."):
                    continue
                if _is_link_or_junction(version_directory) or _safe_relative(version_directory, root) is None:
                    record = DatasetReconciliationRecord(
                        dataset_directory.name,
                        version_directory.name,
                    )
                    record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                    record.block(
                        "Artifact version directory is a link or escapes the configured root."
                    )
                    _finalize_record(record)
                    report.records.append(record)
                    continue
                artifact_version_count += 1
                if artifact_version_count > selected_limits.max_artifact_version_directories:
                    report.scan_truncated = True
                    report.warnings.append("Artifact version-directory limit was reached.")
                    break
                metadata = _sidecar(
                    version_directory / "metadata.json",
                    max_bytes=selected_limits.max_sidecar_bytes,
                ) or {}
                metadata_dataset_id = _clean(metadata.get("datasetId"))
                metadata_version_id = _clean(metadata.get("versionId"))
                pair = (
                    metadata_dataset_id or dataset_directory.name,
                    metadata_version_id or version_directory.name,
                )
                actual_directory_key = os.path.normcase(
                    str(version_directory.resolve())
                )
                if (
                    pair in registered_pairs
                    and actual_directory_key
                    in expected_artifact_directories.get(pair, set())
                ):
                    continue
                record = DatasetReconciliationRecord(pair[0] or None, pair[1] or None)
                record.artifact_path = _safe_relative(version_directory, root)
                record.artifact_state = {
                    "exists": True,
                    "directory_only": True,
                    "metadata_sidecar_present": bool(metadata),
                }
                record.add_state(ReconciliationState.ARTIFACT_WITHOUT_REGISTRY)
                if pair in registered_pairs:
                    record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                    record.block(
                        "Unreferenced artifact directory claims an already registered identity."
                    )
                else:
                    record.block("Artifact version has no authoritative registry record.")
                if pair[0] not in registered_dataset_ids:
                    record.add_state(ReconciliationState.VERSION_WITHOUT_DATASET)
                if not metadata_dataset_id or not metadata_version_id:
                    record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
                    record.block("Orphan artifact lacks an exact identity sidecar.")
                else:
                    metadata_path = version_directory / "metadata.json"
                    record.evidence_sources.append(
                        EvidenceSource(
                            kind="artifact_metadata_sidecar",
                            tier=EvidenceTier.STRONG_CORROBORATION,
                            reference=_safe_relative(metadata_path, root) or metadata_path.name,
                            fields=("dataset_id", "dataset_version_id", "original_filename"),
                            sha256=bounded_evidence_hash(metadata_path),
                        )
                    )
                lineage_path = version_directory / "lineage.json"
                lineage = _sidecar(
                    lineage_path,
                    max_bytes=selected_limits.max_sidecar_bytes,
                )
                if lineage is not None:
                    record.content_hash = _clean(lineage.get("hash")) or None
                    record.source_metadata = {
                        "original_filename": lineage.get("originalFilename"),
                        "registered_by": lineage.get("registeredBy"),
                        "registered_at": lineage.get("registeredAt"),
                        "source_type": lineage.get("sourceType"),
                    }
                    record.evidence_sources.append(
                        EvidenceSource(
                            kind="artifact_lineage_sidecar",
                            tier=EvidenceTier.STRONG_CORROBORATION,
                            reference=_safe_relative(lineage_path, root) or lineage_path.name,
                            fields=("content_hash", "registered_by", "registered_at"),
                            sha256=bounded_evidence_hash(lineage_path),
                        )
                    )
                # Sidecars remain Tier 2.  No owner/ACL is inferred from them.
                record.add_state(ReconciliationState.OWNERSHIP_UNRESOLVED)
                record.add_state(ReconciliationState.ACL_UNRESOLVED)
                record.block("Owner and ACL require authoritative registry evidence.")
                _finalize_record(record)
                report.records.append(record)
            if artifact_version_count > selected_limits.max_artifact_version_directories:
                break

    # Reconcile the legacy JSON projections before consulting durable authority.
    legacy_pairs: set[tuple[str, str]] = set()
    legacy_versions: Dict[tuple[str, str], set[str]] = {}
    legacy_values = legacy_links_document.get("links", [])
    legacy_values = legacy_values if isinstance(legacy_values, list) else []

    def flag_projection_divergence(
        project_id: str,
        dataset_id: str,
        reason: str,
    ) -> None:
        matching_records = [
            record for record in report.records if record.dataset_id == dataset_id
        ]
        if not matching_records:
            record = DatasetReconciliationRecord(dataset_id or None, None)
            record.add_state(ReconciliationState.PROJECT_LINK_WITHOUT_DATASET)
            record.block("Project-link projection names an unregistered dataset.")
            matching_records = [record]
            report.records.append(record)
        for record in matching_records:
            record.add_state(ReconciliationState.LEGACY_LINK_DIVERGENCE)
            record.block(reason)
            record.project_link_evidence.append(
                {
                    "project_id": project_id or None,
                    "dataset_id": dataset_id or None,
                    "authority": "projection_comparison",
                }
            )

    for index, link_value in enumerate(legacy_values):
        if not isinstance(link_value, dict):
            record = DatasetReconciliationRecord(None, None)
            record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
            record.block(f"Legacy project-link entry {index} is not an object.")
            report.records.append(record)
            continue
        project_id = _clean(link_value.get("projectId"))
        dataset_id = _clean(link_value.get("datasetId"))
        version_id = _clean(link_value.get("versionId"))
        if not project_id or not dataset_id:
            record = DatasetReconciliationRecord(dataset_id or None, version_id or None)
            record.add_state(ReconciliationState.AMBIGUOUS_IDENTITY)
            record.block("Legacy project-link projection lacks an exact identity.")
            report.records.append(record)
            continue
        pair = (project_id, dataset_id)
        legacy_pairs.add(pair)
        legacy_versions.setdefault(pair, set()).add(version_id)
        matching_records = [
            record for record in report.records if record.dataset_id == dataset_id
        ]
        evidence = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": version_id or None,
            "authority": "legacy_projection",
        }
        if not matching_records:
            record = DatasetReconciliationRecord(dataset_id, version_id or None)
            record.project_link_evidence.append(evidence)
            record.add_state(ReconciliationState.PROJECT_LINK_WITHOUT_DATASET)
            record.block("Legacy project-link projection names an unregistered dataset.")
            report.records.append(record)
            continue
        for record in matching_records:
            record.project_link_evidence.append(evidence)
            record.evidence_sources.append(
                EvidenceSource(
                    kind="legacy_project_link_projection",
                    tier=EvidenceTier.SUPPORTING_ONLY,
                    reference="project_links.json",
                    fields=("project_id", "dataset_id", "dataset_version_id"),
                    sha256=report.project_links_sha256,
                )
            )
            if not version_id or (dataset_id, version_id) not in registered_pairs:
                record.add_state(ReconciliationState.PROJECT_LINK_WITHOUT_VERSION)
                record.block(
                    "Legacy project-link projection does not name a registered exact version."
                )

    registry_projection_pairs: set[tuple[str, str]] = set()
    registry_projection_versions: Dict[tuple[str, str], set[str]] = {}
    for dataset_value in datasets:
        if not isinstance(dataset_value, dict):
            continue
        dataset_id = _clean(dataset_value.get("datasetId"))
        linked_projects = dataset_value.get("linkedProjects")
        linked_projects = linked_projects if isinstance(linked_projects, list) else []
        for projection in linked_projects:
            if not isinstance(projection, dict):
                flag_projection_divergence(
                    "",
                    dataset_id,
                    "Registry linkedProjects projection contains a malformed entry.",
                )
                continue
            project_id = _clean(projection.get("projectId"))
            version_id = _clean(projection.get("versionId"))
            if not project_id:
                flag_projection_divergence(
                    "",
                    dataset_id,
                    "Registry linkedProjects projection lacks an exact project identity.",
                )
                continue
            pair = (project_id, dataset_id)
            registry_projection_pairs.add(pair)
            registry_projection_versions.setdefault(pair, set()).add(version_id)
            if not version_id or (dataset_id, version_id) not in registered_pairs:
                for record in [
                    item for item in report.records if item.dataset_id == dataset_id
                ]:
                    record.add_state(ReconciliationState.PROJECT_LINK_WITHOUT_VERSION)
                    record.block(
                        "Registry linkedProjects projection does not name a registered exact version."
                    )

    for project_id, dataset_id in legacy_pairs.symmetric_difference(
        registry_projection_pairs
    ):
        flag_projection_divergence(
            project_id,
            dataset_id,
            "Legacy project_links.json and registry linkedProjects projections disagree.",
        )
    for pair in legacy_pairs.intersection(registry_projection_pairs):
        if legacy_versions.get(pair) != registry_projection_versions.get(pair):
            flag_projection_divergence(
                pair[0],
                pair[1],
                "Legacy project-link projections disagree on the exact dataset version.",
            )

    # Cross-check durable dataset authorization and exact active selections.
    active_link_pairs = {
        (_clean(link.get("project_id")), _clean(link.get("dataset_id")))
        for link in durable_links
        if _clean(link.get("link_status")).casefold() == "active"
    }
    if durable_authority_available:
        projected_pairs = legacy_pairs.union(registry_projection_pairs)
        for project_id, dataset_id in projected_pairs.symmetric_difference(
            active_link_pairs
        ):
            flag_projection_divergence(
                project_id,
                dataset_id,
                "Legacy Dataset Library projection disagrees with durable project authorization.",
            )

        active_versions = {
            (_clean(selection.get("project_id")), _clean(selection.get("dataset_id"))):
            _clean(selection.get("dataset_version_id"))
            for selection in active_selections
            if _clean(selection.get("activation_status")).casefold() == "active"
        }
        for pair in projected_pairs.intersection(active_versions):
            projected_versions = legacy_versions.get(
                pair,
                registry_projection_versions.get(pair, set()),
            )
            if active_versions[pair] not in projected_versions:
                flag_projection_divergence(
                    pair[0],
                    pair[1],
                    "Legacy projection contradicts the durable active exact version.",
                )
    for link in durable_links:
        if _clean(link.get("link_status")).casefold() != "active":
            continue
        dataset_id = _clean(link.get("dataset_id"))
        project_id = _clean(link.get("project_id"))
        matching = [
            record for record in report.records if record.dataset_id == dataset_id
        ]
        evidence = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "link_status": link.get("link_status"),
            "linked_by": link.get("linked_by"),
            "linked_at": link.get("linked_at"),
        }
        if matching:
            for record in matching:
                record.project_link_evidence.append(evidence)
                record.evidence_sources.append(
                    EvidenceSource(
                        kind="durable_project_dataset_link",
                        tier=EvidenceTier.AUTHORITATIVE,
                        reference=f"project_dataset_links:{project_id}:{dataset_id}",
                        fields=("project_id", "dataset_id", "authorization"),
                    )
                )
        else:
            record = DatasetReconciliationRecord(dataset_id or None, None)
            record.project_link_evidence.append(evidence)
            record.add_state(ReconciliationState.PROJECT_LINK_WITHOUT_DATASET)
            record.block("Durable project link names an unregistered dataset.")
            _finalize_record(record)
            report.records.append(record)

    for selection in active_selections:
        if _clean(selection.get("activation_status")).casefold() != "active":
            continue
        project_id = _clean(selection.get("project_id"))
        dataset_id = _clean(selection.get("dataset_id"))
        version_id = _clean(selection.get("dataset_version_id"))
        pair = (dataset_id, version_id)
        matching = records_by_pair.get(pair, [])
        evidence = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "activation_revision": selection.get("activation_revision"),
            "activation_status": selection.get("activation_status"),
        }
        if not matching:
            record = DatasetReconciliationRecord(dataset_id or None, version_id or None)
            record.active_selection_evidence.append(evidence)
            record.add_state(ReconciliationState.ACTIVE_SELECTION_WITHOUT_VERSION)
            record.block("Active selection names an unregistered exact version.")
            if (project_id, dataset_id) not in active_link_pairs:
                record.add_state(ReconciliationState.ACTIVE_SELECTION_WITHOUT_LINK)
                record.block("Active selection has no active project-dataset link.")
            _finalize_record(record)
            report.records.append(record)
            continue
        for record in matching:
            record.active_selection_evidence.append(evidence)
            record.evidence_sources.append(
                EvidenceSource(
                    kind="durable_active_dataset_selection",
                    tier=EvidenceTier.AUTHORITATIVE,
                    reference=f"active_modeling_dataset_versions:{project_id}",
                    fields=(
                        "project_id",
                        "dataset_id",
                        "dataset_version_id",
                        "activation_revision",
                    ),
                )
            )
            if (project_id, dataset_id) not in active_link_pairs:
                record.add_state(ReconciliationState.ACTIVE_SELECTION_WITHOUT_LINK)
                record.block("Active selection has no active project-dataset link.")

    # Recompute final status after durable evidence has been attached.
    for record in report.records:
        record.states = [
            state
            for state in record.states
            if state not in {ReconciliationState.HEALTHY, ReconciliationState.RECOVERABLE}
        ]
        _finalize_record(record)
    return report


__all__ = [
    "DatasetLibraryReconciliationReport",
    "DatasetReconciliationRecord",
    "EvidenceSource",
    "EvidenceTier",
    "ReconciliationLimits",
    "ReconciliationState",
    "scan_dataset_library",
]
