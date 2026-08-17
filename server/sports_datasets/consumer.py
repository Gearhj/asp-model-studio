from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from .constants import (
    CANONICALIZATION_VERSION,
    CONTRACT_NAME,
    CONTRACT_VERSION,
    DATASET_ID,
    DATASET_VERSION_ID,
    EVIDENCE_CUTOFF,
    EXPECTED_ALLOWED_USES,
    EXPECTED_FAMILIES,
    EXPECTED_FOLDS,
    EXPECTED_LIMITATION_IDS,
    EXPECTED_METADATA_FILES,
    EXPECTED_POPULATIONS,
    EXPECTED_POPULATION_PROHIBITIONS,
    EXPECTED_PROHIBITED_USES,
    EXPECTED_RIGHTS_IDS,
    EXPECTED_TOTALS,
    LEAGUE,
    LOGICAL_PACKAGE_ROOT,
    MANIFEST_ID,
    MANIFEST_SHA,
    PACKAGE_ID,
    PA_CLASS_ORDER,
    PARTITION_AUTHORITY_SHA,
    PUBLISHER,
    PUBLISHED_AT,
    README_SHA,
    SPORT,
    SUPERSEDED_MANIFEST_PREFIX,
    VALIDATION_REPORT_SHA,
)


ProgressCallback = Callable[[Mapping[str, Any]], None]
VALIDATION_CACHE_LOCK = threading.RLock()


class ManifestValidationError(RuntimeError):
    """Fail-closed validation error containing no physical filesystem path."""

    def __init__(self, code: str, message: str, *, logical_uri: str | None = None) -> None:
        self.code = code
        self.logical_uri = logical_uri
        suffix = f" ({logical_uri})" if logical_uri else ""
        super().__init__(f"{message}{suffix}")

    def public_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.logical_uri:
            detail["logicalUri"] = self.logical_uri
        return detail


@dataclass(frozen=True)
class ValidatedPackage:
    package_root: Path
    manifest: dict[str, Any]
    schema_registry: dict[str, Any]
    source_rights: dict[str, Any]
    validation_report: dict[str, Any]
    partition_authority_sha: str
    root_identity: str
    cache_hits: int
    cache_misses: int
    validated_at: str

    @property
    def partitions(self) -> list[dict[str, Any]]:
        return self.manifest["partitions"]


_MANIFEST_KEYS = {
    "canonicalization_version",
    "contract_name",
    "contract_version",
    "data_families",
    "data_quality_evidence",
    "dataset_id",
    "dataset_version_id",
    "development_purpose",
    "evidence_cutoff",
    "identity_coverage",
    "known_limitations",
    "league",
    "manifest_id",
    "manifest_sha256",
    "package_artifacts",
    "package_id",
    "partitions",
    "populations",
    "published_at",
    "publisher",
    "seasons",
    "source_lineage",
    "source_rights_ids",
    "sport",
    "supported_consumer_range",
    "target_definitions",
    "temporal_contract",
    "totals",
}

_PARTITION_KEYS = {
    "byte_count",
    "checkpoint_lineage_id",
    "family",
    "file_sha256",
    "governance_checksum",
    "maximum_date",
    "minimum_date",
    "month",
    "original_source_logical_identity",
    "package_relative_uri",
    "partition_id",
    "physical_schema",
    "physical_schema_fingerprint",
    "row_count",
    "schema_id",
    "season",
    "source_key",
    "source_rights_ids",
    "source_version_id",
    "target_eligibility",
    "temporal_classification",
}

_FAMILY_KEYS = {
    "byte_count",
    "date_range",
    "family_id",
    "file_count",
    "known_limitations",
    "population_eligibility",
    "purpose",
    "rights_control_ids",
    "row_count",
    "schema_id",
    "source_key",
    "source_version_id",
    "target_feature_role",
    "temporal_classification",
}

_SEASON_KEYS = {
    "bullpen_appearances",
    "complete_lineup_coverage",
    "date_range",
    "games",
    "plate_appearances",
    "role",
    "season",
    "starter_targets",
    "transitions",
    "weather_coverage",
}

_POPULATION_KEYS = {
    "allowed_uses",
    "description",
    "evaluation_precedence",
    "expected_row_count",
    "population_id",
    "predicate_contract_version",
    "prohibited_uses",
    "readiness_operator_revision",
    "row_selection",
    "season_scope",
    "temporal_meaning",
}

_FOLD_KEYS = {
    "fold_id",
    "training_end",
    "training_rows",
    "training_seasons",
    "validation_end",
    "validation_rows",
    "validation_season",
    "validation_start",
}

_TARGET_KEYS = {
    "description",
    "family_ids",
    "limitations",
    "ordered_classes",
    "role",
    "target_id",
    "taxonomy_identity",
    "taxonomy_version",
}

_RIGHTS_TOP_KEYS = {
    "identity_checksum",
    "package_allowed_purposes",
    "package_controls",
    "package_prohibited_purposes",
    "policy_version",
    "record_count",
    "records",
    "schema_version",
}

_RIGHTS_RECORD_KEYS = {
    "acquisition_attribution_identity_checksum",
    "allowed_purposes",
    "attribution_text",
    "controls",
    "display_name",
    "fd1_use",
    "inventory_classification",
    "license_identity",
    "license_uri",
    "record_key",
    "required_attribution_text",
    "review_note",
    "rights_classification",
    "rights_control_id",
    "source_identifiers",
    "source_name",
    "source_releases",
    "terms_checksum",
    "terms_uri",
}

_SCHEMA_TOP_KEYS = {
    "families",
    "family_count",
    "nullability_policy",
    "partition_count",
    "physical_variant_count",
    "schema_name",
    "schema_version",
}

_SCHEMA_FAMILY_KEYS = {
    "family",
    "logical_schema_version",
    "partition_count",
    "physical_variant_count",
    "physical_variants",
}

_SCHEMA_VARIANT_KEYS = {
    "compatible_partition_count",
    "fields",
    "physical_schema_fingerprint",
    "physical_schema_version",
}

_SCHEMA_FIELD_KEYS = {
    "dtype",
    "name",
    "nullable",
    "semantic_description",
    "source_field_lineage",
    "target_feature_identity_classification",
    "temporal_risk_classification",
}


def _duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestValidationError("DUPLICATE_JSON_KEY", f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ManifestValidationError("NON_FINITE_JSON_NUMBER", f"Non-finite JSON number rejected: {value}")


def load_strict_json(path: Path, *, logical_uri: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ManifestValidationError("INVALID_UTF8", "Metadata must be strict UTF-8", logical_uri=logical_uri) from exc
    except OSError as exc:
        raise ManifestValidationError("METADATA_UNREADABLE", "Required metadata is unavailable", logical_uri=logical_uri) from exc
    try:
        value = json.loads(text, object_pairs_hook=_duplicate_guard, parse_constant=_invalid_constant)
    except ManifestValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ManifestValidationError("INVALID_JSON", "Metadata is not valid strict JSON", logical_uri=logical_uri) from exc
    if type(value) is not dict:
        raise ManifestValidationError("INVALID_JSON_ROOT", "Metadata root must be an object", logical_uri=logical_uri)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError("NON_CANONICAL_VALUE", "Value cannot be canonically serialized") from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, *, logical_uri: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(4 * 1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ManifestValidationError("FILE_UNREADABLE", "Declared package file is unreadable", logical_uri=logical_uri) from exc
    return digest.hexdigest()


def raw_absolute_path(path: Path) -> Path:
    """Return an absolute spelling without resolving a symlink/junction boundary."""

    return Path(os.path.abspath(str(path.expanduser())))


def reject_reparse_boundary(path: Path, *, label: str) -> None:
    raw = raw_absolute_path(path)
    if raw.exists() and (raw.is_symlink() or _is_reparse_point(raw)):
        raise ManifestValidationError("REPARSE_BOUNDARY_REJECTED", f"{label} may not be a symlink or junction")


def reject_reparse_chain(path: Path, *, label: str) -> None:
    """Inspect every existing component before any resolution can erase it."""

    raw = raw_absolute_path(path)
    chain: list[Path] = []
    current = raw
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    for component in reversed(chain):
        if component.exists():
            reject_reparse_boundary(component, label=label)


def filesystem_identity(path: Path, *, root: Path | None = None) -> str:
    """Hash non-public resolved path plus filesystem object identity for cache binding."""

    try:
        resolved = path.resolve(strict=True)
        file_stat = resolved.stat()
    except OSError as exc:
        raise ManifestValidationError("FILESYSTEM_IDENTITY_UNAVAILABLE", "Filesystem identity is unavailable") from exc
    payload: dict[str, Any] = {
        "resolved": str(resolved).casefold(),
        "device": int(file_stat.st_dev),
        "inode": int(file_stat.st_ino),
    }
    if root is not None:
        resolved_root = root.resolve(strict=True)
        root_stat = resolved_root.stat()
        payload.update(
            {
                "root": str(resolved_root).casefold(),
                "rootDevice": int(root_stat.st_dev),
                "rootInode": int(root_stat.st_ino),
            }
        )
    return sha256_bytes(canonical_json_bytes(payload))


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], *, code: str, label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ManifestValidationError(code, f"{label} field set differs (missing={missing}, extra={extra})")


def _require_exact_int(value: Any, expected: int, *, code: str, label: str) -> None:
    if type(value) is not int or value != expected:
        raise ManifestValidationError(code, f"{label} must equal {expected}")


def validate_package_relative_uri(value: Any) -> str:
    if type(value) is not str or not value:
        raise ManifestValidationError("UNSAFE_PACKAGE_PATH", "Package-relative URI must be a non-empty string")
    if "\\" in value or value.startswith(("/", "//")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        raise ManifestValidationError("UNSAFE_PACKAGE_PATH", "Absolute, UNC, drive, and URI paths are rejected", logical_uri=value)
    if PureWindowsPath(value).is_absolute():
        raise ManifestValidationError("UNSAFE_PACKAGE_PATH", "Windows absolute paths are rejected", logical_uri=value)
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ManifestValidationError("UNSAFE_PACKAGE_PATH", "Path traversal and non-normal paths are rejected", logical_uri=value)
    if parsed.as_posix() != value:
        raise ManifestValidationError("UNSAFE_PACKAGE_PATH", "Package-relative URI must be normalized POSIX form", logical_uri=value)
    return value


def semantic_manifest_sha(manifest: Mapping[str, Any]) -> str:
    semantic = copy.deepcopy(dict(manifest))
    for field in ("manifest_id", "manifest_sha256", "dataset_version_id", "package_id", "published_at"):
        if field not in semantic:
            raise ManifestValidationError("MISSING_IDENTITY_FIELD", f"Missing semantic identity field: {field}")
        del semantic[field]
    return sha256_bytes(canonical_json_bytes(semantic))


def partition_authority_sha(partitions: Iterable[Mapping[str, Any]]) -> str:
    projection = [copy.deepcopy(dict(item)) for item in partitions]
    projection.sort(key=lambda item: (str(item.get("package_relative_uri", "")), str(item.get("partition_id", ""))))
    return sha256_bytes(canonical_json_bytes(projection))


def _arrow_dtype(value: pa.DataType) -> str:
    if pa.types.is_null(value):
        return "Null"
    if pa.types.is_string(value) or pa.types.is_large_string(value):
        return "String"
    if pa.types.is_int64(value):
        return "Int64"
    if pa.types.is_boolean(value):
        return "Boolean"
    if pa.types.is_list(value) or pa.types.is_large_list(value):
        return f"List({_arrow_dtype(value.value_type)})"
    if pa.types.is_struct(value):
        members = ", ".join(f"'{field.name}': {_arrow_dtype(field.type)}" for field in value)
        return f"Struct({{{members}}})"
    raise ManifestValidationError("UNSUPPORTED_PARQUET_TYPE", f"Unsupported Parquet field type: {value}")


def parquet_physical_schema(path: Path, *, logical_uri: str) -> tuple[list[dict[str, str]], int]:
    try:
        parquet = pq.ParquetFile(path)
        schema = [{"name": field.name, "dtype": _arrow_dtype(field.type)} for field in parquet.schema_arrow]
        return schema, int(parquet.metadata.num_rows)
    except ManifestValidationError:
        raise
    except Exception as exc:
        raise ManifestValidationError("INVALID_PARQUET", "Parquet footer could not be validated", logical_uri=logical_uri) from exc


def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def _validate_resolved_child(root: Path, path: Path, *, logical_uri: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ManifestValidationError("MISSING_FILE", "Declared package file is missing", logical_uri=logical_uri) from exc
    if resolved == root or root not in resolved.parents:
        raise ManifestValidationError("PACKAGE_ESCAPE", "Package path escapes the approved root", logical_uri=logical_uri)
    current = path
    while current != root:
        if current.is_symlink() or _is_reparse_point(current):
            raise ManifestValidationError("LINK_ESCAPE_RISK", "Symlink or junction entries are rejected", logical_uri=logical_uri)
        current = current.parent
    try:
        if resolved.stat().st_nlink != 1:
            raise ManifestValidationError("HARDLINK_SUBSTITUTION", "Hard-linked package files are rejected", logical_uri=logical_uri)
    except OSError as exc:
        raise ManifestValidationError("FILE_UNREADABLE", "Package file metadata is unavailable", logical_uri=logical_uri) from exc
    return resolved


def _format_utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class SportsDatasetManifestConsumer:
    """Fail-closed consumer for the single approved V1 MLB FD1 adapter."""

    def __init__(self, package_root: Path, *, cache_path: Path, progress: ProgressCallback | None = None) -> None:
        raw_package_root = raw_absolute_path(package_root)
        reject_reparse_chain(raw_package_root, label="Configured package root chain")
        self.package_root = raw_package_root.resolve(strict=False)
        raw_cache_path = raw_absolute_path(cache_path)
        reject_reparse_chain(raw_cache_path, label="Configured validation cache chain")
        self.cache_path = raw_cache_path
        self.progress = progress
        resolved_cache_path = raw_cache_path.resolve(strict=False)
        if self.package_root == resolved_cache_path or self.package_root in resolved_cache_path.parents:
            raise ManifestValidationError("CACHE_INSIDE_EXCHANGE", "Validation cache must remain outside the exchange package")
        self._started = time.monotonic()
        self._rows_processed = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._root_identity: str | None = None

    def _emit(self, stage: str, *, processed: int, total: int, errors: int = 0) -> None:
        if not self.progress:
            return
        elapsed = time.monotonic() - self._started
        eta: float | None = None
        if processed > 0 and total >= processed:
            eta = elapsed * (total - processed) / processed
        self.progress(
            {
                "title": "ASP MODEL STUDIO — MLB BASELINE",
                "stage": stage,
                "elapsedSeconds": round(elapsed, 2),
                "partitionsProcessed": processed,
                "partitionsTotal": total,
                "rowsProcessed": self._rows_processed,
                "rowsTotal": EXPECTED_TOTALS["rows"],
                "errors": errors,
                "etaSeconds": None if eta is None else round(eta, 2),
            }
        )

    def _load_cache(self) -> dict[str, Any]:
        reject_reparse_chain(self.cache_path, label="Validation cache chain")
        if self.cache_path.exists():
            metadata = self.cache_path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ManifestValidationError(
                    "CACHE_LINK_REJECTED",
                    "Target-local validation cache must be a single-link regular file",
                )
        if not self.cache_path.is_file():
            return {"version": "SPORTS_DATASET_VALIDATION_CACHE_V1", "entries": {}}
        try:
            cache = load_strict_json(self.cache_path, logical_uri="target-local://sports-dataset-validation-cache")
        except ManifestValidationError:
            return {"version": "SPORTS_DATASET_VALIDATION_CACHE_V1", "entries": {}}
        if cache.get("version") != "SPORTS_DATASET_VALIDATION_CACHE_V1" or type(cache.get("entries")) is not dict:
            return {"version": "SPORTS_DATASET_VALIDATION_CACHE_V1", "entries": {}}
        return cache

    def _save_cache(self, cache: dict[str, Any]) -> None:
        temporary_name: str | None = None
        try:
            reject_reparse_chain(
                self.cache_path.parent,
                label="Validation cache parent chain",
            )
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            reject_reparse_chain(
                self.cache_path.parent,
                label="Validation cache parent chain",
            )
            if self.cache_path.exists():
                reject_reparse_chain(self.cache_path, label="Validation cache chain")
                metadata = self.cache_path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise ManifestValidationError(
                        "CACHE_LINK_REJECTED",
                        "Target-local validation cache must be a single-link regular file",
                    )
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".sports-validation-cache-",
                suffix=".tmp",
                dir=self.cache_path.parent,
                delete=False,
            ) as handle:
                temporary_name = handle.name
                handle.write(canonical_json_bytes(cache))
                handle.flush()
                os.fsync(handle.fileno())
            temporary = Path(temporary_name)
            reject_reparse_chain(temporary, label="Validation cache temporary chain")
            if temporary.lstat().st_nlink != 1:
                raise ManifestValidationError(
                    "CACHE_LINK_REJECTED",
                    "Target-local validation cache temporary must not be hard-linked",
                )
            os.replace(temporary, self.cache_path)
            temporary_name = None
            reject_reparse_chain(self.cache_path, label="Validation cache chain")
            if self.cache_path.lstat().st_nlink != 1:
                raise ManifestValidationError(
                    "CACHE_LINK_REJECTED",
                    "Target-local validation cache must not be hard-linked",
                )
        except OSError as exc:
            raise ManifestValidationError("CACHE_WRITE_FAILED", "Target-local validation cache could not be saved") from exc
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    @staticmethod
    def validate_manifest_contract(manifest: Mapping[str, Any]) -> None:
        _require_exact_keys(manifest, _MANIFEST_KEYS, code="MANIFEST_FIELDS_MISMATCH", label="Manifest")
        exact_values = {
            "contract_name": CONTRACT_NAME,
            "contract_version": CONTRACT_VERSION,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "dataset_id": DATASET_ID,
            "publisher": PUBLISHER,
            "sport": SPORT,
            "league": LEAGUE,
            "evidence_cutoff": EVIDENCE_CUTOFF,
        }
        for field, expected in exact_values.items():
            if type(manifest.get(field)) is not str or manifest[field] != expected:
                raise ManifestValidationError("CONTRACT_AUTHORITY_MISMATCH", f"{field} differs from the approved authority")
        published_at = manifest.get("published_at")
        if type(published_at) is not str or published_at != PUBLISHED_AT or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", published_at):
            raise ManifestValidationError("PUBLICATION_TIME_MISMATCH", "Published time differs from the frozen UTC adapter authority")

        claimed = manifest.get("manifest_sha256")
        if type(claimed) is not str:
            raise ManifestValidationError("INVALID_MANIFEST_SHA", "Manifest SHA must be a string")
        if claimed.startswith(SUPERSEDED_MANIFEST_PREFIX) or SUPERSEDED_MANIFEST_PREFIX in str(manifest.get("package_id", "")):
            raise ManifestValidationError("SUPERSEDED_PACKAGE", "The superseded 6c6cde package is rejected")
        digest = semantic_manifest_sha(manifest)
        if digest != MANIFEST_SHA or claimed != MANIFEST_SHA:
            raise ManifestValidationError("SEMANTIC_DIGEST_MISMATCH", "Manifest semantic SHA-256 differs from the approved authority")
        derived = {
            "manifest_id": f"sports-dataset-manifest:sha256:{digest}",
            "manifest_sha256": digest,
            "dataset_version_id": f"{manifest['dataset_id']}:sha256:{digest}",
            "package_id": f"sha256-{digest}",
        }
        for field, expected in derived.items():
            if manifest.get(field) != expected:
                raise ManifestValidationError("DERIVED_ID_MISMATCH", f"Derived identity differs: {field}")
        if derived != {
            "manifest_id": MANIFEST_ID,
            "manifest_sha256": MANIFEST_SHA,
            "dataset_version_id": DATASET_VERSION_ID,
            "package_id": PACKAGE_ID,
        }:
            raise ManifestValidationError("DERIVED_ID_AUTHORITY_MISMATCH", "Derived identities are not the approved identities")

        totals = manifest.get("totals")
        if type(totals) is not dict:
            raise ManifestValidationError("TOTALS_MISSING", "Manifest totals must be an object")
        _require_exact_keys(totals, {"parquet_bytes", "parquet_files", "rows"}, code="TOTAL_FIELDS_MISMATCH", label="Totals")
        _require_exact_int(totals.get("parquet_files"), EXPECTED_TOTALS["parquet_files"], code="PARQUET_COUNT_MISMATCH", label="Parquet files")
        _require_exact_int(totals.get("rows"), EXPECTED_TOTALS["rows"], code="ROW_COUNT_MISMATCH", label="Rows")
        _require_exact_int(totals.get("parquet_bytes"), EXPECTED_TOTALS["parquet_bytes"], code="BYTE_COUNT_MISMATCH", label="Parquet bytes")

        partitions = manifest.get("partitions")
        if type(partitions) is not list or len(partitions) != EXPECTED_TOTALS["parquet_files"]:
            raise ManifestValidationError("PARTITION_COUNT_MISMATCH", "Manifest must declare exactly 329 partitions")
        ids: set[str] = set()
        uris: set[str] = set()
        for partition in partitions:
            if type(partition) is not dict:
                raise ManifestValidationError("INVALID_PARTITION", "Partition entries must be objects")
            _require_exact_keys(partition, _PARTITION_KEYS, code="PARTITION_FIELDS_MISMATCH", label="Partition")
            uri = validate_package_relative_uri(partition.get("package_relative_uri"))
            if not uri.endswith(".parquet") or not uri.startswith("parquet/"):
                raise ManifestValidationError("INVALID_PARTITION_URI", "Partition must be a Parquet URI below parquet/", logical_uri=uri)
            partition_id = partition.get("partition_id")
            if type(partition_id) is not str or not partition_id or partition_id in ids:
                raise ManifestValidationError("DUPLICATE_PARTITION_ID", "Partition identities must be unique", logical_uri=uri)
            if uri in uris:
                raise ManifestValidationError("DUPLICATE_PARTITION_URI", "Partition URIs must be unique", logical_uri=uri)
            ids.add(partition_id)
            uris.add(uri)
            if partition.get("family") not in EXPECTED_FAMILIES:
                raise ManifestValidationError("UNKNOWN_FAMILY", "Partition family is not approved", logical_uri=uri)
            for field in ("row_count", "byte_count", "season"):
                if type(partition.get(field)) is not int:
                    raise ManifestValidationError("PARTITION_TYPE_MISMATCH", f"Partition {field} must be an integer", logical_uri=uri)
            if partition["season"] not in {2021, 2022, 2023, 2024, 2025}:
                raise ManifestValidationError("SEASON_MISMATCH", "Partition season is outside 2021–2025", logical_uri=uri)
            if partition.get("month") is not None and (type(partition["month"]) is not int or not 1 <= partition["month"] <= 12):
                raise ManifestValidationError("MONTH_MISMATCH", "Partition month is invalid", logical_uri=uri)
            physical_schema = partition.get("physical_schema")
            if type(physical_schema) is not list or not physical_schema:
                raise ManifestValidationError("PHYSICAL_SCHEMA_MISSING", "Partition physical schema is required", logical_uri=uri)
            for field in physical_schema:
                if type(field) is not dict or set(field) != {"name", "dtype"} or not all(type(value) is str for value in field.values()):
                    raise ManifestValidationError("PHYSICAL_SCHEMA_FIELDS_MISMATCH", "Physical schema fields must contain exact name and dtype", logical_uri=uri)
            fingerprint = sha256_bytes(canonical_json_bytes(physical_schema))
            if fingerprint != partition.get("physical_schema_fingerprint"):
                raise ManifestValidationError("SCHEMA_FINGERPRINT_MISMATCH", "Partition physical-schema fingerprint differs", logical_uri=uri)

        authority = partition_authority_sha(partitions)
        if authority != PARTITION_AUTHORITY_SHA:
            raise ManifestValidationError("PARTITION_AUTHORITY_MISMATCH", "Partition authority SHA-256 differs from the approved anchor")

        families = manifest.get("data_families")
        if type(families) is not list or len(families) != len(EXPECTED_FAMILIES):
            raise ManifestValidationError("FAMILY_COUNT_MISMATCH", "Manifest must contain ten logical families")
        for family in families:
            if type(family) is not dict:
                raise ManifestValidationError("INVALID_FAMILY", "Family entries must be objects")
            _require_exact_keys(family, _FAMILY_KEYS, code="FAMILY_FIELDS_MISMATCH", label="Family")
        if tuple(item.get("family_id") for item in families) != EXPECTED_FAMILIES:
            raise ManifestValidationError("FAMILY_AUTHORITY_MISMATCH", "Logical family order or identities differ")

        seasons = manifest.get("seasons")
        if type(seasons) is not list or len(seasons) != 5:
            raise ManifestValidationError("SEASON_COVERAGE_MISMATCH", "Exactly five seasons are required")
        for season in seasons:
            if type(season) is not dict:
                raise ManifestValidationError("INVALID_SEASON", "Season entries must be objects")
            _require_exact_keys(season, _SEASON_KEYS, code="SEASON_FIELDS_MISMATCH", label="Season")
        if [item.get("season") for item in seasons] != [2021, 2022, 2023, 2024, 2025]:
            raise ManifestValidationError("SEASON_ORDER_MISMATCH", "Season order must remain 2021–2025")

        populations = manifest.get("populations")
        if type(populations) is not list or len(populations) != 3:
            raise ManifestValidationError("POPULATION_COUNT_MISMATCH", "Exactly three populations are required")
        found_populations: dict[str, int] = {}
        for population in populations:
            if type(population) is not dict:
                raise ManifestValidationError("INVALID_POPULATION", "Population entries must be objects")
            _require_exact_keys(population, _POPULATION_KEYS, code="POPULATION_FIELDS_MISMATCH", label="Population")
            if tuple(population.get("allowed_uses") or ()) != EXPECTED_ALLOWED_USES:
                raise ManifestValidationError("POPULATION_RIGHTS_MISMATCH", "Population allowed uses differ")
            population_id = str(population.get("population_id"))
            if tuple(population.get("prohibited_uses") or ()) != EXPECTED_POPULATION_PROHIBITIONS.get(population_id):
                raise ManifestValidationError("POPULATION_RIGHTS_MISMATCH", "Population prohibitions differ")
            found_populations[population_id] = population.get("expected_row_count")
        if found_populations != EXPECTED_POPULATIONS or sum(found_populations.values()) != EXPECTED_TOTALS["rows"]:
            raise ManifestValidationError("POPULATION_RECONCILIATION_FAILED", "Population counts do not reconcile")

        temporal = manifest.get("temporal_contract")
        if type(temporal) is not dict or type(temporal.get("folds")) is not list:
            raise ManifestValidationError("TEMPORAL_CONTRACT_MISSING", "Temporal folds are required")
        folds: dict[str, dict[str, Any]] = {}
        for fold in temporal["folds"]:
            if type(fold) is not dict:
                raise ManifestValidationError("INVALID_FOLD", "Temporal fold entries must be objects")
            _require_exact_keys(fold, _FOLD_KEYS, code="FOLD_FIELDS_MISMATCH", label="Temporal fold")
            folds[str(fold.get("fold_id"))] = fold
        if set(folds) != set(EXPECTED_FOLDS):
            raise ManifestValidationError("FOLD_ID_MISMATCH", "Temporal fold identities differ")
        for fold_id, expected in EXPECTED_FOLDS.items():
            fold = folds[fold_id]
            for field, value in expected.items():
                if fold.get(field) != value:
                    raise ManifestValidationError("FOLD_COUNT_MISMATCH", f"Temporal fold differs: {fold_id}.{field}")
        if temporal.get("untouched_final_holdout_claimed") is not False:
            raise ManifestValidationError("HOLDOUT_CLAIM_MISMATCH", "2025 must not be described as an untouched holdout")

        targets = manifest.get("target_definitions")
        if type(targets) is not list:
            raise ManifestValidationError("TARGETS_MISSING", "Target definitions are required")
        for target in targets:
            if type(target) is not dict:
                raise ManifestValidationError("INVALID_TARGET", "Target entries must be objects")
            _require_exact_keys(target, _TARGET_KEYS, code="TARGET_FIELDS_MISMATCH", label="Target")
        pa_target = next((item for item in targets if item.get("target_id") == "plate_appearance_outcome"), None)
        if pa_target is None or tuple(pa_target.get("ordered_classes") or ()) != PA_CLASS_ORDER:
            raise ManifestValidationError("CLASS_ORDER_MISMATCH", "Plate-appearance probability class order differs")

        limitations = manifest.get("known_limitations")
        if type(limitations) is not list:
            raise ManifestValidationError("LIMITATIONS_MISSING", "Known limitations are required")
        for limitation in limitations:
            if type(limitation) is not dict or set(limitation) != {"description", "limitation_id", "scope"}:
                raise ManifestValidationError("LIMITATION_FIELDS_MISMATCH", "Limitation fields differ")
        if tuple(item.get("limitation_id") for item in limitations) != EXPECTED_LIMITATION_IDS:
            raise ManifestValidationError("LIMITATION_MISMATCH", "Known limitations differ from the approved authority")
        if tuple(manifest.get("source_rights_ids") or ()) != EXPECTED_RIGHTS_IDS:
            raise ManifestValidationError("RIGHTS_REFERENCE_MISMATCH", "Manifest source-right references differ")

    @staticmethod
    def validate_schema_registry(registry: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        _require_exact_keys(registry, _SCHEMA_TOP_KEYS, code="SCHEMA_REGISTRY_FIELDS_MISMATCH", label="Schema registry")
        expected_scalars = {
            "schema_name": "SPORTS_DATASET_SCHEMA_REGISTRY_V1",
            "schema_version": "sports_dataset_schema_registry_v1",
            "family_count": EXPECTED_TOTALS["logical_families"],
            "partition_count": EXPECTED_TOTALS["parquet_files"],
            "physical_variant_count": EXPECTED_TOTALS["physical_variants"],
            "nullability_policy": "CONSERVATIVE_ALL_PARQUET_FIELDS_NULLABLE",
        }
        for field, expected in expected_scalars.items():
            if registry.get(field) != expected or type(registry.get(field)) is not type(expected):
                raise ManifestValidationError("SCHEMA_REGISTRY_AUTHORITY_MISMATCH", f"Schema registry differs: {field}")
        families = registry.get("families")
        if type(families) is not list:
            raise ManifestValidationError("SCHEMA_FAMILIES_MISSING", "Schema families are required")
        family_map: dict[str, dict[str, list[dict[str, str]]]] = {}
        variant_total = 0
        partition_total = 0
        for family in families:
            if type(family) is not dict:
                raise ManifestValidationError("INVALID_SCHEMA_FAMILY", "Schema family must be an object")
            _require_exact_keys(family, _SCHEMA_FAMILY_KEYS, code="SCHEMA_FAMILY_FIELDS_MISMATCH", label="Schema family")
            family_name = family.get("family")
            if family_name not in EXPECTED_FAMILIES or family_name in family_map:
                raise ManifestValidationError("SCHEMA_FAMILY_MISMATCH", "Schema family identities differ")
            variants = family.get("physical_variants")
            if type(variants) is not list or len(variants) != family.get("physical_variant_count"):
                raise ManifestValidationError("SCHEMA_VARIANT_COUNT_MISMATCH", "Physical variant counts differ")
            variant_map: dict[str, list[dict[str, str]]] = {}
            compatible_total = 0
            for variant in variants:
                if type(variant) is not dict:
                    raise ManifestValidationError("INVALID_SCHEMA_VARIANT", "Schema variants must be objects")
                _require_exact_keys(variant, _SCHEMA_VARIANT_KEYS, code="SCHEMA_VARIANT_FIELDS_MISMATCH", label="Schema variant")
                fields = variant.get("fields")
                if type(fields) is not list or not fields:
                    raise ManifestValidationError("SCHEMA_FIELDS_MISSING", "Schema variant fields are required")
                projection: list[dict[str, str]] = []
                for field in fields:
                    if type(field) is not dict:
                        raise ManifestValidationError("INVALID_SCHEMA_FIELD", "Schema fields must be objects")
                    _require_exact_keys(field, _SCHEMA_FIELD_KEYS, code="SCHEMA_FIELD_FIELDS_MISMATCH", label="Schema field")
                    if type(field.get("name")) is not str or type(field.get("dtype")) is not str or type(field.get("nullable")) is not bool:
                        raise ManifestValidationError("SCHEMA_FIELD_TYPE_MISMATCH", "Schema field types differ")
                    projection.append({"name": field["name"], "dtype": field["dtype"]})
                fingerprint = sha256_bytes(canonical_json_bytes(projection))
                if fingerprint != variant.get("physical_schema_fingerprint") or fingerprint in variant_map:
                    raise ManifestValidationError("SCHEMA_VARIANT_FINGERPRINT_MISMATCH", "Schema variant fingerprint differs or is duplicated")
                variant_map[fingerprint] = projection
                count = variant.get("compatible_partition_count")
                if type(count) is not int or count <= 0:
                    raise ManifestValidationError("SCHEMA_COMPATIBILITY_COUNT_MISMATCH", "Compatible partition count is invalid")
                compatible_total += count
            if compatible_total != family.get("partition_count"):
                raise ManifestValidationError("SCHEMA_PARTITION_RECONCILIATION_FAILED", "Schema compatible partitions do not reconcile")
            family_map[family_name] = variant_map
            variant_total += len(variants)
            partition_total += family["partition_count"]
        if tuple(family_map) != EXPECTED_FAMILIES or variant_total != EXPECTED_TOTALS["physical_variants"] or partition_total != EXPECTED_TOTALS["parquet_files"]:
            raise ManifestValidationError("SCHEMA_REGISTRY_RECONCILIATION_FAILED", "Schema registry totals do not reconcile")
        for partition in manifest["partitions"]:
            expected_schema = family_map.get(partition["family"], {}).get(partition["physical_schema_fingerprint"])
            if expected_schema != partition["physical_schema"]:
                raise ManifestValidationError("PARTITION_SCHEMA_NOT_REGISTERED", "Partition physical schema is not registered", logical_uri=partition["package_relative_uri"])

    @staticmethod
    def validate_source_rights(rights: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        _require_exact_keys(rights, _RIGHTS_TOP_KEYS, code="RIGHTS_FIELDS_MISMATCH", label="Source rights")
        if rights.get("schema_version") != "SPORTS_DATASET_SOURCE_RIGHTS_V1" or rights.get("record_count") != 6:
            raise ManifestValidationError("RIGHTS_CONTRACT_MISMATCH", "Source-right contract differs")
        if tuple(rights.get("package_allowed_purposes") or ()) != EXPECTED_ALLOWED_USES:
            raise ManifestValidationError("RIGHTS_ALLOWED_USE_MISMATCH", "Package allowed uses differ")
        if tuple(rights.get("package_prohibited_purposes") or ()) != EXPECTED_PROHIBITED_USES:
            raise ManifestValidationError("RIGHTS_PROHIBITION_MISMATCH", "Package prohibited uses differ")
        controls = rights.get("package_controls")
        if type(controls) is not dict or controls.get("public_redistribution_authorized") is not False or controls.get("raw_redistribution_authorized") is not False or controls.get("unreviewed_commercial_redistribution_authorized") is not False:
            raise ManifestValidationError("RIGHTS_CONTROL_MISMATCH", "Source-right redistribution controls differ")
        records = rights.get("records")
        if type(records) is not list or len(records) != 6:
            raise ManifestValidationError("RIGHTS_RECORD_COUNT_MISMATCH", "Exactly six source-right records are required")
        for record in records:
            if type(record) is not dict:
                raise ManifestValidationError("INVALID_RIGHTS_RECORD", "Source-right records must be objects")
            if set(record) not in (_RIGHTS_RECORD_KEYS, _RIGHTS_RECORD_KEYS - {"source_identifiers"}):
                _require_exact_keys(record, _RIGHTS_RECORD_KEYS, code="RIGHTS_RECORD_FIELDS_MISMATCH", label="Source-right record")
        ids = tuple(record.get("rights_control_id") for record in records)
        if ids != EXPECTED_RIGHTS_IDS or ids != tuple(manifest.get("source_rights_ids") or ()):
            raise ManifestValidationError("RIGHTS_REFERENCE_MISMATCH", "Source-right identities differ")
        status_by_id = {record["rights_control_id"]: (record.get("fd1_use") or {}).get("status") for record in records}
        if status_by_id.get("NOAA_NCEI_LCDV2_ZERO_USE") != "ZERO_USE_NO_DOWNLOAD" or status_by_id.get("OPEN_METEO_FREE_HOSTED_ZERO_USE") != "ZERO_USE_NO_REQUEST":
            raise ManifestValidationError("ZERO_USE_RIGHTS_MISMATCH", "Zero-use provider controls differ")

    def _validate_metadata_bindings(
        self,
        manifest: dict[str, Any],
        schema_registry: dict[str, Any],
        source_rights: dict[str, Any],
        validation_report: dict[str, Any],
    ) -> None:
        artifacts = manifest.get("package_artifacts")
        if type(artifacts) is not list or len(artifacts) != 3:
            raise ManifestValidationError("PACKAGE_ARTIFACT_COUNT_MISMATCH", "Exactly three semantic package artifacts are required")
        expected_artifact_keys = {"byte_count", "logical_uri", "semantic_digest_member", "sha256"}
        artifact_names: list[str] = []
        for artifact in artifacts:
            if type(artifact) is not dict:
                raise ManifestValidationError("INVALID_PACKAGE_ARTIFACT", "Package artifacts must be objects")
            _require_exact_keys(artifact, expected_artifact_keys, code="PACKAGE_ARTIFACT_FIELDS_MISMATCH", label="Package artifact")
            uri = validate_package_relative_uri(artifact.get("logical_uri"))
            if uri not in {"attribution.md", "schema-registry.json", "source-rights.json"} or artifact.get("semantic_digest_member") is not True:
                raise ManifestValidationError("PACKAGE_ARTIFACT_AUTHORITY_MISMATCH", "Semantic package artifact differs", logical_uri=uri)
            path = _validate_resolved_child(self.package_root, self.package_root / PurePosixPath(uri), logical_uri=uri)
            stat_result = path.stat()
            if stat_result.st_size != artifact.get("byte_count") or sha256_file(path, logical_uri=uri) != artifact.get("sha256"):
                raise ManifestValidationError("PACKAGE_ARTIFACT_HASH_MISMATCH", "Semantic package artifact hash or bytes differ", logical_uri=uri)
            artifact_names.append(uri)
        if artifact_names != ["attribution.md", "schema-registry.json", "source-rights.json"]:
            raise ManifestValidationError("PACKAGE_ARTIFACT_ORDER_MISMATCH", "Semantic package artifact order differs")

        readme_path = _validate_resolved_child(self.package_root, self.package_root / "README.md", logical_uri="README.md")
        report_path = _validate_resolved_child(self.package_root, self.package_root / "validation-report.json", logical_uri="validation-report.json")
        if sha256_file(readme_path, logical_uri="README.md") != README_SHA:
            raise ManifestValidationError("README_HASH_MISMATCH", "README checksum differs", logical_uri="README.md")
        report_sha = sha256_file(report_path, logical_uri="validation-report.json")
        if report_sha != VALIDATION_REPORT_SHA:
            raise ManifestValidationError("VALIDATION_REPORT_HASH_MISMATCH", "Validation report checksum differs", logical_uri="validation-report.json")
        try:
            readme_text = readme_path.read_bytes().decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            raise ManifestValidationError("README_INVALID", "README must be readable strict UTF-8", logical_uri="README.md") from exc
        match = re.search(r"validation-report-sha256:\s*`([0-9a-f]{64})`", readme_text)
        if not match or match.group(1) != report_sha:
            raise ManifestValidationError("README_REPORT_BINDING_MISMATCH", "README does not bind the validation-report checksum")
        if validation_report.get("status") != "VALID" or validation_report.get("manifest_sha256") != MANIFEST_SHA or validation_report.get("manifest_id") != MANIFEST_ID or validation_report.get("package_id") != PACKAGE_ID:
            raise ManifestValidationError("VALIDATION_REPORT_IDENTITY_MISMATCH", "Validation report identity or status differs")
        if validation_report.get("provider_network_calls") != 0 or validation_report.get("database_accessed") is not False or validation_report.get("source_runtime_accessed") is not False:
            raise ManifestValidationError("VALIDATION_REPORT_BOUNDARY_MISMATCH", "Validation report system-boundary evidence differs")
        if validation_report.get("package_total_files") != EXPECTED_TOTALS["package_files"] or validation_report.get("parquet_files_checked") != EXPECTED_TOTALS["parquet_files"] or validation_report.get("population_counts") != EXPECTED_POPULATIONS:
            raise ManifestValidationError("VALIDATION_REPORT_TOTAL_MISMATCH", "Validation report totals differ")
        self.validate_schema_registry(schema_registry, manifest)
        self.validate_source_rights(source_rights, manifest)

    def _inventory(self, declared_uris: set[str]) -> dict[str, Path]:
        if not self.package_root.is_dir():
            raise ManifestValidationError("PACKAGE_UNAVAILABLE", "Approved exchange package is not available")
        root = self.package_root.resolve(strict=True)
        found: dict[str, Path] = {}
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in list(directories):
                child = current_path / name
                relative = child.relative_to(root).as_posix()
                if child.is_symlink() or _is_reparse_point(child):
                    raise ManifestValidationError("LINK_ESCAPE_RISK", "Symlink or junction directories are rejected", logical_uri=relative)
            for name in files:
                child = current_path / name
                relative = child.relative_to(root).as_posix()
                validate_package_relative_uri(relative)
                found[relative] = _validate_resolved_child(root, child, logical_uri=relative)
        expected = declared_uris | set(EXPECTED_METADATA_FILES)
        if len(found) != EXPECTED_TOTALS["package_files"] or set(found) != expected:
            missing = sorted(expected - set(found))[:5]
            undeclared = sorted(set(found) - expected)[:5]
            raise ManifestValidationError("FILE_INVENTORY_MISMATCH", f"Package inventory differs (missing={missing}, undeclared={undeclared})")
        return found

    def _validate_partition(
        self,
        partition: Mapping[str, Any],
        path: Path,
        cache: dict[str, Any],
    ) -> None:
        uri = str(partition["package_relative_uri"])
        stat_result = path.stat()
        expected_binding = {
            "manifestSha": MANIFEST_SHA,
            "logicalUri": uri,
            "size": stat_result.st_size,
            "mtimeNs": stat_result.st_mtime_ns,
            "fileSha": partition["file_sha256"],
            "schemaFingerprint": partition["physical_schema_fingerprint"],
            "rowCount": partition["row_count"],
            "rootIdentity": self._root_identity,
            "fileIdentity": filesystem_identity(path, root=self.package_root),
        }
        cached = cache["entries"].get(uri)
        if cached == expected_binding:
            self._cache_hits += 1
            self._rows_processed += int(partition["row_count"])
            return
        self._cache_misses += 1
        if stat_result.st_size != partition["byte_count"]:
            raise ManifestValidationError("PARTITION_BYTE_COUNT_MISMATCH", "Partition byte count differs", logical_uri=uri)
        if sha256_file(path, logical_uri=uri) != partition["file_sha256"]:
            raise ManifestValidationError("PARTITION_HASH_MISMATCH", "Partition SHA-256 differs", logical_uri=uri)
        physical_schema, row_count = parquet_physical_schema(path, logical_uri=uri)
        if row_count != partition["row_count"]:
            raise ManifestValidationError("PARTITION_ROW_COUNT_MISMATCH", "Parquet footer row count differs", logical_uri=uri)
        if physical_schema != partition["physical_schema"]:
            raise ManifestValidationError("PARTITION_SCHEMA_MISMATCH", "Ordered Parquet physical schema differs", logical_uri=uri)
        fingerprint = sha256_bytes(canonical_json_bytes(physical_schema))
        if fingerprint != partition["physical_schema_fingerprint"]:
            raise ManifestValidationError("PARTITION_SCHEMA_FINGERPRINT_MISMATCH", "Parquet schema fingerprint differs", logical_uri=uri)
        cache["entries"][uri] = expected_binding
        self._rows_processed += row_count

    def _validate_partitions_with_cache(
        self,
        partitions: list[dict[str, Any]],
        inventory: Mapping[str, Path],
        declared: set[str],
    ) -> str:
        with VALIDATION_CACHE_LOCK:
            cache = self._load_cache()
            cache["manifestSha"] = MANIFEST_SHA
            cache["partitionAuthoritySha"] = PARTITION_AUTHORITY_SHA
            cache["rootIdentity"] = self._root_identity
            cache["entries"] = {key: value for key, value in cache["entries"].items() if key in declared}
            for index, partition in enumerate(partitions, start=1):
                self._validate_partition(partition, inventory[partition["package_relative_uri"]], cache)
                if index == 1 or index % 25 == 0 or index == len(partitions):
                    self._emit("VALIDATING_PACKAGE_FILES", processed=index, total=len(partitions))
            validated_at = _format_utc_now()
            cache["validatedAt"] = validated_at
            self._save_cache(cache)
            return validated_at

    @staticmethod
    def _reconcile(manifest: Mapping[str, Any], validation_report: Mapping[str, Any]) -> None:
        partitions = manifest["partitions"]
        if sum(item["row_count"] for item in partitions) != EXPECTED_TOTALS["rows"] or sum(item["byte_count"] for item in partitions) != EXPECTED_TOTALS["parquet_bytes"]:
            raise ManifestValidationError("PARTITION_TOTAL_RECONCILIATION_FAILED", "Partition totals do not reconcile")
        family_rows: Counter[str] = Counter()
        family_bytes: Counter[str] = Counter()
        family_files: Counter[str] = Counter()
        season_rows: Counter[int] = Counter()
        season_bytes: Counter[int] = Counter()
        season_files: Counter[int] = Counter()
        for item in partitions:
            family_rows[item["family"]] += item["row_count"]
            family_bytes[item["family"]] += item["byte_count"]
            family_files[item["family"]] += 1
            season_rows[item["season"]] += item["row_count"]
            season_bytes[item["season"]] += item["byte_count"]
            season_files[item["season"]] += 1
        manifest_families = {item["family_id"]: item for item in manifest["data_families"]}
        report_families = validation_report.get("family_totals") or {}
        for family in EXPECTED_FAMILIES:
            expected = {
                "files": family_files[family],
                "parquet_bytes": family_bytes[family],
                "rows": family_rows[family],
            }
            item = manifest_families.get(family) or {}
            if item.get("file_count") != expected["files"] or item.get("byte_count") != expected["parquet_bytes"] or item.get("row_count") != expected["rows"] or report_families.get(family) != expected:
                raise ManifestValidationError("FAMILY_TOTAL_RECONCILIATION_FAILED", f"Family totals do not reconcile: {family}")
        report_seasons = validation_report.get("season_totals") or {}
        for season in range(2021, 2026):
            expected = {"files": season_files[season], "parquet_bytes": season_bytes[season], "rows": season_rows[season]}
            if report_seasons.get(str(season)) != expected:
                raise ManifestValidationError("SEASON_TOTAL_RECONCILIATION_FAILED", f"Season totals do not reconcile: {season}")
        season_pa = {item["season"]: item["plate_appearances"] for item in manifest["seasons"]}
        if season_pa[2023] != 184_104 or season_pa[2024] != 182_449 or season_pa[2025] != 182_926:
            raise ManifestValidationError("TEMPORAL_FOLD_COUNT_MISMATCH", "Plate-appearance season counts differ from frozen folds")

    def validate(self) -> ValidatedPackage:
        self._emit("VALIDATING_MANIFEST", processed=0, total=EXPECTED_TOTALS["parquet_files"])
        reject_reparse_chain(raw_absolute_path(self.package_root), label="Configured package root chain")
        self._root_identity = filesystem_identity(self.package_root)
        manifest = load_strict_json(self.package_root / "sports-dataset-manifest.json", logical_uri="sports-dataset-manifest.json")
        self.validate_manifest_contract(manifest)
        schema_registry = load_strict_json(self.package_root / "schema-registry.json", logical_uri="schema-registry.json")
        source_rights = load_strict_json(self.package_root / "source-rights.json", logical_uri="source-rights.json")
        validation_report = load_strict_json(self.package_root / "validation-report.json", logical_uri="validation-report.json")
        self._validate_metadata_bindings(manifest, schema_registry, source_rights, validation_report)
        declared = {str(item["package_relative_uri"]) for item in manifest["partitions"]}
        inventory = self._inventory(declared)
        partitions = manifest["partitions"]
        validated_at = self._validate_partitions_with_cache(partitions, inventory, declared)
        self._reconcile(manifest, validation_report)
        self._emit("PACKAGE_VALID", processed=len(partitions), total=len(partitions))
        return ValidatedPackage(
            package_root=self.package_root,
            manifest=manifest,
            schema_registry=schema_registry,
            source_rights=source_rights,
            validation_report=validation_report,
            partition_authority_sha=PARTITION_AUTHORITY_SHA,
            root_identity=self._root_identity,
            cache_hits=self._cache_hits,
            cache_misses=self._cache_misses,
            validated_at=validated_at,
        )
