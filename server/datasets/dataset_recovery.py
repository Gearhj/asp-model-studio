"""Fail-closed, offline Dataset Library forensic recovery.

This module deliberately has no browser/session fallback.  A caller supplies an
existing operator identity, exact dataset/version identifiers, and a hashed
evidence report.  Recovery is possible only from a verified authoritative
registry snapshot plus independent artifact corroboration.

The service never creates an active modeling dataset selection and never reads
or updates training, Evaluation, Model Registry, or Scoring records.
"""

from __future__ import annotations

import hashlib
import csv
import json
import os
import re
import sqlite3
import uuid
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from .dataset_storage import DatasetLibraryStorage


ALLOWED_DATASET_ROLES = {"owner", "editor", "viewer", "auditor"}
PROJECT_PERMISSION_ORDER = (
    "view",
    "comment",
    "edit",
    "validate",
    "approve",
    "export",
    "admin",
)
TIER1_SOURCE_KINDS = {
    "authoritative_registry_snapshot",
    "authoritative_project_links_snapshot",
    "immutable_version_schema_snapshot",
}
TIER2_SOURCE_KINDS = {"live_artifact", "artifact_sidecar"}
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MAX_EVIDENCE_REPORT_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
_MAINTENANCE_TABLE_CONTRACT_SQL = """
CREATE TABLE IF NOT EXISTS dataset_library_maintenance_events (
  maintenance_event_id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  operation_type TEXT NOT NULL
    CHECK (operation_type IN ('reconcile', 'recover', 'verify', 'quarantine')),
  event_status TEXT NOT NULL
    CHECK (event_status IN ('started', 'complete', 'failed', 'refused')),
  actor_user_id TEXT NOT NULL,
  project_id TEXT,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  evidence_report_sha256 TEXT NOT NULL,
  backup_manifest_sha256 TEXT,
  registry_before_sha256 TEXT,
  registry_after_sha256 TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
)
"""
_MAINTENANCE_TRIGGER_CONTRACT_SQL = {
    "trg_dataset_library_maintenance_events_no_update": """
CREATE TRIGGER IF NOT EXISTS trg_dataset_library_maintenance_events_no_update
BEFORE UPDATE ON dataset_library_maintenance_events
BEGIN
  SELECT RAISE(ABORT, 'dataset_library_maintenance_events is append-only');
END
""",
    "trg_dataset_library_maintenance_events_no_delete": """
CREATE TRIGGER IF NOT EXISTS trg_dataset_library_maintenance_events_no_delete
BEFORE DELETE ON dataset_library_maintenance_events
BEGIN
  SELECT RAISE(ABORT, 'dataset_library_maintenance_events is append-only');
END
""",
}
_MAINTENANCE_EVENT_COLUMNS = (
    "maintenance_event_id",
    "attempt_id",
    "operation_id",
    "operation_type",
    "event_status",
    "actor_user_id",
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "reason",
    "evidence_report_sha256",
    "backup_manifest_sha256",
    "registry_before_sha256",
    "registry_after_sha256",
    "created_at",
    "metadata_json",
)


class DatasetRecoveryError(RuntimeError):
    """Base class for an intentionally refused recovery."""


class DatasetRecoveryEvidenceError(DatasetRecoveryError):
    """The supplied evidence does not establish the requested identity."""


class DatasetRecoveryAuthorizationError(DatasetRecoveryError):
    """The explicit maintenance actor is absent or unauthorized."""


class DatasetRecoveryConflictError(DatasetRecoveryError):
    """Existing live metadata conflicts with the proven recovery record."""


class DatasetRecoveryApplyError(DatasetRecoveryError):
    """A mutation failed after recovery preflight completed."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _storage_json_sha256(value: Any) -> str:
    """Predict the exact canonical hash used by DatasetLibraryStorage."""

    rendered = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    return _sha256_bytes((rendered + "\n").encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably publish one recovery-sidecar file outside the live catalog."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _strip_sql_comments(sql: Any) -> str:
    """Remove SQLite comments without treating comment markers in literals as syntax."""

    source = str(sql or "")
    rendered: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            rendered.append(character)
            if quote == "[":
                if character == "]":
                    if following == "]":
                        rendered.append(following)
                        index += 1
                    else:
                        quote = None
            elif character == quote:
                if following == quote:
                    rendered.append(following)
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if character in {"'", '"', "`", "["}:
            quote = character
            rendered.append(character)
            index += 1
            continue
        if character == "-" and following == "-":
            rendered.append(" ")
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if character == "/" and following == "*":
            rendered.append(" ")
            index += 2
            while index + 1 < len(source) and source[index : index + 2] != "*/":
                index += 1
            index = min(index + 2, len(source))
            continue
        rendered.append(character)
        index += 1
    return "".join(rendered)


def _normalized_sql_contract(sql: Any) -> str:
    source = _strip_sql_comments(sql).rstrip()
    if source.endswith(";"):
        source = source[:-1].rstrip()
    rendered: list[str] = []
    quote: str | None = None
    pending_space = False
    index = 0
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            rendered.append(character)
            if quote == "[":
                if character == "]":
                    quote = None
            elif character == quote:
                if following == quote:
                    rendered.append(following)
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if character in {"'", '"', "`", "["}:
            if pending_space and rendered:
                rendered.append(" ")
            pending_space = False
            quote = character
            rendered.append(character)
        elif character.isspace():
            pending_space = True
        else:
            if pending_space and rendered:
                rendered.append(" ")
            pending_space = False
            rendered.append(character.casefold())
        index += 1
    return "".join(rendered).strip()


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            return bool(is_junction())
        except OSError:
            return True
    return False


def _assert_unlinked_path(path: Path, *, root: Path | None, label: str) -> None:
    """Reject a link/junction in every caller-controlled path component."""

    lexical_path = Path(os.path.abspath(str(path.expanduser())))
    lexical_root = (
        Path(os.path.abspath(str(root.expanduser()))) if root is not None else None
    )
    if lexical_root is not None:
        try:
            relative_parts = lexical_path.relative_to(lexical_root).parts
        except ValueError as exc:
            raise DatasetRecoveryEvidenceError(
                f"{label} escapes its authorized root."
            ) from exc
        current = lexical_root
        candidates = [current]
        for part in relative_parts:
            current = current / part
            candidates.append(current)
    else:
        anchor = Path(lexical_path.anchor)
        current = anchor
        candidates = [current]
        for part in lexical_path.parts[len(anchor.parts) :]:
            current = current / part
            candidates.append(current)
    for candidate in candidates:
        if candidate.exists() and _is_link_or_junction(candidate):
            raise DatasetRecoveryEvidenceError(
                f"{label} cannot traverse a filesystem link or junction."
            )


def _assert_regular_unlinked_file(
    path: Path,
    *,
    root: Path | None = None,
    label: str,
) -> Path:
    _assert_unlinked_path(path, root=root, label=label)
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise DatasetRecoveryEvidenceError(f"{label} is unavailable.")
    return resolved


def _safe_relative_path(root: Path, value: Any) -> Path:
    raw = _text(value).replace("\\", "/")
    if not raw:
        raise DatasetRecoveryEvidenceError(
            "The authoritative version record has no immutable artifact path."
        )
    unresolved = root.expanduser() / raw
    _assert_unlinked_path(
        unresolved,
        root=root.expanduser(),
        label="The authoritative artifact path",
    )
    candidate = unresolved.resolve()
    root = root.resolve()
    if candidate == root or root not in candidate.parents:
        raise DatasetRecoveryEvidenceError(
            "The authoritative artifact path escapes the Dataset Library root."
        )
    return candidate


def _read_json_bytes(value: bytes, label: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetRecoveryEvidenceError(f"{label} is not valid UTF-8 JSON.") from exc
    if not isinstance(parsed, dict):
        raise DatasetRecoveryEvidenceError(f"{label} must contain a JSON object.")
    return parsed


def _normalized_tier(value: Any) -> int:
    normalized = _text(value).casefold().replace("_", "").replace("-", "")
    if normalized in {"1", "tier1", "authoritative"}:
        return 1
    if normalized in {"2", "tier2", "strongcorroboration", "corroboration"}:
        return 2
    if normalized in {"3", "tier3", "supporting"}:
        return 3
    return 0


def _permission_rank(value: Any) -> int:
    normalized = _text(value).casefold()
    try:
        return PROJECT_PERMISSION_ORDER.index(normalized)
    except ValueError:
        return -1


@dataclass(frozen=True)
class DatasetRecoveryRequest:
    dataset_id: str
    dataset_version_id: str
    actor_user_id: str
    evidence_report: Path
    trusted_tier1_container: Path
    trusted_tier1_container_sha256: str
    backup_directory: Path
    reason: str
    project_id: str | None = None

    def validate(self) -> None:
        required = {
            "dataset_id": self.dataset_id,
            "dataset_version_id": self.dataset_version_id,
            "actor_user_id": self.actor_user_id,
            "trusted_tier1_container_sha256": self.trusted_tier1_container_sha256,
            "reason": self.reason,
        }
        missing = [name for name, value in required.items() if not _text(value)]
        if missing:
            raise DatasetRecoveryEvidenceError(
                "Recovery requires explicit " + ", ".join(sorted(missing)) + "."
            )
        for name, value in (
            ("dataset_id", self.dataset_id),
            ("dataset_version_id", self.dataset_version_id),
            ("actor_user_id", self.actor_user_id),
            ("project_id", self.project_id),
        ):
            if value is not None and not SAFE_IDENTIFIER_RE.fullmatch(_text(value)):
                raise DatasetRecoveryEvidenceError(
                    f"Recovery {name} contains unsafe characters."
                )
        if len(self.reason) > 1000 or any(ord(char) < 32 for char in self.reason):
            raise DatasetRecoveryEvidenceError(
                "Recovery reason contains unsafe control characters or is too long."
            )
        normalized_hash = _text(self.trusted_tier1_container_sha256).casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized_hash):
            raise DatasetRecoveryEvidenceError(
                "The trusted Tier 1 container SHA-256 is invalid."
            )
        _assert_regular_unlinked_file(
            self.evidence_report,
            label="The evidence report",
        )
        if self.evidence_report.stat().st_size > MAX_EVIDENCE_REPORT_BYTES:
            raise DatasetRecoveryEvidenceError(
                "The evidence report exceeds its safe read limit."
            )
        _assert_regular_unlinked_file(
            self.trusted_tier1_container,
            label="The trusted Tier 1 container",
        )


@dataclass(frozen=True)
class _VerifiedSource:
    tier: int
    kind: str
    family: str
    reference: str
    sha256: str
    content: bytes
    physical_path_sha256: str | None


class DatasetRecoveryService:
    """Plan and apply exact Dataset Library recovery against injected stores."""

    def __init__(
        self,
        *,
        storage: DatasetLibraryStorage,
        security_database: str | Path,
        persistence_database: str | Path,
    ) -> None:
        self.storage = storage
        self.security_database = Path(security_database).expanduser().resolve()
        self.persistence_database = Path(persistence_database).expanduser().resolve()

    @staticmethod
    def _read_only_connection(path: Path) -> sqlite3.Connection:
        if not path.is_file():
            raise DatasetRecoveryAuthorizationError(
                f"Required ATLAS authority store is unavailable: {path.name}."
            )
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _operator(self, actor_user_id: str) -> Dict[str, Any]:
        try:
            with closing(self._read_only_connection(self.security_database)) as connection:
                row = connection.execute(
                    "SELECT user_id, display_name, role, status FROM users WHERE user_id = ?",
                    (actor_user_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DatasetRecoveryAuthorizationError(
                "The ATLAS security authority could not be read."
            ) from exc
        if row is None:
            raise DatasetRecoveryAuthorizationError(
                "The maintenance actor does not exist in ATLAS security."
            )
        actor = dict(row)
        if _text(actor.get("status")).casefold() != "active":
            raise DatasetRecoveryAuthorizationError(
                "The maintenance actor is not active."
            )
        return actor

    def _project_authorization(
        self,
        actor: Mapping[str, Any],
        project_id: str,
    ) -> Dict[str, Any]:
        try:
            with closing(self._read_only_connection(self.persistence_database)) as connection:
                project = connection.execute(
                    "SELECT project_id, owner_user_id, created_by FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                if project is None:
                    raise DatasetRecoveryAuthorizationError(
                        "The requested project does not exist."
                    )
                actor_id = _text(actor.get("user_id"))
                if _text(actor.get("role")).casefold() == "admin":
                    return {"allowed": True, "basis": "admin", "permission": "admin"}
                if actor_id in {
                    _text(project["owner_user_id"]),
                    _text(project["created_by"]),
                }:
                    return {"allowed": True, "basis": "project_owner", "permission": "admin"}
                group_ids = {
                    _text(row[0])
                    for row in connection.execute(
                        "SELECT group_id FROM user_group_members WHERE user_id = ? AND status = 'active'",
                        (actor_id,),
                    ).fetchall()
                }
                permissions = connection.execute(
                    """
                    SELECT principal_type, principal_id, permission_level
                    FROM resource_permissions
                    WHERE resource_type = 'project' AND resource_id = ? AND status = 'active'
                    """,
                    (project_id,),
                ).fetchall()
                effective = max(
                    (
                        _permission_rank(row["permission_level"])
                        for row in permissions
                        if (
                            row["principal_type"] == "user"
                            and row["principal_id"] == actor_id
                        )
                        or (
                            row["principal_type"] == "group"
                            and row["principal_id"] in group_ids
                        )
                    ),
                    default=-1,
                )
        except DatasetRecoveryAuthorizationError:
            raise
        except sqlite3.Error as exc:
            raise DatasetRecoveryAuthorizationError(
                "Project authorization could not be verified."
            ) from exc
        required = _permission_rank("edit")
        if effective < required:
            raise DatasetRecoveryAuthorizationError(
                "The maintenance actor lacks edit permission on the requested project."
            )
        return {
            "allowed": True,
            "basis": "resource_permission",
            "permission": PROJECT_PERMISSION_ORDER[effective],
        }

    @staticmethod
    def _source_reference(source: Mapping[str, Any]) -> str:
        container = _text(source.get("container_path") or source.get("containerPath"))
        member = _text(source.get("member_path") or source.get("memberPath"))
        path = _text(source.get("path"))
        return f"{Path(container).name}!{member}" if container else Path(path).name

    def _verify_source(
        self,
        source: Mapping[str, Any],
        *,
        default_tier: int,
        container_hash_cache: Dict[Path, str],
        request: DatasetRecoveryRequest,
    ) -> _VerifiedSource:
        tier = _normalized_tier(source.get("tier")) or default_tier
        if tier not in {1, 2, 3}:
            raise DatasetRecoveryEvidenceError("An evidence source has no valid tier.")
        kind = _text(source.get("kind")).casefold() or "unspecified"
        if tier == 1 and kind not in TIER1_SOURCE_KINDS:
            raise DatasetRecoveryEvidenceError(
                "A Tier 1 source has no recognized authoritative source kind."
            )
        if tier == 2 and kind not in TIER2_SOURCE_KINDS:
            raise DatasetRecoveryEvidenceError(
                "A Tier 2 source has no recognized exact-artifact source kind."
            )
        container_value = _text(
            source.get("container_path") or source.get("containerPath")
        )
        member = _text(source.get("member_path") or source.get("memberPath"))
        if container_value:
            container = _assert_regular_unlinked_file(
                Path(container_value),
                label="An archive evidence source",
            )
            if not member:
                raise DatasetRecoveryEvidenceError(
                    "An archive evidence source is unavailable or has no member path."
                )
            expected_container_hash = _text(
                source.get("container_sha256") or source.get("containerSha256")
            ).casefold()
            actual_container_hash = container_hash_cache.get(container)
            if actual_container_hash is None:
                actual_container_hash = _sha256_file(container)
                container_hash_cache[container] = actual_container_hash
            if not expected_container_hash or actual_container_hash != expected_container_hash:
                raise DatasetRecoveryEvidenceError(
                    "An evidence archive checksum does not match the report."
                )
            try:
                with zipfile.ZipFile(container) as archive:
                    member_info = archive.getinfo(member)
                    if member_info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                        raise DatasetRecoveryEvidenceError(
                            "An evidence archive member exceeds its safe read limit."
                        )
                    content = archive.read(member)
            except DatasetRecoveryEvidenceError:
                raise
            except (KeyError, OSError, zipfile.BadZipFile) as exc:
                raise DatasetRecoveryEvidenceError(
                    "An evidence archive member could not be read."
                ) from exc
            expected_hash = _text(
                source.get("member_sha256")
                or source.get("memberSha256")
                or source.get("sha256")
            ).casefold()
            expected_bytes = source.get("member_bytes") or source.get("memberBytes")
            if tier == 1:
                trusted_container = request.trusted_tier1_container.expanduser().resolve()
                trusted_hash = _text(
                    request.trusted_tier1_container_sha256
                ).casefold()
                if (
                    os.path.normcase(str(container))
                    != os.path.normcase(str(trusted_container))
                    or expected_container_hash != trusted_hash
                    or actual_container_hash != trusted_hash
                ):
                    raise DatasetRecoveryEvidenceError(
                        "A Tier 1 source is not bound to the explicit trusted archive and checksum."
                    )
                family = f"tier1-archive:{actual_container_hash}"
            else:
                family = f"tier{tier}-archive:{actual_container_hash}"
            physical_path_sha256 = None
        else:
            if tier == 1:
                raise DatasetRecoveryEvidenceError(
                    "Tier 1 authority must come from the explicit trusted archive."
                )
            path = _assert_regular_unlinked_file(
                Path(_text(source.get("path"))),
                label="An evidence source file",
            )
            content = b""
            expected_hash = _text(source.get("sha256")).casefold()
            expected_bytes = source.get("bytes")
            physical_root_hash = _sha256_bytes(
                os.path.normcase(str(path.parent)).encode("utf-8")
            )
            family = f"tier{tier}-filesystem:{physical_root_hash}"
            physical_path_sha256 = _sha256_bytes(
                os.path.normcase(str(path)).encode("utf-8")
            )
        actual_hash = (
            _sha256_bytes(content)
            if container_value
            else _sha256_file(path)
        )
        if not expected_hash or actual_hash != expected_hash:
            raise DatasetRecoveryEvidenceError(
                "An evidence source checksum does not match the report."
            )
        if expected_bytes is not None:
            try:
                actual_bytes = len(content) if container_value else path.stat().st_size
                bytes_match = int(expected_bytes) == actual_bytes
            except (TypeError, ValueError, OSError):
                bytes_match = False
            if not bytes_match:
                raise DatasetRecoveryEvidenceError(
                    "An evidence source byte count does not match the report."
                )
        return _VerifiedSource(
            tier=tier,
            kind=kind,
            family=family,
            reference=self._source_reference(source),
            sha256=actual_hash,
            content=content,
            physical_path_sha256=physical_path_sha256,
        )

    def _verified_sources(
        self,
        report: Mapping[str, Any],
        request: DatasetRecoveryRequest,
    ) -> list[_VerifiedSource]:
        sources: list[_VerifiedSource] = []
        container_hash_cache: Dict[Path, str] = {}
        for key, tier in (("tier1_sources", 1), ("tier2_sources", 2), ("tier3_sources", 3)):
            values = report.get(key) or []
            if not isinstance(values, list):
                raise DatasetRecoveryEvidenceError(f"{key} must be a list.")
            for source in values:
                if not isinstance(source, dict):
                    raise DatasetRecoveryEvidenceError("Evidence sources must be objects.")
                sources.append(
                    self._verify_source(
                        source,
                        default_tier=tier,
                        container_hash_cache=container_hash_cache,
                        request=request,
                    )
                )
        generic = report.get("evidence_sources") or report.get("sources") or []
        if generic:
            if not isinstance(generic, list):
                raise DatasetRecoveryEvidenceError("evidence_sources must be a list.")
            for source in generic:
                if not isinstance(source, dict):
                    raise DatasetRecoveryEvidenceError("Evidence sources must be objects.")
                sources.append(
                    self._verify_source(
                        source,
                        default_tier=0,
                        container_hash_cache=container_hash_cache,
                        request=request,
                    )
                )
        return sources

    @staticmethod
    def _source_by_basename(
        sources: Sequence[_VerifiedSource],
        basename: str,
        *,
        tier: int | None = None,
    ) -> list[_VerifiedSource]:
        expected = basename.casefold()
        return [
            source
            for source in sources
            if (tier is None or source.tier == tier)
            and source.reference.replace("\\", "/").rsplit("/", 1)[-1].casefold()
            == expected
        ]

    @staticmethod
    def _exact_dataset_record(
        registry_sources: Sequence[_VerifiedSource],
        dataset_id: str,
    ) -> Dict[str, Any]:
        candidates: list[Dict[str, Any]] = []
        for source in registry_sources:
            payload = _read_json_bytes(source.content, source.reference)
            datasets = payload.get("datasets")
            if not isinstance(datasets, list):
                raise DatasetRecoveryEvidenceError(
                    "An authoritative registry snapshot has no datasets array."
                )
            source_matches = [
                candidate
                for candidate in datasets
                if isinstance(candidate, dict)
                and _text(candidate.get("datasetId")) == dataset_id
            ]
            if len(source_matches) > 1:
                raise DatasetRecoveryEvidenceError(
                    "A Tier 1 registry snapshot contains an ambiguous dataset_id."
                )
            candidates.extend(source_matches)
        if not candidates:
            raise DatasetRecoveryEvidenceError(
                "No Tier 1 registry snapshot contains the exact dataset_id."
            )
        canonical = {_canonical_json(candidate) for candidate in candidates}
        if len(canonical) != 1:
            raise DatasetRecoveryEvidenceError(
                "Authoritative registry snapshots disagree about the dataset record."
            )
        return json.loads(next(iter(canonical)).decode("utf-8"))

    @staticmethod
    def _exact_version_record(
        dataset: Mapping[str, Any],
        dataset_version_id: str,
    ) -> Dict[str, Any]:
        candidates = [
            version
            for version in (dataset.get("versions") or [])
            if isinstance(version, dict)
            and _text(version.get("versionId")) == dataset_version_id
        ]
        if len(candidates) != 1:
            raise DatasetRecoveryEvidenceError(
                "The exact immutable version is missing or ambiguous in Tier 1 evidence."
            )
        return dict(candidates[0])

    @staticmethod
    def _exact_project_link(
        sources: Sequence[_VerifiedSource],
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> Dict[str, Any] | None:
        candidates: list[Dict[str, Any]] = []
        for source in sources:
            payload = _read_json_bytes(source.content, source.reference)
            links = payload.get("links")
            if not isinstance(links, list):
                raise DatasetRecoveryEvidenceError(
                    "An authoritative project-links snapshot has no links array."
                )
            source_matches = [
                link
                for link in links
                if isinstance(link, dict)
                and _text(link.get("projectId")) == project_id
                and _text(link.get("datasetId")) == dataset_id
                and _text(link.get("versionId")) == dataset_version_id
            ]
            if len(source_matches) > 1:
                raise DatasetRecoveryEvidenceError(
                    "A Tier 1 project-links snapshot contains an ambiguous exact relationship."
                )
            candidates.extend(source_matches)
        if not candidates:
            return None
        canonical = {_canonical_json(candidate) for candidate in candidates}
        if len(canonical) != 1:
            raise DatasetRecoveryEvidenceError(
                "Authoritative project-link snapshots disagree."
            )
        return json.loads(next(iter(canonical)).decode("utf-8"))

    def _artifact_verification(
        self,
        *,
        dataset: Mapping[str, Any],
        version: Mapping[str, Any],
        sources: Sequence[_VerifiedSource],
        dataset_id: str,
        dataset_version_id: str,
    ) -> Dict[str, Any]:
        artifact = _safe_relative_path(
            self.storage.paths.root,
            version.get("fullDataPath"),
        )
        if not artifact.is_file():
            raise DatasetRecoveryEvidenceError(
                "The exact immutable dataset artifact is unavailable."
            )
        authoritative_content_hash = _text(version.get("hash")).casefold()
        if not authoritative_content_hash:
            raise DatasetRecoveryEvidenceError(
                "Tier 1 version metadata has no content checksum."
            )
        actual_content_hash = _sha256_file(artifact)
        if actual_content_hash != authoritative_content_hash:
            raise DatasetRecoveryEvidenceError(
                "The immutable artifact checksum does not match Tier 1 metadata."
            )
        version_root = artifact.parent
        metadata_path = version_root / "metadata.json"
        lineage_path = version_root / "lineage.json"
        schema_path = version_root / "schema.json"
        profile_path = version_root / "profile.json"
        preview_path = _safe_relative_path(
            self.storage.paths.root,
            version.get("previewPath"),
        )
        sample_path = _safe_relative_path(
            self.storage.paths.root,
            version.get("samplePath"),
        )
        registered_profile_path = _safe_relative_path(
            self.storage.paths.root,
            version.get("profilePath"),
        )
        if any(
            path.parent != version_root
            for path in (preview_path, sample_path, registered_profile_path)
        ) or registered_profile_path != profile_path:
            raise DatasetRecoveryEvidenceError(
                "Immutable version sidecar paths do not share the exact version root."
            )
        for required in (
            metadata_path,
            lineage_path,
            schema_path,
            profile_path,
            preview_path,
            sample_path,
        ):
            _assert_regular_unlinked_file(
                required,
                root=self.storage.paths.root,
                label=f"Required artifact sidecar {required.name}",
            )
        metadata = _read_json_bytes(metadata_path.read_bytes(), "metadata.json")
        lineage = _read_json_bytes(lineage_path.read_bytes(), "lineage.json")
        profile = _read_json_bytes(profile_path.read_bytes(), "profile.json")
        schema = _read_json_bytes(schema_path.read_bytes(), "schema.json")
        if (
            _text(metadata.get("datasetId")) != dataset_id
            or _text(metadata.get("versionId")) != dataset_version_id
        ):
            raise DatasetRecoveryEvidenceError(
                "Artifact metadata does not match the exact requested identity."
            )
        if _text(lineage.get("hash")).casefold() != actual_content_hash:
            raise DatasetRecoveryEvidenceError(
                "Artifact lineage does not match the immutable content checksum."
            )
        if not _text(lineage.get("registeredBy")) or not _text(lineage.get("registeredAt")):
            raise DatasetRecoveryEvidenceError(
                "Artifact lineage lacks registration provenance."
            )
        if (
            _text(version.get("createdBy")) != _text(lineage.get("registeredBy"))
            or _text(version.get("originalFilename"))
            != _text(metadata.get("originalFilename"))
            or _text(version.get("originalFilename"))
            != _text(lineage.get("originalFilename"))
            or _text(dataset.get("sourceType"))
            != _text(lineage.get("sourceType"))
        ):
            raise DatasetRecoveryEvidenceError(
                "Artifact registration provenance conflicts with Tier 1 metadata."
            )
        try:
            expected_rows = int(version.get("rowCount"))
            expected_columns = int(version.get("columnCount"))
            profile_rows = int(profile.get("rowCount"))
            profile_columns = int(profile.get("columnCount"))
        except (TypeError, ValueError) as exc:
            raise DatasetRecoveryEvidenceError(
                "Immutable row or column counts are missing."
            ) from exc
        if (
            expected_rows <= 0
            or expected_columns <= 0
            or profile_rows != expected_rows
            or profile_columns != expected_columns
        ):
            raise DatasetRecoveryEvidenceError(
                "Profile row or column counts conflict with Tier 1 metadata."
            )
        target_candidates = profile.get("targetCandidates")
        if not isinstance(target_candidates, list) or not target_candidates:
            raise DatasetRecoveryEvidenceError(
                "Target-capable dataset metadata could not be established."
            )
        schema_columns = schema.get("columns")
        schema_names = {
            _text(column.get("name"))
            for column in (schema_columns or [])
            if isinstance(column, dict) and _text(column.get("name"))
        }
        if (
            not isinstance(schema_columns, list)
            or len(schema_names) != expected_columns
            or not schema_names.intersection(_text(item) for item in target_candidates)
        ):
            raise DatasetRecoveryEvidenceError(
                "Target-capable profile metadata does not agree with the exact schema."
            )
        profile_schema = profile.get("schema")
        profile_schema_names = {
            _text(column.get("name"))
            for column in (profile_schema or [])
            if isinstance(column, dict) and _text(column.get("name"))
        }
        if (
            not isinstance(profile_schema, list)
            or profile_schema_names != schema_names
        ):
            raise DatasetRecoveryEvidenceError(
                "The immutable profile schema conflicts with the exact schema sidecar."
            )
        schema_order = [
            _text(column.get("name"))
            for column in schema_columns
            if isinstance(column, dict)
        ]
        try:
            with artifact.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader)
                actual_rows = 0
                for row in reader:
                    if len(row) != expected_columns:
                        raise DatasetRecoveryEvidenceError(
                            "The immutable CSV contains a row with the wrong column count."
                        )
                    actual_rows += 1
        except (OSError, UnicodeDecodeError, csv.Error, StopIteration) as exc:
            raise DatasetRecoveryEvidenceError(
                "The immutable CSV artifact could not be structurally verified."
            ) from exc
        if header != schema_order or actual_rows != expected_rows:
            raise DatasetRecoveryEvidenceError(
                "The immutable CSV shape conflicts with Tier 1 and profile metadata."
            )
        actual_schema_hash = _sha256_file(schema_path)
        expected_schema_hashes = {
            _text(version.get("schemaHash")).casefold()
        } - {""}
        for source in self._source_by_basename(sources, "schema.json", tier=1):
            if source.kind != "immutable_version_schema_snapshot":
                continue
            if dataset_id in source.reference and dataset_version_id in source.reference:
                expected_schema_hashes.add(source.sha256)
        if not expected_schema_hashes:
            raise DatasetRecoveryEvidenceError(
                "No authoritative schema checksum or exact Tier 1 schema snapshot was supplied."
            )
        if len(expected_schema_hashes) != 1:
            raise DatasetRecoveryEvidenceError(
                "Authoritative schema checksums disagree."
            )
        if actual_schema_hash != next(iter(expected_schema_hashes)):
            raise DatasetRecoveryEvidenceError(
                "The schema checksum does not match authoritative evidence."
            )
        exact_live_files = (
            artifact,
            metadata_path,
            lineage_path,
            schema_path,
            profile_path,
            preview_path,
            sample_path,
        )
        exact_live_signals = {
            (
                _sha256_file(path),
                _sha256_bytes(
                    os.path.normcase(str(path.resolve())).encode("utf-8")
                ),
            )
            for path in exact_live_files
        }
        corroborating_families = {
            source.family
            for source in sources
            if source.tier == 2
            and (source.sha256, source.physical_path_sha256)
            in exact_live_signals
        }
        return {
            "artifact_path": str(artifact),
            "artifact_sha256": actual_content_hash,
            "schema_sha256": actual_schema_hash,
            "row_count": expected_rows,
            "column_count": expected_columns,
            "registered_by": _text(lineage.get("registeredBy")),
            "registered_at": _text(lineage.get("registeredAt")),
            "corroborating_families": sorted(corroborating_families),
        }

    def _owner_acl_verification(
        self,
        dataset: Mapping[str, Any],
    ) -> Dict[str, Any]:
        owner = _text(dataset.get("ownerUserId"))
        if not owner:
            raise DatasetRecoveryEvidenceError("Tier 1 owner evidence is missing.")
        access = dataset.get("access")
        if not isinstance(access, list) or not access:
            raise DatasetRecoveryEvidenceError("Tier 1 ACL evidence is missing.")
        normalized: list[Dict[str, str]] = []
        for grant in access:
            if not isinstance(grant, dict):
                raise DatasetRecoveryEvidenceError("Tier 1 ACL evidence is malformed.")
            user_id = _text(grant.get("userId"))
            role = _text(grant.get("role")).casefold()
            if not user_id or role not in ALLOWED_DATASET_ROLES:
                raise DatasetRecoveryEvidenceError("Tier 1 ACL evidence is malformed.")
            normalized.append({"userId": user_id, "role": role})
        if {"userId": owner, "role": "owner"} not in normalized:
            raise DatasetRecoveryEvidenceError(
                "The proven owner is not preserved as owner in the Tier 1 ACL."
            )
        try:
            with closing(self._read_only_connection(self.security_database)) as connection:
                principals = {
                    row[0]
                    for row in connection.execute(
                        "SELECT user_id FROM users WHERE user_id IN (%s)"
                        % ",".join("?" for _ in normalized),
                        tuple(grant["userId"] for grant in normalized),
                    ).fetchall()
                }
        except sqlite3.Error as exc:
            raise DatasetRecoveryEvidenceError(
                "ACL principals could not be verified against ATLAS security."
            ) from exc
        missing = sorted({grant["userId"] for grant in normalized} - principals)
        if missing:
            raise DatasetRecoveryEvidenceError(
                "One or more proven ACL principals do not exist in ATLAS security."
            )
        return {"owner_user_id": owner, "access": normalized}

    def _project_link_verification(
        self,
        *,
        dataset: Mapping[str, Any],
        project_link: Mapping[str, Any],
    ) -> Dict[str, Any]:
        required = {
            "projectId": _text(project_link.get("projectId")),
            "datasetId": _text(project_link.get("datasetId")),
            "versionId": _text(project_link.get("versionId")),
            "datasetRole": _text(project_link.get("datasetRole")),
            "linkedAt": _text(project_link.get("linkedAt")),
            "linkedBy": _text(project_link.get("linkedBy")),
        }
        if not all(required.values()):
            raise DatasetRecoveryEvidenceError(
                "Tier 1 project-link provenance is incomplete."
            )
        registry_matches = [
            link
            for link in (dataset.get("linkedProjects") or [])
            if isinstance(link, dict)
            and _text(link.get("projectId")) == required["projectId"]
        ]
        expected_projection = {
            "projectId": required["projectId"],
            "versionId": required["versionId"],
            "datasetRole": required["datasetRole"],
        }
        if (
            len(registry_matches) != 1
            or _canonical_json(registry_matches[0])
            != _canonical_json(expected_projection)
        ):
            raise DatasetRecoveryEvidenceError(
                "Tier 1 registry and project-link projections disagree."
            )
        try:
            with closing(self._read_only_connection(self.security_database)) as connection:
                principal = connection.execute(
                    "SELECT user_id FROM users WHERE user_id = ?",
                    (required["linkedBy"],),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DatasetRecoveryEvidenceError(
                "Project-link provenance could not be verified against ATLAS security."
            ) from exc
        if principal is None:
            raise DatasetRecoveryEvidenceError(
                "The proven project-link actor does not exist in ATLAS security."
            )
        return {
            "linked_by": required["linkedBy"],
            "linked_at": required["linkedAt"],
            "dataset_role": required["datasetRole"],
            "registry_projection_verified": True,
        }

    @staticmethod
    def _scope_record(
        dataset: Mapping[str, Any],
        version: Mapping[str, Any],
        project_link: Mapping[str, Any] | None,
    ) -> Dict[str, Any]:
        recovered = dict(dataset)
        recovered["versions"] = [dict(version)]
        recovered["linkedProjects"] = (
            [
                {
                    "projectId": project_link.get("projectId"),
                    "versionId": project_link.get("versionId"),
                    "datasetRole": project_link.get("datasetRole") or "modeling",
                }
            ]
            if project_link
            else []
        )
        return recovered

    @staticmethod
    def _immutable_dataset_contract(record: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in record.items()
            if key not in {"versions", "linkedProjects", "updatedAt"}
        }

    @staticmethod
    def _immutable_version_contract(record: Mapping[str, Any]) -> Dict[str, Any]:
        return dict(record)

    def _planned_registry(
        self,
        current: Mapping[str, Any],
        recovered: Mapping[str, Any],
        dataset_version_id: str,
    ) -> tuple[Dict[str, Any], bool]:
        datasets = current.get("datasets")
        if not isinstance(datasets, list):
            raise DatasetRecoveryConflictError(
                "The live registry has no valid datasets array."
            )
        requested_id = _text(recovered.get("datasetId"))
        for other in datasets:
            if not isinstance(other, dict):
                raise DatasetRecoveryConflictError("The live registry is malformed.")
            for version in other.get("versions") or []:
                if (
                    isinstance(version, dict)
                    and _text(version.get("versionId")) == dataset_version_id
                    and _text(other.get("datasetId")) != requested_id
                ):
                    raise DatasetRecoveryConflictError(
                        "The exact version_id is already bound to another dataset."
                    )
        matching_datasets = [
            item
            for item in datasets
            if isinstance(item, dict)
            and _text(item.get("datasetId")) == requested_id
        ]
        if len(matching_datasets) > 1:
            raise DatasetRecoveryConflictError(
                "The live registry contains an ambiguous duplicate dataset_id."
            )
        existing = matching_datasets[0] if matching_datasets else None
        planned = json.loads(json.dumps(current))
        if existing is None:
            planned["datasets"].append(dict(recovered))
            return planned, True
        if self._immutable_dataset_contract(existing) != self._immutable_dataset_contract(recovered):
            raise DatasetRecoveryConflictError(
                "Existing dataset metadata conflicts with authoritative evidence."
            )
        recovered_version = dict((recovered.get("versions") or [])[0])
        matching_versions = [
            item
            for item in (existing.get("versions") or [])
            if isinstance(item, dict)
            and _text(item.get("versionId")) == dataset_version_id
        ]
        if len(matching_versions) > 1:
            raise DatasetRecoveryConflictError(
                "The live registry contains an ambiguous duplicate version_id."
            )
        existing_version = matching_versions[0] if matching_versions else None
        version_changed = False
        if existing_version is not None:
            if self._immutable_version_contract(existing_version) != self._immutable_version_contract(recovered_version):
                raise DatasetRecoveryConflictError(
                    "Existing version metadata conflicts with authoritative evidence."
                )
        else:
            for item in planned["datasets"]:
                if _text(item.get("datasetId")) == requested_id:
                    item.setdefault("versions", []).append(recovered_version)
                    version_changed = True
                    break

        recovered_links = recovered.get("linkedProjects") or []
        if not recovered_links:
            return planned, version_changed
        recovered_link = recovered_links[0]
        project_id = _text(recovered_link.get("projectId"))
        registry_link_changed = False
        for item in planned["datasets"]:
            if _text(item.get("datasetId")) != requested_id:
                continue
            matching_links = [
                link
                for link in (item.get("linkedProjects") or [])
                if isinstance(link, dict)
                and _text(link.get("projectId")) == project_id
            ]
            if matching_links:
                if (
                    len(matching_links) != 1
                    or _canonical_json(matching_links[0])
                    != _canonical_json(recovered_link)
                ):
                    raise DatasetRecoveryConflictError(
                        "The live registry project projection conflicts with authoritative evidence."
                    )
            else:
                item.setdefault("linkedProjects", []).append(dict(recovered_link))
                registry_link_changed = True
            break
        return planned, version_changed or registry_link_changed

    @staticmethod
    def _planned_links(
        current: Mapping[str, Any],
        project_link: Mapping[str, Any] | None,
    ) -> tuple[Dict[str, Any], bool]:
        links = current.get("links")
        if not isinstance(links, list):
            raise DatasetRecoveryConflictError("The live project-links store is malformed.")
        planned = json.loads(json.dumps(current))
        if project_link is None:
            return planned, False
        matching = [
            link
            for link in links
            if isinstance(link, dict)
            and _text(link.get("projectId")) == _text(project_link.get("projectId"))
            and _text(link.get("datasetId")) == _text(project_link.get("datasetId"))
        ]
        if matching:
            if len(matching) != 1 or _canonical_json(matching[0]) != _canonical_json(project_link):
                raise DatasetRecoveryConflictError(
                    "The live project link conflicts with authoritative evidence."
                )
            return planned, False
        planned["links"].append(dict(project_link))
        return planned, True

    def _active_selection(self, project_id: str | None) -> Dict[str, Any] | None:
        if not project_id:
            return None
        try:
            with closing(self._read_only_connection(self.persistence_database)) as connection:
                row = connection.execute(
                    "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                return dict(row) if row else None
        except sqlite3.Error as exc:
            raise DatasetRecoveryConflictError(
                "The active-selection authority could not be inspected."
            ) from exc

    def _durable_project_link(
        self,
        project_id: str | None,
        dataset_id: str,
    ) -> Dict[str, Any] | None:
        if not project_id:
            return None
        try:
            with closing(self._read_only_connection(self.persistence_database)) as connection:
                row = connection.execute(
                    """
                    SELECT * FROM project_dataset_links
                    WHERE project_id = ? AND dataset_id = ?
                    """,
                    (project_id, dataset_id),
                ).fetchone()
                return dict(row) if row else None
        except sqlite3.Error as exc:
            raise DatasetRecoveryConflictError(
                "The durable project-link authority could not be inspected."
            ) from exc

    def _verify_recovery_durable_link_ownership(
        self,
        *,
        link: Mapping[str, Any],
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        operation_id: str,
        actor_user_id: str,
        reason: str,
    ) -> str:
        """Prove a durable link and its append-only event belong to one recovery."""

        try:
            metadata = json.loads(_text(link.get("metadata_json")) or "{}")
        except (TypeError, ValueError) as exc:
            raise DatasetRecoveryConflictError(
                "The recovery-created durable project link has malformed metadata."
            ) from exc
        if not isinstance(metadata, Mapping) or (
            _text(link.get("project_id")) != project_id
            or _text(link.get("dataset_id")) != dataset_id
            or _text(link.get("link_status")).casefold() != "active"
            or _text(link.get("linked_by")) != actor_user_id
            or _text(metadata.get("recoveryOperationId")) != operation_id
            or _text(metadata.get("lastValidatedVersionId")) != dataset_version_id
            or _text(metadata.get("reason")) != reason
        ):
            raise DatasetRecoveryConflictError(
                "The recovery-created durable project link no longer has exact operation ownership."
            )
        with closing(self._read_only_connection(self.persistence_database)) as connection:
            event_rows = connection.execute(
                """
                SELECT activation_event_id, actor_user_id, metadata_json
                FROM project_dataset_activation_events
                WHERE project_id = ? AND dataset_id = ?
                  AND event_type = 'project_dataset_linked'
                  AND event_status = 'complete'
                """,
                (project_id, dataset_id),
            ).fetchall()
        matching_event_ids: list[str] = []
        for event_row in event_rows:
            try:
                event_metadata = json.loads(event_row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                continue
            if (
                isinstance(event_metadata, Mapping)
                and _text(event_row["actor_user_id"]) == actor_user_id
                and _text(event_metadata.get("recoveryOperationId")) == operation_id
                and _text(event_metadata.get("requestedDatasetVersionId"))
                == dataset_version_id
                and _text(event_metadata.get("reason")) == reason
            ):
                matching_event_ids.append(_text(event_row["activation_event_id"]))
        if len(matching_event_ids) != 1:
            raise DatasetRecoveryConflictError(
                "The recovery-created durable project-link event is missing or ambiguous."
            )
        return matching_event_ids[0]

    def _authority_record_counts(
        self,
        registry: Mapping[str, Any],
        legacy_links: Mapping[str, Any],
    ) -> Dict[str, int]:
        """Count every record in the five Dataset Library authority surfaces."""

        datasets = registry.get("datasets")
        links = legacy_links.get("links")
        if not isinstance(datasets, list) or not isinstance(links, list):
            raise DatasetRecoveryConflictError(
                "Dataset Library authority record counts could not be established."
            )
        version_records = 0
        for dataset in datasets:
            if not isinstance(dataset, Mapping):
                raise DatasetRecoveryConflictError(
                    "The live registry contains a malformed dataset record."
                )
            versions = dataset.get("versions") or []
            if not isinstance(versions, list) or any(
                not isinstance(version, Mapping) for version in versions
            ):
                raise DatasetRecoveryConflictError(
                    "The live registry contains malformed version records."
                )
            version_records += len(versions)
        if any(not isinstance(link, Mapping) for link in links):
            raise DatasetRecoveryConflictError(
                "The live project-links store contains malformed records."
            )
        try:
            with closing(self._read_only_connection(self.persistence_database)) as connection:
                durable_link_records = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM project_dataset_links"
                    ).fetchone()[0]
                )
                active_selection_records = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM active_modeling_dataset_versions"
                    ).fetchone()[0]
                )
        except sqlite3.Error as exc:
            raise DatasetRecoveryConflictError(
                "Durable Dataset Library authority record counts could not be established."
            ) from exc
        return {
            "registry_dataset_records": len(datasets),
            "registry_version_records": version_records,
            "legacy_project_link_records": len(links),
            "durable_project_link_records": durable_link_records,
            "active_selection_records": active_selection_records,
        }

    @staticmethod
    def _projected_record_counts(
        current_counts: Mapping[str, int],
        planned_registry: Mapping[str, Any],
        planned_legacy_links: Mapping[str, Any],
        *,
        durable_link_change: bool,
    ) -> Dict[str, int]:
        datasets = planned_registry.get("datasets") or []
        links = planned_legacy_links.get("links") or []
        return {
            "registry_dataset_records": len(datasets),
            "registry_version_records": sum(
                len(dataset.get("versions") or [])
                for dataset in datasets
                if isinstance(dataset, Mapping)
            ),
            "legacy_project_link_records": len(links),
            "durable_project_link_records": int(
                current_counts["durable_project_link_records"]
            )
            + int(durable_link_change),
            "active_selection_records": int(
                current_counts["active_selection_records"]
            ),
        }

    def _creation_audit_corroboration(
        self,
        *,
        dataset: Mapping[str, Any],
        dataset_id: str,
        dataset_version_id: str,
        project_id: str | None,
    ) -> Dict[str, Any]:
        """Corroborate identity from the durable audit log when available.

        This signal is deliberately supplemental: it can strengthen a valid
        Tier 1 + independent Tier 2 proof, but it can never substitute for the
        exact live artifact evidence required by recovery.
        """

        try:
            with closing(self._read_only_connection(self.persistence_database)) as connection:
                exists = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'audit_log'
                    """
                ).fetchone()
                if exists is None:
                    return {"status": "not_available"}
                rows = connection.execute(
                    """
                    SELECT audit_id, project_id, user_id, created_at, metadata_json
                    FROM audit_log
                    WHERE action_type = 'dataset.created'
                      AND entity_type = 'dataset'
                      AND entity_id = ?
                    ORDER BY created_at ASC, audit_id ASC
                    """,
                    (dataset_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise DatasetRecoveryConflictError(
                "The durable creation-audit authority could not be inspected."
            ) from exc
        if not rows:
            return {"status": "not_available"}

        matches: list[sqlite3.Row] = []
        owner_id = _text(dataset.get("ownerUserId"))
        dataset_name = _text(dataset.get("name"))
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(metadata, dict):
                continue
            if (
                _text(row["user_id"]) == owner_id
                and _text(metadata.get("versionId")) == dataset_version_id
                and _text(metadata.get("name")) == dataset_name
                and _text(metadata.get("outcome")).casefold() == "success"
                and _text(row["created_at"])
                and (
                    not project_id
                    or not _text(row["project_id"])
                    or _text(row["project_id"]) == project_id
                )
            ):
                matches.append(row)
        if len(matches) != 1:
            raise DatasetRecoveryEvidenceError(
                "Durable dataset-creation audit rows conflict with the exact recovery identity."
            )
        match = matches[0]
        return {
            "status": "verified",
            "audit_id": _text(match["audit_id"]),
            "created_at": _text(match["created_at"]),
            "actor_user_id": _text(match["user_id"]),
        }

    def _remove_recovery_durable_link(
        self,
        *,
        project_id: str,
        dataset_id: str,
        operation_id: str,
        dataset_version_id: str,
        actor_user_id: str,
        reason: str,
        active_selection_before: Mapping[str, Any] | None,
    ) -> bool:
        """Compensate only a link inserted by this exact failed operation."""

        with closing(sqlite3.connect(self.persistence_database)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            active_row = connection.execute(
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            active_now = dict(active_row) if active_row else None
            if active_now != (
                dict(active_selection_before) if active_selection_before else None
            ):
                raise DatasetRecoveryApplyError(
                    "The active dataset selection changed before recovery rollback."
                )
            link_row = connection.execute(
                """
                SELECT * FROM project_dataset_links
                WHERE project_id = ? AND dataset_id = ?
                """,
                (project_id, dataset_id),
            ).fetchone()
            if link_row is None:
                connection.commit()
                return False
            try:
                metadata = json.loads(link_row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            if _text(metadata.get("recoveryOperationId")) != operation_id:
                raise DatasetRecoveryApplyError(
                    "The durable project link changed before recovery rollback."
                )
            event_rows = connection.execute(
                """
                SELECT activation_event_id, metadata_json
                FROM project_dataset_activation_events
                WHERE project_id = ?
                  AND dataset_id = ?
                  AND event_type = 'project_dataset_linked'
                  AND event_status = 'complete'
                """,
                (project_id, dataset_id),
            ).fetchall()
            matching_event_ids = []
            for event_row in event_rows:
                try:
                    event_metadata = json.loads(event_row["metadata_json"] or "{}")
                except (TypeError, ValueError):
                    event_metadata = {}
                if _text(event_metadata.get("recoveryOperationId")) == operation_id:
                    matching_event_ids.append(event_row["activation_event_id"])
            if len(matching_event_ids) != 1:
                raise DatasetRecoveryApplyError(
                    "The recovery project-link audit event is missing or ambiguous."
                )
            connection.execute(
                """
                DELETE FROM project_dataset_links
                WHERE project_id = ? AND dataset_id = ?
                """,
                (project_id, dataset_id),
            )
            connection.execute(
                """
                INSERT INTO project_dataset_activation_events (
                  activation_event_id, project_id, dataset_id,
                  dataset_version_id, activation_revision, event_type,
                  event_status, actor_user_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, NULL, ?, 'complete', ?, ?, ?)
                """,
                (
                    f"dataset-activation-{uuid.uuid4().hex}",
                    project_id,
                    dataset_id,
                    dataset_version_id,
                    "project_dataset_link_recovery_compensated",
                    actor_user_id,
                    _now_iso(),
                    _canonical_json(
                        {
                            "source": "dataset_library_forensic_recovery",
                            "recoveryOperationId": operation_id,
                            "compensatedEventId": matching_event_ids[0],
                            "reason": reason,
                        }
                    ).decode("utf-8"),
                ),
            )
            connection.commit()
            return True

    def plan(
        self,
        request: DatasetRecoveryRequest,
        *,
        allow_pending_recovery: bool = False,
    ) -> Dict[str, Any]:
        request.validate()
        if (
            request.backup_directory.expanduser().resolve()
            != self.storage.paths.backup_root.expanduser().resolve()
        ):
            raise DatasetRecoveryEvidenceError(
                "The requested backup directory must match the configured external backup root."
            )
        actor = self._operator(_text(request.actor_user_id))
        project_auth = (
            self._project_authorization(actor, _text(request.project_id))
            if request.project_id
            else None
        )
        report_bytes = request.evidence_report.read_bytes()
        evidence_sha = _sha256_bytes(report_bytes)
        evidence = _read_json_bytes(report_bytes, "evidence report")
        sources = self._verified_sources(evidence, request)
        tier1_registry = self._source_by_basename(sources, "registry.json", tier=1)
        tier1_registry = [
            source
            for source in tier1_registry
            if source.kind == "authoritative_registry_snapshot"
        ]
        if not tier1_registry:
            raise DatasetRecoveryEvidenceError(
                "Recovery requires a Tier 1 authoritative registry snapshot."
            )
        dataset = self._exact_dataset_record(tier1_registry, _text(request.dataset_id))
        version = self._exact_version_record(dataset, _text(request.dataset_version_id))
        embedded_dataset = evidence.get("dataset_record")
        if embedded_dataset is not None and _canonical_json(embedded_dataset) != _canonical_json(dataset):
            raise DatasetRecoveryEvidenceError(
                "The evidence report dataset record conflicts with its Tier 1 source."
            )
        owner_acl = self._owner_acl_verification(dataset)
        creation_audit = self._creation_audit_corroboration(
            dataset=dataset,
            dataset_id=_text(request.dataset_id),
            dataset_version_id=_text(request.dataset_version_id),
            project_id=_text(request.project_id) or None,
        )
        if not request.project_id and (
            _text(actor.get("role")).casefold() != "admin"
            and _text(actor.get("user_id")) not in {
                grant["userId"]
                for grant in owner_acl["access"]
                if grant["role"] in {"owner", "editor"}
            }
        ):
            raise DatasetRecoveryAuthorizationError(
                "The actor is neither an administrator nor a proven dataset owner/editor."
            )
        artifact = self._artifact_verification(
            dataset=dataset,
            version=version,
            sources=sources,
            dataset_id=_text(request.dataset_id),
            dataset_version_id=_text(request.dataset_version_id),
        )
        tier1_families = {source.family for source in sources if source.tier == 1}
        tier2_families = set(artifact["corroborating_families"])
        if not tier1_families or not tier2_families:
            raise DatasetRecoveryEvidenceError(
                "Recovery requires a supplied, verified Tier 2 exact-artifact source."
            )
        if tier1_families & tier2_families:
            raise DatasetRecoveryEvidenceError(
                "Tier 1 and Tier 2 evidence must come from independent physical families."
            )
        project_link = None
        project_link_provenance = None
        if request.project_id:
            link_sources = self._source_by_basename(
                sources,
                "project_links.json",
                tier=1,
            )
            link_sources = [
                source
                for source in link_sources
                if source.kind == "authoritative_project_links_snapshot"
            ]
            if not link_sources:
                raise DatasetRecoveryEvidenceError(
                    "Project-link recovery requires a Tier 1 project-links snapshot."
                )
            project_link = self._exact_project_link(
                link_sources,
                project_id=_text(request.project_id),
                dataset_id=_text(request.dataset_id),
                dataset_version_id=_text(request.dataset_version_id),
            )
            if project_link is None:
                raise DatasetRecoveryEvidenceError(
                    "The exact project relationship is not proven by Tier 1 evidence."
                )
            project_link_provenance = self._project_link_verification(
                dataset=dataset,
                project_link=project_link,
            )
            embedded_link = evidence.get("project_link_record")
            if embedded_link is not None and _canonical_json(embedded_link) != _canonical_json(project_link):
                raise DatasetRecoveryEvidenceError(
                    "The evidence report project link conflicts with its Tier 1 source."
                )
        recovered = self._scope_record(dataset, version, project_link)
        current_registry = self.storage.read_registry(
            allow_pending_recovery=allow_pending_recovery
        )
        current_links = self.storage.read_links(
            allow_pending_recovery=allow_pending_recovery
        )
        registry_before_bytes = self.storage.paths.registry_path.read_bytes()
        links_before_bytes = self.storage.paths.project_links_path.read_bytes()
        if (
            _canonical_json(_read_json_bytes(registry_before_bytes, "live registry"))
            != _canonical_json(current_registry)
            or _canonical_json(_read_json_bytes(links_before_bytes, "live project links"))
            != _canonical_json(current_links)
        ):
            raise DatasetRecoveryConflictError(
                "Dataset Library authority changed during recovery inspection."
            )
        registry_before_sha256 = _sha256_bytes(registry_before_bytes)
        links_before_sha256 = _sha256_bytes(links_before_bytes)
        before_record_counts = self._authority_record_counts(
            current_registry,
            current_links,
        )
        planned_registry, registry_change = self._planned_registry(
            current_registry,
            recovered,
            _text(request.dataset_version_id),
        )
        planned_links, links_change = self._planned_links(current_links, project_link)
        active_before = self._active_selection(request.project_id)
        durable_link_before = self._durable_project_link(
            request.project_id,
            _text(request.dataset_id),
        )
        if active_before is not None:
            active_dataset_id = _text(active_before.get("dataset_id"))
            active_link = self._durable_project_link(
                request.project_id,
                active_dataset_id,
            )
            if (
                not isinstance(active_link, Mapping)
                or _text(active_link.get("link_status")).casefold() != "active"
            ):
                raise DatasetRecoveryConflictError(
                    "The existing active dataset selection has no durable authorization link."
                )
        if durable_link_before is not None and (
            _text(durable_link_before.get("link_status")).casefold() != "active"
        ):
            raise DatasetRecoveryConflictError(
                "A current durable project-link revocation conflicts with historical recovery evidence."
            )
        durable_link_change = bool(project_link and durable_link_before is None)
        projected_record_counts = self._projected_record_counts(
            before_record_counts,
            planned_registry,
            planned_links,
            durable_link_change=durable_link_change,
        )
        operation_contract = {
            "dataset_id": _text(request.dataset_id),
            "dataset_version_id": _text(request.dataset_version_id),
            "project_id": _text(request.project_id) or None,
            "evidence_report_sha256": evidence_sha,
            "recovered_record_sha256": _sha256_bytes(_canonical_json(recovered)),
        }
        operation_id = "dataset-recovery-" + _sha256_bytes(
            _canonical_json(operation_contract)
        )[:24]
        return {
            "schema_version": "atlas.dataset-library-recovery.v1",
            "report_id": f"recovery-report-{uuid.uuid4().hex}",
            "operation_id": operation_id,
            "mode": "dry_run",
            "generated_at": _now_iso(),
            "scope": {
                "dataset_id": _text(request.dataset_id),
                "dataset_version_id": _text(request.dataset_version_id),
                "project_id": _text(request.project_id) or None,
            },
            "actor": {
                "user_id": _text(actor.get("user_id")),
                "exists": True,
                "active": True,
                "role": _text(actor.get("role")),
                "project_authorization": project_auth,
            },
            "evidence": {
                "report_sha256": evidence_sha,
                "tier1_families": sorted(tier1_families),
                "sources": [
                    {
                        "tier": source.tier,
                        "kind": source.kind,
                        "family": source.family,
                        "reference": source.reference,
                        "sha256": source.sha256,
                    }
                    for source in sources
                ],
                "threshold_met": True,
                "confidence": "high",
            },
            "reconciliation": {
                "state": (
                    "recoverable"
                    if registry_change or links_change or durable_link_change
                    else "healthy"
                ),
                "registry_state": "missing_exact_record" if registry_change else "exact_record_present",
                "artifact_state": "verified",
                "owner_evidence": owner_acl,
                "acl_evidence": "verified_tier1",
                "project_link_evidence": "verified_tier1" if project_link else "not_requested",
                "project_link_provenance": project_link_provenance,
                "creation_audit_corroboration": creation_audit,
                "active_selection_evidence": active_before,
                "recovery_eligible": True,
                "blocking_reasons": [],
            },
            "artifact_verification": artifact,
            "plan": {
                "registry_change": registry_change,
                "legacy_project_links_change": links_change,
                "durable_project_link_change": durable_link_change,
                "active_selection_change": False,
                "operations": [
                    operation
                    for operation, enabled in (
                        ("restore_exact_registry_record", registry_change),
                        ("restore_proven_legacy_link_projection", links_change),
                        ("restore_proven_durable_project_link", durable_link_change),
                        ("record_maintenance_audit", True),
                    )
                    if enabled
                ],
            },
            "before": {
                "registry_sha256": registry_before_sha256,
                "project_links_sha256": links_before_sha256,
                "active_selection": active_before,
                "record_counts": before_record_counts,
            },
            "after": {
                "registry_sha256": (
                    _storage_json_sha256(planned_registry)
                    if registry_change
                    else registry_before_sha256
                ),
                "project_links_sha256": (
                    _storage_json_sha256(planned_links)
                    if links_change
                    else links_before_sha256
                ),
                "active_selection": active_before,
                "record_counts": projected_record_counts,
                "projected": True,
            },
            "active_selection": {
                "before": active_before,
                "after": active_before,
                "intentionally_unset": active_before is None,
            },
            "backup": None,
            "mutation": {
                "attempted": False,
                "applied": False,
                "idempotent": not (
                    registry_change or links_change or durable_link_change
                ),
                "rolled_back": False,
            },
            "audit": None,
            "errors": [],
            "_internal": {
                "current_registry": current_registry,
                "current_links": current_links,
                "planned_registry": planned_registry,
                "planned_links": planned_links,
                "recovered_record": recovered,
                "project_link": project_link,
                "durable_link_before": durable_link_before,
                "registry_before_bytes": registry_before_bytes,
                "links_before_bytes": links_before_bytes,
            },
        }

    def _maintenance_event_exists(self, operation_id: str) -> Dict[str, Any] | None:
        try:
            with closing(self._read_only_connection(self.persistence_database)) as connection:
                row = connection.execute(
                    """
                    SELECT * FROM dataset_library_maintenance_events
                    WHERE operation_id = ? AND event_status = 'complete'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (operation_id,),
                ).fetchone()
                return dict(row) if row else None
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).casefold():
                return None
            raise

    @staticmethod
    def _state_sha256(value: Any) -> str:
        return _sha256_bytes(_canonical_json(value))

    def _completed_event_matches_current(
        self,
        *,
        plan: Mapping[str, Any],
        internal: Mapping[str, Any],
        event: Mapping[str, Any],
    ) -> bool:
        if (
            not bool(plan.get("mutation", {}).get("idempotent"))
            or plan.get("reconciliation", {}).get("state") != "healthy"
            or _text(event.get("registry_after_sha256"))
            != _text(plan.get("before", {}).get("registry_sha256"))
        ):
            return False
        try:
            metadata = json.loads(_text(event.get("metadata_json")) or "{}")
        except (TypeError, ValueError):
            return False
        durable_before = internal.get("durable_link_before")
        durable_present = bool(
            isinstance(durable_before, Mapping)
            and _text(durable_before.get("link_status")).casefold() == "active"
        )
        return bool(
            _text(metadata.get("projectLinksAfterSha256"))
            == _text(plan.get("before", {}).get("project_links_sha256"))
            and bool(metadata.get("durableLinkPresent")) == durable_present
            and _text(metadata.get("activeSelectionSha256"))
            == self._state_sha256(plan.get("active_selection", {}).get("before"))
        )

    def _record_idempotent_apply_attempt(
        self,
        *,
        plan: Mapping[str, Any],
        internal: Mapping[str, Any],
        request: DatasetRecoveryRequest,
        attempt_id: str,
        prior_event: Mapping[str, Any],
        concurrent_completion_observed: bool,
    ) -> str:
        """Append an audit row for every no-op apply invocation.

        A prior complete event proves the recovered state, but it must never
        substitute for the audit trail of a new operator attempt.  This method
        records the no-op without creating another backup or changing any
        Dataset Library authority.
        """

        durable_before = internal.get("durable_link_before")
        durable_present = bool(
            isinstance(durable_before, Mapping)
            and _text(durable_before.get("link_status")).casefold() == "active"
        )
        return self._write_maintenance_event_reconciled(
            plan=plan,
            request=request,
            status="complete",
            attempt_id=attempt_id,
            backup_manifest_sha256=None,
            registry_after_sha256=plan["before"]["registry_sha256"],
            metadata={
                "idempotent": True,
                "stateMutationPerformed": False,
                "backupCreated": False,
                "priorMaintenanceEventId": prior_event[
                    "maintenance_event_id"
                ],
                "concurrentCompletionObserved": bool(
                    concurrent_completion_observed
                ),
                "projectLinksAfterSha256": plan["before"][
                    "project_links_sha256"
                ],
                "durableLinkPresent": durable_present,
                "activeSelectionSha256": self._state_sha256(
                    plan["active_selection"]["before"]
                ),
                "activeSelectionChanged": False,
            },
        )

    @staticmethod
    def _verified_inputs_match(
        first: Mapping[str, Any],
        second: Mapping[str, Any],
    ) -> bool:
        return bool(
            _text(first.get("operation_id")) == _text(second.get("operation_id"))
            and first.get("evidence") == second.get("evidence")
            and first.get("artifact_verification")
            == second.get("artifact_verification")
            and first.get("scope") == second.get("scope")
        )

    def _maintenance_schema_available(self) -> bool:
        expected_columns = {
            "maintenance_event_id": ("TEXT", False, None, 1, 0),
            "attempt_id": ("TEXT", True, None, 0, 0),
            "operation_id": ("TEXT", True, None, 0, 0),
            "operation_type": ("TEXT", True, None, 0, 0),
            "event_status": ("TEXT", True, None, 0, 0),
            "actor_user_id": ("TEXT", True, None, 0, 0),
            "project_id": ("TEXT", False, None, 0, 0),
            "dataset_id": ("TEXT", True, None, 0, 0),
            "dataset_version_id": ("TEXT", True, None, 0, 0),
            "reason": ("TEXT", True, None, 0, 0),
            "evidence_report_sha256": ("TEXT", True, None, 0, 0),
            "backup_manifest_sha256": ("TEXT", False, None, 0, 0),
            "registry_before_sha256": ("TEXT", False, None, 0, 0),
            "registry_after_sha256": ("TEXT", False, None, 0, 0),
            "created_at": ("TEXT", True, None, 0, 0),
            "metadata_json": ("TEXT", True, "'{}'", 0, 0),
        }
        expected_indexes = {
            "idx_dataset_library_maintenance_operation_event": (
                ("operation_id", False, "BINARY"),
                ("event_status", False, "BINARY"),
                ("created_at", True, "BINARY"),
            ),
            "idx_dataset_library_maintenance_attempt": (
                ("attempt_id", False, "BINARY"),
                ("created_at", False, "BINARY"),
            ),
            "idx_dataset_library_maintenance_identity": (
                ("dataset_id", False, "BINARY"),
                ("dataset_version_id", False, "BINARY"),
                ("created_at", True, "BINARY"),
            ),
            "idx_dataset_library_maintenance_project": (
                ("project_id", False, "BINARY"),
                ("created_at", True, "BINARY"),
            ),
        }
        primary_key_index = "sqlite_autoindex_dataset_library_maintenance_events_1"
        try:
            with closing(self._read_only_connection(self.persistence_database)) as connection:
                row = connection.execute(
                    """
                    SELECT sql FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'dataset_library_maintenance_events'
                    """
                ).fetchone()
                if row is None:
                    return False
                maintenance_table_name = "dataset_library_maintenance_events"
                trigger_rows = connection.execute(
                    """
                    SELECT name, tbl_name, sql
                    FROM sqlite_master
                    WHERE type = 'trigger'
                    """
                ).fetchall()
                relevant_triggers: dict[str, Dict[str, Any]] = {}
                for trigger in trigger_rows:
                    trigger_name = _text(trigger["name"]).casefold()
                    attached_table = _text(trigger["tbl_name"]).casefold()
                    trigger_sql = _normalized_sql_contract(trigger["sql"])
                    if (
                        attached_table == maintenance_table_name
                        or maintenance_table_name in trigger_name
                        or re.search(
                            rf"\b{re.escape(maintenance_table_name)}\b",
                            trigger_sql,
                            flags=re.IGNORECASE,
                        )
                    ):
                        relevant_triggers[trigger_name] = dict(trigger)
                trigger_inventory = set(relevant_triggers)
                expected_trigger_inventory = set(
                    _MAINTENANCE_TRIGGER_CONTRACT_SQL
                )
                if trigger_inventory not in (
                    set(),
                    expected_trigger_inventory,
                ):
                    raise DatasetRecoveryApplyError(
                        "The maintenance audit append-only trigger inventory is incompatible."
                    )
                trigger_contract_present = bool(trigger_inventory)
                if trigger_contract_present:
                    for trigger_name, expected_trigger_sql in (
                        _MAINTENANCE_TRIGGER_CONTRACT_SQL.items()
                    ):
                        trigger = relevant_triggers[trigger_name]
                        if _text(trigger.get("tbl_name")).casefold() != maintenance_table_name:
                            raise DatasetRecoveryApplyError(
                                "A maintenance audit append-only trigger is attached to the wrong table."
                            )
                        expected_sql = _normalized_sql_contract(expected_trigger_sql)
                        expected_without_if_not_exists = expected_sql.replace(
                            "create trigger if not exists ",
                            "create trigger ",
                            1,
                        )
                        if _normalized_sql_contract(trigger.get("sql")) not in {
                            expected_sql,
                            expected_without_if_not_exists,
                        }:
                            raise DatasetRecoveryApplyError(
                                "A maintenance audit append-only trigger contract is incompatible."
                            )
                column_rows = connection.execute(
                    "PRAGMA table_xinfo(dataset_library_maintenance_events)"
                ).fetchall()
                columns = {
                    _text(info["name"]): dict(info)
                    for info in column_rows
                }
                indexes = {
                    _text(info["name"]): dict(info)
                    for info in connection.execute(
                        "PRAGMA index_list(dataset_library_maintenance_events)"
                    ).fetchall()
                }
                if (
                    len(column_rows) != len(expected_columns)
                    or set(columns) != set(expected_columns)
                ):
                    raise DatasetRecoveryApplyError(
                        "The maintenance audit table is incompatible with migration 0022."
                    )
                for name, expected in expected_columns.items():
                    column = columns[name]
                    actual = (
                        _text(column.get("type")).upper(),
                        bool(column.get("notnull")),
                        column.get("dflt_value"),
                        int(column.get("pk") or 0),
                        int(column.get("hidden") or 0),
                    )
                    if actual != expected:
                        raise DatasetRecoveryApplyError(
                            "The maintenance audit column contract is incompatible "
                            "with migration 0022."
                        )
                expected_index_names = set(expected_indexes) | {
                    primary_key_index
                }
                if set(indexes) != expected_index_names:
                    raise DatasetRecoveryApplyError(
                        "The maintenance audit indexes contain an unexpected or missing index."
                    )
                for index_name, expected_parts in expected_indexes.items():
                    index = indexes[index_name]
                    if (
                        bool(index.get("unique"))
                        or _text(index.get("origin")) != "c"
                        or bool(index.get("partial"))
                    ):
                        raise DatasetRecoveryApplyError(
                            "A maintenance audit index has incompatible uniqueness, origin, or partial-index metadata."
                        )
                    index_parts = [
                        dict(info)
                        for info in connection.execute(
                            f"PRAGMA index_xinfo('{index_name}')"
                        ).fetchall()
                    ]
                    parts = tuple(
                        (
                            _text(info["name"]),
                            bool(info["desc"]),
                            _text(info["coll"]).upper(),
                        )
                        for info in index_parts
                        if bool(info["key"])
                    )
                    if parts != expected_parts:
                        raise DatasetRecoveryApplyError(
                            "A maintenance audit index has incompatible columns or order, or collation."
                        )
                    auxiliary_parts = tuple(
                        (
                            int(info["cid"]),
                            _text(info["name"]),
                            bool(info["desc"]),
                            _text(info["coll"]).upper(),
                        )
                        for info in index_parts
                        if not bool(info["key"])
                    )
                    if auxiliary_parts != ((-1, "", False, "BINARY"),):
                        raise DatasetRecoveryApplyError(
                            "A maintenance audit index has incompatible auxiliary columns."
                        )
                primary_index = indexes[primary_key_index]
                if (
                    not bool(primary_index.get("unique"))
                    or _text(primary_index.get("origin")) != "pk"
                    or bool(primary_index.get("partial"))
                ):
                    raise DatasetRecoveryApplyError(
                        "The maintenance audit primary-key index is incompatible."
                    )
                primary_parts = [
                    dict(info)
                    for info in connection.execute(
                        f"PRAGMA index_xinfo('{primary_key_index}')"
                    ).fetchall()
                ]
                primary_keys = tuple(
                    (
                        _text(info["name"]),
                        bool(info["desc"]),
                        _text(info["coll"]).upper(),
                    )
                    for info in primary_parts
                    if bool(info["key"])
                )
                primary_auxiliary = tuple(
                    (
                        int(info["cid"]),
                        _text(info["name"]),
                        bool(info["desc"]),
                        _text(info["coll"]).upper(),
                    )
                    for info in primary_parts
                    if not bool(info["key"])
                )
                if (
                    primary_keys
                    != (("maintenance_event_id", False, "BINARY"),)
                    or primary_auxiliary != ((-1, "", False, "BINARY"),)
                ):
                    raise DatasetRecoveryApplyError(
                        "The maintenance audit primary-key index is incompatible."
                    )
                normalized_sql = _normalized_sql_contract(row["sql"])
                expected_sql = _normalized_sql_contract(
                    _MAINTENANCE_TABLE_CONTRACT_SQL
                )
                expected_without_if_not_exists = expected_sql.replace(
                    "create table if not exists ",
                    "create table ",
                    1,
                )
                if normalized_sql not in {
                    expected_sql,
                    expected_without_if_not_exists,
                }:
                    raise DatasetRecoveryApplyError(
                        "The maintenance audit executable table contract is incompatible."
                    )
                migration = connection.execute(
                    """
                    SELECT 1 FROM schema_migrations
                    WHERE version = '0022_dataset_library_maintenance.sql'
                    """
                ).fetchone()
                if migration is None:
                    raise DatasetRecoveryApplyError(
                        "The maintenance audit migration record is missing."
                    )
                append_only_migration = connection.execute(
                    """
                    SELECT 1 FROM schema_migrations
                    WHERE version = '0023_dataset_library_maintenance_append_only.sql'
                    """
                ).fetchone()
                migration_0023_present = append_only_migration is not None
                if trigger_contract_present != migration_0023_present:
                    raise DatasetRecoveryApplyError(
                        "The maintenance audit append-only migration state is inconsistent."
                    )
                return trigger_contract_present
        except DatasetRecoveryApplyError:
            raise
        except sqlite3.Error as exc:
            raise DatasetRecoveryApplyError(
                "The maintenance audit authority could not be inspected."
            ) from exc

    def _ensure_maintenance_schema(self) -> bool:
        """Apply pending maintenance migrations only after safety backup."""

        if self._maintenance_schema_available():
            return False
        migration_root = (
            Path(__file__).resolve().parents[1]
            / "persistence"
            / "migrations"
        )
        migration_names = (
            "0022_dataset_library_maintenance.sql",
            "0023_dataset_library_maintenance_append_only.sql",
        )
        migration_paths: list[Path] = []
        for migration_name in migration_names:
            migration_path = migration_root / migration_name
            if not migration_path.is_file():
                raise DatasetRecoveryApplyError(
                    f"Dataset Library maintenance migration {migration_name} is unavailable."
                )
            migration_paths.append(migration_path)
        with closing(sqlite3.connect(self.persistence_database)) as connection:
            connection.row_factory = sqlite3.Row
            has_migration_table = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_migrations'
                """
            ).fetchone() is not None
            if not has_migration_table:
                raise DatasetRecoveryApplyError(
                    "The persistence migration authority is unavailable."
                )
            applied = {
                _text(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            pending = [path for path in migration_paths if path.name not in applied]
            if not pending:
                raise DatasetRecoveryApplyError(
                    "The maintenance migration records exist but their schema is incomplete."
                )
        try:
            from ..persistence.db import Database, PersistenceUnavailableError

            Database(self.persistence_database).apply_migrations(pending)
        except (OSError, sqlite3.Error, PersistenceUnavailableError) as exc:
            raise DatasetRecoveryApplyError(
                "Dataset Library maintenance migrations failed."
            ) from exc
        if not self._maintenance_schema_available():
            raise DatasetRecoveryApplyError(
                "Dataset Library maintenance migrations did not persist."
            )
        return True

    def _write_maintenance_event(
        self,
        *,
        plan: Mapping[str, Any],
        request: DatasetRecoveryRequest,
        status: str,
        attempt_id: str,
        backup_manifest_sha256: str | None,
        registry_after_sha256: str | None,
        metadata: Mapping[str, Any],
        event_id: str | None = None,
        created_at: str | None = None,
    ) -> str:
        event_id = event_id or f"dataset-maintenance-{uuid.uuid4().hex}"
        expected = self._maintenance_event_record(
            plan=plan,
            request=request,
            status=status,
            attempt_id=attempt_id,
            backup_manifest_sha256=backup_manifest_sha256,
            registry_after_sha256=registry_after_sha256,
            metadata=metadata,
            event_id=event_id,
            created_at=created_at or _now_iso(),
        )
        with closing(sqlite3.connect(self.persistence_database)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO dataset_library_maintenance_events (
                  maintenance_event_id, attempt_id, operation_id,
                  operation_type, event_status,
                  actor_user_id, project_id, dataset_id, dataset_version_id,
                  reason, evidence_report_sha256, backup_manifest_sha256,
                  registry_before_sha256, registry_after_sha256, created_at,
                  metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(expected[column] for column in _MAINTENANCE_EVENT_COLUMNS),
            )
            connection.commit()
        return event_id

    @staticmethod
    def _maintenance_event_record(
        *,
        plan: Mapping[str, Any],
        request: DatasetRecoveryRequest,
        status: str,
        attempt_id: str,
        backup_manifest_sha256: str | None,
        registry_after_sha256: str | None,
        metadata: Mapping[str, Any],
        event_id: str,
        created_at: str,
    ) -> Dict[str, Any]:
        return {
            "maintenance_event_id": event_id,
            "attempt_id": attempt_id,
            "operation_id": plan["operation_id"],
            "operation_type": "recover",
            "event_status": status,
            "actor_user_id": request.actor_user_id,
            "project_id": request.project_id,
            "dataset_id": request.dataset_id,
            "dataset_version_id": request.dataset_version_id,
            "reason": request.reason,
            "evidence_report_sha256": plan["evidence"]["report_sha256"],
            "backup_manifest_sha256": backup_manifest_sha256,
            "registry_before_sha256": plan["before"]["registry_sha256"],
            "registry_after_sha256": registry_after_sha256,
            "created_at": created_at,
            "metadata_json": _canonical_json(dict(metadata)).decode("utf-8"),
        }

    def _maintenance_event_matches_exactly(
        self,
        expected: Mapping[str, Any],
    ) -> bool:
        with closing(
            self._read_only_connection(self.persistence_database)
        ) as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(_MAINTENANCE_EVENT_COLUMNS)}
                FROM dataset_library_maintenance_events
                WHERE maintenance_event_id = ?
                """,
                (expected["maintenance_event_id"],),
            ).fetchone()
        if row is None:
            return False
        actual = {
            column: row[column] for column in _MAINTENANCE_EVENT_COLUMNS
        }
        return actual == dict(expected)

    def _write_maintenance_event_reconciled(
        self,
        *,
        plan: Mapping[str, Any],
        request: DatasetRecoveryRequest,
        status: str,
        attempt_id: str,
        backup_manifest_sha256: str | None,
        registry_after_sha256: str | None,
        metadata: Mapping[str, Any],
        event_id: str | None = None,
    ) -> str:
        """Persist one append-only event and reconcile an ambiguous DB commit.

        SQLite can report an error after the commit reached durable storage.
        A caller must therefore query the reserved event id and accept it only
        when every immutable field matches the requested row exactly.
        """

        reserved_event_id = event_id or f"dataset-maintenance-{uuid.uuid4().hex}"
        reserved_created_at = _now_iso()
        expected = self._maintenance_event_record(
            plan=plan,
            request=request,
            status=status,
            attempt_id=attempt_id,
            backup_manifest_sha256=backup_manifest_sha256,
            registry_after_sha256=registry_after_sha256,
            metadata=metadata,
            event_id=reserved_event_id,
            created_at=reserved_created_at,
        )
        write_error: Exception | None = None
        try:
            self._write_maintenance_event(
                plan=plan,
                request=request,
                status=status,
                attempt_id=attempt_id,
                backup_manifest_sha256=backup_manifest_sha256,
                registry_after_sha256=registry_after_sha256,
                metadata=metadata,
                event_id=reserved_event_id,
                created_at=reserved_created_at,
            )
        except Exception as exc:
            write_error = exc
        try:
            exact_readback = self._maintenance_event_matches_exactly(expected)
        except Exception as readback_error:
            if write_error is not None:
                raise write_error
            raise DatasetRecoveryApplyError(
                "The maintenance audit event exact readback could not be verified."
            ) from readback_error
        if exact_readback:
            return reserved_event_id
        if write_error is not None:
            raise write_error
        raise DatasetRecoveryApplyError(
            "The maintenance audit event failed exact immutable readback."
        )

    def _write_recovery_journal_reconciled(
        self,
        payload: Mapping[str, Any],
        *,
        expected_sha256: str | None,
    ) -> Dict[str, Any]:
        """Write a journal state and resolve post-replace verification errors."""

        expected_after_sha256 = _storage_json_sha256(payload)
        try:
            result = self.storage.write_recovery_journal(
                payload,
                expected_sha256=expected_sha256,
            )
            if _text(result.get("afterSha256")) != expected_after_sha256:
                raise DatasetRecoveryApplyError(
                    "The recovery journal checksum did not match its exact payload."
                )
            return result
        except Exception:
            try:
                live = self.storage.read_recovery_journal(required=True)
                live_sha256 = self.storage.sha256_file(
                    self.storage.paths.recovery_journal_path
                )
                if live == dict(payload) and live_sha256 == expected_after_sha256:
                    return {
                        "changed": True,
                        "path": str(self.storage.paths.recovery_journal_path),
                        "beforeSha256": expected_sha256,
                        "afterSha256": live_sha256,
                        "ambiguousOutcomeReconciled": True,
                    }
            except Exception:
                pass
            raise

    def _build_applied_report(
        self,
        *,
        plan: Dict[str, Any],
        backup: Mapping[str, Any] | None,
        registry_after_sha256: str,
        project_links_after_sha256: str,
        active_selection_after: Mapping[str, Any] | None,
        record_counts_after: Mapping[str, int],
        maintenance_event_id: str,
        attempt_id: str,
    ) -> Dict[str, Any]:
        """Build the success result only after the recovery commit is durable.

        Keeping this post-commit boundary explicit makes it possible to prove
        that a presentation/result-building failure cannot compensate an
        already committed authority change.
        """

        plan["mode"] = "apply"
        plan["backup"] = dict(backup) if backup is not None else None
        plan["after"] = {
            "registry_sha256": registry_after_sha256,
            "project_links_sha256": project_links_after_sha256,
            "active_selection": active_selection_after,
            "record_counts": dict(record_counts_after),
            "projected": False,
        }
        plan["active_selection"]["after"] = active_selection_after
        plan["mutation"].update(
            {"attempted": True, "applied": True, "idempotent": False}
        )
        plan["audit"] = {
            "maintenance_event_id": maintenance_event_id,
            "status": "complete",
        }
        plan["journal"] = {
            "status": "committed",
            "attempt_id": attempt_id,
        }
        return plan

    @staticmethod
    def _sqlite_integrity(
        connection: sqlite3.Connection,
        *,
        required_tables: set[str],
        label: str,
    ) -> Dict[str, Any]:
        quick = [
            _text(row[0])
            for row in connection.execute("PRAGMA quick_check").fetchall()
        ]
        integrity = [
            _text(row[0])
            for row in connection.execute("PRAGMA integrity_check").fetchall()
        ]
        tables = {
            _text(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = sorted(required_tables - tables)
        if quick != ["ok"] or integrity != ["ok"] or missing:
            raise DatasetRecoveryApplyError(
                f"The {label} failed SQLite integrity or authority-table validation."
            )
        return {
            "quickCheck": "ok",
            "integrityCheck": "ok",
            "requiredTables": sorted(required_tables),
        }

    def _backup_persistence_database(self, bundle_path: Path) -> Dict[str, Any]:
        target = bundle_path / "atlas_persistence_before.sqlite3"
        required_tables = {
            "projects",
            "project_dataset_links",
            "active_modeling_dataset_versions",
            "project_dataset_activation_events",
            "schema_migrations",
        }
        source_uri = f"file:{self.persistence_database.as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source:
            source_integrity = self._sqlite_integrity(
                source,
                required_tables=required_tables,
                label="source persistence database",
            )
            with closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
        target_uri = f"file:{target.as_posix()}?mode=ro"
        with closing(sqlite3.connect(target_uri, uri=True)) as copied:
            backup_integrity = self._sqlite_integrity(
                copied,
                required_tables=required_tables,
                label="persistence safety backup",
            )
        return {
            "logical_name": "persistence_database",
            "file": target.name,
            "sha256": _sha256_file(target),
            "bytes": target.stat().st_size,
            "sourceIntegrity": source_integrity,
            "backupIntegrity": backup_integrity,
        }

    @staticmethod
    def _verify_recovery_backup(
        *,
        operation_id: str,
        before: Mapping[str, Any],
        bundle_path: Path,
        storage_manifest_path: Path,
        storage_manifest_sha256: str,
        safety_manifest_path: Path,
        safety_manifest_sha256: str,
        persistence_backup: Mapping[str, Any],
    ) -> Dict[str, Any]:
        _assert_unlinked_path(
            bundle_path,
            root=None,
            label="The recovery backup bundle",
        )
        bundle_path = bundle_path.resolve()

        def safe_bundle_file(path: Path) -> Path:
            _assert_unlinked_path(
                path,
                root=bundle_path,
                label="A recovery backup member",
            )
            resolved = path.resolve()
            if resolved == bundle_path or bundle_path not in resolved.parents:
                raise DatasetRecoveryApplyError(
                    "A recovery backup member escapes its safety bundle."
                )
            if not resolved.is_file():
                raise DatasetRecoveryApplyError(
                    "A required recovery backup member is missing."
                )
            return resolved

        manifest_path = safe_bundle_file(storage_manifest_path)
        if _sha256_file(manifest_path) != storage_manifest_sha256:
            raise DatasetRecoveryApplyError(
                "The Dataset Library backup manifest checksum failed."
            )
        manifest = _read_json_bytes(
            manifest_path.read_bytes(),
            "Dataset Library backup manifest",
        )
        files = manifest.get("files")
        if (
            manifest.get("kind") != "atlas_dataset_library_backup"
            or manifest.get("formatVersion") != 1
            or not isinstance(files, list)
        ):
            raise DatasetRecoveryApplyError(
                "The Dataset Library backup manifest is malformed."
            )
        authority_records: Dict[str, Mapping[str, Any]] = {}
        for record in files:
            if not isinstance(record, Mapping) or not record.get("exists"):
                continue
            source_path = _text(record.get("sourceRelativePath")).replace(
                "\\", "/"
            )
            if source_path in authority_records:
                raise DatasetRecoveryApplyError(
                    "The Dataset Library backup contains a duplicate authority snapshot."
                )
            authority_records[source_path] = record
        if set(authority_records) != {"registry.json", "project_links.json"}:
            raise DatasetRecoveryApplyError(
                "The Dataset Library backup does not contain both exact authority documents."
            )
        expected_before_hashes = {
            "registry.json": _text(before.get("registry_sha256")).casefold(),
            "project_links.json": _text(
                before.get("project_links_sha256")
            ).casefold(),
        }
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
            for expected_hash in expected_before_hashes.values()
        ):
            raise DatasetRecoveryApplyError(
                "The recovery plan has no valid exact before-state checksums."
            )
        verified_files = 0
        for source_path, record in authority_records.items():
            relative = _text(record.get("backupRelativePath"))
            member = safe_bundle_file(bundle_path / relative)
            declared_hash = _text(record.get("sha256")).casefold()
            if (
                declared_hash != expected_before_hashes[source_path]
                or _sha256_file(member) != expected_before_hashes[source_path]
                or member.stat().st_size != int(record.get("sizeBytes") or -1)
            ):
                raise DatasetRecoveryApplyError(
                    "A Dataset Library backup snapshot does not match the exact pre-recovery authority state."
                )
            verified_files += 1
        persistence_path = safe_bundle_file(
            bundle_path / _text(persistence_backup.get("file"))
        )
        if (
            _sha256_file(persistence_path)
            != _text(persistence_backup.get("sha256"))
            or persistence_path.stat().st_size
            != int(persistence_backup.get("bytes") or -1)
        ):
            raise DatasetRecoveryApplyError(
                "The persistence safety-backup checksum failed."
            )
        persistence_uri = f"file:{persistence_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(persistence_uri, uri=True)) as connection:
            quick = [
                _text(row[0])
                for row in connection.execute("PRAGMA quick_check").fetchall()
            ]
            integrity = [
                _text(row[0])
                for row in connection.execute("PRAGMA integrity_check").fetchall()
            ]
            required_tables = set(
                persistence_backup.get("backupIntegrity", {}).get(
                    "requiredTables", []
                )
            )
            tables = {
                _text(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        expected_required_tables = {
            "projects",
            "project_dataset_links",
            "active_modeling_dataset_versions",
            "project_dataset_activation_events",
            "schema_migrations",
        }
        if (
            quick != ["ok"]
            or integrity != ["ok"]
            or required_tables != expected_required_tables
            or not required_tables.issubset(tables)
        ):
            raise DatasetRecoveryApplyError(
                "The persistence safety backup failed independent SQLite verification."
            )
        safety_path = safe_bundle_file(safety_manifest_path)
        if _sha256_file(safety_path) != safety_manifest_sha256:
            raise DatasetRecoveryApplyError(
                "The recovery safety-manifest checksum failed."
            )
        safety = _read_json_bytes(
            safety_path.read_bytes(),
            "recovery safety manifest",
        )
        if (
            safety.get("schema_version")
            != "atlas.dataset-library-recovery-backup.v1"
            or _text(safety.get("operation_id")) != operation_id
            or _text(safety.get("storage_bundle_manifest_sha256"))
            != storage_manifest_sha256
            or safety.get("persistence_database") != dict(persistence_backup)
            or safety.get("before") != dict(before)
        ):
            raise DatasetRecoveryApplyError(
                "The recovery safety manifest does not bind every backup component."
            )
        return {
            "status": "verified",
            "storageManifestSha256": storage_manifest_sha256,
            "safetyManifestSha256": safety_manifest_sha256,
            "persistenceDatabaseSha256": persistence_backup.get("sha256"),
            "verifiedSnapshotFiles": verified_files,
        }

    def _resume_commit_pending(
        self,
        request: DatasetRecoveryRequest,
        observed_journal: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Finalize an exact post-commit recovery without compensating it."""

        with self.storage.exclusive_lock():
            journal = self.storage.read_recovery_journal(required=True)
            if journal != dict(observed_journal):
                raise DatasetRecoveryConflictError(
                    "The recovery journal changed before resume acquired the library lock."
                )
            if _text(journal.get("status")).casefold() != "commit_pending":
                raise DatasetRecoveryConflictError(
                    "Only an exact commit_pending recovery can be resumed."
                )
            journal_sha256 = self.storage.sha256_file(
                self.storage.paths.recovery_journal_path
            )
            plan = self.plan(request, allow_pending_recovery=True)
            internal = dict(plan.pop("_internal"))
            expected_project = _text(request.project_id) or None
            journal_project = _text(journal.get("projectId")) or None
            if (
                _text(journal.get("operationId")) != _text(plan["operation_id"])
                or _text(journal.get("actorUserId")) != _text(request.actor_user_id)
                or journal_project != expected_project
                or _text(journal.get("datasetId")) != _text(request.dataset_id)
                or _text(journal.get("datasetVersionId"))
                != _text(request.dataset_version_id)
                or _text(journal.get("reason")) != _text(request.reason)
            ):
                raise DatasetRecoveryConflictError(
                    "The commit_pending journal does not match the exact recovery request."
                )
            before = journal.get("before")
            after = journal.get("after")
            if not isinstance(before, Mapping) or not isinstance(after, Mapping):
                raise DatasetRecoveryApplyError(
                    "The commit_pending journal has no exact before/after proof."
                )
            backup_proof = journal.get("backupProof")
            if not isinstance(backup_proof, Mapping):
                raise DatasetRecoveryApplyError(
                    "The commit_pending journal has no complete safety-backup proof."
                )
            persistence_backup = backup_proof.get("persistenceDatabase")
            backup_before = backup_proof.get("before")
            if (
                not isinstance(persistence_backup, Mapping)
                or not isinstance(backup_before, Mapping)
                or _text(backup_proof.get("safetyManifestSha256")).casefold()
                != _text(journal.get("backupManifestSha256")).casefold()
            ):
                raise DatasetRecoveryApplyError(
                    "The commit_pending safety-backup proof is malformed."
                )
            backup_verification = self._verify_recovery_backup(
                operation_id=_text(journal.get("operationId")),
                before=backup_before,
                bundle_path=Path(_text(backup_proof.get("bundlePath"))),
                storage_manifest_path=Path(
                    _text(backup_proof.get("storageManifestPath"))
                ),
                storage_manifest_sha256=_text(
                    backup_proof.get("storageManifestSha256")
                ).casefold(),
                safety_manifest_path=Path(
                    _text(backup_proof.get("safetyManifestPath"))
                ),
                safety_manifest_sha256=_text(
                    backup_proof.get("safetyManifestSha256")
                ).casefold(),
                persistence_backup=persistence_backup,
            )
            registry_after = self.storage.sha256_file(
                self.storage.paths.registry_path
            )
            links_after = self.storage.sha256_file(
                self.storage.paths.project_links_path
            )
            active_after = self._active_selection(request.project_id)
            durable_after = self._durable_project_link(
                request.project_id,
                request.dataset_id,
            )
            durable_after_sha256 = self._state_sha256(durable_after)
            durable_link_changed = journal.get("durableLinkChanged")
            durable_before_sha256 = _text(
                before.get("durableProjectLinkSha256")
            ).casefold()
            expected_durable_after_sha256 = _text(
                after.get("durableProjectLinkSha256")
            ).casefold()
            if (
                registry_after != _text(after.get("registrySha256")).casefold()
                or links_after
                != _text(after.get("projectLinksSha256")).casefold()
                or self._state_sha256(active_after)
                != _text(after.get("activeSelectionSha256")).casefold()
                or not re.fullmatch(r"[0-9a-f]{64}", durable_before_sha256)
                or not re.fullmatch(
                    r"[0-9a-f]{64}", expected_durable_after_sha256
                )
                or durable_after_sha256 != expected_durable_after_sha256
                or not isinstance(durable_link_changed, bool)
                or plan["reconciliation"]["state"] != "healthy"
                or not plan["mutation"]["idempotent"]
            ):
                raise DatasetRecoveryConflictError(
                    "The committed authorities do not match the exact pending decision."
                )
            if durable_link_changed:
                if (
                    durable_before_sha256 != self._state_sha256(None)
                    or not isinstance(durable_after, Mapping)
                ):
                    raise DatasetRecoveryConflictError(
                        "The pending recovery has contradictory durable-link provenance."
                    )
                self._verify_recovery_durable_link_ownership(
                    link=durable_after,
                    project_id=request.project_id or "",
                    dataset_id=request.dataset_id,
                    dataset_version_id=request.dataset_version_id,
                    operation_id=plan["operation_id"],
                    actor_user_id=request.actor_user_id,
                    reason=request.reason,
                )
            elif durable_before_sha256 != expected_durable_after_sha256:
                raise DatasetRecoveryConflictError(
                    "The pending recovery durable-link hashes contradict its change flag."
                )
            if not self._maintenance_schema_available():
                raise DatasetRecoveryApplyError(
                    "The immutable maintenance schema is unavailable during resume."
                )
            event_id = _text(journal.get("plannedMaintenanceEventId"))
            if not SAFE_IDENTIFIER_RE.fullmatch(event_id):
                raise DatasetRecoveryApplyError(
                    "The pending terminal maintenance-event identifier is invalid."
                )
            attempt_id = _text(journal.get("attemptId"))
            backup_manifest_sha256 = _text(
                journal.get("backupManifestSha256")
            ).casefold()
            durable_present = bool(
                isinstance(durable_after, Mapping)
                and _text(durable_after.get("link_status")).casefold() == "active"
            )
            event_plan = {
                **plan,
                "before": {
                    **dict(plan["before"]),
                    "registry_sha256": _text(
                        before.get("registrySha256")
                    ).casefold(),
                },
            }
            with closing(
                self._read_only_connection(self.persistence_database)
            ) as connection:
                event_row = connection.execute(
                    f"""
                    SELECT {", ".join(_MAINTENANCE_EVENT_COLUMNS)}
                    FROM dataset_library_maintenance_events
                    WHERE maintenance_event_id = ?
                    """,
                    (event_id,),
                ).fetchone()
                started_row = connection.execute(
                    """
                    SELECT maintenance_event_id
                    FROM dataset_library_maintenance_events
                    WHERE attempt_id = ? AND event_status = 'started'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (attempt_id,),
                ).fetchone()
            started_event_id = (
                _text(started_row["maintenance_event_id"])
                if started_row is not None
                else None
            )
            event_previously_durable = event_row is not None
            if event_row is not None:
                event = dict(event_row)
                try:
                    metadata = json.loads(_text(event.get("metadata_json")) or "{}")
                except (TypeError, ValueError) as exc:
                    raise DatasetRecoveryApplyError(
                        "The pending terminal event metadata is malformed."
                    ) from exc
                committed_at = _text(
                    metadata.get("terminalJournalCommittedAt")
                )
                if not committed_at:
                    raise DatasetRecoveryApplyError(
                        "The pending terminal event cannot reconstruct its exact journal."
                    )
                committed_journal = {
                    **journal,
                    "status": "committed",
                    "committedAt": committed_at,
                    "maintenanceEventId": event_id,
                }
                expected_event = self._maintenance_event_record(
                    plan=event_plan,
                    request=request,
                    status="complete",
                    attempt_id=attempt_id,
                    backup_manifest_sha256=backup_manifest_sha256,
                    registry_after_sha256=registry_after,
                    metadata=metadata,
                    event_id=event_id,
                    created_at=_text(event.get("created_at")),
                )
                if event != expected_event or (
                    metadata.get("terminalJournalPayloadSha256")
                    != self._state_sha256(committed_journal)
                ):
                    raise DatasetRecoveryApplyError(
                        "The pending terminal maintenance event failed exact resume verification."
                    )
            else:
                committed_at = _now_iso()
                committed_journal = {
                    **journal,
                    "status": "committed",
                    "committedAt": committed_at,
                    "maintenanceEventId": event_id,
                }
                metadata = {
                    "registryChanged": before.get("registrySha256")
                    != after.get("registrySha256"),
                    "legacyLinksChanged": before.get("projectLinksSha256")
                    != after.get("projectLinksSha256"),
                    "durableLinkChanged": durable_link_changed,
                    "durableLinkPresent": durable_present,
                    "backupVerified": True,
                    "maintenanceSchemaApplied": False,
                    "projectLinksAfterSha256": links_after,
                    "activeSelectionSha256": self._state_sha256(active_after),
                    "activeSelectionChanged": False,
                    "recoveryJournalStatus": "commit_pending",
                    "terminalJournalTarget": "committed",
                    "terminalJournalCommittedAt": committed_at,
                    "terminalJournalPayloadSha256": self._state_sha256(
                        committed_journal
                    ),
                    "startedMaintenanceEventId": started_event_id,
                    "recoveryResumed": True,
                }
                self._write_maintenance_event_reconciled(
                    plan=event_plan,
                    request=request,
                    status="complete",
                    attempt_id=attempt_id,
                    backup_manifest_sha256=backup_manifest_sha256,
                    registry_after_sha256=registry_after,
                    metadata=metadata,
                    event_id=event_id,
                )
            self._write_recovery_journal_reconciled(
                committed_journal,
                expected_sha256=journal_sha256,
            )
            self.storage.assert_no_pending_recovery()
            report = self._build_applied_report(
                plan=plan,
                backup={
                    "status": "verified_before_commit_resume",
                    "safetyManifestSha256": backup_manifest_sha256,
                    "verification": backup_verification,
                },
                registry_after_sha256=registry_after,
                project_links_after_sha256=links_after,
                active_selection_after=active_after,
                record_counts_after=plan["before"]["record_counts"],
                maintenance_event_id=event_id,
                attempt_id=attempt_id,
            )
            report["resume"] = {
                "commitPendingFinalized": True,
                "eventPreviouslyDurable": event_previously_durable,
            }
            return report

    def apply(self, request: DatasetRecoveryRequest) -> Dict[str, Any]:
        observed_journal = self.storage.read_recovery_journal(required=False)
        if (
            observed_journal is not None
            and _text(observed_journal.get("status")).casefold()
            == "commit_pending"
        ):
            return self._resume_commit_pending(request, observed_journal)
        plan = self.plan(request)
        internal = dict(plan.pop("_internal"))
        attempt_id = f"dataset-recovery-attempt-{uuid.uuid4().hex}"
        maintenance_schema_available = self._maintenance_schema_available()
        existing_event = self._maintenance_event_exists(plan["operation_id"])
        if (
            maintenance_schema_available
            and existing_event is not None
            and self._completed_event_matches_current(
                plan=plan,
                internal=internal,
                event=existing_event,
            )
        ):
            event_id = self._record_idempotent_apply_attempt(
                plan=plan,
                internal=internal,
                request=request,
                attempt_id=attempt_id,
                prior_event=existing_event,
                concurrent_completion_observed=False,
            )
            plan["mode"] = "apply"
            plan["after"]["projected"] = False
            plan["mutation"].update(
                {"attempted": False, "applied": False, "idempotent": True}
            )
            plan["audit"] = {
                "maintenance_event_id": event_id,
                "status": "complete",
                "idempotent": True,
                "prior_maintenance_event_id": existing_event[
                    "maintenance_event_id"
                ],
            }
            return plan

        registry_changed = bool(plan["plan"]["registry_change"])
        links_changed = bool(plan["plan"]["legacy_project_links_change"])
        durable_link_change = bool(plan["plan"]["durable_project_link_change"])
        project_link = internal.get("project_link")
        if (
            not registry_changed
            and not links_changed
            and not durable_link_change
            and maintenance_schema_available
        ):
            event_id = self._write_maintenance_event_reconciled(
                plan=plan,
                request=request,
                status="complete",
                attempt_id=attempt_id,
                backup_manifest_sha256=None,
                registry_after_sha256=plan["before"]["registry_sha256"],
                metadata={
                    "idempotent": True,
                    "projectLinksAfterSha256": plan["before"][
                        "project_links_sha256"
                    ],
                    "durableLinkPresent": bool(
                        isinstance(internal.get("durable_link_before"), Mapping)
                        and _text(
                            internal["durable_link_before"].get("link_status")
                        ).casefold()
                        == "active"
                    ),
                    "activeSelectionSha256": self._state_sha256(
                        plan["active_selection"]["before"]
                    ),
                    "activeSelectionChanged": False,
                },
            )
            plan["mode"] = "apply"
            plan["after"]["projected"] = False
            plan["audit"] = {"maintenance_event_id": event_id, "status": "complete"}
            plan["mutation"].update(
                {"attempted": False, "applied": False, "idempotent": True}
            )
            return plan

        backup_manifest_sha = None
        backup: Dict[str, Any] | None = None
        registry_written = False
        links_written = False
        registry_write_attempted = False
        links_write_attempted = False
        durable_link_changed = False
        durable_link_write_attempted = False
        registry_write_sha = _storage_json_sha256(internal["planned_registry"])
        links_write_sha = _storage_json_sha256(internal["planned_links"])
        rollback_complete = True
        rollback_error_type: str | None = None
        maintenance_schema_applied = False
        journal_prepared_sha: str | None = None
        journal_status: str | None = None
        backup_fully_verified = False
        event_id: str | None = None
        complete_event_persisted = False
        registry_after: str | None = None
        links_after: str | None = None
        active_after: Mapping[str, Any] | None = None
        after_record_counts: Mapping[str, int] | None = None
        commit_decision_attempted = False
        commit_decision_durable = False
        try:
            with self.storage.exclusive_lock():
                locked_plan = self.plan(request)
                locked_internal = dict(locked_plan.pop("_internal"))
                if not self._verified_inputs_match(plan, locked_plan):
                    raise DatasetRecoveryConflictError(
                        "Recovery evidence or immutable artifacts changed after preflight."
                    )
                # Recheck hashes under the same cross-process lock used by all
                # Dataset Library writers.  A stale plan must never overwrite a
                # concurrent registration or ACL edit.
                current_registry_hash = self.storage.sha256_file(
                    self.storage.paths.registry_path
                )
                current_links_hash = self.storage.sha256_file(
                    self.storage.paths.project_links_path
                )
                if (
                    current_registry_hash != plan["before"]["registry_sha256"]
                    or current_links_hash != plan["before"]["project_links_sha256"]
                ):
                    concurrent_event = self._maintenance_event_exists(
                        plan["operation_id"]
                    )
                    if (
                        concurrent_event is not None
                        and self._completed_event_matches_current(
                            plan=locked_plan,
                            internal=locked_internal,
                            event=concurrent_event,
                        )
                    ):
                        event_id = self._record_idempotent_apply_attempt(
                            plan=locked_plan,
                            internal=locked_internal,
                            request=request,
                            attempt_id=attempt_id,
                            prior_event=concurrent_event,
                            concurrent_completion_observed=True,
                        )
                        locked_plan["mode"] = "apply"
                        locked_plan["after"]["projected"] = False
                        locked_plan["mutation"].update(
                            {
                                "attempted": False,
                                "applied": False,
                                "idempotent": True,
                            }
                        )
                        locked_plan["audit"] = {
                            "maintenance_event_id": event_id,
                            "status": "complete",
                            "idempotent": True,
                            "prior_maintenance_event_id": concurrent_event[
                                "maintenance_event_id"
                            ],
                        }
                        return locked_plan
                    raise DatasetRecoveryConflictError(
                        "Dataset Library state changed after recovery preflight."
                    )
                internal = locked_internal
                backup = self.storage.create_backup_bundle(
                    reason=request.reason,
                    backup_directory=request.backup_directory,
                    include_paths=(
                        self.storage.paths.registry_path,
                        self.storage.paths.project_links_path,
                    ),
                    defer_retention=True,
                )
                bundle_path = Path(backup["bundlePath"]).resolve()
                persistence_backup = self._backup_persistence_database(bundle_path)
                safety_manifest = {
                    "schema_version": "atlas.dataset-library-recovery-backup.v1",
                    "operation_id": plan["operation_id"],
                    "created_at": _now_iso(),
                    "reason": request.reason,
                    "storage_bundle_manifest": backup.get("manifestPath"),
                    "storage_bundle_manifest_sha256": backup.get(
                        "manifestSha256"
                    ),
                    "persistence_database": persistence_backup,
                    "before": plan["before"],
                }
                safety_manifest_path = bundle_path / "recovery_safety_manifest.json"
                _atomic_write_bytes(
                    safety_manifest_path,
                    _canonical_json(safety_manifest),
                )
                backup_manifest_sha = _sha256_file(safety_manifest_path)
                backup_verification = self._verify_recovery_backup(
                    operation_id=plan["operation_id"],
                    before=plan["before"],
                    bundle_path=bundle_path,
                    storage_manifest_path=Path(backup["manifestPath"]),
                    storage_manifest_sha256=_text(backup["manifestSha256"]),
                    safety_manifest_path=safety_manifest_path,
                    safety_manifest_sha256=backup_manifest_sha,
                    persistence_backup=persistence_backup,
                )
                backup = {
                    **backup,
                    "safetyManifestPath": str(safety_manifest_path),
                    "safetyManifestSha256": backup_manifest_sha,
                    "persistenceDatabase": persistence_backup,
                    "verification": backup_verification,
                }
                backup_fully_verified = True
                previous_journal = self.storage.read_recovery_journal()
                previous_journal_sha = (
                    self.storage.sha256_file(
                        self.storage.paths.recovery_journal_path
                    )
                    if previous_journal is not None
                    else None
                )
                prepared_journal = {
                    "kind": "atlas_dataset_library_recovery_journal",
                    "formatVersion": 1,
                    "status": "prepared",
                    "operationId": plan["operation_id"],
                    "attemptId": attempt_id,
                    "createdAt": _now_iso(),
                    "actorUserId": request.actor_user_id,
                    "reason": request.reason,
                    "projectId": request.project_id,
                    "datasetId": request.dataset_id,
                    "datasetVersionId": request.dataset_version_id,
                    "backupManifestSha256": backup_manifest_sha,
                    "backupProof": {
                        "bundlePath": str(bundle_path),
                        "storageManifestPath": str(backup["manifestPath"]),
                        "storageManifestSha256": _text(
                            backup["manifestSha256"]
                        ).casefold(),
                        "safetyManifestPath": str(safety_manifest_path),
                        "safetyManifestSha256": backup_manifest_sha,
                        "persistenceDatabase": persistence_backup,
                        "before": plan["before"],
                    },
                    "before": {
                        "registrySha256": current_registry_hash,
                        "projectLinksSha256": current_links_hash,
                        "activeSelectionSha256": self._state_sha256(
                            plan["active_selection"]["before"]
                        ),
                        "durableProjectLinkSha256": self._state_sha256(
                            internal.get("durable_link_before")
                        ),
                    },
                }
                journal_result = self._write_recovery_journal_reconciled(
                    prepared_journal,
                    expected_sha256=previous_journal_sha,
                )
                journal_prepared_sha = _text(journal_result.get("afterSha256"))
                journal_status = "prepared"
                maintenance_schema_applied = self._ensure_maintenance_schema()
                started_event_id = self._write_maintenance_event_reconciled(
                    plan=plan,
                    request=request,
                    status="started",
                    attempt_id=attempt_id,
                    backup_manifest_sha256=backup_manifest_sha,
                    registry_after_sha256=None,
                    metadata={
                        "backupCreated": True,
                        "backupVerified": True,
                        "maintenanceSchemaApplied": maintenance_schema_applied,
                        "activeSelectionChanged": False,
                    },
                )
                if registry_changed:
                    registry_write_attempted = True
                    write_result = self.storage.atomic_write_json(
                        self.storage.paths.registry_path,
                        internal["planned_registry"],
                        expected_sha256=current_registry_hash,
                        shape_validator=lambda value: isinstance(value, dict)
                        and isinstance(value.get("datasets"), list),
                    )
                    if _text(write_result.get("afterSha256")) != registry_write_sha:
                        raise DatasetRecoveryApplyError(
                            "The recovered registry hash did not match its planned payload."
                        )
                    registry_written = bool(write_result.get("changed"))
                if links_changed:
                    links_write_attempted = True
                    write_result = self.storage.atomic_write_json(
                        self.storage.paths.project_links_path,
                        internal["planned_links"],
                        expected_sha256=current_links_hash,
                        shape_validator=lambda value: isinstance(value, dict)
                        and isinstance(value.get("links"), list),
                    )
                    if _text(write_result.get("afterSha256")) != links_write_sha:
                        raise DatasetRecoveryApplyError(
                            "The recovered project-links hash did not match its planned payload."
                        )
                    links_written = bool(write_result.get("changed"))

                if durable_link_change and project_link:
                    from ..persistence.db import Database
                    from ..persistence.repositories.project_dataset_activation_repository import (
                        ProjectDatasetActivationRepository,
                    )

                    repository = ProjectDatasetActivationRepository(
                        Database(self.persistence_database)
                    )
                    # Mark the attempt before entering repository code. A
                    # connection-close or wrapper failure can occur after the
                    # repository transaction commits but before it returns.
                    # The exception path must therefore reconcile the exact
                    # operation-owned row instead of trusting a return flag.
                    durable_link_write_attempted = True
                    result = repository.authorize_link(
                        project_id=request.project_id or "",
                        dataset_id=request.dataset_id,
                        actor_user_id=request.actor_user_id,
                        metadata={
                            "source": "dataset_library_forensic_recovery",
                            "datasetRole": project_link.get("datasetRole") or "modeling",
                            "requestedDatasetVersionId": request.dataset_version_id,
                            "recoveryOperationId": plan["operation_id"],
                            "evidenceReportSha256": plan["evidence"]["report_sha256"],
                            "reason": request.reason,
                        },
                    )
                    durable_link_changed = bool(result.get("changed"))
                    if not durable_link_changed:
                        raise DatasetRecoveryApplyError(
                            "The durable project link was not created as planned."
                        )

                active_after = self._active_selection(request.project_id)
                if active_after != plan["active_selection"]["before"]:
                    raise DatasetRecoveryApplyError(
                        "Recovery changed the active modeling selection, which is forbidden."
                    )
                registry_after = self.storage.sha256_file(
                    self.storage.paths.registry_path
                )
                links_after = self.storage.sha256_file(
                    self.storage.paths.project_links_path
                )
                durable_after = self._durable_project_link(
                    request.project_id,
                    request.dataset_id,
                )
                durable_present = bool(
                    isinstance(durable_after, Mapping)
                    and _text(durable_after.get("link_status")).casefold() == "active"
                )
                if project_link and not durable_present:
                    raise DatasetRecoveryApplyError(
                        "The proven durable project link did not persist."
                    )
                post_plan = self.plan(request, allow_pending_recovery=True)
                post_plan.pop("_internal", None)
                if (
                    not self._verified_inputs_match(plan, post_plan)
                    or post_plan["reconciliation"]["state"] != "healthy"
                    or not post_plan["mutation"]["idempotent"]
                    or post_plan["active_selection"]["before"]
                    != plan["active_selection"]["before"]
                ):
                    raise DatasetRecoveryApplyError(
                        "Recovery post-write verification did not reproduce the exact plan."
                    )
                after_record_counts = post_plan["before"]["record_counts"]
                # Reserve the terminal event id before publishing the durable
                # commit decision. The intermediate journal remains blocking
                # until that exact terminal row is durable.
                event_id = f"dataset-maintenance-{uuid.uuid4().hex}"
                commit_pending_journal = {
                    **prepared_journal,
                    "status": "commit_pending",
                    "commitPendingAt": _now_iso(),
                    "plannedMaintenanceEventId": event_id,
                    "durableLinkChanged": durable_link_changed,
                    "after": {
                        "registrySha256": registry_after,
                        "projectLinksSha256": links_after,
                        "activeSelectionSha256": self._state_sha256(active_after),
                        "durableProjectLinkSha256": self._state_sha256(
                            durable_after
                        ),
                    },
                }
                commit_decision_attempted = True
                journal_result = self._write_recovery_journal_reconciled(
                    commit_pending_journal,
                    expected_sha256=journal_prepared_sha,
                )
                # A durable commit_pending state is the commit decision. It
                # continues to block all normal reads until the referenced
                # terminal audit row exists and the final committed state is
                # durably published.
                journal_status = "commit_pending"
                commit_decision_durable = True
                journal_prepared_sha = _text(journal_result.get("afterSha256"))
                committed_journal = {
                    **commit_pending_journal,
                    "status": "committed",
                    "committedAt": _now_iso(),
                    "maintenanceEventId": event_id,
                }
                self._write_maintenance_event_reconciled(
                    plan=plan,
                    request=request,
                    status="complete",
                    attempt_id=attempt_id,
                    backup_manifest_sha256=backup_manifest_sha,
                    registry_after_sha256=registry_after,
                    metadata={
                        "registryChanged": registry_written,
                        "legacyLinksChanged": links_written,
                        "durableLinkChanged": durable_link_changed,
                        "durableLinkPresent": durable_present,
                        "backupVerified": True,
                        "maintenanceSchemaApplied": maintenance_schema_applied,
                        "projectLinksAfterSha256": links_after,
                        "activeSelectionSha256": self._state_sha256(active_after),
                        "activeSelectionChanged": False,
                        "recoveryJournalStatus": "commit_pending",
                        "terminalJournalTarget": "committed",
                        "terminalJournalCommittedAt": committed_journal[
                            "committedAt"
                        ],
                        "terminalJournalPayloadSha256": self._state_sha256(
                            committed_journal
                        ),
                        "startedMaintenanceEventId": started_event_id,
                    },
                    event_id=event_id,
                )
                complete_event_persisted = True
                journal_result = self._write_recovery_journal_reconciled(
                    committed_journal,
                    expected_sha256=journal_prepared_sha,
                )
                journal_status = "committed"
                journal_prepared_sha = _text(journal_result.get("afterSha256"))
                try:
                    self.storage.prune_backup_bundles(retention_limit=20)
                    backup["retentionPruned"] = True
                except Exception as prune_exc:
                    backup["retentionPruned"] = False
                    backup["retentionPruneErrorType"] = type(prune_exc).__name__
            return self._build_applied_report(
                plan=plan,
                backup=backup,
                registry_after_sha256=registry_after or "",
                project_links_after_sha256=links_after or "",
                active_selection_after=active_after,
                record_counts_after=after_record_counts or {},
                maintenance_event_id=event_id or "",
                attempt_id=attempt_id,
            )
        except Exception as exc:
            if commit_decision_attempted:
                try:
                    live_journal = self.storage.read_recovery_journal(required=True)
                    if (
                        _text(live_journal.get("operationId"))
                        == _text(plan["operation_id"])
                        and _text(live_journal.get("attemptId")) == attempt_id
                    ):
                        live_status = _text(live_journal.get("status")).casefold()
                        if live_status in {
                            "prepared",
                            "commit_pending",
                            "committed",
                        }:
                            journal_status = live_status
                            commit_decision_durable = live_status in {
                                "commit_pending",
                                "committed",
                            }
                        else:
                            commit_decision_durable = True
                            journal_status = "indeterminate_commit_transition"
                    else:
                        commit_decision_durable = True
                        journal_status = "indeterminate_commit_transition"
                except Exception:
                    # An attempted atomic terminal transition has an ambiguous
                    # outcome. Never compensate until a readable journal proves
                    # that the commit decision remained prepared.
                    commit_decision_durable = True
                    journal_status = "indeterminate_commit_transition"
            if commit_decision_durable or journal_status in {
                "commit_pending",
                "committed",
                "indeterminate_commit_transition",
            }:
                # Authority and journal are already durable. A later audit or
                # result-building failure is an operational error, never a
                # reason to compensate a committed recovery.
                plan["mode"] = "apply"
                plan["backup"] = backup
                plan["after"] = {
                    "registry_sha256": registry_after,
                    "project_links_sha256": links_after,
                    "active_selection": active_after,
                    "record_counts": dict(after_record_counts or {}),
                    "projected": False,
                }
                plan["active_selection"]["after"] = active_after
                plan["mutation"].update(
                    {
                        "attempted": True,
                        "applied": True,
                        "idempotent": False,
                        "rolled_back": False,
                        "rollback_complete": None,
                    }
                )
                plan["audit"] = {
                    "maintenance_event_id": event_id,
                    "status": (
                        "complete"
                        if complete_event_persisted
                        else "pending_after_commit"
                    ),
                }
                plan["journal"] = {
                    "status": journal_status,
                    "attempt_id": attempt_id,
                }
                plan["errors"] = [
                    {
                        "error_type": type(exc).__name__,
                        "phase": "post_commit",
                    }
                ]
                wrapped = DatasetRecoveryApplyError(
                    "Dataset recovery reached its commit boundary, but terminal "
                    "finalization failed "
                    f"closed: {type(exc).__name__}."
                )
                wrapped.recovery_report = sanitized_report(plan)
                raise wrapped from exc
            # If an atomic file replacement succeeded but a later stage failed,
            # restore only the exact preflight payloads and only when the file
            # still carries this operation's expected post-write checksum.
            rollback_errors: list[str] = []
            if registry_write_attempted:
                try:
                    with self.storage.exclusive_lock():
                        registry_live_sha = self.storage.sha256_file(
                            self.storage.paths.registry_path
                        )
                        if registry_live_sha == registry_write_sha:
                            self.storage.atomic_restore_json_bytes(
                                self.storage.paths.registry_path,
                                internal["registry_before_bytes"],
                                expected_sha256=registry_write_sha,
                            )
                        elif registry_live_sha != plan["before"]["registry_sha256"]:
                            raise DatasetRecoveryConflictError(
                                "The registry changed before recovery rollback."
                            )
                except Exception as rollback_exc:
                    rollback_errors.append(type(rollback_exc).__name__)
            if links_write_attempted:
                try:
                    with self.storage.exclusive_lock():
                        links_live_sha = self.storage.sha256_file(
                            self.storage.paths.project_links_path
                        )
                        if links_live_sha == links_write_sha:
                            self.storage.atomic_restore_json_bytes(
                                self.storage.paths.project_links_path,
                                internal["links_before_bytes"],
                                expected_sha256=links_write_sha,
                            )
                        elif links_live_sha != plan["before"]["project_links_sha256"]:
                            raise DatasetRecoveryConflictError(
                                "The project-links store changed before recovery rollback."
                            )
                except Exception as rollback_exc:
                    rollback_errors.append(type(rollback_exc).__name__)
            if durable_link_write_attempted:
                try:
                    durable_link_compensated = self._remove_recovery_durable_link(
                        project_id=request.project_id or "",
                        dataset_id=request.dataset_id,
                        operation_id=plan["operation_id"],
                        dataset_version_id=request.dataset_version_id,
                        actor_user_id=request.actor_user_id,
                        reason=request.reason,
                        active_selection_before=plan["active_selection"]["before"],
                    )
                    durable_link_changed = (
                        durable_link_changed or durable_link_compensated
                    )
                except Exception as rollback_exc:
                    rollback_errors.append(type(rollback_exc).__name__)
            if rollback_errors:
                # Preserve the original exception and report that manual
                # reconciliation is required; never guess through rollback.
                rollback_complete = False
                rollback_error_type = ",".join(rollback_errors)
            # Authority rollback is distinct from publication of its terminal
            # audit proof. If failed-event persistence later fails, the stores
            # can still be exactly restored while the prepared journal remains
            # blocking until an operator reconciles that missing proof.
            authority_rollback_complete = rollback_complete
            failed_event_id = None
            failure_metadata = {
                "errorType": type(exc).__name__,
                "rolledBack": bool(
                    authority_rollback_complete
                    and (
                        registry_write_attempted
                        or links_write_attempted
                        or durable_link_write_attempted
                    )
                ),
                "rollbackComplete": rollback_complete,
                "rollbackErrorType": rollback_error_type,
                "activeSelectionChanged": False,
            }
            if journal_status == "prepared" and rollback_complete:
                try:
                    live_journal = self.storage.read_recovery_journal(required=True)
                    if (
                        _text(live_journal.get("operationId"))
                        != _text(plan["operation_id"])
                        or _text(live_journal.get("attemptId")) != attempt_id
                        or _text(live_journal.get("status")).casefold()
                        != "prepared"
                    ):
                        raise DatasetRecoveryConflictError(
                            "The recovery journal changed before compensation completed."
                        )
                    live_journal_sha = self.storage.sha256_file(
                        self.storage.paths.recovery_journal_path
                    )
                    failed_event_id = f"dataset-maintenance-{uuid.uuid4().hex}"
                    aborted_journal = {
                        **live_journal,
                        "status": "aborted",
                        "abortedAt": _now_iso(),
                        "failedMaintenanceEventId": failed_event_id,
                        "failureType": type(exc).__name__,
                    }
                    failed_event_id = self._write_maintenance_event_reconciled(
                        plan=plan,
                        request=request,
                        status="failed",
                        attempt_id=attempt_id,
                        backup_manifest_sha256=backup_manifest_sha,
                        registry_after_sha256=self.storage.sha256_file(
                            self.storage.paths.registry_path
                        ),
                        metadata={
                            **failure_metadata,
                            "terminalJournalPayloadSha256": self._state_sha256(
                                aborted_journal
                            ),
                        },
                        event_id=failed_event_id,
                    )
                    self._write_recovery_journal_reconciled(
                        aborted_journal,
                        expected_sha256=live_journal_sha,
                    )
                    journal_status = "aborted"
                except Exception as journal_exc:
                    rollback_complete = False
                    rollback_errors.append(type(journal_exc).__name__)
                    rollback_error_type = ",".join(rollback_errors)
            else:
                try:
                    failed_event_id = self._write_maintenance_event_reconciled(
                        plan=plan,
                        request=request,
                        status="failed",
                        attempt_id=attempt_id,
                        backup_manifest_sha256=backup_manifest_sha,
                        registry_after_sha256=self.storage.sha256_file(
                            self.storage.paths.registry_path
                        ),
                        metadata=failure_metadata,
                    )
                except Exception:
                    pass
            if backup is not None and not backup_fully_verified:
                try:
                    bundle_value = backup.get("bundlePath")
                    if bundle_value:
                        self.storage.discard_incomplete_backup_bundle(bundle_value)
                    backup = {
                        "status": "discarded_incomplete",
                        "verification": {"status": "failed"},
                    }
                except Exception as discard_exc:
                    rollback_complete = False
                    rollback_errors.append(type(discard_exc).__name__)
                    rollback_error_type = ",".join(rollback_errors)
            plan["mode"] = "apply"
            plan["backup"] = backup
            plan["mutation"].update(
                {
                    "attempted": True,
                    "applied": False,
                    "idempotent": False,
                    "rolled_back": bool(
                        authority_rollback_complete
                        and (
                            registry_write_attempted
                            or links_write_attempted
                            or durable_link_write_attempted
                        )
                    ),
                    "rollback_complete": rollback_complete,
                    "rollback_error_type": rollback_error_type,
                }
            )
            plan["audit"] = {
                "maintenance_event_id": failed_event_id,
                "status": "failed" if failed_event_id else "unavailable",
            }
            plan["journal"] = {
                "status": journal_status or "not_created",
                "attempt_id": attempt_id,
            }
            plan["errors"] = [{"error_type": type(exc).__name__}]
            try:
                after_registry_document = self.storage.read_registry(
                    allow_pending_recovery=True
                )
                after_links_document = self.storage.read_links(
                    allow_pending_recovery=True
                )
                plan["after"] = {
                    "registry_sha256": self.storage.sha256_file(
                        self.storage.paths.registry_path
                    ),
                    "project_links_sha256": self.storage.sha256_file(
                        self.storage.paths.project_links_path
                    ),
                    "active_selection": self._active_selection(request.project_id),
                    "record_counts": self._authority_record_counts(
                        after_registry_document,
                        after_links_document,
                    ),
                    "projected": False,
                }
            except Exception:
                plan["after"] = {"verification": "unavailable"}
            if isinstance(exc, DatasetRecoveryError):
                exc.recovery_report = sanitized_report(plan)
                raise
            wrapped = DatasetRecoveryApplyError(
                f"Dataset recovery failed closed: {type(exc).__name__}."
            )
            wrapped.recovery_report = sanitized_report(plan)
            raise wrapped from exc


def sanitized_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Remove internal payloads and absolute artifact paths for JSON output."""

    output = json.loads(json.dumps(report, default=str))
    output.pop("_internal", None)
    artifact = output.get("artifact_verification")
    if isinstance(artifact, dict) and artifact.get("artifact_path"):
        artifact["artifact_path"] = Path(artifact["artifact_path"]).name
    backup = output.get("backup")
    if isinstance(backup, dict):
        for key in ("bundlePath", "manifestPath", "safetyManifestPath"):
            if backup.get(key):
                backup[key] = Path(str(backup[key])).name
    return output
