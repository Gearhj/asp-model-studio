"""Strict external storage and bounded loading for bureau metadata catalogs."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from types import MappingProxyType
from typing import Any, Mapping, TypeVar

from pydantic import BaseModel, ValidationError

from .normalizer import (
    BureauMetadataNormalizationError,
    catalog_relative_directory,
    normalize_attribute_code,
    normalize_value_code,
    validate_relative_artifact_path,
    validate_sha256,
)
from .types import (
    BureauAttributeDefinition,
    BureauCatalogFileDescriptor,
    BureauCatalogKey,
    BureauCatalogManifest,
    BureauSpecialValueDefinition,
)
from .validation import BureauCatalogValidationError, validate_catalog


CATALOG_MANIFEST_FILE = "catalog_manifest.json"
_DEFAULT_MAX_FILE_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_TOTAL_BYTES = 192 * 1024 * 1024


class BureauCatalogStoreError(RuntimeError):
    """Base class for safe catalog storage failures."""


class BureauCatalogRootError(BureauCatalogStoreError):
    """Raised when the configured catalog root is missing or unsafe."""


class BureauCatalogNotFoundError(BureauCatalogStoreError):
    """Raised when the exact checksum-qualified catalog does not exist."""


class BureauCatalogIntegrityError(BureauCatalogStoreError):
    """Raised when a catalog artifact cannot be verified."""


@dataclass(frozen=True, slots=True)
class LoadedBureauCatalog:
    manifest: BureauCatalogManifest
    attributes_by_code: Mapping[str, BureauAttributeDefinition]
    special_values_by_key: Mapping[tuple[str, str], BureauSpecialValueDefinition]
    reconciliation_findings: tuple[Mapping[str, Any], ...]
    validation_summary: Mapping[str, Any]


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
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
        )
    return False


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(str(path.expanduser())))


def _assert_no_linked_component(path: Path, *, label: str) -> Path:
    lexical = _lexical_absolute(path)
    parts = lexical.parts
    if not parts:
        raise BureauCatalogRootError(f"{label} is invalid.")
    current = Path(parts[0])
    if _is_link_or_junction(current):
        raise BureauCatalogRootError(f"{label} cannot traverse filesystem links.")
    for part in parts[1:]:
        current = current / part
        if current.exists() and _is_link_or_junction(current):
            raise BureauCatalogRootError(
                f"{label} cannot traverse filesystem links or junctions."
            )
    return lexical


def _safe_repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_external_catalog_root(
    root: str | Path,
    *,
    repository_root: str | Path | None = None,
) -> Path:
    supplied = Path(root)
    if not supplied.is_absolute():
        raise BureauCatalogRootError(
            "Bureau catalog root must be an explicit absolute external path."
        )
    lexical = _assert_no_linked_component(supplied, label="Bureau catalog root")
    if not lexical.exists() or not lexical.is_dir():
        raise BureauCatalogRootError(
            "Bureau catalog root must already exist as a directory."
        )
    resolved = lexical.resolve(strict=True)
    repository = _assert_no_linked_component(
        Path(repository_root) if repository_root is not None else _safe_repository_root(),
        label="Repository root",
    ).resolve(strict=True)
    if (
        resolved == repository
        or _is_relative_to(resolved, repository)
        or _is_relative_to(repository, resolved)
    ):
        raise BureauCatalogRootError(
            "Bureau catalog root must remain physically separate from the repository."
        )
    try:
        if os.path.samefile(resolved, repository):
            raise BureauCatalogRootError(
                "Bureau catalog root aliases the repository."
            )
    except OSError:
        pass
    return resolved


_ModelT = TypeVar("_ModelT", bound=BaseModel)


class BureauCatalogStore:
    """Read one exact checksum-qualified catalog without discovery fallback."""

    def __init__(
        self,
        root: str | Path,
        *,
        repository_root: str | Path | None = None,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        self.root = validate_external_catalog_root(
            root,
            repository_root=repository_root,
        )
        self.max_file_bytes = int(max_file_bytes)
        self.max_total_bytes = int(max_total_bytes)
        if self.max_file_bytes <= 0 or self.max_total_bytes <= 0:
            raise BureauCatalogRootError("Catalog read limits must be positive.")
        if self.max_file_bytes > self.max_total_bytes:
            raise BureauCatalogRootError(
                "Per-file catalog limit cannot exceed the total read limit."
            )

    def _exact_directory(
        self,
        key: BureauCatalogKey,
        expected_checksum: str,
    ) -> Path:
        relative = catalog_relative_directory(key, expected_checksum)
        candidate = _assert_no_linked_component(
            self.root.joinpath(*relative.parts),
            label="Exact bureau catalog directory",
        )
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise BureauCatalogNotFoundError(
                "The exact checksum-qualified bureau catalog is unavailable."
            ) from exc
        if not resolved.is_dir() or not _is_relative_to(resolved, self.root):
            raise BureauCatalogIntegrityError(
                "The exact bureau catalog directory is outside its configured root."
            )
        return resolved

    def _artifact_path(self, directory: Path, relative_path: str) -> Path:
        try:
            safe_relative = validate_relative_artifact_path(relative_path)
        except BureauMetadataNormalizationError as exc:
            raise BureauCatalogIntegrityError(
                "Catalog manifest contains an unsafe artifact reference."
            ) from exc
        lexical = _assert_no_linked_component(
            directory.joinpath(*safe_relative.split("/")),
            label="Bureau catalog artifact",
        )
        try:
            resolved = lexical.resolve(strict=True)
        except FileNotFoundError as exc:
            raise BureauCatalogIntegrityError(
                "A required bureau catalog artifact is missing."
            ) from exc
        if not resolved.is_file() or not _is_relative_to(resolved, directory):
            raise BureauCatalogIntegrityError(
                "A bureau catalog artifact escapes its exact catalog directory."
            )
        return resolved

    def _read_path(self, path: Path, *, max_bytes: int) -> bytes:
        try:
            size = path.stat().st_size
            if size > max_bytes:
                raise BureauCatalogIntegrityError(
                    "A bureau catalog artifact exceeds its configured read limit."
                )
            with path.open("rb") as handle:
                payload = handle.read(max_bytes + 1)
        except BureauCatalogIntegrityError:
            raise
        except OSError as exc:
            raise BureauCatalogIntegrityError(
                "A bureau catalog artifact could not be read."
            ) from exc
        if len(payload) > max_bytes or len(payload) != size:
            raise BureauCatalogIntegrityError(
                "A bureau catalog artifact changed or exceeded its read limit."
            )
        return payload

    def _read_descriptor(
        self,
        directory: Path,
        descriptor: BureauCatalogFileDescriptor,
    ) -> bytes:
        if descriptor.size_bytes > self.max_file_bytes:
            raise BureauCatalogIntegrityError(
                "A bureau catalog descriptor exceeds its configured read limit."
            )
        path = self._artifact_path(directory, descriptor.relative_path)
        payload = self._read_path(path, max_bytes=self.max_file_bytes)
        if len(payload) != descriptor.size_bytes:
            raise BureauCatalogIntegrityError(
                "A bureau catalog artifact size does not match its descriptor."
            )
        if hashlib.sha256(payload).hexdigest() != descriptor.sha256:
            raise BureauCatalogIntegrityError(
                "A bureau catalog artifact checksum could not be verified."
            )
        return payload

    @staticmethod
    def _decode_json(payload: bytes) -> Mapping[str, Any]:
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise BureauCatalogIntegrityError(
                "A bureau catalog JSON artifact is malformed."
            ) from exc
        if not isinstance(value, dict):
            raise BureauCatalogIntegrityError(
                "A bureau catalog JSON artifact must contain an object."
            )
        return value

    @staticmethod
    def _decode_jsonl(
        payload: bytes,
        model: type[_ModelT] | None,
        *,
        expected_count: int,
    ) -> tuple[_ModelT | Mapping[str, Any], ...]:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BureauCatalogIntegrityError(
                "A bureau catalog JSONL artifact is not UTF-8."
            ) from exc
        records: list[_ModelT | Mapping[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                raise BureauCatalogIntegrityError(
                    "A bureau catalog JSONL artifact contains a blank record."
                )
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise TypeError("record is not an object")
                records.append(model.model_validate(raw) if model is not None else raw)
            except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                raise BureauCatalogIntegrityError(
                    "A bureau catalog JSONL record is malformed."
                ) from exc
        if len(records) != expected_count:
            raise BureauCatalogIntegrityError(
                "A bureau catalog JSONL record count does not match its descriptor."
            )
        return tuple(records)

    def load_exact(
        self,
        key: BureauCatalogKey,
        expected_checksum: str,
    ) -> LoadedBureauCatalog:
        try:
            checksum = validate_sha256(
                expected_checksum,
                field_name="expected catalog checksum",
            )
        except BureauMetadataNormalizationError as exc:
            raise BureauCatalogIntegrityError(
                "An exact lowercase catalog checksum is required."
            ) from exc
        directory = self._exact_directory(key, checksum)
        manifest_path = self._artifact_path(directory, CATALOG_MANIFEST_FILE)
        manifest_payload = self._read_path(
            manifest_path,
            max_bytes=min(self.max_file_bytes, 2 * 1024 * 1024),
        )
        try:
            manifest = BureauCatalogManifest.model_validate(
                self._decode_json(manifest_payload)
            )
        except ValidationError as exc:
            raise BureauCatalogIntegrityError(
                "The bureau catalog manifest violates its strict contract."
            ) from exc
        if manifest.catalog_key != key or manifest.catalog_checksum != checksum:
            raise BureauCatalogIntegrityError(
                "The bureau catalog manifest contradicts the exact requested identity."
            )

        required_descriptors = [manifest.attribute_file, manifest.special_value_file]
        optional_descriptors = [
            manifest.reconciliation_file,
            manifest.lookup_index_file,
            manifest.validation_file,
            manifest.build_log_file,
        ]
        described_total = sum(
            descriptor.size_bytes
            for descriptor in [*required_descriptors, *optional_descriptors]
            if descriptor is not None
        )
        if described_total > self.max_total_bytes:
            raise BureauCatalogIntegrityError(
                "The exact bureau catalog exceeds its configured total read limit."
            )

        attributes = self._decode_jsonl(
            self._read_descriptor(directory, manifest.attribute_file),
            BureauAttributeDefinition,
            expected_count=manifest.attribute_file.record_count,
        )
        special_values = self._decode_jsonl(
            self._read_descriptor(directory, manifest.special_value_file),
            BureauSpecialValueDefinition,
            expected_count=manifest.special_value_file.record_count,
        )
        findings: tuple[Mapping[str, Any], ...] = ()
        if manifest.reconciliation_file is not None:
            findings = self._decode_jsonl(
                self._read_descriptor(directory, manifest.reconciliation_file),
                None,
                expected_count=manifest.reconciliation_file.record_count,
            )  # type: ignore[assignment]
        validation_summary: Mapping[str, Any] = MappingProxyType({})
        if manifest.validation_file is not None:
            validation_summary = MappingProxyType(
                dict(
                    self._decode_json(
                        self._read_descriptor(directory, manifest.validation_file)
                    )
                )
            )
        for descriptor in (manifest.lookup_index_file, manifest.build_log_file):
            if descriptor is not None:
                # Verify the artifact even though runtime lookup builds its own
                # immutable indexes from validated definitions.
                self._read_descriptor(directory, descriptor)

        try:
            validate_catalog(
                manifest=manifest,
                expected_key=key,
                expected_checksum=checksum,
                attributes=attributes,  # type: ignore[arg-type]
                special_values=special_values,  # type: ignore[arg-type]
                reconciliation_findings=findings,
            )
        except (BureauCatalogValidationError, BureauMetadataNormalizationError) as exc:
            raise BureauCatalogIntegrityError(
                "The exact bureau catalog failed integrity validation."
            ) from exc

        attributes_by_code = {
            attribute.attribute_code: attribute for attribute in attributes
        }
        specials_by_key: dict[tuple[str, str], BureauSpecialValueDefinition] = {}
        for special in special_values:
            attribute = attributes_by_code[special.attribute_code]
            normalized_code = normalize_value_code(
                special.value_code,
                attribute.numeric_type,
            )
            specials_by_key[(special.attribute_code, normalized_code)] = special
        return LoadedBureauCatalog(
            manifest=manifest,
            attributes_by_code=MappingProxyType(attributes_by_code),
            special_values_by_key=MappingProxyType(specials_by_key),
            reconciliation_findings=tuple(
                MappingProxyType(dict(finding)) for finding in findings
            ),
            validation_summary=validation_summary,
        )


class BureauCatalogLoader:
    """Thread-safe, bounded LRU of already checksum-verified snapshots."""

    def __init__(self, store: BureauCatalogStore, *, max_entries: int = 4) -> None:
        if int(max_entries) <= 0:
            raise ValueError("Bureau catalog cache size must be positive.")
        self.store = store
        self.max_entries = int(max_entries)
        self._lock = threading.RLock()
        self._cache: OrderedDict[
            tuple[BureauCatalogKey, str], LoadedBureauCatalog
        ] = OrderedDict()

    def load_exact(
        self,
        key: BureauCatalogKey,
        expected_checksum: str,
    ) -> LoadedBureauCatalog:
        checksum = validate_sha256(
            expected_checksum,
            field_name="expected catalog checksum",
        )
        cache_key = (key, checksum)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached
        loaded = self.store.load_exact(key, checksum)
        with self._lock:
            existing = self._cache.get(cache_key)
            if existing is not None:
                self._cache.move_to_end(cache_key)
                return existing
            self._cache[cache_key] = loaded
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
            return loaded

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)


__all__ = [
    "BureauCatalogIntegrityError",
    "BureauCatalogLoader",
    "BureauCatalogNotFoundError",
    "BureauCatalogRootError",
    "BureauCatalogStore",
    "BureauCatalogStoreError",
    "CATALOG_MANIFEST_FILE",
    "LoadedBureauCatalog",
    "validate_external_catalog_root",
]
