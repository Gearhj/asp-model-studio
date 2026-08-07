"""Safe primitives for reading restricted bureau-metadata sources.

The catalog build is deliberately an offline process.  Source paths and the
final artifact directory must be supplied explicitly and must live outside the
ATLAS repository.  This module centralizes those checks so individual parsers
cannot accidentally grow a repository-relative or environment-based fallback.

No function in this module logs file contents.  Exceptions contain only a
sanitized role and failure category; callers that need a path for an external
restricted build log already have the explicit path they supplied.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_HASH_CHUNK_SIZE = 1024 * 1024


class BureauSourceError(RuntimeError):
    """Base error for restricted source and output handling."""


class UnsafeBureauPathError(BureauSourceError):
    """Raised when a source or output could overlap the repository."""


class BureauSourceUnavailableError(BureauSourceError):
    """Raised when an explicitly selected source is missing or unreadable."""


class BureauArtifactConflictError(BureauSourceError):
    """Raised when an immutable final artifact directory already exists."""


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """Non-content metadata for one explicitly selected source file."""

    path: Path
    filename: str
    suffix: str
    size_bytes: int
    sha256: str

    def public_metadata(self) -> dict[str, str | int]:
        """Return manifest-safe metadata without exposing a host path."""

        return {
            "filename": self.filename,
            "suffix": self.suffix,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


def repository_root() -> Path:
    """Return the resolved repository root used by the isolation guard."""

    return _REPOSITORY_ROOT


def is_within(path: Path, parent: Path) -> bool:
    """Return whether *path* is equal to or contained by *parent*."""

    resolved_path = path.resolve(strict=False)
    resolved_parent = parent.resolve(strict=False)
    return resolved_path == resolved_parent or resolved_parent in resolved_path.parents


def paths_overlap(first: Path, second: Path) -> bool:
    """Return whether either resolved path contains the other."""

    first_resolved = first.resolve(strict=False)
    second_resolved = second.resolve(strict=False)
    return (
        first_resolved == second_resolved
        or first_resolved in second_resolved.parents
        or second_resolved in first_resolved.parents
    )


def _require_explicit_absolute(path: str | Path, *, role: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise UnsafeBureauPathError(f"{role} must be an explicit absolute path")
    return candidate.resolve(strict=False)


def _require_external(path: Path, *, role: str, repository: Path | None) -> None:
    selected_repository = (repository or _REPOSITORY_ROOT).resolve(strict=False)
    if is_within(path, selected_repository):
        raise UnsafeBureauPathError(f"{role} must remain outside the repository")


def sha256_file(path: str | Path, *, chunk_size: int = _HASH_CHUNK_SIZE) -> str:
    """Calculate a streaming SHA-256 without materializing source contents."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_external_source(
    path: str | Path,
    *,
    role: str,
    expected_suffixes: tuple[str, ...] = (),
    repository: Path | None = None,
) -> SourceDescriptor:
    """Validate and fingerprint one explicit external source.

    ``expected_suffixes`` is matched case-insensitively.  The function never
    searches for a replacement source and never chooses a first/latest file.
    """

    resolved = _require_explicit_absolute(path, role=role)
    _require_external(resolved, role=role, repository=repository)
    if not resolved.exists() or not resolved.is_file():
        raise BureauSourceUnavailableError(f"{role} is not an available file")
    suffixes = tuple(value.casefold() for value in expected_suffixes)
    if suffixes and resolved.suffix.casefold() not in suffixes:
        raise BureauSourceUnavailableError(f"{role} has an unsupported file type")
    try:
        size = resolved.stat().st_size
        checksum = sha256_file(resolved)
    except OSError as exc:
        raise BureauSourceUnavailableError(f"{role} could not be read") from exc
    return SourceDescriptor(
        path=resolved,
        filename=resolved.name,
        suffix=resolved.suffix.casefold(),
        size_bytes=size,
        sha256=checksum,
    )


def inspect_external_output_directory(
    path: str | Path,
    *,
    repository: Path | None = None,
) -> Path:
    """Validate an explicit external final directory without creating it."""

    resolved = _require_explicit_absolute(path, role="output directory")
    selected_repository = (repository or _REPOSITORY_ROOT).resolve(strict=False)
    if paths_overlap(resolved, selected_repository):
        raise UnsafeBureauPathError(
            "output directory must remain physically separate from the repository"
        )
    if resolved.parent == resolved:
        raise UnsafeBureauPathError("output directory must not be a filesystem root")
    return resolved


def write_bytes_fsync(path: Path, payload: bytes) -> None:
    """Create one staging file and flush its content before publication."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def staged_external_directory(
    final_directory: str | Path,
    *,
    repository: Path | None = None,
) -> Iterator[Path]:
    """Yield a private sibling directory, then atomically publish it.

    The destination is immutable: an existing final directory is never
    replaced or merged.  A failed build removes only the unique staging
    directory created by this invocation.  Because staging and final paths are
    siblings, ``os.replace`` remains a same-filesystem atomic rename.
    """

    final_path = inspect_external_output_directory(
        final_directory,
        repository=repository,
    )
    if final_path.exists():
        raise BureauArtifactConflictError("final artifact directory already exists")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = final_path.parent / (
        f".{final_path.name}.staging-{os.getpid()}-{uuid.uuid4().hex}"
    )
    if paths_overlap(staging_path, _REPOSITORY_ROOT):
        raise UnsafeBureauPathError("staging directory must remain outside the repository")
    # Python's mode-to-ACL translation on Windows can make a newly created
    # directory inaccessible to the process that created it.  The caller must
    # select an already restricted Windows root; POSIX receives the additional
    # owner-only mode at creation time.
    if os.name == "nt":
        staging_path.mkdir()
    else:  # pragma: no cover - exercised by non-Windows deployments
        staging_path.mkdir(mode=0o700)
    published = False
    try:
        yield staging_path
        if final_path.exists():
            raise BureauArtifactConflictError("final artifact directory appeared during build")
        os.replace(staging_path, final_path)
        published = True
    finally:
        if not published and staging_path.exists():
            shutil.rmtree(staging_path, ignore_errors=True)


__all__ = [
    "BureauArtifactConflictError",
    "BureauSourceError",
    "BureauSourceUnavailableError",
    "SourceDescriptor",
    "UnsafeBureauPathError",
    "inspect_external_output_directory",
    "inspect_external_source",
    "is_within",
    "paths_overlap",
    "repository_root",
    "sha256_file",
    "staged_external_directory",
    "write_bytes_fsync",
]
