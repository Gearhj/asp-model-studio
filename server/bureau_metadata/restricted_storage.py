"""Durable, fail-closed installation for restricted bureau metadata catalogs.

The installer copies one already-built exact catalog snapshot into a dedicated
external authority.  It never discovers a first/latest catalog, never moves or
deletes the source, and never exposes a physical path in its public result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import uuid
from typing import Iterable, Mapping

from pydantic import ValidationError

from .catalog_store import (
    BureauCatalogIntegrityError,
    BureauCatalogStore,
    CATALOG_MANIFEST_FILE,
    _assert_no_linked_component,
    _is_link_or_junction,
    _is_relative_to,
)
from .normalizer import catalog_relative_directory, validate_sha256
from .types import BureauCatalogKey, BureauCatalogManifest


RESTRICTED_ROOT_ENV = "ATLAS_RESTRICTED_METADATA_ROOT"
RESTRICTED_MANIFEST_FILE = "restricted_installation_manifest.json"
INSTALLATION_AUDIT_FILE = "catalog_installation_audit.jsonl"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_PROTECTED_PATH_ENVIRONMENTS = (
    "ATLAS_DATASET_LIBRARY_ROOT",
    "ATLAS_DATASET_LIBRARY_BACKUP_ROOT",
    "ATLAS_SQLITE_PATH",
    "ATLAS_SECURITY_ROOT",
    "ATLAS_SECURITY_DB_PATH",
    "ATLAS_CHECKPOINT_PATH",
    "ATLAS_EVIDENCE_ROOT",
    "ATLAS_FEATURE_MANIFEST_ROOT",
    "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT",
    "ATLAS_SCORING_RUN_ARTIFACT_ROOT",
)


class RestrictedStorageError(RuntimeError):
    """Base class for safe restricted-storage failures."""


class RestrictedStorageConfigurationError(RestrictedStorageError):
    """The durable root is missing, unsafe, aliased, or contradictory."""


class RestrictedStorageIntegrityError(RestrictedStorageError):
    """The source or copied exact catalog failed verification."""


class RestrictedStorageConflictError(RestrictedStorageError):
    """The same exact logical version already has different content."""


@dataclass(frozen=True, slots=True)
class WindowsAclAssessment:
    status: str
    safe: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CatalogInstallationResult:
    catalog_id: str
    catalog_checksum: str
    attribute_count: int
    special_value_count: int
    storage_reference: str
    installation_status: str
    integrity_status: str
    idempotent: bool
    installed_at: str

    def public_payload(self) -> dict[str, object]:
        """Return a browser-safe result with no path or source filename."""

        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_existing(path: Path, *, label: str) -> Path:
    lexical = _assert_no_linked_component(path, label=label)
    try:
        resolved = lexical.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise RestrictedStorageConfigurationError(f"{label} does not exist.") from exc
    if not resolved.is_dir():
        raise RestrictedStorageConfigurationError(f"{label} must be a directory.")
    return resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or _is_relative_to(left, right) or _is_relative_to(right, left)


def _samefile_or_overlap(left: Path, right: Path) -> bool:
    if _paths_overlap(left, right):
        return True
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _default_forbidden_roots(repository_root: Path) -> tuple[Path, ...]:
    candidates = (
        repository_root,
        repository_root / ".tmp",
        repository_root / "audit-output",
        repository_root / "dist",
        repository_root / "public",
        repository_root / "test-results",
        repository_root / "playwright-report",
        repository_root / "server" / "data",
        repository_root / "server" / "artifacts" / "datasets",
        Path(tempfile.gettempdir()),
    )
    return tuple(Path(os.path.abspath(str(path))) for path in candidates)


def _git_worktree_roots(repository_root: Path) -> tuple[Path, ...]:
    """Return every worktree registered for the current repository.

    Git is advisory here: failure to enumerate does not relax the direct
    repository overlap check, while a successful result closes the gap where a
    sibling worktree would otherwise look like an unrelated durable directory.
    """

    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), "worktree", "list", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if completed.returncode != 0:
        return ()
    roots: list[Path] = []
    for line in completed.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        raw = line[len("worktree ") :].strip()
        if raw:
            roots.append(Path(os.path.abspath(raw)))
    return tuple(roots)


def _configured_protected_roots() -> tuple[Path, ...]:
    """Resolve configured live authorities without importing their modules."""

    roots: list[Path] = []
    for name in _PROTECTED_PATH_ENVIRONMENTS:
        raw = str(os.getenv(name) or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = Path(os.path.abspath(str(candidate)))
        # Database/checkpoint variables name files.  Comparing the file itself
        # is sufficient and avoids unnecessarily rejecting a safe sibling.
        roots.append(candidate)
    return tuple(roots)


def validate_restricted_metadata_root(
    root: str | Path | None,
    *,
    repository_root: str | Path | None = None,
    additional_forbidden_roots: Iterable[str | Path] = (),
    require_exists: bool = True,
) -> Path:
    """Resolve a durable root and reject every known unsafe overlap/alias."""

    supplied = str(root or "").strip()
    if not supplied:
        raise RestrictedStorageConfigurationError(
            f"{RESTRICTED_ROOT_ENV} must name an explicit durable restricted root."
        )
    candidate = Path(supplied).expanduser()
    if not candidate.is_absolute():
        raise RestrictedStorageConfigurationError(
            "Restricted metadata root must be an absolute path."
        )
    lexical = _assert_no_linked_component(candidate, label="Restricted metadata root")
    if require_exists:
        resolved = _canonical_existing(lexical, label="Restricted metadata root")
    else:
        parent = _canonical_existing(lexical.parent, label="Restricted metadata parent")
        if lexical.exists() and _is_link_or_junction(lexical):
            raise RestrictedStorageConfigurationError(
                "Restricted metadata root cannot be a filesystem link or junction."
            )
        resolved = parent / lexical.name

    repo = Path(repository_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    forbidden = [
        *_default_forbidden_roots(repo),
        *_git_worktree_roots(repo),
        *_configured_protected_roots(),
        *(Path(path) for path in additional_forbidden_roots),
    ]
    for raw_forbidden in forbidden:
        absolute = Path(os.path.abspath(str(raw_forbidden.expanduser())))
        # A missing forbidden child still matters lexically; an existing path
        # is additionally canonicalized so junction/case aliases cannot evade
        # the overlap comparison.
        comparisons = [absolute]
        if absolute.exists():
            try:
                comparisons.append(absolute.resolve(strict=True))
            except OSError:
                pass
        for forbidden_path in comparisons:
            if _samefile_or_overlap(resolved, forbidden_path):
                raise RestrictedStorageConfigurationError(
                    "Restricted metadata root overlaps a prohibited runtime or source location."
                )
    return resolved


def inspect_windows_acl(path: str | Path) -> WindowsAclAssessment:
    """Inspect Windows ACLs without modifying them or emitting raw ACL text."""

    if os.name != "nt":
        return WindowsAclAssessment("not_supported", True, "Platform ACL inspection unavailable.")
    candidate = Path(path)
    try:
        completed = subprocess.run(
            ["icacls", str(candidate)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return WindowsAclAssessment("unavailable", True, "Windows ACL inspection was unavailable.")
    if completed.returncode != 0:
        return WindowsAclAssessment("unavailable", True, "Windows ACL inspection could not complete.")
    broad_principals = ("everyone:", "authenticated users:", "builtin\\users:")
    broad_access = ("(f)", "(m)", "(w)", "(rx)", "(r)")
    unsafe_line = False
    for raw_line in completed.stdout.splitlines():
        normalized = raw_line.casefold()
        if any(principal in normalized for principal in broad_principals) and any(
            access in normalized for access in broad_access
        ):
            unsafe_line = True
            break
    if unsafe_line:
        return WindowsAclAssessment(
            "unsafe",
            False,
            "Restricted metadata root grants broad read or write access.",
        )
    return WindowsAclAssessment("safe", True, "No broad read/write grant was detected.")


def _read_manifest(exact_directory: Path) -> BureauCatalogManifest:
    manifest_path = exact_directory / CATALOG_MANIFEST_FILE
    if not manifest_path.is_file() or _is_link_or_junction(manifest_path):
        raise RestrictedStorageIntegrityError("Source catalog manifest is unavailable or linked.")
    try:
        payload = manifest_path.read_bytes()
        if len(payload) > MAX_MANIFEST_BYTES:
            raise RestrictedStorageIntegrityError("Source catalog manifest exceeds its read limit.")
        decoded = json.loads(payload.decode("utf-8"))
        return BureauCatalogManifest.model_validate(decoded)
    except RestrictedStorageIntegrityError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise RestrictedStorageIntegrityError("Source catalog manifest is invalid.") from exc


def _storage_reference(key: BureauCatalogKey, checksum: str) -> str:
    relative = catalog_relative_directory(key, checksum).as_posix()
    return "restricted-catalog:" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:32]


class RestrictedCatalogInstaller:
    """Copy, verify, and atomically publish one exact catalog version."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        repository_root: str | Path | None = None,
        additional_forbidden_roots: Iterable[str | Path] = (),
        require_safe_acl: bool = True,
    ) -> None:
        configured = root if root is not None else os.getenv(RESTRICTED_ROOT_ENV)
        self.repository_root = Path(repository_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
        self.root = validate_restricted_metadata_root(
            configured,
            repository_root=self.repository_root,
            additional_forbidden_roots=additional_forbidden_roots,
        )
        acl = inspect_windows_acl(self.root)
        if require_safe_acl and not acl.safe:
            raise RestrictedStorageConfigurationError(acl.detail)
        self.acl_assessment = acl

    @property
    def audit_path(self) -> Path:
        return self.root / "registry" / INSTALLATION_AUDIT_FILE

    def _append_audit(
        self,
        *,
        actor: str,
        manifest: BureauCatalogManifest,
        status: str,
        correlation_id: str,
    ) -> None:
        audit_dir = self.root / "registry"
        audit_dir.mkdir(parents=True, exist_ok=True)
        if _is_link_or_junction(audit_dir):
            raise RestrictedStorageConfigurationError("Installation audit directory is linked.")
        record = {
            "event_id": "catalog-install-" + uuid.uuid4().hex,
            "actor": str(actor).strip() or "unknown",
            "catalog_id": manifest.catalog_id,
            "catalog_checksum": manifest.catalog_checksum,
            "attribute_count": manifest.attribute_count,
            "special_value_count": manifest.special_value_count,
            "status": status,
            "correlation_id": correlation_id,
            "server_timestamp": _utc_now(),
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _source_store(self, exact_directory: Path, manifest: BureauCatalogManifest) -> BureauCatalogStore:
        expected_relative = Path(*catalog_relative_directory(manifest.catalog_key, manifest.catalog_checksum).parts)
        try:
            source_root = exact_directory.parents[len(expected_relative.parts) - 1]
            actual_relative = exact_directory.relative_to(source_root)
        except (IndexError, ValueError) as exc:
            raise RestrictedStorageIntegrityError(
                "Source catalog directory is not an exact checksum-qualified snapshot."
            ) from exc
        if tuple(part.casefold() for part in actual_relative.parts) != tuple(
            part.casefold() for part in expected_relative.parts
        ):
            raise RestrictedStorageIntegrityError(
                "Source catalog directory contradicts its manifest identity."
            )
        return BureauCatalogStore(source_root, repository_root=self.repository_root)

    def install(
        self,
        source_catalog_directory: str | Path,
        *,
        expected_catalog_checksum: str,
        expected_attribute_count: int,
        expected_special_value_count: int,
        actor: str | None = None,
        inject_failure_after_copy: bool = False,
    ) -> CatalogInstallationResult:
        correlation_id = "catalog-install-corr-" + uuid.uuid4().hex
        checksum = validate_sha256(expected_catalog_checksum, field_name="expected_catalog_checksum")
        source = _canonical_existing(Path(source_catalog_directory), label="Source catalog directory")
        if _samefile_or_overlap(source, self.root):
            raise RestrictedStorageConfigurationError(
                "Source and restricted destination roots cannot overlap."
            )
        manifest = _read_manifest(source)
        if manifest.catalog_checksum != checksum:
            raise RestrictedStorageIntegrityError("Source catalog checksum does not match the expected checksum.")
        if manifest.attribute_count != int(expected_attribute_count):
            raise RestrictedStorageIntegrityError("Source catalog record count does not match the expected count.")
        if manifest.special_value_count != int(expected_special_value_count):
            raise RestrictedStorageIntegrityError(
                "Source catalog special-value count does not match the expected count."
            )
        source_store = self._source_store(source, manifest)
        source_store.load_exact(manifest.catalog_key, checksum)

        relative = Path(*catalog_relative_directory(manifest.catalog_key, checksum).parts)
        final_directory = self.root / relative
        identity_directory = final_directory.parent
        identity_directory.mkdir(parents=True, exist_ok=True)
        for existing in identity_directory.iterdir():
            if existing.is_dir() and existing.name.casefold() != checksum.casefold():
                raise RestrictedStorageConflictError(
                    "The same logical catalog version is already installed with different content."
                )
        installed_at = _utc_now()
        principal = str(actor or getpass.getuser()).strip() or "unknown"
        if final_directory.exists():
            BureauCatalogStore(self.root, repository_root=self.repository_root).load_exact(
                manifest.catalog_key, checksum
            )
            self._append_audit(
                actor=principal,
                manifest=manifest,
                status="idempotent_verified",
                correlation_id=correlation_id,
            )
            return CatalogInstallationResult(
                catalog_id=manifest.catalog_id,
                catalog_checksum=checksum,
                attribute_count=manifest.attribute_count,
                special_value_count=manifest.special_value_count,
                storage_reference=_storage_reference(manifest.catalog_key, checksum),
                installation_status="installed",
                integrity_status="verified",
                idempotent=True,
                installed_at=installed_at,
            )

        staging_root = self.root / (".catalog-installing-" + uuid.uuid4().hex)
        staging_exact = staging_root / relative
        try:
            staging_exact.parent.mkdir(parents=True, exist_ok=False)
            shutil.copytree(source, staging_exact, symlinks=False, copy_function=shutil.copy2)
            for copied in staging_exact.rglob("*"):
                if _is_link_or_junction(copied):
                    raise RestrictedStorageIntegrityError(
                        "Copied catalog contains a filesystem link or junction."
                    )
            if inject_failure_after_copy:
                raise RestrictedStorageIntegrityError("Injected installation failure after copy.")
            copied_store = BureauCatalogStore(staging_root, repository_root=self.repository_root)
            copied = copied_store.load_exact(manifest.catalog_key, checksum)
            restricted_manifest = {
                "schema_version": "1.0",
                "storage_reference": _storage_reference(manifest.catalog_key, checksum),
                "catalog_id": copied.manifest.catalog_id,
                "catalog_checksum": copied.manifest.catalog_checksum,
                "attribute_count": copied.manifest.attribute_count,
                "special_value_count": copied.manifest.special_value_count,
                "installed_at": installed_at,
                "installed_by": principal,
                "integrity_status": "verified",
            }
            manifest_bytes = json.dumps(
                restricted_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            (staging_exact / RESTRICTED_MANIFEST_FILE).write_bytes(manifest_bytes)
            # Recheck the catalog artifacts after writing the restricted envelope.
            copied_store.load_exact(manifest.catalog_key, checksum)
            os.replace(staging_exact, final_directory)
            self._append_audit(
                actor=principal,
                manifest=manifest,
                status="installed_verified",
                correlation_id=correlation_id,
            )
        except Exception:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            raise
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)

        return CatalogInstallationResult(
            catalog_id=manifest.catalog_id,
            catalog_checksum=checksum,
            attribute_count=manifest.attribute_count,
            special_value_count=manifest.special_value_count,
            storage_reference=_storage_reference(manifest.catalog_key, checksum),
            installation_status="installed",
            integrity_status="verified",
            idempotent=False,
            installed_at=installed_at,
        )


__all__ = [
    "CatalogInstallationResult",
    "INSTALLATION_AUDIT_FILE",
    "RESTRICTED_MANIFEST_FILE",
    "RESTRICTED_ROOT_ENV",
    "RestrictedCatalogInstaller",
    "RestrictedStorageConfigurationError",
    "RestrictedStorageConflictError",
    "RestrictedStorageError",
    "RestrictedStorageIntegrityError",
    "WindowsAclAssessment",
    "inspect_windows_acl",
    "validate_restricted_metadata_root",
]
