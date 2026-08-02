"""Durable file primitives for the ATLAS Dataset Library.

The legacy Dataset Library catalog is a JSON document accompanied by immutable
version artifacts.  This module deliberately contains no catalog business
logic.  It provides the small set of strict, crash-resistant primitives needed
by normal writers, recovery tooling, and the startup integrity scanner:

* strict reads that never create a store or turn corruption into an empty list;
* a process/thread compatible write lock;
* external, checksummed backup bundles; and
* unique-temp + fsync + atomic-replace JSON writes.

Nothing in this module mutates storage during import or during a read.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional


class DatasetStorageError(RuntimeError):
    """Base error for Dataset Library storage failures."""


class DatasetStoreMissingError(DatasetStorageError):
    """Raised when a required Dataset Library record does not exist."""


class DatasetStoreMalformedError(DatasetStorageError):
    """Raised when a Dataset Library document cannot be parsed or validated."""


class DatasetStoreConflictError(DatasetStorageError):
    """Raised when an optimistic write observes a different current document."""


class UnsafeTestStorageError(DatasetStorageError):
    """Raised when a test process attempts to write the configured live root."""


class DatasetRecoveryPendingError(DatasetStorageError):
    """Raised while a prepared recovery transaction requires resolution."""


_MODULE_PATH = Path(__file__).resolve()
_REPOSITORY_ROOT = _MODULE_PATH.parents[2]
_DEFAULT_LIBRARY_ROOT = _MODULE_PATH.parents[1] / "artifacts" / "datasets"
_DEFAULT_PERSISTENCE_DATABASE = _MODULE_PATH.parents[1] / "data" / "atlas_local.db"
_DEFAULT_BACKUP_ROOT = Path(
    os.getenv("LOCALAPPDATA")
    or os.getenv("XDG_STATE_HOME")
    or tempfile.gettempdir()
) / "ATLAS" / "dataset-library-backups"
_BACKUP_PREFIX = "atlas-dataset-library-"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return a streaming SHA-256 digest without changing the file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DatasetStoreMalformedError(
            f"Dataset Library payload is not valid JSON data: {exc}"
        ) from exc
    return (rendered + "\n").encode("utf-8")


def _validate_root_shape(payload: Any, expected_root_key: str | None) -> None:
    if not isinstance(payload, dict):
        raise DatasetStoreMalformedError(
            "Dataset Library JSON must contain a top-level object."
        )
    if expected_root_key is None:
        return
    if expected_root_key not in payload:
        raise DatasetStoreMalformedError(
            f"Dataset Library JSON is missing the '{expected_root_key}' collection."
        )
    if not isinstance(payload.get(expected_root_key), list):
        raise DatasetStoreMalformedError(
            f"Dataset Library '{expected_root_key}' must be a list."
        )


def read_json_strict(
    path: str | Path,
    expected_root_key: str | None = None,
    allow_missing: bool = False,
    *,
    max_bytes: int | None = None,
) -> Any:
    """Read one JSON document without creating or defaulting it.

    ``allow_missing`` returns ``None`` only for a genuinely absent path.  A
    permission error, short read, malformed document, or wrong root shape is
    always surfaced as an error.
    """

    resolved = Path(path)
    if _is_link_or_junction(resolved):
        raise DatasetStoreMalformedError(
            f"Dataset Library document cannot be a filesystem link: {resolved.name}"
        )
    if not resolved.exists():
        if allow_missing:
            return None
        raise DatasetStoreMissingError(
            f"Required Dataset Library document is missing: {resolved.name}"
        )
    if not resolved.is_file():
        raise DatasetStoreMalformedError(
            f"Dataset Library document is not a regular file: {resolved.name}"
        )
    try:
        if max_bytes is None:
            raw = resolved.read_bytes()
        else:
            byte_limit = max(0, int(max_bytes))
            with resolved.open("rb") as handle:
                raw = handle.read(byte_limit + 1)
            if len(raw) > byte_limit:
                raise DatasetStoreMalformedError(
                    f"Dataset Library document exceeds its read limit: {resolved.name}"
                )
        text = raw.decode("utf-8")
    except DatasetStoreMalformedError:
        raise
    except UnicodeDecodeError as exc:
        raise DatasetStoreMalformedError(
            f"Dataset Library document is not UTF-8 JSON: {resolved.name}"
        ) from exc
    except OSError as exc:
        raise DatasetStorageError(
            "Dataset Library document could not be read: "
            f"{resolved.name} ({type(exc).__name__})"
        ) from exc
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DatasetStoreMalformedError(
            f"Dataset Library document is malformed: {resolved.name}: {exc}"
        ) from exc
    _validate_root_shape(payload, expected_root_key)
    return payload


def _is_journal_text(payload: Mapping[str, Any], field: str) -> bool:
    return bool(str(payload.get(field) or "").strip())


def _is_journal_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().casefold()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _journal_hash_block(payload: Any, fields: tuple[str, ...]) -> bool:
    return bool(
        isinstance(payload, Mapping)
        and all(_is_journal_sha256(payload.get(field)) for field in fields)
    )


def _validate_recovery_journal(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("kind") != "atlas_dataset_library_recovery_journal":
        return False
    if payload.get("formatVersion") != 1:
        return False
    if str(payload.get("status") or "").casefold() not in {
        "prepared",
        "commit_pending",
        "committed",
        "aborted",
    }:
        return False
    required = ("operationId", "createdAt", "actorUserId", "reason")
    if not all(_is_journal_text(payload, field) for field in required):
        return False

    status = str(payload.get("status") or "").casefold()
    before_fields = ("registrySha256", "projectLinksSha256")

    # Normal Dataset Library link-projection transactions share this journal
    # primitive with offline forensic recovery.  Their operationType and
    # expectedAfter fields distinguish the projection schema from recovery's
    # attempt/audit schema.
    if _is_journal_text(payload, "operationType"):
        if status == "commit_pending":
            return False
        if not all(
            _is_journal_text(payload, field)
            for field in (
                "projectId",
                "datasetId",
                "backupBundleName",
                "backupManifestSha256",
            )
        ):
            return False
        if not _is_journal_sha256(payload.get("backupManifestSha256")):
            return False
        if not _journal_hash_block(payload.get("before"), before_fields):
            return False
        if not _journal_hash_block(payload.get("expectedAfter"), before_fields):
            return False
        if status == "prepared":
            return True
        if not _is_journal_text(payload, "resolvedAt"):
            return False
        return status == "committed" or (
            status == "aborted" and _is_journal_text(payload, "failureType")
        )

    if not all(
        _is_journal_text(payload, field)
        for field in (
            "attemptId",
            "datasetId",
            "datasetVersionId",
            "backupManifestSha256",
        )
    ):
        return False
    if not _is_journal_sha256(payload.get("backupManifestSha256")):
        return False
    if not _journal_hash_block(
        payload.get("before"),
        (*before_fields, "activeSelectionSha256"),
    ):
        return False
    if status == "prepared":
        return True
    if status == "commit_pending":
        return bool(
            _is_journal_text(payload, "commitPendingAt")
            and _is_journal_text(payload, "plannedMaintenanceEventId")
            and _journal_hash_block(
                payload.get("after"),
                (*before_fields, "activeSelectionSha256"),
            )
        )
    if status == "committed":
        return bool(
            _is_journal_text(payload, "committedAt")
            and _is_journal_text(payload, "maintenanceEventId")
            and _journal_hash_block(
                payload.get("after"),
                (*before_fields, "activeSelectionSha256"),
            )
        )
    return bool(
        status == "aborted"
        and _is_journal_text(payload, "abortedAt")
        and _is_journal_text(payload, "failureType")
        and _is_journal_text(payload, "failedMaintenanceEventId")
    )


def _terminal_recovery_journal_is_proven(
    payload: Mapping[str, Any],
    *,
    library_root: Path,
) -> bool:
    """Bind a terminal journal to exact catalog state and durable audit proof."""

    # Normal two-document projection transactions have no maintenance-event
    # row. Their existing terminal schema remains their crash marker; later
    # independent catalog transactions are allowed to advance authority hashes.
    if _is_journal_text(payload, "operationType"):
        return True

    status = str(payload.get("status") or "").casefold()
    event_id_field = (
        "maintenanceEventId"
        if status == "committed"
        else "failedMaintenanceEventId"
    )
    event_id = str(payload.get(event_id_field) or "").strip()
    database = Path(
        os.getenv("ATLAS_SQLITE_PATH") or _DEFAULT_PERSISTENCE_DATABASE
    ).expanduser().resolve()
    if not event_id or not database.is_file():
        return False
    uri = f"file:{database.as_posix()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT * FROM dataset_library_maintenance_events
                WHERE maintenance_event_id = ?
                """,
                (event_id,),
            ).fetchone()
    except sqlite3.Error:
        return False
    if row is None:
        return False
    event = dict(row)
    before = payload.get("before") or {}
    terminal_hashes = payload.get("after") if status == "committed" else before
    if not isinstance(before, Mapping) or not isinstance(terminal_hashes, Mapping):
        return False
    try:
        metadata = json.loads(str(event.get("metadata_json") or "{}"))
    except (TypeError, ValueError):
        return False
    optional_project = payload.get("projectId")
    expected_project = (
        str(optional_project).strip()
        if optional_project not in (None, "")
        else None
    )
    expected_status = "complete" if status == "committed" else "failed"
    terminal_journal_sha256 = sha256_bytes(
        json.dumps(
            dict(payload),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    common_matches = bool(
        event.get("maintenance_event_id") == event_id
        and event.get("attempt_id") == payload.get("attemptId")
        and event.get("operation_id") == payload.get("operationId")
        and event.get("operation_type") == "recover"
        and event.get("event_status") == expected_status
        and event.get("actor_user_id") == payload.get("actorUserId")
        and event.get("project_id") == expected_project
        and event.get("dataset_id") == payload.get("datasetId")
        and event.get("dataset_version_id") == payload.get("datasetVersionId")
        and event.get("reason") == payload.get("reason")
        and _is_journal_sha256(event.get("evidence_report_sha256"))
        and event.get("backup_manifest_sha256")
        == payload.get("backupManifestSha256")
        and event.get("registry_before_sha256")
        == before.get("registrySha256")
        and event.get("registry_after_sha256")
        == terminal_hashes.get("registrySha256")
        and bool(str(event.get("created_at") or "").strip())
        and metadata.get("activeSelectionChanged") is False
        and metadata.get("terminalJournalPayloadSha256")
        == terminal_journal_sha256
    )
    if not common_matches:
        return False
    if status == "committed":
        return bool(
            metadata.get("projectLinksAfterSha256")
            == terminal_hashes.get("projectLinksSha256")
            and metadata.get("activeSelectionSha256")
            == terminal_hashes.get("activeSelectionSha256")
            and metadata.get("recoveryJournalStatus") == "commit_pending"
            and metadata.get("terminalJournalTarget") == "committed"
        )
    return bool(
        metadata.get("errorType") == payload.get("failureType")
        and metadata.get("rollbackComplete") is True
    )


def assert_no_pending_recovery(
    root: str | Path,
    *,
    max_bytes: int = 1024 * 1024,
) -> None:
    """Fail closed while a prepared recovery journal exists."""

    # Keep the configured path lexical until every existing component has been
    # inspected.  Dataset Registry reads call this guard before opening any of
    # their authorities; resolving first would allow a configured symlink or
    # Windows junction to redirect those reads while hiding the alias itself.
    lexical_root = _assert_no_linked_path_component(
        root,
        label="Dataset Library root",
    )
    journal_path = lexical_root / ".dataset-library-recovery-journal.json"
    payload = read_json_strict(
        journal_path,
        allow_missing=True,
        max_bytes=max_bytes,
    )
    if payload is None:
        return
    if not _validate_recovery_journal(payload):
        raise DatasetStoreMalformedError(
            "Dataset Library recovery journal is malformed."
        )
    status = str(payload.get("status") or "").casefold()
    if status not in {"committed", "aborted"}:
        raise DatasetRecoveryPendingError(
            "Dataset Library recovery has not reached a verified terminal state."
        )
    if not _terminal_recovery_journal_is_proven(
        payload,
        library_root=lexical_root,
    ):
        raise DatasetRecoveryPendingError(
            "Dataset Library recovery terminal state lacks exact durable proof."
        )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


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


def _assert_no_linked_path_component(path: str | Path, *, label: str) -> Path:
    """Return a lexical absolute path only when no existing component is linked.

    Calling ``resolve`` first would erase the evidence that a configured root
    was a symlink or Windows junction.  Walk the lexical path from its anchor
    before resolution so authorities and backup roots cannot be redirected.
    """

    lexical = Path(os.path.abspath(str(Path(path).expanduser())))
    parts = lexical.parts
    if not parts:
        raise DatasetStorageError(f"{label} is invalid.")
    current = Path(parts[0])
    if _is_link_or_junction(current):
        raise DatasetStorageError(f"{label} cannot traverse filesystem links.")
    for part in parts[1:]:
        current = current / part
        if _is_link_or_junction(current):
            raise DatasetStorageError(f"{label} cannot traverse filesystem links.")
    return lexical


def _has_linked_component_within(path: Path, root: Path) -> bool:
    """Detect aliases below root without following them as authority."""

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


def _existing_lexical_components(path: Path, *, label: str) -> list[Path]:
    """Return existing path components without following a configured alias."""

    lexical = Path(os.path.abspath(str(path.expanduser())))
    components: list[Path] = []
    current = Path(lexical.parts[0])
    for part in (None, *lexical.parts[1:]):
        if part is not None:
            current = current / part
        try:
            os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise DatasetStorageError(
                f"{label} physical identity could not be verified."
            ) from exc
        components.append(current)
    return components


def _physical_overlap_with_protected_root(
    path: str | Path,
    protected_root: str | Path,
    *,
    label: str,
) -> bool:
    """Detect exact aliases and same-device bind/mapped-root indirection.

    ``Path.resolve`` cannot expose POSIX bind mounts or every Windows mapped
    share spelling.  Existing component identities are therefore compared
    with the protected root and its ancestors.  A same-device mount reached
    through a different lexical anchor is rejected conservatively because it
    can hide an otherwise unobservable bind/share alias into protected data.
    """

    lexical = Path(os.path.abspath(str(Path(path).expanduser())))
    protected = Path(protected_root).expanduser().resolve()
    protected_ancestors = [protected, *protected.parents]
    components = _existing_lexical_components(lexical, label=label)

    for component in components:
        for ancestor in protected_ancestors:
            try:
                same = os.path.samefile(component, ancestor)
            except FileNotFoundError:
                same = False
            except OSError as exc:
                raise DatasetStorageError(
                    f"{label} physical identity could not be verified."
                ) from exc
            if not same:
                continue
            try:
                remainder = lexical.relative_to(component)
            except ValueError:
                continue
            projected = ancestor.joinpath(remainder)
            if (
                projected == protected
                or _is_relative_to(projected, protected)
                or _is_relative_to(protected, projected)
            ):
                return True

        try:
            is_mount = component.is_mount()
            component_device = component.stat().st_dev if is_mount else None
            protected_device = protected.stat().st_dev
        except OSError as exc:
            raise DatasetStorageError(
                f"{label} mount identity could not be verified."
            ) from exc
        if not is_mount or component_device != protected_device:
            continue
        component_anchor = Path(component.anchor)
        protected_anchor = Path(protected.anchor)
        same_lexical_anchor = os.path.normcase(str(component_anchor)) == os.path.normcase(
            str(protected_anchor)
        )
        if component != component_anchor or not same_lexical_anchor:
            return True
    return False


def _assert_no_protected_physical_overlap(
    path: str | Path,
    *,
    protected_roots: Iterable[str | Path],
    label: str,
) -> None:
    for protected_root in protected_roots:
        if _physical_overlap_with_protected_root(
            path,
            protected_root,
            label=label,
        ):
            raise DatasetStorageError(
                f"{label} physically aliases protected ATLAS storage."
            )


def assert_test_storage_isolated(root: str | Path) -> None:
    """Fail closed when a test points at the checked-in live library root."""

    lexical = _assert_no_linked_path_component(
        root,
        label="Test Dataset Library root",
    )
    try:
        _assert_no_protected_physical_overlap(
            lexical,
            protected_roots=(_DEFAULT_LIBRARY_ROOT,),
            label="Test Dataset Library root",
        )
    except DatasetStorageError as exc:
        raise UnsafeTestStorageError(
            "Test Dataset Library storage physically aliases the checked-in "
            "live root. Use a UUID-specific temporary path."
        ) from exc
    resolved = lexical.resolve()
    live = _DEFAULT_LIBRARY_ROOT.resolve()
    if resolved == live or _is_relative_to(resolved, live):
        raise UnsafeTestStorageError(
            "Test Dataset Library storage resolves to the checked-in live root. "
            "Set ATLAS_DATASET_LIBRARY_ROOT to a UUID-specific temporary path "
            "before importing server modules."
        )


def _test_mode_enabled() -> bool:
    return (
        os.getenv("ATLAS_ENV", "").strip().casefold() in {"test", "testing"}
        or os.getenv("ATLAS_TEST_MODE", "").strip().casefold()
        in {"1", "true", "yes"}
        or bool(os.getenv("PYTEST_CURRENT_TEST"))
    )


@dataclass(frozen=True)
class DatasetLibraryPaths:
    root: Path
    registry_path: Path
    project_links_path: Path
    users_path: Path
    lock_path: Path
    backup_root: Path

    @property
    def recovery_journal_path(self) -> Path:
        return self.root / ".dataset-library-recovery-journal.json"

    @classmethod
    def from_environment(
        cls,
        *,
        backup_root: str | Path | None = None,
    ) -> "DatasetLibraryPaths":
        requested_root = Path(
            os.getenv("ATLAS_DATASET_LIBRARY_ROOT", str(_DEFAULT_LIBRARY_ROOT))
        ).expanduser()
        requested_backup = Path(
            backup_root
            or os.getenv(
                "ATLAS_DATASET_LIBRARY_BACKUP_ROOT",
                str(_DEFAULT_BACKUP_ROOT),
            )
        ).expanduser()
        lexical_root = _assert_no_linked_path_component(
            requested_root,
            label="Dataset Library root",
        )
        root = lexical_root.resolve()
        if root != _DEFAULT_LIBRARY_ROOT.resolve():
            _assert_no_protected_physical_overlap(
                lexical_root,
                protected_roots=(_DEFAULT_LIBRARY_ROOT,),
                label="Configured Dataset Library root",
            )
        configured_backup = _assert_no_linked_path_component(
            requested_backup,
            label="Dataset Library backup root",
        ).resolve()
        return cls(
            root=root,
            registry_path=root / "registry.json",
            project_links_path=root / "project_links.json",
            users_path=root / "users.json",
            lock_path=root / ".dataset-library.lock",
            backup_root=configured_backup,
        )


_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: Dict[str, threading.RLock] = {}
_LOCK_DEPTH = threading.local()


def _thread_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.expanduser().resolve()))
    with _LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


def _acquire_platform_lock(handle: Any, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except (BlockingIOError, OSError):
            if time.monotonic() >= deadline:
                raise DatasetStoreConflictError(
                    "Timed out waiting for the Dataset Library write lock."
                )
            time.sleep(0.05)


def _release_platform_lock(handle: Any) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Closing the handle releases an OS lock even if an explicit unlock is
        # interrupted.  Do not mask an earlier mutation error during cleanup.
        pass


@contextmanager
def library_write_lock(
    root: str | Path,
    timeout_seconds: float = 10.0,
) -> Iterator[None]:
    """Serialize Dataset Library writers across threads and processes.

    The context is re-entrant within one thread.  The lock file contains no
    application data and is not considered a catalog or recovery artifact.
    """

    resolved_root = _assert_no_linked_path_component(
        root,
        label="Dataset Library write root",
    ).resolve()
    if _test_mode_enabled():
        assert_test_storage_isolated(resolved_root)
    resolved_root.mkdir(parents=True, exist_ok=True)
    lock_path = resolved_root / ".dataset-library.lock"
    thread_lock = _thread_lock(lock_path)
    key = os.path.normcase(str(lock_path))
    depths = getattr(_LOCK_DEPTH, "depths", {})
    _LOCK_DEPTH.depths = depths
    with thread_lock:
        depth = int(depths.get(key, 0))
        if depth:
            depths[key] = depth + 1
            try:
                yield
            finally:
                depths[key] -= 1
            return

        handle = lock_path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            _acquire_platform_lock(handle, timeout_seconds)
            depths[key] = 1
            try:
                yield
            finally:
                depths.pop(key, None)
                _release_platform_lock(handle)
        finally:
            handle.close()


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":
        # Windows ReplaceFile/MoveFileEx durability is provided by os.replace;
        # opening directories for fsync is not portable there.
        return
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(str(path.parent), os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / (
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_parent(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _default_shape_key(path: Path) -> str | None:
    if path.name == "registry.json":
        return "datasets"
    if path.name == "project_links.json":
        return "links"
    if path.name == "users.json":
        return "users"
    return None


def _path_within_root(path: Path, root: Path) -> bool:
    resolved = path.expanduser().resolve()
    root = root.expanduser().resolve()
    return resolved == root or _is_relative_to(resolved, root)


def _assert_external_backup_root(
    path: Path,
    *,
    library_root: Path | None = None,
) -> None:
    lexical = _assert_no_linked_path_component(
        path,
        label="Dataset Library backup root",
    )
    protected_roots: list[Path] = [_REPOSITORY_ROOT]
    if library_root is not None:
        protected_roots.append(library_root)
    _assert_no_protected_physical_overlap(
        lexical,
        protected_roots=protected_roots,
        label="Dataset Library backup root",
    )
    resolved = lexical.resolve()
    repository = _REPOSITORY_ROOT.resolve()
    if resolved == repository or _is_relative_to(resolved, repository):
        raise DatasetStorageError(
            "Dataset Library safety backups must be stored outside the repository."
        )
    if library_root is not None:
        source = library_root.expanduser().resolve()
        if (
            resolved == source
            or _is_relative_to(resolved, source)
            or _is_relative_to(source, resolved)
        ):
            raise DatasetStorageError(
                "Dataset Library safety backups must not overlap the live library root."
            )


def _prune_backup_bundles(backup_root: Path, retention: int) -> None:
    keep = max(1, int(retention))
    candidates = []
    for child in backup_root.iterdir():
        if (
            child.is_dir()
            and not _is_link_or_junction(child)
            and child.name.startswith(_BACKUP_PREFIX)
            and (child / "manifest.json").is_file()
            and not _is_link_or_junction(child / "manifest.json")
        ):
            candidates.append(child)
    candidates.sort(key=lambda item: item.name, reverse=True)
    for stale in candidates[keep:]:
        # Both conditions above and the resolved-parent assertion constrain
        # deletion to a manifest-bearing bundle created under this backup root.
        if (
            stale.parent.resolve() == backup_root.resolve()
            and not _is_link_or_junction(stale)
        ):
            shutil.rmtree(stale)


def create_backup_bundle(
    paths: Iterable[str | Path],
    *,
    library_root: str | Path,
    backup_root: str | Path | None = None,
    reason: str,
    retention: int = 20,
    defer_retention: bool = False,
) -> Dict[str, Any]:
    """Copy selected Dataset Library documents into a checksummed bundle.

    This helper does not acquire the library lock so callers can compose one
    consistent backup with a subsequent atomic write under
    :func:`library_write_lock`.
    """

    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise DatasetStorageError("A backup reason is required.")
    source_root = _assert_no_linked_path_component(
        library_root,
        label="Dataset Library source root",
    ).resolve()
    requested_destination_root = Path(
        backup_root
        or os.getenv("ATLAS_DATASET_LIBRARY_BACKUP_ROOT")
        or _DEFAULT_BACKUP_ROOT
    ).expanduser()
    destination_root = _assert_no_linked_path_component(
        requested_destination_root,
        label="Dataset Library backup root",
    ).resolve()
    _assert_external_backup_root(destination_root, library_root=source_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    bundle = destination_root / (
        f"{_BACKUP_PREFIX}{_utc_stamp()}-{uuid.uuid4().hex}"
    )
    snapshots = bundle / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=False)
    records = []
    try:
        for source_value in paths:
            requested_source = Path(source_value).expanduser()
            if _has_linked_component_within(requested_source, source_root):
                raise DatasetStorageError(
                    "Dataset Library backup sources cannot traverse filesystem links."
                )
            source = requested_source.resolve()
            if not _path_within_root(source, source_root):
                raise DatasetStorageError(
                    "A requested backup source is outside the Dataset Library root."
                )
            if not source.exists():
                records.append(
                    {
                        "sourceRelativePath": str(source.relative_to(source_root)),
                        "exists": False,
                    }
                )
                continue
            if not source.is_file():
                raise DatasetStorageError(
                    "Dataset Library backup sources must be regular files."
                )
            relative = source.relative_to(source_root)
            target = snapshots / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = source.read_bytes()
            _atomic_write_bytes(target, payload)
            records.append(
                {
                    "sourceRelativePath": str(relative),
                    "backupRelativePath": str(target.relative_to(bundle)),
                    "exists": True,
                    "sizeBytes": len(payload),
                    "sha256": sha256_bytes(payload),
                }
            )
        manifest = {
            "formatVersion": 1,
            "kind": "atlas_dataset_library_backup",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "reason": normalized_reason,
            "files": records,
        }
        manifest_path = bundle / "manifest.json"
        _atomic_write_bytes(manifest_path, _canonical_json_bytes(manifest))
        manifest_hash = sha256_file(manifest_path)
        if not defer_retention:
            _prune_backup_bundles(destination_root, retention)
        return {
            **manifest,
            "bundlePath": str(bundle),
            "manifestPath": str(manifest_path),
            "manifestSha256": manifest_hash,
            "retentionPruned": not defer_retention,
        }
    except Exception:
        if bundle.exists() and bundle.parent.resolve() == destination_root:
            shutil.rmtree(bundle, ignore_errors=True)
        raise


def atomic_write_json(
    path: str | Path,
    payload: Any,
    *,
    backup_root: str | Path | None = None,
    retention: int | None = None,
    create_backup: bool = True,
    expected_sha256: str | None = None,
) -> Dict[str, Any]:
    """Safely replace one Dataset Library JSON document.

    This convenience API infers the library root from the document parent,
    acquires the cross-process lock, backs up the previous document, validates
    the known top-level shape, and atomically replaces it.  Multi-document
    maintenance operations should instead use :class:`DatasetLibraryStorage`
    under one explicit ``exclusive_lock``.
    """

    requested_destination = Path(path).expanduser()
    destination = _assert_no_linked_path_component(
        requested_destination,
        label="Dataset Library authority document",
    ).resolve()
    root = destination.parent
    if _test_mode_enabled():
        assert_test_storage_isolated(root)
    expected_key = _default_shape_key(destination)
    _validate_root_shape(payload, expected_key)
    with library_write_lock(root):
        before_hash = sha256_file(destination) if destination.exists() else None
        if expected_sha256 is not None and before_hash != expected_sha256:
            raise DatasetStoreConflictError(
                "Dataset Library document changed before the write completed."
            )
        rendered = _canonical_json_bytes(payload)
        after_hash = sha256_bytes(rendered)
        if before_hash == after_hash:
            return {
                "changed": False,
                "path": str(destination),
                "beforeSha256": before_hash,
                "afterSha256": after_hash,
                "backup": None,
            }
        backup = None
        if create_backup:
            backup = create_backup_bundle(
                [destination],
                library_root=root,
                backup_root=backup_root,
                reason=f"Before replacing {destination.name}",
                retention=retention or 20,
            )
        _atomic_write_bytes(destination, rendered)
        verified = read_json_strict(destination, expected_key)
        _validate_root_shape(verified, expected_key)
        return {
            "changed": True,
            "path": str(destination),
            "beforeSha256": before_hash,
            "afterSha256": sha256_file(destination),
            "backup": backup,
        }


class DatasetLibraryStorage:
    """Strict Dataset Library storage facade used by scanners and writers."""

    def __init__(self, paths: DatasetLibraryPaths | None = None) -> None:
        self.paths = paths or DatasetLibraryPaths.from_environment()

    def read_registry(
        self,
        *,
        max_bytes: int | None = None,
        allow_pending_recovery: bool = False,
    ) -> Dict[str, Any]:
        if not allow_pending_recovery:
            self.assert_no_pending_recovery()
        return read_json_strict(
            self.paths.registry_path,
            "datasets",
            max_bytes=max_bytes,
        )

    def read_links(
        self,
        *,
        max_bytes: int | None = None,
        allow_pending_recovery: bool = False,
    ) -> Dict[str, Any]:
        if not allow_pending_recovery:
            self.assert_no_pending_recovery()
        return read_json_strict(
            self.paths.project_links_path,
            "links",
            max_bytes=max_bytes,
        )

    def read_users(
        self,
        *,
        required: bool = False,
        max_bytes: int | None = None,
        allow_pending_recovery: bool = False,
    ) -> Dict[str, Any] | None:
        if not allow_pending_recovery:
            self.assert_no_pending_recovery()
        return read_json_strict(
            self.paths.users_path,
            "users",
            allow_missing=not required,
            max_bytes=max_bytes,
        )

    def read_recovery_journal(
        self,
        *,
        required: bool = False,
        max_bytes: int = 1024 * 1024,
    ) -> Dict[str, Any] | None:
        payload = read_json_strict(
            self.paths.recovery_journal_path,
            allow_missing=not required,
            max_bytes=max_bytes,
        )
        if payload is None:
            return None
        if not _validate_recovery_journal(payload):
            raise DatasetStoreMalformedError(
                "Dataset Library recovery journal is malformed."
            )
        return payload

    def assert_no_pending_recovery(self) -> None:
        assert_no_pending_recovery(self.paths.root)

    def write_recovery_journal(
        self,
        payload: Mapping[str, Any],
        *,
        expected_sha256: str | None = None,
    ) -> Dict[str, Any]:
        with self.exclusive_lock():
            return self.atomic_write_json(
                self.paths.recovery_journal_path,
                dict(payload),
                expected_sha256=expected_sha256,
                shape_validator=_validate_recovery_journal,
            )

    def assert_test_storage_isolated(self) -> None:
        assert_test_storage_isolated(self.paths.root)

    @staticmethod
    def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
        """Expose the shared streaming digest through the storage facade."""

        return sha256_file(path, chunk_size=chunk_size)

    @contextmanager
    def exclusive_lock(self, timeout_seconds: float = 10.0) -> Iterator[None]:
        with library_write_lock(self.paths.root, timeout_seconds):
            yield

    def create_backup_bundle(
        self,
        *,
        reason: str,
        backup_directory: str | Path | None = None,
        include_paths: Iterable[str | Path] | None = None,
        retention_limit: int = 20,
        defer_retention: bool = False,
    ) -> Dict[str, Any]:
        selected = list(
            include_paths
            or (self.paths.registry_path, self.paths.project_links_path)
        )
        return create_backup_bundle(
            selected,
            library_root=self.paths.root,
            backup_root=backup_directory or self.paths.backup_root,
            reason=reason,
            retention=retention_limit,
            defer_retention=defer_retention,
        )

    def prune_backup_bundles(self, *, retention_limit: int = 20) -> None:
        _assert_external_backup_root(
            self.paths.backup_root,
            library_root=self.paths.root,
        )
        self.paths.backup_root.mkdir(parents=True, exist_ok=True)
        _prune_backup_bundles(self.paths.backup_root, retention_limit)

    def discard_incomplete_backup_bundle(
        self,
        bundle_path: str | Path,
    ) -> None:
        requested_root = self.paths.backup_root.expanduser()
        lexical_root = _assert_no_linked_path_component(
            requested_root,
            label="Dataset Library backup root",
        )
        _assert_external_backup_root(
            lexical_root,
            library_root=self.paths.root,
        )
        backup_root = lexical_root.resolve()
        candidate = Path(os.path.abspath(str(Path(bundle_path).expanduser())))
        lexical_root_absolute = Path(os.path.abspath(str(lexical_root)))
        if (
            candidate.parent != lexical_root_absolute
            or not candidate.name.startswith(_BACKUP_PREFIX)
        ):
            raise DatasetStorageError(
                "Incomplete backup bundle is outside the configured backup root."
            )
        if _has_linked_component_within(candidate, lexical_root_absolute):
            raise DatasetStorageError(
                "Refusing to discard a backup bundle through a filesystem link."
            )
        resolved = candidate.resolve()
        if resolved.parent != backup_root:
            raise DatasetStorageError(
                "Incomplete backup bundle resolved outside the configured backup root."
            )
        if resolved.exists():
            shutil.rmtree(candidate)

    def atomic_write_json(
        self,
        path: str | Path,
        payload: Any,
        *,
        expected_sha256: str | None = None,
        shape_validator: Callable[[Any], bool | None] | None = None,
    ) -> Dict[str, Any]:
        """Low-level atomic write; caller is responsible for lock + backup."""

        requested_destination = Path(path).expanduser()
        if _has_linked_component_within(requested_destination, self.paths.root):
            raise DatasetStorageError(
                "Dataset Library writes cannot traverse filesystem links."
            )
        destination = requested_destination.resolve()
        if not _path_within_root(destination, self.paths.root):
            raise DatasetStorageError(
                "Dataset Library writes must remain inside the configured root."
            )
        if _test_mode_enabled():
            self.assert_test_storage_isolated()
        expected_key = _default_shape_key(destination)
        _validate_root_shape(payload, expected_key)
        if shape_validator is not None and shape_validator(payload) is False:
            raise DatasetStoreMalformedError(
                "Dataset Library payload failed its shape validator."
            )
        before_hash = sha256_file(destination) if destination.exists() else None
        if expected_sha256 is not None and before_hash != expected_sha256:
            raise DatasetStoreConflictError(
                "Dataset Library document changed before the write completed."
            )
        rendered = _canonical_json_bytes(payload)
        after_hash = sha256_bytes(rendered)
        if before_hash == after_hash:
            return {
                "changed": False,
                "path": str(destination),
                "beforeSha256": before_hash,
                "afterSha256": after_hash,
            }
        _atomic_write_bytes(destination, rendered)
        verified = read_json_strict(destination, expected_key)
        if shape_validator is not None and shape_validator(verified) is False:
            raise DatasetStoreMalformedError(
                "Written Dataset Library payload failed verification."
            )
        return {
            "changed": True,
            "path": str(destination),
            "beforeSha256": before_hash,
            "afterSha256": sha256_file(destination),
        }

    def atomic_restore_json_bytes(
        self,
        path: str | Path,
        payload: bytes,
        *,
        expected_sha256: str | None = None,
    ) -> Dict[str, Any]:
        """Atomically restore previously captured, already-valid JSON bytes."""

        requested_destination = Path(path).expanduser()
        if _has_linked_component_within(requested_destination, self.paths.root):
            raise DatasetStorageError(
                "Dataset Library restores cannot traverse filesystem links."
            )
        destination = requested_destination.resolve()
        if not _path_within_root(destination, self.paths.root):
            raise DatasetStorageError(
                "Dataset Library restores must remain inside the configured root."
            )
        if _test_mode_enabled():
            self.assert_test_storage_isolated()
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise DatasetStoreMalformedError(
                "Backup payload is not valid UTF-8 JSON."
            ) from exc
        expected_key = _default_shape_key(destination)
        _validate_root_shape(decoded, expected_key)
        before_hash = sha256_file(destination) if destination.exists() else None
        if expected_sha256 is not None and before_hash != expected_sha256:
            raise DatasetStoreConflictError(
                "Dataset Library document changed before compensation."
            )
        restored_hash = sha256_bytes(payload)
        _atomic_write_bytes(destination, payload)
        read_json_strict(destination, expected_key)
        if sha256_file(destination) != restored_hash:
            raise DatasetStorageError("Compensating JSON restore failed verification.")
        return {
            "changed": before_hash != restored_hash,
            "path": str(destination),
            "beforeSha256": before_hash,
            "afterSha256": restored_hash,
        }

    def _mutate_document(
        self,
        *,
        path: Path,
        expected_root_key: str,
        mutator: Callable[[Dict[str, Any]], Mapping[str, Any] | None],
        reason: str,
        backup_directory: str | Path | None,
        expected_sha256: str | None,
    ) -> Dict[str, Any]:
        with self.exclusive_lock():
            current = read_json_strict(path, expected_root_key)
            before_hash = sha256_file(path)
            if expected_sha256 is not None and before_hash != expected_sha256:
                raise DatasetStoreConflictError(
                    "Dataset Library document changed before the mutation began."
                )
            working = copy.deepcopy(current)
            result = mutator(working)
            replacement = dict(result) if result is not None else working
            _validate_root_shape(replacement, expected_root_key)
            if replacement == current:
                return {
                    "changed": False,
                    "path": str(path),
                    "beforeSha256": before_hash,
                    "afterSha256": before_hash,
                    "backup": None,
                }
            rendered_hash = sha256_bytes(_canonical_json_bytes(replacement))
            if rendered_hash == before_hash:
                return {
                    "changed": False,
                    "path": str(path),
                    "beforeSha256": before_hash,
                    "afterSha256": before_hash,
                    "backup": None,
                }
            backup = self.create_backup_bundle(
                reason=reason,
                backup_directory=backup_directory,
                include_paths=[path],
            )
            mutation = self.atomic_write_json(
                path,
                replacement,
                expected_sha256=before_hash,
            )
            mutation["backup"] = backup
            return mutation

    def mutate_registry(
        self,
        mutator: Callable[[Dict[str, Any]], Mapping[str, Any] | None],
        *,
        reason: str,
        backup_directory: str | Path | None = None,
        expected_sha256: str | None = None,
    ) -> Dict[str, Any]:
        return self._mutate_document(
            path=self.paths.registry_path,
            expected_root_key="datasets",
            mutator=mutator,
            reason=reason,
            backup_directory=backup_directory,
            expected_sha256=expected_sha256,
        )

    def mutate_links(
        self,
        mutator: Callable[[Dict[str, Any]], Mapping[str, Any] | None],
        *,
        reason: str,
        backup_directory: str | Path | None = None,
        expected_sha256: str | None = None,
    ) -> Dict[str, Any]:
        return self._mutate_document(
            path=self.paths.project_links_path,
            expected_root_key="links",
            mutator=mutator,
            reason=reason,
            backup_directory=backup_directory,
            expected_sha256=expected_sha256,
        )


__all__ = [
    "DatasetLibraryPaths",
    "DatasetLibraryStorage",
    "DatasetRecoveryPendingError",
    "DatasetStorageError",
    "DatasetStoreConflictError",
    "DatasetStoreMalformedError",
    "DatasetStoreMissingError",
    "UnsafeTestStorageError",
    "assert_test_storage_isolated",
    "assert_no_pending_recovery",
    "atomic_write_json",
    "create_backup_bundle",
    "library_write_lock",
    "read_json_strict",
    "sha256_bytes",
    "sha256_file",
]
