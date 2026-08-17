from __future__ import annotations

import math
import os
import stat
import threading
import uuid
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .constants import EXPECTED_FAMILIES, LOGICAL_PACKAGE_ROOT, MANIFEST_SHA, PACKAGE_RELATIVE_ROOT, PARTITION_AUTHORITY_SHA, PA_CLASS_ORDER
from .consumer import (
    ManifestValidationError,
    VALIDATION_CACHE_LOCK,
    canonical_json_bytes,
    filesystem_identity,
    load_strict_json,
    parquet_physical_schema,
    raw_absolute_path,
    reject_reparse_boundary,
    reject_reparse_chain,
    sha256_bytes,
    sha256_file,
    validate_package_relative_uri,
)
from .registry import SportsDatasetRegistry


MAX_PREVIEW_ROWS = min(max(int(os.getenv("ASP_SPORTS_PREVIEW_ROW_LIMIT", "200")), 1), 1000)
MAX_QUERY_ROWS = min(max(int(os.getenv("ASP_SPORTS_QUERY_ROW_LIMIT", "1000000")), 1), 5_000_000)
MAX_QUERY_FIELDS = min(max(int(os.getenv("ASP_SPORTS_QUERY_FIELD_LIMIT", "64")), 1), 256)
BATCH_ROWS = min(max(int(os.getenv("ASP_SPORTS_QUERY_BATCH_ROWS", "32768")), 1024), 131_072)
MAX_QUERY_MEMORY_BYTES = min(
    max(int(os.getenv("ASP_SPORTS_QUERY_MEMORY_BYTES", str(128 * 1024 * 1024))), 16 * 1024 * 1024),
    512 * 1024 * 1024,
)
MAX_AGGREGATE_CATEGORIES = min(max(int(os.getenv("ASP_SPORTS_AGGREGATE_CATEGORY_LIMIT", "10000")), 8), 100_000)
MAX_QUERY_OUTPUT_BYTES = min(
    max(int(os.getenv("ASP_SPORTS_QUERY_OUTPUT_BYTES", str(4 * 1024 * 1024))), 64 * 1024),
    32 * 1024 * 1024,
)


class SportsDataAccessError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class QueryCancellationRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, tuple[threading.Event, str]] = {}

    def begin(self, query_id: str, *, user_id: str) -> threading.Event:
        with self._lock:
            if query_id in self._events:
                raise SportsDataAccessError("QUERY_ID_IN_USE", "Query identity is already active", status_code=409)
            event = threading.Event()
            self._events[query_id] = (event, user_id)
            return event

    def cancel(self, query_id: str, *, user_id: str, is_admin: bool = False) -> bool:
        with self._lock:
            handle = self._events.get(query_id)
            if handle is None:
                return False
            event, owner_user_id = handle
            if owner_user_id != user_id and not is_admin:
                raise SportsDataAccessError("QUERY_CANCELLATION_FORBIDDEN", "Only the query owner or an administrator may cancel this query", status_code=403)
            event.set()
            return True

    def finish(self, query_id: str) -> None:
        with self._lock:
            self._events.pop(query_id, None)


CANCELLATIONS = QueryCancellationRegistry()


def validate_season_scope(seasons: Sequence[int]) -> tuple[int, ...]:
    selected = tuple(seasons)
    if len(selected) > 5 or len(selected) != len(set(selected)):
        raise SportsDataAccessError("INVALID_SEASON_SCOPE", "Season scope must contain at most five unique seasons")
    if any(type(season) is not int or season not in {2021, 2022, 2023, 2024, 2025} for season in selected):
        raise SportsDataAccessError("INVALID_SEASON_SCOPE", "Season scope is limited to registered seasons 2021–2025")
    return selected


def approved_package_root(exchange_root: Path) -> Path:
    raw_exchange_root = raw_absolute_path(exchange_root)
    reject_reparse_chain(raw_exchange_root, label="Configured exchange root chain")
    package_root = raw_exchange_root
    for component in PACKAGE_RELATIVE_ROOT.parts:
        package_root = package_root / component
        reject_reparse_boundary(package_root, label=f"Configured exchange component {component}")
    return package_root


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "as_py"):
        return _json_safe(value.as_py())
    return str(value)


class SportsDatasetAccessService:
    """Bounded lazy Parquet reads through registered logical identities only."""

    def __init__(
        self,
        registry: SportsDatasetRegistry,
        *,
        exchange_root: Path,
        validation_cache_path: Path,
        cancellation_registry: QueryCancellationRegistry = CANCELLATIONS,
    ) -> None:
        self.registry = registry
        try:
            raw_package_root = approved_package_root(exchange_root)
            self.package_root = raw_package_root.resolve(strict=False)
            self.root_identity = filesystem_identity(self.package_root)
        except ManifestValidationError as exc:
            raise SportsDataAccessError(exc.code, str(exc), status_code=409) from exc
        self.validation_cache_path = validation_cache_path.expanduser().resolve(strict=False)
        if self.package_root == self.validation_cache_path or self.package_root in self.validation_cache_path.parents:
            raise SportsDataAccessError("CACHE_INSIDE_EXCHANGE", "Validation cache must remain outside the exchange package", status_code=500)
        self._cache_lock = VALIDATION_CACHE_LOCK
        self.cancellations = cancellation_registry

    def _registration(self, registration_id: str) -> dict[str, Any]:
        registration = self.registry.get(registration_id)
        if not registration or registration.get("active") != 1 or registration.get("validation_status") != "VALID":
            raise SportsDataAccessError("REGISTRATION_NOT_FOUND", "Active validated dataset registration was not found", status_code=404)
        if registration.get("logical_package_root") != LOGICAL_PACKAGE_ROOT:
            raise SportsDataAccessError("REGISTRATION_ROOT_MISMATCH", "Dataset logical root is not approved", status_code=409)
        registered_root_identity = (registration.get("metadata_json") or {}).get("validationRootIdentity")
        if registered_root_identity != self.root_identity:
            raise SportsDataAccessError("ROOT_IDENTITY_MISMATCH", "Configured exchange root differs from the validated registered root", status_code=409)
        return registration

    def _load_validation_cache(self) -> dict[str, Any]:
        try:
            cache = load_strict_json(self.validation_cache_path, logical_uri="target-local://sports-dataset-validation-cache")
        except ManifestValidationError as exc:
            raise SportsDataAccessError("VALIDATION_CACHE_UNAVAILABLE", "Bound validation cache is unavailable", status_code=409) from exc
        if (
            cache.get("version") != "SPORTS_DATASET_VALIDATION_CACHE_V1"
            or cache.get("manifestSha") != MANIFEST_SHA
            or cache.get("partitionAuthoritySha") != PARTITION_AUTHORITY_SHA
            or cache.get("rootIdentity") != self.root_identity
            or type(cache.get("entries")) is not dict
        ):
            raise SportsDataAccessError("VALIDATION_CACHE_IDENTITY_MISMATCH", "Validation cache does not match the registered exchange root", status_code=409)
        return cache

    def _save_validation_cache(self, cache: Mapping[str, Any]) -> None:
        try:
            temporary = self.validation_cache_path.with_suffix(self.validation_cache_path.suffix + ".tmp")
            temporary.write_bytes(canonical_json_bytes(cache))
            os.replace(temporary, self.validation_cache_path)
        except OSError as exc:
            raise SportsDataAccessError("VALIDATION_CACHE_WRITE_FAILED", "Target-local validation cache could not be refreshed", status_code=500) from exc

    def _verify_partition_authority(self, partition: Mapping[str, Any], path: Path) -> None:
        logical_uri = str(partition["logical_uri"])
        relative = logical_uri[len(LOGICAL_PACKAGE_ROOT) + 1 :]
        stat_result = path.stat()
        if stat_result.st_size != partition["byte_count"]:
            raise SportsDataAccessError("PARTITION_BYTE_COUNT_MISMATCH", "Registered partition byte count changed", status_code=409)
        try:
            physical_schema, row_count = parquet_physical_schema(path, logical_uri=relative)
            current_file_identity = filesystem_identity(path, root=self.package_root)
        except ManifestValidationError as exc:
            raise SportsDataAccessError(exc.code, str(exc), status_code=409) from exc
        if row_count != partition["row_count"]:
            raise SportsDataAccessError("PARTITION_ROW_COUNT_MISMATCH", "Registered partition footer row count changed", status_code=409)
        if physical_schema != partition["physical_schema_json"]:
            raise SportsDataAccessError("PARTITION_SCHEMA_MISMATCH", "Registered partition ordered physical schema changed", status_code=409)
        fingerprint = sha256_bytes(canonical_json_bytes(physical_schema))
        if fingerprint != partition["physical_schema_fingerprint"]:
            raise SportsDataAccessError("PARTITION_SCHEMA_FINGERPRINT_MISMATCH", "Registered partition schema fingerprint changed", status_code=409)
        with self._cache_lock:
            cache = self._load_validation_cache()
            cached = cache["entries"].get(relative)
            current_binding = {
                "manifestSha": cache.get("manifestSha"),
                "logicalUri": relative,
                "size": stat_result.st_size,
                "mtimeNs": stat_result.st_mtime_ns,
                "fileSha": partition["file_sha"],
                "schemaFingerprint": partition["physical_schema_fingerprint"],
                "rowCount": partition["row_count"],
                "rootIdentity": self.root_identity,
                "fileIdentity": current_file_identity,
            }
            if cached == current_binding:
                return
            if cached and cached.get("rootIdentity") not in {None, self.root_identity}:
                raise SportsDataAccessError("PARTITION_ROOT_IDENTITY_MISMATCH", "Partition cache root identity changed", status_code=409)
            if cached and cached.get("fileIdentity") not in {None, current_file_identity}:
                raise SportsDataAccessError("PARTITION_FILE_IDENTITY_CHANGED", "Registered partition filesystem identity changed", status_code=409)
            try:
                current_sha = sha256_file(path, logical_uri=relative)
            except ManifestValidationError as exc:
                raise SportsDataAccessError(exc.code, str(exc), status_code=409) from exc
            if current_sha != partition["file_sha"]:
                raise SportsDataAccessError("PARTITION_HASH_MISMATCH", "Registered partition SHA-256 changed", status_code=409)
            cache["entries"][relative] = current_binding
            self._save_validation_cache(cache)

    def _schema(self, registration_id: str, family: str) -> dict[str, Any]:
        if family not in EXPECTED_FAMILIES:
            raise SportsDataAccessError("FAMILY_NOT_FOUND", "Registered dataset family was not found", status_code=404)
        schema = self.registry.get_schema(registration_id, family)
        if not schema:
            raise SportsDataAccessError("SCHEMA_NOT_FOUND", "Registered family schema was not found", status_code=404)
        return schema

    @staticmethod
    def _allowlist(schema: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {str(item["name"]): item for item in schema.get("fields_json") or []}

    def validate_fields(self, registration_id: str, family: str, fields: Sequence[str] | None) -> tuple[list[str], dict[str, dict[str, Any]]]:
        schema = self._schema(registration_id, family)
        allowlist = self._allowlist(schema)
        selected = list(fields or list(allowlist)[:12])
        if not selected:
            raise SportsDataAccessError("FIELDS_REQUIRED", "At least one registered field is required")
        if len(selected) > MAX_QUERY_FIELDS or len(selected) != len(set(selected)):
            raise SportsDataAccessError("FIELD_LIMIT_EXCEEDED", "Requested fields exceed the bounded unique-field limit")
        rejected = sorted(set(selected) - set(allowlist))
        if rejected:
            raise SportsDataAccessError("FIELD_NOT_ALLOWLISTED", f"Fields are not registered for this family: {', '.join(rejected)}")
        return selected, allowlist

    def _resolve_partition(self, partition: Mapping[str, Any]) -> Path:
        logical_uri = str(partition.get("logical_uri") or "")
        prefix = LOGICAL_PACKAGE_ROOT + "/"
        if not logical_uri.startswith(prefix):
            raise SportsDataAccessError("LOGICAL_URI_MISMATCH", "Registered partition logical URI is invalid", status_code=409)
        try:
            relative = validate_package_relative_uri(logical_uri[len(prefix) :])
        except ManifestValidationError as exc:
            raise SportsDataAccessError(exc.code, str(exc), status_code=409) from exc
        candidate = self.package_root / PurePosixPath(relative)
        try:
            resolved = candidate.resolve(strict=True)
            root = self.package_root.resolve(strict=True)
        except OSError as exc:
            raise SportsDataAccessError("PARTITION_UNAVAILABLE", "Registered partition is unavailable", status_code=409) from exc
        if root not in resolved.parents or not resolved.is_file() or resolved.is_symlink():
            raise SportsDataAccessError("PARTITION_ESCAPE", "Registered partition failed path containment", status_code=409)
        current = candidate
        while current != self.package_root:
            try:
                attributes = getattr(current.lstat(), "st_file_attributes", 0)
            except OSError as exc:
                raise SportsDataAccessError("PARTITION_UNAVAILABLE", "Registered partition metadata is unavailable", status_code=409) from exc
            if current.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise SportsDataAccessError("PARTITION_LINK_REJECTED", "Registered partition contains a symlink or junction", status_code=409)
            current = current.parent
        try:
            if resolved.stat().st_nlink != 1:
                raise SportsDataAccessError("PARTITION_HARDLINK_REJECTED", "Registered partition hardlink substitution was detected", status_code=409)
        except OSError as exc:
            raise SportsDataAccessError("PARTITION_UNAVAILABLE", "Registered partition metadata is unavailable", status_code=409) from exc
        return resolved

    @staticmethod
    def _partition_fields(partition: Mapping[str, Any]) -> set[str]:
        return {str(item["name"]) for item in partition.get("physical_schema_json") or []}

    def _iter_batches(
        self,
        partitions: Sequence[Mapping[str, Any]],
        *,
        fields: Sequence[str],
        cancel_event: threading.Event,
        max_rows: int,
    ) -> Iterator[tuple[pa.RecordBatch, int]]:
        rows_scanned = 0
        for partition in partitions:
            if cancel_event.is_set():
                raise SportsDataAccessError("QUERY_CANCELLED", "Query was cancelled", status_code=409)
            available = self._partition_fields(partition)
            readable = [field for field in fields if field in available]
            path = self._resolve_partition(partition)
            self._verify_partition_authority(partition, path)
            if not readable:
                remaining = int(partition["row_count"])
                while remaining:
                    if cancel_event.is_set():
                        raise SportsDataAccessError("QUERY_CANCELLED", "Query was cancelled", status_code=409)
                    batch_rows = min(BATCH_ROWS, remaining)
                    if rows_scanned + batch_rows > max_rows:
                        raise SportsDataAccessError("QUERY_ROW_LIMIT_EXCEEDED", "Query exceeds the registered analytical row limit", status_code=413)
                    batch = pa.record_batch(
                        [pa.nulls(batch_rows) for _field in fields],
                        names=list(fields),
                    )
                    if batch.nbytes > MAX_QUERY_MEMORY_BYTES:
                        raise SportsDataAccessError("QUERY_MEMORY_LIMIT_EXCEEDED", "Record batch exceeds the analytical memory limit", status_code=413)
                    rows_scanned += batch_rows
                    remaining -= batch_rows
                    yield batch, rows_scanned
                continue
            try:
                parquet = pq.ParquetFile(path)
                for batch in parquet.iter_batches(batch_size=BATCH_ROWS, columns=readable, use_threads=False):
                    if cancel_event.is_set():
                        raise SportsDataAccessError("QUERY_CANCELLED", "Query was cancelled", status_code=409)
                    if rows_scanned + batch.num_rows > max_rows:
                        raise SportsDataAccessError("QUERY_ROW_LIMIT_EXCEEDED", "Query exceeds the registered analytical row limit", status_code=413)
                    if batch.nbytes > MAX_QUERY_MEMORY_BYTES:
                        raise SportsDataAccessError("QUERY_MEMORY_LIMIT_EXCEEDED", "Record batch exceeds the analytical memory limit", status_code=413)
                    rows_scanned += batch.num_rows
                    yield batch, rows_scanned
            except SportsDataAccessError:
                raise
            except Exception as exc:
                raise SportsDataAccessError("PARQUET_READ_FAILED", "Registered Parquet data could not be read") from exc

    def _begin_audit(
        self,
        *,
        query_id: str | None,
        registration_id: str,
        user_id: str,
        operation: str,
        logical_scope: str,
        fields: Sequence[str],
        requested_limit: int | None,
    ) -> tuple[str, threading.Event]:
        selected_id = query_id or f"sports-query-{uuid.uuid4().hex}"
        cancel_event = self.cancellations.begin(selected_id, user_id=user_id)
        try:
            self.registry.record_query_start(
                query_id=selected_id,
                registration_id=registration_id,
                user_id=user_id,
                operation=operation,
                logical_scope=logical_scope,
                fields=fields,
                requested_limit=requested_limit,
            )
        except Exception:
            self.cancellations.finish(selected_id)
            raise
        return selected_id, cancel_event

    def _finish_audit(
        self,
        query_id: str,
        *,
        status: str,
        rows_scanned: int,
        rows_returned: int,
        error_code: str | None = None,
    ) -> None:
        try:
            self.registry.record_query_finish(
                query_id,
                status=status,
                rows_scanned=rows_scanned,
                rows_returned=rows_returned,
                error_code=error_code,
            )
        finally:
            self.cancellations.finish(query_id)

    def family_season_counts(self, registration_id: str, *, user_id: str) -> dict[str, Any]:
        self._registration(registration_id)
        query_id, _event = self._begin_audit(
            query_id=None,
            registration_id=registration_id,
            user_id=user_id,
            operation="FAMILY_SEASON_COUNTS",
            logical_scope=f"{LOGICAL_PACKAGE_ROOT}/parquet",
            fields=[],
            requested_limit=None,
        )
        try:
            partitions = self.registry.list_partitions(registration_id)
            aggregate: dict[tuple[str, int], dict[str, Any]] = {}
            for partition in partitions:
                key = (partition["family"], partition["season"])
                item = aggregate.setdefault(
                    key,
                    {"family": partition["family"], "season": partition["season"], "rows": 0, "bytes": 0, "partitions": 0},
                )
                item["rows"] += partition["row_count"]
                item["bytes"] += partition["byte_count"]
                item["partitions"] += 1
            results = [aggregate[key] for key in sorted(aggregate)]
            self._finish_audit(query_id, status="COMPLETED", rows_scanned=0, rows_returned=len(results))
            return {"queryId": query_id, "counts": results}
        except Exception as exc:
            self._finish_audit(query_id, status="FAILED", rows_scanned=0, rows_returned=0, error_code=getattr(exc, "code", "INTERNAL_ERROR"))
            raise

    def schema_preview(self, registration_id: str, family: str, *, user_id: str) -> dict[str, Any]:
        self._registration(registration_id)
        schema = self._schema(registration_id, family)
        fields = schema.get("fields_json") or []
        query_id, _event = self._begin_audit(
            query_id=None,
            registration_id=registration_id,
            user_id=user_id,
            operation="SCHEMA_PREVIEW",
            logical_scope=f"{LOGICAL_PACKAGE_ROOT}/parquet/{family}",
            fields=[item["name"] for item in fields],
            requested_limit=len(fields),
        )
        self._finish_audit(query_id, status="COMPLETED", rows_scanned=0, rows_returned=len(fields))
        return {
            "queryId": query_id,
            "family": family,
            "logicalSchemaVersion": schema["logical_schema_version"],
            "compatiblePartitions": schema["compatible_partition_count"],
            "physicalVariants": schema["physical_variant_count"],
            "fields": fields,
        }

    def preview(
        self,
        registration_id: str,
        family: str,
        *,
        user_id: str,
        seasons: Sequence[int] = (),
        fields: Sequence[str] | None = None,
        limit: int = 25,
        query_id: str | None = None,
    ) -> dict[str, Any]:
        self._registration(registration_id)
        seasons = validate_season_scope(seasons)
        if type(limit) is not int or not 1 <= limit <= MAX_PREVIEW_ROWS:
            raise SportsDataAccessError("PREVIEW_LIMIT_EXCEEDED", f"Preview limit must be 1–{MAX_PREVIEW_ROWS}")
        selected, _allowlist = self.validate_fields(registration_id, family, fields)
        partitions = self.registry.list_partitions(registration_id, family=family, seasons=seasons)
        if not partitions:
            raise SportsDataAccessError("PARTITIONS_NOT_FOUND", "No registered partitions match the requested scope", status_code=404)
        selected_id, event = self._begin_audit(
            query_id=query_id,
            registration_id=registration_id,
            user_id=user_id,
            operation="BOUNDED_PREVIEW",
            logical_scope=f"{LOGICAL_PACKAGE_ROOT}/parquet/{family}",
            fields=selected,
            requested_limit=limit,
        )
        rows: list[dict[str, Any]] = []
        output_bytes = 2
        rows_scanned = 0
        try:
            for batch, rows_scanned in self._iter_batches(partitions, fields=selected, cancel_event=event, max_rows=MAX_QUERY_ROWS):
                for item in batch.to_pylist():
                    row = {field: _json_safe(item.get(field)) for field in selected}
                    output_bytes += len(canonical_json_bytes(row)) + 1
                    if output_bytes > MAX_QUERY_OUTPUT_BYTES:
                        raise SportsDataAccessError("QUERY_OUTPUT_LIMIT_EXCEEDED", "Preview output exceeds the analytical output limit", status_code=413)
                    rows.append(row)
                    if len(rows) >= limit:
                        break
                if len(rows) >= limit:
                    break
            self._finish_audit(selected_id, status="COMPLETED", rows_scanned=rows_scanned, rows_returned=len(rows))
            return {
                "queryId": selected_id,
                "family": family,
                "seasons": list(seasons),
                "fields": selected,
                "limit": limit,
                "rows": rows,
                "rowsScanned": rows_scanned,
                "logicalScope": f"{LOGICAL_PACKAGE_ROOT}/parquet/{family}",
            }
        except Exception as exc:
            self._finish_audit(selected_id, status="CANCELLED" if getattr(exc, "code", "") == "QUERY_CANCELLED" else "FAILED", rows_scanned=rows_scanned, rows_returned=0, error_code=getattr(exc, "code", "INTERNAL_ERROR"))
            raise

    def class_distribution(
        self,
        registration_id: str,
        family: str,
        field: str,
        *,
        user_id: str,
        seasons: Sequence[int] = (),
        query_id: str | None = None,
    ) -> dict[str, Any]:
        self._registration(registration_id)
        seasons = validate_season_scope(seasons)
        selected, _allowlist = self.validate_fields(registration_id, family, [field])
        partitions = self.registry.list_partitions(registration_id, family=family, seasons=seasons)
        if not partitions:
            raise SportsDataAccessError("PARTITIONS_NOT_FOUND", "No registered partitions match the requested scope", status_code=404)
        declared_rows = sum(item["row_count"] for item in partitions)
        if declared_rows > MAX_QUERY_ROWS:
            raise SportsDataAccessError("QUERY_ROW_LIMIT_EXCEEDED", "Class distribution exceeds the analytical row limit", status_code=413)
        present_partitions = [item for item in partitions if field in self._partition_fields(item)]
        if not present_partitions:
            raise SportsDataAccessError("FIELD_NOT_PRESENT", "Allowlisted field is absent from every selected physical partition", status_code=409)
        selected_id, event = self._begin_audit(
            query_id=query_id,
            registration_id=registration_id,
            user_id=user_id,
            operation="CLASS_DISTRIBUTION",
            logical_scope=f"{LOGICAL_PACKAGE_ROOT}/parquet/{family}",
            fields=selected,
            requested_limit=None,
        )
        counts: Counter[str] = Counter()
        aggregate_bytes = 2
        null_count = 0
        rows_scanned = 0
        try:
            for batch, rows_scanned in self._iter_batches(partitions, fields=selected, cancel_event=event, max_rows=MAX_QUERY_ROWS):
                field_index = batch.schema.get_field_index(field)
                if field_index < 0:
                    raise SportsDataAccessError("FIELD_NOT_PRESENT", "Allowlisted field is absent from a selected physical partition", status_code=409)
                values = batch.column(field_index).to_pylist()
                for value in values:
                    if value is None:
                        null_count += 1
                    else:
                        normalized = str(value)
                        if normalized not in counts:
                            if len(counts) >= MAX_AGGREGATE_CATEGORIES:
                                raise SportsDataAccessError("AGGREGATE_CARDINALITY_LIMIT_EXCEEDED", "Class distribution exceeds the bounded category limit", status_code=413)
                            aggregate_bytes += len(normalized.encode("utf-8")) + 64
                            if aggregate_bytes > MAX_QUERY_OUTPUT_BYTES:
                                raise SportsDataAccessError("QUERY_OUTPUT_LIMIT_EXCEEDED", "Class distribution exceeds the analytical output limit", status_code=413)
                        counts[normalized] += 1
            if family == "plate_appearance" and field == "outcome":
                observed_classes = set(counts)
                expected_classes = set(PA_CLASS_ORDER)
                if observed_classes != expected_classes:
                    missing_classes = sorted(expected_classes - observed_classes)
                    unexpected_classes = sorted(observed_classes - expected_classes)
                    raise SportsDataAccessError(
                        "CLASS_ORDER_AUTHORITY_MISMATCH",
                        f"Plate-appearance classes differ (missing={missing_classes}, unexpected={unexpected_classes})",
                        status_code=409,
                    )
                result = [{"value": value, "count": counts[value]} for value in PA_CLASS_ORDER]
            else:
                result = [{"value": value, "count": count} for value, count in sorted(counts.items())]
            if len(canonical_json_bytes(result)) > MAX_QUERY_OUTPUT_BYTES:
                raise SportsDataAccessError("QUERY_OUTPUT_LIMIT_EXCEEDED", "Class distribution exceeds the analytical output limit", status_code=413)
            self._finish_audit(selected_id, status="COMPLETED", rows_scanned=rows_scanned, rows_returned=len(result))
            return {"queryId": selected_id, "family": family, "field": field, "seasons": list(seasons), "rowsScanned": rows_scanned, "nullCount": null_count, "distribution": result}
        except Exception as exc:
            self._finish_audit(selected_id, status="CANCELLED" if getattr(exc, "code", "") == "QUERY_CANCELLED" else "FAILED", rows_scanned=rows_scanned, rows_returned=0, error_code=getattr(exc, "code", "INTERNAL_ERROR"))
            raise

    def missingness(
        self,
        registration_id: str,
        family: str,
        fields: Sequence[str],
        *,
        user_id: str,
        seasons: Sequence[int] = (),
        query_id: str | None = None,
    ) -> dict[str, Any]:
        self._registration(registration_id)
        seasons = validate_season_scope(seasons)
        selected, _allowlist = self.validate_fields(registration_id, family, fields)
        partitions = self.registry.list_partitions(registration_id, family=family, seasons=seasons)
        if not partitions:
            raise SportsDataAccessError("PARTITIONS_NOT_FOUND", "No registered partitions match the requested scope", status_code=404)
        declared_rows = sum(item["row_count"] for item in partitions)
        if declared_rows > MAX_QUERY_ROWS:
            raise SportsDataAccessError("QUERY_ROW_LIMIT_EXCEEDED", "Missingness scan exceeds the analytical row limit", status_code=413)
        selected_id, event = self._begin_audit(
            query_id=query_id,
            registration_id=registration_id,
            user_id=user_id,
            operation="MISSINGNESS_SUMMARY",
            logical_scope=f"{LOGICAL_PACKAGE_ROOT}/parquet/{family}",
            fields=selected,
            requested_limit=None,
        )
        missing = Counter({field: 0 for field in selected})
        observed = Counter({field: 0 for field in selected})
        rows_scanned = 0
        try:
            for batch, rows_scanned in self._iter_batches(partitions, fields=selected, cancel_event=event, max_rows=MAX_QUERY_ROWS):
                batch_names = set(batch.schema.names)
                for field in selected:
                    if field in batch_names:
                        column = batch.column(batch.schema.get_field_index(field))
                        missing[field] += int(column.null_count)
                        observed[field] += batch.num_rows
                    else:
                        missing[field] += batch.num_rows
                        observed[field] += batch.num_rows
            result = [
                {
                    "field": field,
                    "missing": missing[field],
                    "observed": observed[field] - missing[field],
                    "missingRate": (missing[field] / observed[field]) if observed[field] else None,
                }
                for field in selected
            ]
            self._finish_audit(selected_id, status="COMPLETED", rows_scanned=rows_scanned, rows_returned=len(result))
            return {"queryId": selected_id, "family": family, "seasons": list(seasons), "rowsScanned": rows_scanned, "fields": result}
        except Exception as exc:
            self._finish_audit(selected_id, status="CANCELLED" if getattr(exc, "code", "") == "QUERY_CANCELLED" else "FAILED", rows_scanned=rows_scanned, rows_returned=0, error_code=getattr(exc, "code", "INTERNAL_ERROR"))
            raise

    def feature_eligibility(self, registration_id: str, family: str, *, user_id: str) -> dict[str, Any]:
        schema = self.schema_preview(registration_id, family, user_id=user_id)
        return {
            **schema,
            "fields": [
                {
                    "field": item["name"],
                    "dtype": item["dtype"],
                    "nullable": item["nullable"],
                    "identityClassification": item["target_feature_identity_classification"],
                    "temporalRiskClassification": item["temporal_risk_classification"],
                    "description": item["semantic_description"],
                }
                for item in schema["fields"]
            ],
        }

    def fold_scan_plan(self, registration_id: str, fold_id: str, *, user_id: str) -> dict[str, Any]:
        self._registration(registration_id)
        fold = self.registry.get_fold(registration_id, fold_id)
        if not fold:
            raise SportsDataAccessError("FOLD_NOT_FOUND", "Registered temporal fold was not found", status_code=404)
        seasons = list(fold["training_seasons_json"]) + [fold["validation_season"]]
        partitions = self.registry.list_partitions(registration_id, family="plate_appearance", seasons=seasons)
        query_id, _event = self._begin_audit(
            query_id=None,
            registration_id=registration_id,
            user_id=user_id,
            operation="FOLD_SCAN_PLAN",
            logical_scope=f"{LOGICAL_PACKAGE_ROOT}/parquet/plate_appearance",
            fields=[],
            requested_limit=None,
        )
        self._finish_audit(query_id, status="COMPLETED", rows_scanned=0, rows_returned=len(partitions))
        return {
            "queryId": query_id,
            "foldId": fold_id,
            "trainingSeasons": fold["training_seasons_json"],
            "validationSeason": fold["validation_season"],
            "trainingRows": fold["training_rows"],
            "validationRows": fold["validation_rows"],
            "partitions": [
                {
                    "partitionId": item["partition_id"],
                    "family": item["family"],
                    "season": item["season"],
                    "month": item["month"],
                    "logicalUri": item["logical_uri"],
                    "rows": item["row_count"],
                }
                for item in partitions
            ],
        }

    def cancel(self, query_id: str, *, user_id: str, is_admin: bool = False) -> bool:
        return self.cancellations.cancel(query_id, user_id=user_id, is_admin=is_admin)
