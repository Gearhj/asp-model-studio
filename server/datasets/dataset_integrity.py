"""Bounded Dataset Library integrity checks for startup and administrators.

This module is deliberately read-only.  It never creates catalog files,
repairs orphan artifacts, changes project authorization, or activates a
dataset version.  Startup and the admin endpoint share the same bounded scan
so a malformed or unexpectedly large library cannot block application boot.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path
from typing import Any, Callable, Dict, Mapping

from .dataset_reconciliation import (
    DatasetLibraryReconciliationReport,
    ReconciliationLimits,
    scan_dataset_library,
)
from .dataset_storage import (
    DatasetLibraryStorage,
    DatasetStorageError,
    read_json_strict,
    sha256_file,
)


_BACKUP_PREFIX = "atlas-dataset-library-"
_RECOVERY_SAFETY_MANIFEST = "recovery_safety_manifest.json"
_RECOVERY_DATABASE_TABLES = frozenset(
    {
        "projects",
        "project_dataset_links",
        "active_modeling_dataset_versions",
        "project_dataset_activation_events",
        "schema_migrations",
    }
)


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


def _bounded_environment_integer(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def startup_reconciliation_limits() -> ReconciliationLimits:
    """Return bounded, operator-configurable limits for unattended scans."""

    return ReconciliationLimits(
        max_registry_datasets=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_DATASETS", 5_000, minimum=1, maximum=50_000
        ),
        max_registry_versions=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_VERSIONS", 20_000, minimum=1, maximum=200_000
        ),
        max_artifact_dataset_directories=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_ARTIFACT_DATASETS",
            5_000,
            minimum=1,
            maximum=50_000,
        ),
        max_artifact_version_directories=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_ARTIFACT_VERSIONS",
            20_000,
            minimum=1,
            maximum=200_000,
        ),
        max_checksum_bytes=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_CHECKSUM_BYTES",
            512 * 1024 * 1024,
            minimum=0,
            maximum=20 * 1024 * 1024 * 1024,
        ),
        max_registry_bytes=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_REGISTRY_BYTES",
            64 * 1024 * 1024,
            minimum=1_024,
            maximum=256 * 1024 * 1024,
        ),
        max_project_links_bytes=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_LINK_BYTES",
            16 * 1024 * 1024,
            minimum=1_024,
            maximum=128 * 1024 * 1024,
        ),
        max_sidecar_bytes=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_SIDECAR_BYTES",
            8 * 1024 * 1024,
            minimum=1_024,
            maximum=64 * 1024 * 1024,
        ),
        max_entries_per_directory=_bounded_environment_integer(
            "ATLAS_DATASET_SCAN_MAX_DIRECTORY_ENTRIES",
            100_000,
            minimum=100,
            maximum=500_000,
        ),
    )


def _safe_backup_child(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _safe_unlinked_backup_file(path: Path, root: Path) -> bool:
    if not _safe_backup_child(path, root):
        return False
    lexical_root = Path(os.path.abspath(str(root)))
    lexical_path = Path(os.path.abspath(str(path)))
    try:
        parts = lexical_path.relative_to(lexical_root).parts
    except ValueError:
        return False
    current = lexical_root
    for part in parts:
        current = current / part
        if _is_link_or_junction(current):
            return False
    return path.is_file()


def _audited_recovery_manifests(
    database: Any,
    *,
    max_references: int,
) -> tuple[Dict[str, set[str]], bool, bool]:
    """Return bounded safety-manifest SHA -> operation IDs from durable audit."""

    if database is None:
        return {}, False, False
    configured = getattr(database, "path", database)
    try:
        database_path = Path(configured).expanduser().resolve()
    except (OSError, TypeError, ValueError):
        return {}, False, False
    if not database_path.is_file():
        return {}, False, False
    uri = f"file:{database_path.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=3.0)
        try:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'dataset_library_maintenance_events'"
            ).fetchone()
            if not table_exists:
                return {}, False, False
            bounded_limit = max(1, min(int(max_references), 100_000))
            rows = connection.execute(
                "SELECT backup_manifest_sha256, operation_id "
                "FROM dataset_library_maintenance_events "
                "WHERE backup_manifest_sha256 IS NOT NULL "
                "AND backup_manifest_sha256 <> '' "
                "ORDER BY created_at DESC LIMIT ?",
                (bounded_limit + 1,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}, False, False
    truncated = len(rows) > bounded_limit
    references: Dict[str, set[str]] = {}
    for raw_sha, raw_operation_id in rows[:bounded_limit]:
        digest = str(raw_sha or "").strip().casefold()
        operation_id = str(raw_operation_id or "").strip()
        if len(digest) == 64 and operation_id:
            references.setdefault(digest, set()).add(operation_id)
    return references, True, truncated


def _sqlite_safety_copy_is_valid(path: Path) -> bool:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=3.0)
        try:
            quick = [
                str(row[0]).casefold()
                for row in connection.execute("PRAGMA quick_check").fetchall()
            ]
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return quick == ["ok"] and _RECOVERY_DATABASE_TABLES.issubset(tables)


def inspect_backup_state(
    storage: DatasetLibraryStorage,
    *,
    database: Any = None,
    max_bundles: int = 100,
    max_checksum_bytes: int = 256 * 1024 * 1024,
    max_directory_entries: int = 1_000,
    max_manifest_bytes: int = 8 * 1024 * 1024,
) -> Dict[str, Any]:
    """Return path-free backup counts and bounded checksum verification."""

    backup_root = storage.paths.backup_root
    state: Dict[str, Any] = {
        "configured": True,
        "exists": False,
        "bundle_count": 0,
        "inspected_bundle_count": 0,
        "self_consistent_bundle_count": 0,
        "recovery_safety_bundle_count": 0,
        "audit_bound_verified_bundle_count": 0,
        "audit_bound_invalid_bundle_count": 0,
        "audit_bound_unverified_bundle_count": 0,
        "audit_binding_available": False,
        "audit_reference_scan_truncated": False,
        "invalid_bundle_count": 0,
        "partially_verified_bundle_count": 0,
        "verified_file_count": 0,
        "unverified_file_count": 0,
        "checksummed_bytes": 0,
        "latest_created_at": None,
        "scan_truncated": False,
    }
    if not backup_root.exists() or not backup_root.is_dir():
        return state
    state["exists"] = True
    audit_references, audit_available, audit_truncated = (
        _audited_recovery_manifests(
            database,
            max_references=max_directory_entries,
        )
    )
    state["audit_binding_available"] = audit_available
    state["audit_reference_scan_truncated"] = audit_truncated
    bundles = []
    discovered_bundle_count = 0
    entry_limit = max(1, min(int(max_directory_entries), 10_000))
    for entry_index, child in enumerate(backup_root.iterdir()):
        if entry_index >= entry_limit:
            state["scan_truncated"] = True
            break
        if child.is_dir() and child.name.startswith(_BACKUP_PREFIX):
            discovered_bundle_count += 1
            if _is_link_or_junction(child):
                state["invalid_bundle_count"] += 1
            else:
                bundles.append(child)
    bundles.sort(key=lambda child: child.name, reverse=True)
    state["bundle_count"] = discovered_bundle_count
    selected = bundles[: max(1, min(int(max_bundles), 1_000))]
    if len(selected) < len(bundles):
        state["scan_truncated"] = True
    remaining_bytes = max(0, int(max_checksum_bytes))

    def checksum_within_budget(path: Path) -> str | None:
        nonlocal remaining_bytes
        size = path.stat().st_size
        if size > remaining_bytes:
            state["scan_truncated"] = True
            return None
        remaining_bytes -= size
        state["checksummed_bytes"] += size
        return sha256_file(path).casefold()

    for bundle in selected:
        state["inspected_bundle_count"] += 1
        manifest_path = bundle / "manifest.json"
        bundle_invalid = False
        bundle_partial = False
        try:
            manifest = read_json_strict(
                manifest_path,
                max_bytes=max_manifest_bytes,
            )
        except DatasetStorageError:
            state["invalid_bundle_count"] += 1
            continue
        if (
            not isinstance(manifest, dict)
            or manifest.get("kind") != "atlas_dataset_library_backup"
            or not isinstance(manifest.get("files"), list)
        ):
            state["invalid_bundle_count"] += 1
            continue
        created_at = str(manifest.get("createdAt") or "").strip() or None
        if created_at and (
            state["latest_created_at"] is None
            or created_at > state["latest_created_at"]
        ):
            state["latest_created_at"] = created_at

        for file_record in manifest["files"]:
            if not isinstance(file_record, dict):
                bundle_invalid = True
                continue
            if file_record.get("exists") is False:
                continue
            relative = str(file_record.get("backupRelativePath") or "").strip()
            expected_hash = str(file_record.get("sha256") or "").strip().casefold()
            if not relative or len(expected_hash) != 64:
                bundle_invalid = True
                continue
            snapshot = bundle / relative
            if not _safe_unlinked_backup_file(snapshot, bundle):
                bundle_invalid = True
                continue
            size = snapshot.stat().st_size
            if size > remaining_bytes:
                bundle_partial = True
                state["unverified_file_count"] += 1
                state["scan_truncated"] = True
                continue
            remaining_bytes -= size
            state["checksummed_bytes"] += size
            if sha256_file(snapshot).casefold() != expected_hash:
                bundle_invalid = True
            else:
                state["verified_file_count"] += 1

        if bundle_invalid:
            state["invalid_bundle_count"] += 1
        elif bundle_partial:
            state["partially_verified_bundle_count"] += 1
        else:
            state["self_consistent_bundle_count"] += 1

        safety_path = bundle / _RECOVERY_SAFETY_MANIFEST
        if not safety_path.exists():
            continue
        state["recovery_safety_bundle_count"] += 1
        if not audit_available:
            state["audit_bound_unverified_bundle_count"] += 1
            continue
        audit_invalid = bundle_invalid or bundle_partial
        try:
            if not _safe_unlinked_backup_file(safety_path, bundle):
                raise ValueError("unsafe safety manifest")
            safety_sha = checksum_within_budget(safety_path)
            if safety_sha is None:
                raise OverflowError("safety manifest exceeds checksum budget")
            safety = read_json_strict(
                safety_path,
                max_bytes=max_manifest_bytes,
            )
            if (
                not isinstance(safety, dict)
                or safety.get("schema_version")
                != "atlas.dataset-library-recovery-backup.v1"
            ):
                raise ValueError("invalid safety manifest")
            operation_id = str(safety.get("operation_id") or "").strip()
            if operation_id not in audit_references.get(safety_sha, set()):
                if audit_truncated:
                    raise OverflowError("audit reference scan was truncated")
                raise ValueError("safety manifest is not audit bound")
            declared_manifest = str(
                safety.get("storage_bundle_manifest") or ""
            ).strip()
            expected_manifest_sha = str(
                safety.get("storage_bundle_manifest_sha256") or ""
            ).strip().casefold()
            if (
                not declared_manifest
                or Path(declared_manifest).name != manifest_path.name
                or len(expected_manifest_sha) != 64
                or not _safe_unlinked_backup_file(manifest_path, bundle)
            ):
                raise ValueError("invalid bound storage manifest")
            actual_manifest_sha = checksum_within_budget(manifest_path)
            if (
                actual_manifest_sha is None
                or actual_manifest_sha != expected_manifest_sha
            ):
                raise ValueError("storage manifest checksum mismatch")
            persistence = safety.get("persistence_database")
            if not isinstance(persistence, dict):
                raise ValueError("missing persistence safety copy")
            persistence_relative = str(persistence.get("file") or "").strip()
            persistence_sha = str(persistence.get("sha256") or "").strip().casefold()
            expected_size = int(persistence.get("bytes"))
            persistence_path = bundle / persistence_relative
            if (
                not persistence_relative
                or len(persistence_sha) != 64
                or expected_size < 0
                or not _safe_unlinked_backup_file(persistence_path, bundle)
                or persistence_path.stat().st_size != expected_size
            ):
                raise ValueError("invalid persistence safety copy")
            actual_persistence_sha = checksum_within_budget(persistence_path)
            if (
                actual_persistence_sha is None
                or actual_persistence_sha != persistence_sha
                or not _sqlite_safety_copy_is_valid(persistence_path)
            ):
                raise ValueError("persistence safety copy failed verification")
        except OverflowError:
            state["scan_truncated"] = True
            state["audit_bound_unverified_bundle_count"] += 1
            continue
        except (DatasetStorageError, OSError, TypeError, ValueError):
            audit_invalid = True
        if audit_invalid:
            state["audit_bound_invalid_bundle_count"] += 1
        else:
            state["audit_bound_verified_bundle_count"] += 1
    return state


def run_bounded_integrity_scan(
    *,
    storage: DatasetLibraryStorage | None = None,
    database: Any = None,
    user_resolver: Callable[[str], Mapping[str, Any] | None] | None = None,
    limits: ReconciliationLimits | None = None,
) -> Dict[str, Any]:
    """Build the safe startup/admin integrity payload without mutating state."""

    selected_storage = storage or DatasetLibraryStorage()
    report: DatasetLibraryReconciliationReport = scan_dataset_library(
        selected_storage,
        database=database,
        user_resolver=user_resolver,
        deep_checksums=True,
        limits=limits or startup_reconciliation_limits(),
    )
    backups = inspect_backup_state(selected_storage, database=database)
    return {
        "status": "healthy" if report.healthy else "degraded",
        "reconciliation": report.to_dict(),
        "backup_state": backups,
        "automatic_recovery_performed": False,
    }


__all__ = [
    "inspect_backup_state",
    "run_bounded_integrity_scan",
    "startup_reconciliation_limits",
]
