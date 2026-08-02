"""Reconcile or recover one exact ATLAS Dataset Library version.

This is an offline maintenance command.  It never authenticates with browser
cookies, never chooses a first/latest version, and never activates a modeling
dataset selection.  Dry-run is fully read-only with respect to ATLAS stores.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_LIBRARY_ROOT = ROOT / "server" / "artifacts" / "datasets"
DEFAULT_SECURITY_DB = ROOT / "server" / "artifacts" / "security" / "atlas_security.db"
DEFAULT_PERSISTENCE_DB = ROOT / "server" / "data" / "atlas_local.db"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Inspect and print the exact mutation plan without writing ATLAS state.")
    mode.add_argument("--apply", action="store_true", help="Apply the proven exact recovery after creating an external backup.")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version-id", required=True)
    parser.add_argument("--project-id", help="Restore only this independently proven project relationship; never activates it.")
    parser.add_argument("--actor-user-id", required=True, help="Existing active ATLAS operator identity. No credential is accepted here.")
    parser.add_argument("--evidence-report", type=Path, required=True)
    parser.add_argument(
        "--trusted-tier1-container",
        type=Path,
        required=True,
        help="Exact independently trusted Tier 1 archive; no discovery or latest-file selection is performed.",
    )
    parser.add_argument(
        "--trusted-tier1-container-sha256",
        required=True,
        help="Expected SHA-256 for the exact Tier 1 archive.",
    )
    parser.add_argument("--backup-directory", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--dataset-library-root",
        type=Path,
        default=Path(os.getenv("ATLAS_DATASET_LIBRARY_ROOT", DEFAULT_LIBRARY_ROOT)),
    )
    parser.add_argument(
        "--security-db",
        type=Path,
        default=Path(os.getenv("ATLAS_SECURITY_DB_PATH", DEFAULT_SECURITY_DB)),
    )
    parser.add_argument(
        "--persistence-db",
        type=Path,
        default=Path(os.getenv("ATLAS_SQLITE_PATH", DEFAULT_PERSISTENCE_DB)),
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        help="Optional JSON report path. Keep this outside the Dataset Library root.",
    )
    return parser


def _is_within(path: Path, parent: Path) -> bool:
    path = path.resolve()
    parent = parent.resolve()
    return path == parent or parent in path.parents


def _paths_overlap(first: Path, second: Path) -> bool:
    first = first.expanduser().resolve()
    second = second.expanduser().resolve()
    return first == second or first in second.parents or second in first.parents


def _reported_evidence_paths(evidence_report: Path) -> list[Path]:
    try:
        payload = json.loads(evidence_report.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    sources = []
    for key in (
        "tier1_sources",
        "tier2_sources",
        "tier3_sources",
        "evidence_sources",
        "sources",
    ):
        values = payload.get(key) or []
        if not isinstance(values, list):
            continue
        for source in values:
            if not isinstance(source, dict):
                continue
            value = source.get("container_path") or source.get("containerPath")
            value = value or source.get("path")
            if str(value or "").strip():
                sources.append(Path(str(value)).expanduser().resolve())
    return sources


def _preflight_report_output(target: Path) -> None:
    """Prove that an atomic report can be staged before recovery begins."""

    probe: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.is_dir():
            raise OSError("report parent is not a directory")
        if target.exists():
            if not target.is_file():
                raise OSError("report target is not a file")
            # Opening without writing proves the existing target's write ACL
            # and catches Windows sharing locks before any recovery mutation.
            with target.open("r+b"):
                pass
        probe = target.parent / (
            f".atlas-recovery-report-preflight.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        with probe.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("preflight\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass


def _persist_report(target: Path, serialized: str) -> None:
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_cli_error(error_type: str, error: str) -> str:
    return json.dumps(
        {"ok": False, "error": error, "error_type": error_type},
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    library_root = args.dataset_library_root.expanduser().resolve()
    backup_directory = args.backup_directory.expanduser().resolve()
    evidence_report = args.evidence_report.expanduser().resolve()
    trusted_tier1_container = args.trusted_tier1_container.expanduser().resolve()
    report_output: Path | None = None
    if _is_within(backup_directory, ROOT):
        print(
            _safe_cli_error(
                "UnsafeBackupDirectory",
                "backup_directory must be outside the ATLAS repository",
            )
        )
        return 2
    if args.report_output:
        report_output = args.report_output.expanduser().resolve()
        security_database = args.security_db.expanduser().resolve()
        persistence_database = args.persistence_db.expanduser().resolve()
        protected_paths = [
            library_root,
            library_root / "registry.json",
            library_root / "project_links.json",
            security_database,
            Path(f"{security_database}-wal"),
            Path(f"{security_database}-shm"),
            persistence_database,
            Path(f"{persistence_database}-wal"),
            Path(f"{persistence_database}-shm"),
            evidence_report,
            trusted_tier1_container,
            backup_directory,
            *_reported_evidence_paths(evidence_report),
        ]
        if any(_paths_overlap(report_output, protected) for protected in protected_paths):
            print(
                _safe_cli_error(
                    "UnsafeReportPath",
                    "report_output overlaps an ATLAS authority, artifact, evidence, trust-anchor, or backup path",
                )
            )
            return 2
        try:
            _preflight_report_output(report_output)
        except OSError:
            print(
                _safe_cli_error(
                    "UnsafeReportPath",
                    "report_output parent is unavailable or not writable",
                )
            )
            return 2

    # Bind every cached server path before importing the recovery/storage
    # modules.  This ordering is also what makes subprocess tests incapable of
    # inheriting the developer's live Dataset Library accidentally.
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(library_root)
    os.environ["ATLAS_SECURITY_DB_PATH"] = str(args.security_db.expanduser().resolve())
    os.environ["ATLAS_SQLITE_PATH"] = str(args.persistence_db.expanduser().resolve())

    from server.datasets.dataset_recovery import (  # noqa: PLC0415
        DatasetRecoveryAuthorizationError,
        DatasetRecoveryConflictError,
        DatasetRecoveryError,
        DatasetRecoveryEvidenceError,
        DatasetRecoveryRequest,
        DatasetRecoveryService,
        sanitized_report,
    )
    from server.datasets.dataset_storage import (  # noqa: PLC0415
        DatasetLibraryPaths,
        DatasetLibraryStorage,
        DatasetStorageError,
    )

    paths = DatasetLibraryPaths.from_environment(backup_root=backup_directory)
    storage = DatasetLibraryStorage(paths)
    request = DatasetRecoveryRequest(
        dataset_id=args.dataset_id,
        dataset_version_id=args.dataset_version_id,
        project_id=args.project_id,
        actor_user_id=args.actor_user_id,
        evidence_report=evidence_report,
        trusted_tier1_container=trusted_tier1_container,
        trusted_tier1_container_sha256=args.trusted_tier1_container_sha256,
        backup_directory=backup_directory,
        reason=args.reason,
    )
    service = DatasetRecoveryService(
        storage=storage,
        security_database=args.security_db,
        persistence_database=args.persistence_db,
    )

    def failure_report(exc: Exception) -> dict[str, object]:
        attached = getattr(exc, "recovery_report", None)
        if isinstance(attached, dict):
            return attached
        return {
            "mode": "apply" if args.apply else "dry_run",
            "scope": {
                "dataset_id": args.dataset_id,
                "dataset_version_id": args.dataset_version_id,
                "project_id": args.project_id,
            },
            "backup": None,
            "mutation": {
                "attempted": False,
                "applied": False,
                "rolled_back": False,
                "rollback_complete": True,
            },
            "audit": None,
        }

    try:
        report = service.apply(request) if args.apply else service.plan(request)
        output = {"ok": True, **sanitized_report(report)}
        exit_code = 0
    except DatasetRecoveryAuthorizationError as exc:
        output = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "recovery_report": failure_report(exc),
        }
        exit_code = 3
    except DatasetRecoveryEvidenceError as exc:
        output = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "recovery_report": failure_report(exc),
        }
        exit_code = 4
    except DatasetRecoveryConflictError as exc:
        output = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "recovery_report": failure_report(exc),
        }
        exit_code = 5
    except (DatasetRecoveryError, DatasetStorageError) as exc:
        output = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "recovery_report": failure_report(exc),
        }
        exit_code = 6
    except Exception as exc:  # safe final boundary; never print a traceback/path
        output = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": "Dataset Library recovery failed closed before completion.",
            "recovery_report": failure_report(exc),
        }
        exit_code = 7

    serialized = json.dumps(output, indent=2, sort_keys=True)
    if report_output is not None:
        try:
            _persist_report(report_output, serialized)
        except OSError:
            recovery_report = output.get("recovery_report")
            if not isinstance(recovery_report, dict):
                recovery_report = {
                    key: value for key, value in output.items() if key != "ok"
                }
            persistence_failure = {
                "ok": False,
                "error_type": "ReportPersistenceError",
                "error": "The recovery result was computed but the requested JSON report could not be persisted.",
                "operation_succeeded": bool(output.get("ok")),
                "service_exit_code": exit_code,
                "recovery_report": recovery_report,
            }
            if not output.get("ok"):
                persistence_failure["service_error_type"] = output.get("error_type")
                persistence_failure["service_error"] = output.get("error")
            print(json.dumps(persistence_failure, indent=2, sort_keys=True))
            return 8
    print(serialized)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
