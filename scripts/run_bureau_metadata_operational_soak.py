"""Isolated synthetic long-run soak for the bureau catalog operational layer.

The command intentionally requires an explicit, already-created durable root.
It never discovers a default root, never opens an ATLAS project or dataset, and
never starts or stops a live service.  All catalog content is synthetic.  The
root is claimed with a marker before any authority is created so an accidental
reference to a live or vendor-bearing catalog root fails closed.

The default release workload is deliberately fixed at or above the acceptance
minimums.  Focused tests can instantiate :class:`SoakSettings` with
``enforce_release_minimums=False``; that switch is not exposed by the CLI.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import statistics
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlparse
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.bureau_metadata.catalog_registry import ALLOWED_ENTITLEMENT_OPERATIONS
from server.bureau_metadata.catalog_registry import CatalogRegistryNotFoundError
from server.bureau_metadata.catalog_service import BureauCatalogAccessDeniedError
from server.bureau_metadata.catalog_store import BureauCatalogIntegrityError
from server.bureau_metadata.crosswalk_governance import (
    CrosswalkAuditMetadata,
    CrosswalkEvidenceReference,
    CrosswalkLineage,
    GovernedMappingDecision,
    calculate_revision_checksum,
)
from server.bureau_metadata.crosswalk_governance_repository import (
    CrosswalkGovernanceConflictError,
    CrosswalkGovernanceNotFoundError,
    SQLiteGovernedCrosswalkRepository,
)
from server.bureau_metadata.crosswalk_governance_service import (
    CrosswalkGovernanceAccessDeniedError,
    CrosswalkGovernanceLineageError,
    GovernedCrosswalkService,
)
from server.bureau_metadata.normalizer import (
    canonical_json_bytes,
    catalog_relative_directory,
)
from server.bureau_metadata.operational_service import (
    CatalogSearchTimeoutError,
    OperationalCatalogService,
)
from server.bureau_metadata.restricted_storage import (
    validate_restricted_metadata_root,
)
from server.bureau_metadata.types import (
    BureauAttributeDefinition,
    BureauAttributeMatchCandidate,
    BureauCatalogAccessContext,
    BureauCatalogFileDescriptor,
    BureauCatalogKey,
    BureauCatalogLicenseMetadata,
    BureauCatalogManifest,
    BureauCatalogSourceDescriptor,
    BureauDatasetCrosswalk,
    BureauSourceReference,
    BureauSpecialValueDefinition,
)
from server.bureau_metadata.validation import (
    attribute_record_checksum,
    calculate_catalog_checksum,
    catalog_governance_payload,
    special_definition_checksum,
    special_definition_id,
)


DEFAULT_DURATION_SECONDS = 1_800
MIN_USERS = 25
MIN_PROJECTS = 10
MIN_CATALOG_VERSIONS = 3
MIN_BOUNDED_OPERATIONS = 10_000
MIN_CROSSWALK_PREVIEWS = 1_000
MIN_DECISION_WRITES = 250
MIN_SERVICE_RELOADS = 10
MIN_FRONTEND_AUTHENTICATED_RELOADS = 10
DEFAULT_UNAUTHORIZED_ATTEMPTS = 250
DEFAULT_CONFLICT_TRIALS = 25
ROOT_MARKER = "synthetic_catalog_soak_root.json"
EVIDENCE_DIRECTORY = "soak-evidence"
RELOAD_PROBE_DIRECTORY = "reload-probes"
MAX_RELOAD_PROBE_BYTES = 2 * 1024 * 1024
MAX_FRONTEND_EVIDENCE_BYTES = 64 * 1024
FRONTEND_RELOAD_EVIDENCE_CLASSIFICATION = (
    "synthetic_authenticated_catalog_frontend_reload"
)
LIVE_FRONTEND_PORT = 5174
LIVE_BACKEND_PORT = 8001
DEFAULT_MAX_RSS_GROWTH_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_HANDLE_GROWTH = 32
SYNTHETIC_ATTRIBUTE_COUNT = 32
ALL_OPERATIONS = tuple(sorted(ALLOWED_ENTITLEMENT_OPERATIONS))
REQUIRED_MAPPED_AUTHORITIES = frozenset(
    {
        "restricted-catalog",
        "catalog-registry",
        "temporary-files",
        "browser-profile",
        "browser-downloads",
        "test-output",
        "frontend-build",
    }
)


class SoakConfigurationError(RuntimeError):
    """The requested run cannot prove that it is isolated and synthetic."""


class SoakInvariantError(RuntimeError):
    """A functional or isolation release gate failed during the soak."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _jsonl(records: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(record)) + b"\n" for record in records)


def _descriptor(path: Path, count: int) -> BureauCatalogFileDescriptor:
    payload = path.read_bytes()
    return BureauCatalogFileDescriptor(
        relative_path=path.name,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        record_count=count,
    )


@dataclass(frozen=True, slots=True)
class SoakSettings:
    root: Path | None = None
    duration_seconds: float = DEFAULT_DURATION_SECONDS
    user_count: int = MIN_USERS
    project_count: int = MIN_PROJECTS
    catalog_version_count: int = MIN_CATALOG_VERSIONS
    bounded_operation_count: int = MIN_BOUNDED_OPERATIONS
    crosswalk_preview_count: int = MIN_CROSSWALK_PREVIEWS
    decision_write_count: int = MIN_DECISION_WRITES
    service_reload_count: int = MIN_SERVICE_RELOADS
    unauthorized_attempt_count: int = DEFAULT_UNAUTHORIZED_ATTEMPTS
    conflict_trial_count: int = DEFAULT_CONFLICT_TRIALS
    max_workers: int = MIN_USERS
    heartbeat_seconds: float = 60.0
    enforce_release_minimums: bool = True
    authority_map: Path | None = None
    frontend_reload_evidence: Path | None = None
    frontend_authenticated_reload_minimum: int = MIN_FRONTEND_AUTHENTICATED_RELOADS
    max_rss_growth_bytes: int = DEFAULT_MAX_RSS_GROWTH_BYTES
    max_handle_growth: int = DEFAULT_MAX_HANDLE_GROWTH

    def validate(self) -> Path:
        paths = self.resolve_authority_paths()
        root = paths.restricted_catalog_root
        self._validate_workload()
        if self.enforce_release_minimums:
            if self.frontend_reload_evidence is None:
                raise SoakConfigurationError(
                    "Release soak requires explicit synthetic authenticated frontend "
                    "reload evidence."
                )
            _load_frontend_reload_evidence(
                Path(self.frontend_reload_evidence),
                minimum_reloads=self.frontend_authenticated_reload_minimum,
                allowed_evidence_root=paths.evidence_root,
            )
        return root

    def resolve_authority_paths(self) -> "SoakAuthorityPaths":
        if self.authority_map is not None:
            if self.root is not None:
                raise SoakConfigurationError(
                    "Specify either an isolated root or an authority map, not both."
                )
            return _load_authority_map(Path(self.authority_map))
        if self.root is None:
            raise SoakConfigurationError(
                "An explicit isolated root or authority map is required."
            )
        root = Path(self.root).expanduser()
        if not root.is_absolute():
            raise SoakConfigurationError("The isolated soak root must be absolute.")
        if not root.exists() or not root.is_dir():
            raise SoakConfigurationError(
                "The explicit isolated soak root must already exist as a directory."
            )
        exact = root.resolve(strict=True)
        return SoakAuthorityPaths(
            restricted_catalog_root=exact,
            evidence_root=exact / EVIDENCE_DIRECTORY,
            temporary_root=None,
            browser_profile_root=None,
            browser_downloads_root=None,
            frontend_build_root=None,
            authority_map_checksum=None,
            mapped_authority_count=0,
            authority_map_run_id=None,
            top_level_authority_identities=(),
            per_run_children_allocated=False,
        )

    def _validate_workload(self) -> None:
        scalar_minimums = {
            "duration_seconds": (self.duration_seconds, 0),
            "user_count": (self.user_count, 2),
            "project_count": (self.project_count, 1),
            "catalog_version_count": (self.catalog_version_count, 1),
            "bounded_operation_count": (self.bounded_operation_count, 1),
            "crosswalk_preview_count": (self.crosswalk_preview_count, 1),
            "decision_write_count": (self.decision_write_count, self.project_count),
            "service_reload_count": (self.service_reload_count, 1),
            "unauthorized_attempt_count": (self.unauthorized_attempt_count, 1),
            "conflict_trial_count": (self.conflict_trial_count, 1),
            "max_workers": (self.max_workers, 2),
            "heartbeat_seconds": (self.heartbeat_seconds, 0.01),
            "frontend_authenticated_reload_minimum": (
                self.frontend_authenticated_reload_minimum,
                0,
            ),
            "max_rss_growth_bytes": (self.max_rss_growth_bytes, 0),
            "max_handle_growth": (self.max_handle_growth, 0),
        }
        for label, (actual, minimum) in scalar_minimums.items():
            if actual < minimum:
                raise SoakConfigurationError(f"{label} must be at least {minimum}.")
        if self.enforce_release_minimums:
            release_minimums = {
                "duration_seconds": (self.duration_seconds, DEFAULT_DURATION_SECONDS),
                "user_count": (self.user_count, MIN_USERS),
                "project_count": (self.project_count, MIN_PROJECTS),
                "catalog_version_count": (
                    self.catalog_version_count,
                    MIN_CATALOG_VERSIONS,
                ),
                "bounded_operation_count": (
                    self.bounded_operation_count,
                    MIN_BOUNDED_OPERATIONS,
                ),
                "crosswalk_preview_count": (
                    self.crosswalk_preview_count,
                    MIN_CROSSWALK_PREVIEWS,
                ),
                "decision_write_count": (
                    self.decision_write_count,
                    MIN_DECISION_WRITES,
                ),
                "service_reload_count": (
                    self.service_reload_count,
                    MIN_SERVICE_RELOADS,
                ),
                "max_workers": (self.max_workers, MIN_USERS),
                "frontend_authenticated_reload_minimum": (
                    self.frontend_authenticated_reload_minimum,
                    MIN_FRONTEND_AUTHENTICATED_RELOADS,
                ),
            }
            below = [
                f"{label}={actual} (minimum {minimum})"
                for label, (actual, minimum) in release_minimums.items()
                if actual < minimum
            ]
            if below:
                raise SoakConfigurationError(
                    "Release soak minimums are not satisfied: " + "; ".join(below)
                )


@dataclass(frozen=True, slots=True)
class SoakAuthorityPaths:
    restricted_catalog_root: Path
    evidence_root: Path
    temporary_root: Path | None
    browser_profile_root: Path | None
    browser_downloads_root: Path | None
    frontend_build_root: Path | None
    authority_map_checksum: str | None
    mapped_authority_count: int
    authority_map_run_id: str | None
    top_level_authority_identities: tuple[tuple[str, str], ...]
    per_run_children_allocated: bool


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return True
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return path.is_symlink() or bool(attributes & reparse_flag)


def _load_authority_map(path: Path) -> SoakAuthorityPaths:
    exact_map = Path(path).expanduser()
    if not exact_map.is_absolute() or not exact_map.is_file():
        raise SoakConfigurationError(
            "The isolated authority map must be an explicit existing file."
        )
    raw = exact_map.read_bytes()
    if len(raw) > MAX_RELOAD_PROBE_BYTES:
        raise SoakConfigurationError("The isolated authority map is unbounded.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoakConfigurationError("The isolated authority map is invalid.") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") not in {1, "1"}:
        raise SoakConfigurationError("The isolated authority map schema is unsupported.")
    authority_map_run_id = str(payload.get("run_id") or "").strip()
    if (
        not authority_map_run_id
        or len(authority_map_run_id) > 128
        or any(ord(character) < 32 or ord(character) == 127 for character in authority_map_run_id)
    ):
        raise SoakConfigurationError("The isolated authority map run identity is invalid.")

    base = Path(str(payload.get("base_root") or "")).resolve(strict=True)
    repository = Path(str(payload.get("repository_root") or "")).resolve(strict=True)
    windows_temp = Path(str(payload.get("windows_temp_root") or "")).resolve(strict=True)
    if repository != ROOT.resolve(strict=True):
        raise SoakConfigurationError(
            "The authority map is bound to a different repository identity."
        )
    if exact_map.resolve(strict=True).parent != base:
        raise SoakConfigurationError(
            "The authority map must remain directly under its isolated base."
        )
    if _paths_overlap(base, repository) or _paths_overlap(base, windows_temp):
        raise SoakConfigurationError(
            "The mapped authority base overlaps the repository or Windows Temp."
        )

    raw_authorities = payload.get("authorities")
    if not isinstance(raw_authorities, list) or not raw_authorities or len(raw_authorities) > 100:
        raise SoakConfigurationError("The isolated authority inventory is missing or unbounded.")
    authorities: dict[str, Path] = {}
    for item in raw_authorities:
        if not isinstance(item, Mapping):
            raise SoakConfigurationError("An isolated authority entry is invalid.")
        name = str(item.get("authority") or "").strip()
        if not name or name in authorities:
            raise SoakConfigurationError("Mapped authority names must be nonblank and unique.")
        if (
            item.get("classification") != "isolated"
            or item.get("overlap_result") != "distinct"
            or item.get("reparse_point") is not False
        ):
            raise SoakConfigurationError("A mapped authority is not classified as isolated.")
        candidate = Path(str(item.get("canonical_path") or "")).resolve(strict=True)
        if not candidate.is_dir() or candidate.parent != base or _is_reparse_point(candidate):
            raise SoakConfigurationError(
                "Mapped authorities must be existing non-reparse siblings of the base."
            )
        if _paths_overlap(candidate, repository) or _paths_overlap(candidate, windows_temp):
            raise SoakConfigurationError(
                "A mapped authority overlaps the repository or Windows Temp."
            )
        if any(_paths_overlap(candidate, prior) for prior in authorities.values()):
            raise SoakConfigurationError("Mapped authorities overlap one another.")
        authorities[name] = candidate

    missing = REQUIRED_MAPPED_AUTHORITIES - set(authorities)
    if missing:
        raise SoakConfigurationError(
            "The isolated authority map is missing required authorities: "
            + ", ".join(sorted(missing))
            + "."
        )
    return SoakAuthorityPaths(
        restricted_catalog_root=authorities["restricted-catalog"],
        evidence_root=authorities["test-output"],
        temporary_root=authorities["temporary-files"],
        browser_profile_root=authorities["browser-profile"],
        browser_downloads_root=authorities["browser-downloads"],
        frontend_build_root=authorities["frontend-build"],
        authority_map_checksum=hashlib.sha256(raw).hexdigest(),
        mapped_authority_count=len(authorities),
        authority_map_run_id=authority_map_run_id,
        top_level_authority_identities=tuple(
            (
                name,
                _sha(
                    {
                        "authority_map_run_id": authority_map_run_id,
                        "authority": name,
                        "canonical_path": str(authorities[name]),
                    }
                ),
            )
            for name in ("restricted-catalog", "temporary-files", "test-output")
        ),
        per_run_children_allocated=False,
    )


def _allocate_run_authority_children(
    paths: SoakAuthorityPaths,
    *,
    run_id: str,
) -> SoakAuthorityPaths:
    """Allocate one disjoint child per soak under mapped parent authorities."""

    if paths.authority_map_checksum is None:
        return paths
    child_name = "catalog-soak-" + _sha({"run_id": run_id})[:24]

    def allocate(parent: Path | None, label: str) -> Path:
        if parent is None:
            raise SoakConfigurationError(
                f"The mapped {label} authority is unavailable."
            )
        exact_parent = Path(parent).resolve(strict=True)
        if not exact_parent.is_dir() or _is_reparse_point(exact_parent):
            raise SoakConfigurationError(
                f"The mapped {label} authority is unsafe."
            )
        child = exact_parent / child_name
        if child.exists():
            raise SoakConfigurationError(
                f"The mapped {label} run authority already exists."
            )
        child.mkdir(parents=False, exist_ok=False)
        exact_child = child.resolve(strict=True)
        if (
            exact_child.parent != exact_parent
            or not exact_child.is_dir()
            or _is_reparse_point(exact_child)
        ):
            raise SoakConfigurationError(
                f"The mapped {label} run authority escaped containment."
            )
        return exact_child

    restricted_child = allocate(paths.restricted_catalog_root, "restricted-catalog")
    evidence_child = allocate(paths.evidence_root, "test-output")
    temporary_child = allocate(paths.temporary_root, "temporary-files")
    return SoakAuthorityPaths(
        restricted_catalog_root=restricted_child,
        evidence_root=evidence_child,
        temporary_root=temporary_child,
        browser_profile_root=paths.browser_profile_root,
        browser_downloads_root=paths.browser_downloads_root,
        frontend_build_root=paths.frontend_build_root,
        authority_map_checksum=paths.authority_map_checksum,
        mapped_authority_count=paths.mapped_authority_count,
        authority_map_run_id=paths.authority_map_run_id,
        top_level_authority_identities=paths.top_level_authority_identities,
        per_run_children_allocated=True,
    )


def _frontend_reload_evidence_checksum(payload: Mapping[str, Any]) -> str:
    return _sha(
        {
            key: value
            for key, value in payload.items()
            if key != "evidence_checksum"
        }
    )


def _validated_isolated_origin(value: object, *, label: str) -> str:
    origin = str(value or "").strip()
    parsed = urlparse(origin)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SoakConfigurationError(
            f"Frontend reload evidence {label} has an invalid port."
        ) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise SoakConfigurationError(
            f"Frontend reload evidence {label} must be a bounded isolated origin."
        )
    if port in {LIVE_FRONTEND_PORT, LIVE_BACKEND_PORT}:
        raise SoakConfigurationError(
            "Frontend reload evidence references a prohibited live service port."
        )
    return origin


def _load_frontend_reload_evidence(
    path: Path,
    *,
    minimum_reloads: int,
    allowed_evidence_root: Path,
) -> Mapping[str, Any]:
    exact = Path(path).expanduser()
    if not exact.is_absolute() or not exact.is_file():
        raise SoakConfigurationError(
            "Frontend reload evidence must be an explicit existing file."
        )
    allowed = Path(allowed_evidence_root).resolve(strict=True)
    resolved = exact.resolve(strict=True)
    if resolved == allowed or allowed not in resolved.parents:
        raise SoakConfigurationError(
            "Frontend reload evidence must remain under the isolated test-output authority."
        )
    raw = resolved.read_bytes()
    if len(raw) > MAX_FRONTEND_EVIDENCE_BYTES:
        raise SoakConfigurationError("Frontend reload evidence is unbounded.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoakConfigurationError("Frontend reload evidence is invalid.") from exc
    if not isinstance(payload, Mapping):
        raise SoakConfigurationError("Frontend reload evidence must be one JSON object.")
    evidence = dict(payload)
    allowed_keys = {
        "schema_version",
        "classification",
        "run_id",
        "created_at",
        "frontend_origin",
        "backend_origin",
        "authenticated_reload_attempts",
        "authenticated_reload_successes",
        "synthetic_user_count",
        "synthetic_project_count",
        "synthetic_provider_count",
        "authentication_failures",
        "unexpected_failures",
        "cross_user_contamination",
        "cross_project_contamination",
        "cross_provider_contamination",
        "browser_profile_isolated",
        "contains_vendor_content",
        "live_authority_accessed",
        "live_port_contacted",
        "evidence_checksum",
    }
    if set(evidence) != allowed_keys:
        raise SoakConfigurationError(
            "Frontend reload evidence fields are missing or unsupported."
        )
    if (
        evidence.get("schema_version") != "1.0"
        or evidence.get("classification") != FRONTEND_RELOAD_EVIDENCE_CLASSIFICATION
        or evidence.get("evidence_checksum")
        != _frontend_reload_evidence_checksum(evidence)
    ):
        raise SoakConfigurationError(
            "Frontend reload evidence identity or checksum is contradictory."
        )
    _validated_isolated_origin(evidence.get("frontend_origin"), label="frontend_origin")
    _validated_isolated_origin(evidence.get("backend_origin"), label="backend_origin")

    def count(name: str) -> int:
        value = evidence.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SoakConfigurationError(
                f"Frontend reload evidence {name} must be a nonnegative integer."
            )
        return value

    attempts = count("authenticated_reload_attempts")
    successes = count("authenticated_reload_successes")
    if attempts < int(minimum_reloads) or successes != attempts:
        raise SoakConfigurationError(
            "Frontend authenticated reload coverage is incomplete."
        )
    if (
        count("synthetic_user_count") < 2
        or count("synthetic_project_count") < 2
        or count("synthetic_provider_count") < 2
        or count("authentication_failures") != 0
        or count("unexpected_failures") != 0
        or count("cross_user_contamination") != 0
        or count("cross_project_contamination") != 0
        or count("cross_provider_contamination") != 0
        or evidence.get("browser_profile_isolated") is not True
        or evidence.get("contains_vendor_content") is not False
        or evidence.get("live_authority_accessed") is not False
        or evidence.get("live_port_contacted") is not False
    ):
        raise SoakConfigurationError(
            "Frontend reload evidence failed its isolation or functional gates."
        )
    return {
        "status": "verified",
        "evidence_checksum": evidence["evidence_checksum"],
        "authenticated_reload_attempts": attempts,
        "authenticated_reload_successes": successes,
        "synthetic_user_count": count("synthetic_user_count"),
        "synthetic_project_count": count("synthetic_project_count"),
        "synthetic_provider_count": count("synthetic_provider_count"),
        "cross_user_contamination": 0,
        "cross_project_contamination": 0,
        "cross_provider_contamination": 0,
        "live_port_contacted": False,
    }


@dataclass(frozen=True, slots=True)
class SyntheticCatalogIdentity:
    key: BureauCatalogKey
    checksum: str
    catalog_version_id: str
    exact_directory: Path


@dataclass(slots=True)
class SoakMetrics:
    started_at: str
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    latencies_ms: list[float] = field(default_factory=list, repr=False)
    total_requests: int = 0
    successful_requests: int = 0
    bounded_operations: int = 0
    crosswalk_previews: int = 0
    decision_writes: int = 0
    expected_authorization_denials: int = 0
    concurrency_conflicts: int = 0
    unexpected_failures: int = 0
    timeouts: int = 0
    checksum_failures: int = 0
    expected_tamper_checksum_failures: int = 0
    unexpected_checksum_failures: int = 0
    tamper_probe_count: int = 0
    restart_recovery_failures: int = 0
    inconsistent_entitlement_results: int = 0
    cross_user_contamination: int = 0
    cross_tenant_contamination: int = 0
    cross_project_contamination: int = 0
    cross_provider_contamination: int = 0
    provider_isolation_checks: int = 0
    service_reload_cycles: int = 0
    reload_child_processes: int = 0
    exact_identity_negative_checks: int = 0
    independent_writer_instances: int = 0
    concurrent_alias_reviews: int = 0
    catalog_version_switches: int = 0
    timed_crosswalk_probes: int = 0
    timed_tamper_probes: int = 0
    tamper_detection_passed: bool = False
    tamper_cache_eviction_passed: bool = False
    tamper_recovery_passed: bool = False
    failures: list[Mapping[str, str]] = field(default_factory=list)

    def record_success(self, *, latency_ms: float, category: str) -> None:
        with self.lock:
            self.total_requests += 1
            self.successful_requests += 1
            self.latencies_ms.append(latency_ms)
            if category == "bounded_operation":
                self.bounded_operations += 1
            elif category == "crosswalk_preview":
                self.crosswalk_previews += 1
            elif category == "decision_write":
                self.decision_writes += 1

    def record_expected_denial(self, *, latency_ms: float) -> None:
        with self.lock:
            self.total_requests += 1
            self.expected_authorization_denials += 1
            self.latencies_ms.append(latency_ms)

    def record_conflict(self, *, latency_ms: float) -> None:
        with self.lock:
            self.total_requests += 1
            self.concurrency_conflicts += 1
            self.latencies_ms.append(latency_ms)

    def record_failure(self, scenario: str, exc: BaseException) -> None:
        with self.lock:
            self.total_requests += 1
            self.unexpected_failures += 1
            if isinstance(exc, CatalogSearchTimeoutError):
                self.timeouts += 1
            if isinstance(exc, BureauCatalogIntegrityError):
                self.checksum_failures += 1
                self.unexpected_checksum_failures += 1
            if len(self.failures) < 50:
                self.failures.append(
                    {
                        "scenario": scenario[:96],
                        "exception_type": type(exc).__name__[:96],
                    }
                )

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            latencies = sorted(self.latencies_ms)
            return {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "bounded_operations": self.bounded_operations,
                "crosswalk_previews": self.crosswalk_previews,
                "decision_writes": self.decision_writes,
                "expected_authorization_denials": self.expected_authorization_denials,
                "concurrency_conflicts": self.concurrency_conflicts,
                "unexpected_failures": self.unexpected_failures,
                "timeouts": self.timeouts,
                "latency_ms": _latency_summary(latencies),
                "latency_sample_count": len(latencies),
                "checksum_failures": self.checksum_failures,
                "expected_tamper_checksum_failures": self.expected_tamper_checksum_failures,
                "unexpected_checksum_failures": self.unexpected_checksum_failures,
                "tamper_probe_count": self.tamper_probe_count,
                "restart_recovery_failures": self.restart_recovery_failures,
                "inconsistent_entitlement_results": self.inconsistent_entitlement_results,
                "cross_user_contamination": self.cross_user_contamination,
                "cross_tenant_contamination": self.cross_tenant_contamination,
                "cross_project_contamination": self.cross_project_contamination,
                "cross_provider_contamination": self.cross_provider_contamination,
                "provider_isolation_checks": self.provider_isolation_checks,
                "service_reload_cycles": self.service_reload_cycles,
                "reload_child_processes": self.reload_child_processes,
                "exact_identity_negative_checks": self.exact_identity_negative_checks,
                "independent_writer_instances": self.independent_writer_instances,
                "concurrent_alias_reviews": self.concurrent_alias_reviews,
                "catalog_version_switches": self.catalog_version_switches,
                "timed_crosswalk_probes": self.timed_crosswalk_probes,
                "timed_tamper_probes": self.timed_tamper_probes,
                "tamper_detection_passed": self.tamper_detection_passed,
                "tamper_cache_eviction_passed": self.tamper_cache_eviction_passed,
                "tamper_recovery_passed": self.tamper_recovery_passed,
                "failures": list(self.failures),
            }


def _latency_summary(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "maximum": 0.0}
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "p50": round(float(statistics.median(ordered)), 6),
        "p95": round(float(ordered[p95_index]), 6),
        "maximum": round(float(ordered[-1]), 6),
    }


def _process_measurements() -> tuple[int | None, int | None]:
    try:
        import psutil  # type: ignore[import-not-found]

        process = psutil.Process(os.getpid())
        handles = process.num_handles() if hasattr(process, "num_handles") else None
        return int(process.memory_info().rss), int(handles) if handles is not None else None
    except Exception:
        return None, None


def _claim_isolated_root(root: Path) -> None:
    marker = root / ROOT_MARKER
    children = tuple(root.iterdir())
    if children and not marker.is_file():
        raise SoakConfigurationError(
            "The explicit soak root is nonempty and lacks the synthetic-isolation marker."
        )
    if marker.is_file():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SoakConfigurationError("The synthetic-isolation marker is invalid.") from exc
        if payload.get("classification") != "synthetic_isolated_catalog_soak":
            raise SoakConfigurationError("The root marker does not authorize synthetic soak use.")
        return
    payload = {
        "schema_version": "1.0",
        "classification": "synthetic_isolated_catalog_soak",
        "contains_vendor_content": False,
        "live_atlas_authority": False,
        "created_at": _utc_now(),
    }
    with marker.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


def _publish_synthetic_catalog(root: Path, version_number: int) -> tuple[BureauCatalogKey, str, Path, BureauCatalogManifest]:
    provider_number = 1 + ((version_number - 1) % 2)
    key = BureauCatalogKey(
        provider=f"Synthetic Bureau {provider_number}",
        product="Synthetic Operational Attributes",
        edition="Isolated Acceptance",
        dictionary_version=f"{version_number}.0",
    )
    source = BureauSourceReference(
        source_document_sha256=_sha({"synthetic_source": version_number}),
        source_locator=f"synthetic:{version_number}",
        extraction_method="manual_review",
    )
    attributes: list[dict[str, Any]] = []
    specials: list[dict[str, Any]] = []
    for index in range(SYNTHETIC_ATTRIBUTE_COUNT):
        code = f"SYN{index:03d}"
        attributes.append(
            {
                "catalog_key": key.model_dump(mode="json"),
                "sequence": index + 1,
                "attribute_code": code,
                "description": f"Synthetic operational field {index:03d}",
                "numeric_type": "integer",
                "ordinary_min": "0",
                "ordinary_max": str(100 + version_number),
                "source_references": [source.model_dump(mode="json")],
                "created_at": "2026-08-05T00:00:00Z",
            }
        )
        if index % 4 == 0:
            special_identity = {
                "catalog_key": key.model_dump(mode="json"),
                "attribute_code": code,
                "value_code": str(900 + version_number),
            }
            specials.append(
                {
                    **special_identity,
                    "meaning": f"Synthetic version {version_number} exception",
                    "definition_id": special_definition_id(special_identity),
                    "source_references": [source.model_dump(mode="json")],
                }
            )
    license_metadata = BureauCatalogLicenseMetadata(
        classification="internal_reference",
        policy_id="synthetic-soak-policy",
        policy_version="1",
        allowed_operations=frozenset(ALL_OPERATIONS),
        redistribution_status="prohibited",
        source_export_allowed=False,
        full_catalog_api_allowed=False,
        tenant_sharing_allowed=False,
        public_demo_allowed=False,
        legal_review_required=True,
    )
    checksum = calculate_catalog_checksum(
        schema_version="1.0",
        catalog_key=key,
        attributes=attributes,
        special_values=specials,
        reconciliation_findings=[],
        governance=catalog_governance_payload(
            license_metadata=license_metadata,
            restricted_export=True,
            full_catalog_path=".",
        ),
    )
    for record in attributes:
        record["catalog_checksum"] = checksum
        record["record_checksum"] = attribute_record_checksum(record)
    for record in specials:
        record["catalog_checksum"] = checksum
        record["definition_checksum"] = special_definition_checksum(record)
    typed_attributes = [
        BureauAttributeDefinition.model_validate(record).model_dump(mode="json")
        for record in attributes
    ]
    typed_specials = [
        BureauSpecialValueDefinition.model_validate(record).model_dump(mode="json")
        for record in specials
    ]
    exact = root.joinpath(*catalog_relative_directory(key, checksum).parts)
    if exact.exists():
        manifest = BureauCatalogManifest.model_validate_json(
            (exact / "catalog_manifest.json").read_bytes()
        )
        if manifest.catalog_checksum != checksum:
            raise SoakInvariantError("Existing synthetic catalog identity is contradictory.")
        return key, checksum, exact, manifest
    exact.mkdir(parents=True, exist_ok=False)
    attribute_path = exact / "attribute_definitions.jsonl"
    special_path = exact / "special_value_definitions.jsonl"
    attribute_path.write_bytes(_jsonl(typed_attributes))
    special_path.write_bytes(_jsonl(typed_specials))
    source_hash = _sha({"source": "synthetic", "version": version_number})
    manifest = BureauCatalogManifest(
        catalog_id=f"bureau-catalog-synthetic-operational-{provider_number}",
        catalog_key=key,
        catalog_checksum=checksum,
        attribute_file=_descriptor(attribute_path, len(typed_attributes)),
        special_value_file=_descriptor(special_path, len(typed_specials)),
        source_files=(
            BureauCatalogSourceDescriptor(
                role="canonical_pdf",
                filename="synthetic_source.pdf",
                suffix=".pdf",
                sha256=source_hash,
                size_bytes=0,
            ),
        ),
        attribute_count=len(typed_attributes),
        special_value_count=len(typed_specials),
        validation_status="passed",
        license=license_metadata,
        builder_name="synthetic-operational-soak",
        builder_version="1",
        built_at="2026-08-05T00:00:00Z",
        built_by="synthetic-soak",
        source_control_commit="synthetic",
    )
    (exact / "catalog_manifest.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    return key, checksum, exact, manifest


class _ProjectAuthorization:
    def __init__(self, memberships: Mapping[str, frozenset[str]]) -> None:
        self.memberships = dict(memberships)

    def authorize_project(
        self,
        context: BureauCatalogAccessContext,
        project_id: str,
        permission: str,
    ) -> bool:
        return permission in {"view", "edit"} and context.principal_id in self.memberships.get(
            project_id, frozenset()
        )


class _LineageAuthority:
    def __init__(self, lineages: Mapping[str, CrosswalkLineage]) -> None:
        self.lineages = dict(lineages)

    def current_lineage(
        self, context: BureauCatalogAccessContext, project_id: str
    ) -> CrosswalkLineage:
        if context.project_id != project_id or project_id not in self.lineages:
            raise KeyError("Synthetic project lineage is unavailable.")
        return self.lineages[project_id]


@dataclass(slots=True)
class _ResourceScope:
    """Release harness-owned adapters even when a scenario raises."""

    services: list[OperationalCatalogService] = field(default_factory=list)
    repositories: list[SQLiteGovernedCrosswalkRepository] = field(
        default_factory=list
    )

    def service(self, root: Path) -> OperationalCatalogService:
        instance = OperationalCatalogService(root)
        self.services.append(instance)
        return instance

    def repository(self, root: Path) -> SQLiteGovernedCrosswalkRepository:
        instance = SQLiteGovernedCrosswalkRepository(root)
        self.repositories.append(instance)
        return instance

    def release(self) -> None:
        for service in self.services:
            try:
                service.loader.clear()
            except Exception:
                pass
        self.services.clear()
        self.repositories.clear()
        gc.collect()


def _close_traceback_sqlite_connections(exc: BaseException) -> None:
    """Close incidental SQLite locals retained by a failed Python traceback."""

    seen: set[int] = set()
    traceback = exc.__traceback__
    while traceback is not None:
        for value in tuple(traceback.tb_frame.f_locals.values()):
            if isinstance(value, sqlite3.Connection) and id(value) not in seen:
                seen.add(id(value))
                try:
                    value.close()
                except sqlite3.Error:
                    pass
        traceback = traceback.tb_next


def _read_bounded_json(path: Path) -> Mapping[str, Any]:
    payload = path.read_bytes()
    if len(payload) > MAX_RELOAD_PROBE_BYTES:
        raise SoakInvariantError("The isolated reload probe exceeded its read limit.")
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise SoakInvariantError("The isolated reload probe payload is invalid.")
    return dict(decoded)


def _write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _require_probe_path(root: Path, path: Path) -> Path:
    exact = path.resolve(strict=False)
    if exact == root or root not in exact.parents:
        raise SoakConfigurationError(
            "Reload-probe evidence must remain inside the isolated root."
        )
    return exact


def _reload_probe_checksum(payload: Mapping[str, Any]) -> str:
    return _sha(
        {
            key: value
            for key, value in payload.items()
            if key != "payload_checksum"
        }
    )


def _execute_reload_probe(
    root: Path,
    probe_directory: Path,
    request_path: Path,
    result_path: Path,
) -> Mapping[str, Any]:
    """Validate exact durable state in a fresh isolated Python process."""

    root = validate_restricted_metadata_root(root)
    exact_probe_directory = Path(probe_directory).resolve(strict=True)
    if not exact_probe_directory.is_dir():
        raise SoakConfigurationError("Reload-probe authority is unavailable.")
    _require_probe_path(exact_probe_directory, request_path)
    _require_probe_path(exact_probe_directory, result_path)
    request = _read_bounded_json(request_path)
    if Path(str(request.get("root") or "")).resolve(strict=True) != root:
        raise SoakInvariantError("Reload-probe root identity is contradictory.")
    if request.get("payload_checksum") != _reload_probe_checksum(request):
        raise SoakInvariantError("Reload-probe request checksum verification failed.")
    probes = request.get("probes")
    if not isinstance(probes, list) or not probes or len(probes) > 100:
        raise SoakInvariantError("Reload-probe inventory is missing or unbounded.")

    memberships: dict[str, frozenset[str]] = {}
    lineages: dict[str, CrosswalkLineage] = {}
    normalized: list[tuple[Mapping[str, Any], CrosswalkLineage]] = []
    for raw_probe in probes:
        if not isinstance(raw_probe, Mapping):
            raise SoakInvariantError("Reload-probe entry is invalid.")
        probe = dict(raw_probe)
        lineage = CrosswalkLineage.model_validate(probe.get("lineage"))
        actor = str(probe.get("actor") or "")
        project_id = str(probe.get("project_id") or "")
        if project_id != lineage.project_id or not actor:
            raise SoakInvariantError("Reload-probe project identity is contradictory.")
        prior = lineages.get(project_id)
        if prior is not None and prior != lineage:
            raise SoakInvariantError("Reload-probe lineage inventory is contradictory.")
        lineages[project_id] = lineage
        memberships[project_id] = frozenset({actor})
        normalized.append((probe, lineage))

    service = OperationalCatalogService(root)
    repository = SQLiteGovernedCrosswalkRepository(root)
    governance = GovernedCrosswalkService(
        repository=repository,
        project_authorization=_ProjectAuthorization(memberships),
        catalog_entitlements=service.catalogs.entitlement_provider,
        lineage_authority=_LineageAuthority(lineages),
    )
    exact_checks = 0
    negative_checks = 0
    try:
        for probe, lineage in normalized:
            actor = str(probe["actor"])
            tenant = str(probe["tenant"])
            project_id = str(probe["project_id"])
            governance_id = str(probe["governance_id"])
            catalog_version_id = str(probe["catalog_version_id"])
            expected_revision = int(probe["expected_revision"])
            expected_checksum = str(probe["expected_checksum"])
            expected_history = tuple(str(value) for value in probe["history_checksums"])
            expected_decisions_checksum = str(probe["decisions_checksum"])
            context = _context(actor, tenant, project_id)

            current = governance.get_current(
                context=context,
                lineage=lineage,
                governance_id=governance_id,
            )
            exact = governance.get_revision(
                context=context,
                lineage=lineage,
                governance_id=governance_id,
                revision=expected_revision,
            )
            history = governance.history(
                context=context,
                lineage=lineage,
                governance_id=governance_id,
            )
            health = service.catalog_health(
                principal_id=actor,
                tenant_id=tenant,
                catalog_version_id=catalog_version_id,
            )
            if (
                current != exact
                or current.revision != expected_revision
                or current.revision_checksum != expected_checksum
                or calculate_revision_checksum(current) != expected_checksum
                or tuple(item.revision_checksum for item in history)
                != expected_history
                or _sha(
                    [item.model_dump(mode="json") for item in current.decisions]
                )
                != expected_decisions_checksum
                or health.get("catalog_version_id") != catalog_version_id
            ):
                raise SoakInvariantError(
                    "Fresh-process exact catalog or crosswalk recovery contradicted evidence."
                )
            exact_checks += 4

            try:
                governance.get_current(
                    context=context,
                    lineage=lineage,
                    governance_id=governance_id + "-unknown",
                )
            except CrosswalkGovernanceNotFoundError:
                negative_checks += 1
            else:
                raise SoakInvariantError("Unknown governance identity used a fallback.")

            try:
                governance.get_revision(
                    context=context,
                    lineage=lineage,
                    governance_id=governance_id,
                    revision=expected_revision + 1,
                )
            except CrosswalkGovernanceNotFoundError:
                negative_checks += 1
            else:
                raise SoakInvariantError("Missing exact revision used a fallback.")

            try:
                service.catalog_health(
                    principal_id=actor,
                    tenant_id=tenant,
                    catalog_version_id=catalog_version_id + "-unknown",
                )
            except CatalogRegistryNotFoundError:
                negative_checks += 1
            else:
                raise SoakInvariantError("Unknown catalog version used a fallback.")

            stale_lineage = lineage.model_copy(
                update={
                    "dataset_version_id": lineage.dataset_version_id + "-contradictory"
                }
            )
            try:
                governance.get_current(
                    context=context,
                    lineage=stale_lineage,
                    governance_id=governance_id,
                )
            except (CrosswalkGovernanceLineageError, CrosswalkGovernanceAccessDeniedError):
                negative_checks += 1
            else:
                raise SoakInvariantError("Contradictory lineage used a fallback.")
    finally:
        service.loader.clear()
        del governance
        del repository
        del service
        gc.collect()

    result = {
        "schema_version": "1.0",
        "passed": True,
        "request_checksum": request["payload_checksum"],
        "child_pid": os.getpid(),
        "probe_count": len(normalized),
        "exact_checks": exact_checks,
        "negative_checks": negative_checks,
    }
    _write_exclusive_json(result_path, result)
    return result


def _run_reload_probe_subprocess(
    *,
    root: Path,
    evidence_root: Path,
    run_id: str,
    cycle: int,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    evidence = evidence_root / RELOAD_PROBE_DIRECTORY
    request_path = evidence / f"{run_id}-reload-{cycle:04d}-request.json"
    result_path = evidence / f"{run_id}-reload-{cycle:04d}-result.json"
    request = {
        "schema_version": "1.0",
        "root": str(root),
        "run_id": run_id,
        "cycle": cycle,
        **dict(payload),
    }
    request["payload_checksum"] = _reload_probe_checksum(request)
    _write_exclusive_json(request_path, request)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_bureau_metadata_operational_soak",
            "--internal-reload-probe",
            str(root),
            str(evidence),
            str(request_path),
            str(result_path),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not result_path.is_file():
        raise SoakInvariantError("The fresh-process reload probe failed safely.")
    result = _read_bounded_json(result_path)
    if (
        result.get("passed") is not True
        or result.get("request_checksum") != request["payload_checksum"]
        or int(result.get("child_pid") or 0) in {0, os.getpid()}
    ):
        raise SoakInvariantError("The fresh-process reload evidence is contradictory.")
    return result


def _audit(actor: str, reason: str) -> CrosswalkAuditMetadata:
    return CrosswalkAuditMetadata(
        actor_id=actor,
        request_id="soak-request-" + uuid.uuid4().hex,
        occurred_at=_utc_now(),
        reason=reason,
    )


def _decision(
    actor: str, *, alias_reference: str | None = None
) -> GovernedMappingDecision:
    created = _utc_now()
    evidence_kinds = (
        ("institutional_alias", "analyst_review")
        if alias_reference is not None
        else ("catalog_definition", "exact_match", "analyst_review")
    )
    references = tuple(
        CrosswalkEvidenceReference(
            evidence_id=(
                alias_reference
                if kind == "institutional_alias" and alias_reference is not None
                else f"synthetic-evidence-{kind}-{uuid.uuid4().hex[:12]}"
            ),
            evidence_kind=kind,  # type: ignore[arg-type]
            authority_id=(
                "synthetic-soak-alias-authority"
                if kind == "institutional_alias"
                else "synthetic-soak-evidence"
            ),
            checksum=_sha({"kind": kind, "actor": actor, "created": created}),
            created_by=actor,
            created_at=created,
        )
        for kind in evidence_kinds
    )
    if alias_reference is not None:
        return GovernedMappingDecision(
            dataset_field="SYNTHETIC_SCORE_ALIAS",
            mapping_state="approved_alias",
            candidate_attribute_code="SYN000",
            evidence=references,
            analyst_confirmed=True,
            rationale="Synthetic institutional alias acceptance evidence.",
            alias_authority_id="synthetic-soak-alias-authority",
            institutional_alias_reference=alias_reference,
            reviewer_id=actor,
        )
    return GovernedMappingDecision(
        dataset_field="SYN000",
        mapping_state="exact_verified",
        candidate_attribute_code="SYN000",
        evidence=references,
        analyst_confirmed=True,
        rationale="Synthetic exact-code acceptance evidence.",
        reviewer_id=actor,
    )


def _source_crosswalk(
    *,
    project_id: str,
    lineage: CrosswalkLineage,
    actor: str,
    alias_reference: str | None = None,
) -> BureauDatasetCrosswalk:
    mapping = BureauAttributeMatchCandidate(
        dataset_field=(
            "SYNTHETIC_SCORE_ALIAS" if alias_reference is not None else "SYN000"
        ),
        catalog_key=lineage.catalog_key,
        catalog_checksum=lineage.catalog_checksum,
        candidate_attribute_code="SYN000",
        match_status=(
            "approved_institutional_alias"
            if alias_reference is not None
            else "exact_dictionary_code_match"
        ),
        confidence=1.0,
        institutional_alias_reference=alias_reference,
    )
    crosswalk_id = "synthetic-source-" + _sha(
        {"project_id": project_id, "catalog": lineage.catalog_checksum}
    )[:28]
    checksum = _sha(
        {
            "crosswalk_id": crosswalk_id,
            "project_id": project_id,
            "mapping": mapping.model_dump(mode="json"),
        }
    )
    return BureauDatasetCrosswalk(
        crosswalk_id=crosswalk_id,
        project_id=project_id,
        dataset_id=lineage.dataset_id,
        dataset_version_id=lineage.dataset_version_id,
        schema_checksum=lineage.schema_checksum,
        target_contract_id=lineage.target_contract_id,
        predictor_authorization_id=lineage.predictor_authorization_id,
        catalog_key=lineage.catalog_key,
        catalog_checksum=lineage.catalog_checksum,
        mappings=(mapping,),
        created_by=actor,
        created_at=_utc_now(),
        crosswalk_checksum=checksum,
    )


def _context(actor: str, tenant: str, project_id: str | None = None) -> BureauCatalogAccessContext:
    return BureauCatalogAccessContext(
        principal_id=actor,
        tenant_id=tenant,
        project_id=project_id,
    )


def _timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = call()
    return result, (time.perf_counter() - started) * 1_000.0


def _write_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


def _run_soak_impl(
    settings: SoakSettings,
    *,
    progress: Callable[[Mapping[str, Any]], None] | None = None,
    resources: _ResourceScope,
) -> Mapping[str, Any]:
    """Run one isolated synthetic soak and return aggregate-only metrics."""

    top_level_authority_paths = settings.resolve_authority_paths()
    settings.validate()
    run_id = "catalog-soak-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    authority_paths = _allocate_run_authority_children(
        top_level_authority_paths,
        run_id=run_id,
    )
    root = validate_restricted_metadata_root(
        authority_paths.restricted_catalog_root
    )
    _claim_isolated_root(root)
    if authority_paths.per_run_children_allocated:
        _claim_isolated_root(authority_paths.evidence_root)
        if authority_paths.temporary_root is None:
            raise SoakConfigurationError(
                "The mapped per-run temporary authority is unavailable."
            )
        _claim_isolated_root(authority_paths.temporary_root)
    frontend_reload_coverage: Mapping[str, Any]
    if settings.frontend_reload_evidence is not None:
        frontend_reload_coverage = _load_frontend_reload_evidence(
            Path(settings.frontend_reload_evidence),
            minimum_reloads=settings.frontend_authenticated_reload_minimum,
            allowed_evidence_root=top_level_authority_paths.evidence_root,
        )
    else:
        frontend_reload_coverage = {
            "status": "not_required_for_scaled_test",
            "authenticated_reload_attempts": 0,
            "authenticated_reload_successes": 0,
            "cross_user_contamination": 0,
            "cross_project_contamination": 0,
            "cross_provider_contamination": 0,
            "live_port_contacted": False,
        }
    evidence_root = authority_paths.evidence_root
    progress_path = evidence_root / f"{run_id}-progress.jsonl"
    summary_path = evidence_root / f"{run_id}-summary.json"
    temporary_entries_before = (
        frozenset(child.name for child in authority_paths.temporary_root.iterdir())
        if authority_paths.temporary_root is not None
        else frozenset()
    )
    metrics = SoakMetrics(started_at=_utc_now())
    wall_started = time.monotonic()
    memory_before, handles_before = _process_measurements()

    service = resources.service(root)
    catalogs_by_version_id: dict[str, SyntheticCatalogIdentity] = {}
    catalog_version_ids_by_number: dict[int, str] = {}
    catalog_numbers_by_version_id: dict[str, int] = {}
    for number in range(1, settings.catalog_version_count + 1):
        key, checksum, exact, manifest = _publish_synthetic_catalog(root, number)
        record = service.registry.register_manifest(
            manifest,
            storage_reference=f"restricted-catalog:synthetic-soak-{number}",
            actor="synthetic-catalog-administrator",
            country_or_region="synthetic",
            supported_bureau_versions=(f"synthetic-{number}",),
            provider_availability_metadata={"synthetic": True},
            leveling_metadata={"synthetic": True},
            archive_availability_metadata={"synthetic": False},
        )
        identity = SyntheticCatalogIdentity(
            key=key,
            checksum=checksum,
            catalog_version_id=record.catalog_version_id,
            exact_directory=exact,
        )
        catalogs_by_version_id[record.catalog_version_id] = identity
        catalog_version_ids_by_number[number] = record.catalog_version_id
        catalog_numbers_by_version_id[record.catalog_version_id] = number
    catalog_version_ids = tuple(sorted(catalogs_by_version_id))
    catalog_provider_count = len(
        {identity.key.provider for identity in catalogs_by_version_id.values()}
    )

    entitled_users = tuple(
        f"{run_id}-user-{index:02d}" for index in range(settings.user_count)
    )
    unauthorized_count = max(1, settings.user_count // 5)
    unauthorized_users = tuple(
        f"{run_id}-unauthorized-user-{index:02d}"
        for index in range(unauthorized_count)
    )
    users = entitled_users + unauthorized_users
    tenants = {
        user: f"{run_id}-tenant-{index % 5:02d}"
        for index, user in enumerate(users)
    }
    for user in entitled_users:
        for catalog_version_id in catalog_version_ids:
            service.registry.grant_entitlement(
                principal_id=user,
                tenant_id=tenants[user],
                catalog_version_id=catalog_version_id,
                operations=ALL_OPERATIONS,
                granted_by="synthetic-catalog-administrator",
            )

    project_ids_by_number = {
        index: f"{run_id}-project-{index:02d}"
        for index in range(settings.project_count)
    }
    projects = tuple(
        project_ids_by_number[index] for index in range(settings.project_count)
    )
    project_owners = {
        project: entitled_users[index % len(entitled_users)]
        for index, project in enumerate(projects)
    }
    memberships: dict[str, frozenset[str]] = {
        project: frozenset({project_owners[project]}) for project in projects
    }
    # One non-entitled user deliberately has project access only.  This proves
    # that project authorization never implies restricted-catalog entitlement.
    project_access_probe_id = project_ids_by_number[0]
    memberships[project_access_probe_id] = frozenset(
        {*memberships[project_access_probe_id], unauthorized_users[0]}
    )
    lineages: dict[str, CrosswalkLineage] = {}
    alias_references: dict[str, str | None] = {}
    catalog_version_ids_by_project: dict[str, str] = {}
    for index, project in enumerate(projects):
        catalog_version_id = catalog_version_ids[index % len(catalog_version_ids)]
        catalog_version_ids_by_project[project] = catalog_version_id
        catalog = catalogs_by_version_id[catalog_version_id]
        alias_references[project] = (
            f"synthetic-alias-policy-{index:02d}" if index % 2 else None
        )
        lineages[project] = CrosswalkLineage(
            project_id=project,
            dataset_id=f"{run_id}-dataset-{index:02d}",
            dataset_version_id=f"{run_id}-dataset-version-{index:02d}",
            activation_revision=1,
            target_contract_id=f"{run_id}-target-{index:02d}",
            predictor_authorization_id=f"{run_id}-predictors-{index:02d}",
            schema_checksum=_sha({"project": project, "schema": ["SYN000"]}),
            catalog_key=catalog.key,
            catalog_checksum=catalog.checksum,
        )

    decision_repository = resources.repository(root)

    def governance_service(
        repository: SQLiteGovernedCrosswalkRepository,
        catalog_service: OperationalCatalogService,
    ) -> GovernedCrosswalkService:
        return GovernedCrosswalkService(
            repository=repository,
            project_authorization=_ProjectAuthorization(memberships),
            catalog_entitlements=catalog_service.catalogs.entitlement_provider,
            lineage_authority=_LineageAuthority(lineages),
        )

    governance = governance_service(decision_repository, service)
    governance_ids: dict[str, str] = {}
    decisions: dict[str, tuple[GovernedMappingDecision, ...]] = {}
    for project in projects:
        actor = project_owners[project]
        lineage = lineages[project]
        alias_reference = alias_references[project]
        source = _source_crosswalk(
            project_id=project,
            lineage=lineage,
            actor=actor,
            alias_reference=alias_reference,
        )
        project_decisions = (
            _decision(actor, alias_reference=alias_reference),
        )
        record, latency = _timed(
            lambda p=project, a=actor, l=lineage, s=source, d=project_decisions: governance.register_candidate(
                context=_context(a, tenants[a], p),
                source=s,
                lineage=l,
                decisions=d,
                audit=_audit(a, "Synthetic initial crosswalk decision."),
            )
        )
        metrics.record_success(latency_ms=latency, category="decision_write")
        governance_ids[project] = record.governance_id
        decisions[project] = project_decisions

    def bounded_read(index: int) -> None:
        user = entitled_users[index % len(entitled_users)]
        catalog_version_id = catalog_version_ids[index % len(catalog_version_ids)]
        catalog = catalogs_by_version_id[catalog_version_id]
        operation = index % 4
        try:
            if operation == 0:
                _result, latency = _timed(
                    lambda: service.get_attribute(
                        principal_id=user,
                        tenant_id=tenants[user],
                        catalog_version_id=catalog.catalog_version_id,
                        attribute_code=f"SYN{index % SYNTHETIC_ATTRIBUTE_COUNT:03d}",
                    )
                )
            elif operation == 1:
                _result, latency = _timed(
                    lambda: service.search_attributes(
                        principal_id=user,
                        tenant_id=tenants[user],
                        catalog_version_id=catalog.catalog_version_id,
                        query=f"SYN{index % 10}",
                        offset=index % 3,
                        limit=7,
                    )
                )
            elif operation == 2:
                _result, latency = _timed(
                    lambda: service.list_special_values(
                        principal_id=user,
                        tenant_id=tenants[user],
                        catalog_version_id=catalog.catalog_version_id,
                        attribute_code=f"SYN{(index % 8) * 4:03d}",
                        offset=0,
                        limit=5,
                    )
                )
            else:
                _result, latency = _timed(
                    lambda: service.catalog_health(
                        principal_id=user,
                        tenant_id=tenants[user],
                        catalog_version_id=catalog.catalog_version_id,
                    )
                )
            metrics.record_success(latency_ms=latency, category="bounded_operation")
        except Exception as exc:
            metrics.record_failure("bounded_catalog_operation", exc)

    with ThreadPoolExecutor(max_workers=min(settings.max_workers, settings.user_count)) as pool:
        tuple(pool.map(bounded_read, range(settings.bounded_operation_count)))

    # Exercise explicit version switching without a first/latest selector.  Each
    # lookup is keyed by the exact registered catalog_version_id.
    prior_catalog_version_id: str | None = None
    switch_actor = entitled_users[0]
    for catalog_version_id in catalog_version_ids + catalog_version_ids:
        try:
            _health, latency = _timed(
                lambda c=catalog_version_id: service.catalog_health(
                    principal_id=switch_actor,
                    tenant_id=tenants[switch_actor],
                    catalog_version_id=c,
                )
            )
            metrics.record_success(latency_ms=latency, category="bounded_operation")
            if (
                prior_catalog_version_id is not None
                and prior_catalog_version_id != catalog_version_id
            ):
                with metrics.lock:
                    metrics.catalog_version_switches += 1
            prior_catalog_version_id = catalog_version_id
        except Exception as exc:
            metrics.record_failure("exact_catalog_version_switch", exc)

    # Every synthetic provider deliberately reuses the same attribute codes.
    # Exact version identity must still return that provider/version's distinct
    # range, even after the checksum-aware cache has been warmed by another
    # provider using the same code.
    for catalog_version_id in catalog_version_ids:
        expected_number = catalog_numbers_by_version_id[catalog_version_id]
        try:
            attribute, latency = _timed(
                lambda c=catalog_version_id: service.get_attribute(
                    principal_id=switch_actor,
                    tenant_id=tenants[switch_actor],
                    catalog_version_id=c,
                    attribute_code="SYN000",
                )
            )
            if (
                attribute.get("catalog_version_id") != catalog_version_id
                or str(attribute.get("ordinary_max")) != str(100 + expected_number)
            ):
                with metrics.lock:
                    metrics.cross_provider_contamination += 1
                raise SoakInvariantError(
                    "An overlapping synthetic attribute code crossed provider identity."
                )
            metrics.record_success(latency_ms=latency, category="bounded_operation")
            with metrics.lock:
                metrics.provider_isolation_checks += 1
        except Exception as exc:
            metrics.record_failure("cross_provider_cache_isolation", exc)

    preview_fields = (
        {
            "field_name": "SYN000",
            "description": "Synthetic operational field 000",
            "data_type": "integer",
            "observed_min": "0",
            "observed_max": "100",
            "observed_special_values": (),
        },
    )

    def preview(index: int) -> None:
        project = projects[index % len(projects)]
        actor = project_owners[project]
        lineage = lineages[project]
        try:
            _result, latency = _timed(
                lambda: service.catalogs.build_dataset_crosswalk_candidates_exact(
                    _context(actor, tenants[actor], project),
                    lineage.catalog_key,
                    lineage.catalog_checksum,
                    preview_fields,
                )
            )
            metrics.record_success(latency_ms=latency, category="crosswalk_preview")
        except Exception as exc:
            metrics.record_failure("crosswalk_preview", exc)

    with ThreadPoolExecutor(max_workers=min(settings.max_workers, settings.user_count)) as pool:
        tuple(pool.map(preview, range(settings.crosswalk_preview_count)))

    # Revisions use the exact current revision every time.  Registrations count
    # toward the requested write total, matching the durable append contract.
    remaining_writes = max(0, settings.decision_write_count - len(projects))
    for index in range(remaining_writes):
        project = projects[index % len(projects)]
        actor = project_owners[project]
        current = governance.get_current(
            context=_context(actor, tenants[actor], project),
            lineage=lineages[project],
            governance_id=governance_ids[project],
        )
        try:
            _record, latency = _timed(
                lambda p=project, a=actor, c=current: governance.revise(
                    context=_context(a, tenants[a], p),
                    lineage=lineages[p],
                    governance_id=governance_ids[p],
                    expected_revision=c.revision,
                    decisions=decisions[p],
                    audit=_audit(a, "Synthetic evidence-preserving revision."),
                )
            )
            metrics.record_success(latency_ms=latency, category="decision_write")
        except Exception as exc:
            metrics.record_failure("crosswalk_decision_write", exc)

    def run_conflict_trial(project: str, *, timed: bool = False) -> None:
        """Race two independent production repository instances."""

        actor = project_owners[project]
        expected = governance.get_current(
            context=_context(actor, tenants[actor], project),
            lineage=lineages[project],
            governance_id=governance_ids[project],
        ).revision
        barrier = threading.Barrier(2)

        def conflicting_write() -> str:
            barrier.wait(timeout=10)
            started = time.perf_counter()
            writer_repository = SQLiteGovernedCrosswalkRepository(root)
            writer_governance = governance_service(writer_repository, service)
            with metrics.lock:
                metrics.independent_writer_instances += 1
            try:
                writer_governance.revise(
                    context=_context(actor, tenants[actor], project),
                    lineage=lineages[project],
                    governance_id=governance_ids[project],
                    expected_revision=expected,
                    decisions=decisions[project],
                    audit=_audit(actor, "Synthetic concurrent review."),
                )
                metrics.record_success(
                    latency_ms=(time.perf_counter() - started) * 1_000.0,
                    category="decision_write",
                )
                return "success"
            except CrosswalkGovernanceConflictError:
                metrics.record_conflict(
                    latency_ms=(time.perf_counter() - started) * 1_000.0
                )
                return "conflict"
            except Exception as exc:
                metrics.record_failure("independent_sqlite_writer", exc)
                return "failure"
            finally:
                del writer_governance
                del writer_repository

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(lambda _index: conflicting_write(), range(2)))
        if sorted(outcomes) != ["conflict", "success"]:
            metrics.record_failure(
                "optimistic_concurrency",
                SoakInvariantError("Concurrent revision outcomes were contradictory."),
            )
        elif alias_references[project] is not None:
            with metrics.lock:
                metrics.concurrent_alias_reviews += 1
        if timed:
            with metrics.lock:
                metrics.timed_crosswalk_probes += 1

    # Each conflict trial presents the same exact compare revision to two
    # independent writers.  Exactly one append must win and one must conflict.
    for _trial in range(settings.conflict_trial_count):
        run_conflict_trial(projects[_trial % len(projects)])

    def expected_denial(
        call: Callable[[], Any],
        scenario: str,
        *,
        contamination_dimension: str | None = None,
    ) -> None:
        started = time.perf_counter()
        try:
            call()
        except (BureauCatalogAccessDeniedError, CrosswalkGovernanceAccessDeniedError):
            metrics.record_expected_denial(
                latency_ms=(time.perf_counter() - started) * 1_000.0
            )
        except Exception as exc:
            metrics.record_failure(scenario, exc)
        else:
            with metrics.lock:
                metrics.inconsistent_entitlement_results += 1
                if contamination_dimension == "user":
                    metrics.cross_user_contamination += 1
                elif contamination_dimension == "tenant":
                    metrics.cross_tenant_contamination += 1
                elif contamination_dimension == "project":
                    metrics.cross_project_contamination += 1
                elif contamination_dimension == "provider":
                    metrics.cross_provider_contamination += 1
            metrics.record_failure(
                scenario,
                SoakInvariantError("Unauthorized synthetic access unexpectedly succeeded."),
            )

    for index in range(settings.unauthorized_attempt_count):
        user = unauthorized_users[index % len(unauthorized_users)]
        catalog_version_id = catalog_version_ids[index % len(catalog_version_ids)]
        catalog = catalogs_by_version_id[catalog_version_id]
        expected_denial(
            lambda u=user, c=catalog: service.get_attribute(
                principal_id=u,
                tenant_id=tenants[u],
                catalog_version_id=c.catalog_version_id,
                attribute_code="SYN000",
            ),
            "unauthorized_catalog_lookup",
        )

    # Warm one exact attribute as an entitled principal, then repeat the same
    # request as an unentitled principal and as the same principal in a
    # contradictory tenant. A shared cache entry must never become authority.
    cache_probe_catalog = catalogs_by_version_id[catalog_version_ids[0]]
    cache_probe_actor = entitled_users[0]
    service.get_attribute(
        principal_id=cache_probe_actor,
        tenant_id=tenants[cache_probe_actor],
        catalog_version_id=cache_probe_catalog.catalog_version_id,
        attribute_code="SYN000",
    )
    expected_denial(
        lambda: service.get_attribute(
            principal_id=unauthorized_users[0],
            tenant_id=tenants[unauthorized_users[0]],
            catalog_version_id=cache_probe_catalog.catalog_version_id,
            attribute_code="SYN000",
        ),
        "cross_user_warm_cache_lookup",
        contamination_dimension="user",
    )
    expected_denial(
        lambda: service.get_attribute(
            principal_id=cache_probe_actor,
            tenant_id=tenants[cache_probe_actor] + "-contradictory",
            catalog_version_id=cache_probe_catalog.catalog_version_id,
            attribute_code="SYN000",
        ),
        "cross_tenant_warm_cache_lookup",
        contamination_dimension="tenant",
    )

    # Catalog entitlement without project access cannot read another project's
    # governance state.  Project access without entitlement is denied as well.
    outsider = next(
        (
            user
            for user in entitled_users
            if user not in memberships[project_access_probe_id]
        ),
        None,
    )
    if outsider is None:
        raise SoakConfigurationError(
            "The synthetic cross-project probe needs one nonmember user."
        )
    expected_denial(
        lambda: governance.get_current(
            context=_context(outsider, tenants[outsider], project_access_probe_id),
            lineage=lineages[project_access_probe_id],
            governance_id=governance_ids[project_access_probe_id],
        ),
        "cross_project_governance_read",
        contamination_dimension="project",
    )
    non_entitled_project_user = unauthorized_users[0]
    expected_denial(
        lambda: governance.get_current(
            context=_context(
                non_entitled_project_user,
                tenants[non_entitled_project_user],
                project_access_probe_id,
            ),
            lineage=lineages[project_access_probe_id],
            governance_id=governance_ids[project_access_probe_id],
        ),
        "project_access_without_catalog_entitlement",
    )

    tamper_catalog_version_id = catalog_version_ids_by_number[
        settings.catalog_version_count
    ]
    tamper_catalog = catalogs_by_version_id[tamper_catalog_version_id]
    tamper_actor = entitled_users[0]
    manifest = BureauCatalogManifest.model_validate_json(
        (tamper_catalog.exact_directory / "catalog_manifest.json").read_bytes()
    )
    tamper_path = tamper_catalog.exact_directory / manifest.attribute_file.relative_path
    original_bytes = tamper_path.read_bytes()

    def run_tamper_probe(*, timed: bool = False) -> None:
        """Warm, corrupt, reject, restore, and revalidate one synthetic version."""

        with metrics.lock:
            metrics.tamper_probe_count += 1
        service.get_attribute(
            principal_id=tamper_actor,
            tenant_id=tenants[tamper_actor],
            catalog_version_id=tamper_catalog.catalog_version_id,
            attribute_code="SYN000",
        )
        tamper_path.write_bytes(original_bytes + b"{\"synthetic_tamper\":true}\n")
        try:
            try:
                service.verify_integrity(
                    principal_id=tamper_actor,
                    tenant_id=tenants[tamper_actor],
                    catalog_version_id=tamper_catalog.catalog_version_id,
                )
            except (BureauCatalogIntegrityError, ValueError):
                with metrics.lock:
                    metrics.checksum_failures += 1
                    metrics.expected_tamper_checksum_failures += 1
                    metrics.tamper_detection_passed = True
                    metrics.tamper_cache_eviction_passed = (
                        service.loader.cache_size() == 0
                    )
            else:
                metrics.record_failure(
                    "tamper_detection",
                    SoakInvariantError("Synthetic catalog tampering was not rejected."),
                )
        finally:
            tamper_path.write_bytes(original_bytes)
        try:
            service.verify_integrity(
                principal_id=tamper_actor,
                tenant_id=tenants[tamper_actor],
                catalog_version_id=tamper_catalog.catalog_version_id,
            )
            with metrics.lock:
                metrics.tamper_recovery_passed = True
                if timed:
                    metrics.timed_tamper_probes += 1
        except Exception as exc:
            metrics.record_failure("tamper_recovery", exc)

    # No vendor or live artifact is touched; only generated synthetic bytes are
    # restored after the expected checksum rejection.
    run_tamper_probe()

    reload_cycle_number = 0

    def build_reload_payload() -> Mapping[str, Any]:
        probes: list[Mapping[str, Any]] = []
        for project in projects:
            actor = project_owners[project]
            context = _context(actor, tenants[actor], project)
            current = governance.get_current(
                context=context,
                lineage=lineages[project],
                governance_id=governance_ids[project],
            )
            history = governance.history(
                context=context,
                lineage=lineages[project],
                governance_id=governance_ids[project],
            )
            probes.append(
                {
                    "actor": actor,
                    "tenant": tenants[actor],
                    "project_id": project,
                    "catalog_version_id": catalog_version_ids_by_project[project],
                    "governance_id": governance_ids[project],
                    "lineage": lineages[project].model_dump(mode="json"),
                    "expected_revision": current.revision,
                    "expected_checksum": current.revision_checksum,
                    "history_checksums": [
                        item.revision_checksum for item in history
                    ],
                    "decisions_checksum": _sha(
                        [
                            item.model_dump(mode="json")
                            for item in current.decisions
                        ]
                    ),
                }
            )
        return {"probes": probes}

    def run_reload_cycle() -> bool:
        nonlocal reload_cycle_number
        nonlocal service
        nonlocal decision_repository
        nonlocal governance
        reload_cycle_number += 1
        started = time.perf_counter()
        try:
            result = _run_reload_probe_subprocess(
                root=root,
                evidence_root=evidence_root,
                run_id=run_id,
                cycle=reload_cycle_number,
                payload=build_reload_payload(),
            )
            service.loader.clear()
            service = resources.service(root)
            decision_repository = resources.repository(root)
            governance = governance_service(decision_repository, service)
            for project in projects:
                actor = project_owners[project]
                record = governance.get_current(
                    context=_context(actor, tenants[actor], project),
                    lineage=lineages[project],
                    governance_id=governance_ids[project],
                )
                if (
                    record.lineage != lineages[project]
                    or calculate_revision_checksum(record)
                    != record.revision_checksum
                ):
                    raise SoakInvariantError(
                        "Reloaded exact crosswalk evidence is contradictory."
                    )
        except Exception as exc:
            with metrics.lock:
                metrics.restart_recovery_failures += 1
            metrics.record_failure("service_reload", exc)
            return False
        else:
            metrics.record_success(
                latency_ms=(time.perf_counter() - started) * 1_000.0,
                category="service_reload",
            )
            with metrics.lock:
                metrics.service_reload_cycles += 1
                metrics.reload_child_processes += 1
                metrics.exact_identity_negative_checks += int(
                    result["negative_checks"]
                )
            return True

    # Each required reload crosses a fresh child-process boundary, then the
    # parent reconstructs both production adapters from durable authorities.
    for _cycle in range(settings.service_reload_count):
        if not run_reload_cycle():
            break

    timed_started = time.monotonic()
    next_heartbeat = timed_started
    deadline = timed_started + settings.duration_seconds
    scheduled_reload_interval = (
        settings.duration_seconds / settings.service_reload_count
        if settings.duration_seconds > 0
        else float("inf")
    )
    next_scheduled_reload = timed_started + scheduled_reload_interval
    scheduled_tamper_interval = (
        settings.duration_seconds / 3
        if settings.duration_seconds > 0
        else float("inf")
    )
    next_scheduled_tamper = timed_started + scheduled_tamper_interval
    timed_previous_catalog_version_id: str | None = None
    tail_index = 0
    while time.monotonic() < deadline:
        user = entitled_users[tail_index % len(entitled_users)]
        catalog_version_id = catalog_version_ids[
            tail_index % len(catalog_version_ids)
        ]
        operation = tail_index % 6
        if operation == 1:
            preview(tail_index)
            with metrics.lock:
                metrics.timed_crosswalk_probes += 1
        elif operation == 2:
            project = projects[tail_index % len(projects)]
            actor = project_owners[project]
            try:
                current = governance.get_current(
                    context=_context(actor, tenants[actor], project),
                    lineage=lineages[project],
                    governance_id=governance_ids[project],
                )
                _record, latency = _timed(
                    lambda: governance.revise(
                        context=_context(actor, tenants[actor], project),
                        lineage=lineages[project],
                        governance_id=governance_ids[project],
                        expected_revision=current.revision,
                        decisions=decisions[project],
                        audit=_audit(actor, "Timed synthetic crosswalk review."),
                    )
                )
                metrics.record_success(
                    latency_ms=latency, category="decision_write"
                )
                with metrics.lock:
                    metrics.timed_crosswalk_probes += 1
            except Exception as exc:
                metrics.record_failure("timed_crosswalk_revision", exc)
        elif operation == 3 and tail_index % 30 == 3:
            run_conflict_trial(
                projects[tail_index % len(projects)], timed=True
            )
        else:
            try:
                _health, latency = _timed(
                    lambda: service.catalog_health(
                        principal_id=user,
                        tenant_id=tenants[user],
                        catalog_version_id=catalog_version_id,
                    )
                )
                metrics.record_success(
                    latency_ms=latency, category="bounded_operation"
                )
                if (
                    timed_previous_catalog_version_id is not None
                    and timed_previous_catalog_version_id != catalog_version_id
                ):
                    with metrics.lock:
                        metrics.catalog_version_switches += 1
                timed_previous_catalog_version_id = catalog_version_id
            except Exception as exc:
                metrics.record_failure("duration_tail_health", exc)

        tail_index += 1
        now = time.monotonic()
        if now >= next_scheduled_reload:
            run_reload_cycle()
            next_scheduled_reload += scheduled_reload_interval
            now = time.monotonic()
        if now >= next_scheduled_tamper:
            run_tamper_probe(timed=True)
            next_scheduled_tamper += scheduled_tamper_interval
            now = time.monotonic()
        if now >= next_heartbeat:
            heartbeat = {
                "run_id": run_id,
                "server_timestamp": _utc_now(),
                "elapsed_seconds": round(now - wall_started, 3),
                "timed_soak_elapsed_seconds": round(now - timed_started, 3),
                **metrics.snapshot(),
            }
            _write_jsonl(progress_path, heartbeat)
            if progress is not None:
                progress(heartbeat)
            next_heartbeat = now + settings.heartbeat_seconds
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1.0, remaining))

    gc.collect()
    memory_after, handles_after = _process_measurements()
    completed_monotonic = time.monotonic()
    elapsed = completed_monotonic - wall_started
    timed_soak_elapsed = completed_monotonic - timed_started
    histories = []
    for project in projects:
        actor = project_owners[project]
        histories.append(
            governance.history(
                context=_context(actor, tenants[actor], project),
                lineage=lineages[project],
                governance_id=governance_ids[project],
            )
        )
    duplicate_revisions = sum(
        len(history) - len({record.revision for record in history})
        for history in histories
    )
    transient_roots = sum(
        1
        for child in root.iterdir()
        if child.name.startswith(".catalog-installing-")
    )
    temporary_entries_after = (
        frozenset(child.name for child in authority_paths.temporary_root.iterdir())
        if authority_paths.temporary_root is not None
        else frozenset()
    )
    leaked_temporary_entries = len(
        temporary_entries_after - temporary_entries_before
    )
    rss_delta = (
        memory_after - memory_before
        if memory_before is not None and memory_after is not None
        else None
    )
    handle_delta = (
        handles_after - handles_before
        if handles_before is not None and handles_after is not None
        else None
    )
    cache_entries = service.loader.cache_size()
    cache_limit = service.loader.max_entries
    snapshot = metrics.snapshot()
    configured_thresholds_met = (
        snapshot["bounded_operations"] >= settings.bounded_operation_count
        and snapshot["crosswalk_previews"] >= settings.crosswalk_preview_count
        and snapshot["decision_writes"] >= settings.decision_write_count
        and snapshot["service_reload_cycles"] >= settings.service_reload_count
        and snapshot["reload_child_processes"] >= settings.service_reload_count
        and snapshot["expected_authorization_denials"]
        >= settings.unauthorized_attempt_count
        and timed_soak_elapsed >= settings.duration_seconds
    )
    release_thresholds_met = (
        settings.user_count >= MIN_USERS
        and settings.project_count >= MIN_PROJECTS
        and settings.catalog_version_count >= MIN_CATALOG_VERSIONS
        and settings.max_workers >= MIN_USERS
        and catalog_provider_count >= 2
        and snapshot["bounded_operations"] >= MIN_BOUNDED_OPERATIONS
        and snapshot["crosswalk_previews"] >= MIN_CROSSWALK_PREVIEWS
        and snapshot["decision_writes"] >= MIN_DECISION_WRITES
        and snapshot["service_reload_cycles"] >= MIN_SERVICE_RELOADS
        and snapshot["reload_child_processes"] >= MIN_SERVICE_RELOADS
        and frontend_reload_coverage.get("status") == "verified"
        and int(frontend_reload_coverage["authenticated_reload_successes"])
        >= MIN_FRONTEND_AUTHENTICATED_RELOADS
        and snapshot["timed_crosswalk_probes"] > 0
        and snapshot["timed_tamper_probes"] > 0
        and timed_soak_elapsed >= DEFAULT_DURATION_SECONDS
    )
    functional_integrity = (
        snapshot["unexpected_failures"] == 0
        and snapshot["timeouts"] == 0
        and snapshot["inconsistent_entitlement_results"] == 0
        and snapshot["cross_user_contamination"] == 0
        and snapshot["cross_tenant_contamination"] == 0
        and snapshot["cross_project_contamination"] == 0
        and snapshot["cross_provider_contamination"] == 0
        and snapshot["provider_isolation_checks"]
        >= settings.catalog_version_count
        and snapshot["restart_recovery_failures"] == 0
        and snapshot["concurrency_conflicts"] >= settings.conflict_trial_count
        and snapshot["reload_child_processes"]
        >= settings.service_reload_count
        and snapshot["exact_identity_negative_checks"]
        >= settings.service_reload_count * settings.project_count * 4
        and snapshot["independent_writer_instances"]
        >= settings.conflict_trial_count * 2
        and snapshot["concurrent_alias_reviews"]
        >= (1 if settings.project_count >= 2 else 0)
        and snapshot["catalog_version_switches"]
        >= (settings.catalog_version_count - 1)
        and duplicate_revisions == 0
        and transient_roots == 0
        and leaked_temporary_entries == 0
        and cache_entries <= cache_limit
        and (rss_delta is None or rss_delta <= settings.max_rss_growth_bytes)
        and (handle_delta is None or handle_delta <= settings.max_handle_growth)
        and snapshot["latency_sample_count"] > 0
        and snapshot["unexpected_checksum_failures"] == 0
        and snapshot["expected_tamper_checksum_failures"]
        == snapshot["tamper_probe_count"]
        and snapshot["tamper_probe_count"] >= 1
        and snapshot["tamper_detection_passed"] is True
        and snapshot["tamper_cache_eviction_passed"] is True
        and snapshot["tamper_recovery_passed"] is True
    )
    passed = configured_thresholds_met and functional_integrity
    if settings.enforce_release_minimums:
        passed = passed and release_thresholds_met
    summary = {
        "schema_version": "1.0",
        "run_id": run_id,
        "classification": "synthetic_isolated_catalog_soak",
        "started_at": metrics.started_at,
        "completed_at": _utc_now(),
        "elapsed_seconds": round(elapsed, 6),
        "timed_soak_elapsed_seconds": round(timed_soak_elapsed, 6),
        "configured_duration_seconds": settings.duration_seconds,
        "user_count": settings.user_count,
        "unauthorized_user_count": len(unauthorized_users),
        "synthetic_identity_count": len(users),
        "project_count": settings.project_count,
        "catalog_version_count": settings.catalog_version_count,
        "catalog_provider_count": catalog_provider_count,
        "authority_map": {
            "used": authority_paths.authority_map_checksum is not None,
            "checksum": authority_paths.authority_map_checksum,
            "authority_map_run_id": authority_paths.authority_map_run_id,
            "mapped_authority_count": authority_paths.mapped_authority_count,
            "top_level_authority_identities": dict(
                authority_paths.top_level_authority_identities
            ),
            "per_run_children_allocated": authority_paths.per_run_children_allocated,
            "per_run_child_identity": (
                _sha(
                    {
                        "soak_run_id": run_id,
                        "authority_map_checksum": authority_paths.authority_map_checksum,
                    }
                )
                if authority_paths.per_run_children_allocated
                else None
            ),
        },
        "frontend_authenticated_reload_coverage": dict(frontend_reload_coverage),
        **snapshot,
        "memory": {
            "rss_before_bytes": memory_before,
            "rss_after_bytes": memory_after,
            "rss_delta_bytes": rss_delta,
            "maximum_allowed_growth_bytes": settings.max_rss_growth_bytes,
            "within_limit": rss_delta is None or rss_delta <= settings.max_rss_growth_bytes,
        },
        "file_handles": {
            "before": handles_before,
            "after": handles_after,
            "delta": handle_delta,
            "maximum_allowed_growth": settings.max_handle_growth,
            "within_limit": handle_delta is None or handle_delta <= settings.max_handle_growth,
        },
        "cache_entries": cache_entries,
        "cache_entry_limit": cache_limit,
        "cache_within_limit": cache_entries <= cache_limit,
        "leaked_transient_roots": transient_roots,
        "leaked_temporary_entries": leaked_temporary_entries,
        "duplicate_revisions": duplicate_revisions,
        "configured_thresholds_met": configured_thresholds_met,
        "release_thresholds_met": release_thresholds_met,
        "functional_integrity": functional_integrity,
        "passed": passed,
        "contains_vendor_content": False,
        "live_project_accessed": False,
        "live_service_manipulated": False,
        "live_ports_contacted": False,
        "sealed_holdout_accessed": False,
        "evidence_file": summary_path.name,
    }
    evidence_root.mkdir(parents=True, exist_ok=True)
    with summary_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    # The operational adapters keep no long-lived connection by contract, but
    # release every service/repository reference before returning so Windows
    # does not retain an incidental SQLite handle during focused test cleanup.
    service.loader.clear()
    del governance
    del governance_service
    del decision_repository
    del service
    gc.collect()

    if not passed:
        raise SoakInvariantError(
            "Synthetic catalog soak failed; "
            f"unexpected={summary['unexpected_failures']} "
            "failure_types="
            + ",".join(
                sorted(
                    {
                        str(item.get("exception_type", "unknown"))
                        for item in summary["failures"]
                    }
                )
            )
            + " "
            f"timeouts={summary['timeouts']} "
            f"restart_failures={summary['restart_recovery_failures']} "
            f"tamper_detected={summary['tamper_detection_passed']} "
            f"tamper_recovered={summary['tamper_recovery_passed']}; "
            f"inspect aggregate evidence {summary_path.name}."
        )
    return summary


def run_soak(
    settings: SoakSettings,
    *,
    progress: Callable[[Mapping[str, Any]], None] | None = None,
) -> Mapping[str, Any]:
    resources = _ResourceScope()
    try:
        return _run_soak_impl(
            settings,
            progress=progress,
            resources=resources,
        )
    except BaseException as exc:
        _close_traceback_sqlite_connections(exc)
        raise
    finally:
        resources.release()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the isolated synthetic bureau-catalog operational soak."
    )
    authority = parser.add_mutually_exclusive_group(required=True)
    authority.add_argument(
        "--root",
        type=Path,
        help="Explicit, existing, dedicated non-live restricted root.",
    )
    authority.add_argument(
        "--authority-map",
        type=Path,
        help=(
            "Explicit isolated-authority-map.json; the harness consumes its "
            "restricted-catalog and test-output sibling authorities."
        ),
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=DEFAULT_DURATION_SECONDS,
        help=f"Soak duration; release minimum is {DEFAULT_DURATION_SECONDS} seconds.",
    )
    parser.add_argument(
        "--frontend-reload-evidence",
        type=Path,
        required=True,
        help=(
            "Checksummed synthetic authenticated frontend-reload evidence under "
            "the isolated test-output authority. Live ports 5174 and 8001 are prohibited."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--internal-reload-probe"]:
        if len(arguments) != 5:
            return 2
        try:
            _execute_reload_probe(
                Path(arguments[1]),
                Path(arguments[2]),
                Path(arguments[3]),
                Path(arguments[4]),
            )
        except Exception as exc:  # pragma: no cover - exercised by parent failure
            print(
                f"catalog-reload-probe failed: {type(exc).__name__}",
                flush=True,
            )
            return 1
        return 0

    args = _parser().parse_args(arguments)
    settings = SoakSettings(
        root=args.root,
        authority_map=args.authority_map,
        duration_seconds=args.duration_seconds,
        frontend_reload_evidence=args.frontend_reload_evidence,
    )

    def progress(payload: Mapping[str, Any]) -> None:
        print(
            "catalog-soak heartbeat "
            f"elapsed={payload['elapsed_seconds']}s "
            f"requests={payload['total_requests']} "
            f"unexpected={payload['unexpected_failures']}",
            flush=True,
        )

    try:
        result = run_soak(settings, progress=progress)
    except (SoakConfigurationError, SoakInvariantError):
        print("catalog-soak failed: governed invariant", flush=True)
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI redaction boundary
        # Never print arbitrary exception text: production library failures can
        # contain a path or another restricted identifier.
        print(f"catalog-soak failed: {type(exc).__name__}", flush=True)
        return 1
    print(
        "catalog-soak passed "
        f"run_id={result['run_id']} evidence={result['evidence_file']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
