"""Pure-stdlib authority planning for ATLAS hermetic test children.

This module must remain safe to import before any ``server`` module.  It owns
path validation, external source mirroring, and construction of the sanitized
child environment used by :mod:`scripts.run_hermetic_tests`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import uuid
from typing import Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
HERMETIC_MODE = "HERMETIC_REGRESSION"
RUN_PREFIX = "atlas-hrt-"
ISOLATED_MIGRATION_FIXTURES = frozenset(
    {
        "server/persistence/migrations/0028_project_deletion_append_only_cascade.sql",
    }
)
NODE_RUNTIME_PACKAGE_FILES: dict[str, tuple[str, ...]] = {
    # ``typescript.js`` is the self-contained CommonJS compiler API used by
    # legacy source-contract tests.  Copy only the declared runtime entrypoint
    # and its package metadata; never alias the repository's node_modules tree.
    "typescript": ("package.json", "lib/typescript.js"),
}
ROOT_PACKAGE_JSON = "package.json"

AUTHORITY_LAYOUT: dict[str, tuple[str, str]] = {
    "persistence_database": ("ATLAS_SQLITE_PATH", "authorities/persistence/atlas_local.db"),
    "security_root": ("ATLAS_SECURITY_ROOT", "authorities/security"),
    "security_database": ("ATLAS_SECURITY_DB_PATH", "authorities/security/atlas_security.db"),
    "dataset_library": ("ATLAS_DATASET_LIBRARY_ROOT", "authorities/dataset-library"),
    "dataset_backups": ("ATLAS_DATASET_LIBRARY_BACKUP_ROOT", "authorities/dataset-backups"),
    "bureau_catalog_registry_root": (
        "ATLAS_BUREAU_CATALOG_REGISTRY_ROOT",
        "authorities/bureau-catalog-registry",
    ),
    "restricted_metadata_root": (
        "ATLAS_RESTRICTED_METADATA_ROOT",
        "authorities/restricted-bureau-metadata",
    ),
    "catalog_install_journal_root": (
        "ATLAS_ISOLATED_CATALOG_INSTALL_JOURNAL_ROOT",
        "authorities/catalog-install-journal",
    ),
    "workflow_checkpoint": ("ATLAS_CHECKPOINT_PATH", "authorities/checkpoint/workflow_checkpoint.json"),
    "evidence_root": ("ATLAS_EVIDENCE_ROOT", "authorities/evidence"),
    "feature_manifest_root": ("ATLAS_FEATURE_MANIFEST_ROOT", "authorities/feature-manifests"),
    "model_registry_root": ("ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT", "authorities/model-registry"),
    "scoring_artifact_root": ("ATLAS_SCORING_RUN_ARTIFACT_ROOT", "authorities/scoring-runs"),
    "vif_plan_root": ("ATLAS_VIF_PLAN_ROOT", "authorities/vif-plans"),
    "python_runtime_root": ("ATLAS_PYTHON_RUNTIME_DIR", "authorities/python-runtime"),
    "sas_config_root": ("ATLAS_SAS_CONFIG_DIR", "authorities/sas-config"),
    "browser_storage_root": ("ATLAS_BROWSER_STORAGE_ROOT", "authorities/browser-storage"),
    "playwright_output_root": ("ATLAS_PLAYWRIGHT_OUTPUT_ROOT", "authorities/playwright-output"),
}

FILE_AUTHORITIES = frozenset(
    {"persistence_database", "security_database", "workflow_checkpoint"}
)
ALLOWED_NESTING = frozenset({frozenset({"security_root", "security_database"})})
SYSTEM_ENV_ALLOWLIST = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
        "COMMONPROGRAMW6432",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "WINDIR",
    }
)


class HermeticAuthorityError(RuntimeError):
    """Fail-closed exception that exposes a category, never a path value."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(f"HERMETIC_GUARD_REJECTED:{category}")


@dataclass(frozen=True)
class RunAuthority:
    run_id: str
    root: Path


@dataclass(frozen=True)
class ChildAuthority:
    run_id: str
    suite_name: str
    root: Path
    source_root: Path
    authorities: Mapping[str, Path]

    def environment_path(self, key: str) -> Path:
        return Path(self.authorities[key])


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-.") or "suite"


def _has_traversal(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def _is_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _walk_files(root: Path) -> Iterable[Path]:
    """Walk files without following a symlink, junction, or reparse directory."""

    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if not (current_path / name).is_symlink()
            and not _is_reparse(current_path / name)
        ]
        for name in filenames:
            path = current_path / name
            if not path.is_symlink() and not _is_reparse(path):
                yield path


def _existing_components(path: Path) -> Iterable[Path]:
    current = Path(path.anchor)
    if current.exists():
        yield current
    for part in path.parts[1:] if path.anchor else path.parts:
        current = current / part
        if not current.exists():
            break
        yield current


def _windows_long_path(path: Path) -> Path:
    if os.name != "nt" or not path.exists():
        return path
    buffer = ctypes.create_unicode_buffer(32768)
    try:
        length = ctypes.windll.kernel32.GetLongPathNameW(str(path), buffer, len(buffer))
    except (AttributeError, OSError):
        return path
    return Path(buffer.value) if length and length < len(buffer) else path


def canonical_path(path: str | Path, *, reject_links: bool = True) -> Path:
    raw = str(path)
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise HermeticAuthorityError("relative-path")
    if _has_traversal(candidate):
        raise HermeticAuthorityError("path-traversal")
    if raw.startswith("\\\\") or raw.startswith("\\\\?\\") or raw.startswith("\\\\.\\"):
        raise HermeticAuthorityError("unc-or-device-alias")
    if reject_links:
        for component in _existing_components(candidate):
            if component.is_symlink() or _is_reparse(component):
                raise HermeticAuthorityError("linked-or-reparse-path")
    resolved = candidate.resolve(strict=False)
    return _windows_long_path(resolved).resolve(strict=False)


def path_identity(path: str | Path) -> str:
    return os.path.normcase(str(canonical_path(path))).casefold()


def overlaps(left: str | Path, right: str | Path) -> bool:
    a = canonical_path(left)
    b = canonical_path(right)
    return a == b or a in b.parents or b in a.parents


def _live_roots() -> tuple[Path, ...]:
    configured_live_backup = os.environ.get("ATLAS_LIVE_DATASET_LIBRARY_BACKUP_ROOT")
    local = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    configured_live_repository = os.environ.get("ATLAS_LIVE_REPOSITORY_ROOT")
    repository_roots = (
        [Path(configured_live_repository)]
        if configured_live_repository
        else [REPO_ROOT]
    )
    roots: list[Path] = []
    for repository in repository_roots:
        roots.extend(
            (
                repository,
                repository / ".tmp",
                repository / ".runtime",
                repository / "server" / "data",
                repository / "server" / "artifacts",
            )
        )
    roots.append(
        Path(configured_live_backup)
        if configured_live_backup
        else local / "ATLAS" / "dataset-library-backups"
    )
    return tuple(
        path.resolve(strict=False)
        for path in roots
    )


def validate_external_root(root: str | Path) -> Path:
    resolved = canonical_path(root)
    for live in _live_roots():
        if overlaps(resolved, live):
            raise HermeticAuthorityError("live-or-repository-overlap")
    return resolved


def validate_child(child: ChildAuthority) -> None:
    if child.run_id.startswith(RUN_PREFIX) is False:
        raise HermeticAuthorityError("run-id")
    if not child.suite_name:
        raise HermeticAuthorityError("suite-name")
    root = validate_external_root(child.root)
    source = canonical_path(child.source_root)
    if source == root or root not in source.parents:
        raise HermeticAuthorityError("source-root")
    expected = set(AUTHORITY_LAYOUT)
    if set(child.authorities) != expected:
        raise HermeticAuthorityError("missing-authority")
    canonical: dict[str, Path] = {}
    for name, path in child.authorities.items():
        resolved = canonical_path(path)
        if resolved == root or root not in resolved.parents:
            raise HermeticAuthorityError("authority-outside-root")
        for live in _live_roots():
            if overlaps(resolved, live):
                raise HermeticAuthorityError("live-authority")
        canonical[name] = resolved
    names = sorted(canonical)
    for index, name in enumerate(names):
        for other in names[index + 1 :]:
            if frozenset({name, other}) in ALLOWED_NESTING:
                continue
            if overlaps(canonical[name], canonical[other]):
                raise HermeticAuthorityError("test-authority-overlap")
    if overlaps(canonical["dataset_library"], canonical["dataset_backups"]):
        raise HermeticAuthorityError("dataset-backup-overlap")


def validate_children_disjoint(children: Iterable[ChildAuthority]) -> None:
    materialized = list(children)
    for child in materialized:
        validate_child(child)
    for index, child in enumerate(materialized):
        for other in materialized[index + 1 :]:
            if overlaps(child.root, other.root):
                raise HermeticAuthorityError("suite-root-overlap")
            for key in ("persistence_database", "security_database"):
                if path_identity(child.authorities[key]) == path_identity(other.authorities[key]):
                    raise HermeticAuthorityError("shared-writable-database")


def create_run_authority(base: str | Path | None = None) -> RunAuthority:
    parent = Path(base or tempfile.gettempdir()).expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = f"{RUN_PREFIX}{stamp}-{uuid.uuid4().hex[:10]}"
    root = validate_external_root(parent / run_id)
    root.mkdir(parents=False, exist_ok=False)
    return RunAuthority(run_id=run_id, root=root)


def create_child_authority(run: RunAuthority, suite_name: str) -> ChildAuthority:
    suffix = uuid.uuid4().hex[:10]
    # Keep the physical child path deliberately short.  Several existing
    # Windows fixtures create two additional timestamped backup directories;
    # embedding the full suite name here can cross the legacy MAX_PATH limit
    # even though every component is otherwise valid.  The descriptive suite
    # name remains in process metadata and both JSON manifests.
    root = run.root / "c" / suffix
    source = root / "source"
    authorities = {
        name: root / relative
        for name, (_environment, relative) in AUTHORITY_LAYOUT.items()
    }
    child = ChildAuthority(
        run_id=run.run_id,
        suite_name=safe_name(suite_name),
        root=root,
        source_root=source,
        authorities=authorities,
    )
    validate_child(child)
    return child


def _is_mirror_source(
    relative: Path,
    isolated_migrations: frozenset[str] = frozenset(),
) -> bool:
    parts = {part.casefold() for part in relative.parts}
    if parts.intersection(
        {
            ".git",
            ".runtime",
            ".tmp",
            "__pycache__",
            ".pytest_cache",
            "artifacts",
            "node_modules",
            "dist",
            "test-results",
            "audit-output",
        }
    ):
        return False
    if len(relative.parts) >= 2 and relative.parts[0] == "server" and relative.parts[1] == "data":
        return False
    name = relative.name.casefold()
    if name.startswith(".env"):
        return False
    relative_key = relative.as_posix()
    if relative_key in ISOLATED_MIGRATION_FIXTURES:
        return relative_key in isolated_migrations
    if relative.suffix.casefold() in {
        ".csv",
        ".tsv",
        ".parquet",
        ".xlsx",
        ".xls",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".pkl",
        ".pickle",
        ".joblib",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".zip",
        ".7z",
    }:
        return False
    return relative.suffix.casefold() in {
        ".md",
        ".txt",
        ".py",
        ".pyi",
        ".sql",
        ".json",
        ".css",
        ".mjs",
        ".js",
        ".cjs",
        ".ts",
        ".tsx",
    }


def _exclusive_json(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _validated_root_package_source() -> tuple[Path, str]:
    """Return the exact repository package metadata and its immutable digest."""

    repository = canonical_path(REPO_ROOT)
    source = canonical_path(REPO_ROOT / ROOT_PACKAGE_JSON)
    if source.parent != repository or not source.is_file():
        raise HermeticAuthorityError("root-package-source")
    if source.is_symlink() or _is_reparse(source):
        raise HermeticAuthorityError("root-package-source-linked")
    try:
        content = source.read_bytes()
        metadata = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HermeticAuthorityError("root-package-metadata") from exc
    if (
        not isinstance(metadata, dict)
        or metadata.get("name") != "atlas"
        or metadata.get("private") is not True
        or metadata.get("type") != "module"
        or not isinstance(metadata.get("scripts"), dict)
    ):
        raise HermeticAuthorityError("root-package-metadata")
    return source, hashlib.sha256(content).hexdigest()


def copy_root_package_json(child: ChildAuthority) -> dict[str, str]:
    """Copy root package metadata into a verified, read-only child authority.

    Node source-contract tests intentionally inspect the repository package
    metadata.  Supplying a physical child-local copy prevents those reads (and
    Node package-scope discovery) from climbing back to the live repository.
    """

    validate_child(child)
    if not child.source_root.is_dir():
        raise HermeticAuthorityError("missing-source-root")
    source, source_hash = _validated_root_package_source()
    source_before = source.stat()
    target = child.source_root / ROOT_PACKAGE_JSON
    if target.exists():
        raise HermeticAuthorityError("root-package-destination-exists")
    shutil.copy2(source, target)
    if target.is_symlink() or _is_reparse(target):
        raise HermeticAuthorityError("root-package-destination-linked")
    try:
        if os.path.samefile(source, target):
            raise HermeticAuthorityError("root-package-source-alias")
    except OSError as exc:
        raise HermeticAuthorityError("root-package-copy-verification") from exc
    try:
        target.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    except OSError as exc:
        raise HermeticAuthorityError("root-package-immutability") from exc
    target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    target_mode = stat.S_IMODE(target.stat().st_mode)
    source_after = source.stat()
    if (
        target_hash != source_hash
        or target_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        or source_after.st_size != source_before.st_size
        or source_after.st_mtime_ns != source_before.st_mtime_ns
        or hashlib.sha256(source.read_bytes()).hexdigest() != source_hash
    ):
        raise HermeticAuthorityError("root-package-copy-verification")
    return {"path": ROOT_PACKAGE_JSON, "sha256": target_hash}


def create_source_mirror(
    child: ChildAuthority,
    *,
    isolated_migrations: Iterable[str] = (),
    node_runtime_packages: Iterable[str] = (),
) -> dict[str, object]:
    """Create a source-only mirror after the authority plan has passed."""

    validate_child(child)
    requested_migrations = frozenset(str(item) for item in isolated_migrations)
    if not requested_migrations.issubset(ISOLATED_MIGRATION_FIXTURES):
        raise HermeticAuthorityError("unsupported-isolated-migration")
    requested_node_packages = frozenset(str(item) for item in node_runtime_packages)
    if not requested_node_packages.issubset(NODE_RUNTIME_PACKAGE_FILES):
        raise HermeticAuthorityError("unsupported-node-runtime-package")
    child.root.mkdir(parents=True, exist_ok=False)
    child.source_root.mkdir(parents=False, exist_ok=False)
    copied: list[dict[str, str]] = []
    root_package = copy_root_package_json(child)
    copied.append(root_package)
    root_requirements = REPO_ROOT / "requirements.txt"
    requirements_target = child.source_root / "requirements.txt"
    shutil.copy2(root_requirements, requirements_target)
    copied.append(
        {
            "path": "requirements.txt",
            "sha256": hashlib.sha256(requirements_target.read_bytes()).hexdigest(),
        }
    )
    for top in ("server", "scripts", "tests", "shared", "src"):
        origin = REPO_ROOT / top
        for source in sorted(_walk_files(origin)):
            relative = source.relative_to(REPO_ROOT)
            if not _is_mirror_source(relative, requested_migrations):
                continue
            if source.is_symlink() or _is_reparse(source):
                raise HermeticAuthorityError("linked-source")
            target = child.source_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(
                {
                    "path": relative.as_posix(),
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            )
    for empty in (
        child.source_root / "server" / "data",
        child.source_root / "server" / "artifacts",
        child.source_root / "server" / "artifacts" / "datasets",
        child.source_root / "server" / "static",
        child.source_root / ".runtime",
        child.source_root / ".tmp",
    ):
        empty.mkdir(parents=True, exist_ok=True)
    copied.extend(copy_node_runtime_packages(child, requested_node_packages))
    sitecustomize = child.source_root / "sitecustomize.py"
    sitecustomize.write_text(
        "from scripts.hermetic_test_authority import sitecustomize_guard\n"
        "sitecustomize_guard()\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        "schema_version": 1,
        "copied_file_count": len(copied),
        "migration_0028_included": bool(
            ISOLATED_MIGRATION_FIXTURES.intersection(requested_migrations)
        ),
        "isolated_migration_fixtures": sorted(requested_migrations),
        "node_runtime_packages": sorted(requested_node_packages),
        "node_runtime_is_copied": bool(requested_node_packages),
        "root_package_json": {
            **root_package,
            "child_local": True,
            "read_only": True,
        },
        "raw_data_included": False,
        "files": copied,
    }
    _exclusive_json(child.root / "source-manifest.json", manifest)
    return manifest


def _node_runtime_source_files(package_name: str) -> tuple[tuple[Path, Path], ...]:
    relative_files = NODE_RUNTIME_PACKAGE_FILES.get(package_name)
    if relative_files is None:
        raise HermeticAuthorityError("unsupported-node-runtime-package")
    package_root = REPO_ROOT / "node_modules" / package_name
    if not package_root.is_dir() or package_root.is_symlink() or _is_reparse(package_root):
        raise HermeticAuthorityError("node-runtime-package-unavailable")
    resolved_package_root = canonical_path(package_root)
    expected_modules_root = canonical_path(REPO_ROOT / "node_modules")
    if resolved_package_root.parent != expected_modules_root:
        raise HermeticAuthorityError("node-runtime-source-root")
    sources: list[tuple[Path, Path]] = []
    for relative_text in relative_files:
        relative = Path(relative_text)
        if relative.is_absolute() or _has_traversal(relative):
            raise HermeticAuthorityError("node-runtime-source-path")
        source = canonical_path(package_root / relative)
        if resolved_package_root not in source.parents or not source.is_file():
            raise HermeticAuthorityError("node-runtime-package-unavailable")
        sources.append((relative, source))
    try:
        metadata = json.loads(sources[0][1].read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HermeticAuthorityError("node-runtime-package-metadata") from exc
    if not isinstance(metadata, dict):
        raise HermeticAuthorityError("node-runtime-package-metadata")
    declared_main = str(metadata.get("main") or "").replace("\\", "/")
    if declared_main.startswith("./"):
        declared_main = declared_main[2:]
    if (
        metadata.get("name") != package_name
        or declared_main != "lib/typescript.js"
    ):
        raise HermeticAuthorityError("node-runtime-package-metadata")
    return tuple(sources)


def copy_node_runtime_packages(
    child: ChildAuthority,
    package_names: Iterable[str],
) -> list[dict[str, str]]:
    """Copy approved Node runtime entrypoints into one external child source.

    The destination is a physical child-local copy.  Source and destination
    hashes are compared immediately, and a same-file alias fails closed.
    """

    validate_child(child)
    requested = tuple(sorted(set(str(item) for item in package_names)))
    unsupported = set(requested).difference(NODE_RUNTIME_PACKAGE_FILES)
    if unsupported:
        raise HermeticAuthorityError("unsupported-node-runtime-package")
    if not requested:
        return []
    if not child.source_root.is_dir():
        raise HermeticAuthorityError("missing-source-root")
    destination_root = canonical_path(child.source_root / "node_modules")
    if child.source_root.resolve() not in destination_root.parents:
        raise HermeticAuthorityError("node-runtime-destination-root")
    copied: list[dict[str, str]] = []
    for package_name in requested:
        for relative, source in _node_runtime_source_files(package_name):
            target = destination_root / package_name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise HermeticAuthorityError("node-runtime-destination-exists")
            shutil.copy2(source, target)
            if target.is_symlink() or _is_reparse(target):
                raise HermeticAuthorityError("node-runtime-destination-linked")
            try:
                if os.path.samefile(source, target):
                    raise HermeticAuthorityError("node-runtime-source-alias")
            except OSError as exc:
                raise HermeticAuthorityError("node-runtime-copy-verification") from exc
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if target_hash != source_hash:
                raise HermeticAuthorityError("node-runtime-copy-verification")
            copied.append(
                {
                    "path": target.relative_to(child.source_root).as_posix(),
                    "sha256": target_hash,
                }
            )
    return copied


def build_child_environment(
    child: ChildAuthority,
    inherited: Mapping[str, str] | None = None,
) -> dict[str, str]:
    validate_child(child)
    source = dict(inherited or os.environ)
    _root_package_source, root_package_hash = _validated_root_package_source()
    live_backup_root = Path(source.get("LOCALAPPDATA") or tempfile.gettempdir()) / "ATLAS" / "dataset-library-backups"
    environment = {
        key: value
        for key, value in source.items()
        if key.upper() in SYSTEM_ENV_ALLOWLIST
    }
    environment.update(
        {
            "ATLAS_TEST_MODE": "1",
            "ATLAS_ENV": "testing",
            "ATLAS_RUN_ID": child.run_id,
            "ATLAS_PROCESS_ROLE": "test",
            "ATLAS_TEST_NAME": child.suite_name,
            "ATLAS_CHILD_ID": child.root.name,
            "ATLAS_HERMETIC_MODE": HERMETIC_MODE,
            "ATLAS_HERMETIC_ROOT": str(child.root),
            "ATLAS_HERMETIC_SOURCE_ROOT": str(child.source_root),
            "ATLAS_HERMETIC_NODE_MODULES_ROOT": str(
                child.source_root / "node_modules"
            ),
            "ATLAS_HERMETIC_NODE_CACHE_ROOT": str(
                child.root / "authorities" / "node-cache"
            ),
            "ATLAS_HERMETIC_PACKAGE_JSON": str(
                child.source_root / ROOT_PACKAGE_JSON
            ),
            "ATLAS_HERMETIC_PACKAGE_JSON_SHA256": root_package_hash,
            "ATLAS_HERMETIC_NODE_GUARD_PASSED": "0",
            "ATLAS_LIVE_REPOSITORY_ROOT": str(REPO_ROOT),
            "ATLAS_LIVE_DATASET_LIBRARY_BACKUP_ROOT": str(live_backup_root),
            "ATLAS_HERMETIC_GUARD_PASSED": "0",
            "ATLAS_TEST_BACKEND_URL": "http://atlas-hermetic.invalid",
            "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "0",
            "ATLAS_ALLOW_PUBLIC_REGISTRATION": "0",
            "ATLAS_LOCAL_DEV": "0",
            "ATLAS_HOSTED_MODE": "0",
            "ATLAS_AUTH_ENABLED": "0",
            "ATLAS_CODE_EXECUTION": "0",
            "ATLAS_SESSION_SECRET": hashlib.sha256(
                f"{child.run_id}:{child.suite_name}".encode("utf-8")
            ).hexdigest(),
            "PYTHONPATH": str(child.source_root),
            # Hermetic children are one-shot processes with immutable source
            # mirrors.  Persisting bytecode creates thousands of files per
            # suite without providing a reusable cache and can make late
            # Windows process startup unbounded as preserved evidence grows.
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(child.root / "authorities" / "pycache"),
            "TEMP": str(child.root / "t"),
            "TMP": str(child.root / "t"),
            "HOME": str(child.root / "authorities" / "home"),
            "USERPROFILE": str(child.root / "authorities" / "home"),
            "APPDATA": str(child.root / "authorities" / "appdata"),
            "LOCALAPPDATA": str(child.root / "authorities" / "localappdata"),
            "XDG_CACHE_HOME": str(child.root / "authorities" / "cache"),
            "MPLCONFIGDIR": str(child.root / "authorities" / "matplotlib"),
            "NUMBA_CACHE_DIR": str(child.root / "authorities" / "numba"),
            "JOBLIB_TEMP_FOLDER": str(child.root / "authorities" / "joblib"),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "NODE_COMPILE_CACHE": str(child.root / "authorities" / "node-cache"),
        }
    )
    for name, (variable, _relative) in AUTHORITY_LAYOUT.items():
        environment[variable] = str(child.authorities[name])
    return environment


def resolved_authority_manifest(child: ChildAuthority) -> dict[str, object]:
    validate_child(child)
    relative = {
        name: canonical_path(path).relative_to(child.root).as_posix()
        for name, path in sorted(child.authorities.items())
    }
    hardcoded = [
        "server/artifacts/analytics",
        "server/artifacts/credit_risk",
        "server/artifacts/eda_documentation",
        "server/artifacts/model_documentation",
        "server/artifacts/notebooks",
        "server/artifacts/projects",
        "server/artifacts/sql_studio",
    ]
    return {
        "schema_version": 1,
        "run_id": child.run_id,
        "suite_name": child.suite_name,
        "mode": HERMETIC_MODE,
        "authorities": relative,
        "hardcoded_mirror_authorities": hardcoded,
        "all_external": True,
    }


def prepare_child(
    child: ChildAuthority,
    *,
    isolated_migrations: Iterable[str] = (),
    node_runtime_packages: Iterable[str] = (),
) -> dict[str, object]:
    source_manifest = create_source_mirror(
        child,
        isolated_migrations=isolated_migrations,
        node_runtime_packages=node_runtime_packages,
    )
    for name, path in child.authorities.items():
        parent = path.parent if name in FILE_AUTHORITIES else path
        parent.mkdir(parents=True, exist_ok=True)
    for extra in (
        child.root / "authorities" / "pycache",
        child.root / "t",
        child.root / "authorities" / "home",
        child.root / "authorities" / "appdata",
        child.root / "authorities" / "localappdata",
        child.root / "authorities" / "cache",
        child.root / "authorities" / "matplotlib",
        child.root / "authorities" / "numba",
        child.root / "authorities" / "joblib",
        child.root / "authorities" / "node-cache",
        child.root / "reports",
    ):
        extra.mkdir(parents=True, exist_ok=True)
    manifest = resolved_authority_manifest(child)
    _exclusive_json(child.root / "authority-manifest.json", manifest)
    return {"source": source_manifest, "authorities": manifest}


def sitecustomize_guard() -> None:
    """Run before pytest/plugins or ATLAS imports in every Python child."""

    if os.environ.get("ATLAS_HERMETIC_MODE") != HERMETIC_MODE:
        return
    try:
        required = {
            "ATLAS_TEST_MODE": "1",
            "ATLAS_PROCESS_ROLE": "test",
        }
        if any(os.environ.get(key) != value for key, value in required.items()):
            raise HermeticAuthorityError("metadata")
        # A suite may spawn a fresh Python interpreter and inherit the
        # parent's post-guard sentinel.  Sitecustomize still runs before any
        # application import in that interpreter, so accept either state and
        # fully revalidate every authority below.  Any missing or changed
        # authority continues to fail closed.
        if os.environ.get("ATLAS_HERMETIC_GUARD_PASSED") not in {"0", "1"}:
            raise HermeticAuthorityError("metadata")
        run_id = os.environ.get("ATLAS_RUN_ID", "")
        if not run_id.startswith(RUN_PREFIX) or not os.environ.get("ATLAS_TEST_NAME"):
            raise HermeticAuthorityError("metadata")
        if any(name == "server" or name.startswith("server.") for name in __import__("sys").modules):
            raise HermeticAuthorityError("atlas-preimport")
        root = validate_external_root(os.environ.get("ATLAS_HERMETIC_ROOT", ""))
        source_root = canonical_path(os.environ.get("ATLAS_HERMETIC_SOURCE_ROOT", ""))
        if root not in source_root.parents:
            raise HermeticAuthorityError("source-root")
        configured: dict[str, Path] = {}
        for name, (variable, _relative) in AUTHORITY_LAYOUT.items():
            value = os.environ.get(variable)
            if not value:
                raise HermeticAuthorityError("missing-authority")
            configured[name] = Path(value)
        child = ChildAuthority(run_id, os.environ["ATLAS_TEST_NAME"], root, source_root, configured)
        validate_child(child)
        backend = os.environ.get("ATLAS_TEST_BACKEND_URL", "")
        if re.search(r"https?://(?:127\.0\.0\.1|localhost|\[::1\]):(?:5174|8001)(?:/|$)", backend, re.I):
            raise HermeticAuthorityError("live-backend")
        os.environ["ATLAS_HERMETIC_GUARD_PASSED"] = "1"
    except HermeticAuthorityError as exc:
        try:
            __import__("sys").stderr.write(f"{exc}\n")
            __import__("sys").stderr.flush()
        finally:
            os._exit(86)


def inventory_created_files(child: ChildAuthority | Path) -> dict[str, int]:
    root = child.root if isinstance(child, ChildAuthority) else Path(child)
    files = list(_walk_files(root))
    return {
        "created_file_count": len(files),
        "created_byte_count": sum(path.stat().st_size for path in files),
    }


__all__ = [
    "AUTHORITY_LAYOUT",
    "ChildAuthority",
    "FILE_AUTHORITIES",
    "HERMETIC_MODE",
    "ISOLATED_MIGRATION_FIXTURES",
    "NODE_RUNTIME_PACKAGE_FILES",
    "ROOT_PACKAGE_JSON",
    "HermeticAuthorityError",
    "REPO_ROOT",
    "RUN_PREFIX",
    "RunAuthority",
    "build_child_environment",
    "canonical_path",
    "create_child_authority",
    "create_run_authority",
    "create_source_mirror",
    "copy_root_package_json",
    "copy_node_runtime_packages",
    "inventory_created_files",
    "overlaps",
    "path_identity",
    "prepare_child",
    "resolved_authority_manifest",
    "safe_name",
    "sitecustomize_guard",
    "validate_child",
    "validate_children_disjoint",
    "validate_external_root",
]
