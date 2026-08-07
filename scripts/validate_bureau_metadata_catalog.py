"""Run restricted, aggregate-only acceptance for one bureau metadata catalog.

The canonical PDF, CSV staging file, output root, and summary file are explicit
absolute paths outside the repository.  The harness never prints source-derived
attribute codes, descriptions, value definitions, or host paths.  It performs
three clean deterministic builds, exact-load and lookup workloads, concurrent
read validation, and fail-closed integrity checks against disposable copies.

This module is deliberately not a service entrypoint and exposes no catalog
enumeration or export operation.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import tracemalloc
from typing import Any, Callable, Iterable, Mapping, Sequence
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.bureau_metadata import catalog_builder as builder_module  # noqa: E402
from server.bureau_metadata.catalog_builder import (  # noqa: E402
    CatalogBuildConfig,
    CatalogBuildError,
    CatalogBuildResult,
    build_catalog,
)
from server.bureau_metadata.catalog_service import BureauCatalogService  # noqa: E402
from server.bureau_metadata.catalog_store import (  # noqa: E402
    BureauCatalogIntegrityError,
    BureauCatalogLoader,
    BureauCatalogNotFoundError,
    BureauCatalogStore,
)
from server.bureau_metadata.normalizer import (  # noqa: E402
    catalog_id_for_key,
    catalog_relative_directory,
    validate_sha256,
)
from server.bureau_metadata.source_reader import (  # noqa: E402
    SourceDescriptor,
    inspect_external_output_directory,
    inspect_external_source,
    is_within,
    paths_overlap,
    sha256_file,
)
from server.bureau_metadata.types import (  # noqa: E402
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
)


SCHEMA_VERSION = "1.0"
DEFAULT_RELOAD_COUNT = 100
DEFAULT_LOOKUP_COUNT = 100_000
DEFAULT_CLASSIFICATION_COUNT = 100_000
DEFAULT_READER_WORKERS = 8
_ARTIFACT_MANIFEST = "catalog_manifest.json"


class CatalogAcceptanceError(RuntimeError):
    """Raised when an acceptance invariant is not satisfied."""


@dataclass(frozen=True, slots=True)
class AcceptanceWorkload:
    """Acceptance workload; CLI always uses the required production values."""

    reload_count: int = DEFAULT_RELOAD_COUNT
    exact_lookup_count: int = DEFAULT_LOOKUP_COUNT
    classification_count: int = DEFAULT_CLASSIFICATION_COUNT
    reader_workers: int = DEFAULT_READER_WORKERS
    concurrent_operations_per_worker: int = 64

    def validate(self) -> "AcceptanceWorkload":
        values = (
            self.reload_count,
            self.exact_lookup_count,
            self.classification_count,
            self.reader_workers,
            self.concurrent_operations_per_worker,
        )
        if any(int(value) <= 0 for value in values):
            raise CatalogAcceptanceError("acceptance workload values must be positive")
        return self


@dataclass(frozen=True, slots=True)
class AcceptanceSettings:
    pdf_path: Path
    csv_path: Path
    output_root: Path
    summary_path: Path
    provider: str
    product: str
    edition: str
    dictionary_version: str
    policy_id: str
    policy_version: str
    built_by: str
    source_control_commit: str
    catalog_id: str | None = None
    built_at: str | None = None
    resume_completed_builds: bool = False
    expected_catalog_checksum: str | None = None

    def build_config(self) -> CatalogBuildConfig:
        timestamp = self.built_at or datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        return CatalogBuildConfig(
            provider=self.provider,
            product=self.product,
            edition=self.edition,
            dictionary_version=self.dictionary_version,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            built_by=self.built_by,
            source_control_commit=self.source_control_commit,
            catalog_id=self.catalog_id,
            built_at=timestamp,
        )


@dataclass(frozen=True, slots=True)
class _ArtifactInventory:
    hashes: Mapping[str, str]
    sizes: Mapping[str, int]
    total_bytes: int


class _ExactGrantProvider:
    """Acceptance-only exact grant provider with no discovery authority."""

    def authorize(self, context, catalog_key, catalog_checksum, operation):
        return BureauCatalogAccessGrant(
            grant_id="bureau-catalog-acceptance-grant",
            principal_id=context.principal_id,
            tenant_id=context.tenant_id,
            catalog_key=catalog_key,
            catalog_checksum=catalog_checksum,
            operation=operation,
            expires_at="2099-01-01T00:00:00Z",
        )


def _percentile_ms(samples_seconds: Sequence[float], percentile: float) -> float:
    if not samples_seconds:
        return 0.0
    ordered = sorted(samples_seconds)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index] * 1000.0, 6)


def _timing_summary(samples_seconds: Sequence[float]) -> dict[str, float | int]:
    total = sum(samples_seconds)
    return {
        "samples": len(samples_seconds),
        "total_ms": round(total * 1000.0, 6),
        "mean_ms": round((total / len(samples_seconds)) * 1000.0, 6)
        if samples_seconds
        else 0.0,
        "p95_ms": _percentile_ms(samples_seconds, 0.95),
        "max_ms": round(max(samples_seconds, default=0.0) * 1000.0, 6),
    }


def _operation_timing_summary(
    samples_seconds: Sequence[float],
) -> dict[str, float]:
    """Summarize individually timed operations in microseconds."""

    if not samples_seconds:
        return {
            "minimum_microseconds": 0.0,
            "mean_microseconds": 0.0,
            "p95_microseconds": 0.0,
            "maximum_microseconds": 0.0,
        }
    return {
        "minimum_microseconds": round(min(samples_seconds) * 1_000_000.0, 6),
        "mean_microseconds": round(
            sum(samples_seconds) * 1_000_000.0 / len(samples_seconds), 6
        ),
        "p95_microseconds": round(
            _percentile_ms(samples_seconds, 0.95) * 1000.0, 6
        ),
        "maximum_microseconds": round(max(samples_seconds) * 1_000_000.0, 6),
    }


def _safe_sha256(path: Path) -> str:
    return sha256_file(path)


def _ensure_external_root(
    settings: AcceptanceSettings,
) -> tuple[SourceDescriptor, SourceDescriptor]:
    pdf = inspect_external_source(
        settings.pdf_path,
        role="canonical PDF",
        expected_suffixes=(".pdf",),
    )
    csv = inspect_external_source(
        settings.csv_path,
        role="CSV staging source",
        expected_suffixes=(".csv",),
    )
    if paths_overlap(pdf.path, csv.path):
        raise CatalogAcceptanceError("catalog sources must be distinct files")

    output = inspect_external_output_directory(settings.output_root)
    summary = Path(settings.summary_path).expanduser()
    if not summary.is_absolute():
        raise CatalogAcceptanceError("summary path must be an explicit absolute path")
    summary = summary.resolve(strict=False)
    inspect_external_output_directory(summary.parent)
    if summary.suffix.casefold() != ".json":
        raise CatalogAcceptanceError("summary path must name a JSON file")
    if not is_within(summary, output) or summary == output:
        raise CatalogAcceptanceError("summary path must remain inside the acceptance root")
    if paths_overlap(output, pdf.path) or paths_overlap(output, csv.path):
        raise CatalogAcceptanceError("acceptance output must not overlap a source")
    if output.exists():
        if not output.is_dir():
            raise CatalogAcceptanceError("acceptance output root is not a directory")
        try:
            children = tuple(output.iterdir())
            if not settings.resume_completed_builds and children:
                raise CatalogAcceptanceError("acceptance output root must be empty")
        except OSError as exc:
            raise CatalogAcceptanceError("acceptance output root is unavailable") from exc
    else:
        output.mkdir(parents=True)
    if summary.exists():
        raise CatalogAcceptanceError("acceptance summary already exists")
    if settings.resume_completed_builds:
        if settings.expected_catalog_checksum is None:
            raise CatalogAcceptanceError(
                "resume requires an explicit expected catalog checksum"
            )
    elif settings.expected_catalog_checksum is not None:
        raise CatalogAcceptanceError(
            "expected catalog checksum is accepted only for an explicit resume"
        )
    return pdf, csv


def _artifact_inventory(directory: Path) -> _ArtifactInventory:
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise CatalogAcceptanceError("published catalog contains no artifacts")
    hashes: dict[str, str] = {}
    sizes: dict[str, int] = {}
    total = 0
    for path in files:
        relative = path.relative_to(directory).as_posix()
        # Artifact names are schema-controlled. Source-derived names are never
        # emitted by the builder beneath a published catalog directory.
        size = path.stat().st_size
        hashes[relative] = _safe_sha256(path)
        sizes[relative] = size
        total += size
    return _ArtifactInventory(hashes=hashes, sizes=sizes, total_bytes=total)


def _run_clean_builds(
    *,
    pdf: Path,
    csv: Path,
    output_root: Path,
    config: CatalogBuildConfig,
    build_function: Callable[..., CatalogBuildResult],
) -> tuple[list[CatalogBuildResult], list[_ArtifactInventory], list[float]]:
    results: list[CatalogBuildResult] = []
    inventories: list[_ArtifactInventory] = []
    timings: list[float] = []
    for ordinal in range(1, 4):
        build_root = output_root / f"deterministic-build-{ordinal:02d}"
        if build_root.exists():
            raise CatalogAcceptanceError("a deterministic build root already exists")
        started = time.perf_counter()
        result = build_function(
            pdf_path=pdf,
            csv_path=csv,
            output_directory=build_root,
            config=config,
        )
        timings.append(time.perf_counter() - started)
        if result.validation_status == "failed":
            raise CatalogAcceptanceError("a deterministic catalog build failed validation")
        results.append(result)
        inventories.append(_artifact_inventory(result.output_directory))

    checksums = {item.catalog_checksum for item in results}
    if len(checksums) != 1:
        raise CatalogAcceptanceError("clean builds produced different catalog checksums")
    first_hashes = dict(inventories[0].hashes)
    if any(dict(item.hashes) != first_hashes for item in inventories[1:]):
        raise CatalogAcceptanceError("clean builds produced different artifact hashes")
    return results, inventories, timings


def _assert_exact_published_tree(
    *,
    build_root: Path,
    catalog_directory: Path,
    manifest: Any,
) -> None:
    """Reject extra, missing, or displaced files in one resumed build root."""

    descriptors = (
        manifest.attribute_file,
        manifest.special_value_file,
        manifest.reconciliation_file,
        manifest.lookup_index_file,
        manifest.validation_file,
        manifest.build_log_file,
    )
    expected_catalog_files = {_ARTIFACT_MANIFEST}
    expected_catalog_files.update(
        descriptor.relative_path
        for descriptor in descriptors
        if descriptor is not None
    )
    actual_catalog_files = {
        path.relative_to(catalog_directory).as_posix()
        for path in catalog_directory.rglob("*")
        if path.is_file()
    }
    if actual_catalog_files != expected_catalog_files:
        raise CatalogAcceptanceError(
            "a resumed catalog contains missing or unexpected artifacts"
        )

    expected_root_files = {
        (catalog_directory.relative_to(build_root) / relative).as_posix()
        for relative in expected_catalog_files
    }
    actual_root_files = {
        path.relative_to(build_root).as_posix()
        for path in build_root.rglob("*")
        if path.is_file()
    }
    if actual_root_files != expected_root_files:
        raise CatalogAcceptanceError(
            "a resumed build root contains an unexpected catalog or file"
        )

    expected_directories: set[str] = set()
    for relative_file in expected_root_files:
        parent = Path(relative_file).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    actual_directories = {
        path.relative_to(build_root).as_posix()
        for path in build_root.rglob("*")
        if path.is_dir()
    }
    if actual_directories != expected_directories:
        raise CatalogAcceptanceError(
            "a resumed build root contains an unexpected directory"
        )


def _assert_resume_manifest_contract(
    *,
    manifest: Any,
    config: CatalogBuildConfig,
    pdf_source: SourceDescriptor,
    csv_source: SourceDescriptor,
    explicit_built_at: str | None,
) -> None:
    expected_catalog_id = config.catalog_id or catalog_id_for_key(config.catalog_key())
    if manifest.catalog_id != expected_catalog_id:
        raise CatalogAcceptanceError("resumed catalog ID contradicts the exact request")
    if (
        manifest.schema_version != builder_module.SCHEMA_VERSION
        or manifest.builder_name != builder_module.BUILDER_NAME
        or manifest.builder_version != builder_module.BUILDER_VERSION
        or manifest.license.policy_id != config.policy_id
        or manifest.license.policy_version != config.policy_version
        or manifest.license.allowed_operations != frozenset(config.allowed_operations)
        or manifest.license.classification != config.license_classification
        or manifest.license.redistribution_status != config.redistribution_status
        or manifest.license.source_export_allowed
        or manifest.license.full_catalog_api_allowed
        or manifest.license.tenant_sharing_allowed
        or manifest.license.public_demo_allowed
        or not manifest.license.legal_review_required
        or manifest.built_by != config.built_by
        or manifest.source_control_commit != config.source_control_commit
    ):
        raise CatalogAcceptanceError(
            "resumed catalog governance metadata contradicts the exact request"
        )
    if explicit_built_at is not None and manifest.built_at != explicit_built_at:
        raise CatalogAcceptanceError(
            "resumed catalog timestamp contradicts the explicit request"
        )
    by_role = {source.role: source for source in manifest.source_files}
    if len(manifest.source_files) != 2 or set(by_role) != {
        "canonical_pdf",
        "csv_staging",
    }:
        raise CatalogAcceptanceError("resumed catalog source inventory is incomplete")
    for actual, expected in (
        (by_role["canonical_pdf"], pdf_source),
        (by_role["csv_staging"], csv_source),
    ):
        if (
            actual.filename != expected.filename
            or actual.suffix.casefold() != expected.suffix.casefold()
            or actual.sha256 != expected.sha256
            or actual.size_bytes != expected.size_bytes
        ):
            raise CatalogAcceptanceError(
                "resumed catalog source fingerprint contradicts the exact source"
            )


def _load_completed_builds(
    *,
    output_root: Path,
    config: CatalogBuildConfig,
    expected_checksum: str,
    pdf_source: SourceDescriptor,
    csv_source: SourceDescriptor,
    explicit_built_at: str | None,
) -> tuple[list[CatalogBuildResult], list[_ArtifactInventory], list[float]]:
    """Resume only three exact, complete, byte-identical published catalogs."""

    checksum = validate_sha256(
        expected_checksum,
        field_name="expected catalog checksum",
    )
    expected_names = {
        "deterministic-build-01",
        "deterministic-build-02",
        "deterministic-build-03",
    }
    children = tuple(output_root.iterdir())
    if (
        {child.name for child in children} != expected_names
        or any(not child.is_dir() for child in children)
    ):
        raise CatalogAcceptanceError(
            "resume requires exactly three completed deterministic build roots"
        )

    key = BureauCatalogKey.model_validate(config.catalog_key())
    relative_catalog = Path(*catalog_relative_directory(key, checksum).parts)
    results: list[CatalogBuildResult] = []
    inventories: list[_ArtifactInventory] = []
    verification_timings: list[float] = []
    for ordinal in range(1, 4):
        build_root = output_root / f"deterministic-build-{ordinal:02d}"
        catalog_directory = build_root / relative_catalog
        started = time.perf_counter()
        loaded = BureauCatalogStore(build_root).load_exact(key, checksum)
        verification_timings.append(time.perf_counter() - started)
        if catalog_directory.resolve(strict=True) != (
            build_root / relative_catalog
        ).resolve(strict=True):
            raise CatalogAcceptanceError("resumed exact catalog path is contradictory")
        _assert_exact_published_tree(
            build_root=build_root,
            catalog_directory=catalog_directory,
            manifest=loaded.manifest,
        )
        _assert_resume_manifest_contract(
            manifest=loaded.manifest,
            config=config,
            pdf_source=pdf_source,
            csv_source=csv_source,
            explicit_built_at=explicit_built_at,
        )
        aggregate = loaded.validation_summary.get("aggregate_summary", {})
        if not isinstance(aggregate, Mapping):
            raise CatalogAcceptanceError(
                "resumed validation summary does not contain aggregates"
            )
        results.append(
            CatalogBuildResult(
                output_directory=catalog_directory,
                manifest_path=catalog_directory / _ARTIFACT_MANIFEST,
                catalog_id=loaded.manifest.catalog_id,
                catalog_checksum=loaded.manifest.catalog_checksum,
                attribute_count=loaded.manifest.attribute_count,
                special_value_count=loaded.manifest.special_value_count,
                validation_finding_count=loaded.manifest.validation_finding_count,
                validation_status=loaded.manifest.validation_status,
                aggregate_summary=dict(aggregate),
            )
        )
        inventories.append(_artifact_inventory(catalog_directory))

    if any(result.catalog_checksum != checksum for result in results):
        raise CatalogAcceptanceError("a resumed build has a different exact checksum")
    reference_hashes = dict(inventories[0].hashes)
    if any(dict(item.hashes) != reference_hashes for item in inventories[1:]):
        raise CatalogAcceptanceError("resumed builds are not byte-identical")
    return results, inventories, verification_timings


def _service_for(
    root: Path,
    *,
    max_entries: int = 2,
) -> tuple[BureauCatalogStore, BureauCatalogLoader, BureauCatalogService]:
    store = BureauCatalogStore(root)
    loader = BureauCatalogLoader(store, max_entries=max_entries)
    service = BureauCatalogService(loader, _ExactGrantProvider())
    return store, loader, service


def _classification_inputs(catalog: Any) -> tuple[tuple[str, object], ...]:
    specials_by_attribute: dict[str, str] = {}
    for (attribute_code, _), special in catalog.special_values_by_key.items():
        specials_by_attribute.setdefault(attribute_code, special.value_code)
    inputs: list[tuple[str, object]] = []
    for code, attribute in catalog.attributes_by_code.items():
        observed: object
        if code in specials_by_attribute:
            observed = specials_by_attribute[code]
        elif attribute.valid_values:
            observed = attribute.valid_values[0]
        elif attribute.ordinary_min is not None:
            observed = attribute.ordinary_min
        elif attribute.numeric_type in {"integer", "decimal"}:
            observed = 0
        elif attribute.numeric_type == "date":
            observed = "2000-01-01"
        else:
            observed = "acceptance-probe"
        inputs.append((code, observed))
    if not inputs:
        raise CatalogAcceptanceError("catalog has no attributes for acceptance")
    return tuple(inputs)


def _run_runtime_workload(
    *,
    catalog_root: Path,
    key: BureauCatalogKey,
    checksum: str,
    workload: AcceptanceWorkload,
) -> dict[str, Any]:
    workload.validate()
    store, loader, service = _service_for(catalog_root)
    context = BureauCatalogAccessContext(principal_id="acceptance-harness")

    reload_timings: list[float] = []
    loaded = None
    for _ in range(workload.reload_count):
        started = time.perf_counter()
        loaded = store.load_exact(key, checksum)
        reload_timings.append(time.perf_counter() - started)
    if loaded is None or loaded.manifest.catalog_checksum != checksum:
        raise CatalogAcceptanceError("exact catalog reload did not preserve identity")

    codes = tuple(loaded.attributes_by_code)
    if not codes:
        raise CatalogAcceptanceError("catalog has no exact lookup keys")
    # Prime the authorized loader outside the performance samples. The required
    # operations measure bounded exact lookup/classification latency, while the
    # separately reported uncached reload workload measures disk verification.
    loader.load_exact(key, checksum)
    lookup_timings: list[float] = []
    started = time.perf_counter()
    for index in range(workload.exact_lookup_count):
        operation_started = time.perf_counter()
        result = service.get_attribute_exact(
            context,
            key,
            checksum,
            codes[index % len(codes)],
        )
        operation_elapsed = time.perf_counter() - operation_started
        if result.catalog_checksum != checksum:
            raise CatalogAcceptanceError("exact attribute lookup crossed catalog identity")
        lookup_timings.append(operation_elapsed)
    lookup_elapsed = time.perf_counter() - started

    classification_inputs = _classification_inputs(loaded)
    classification_counts: dict[str, int] = {}
    classification_timings: list[float] = []
    started = time.perf_counter()
    for index in range(workload.classification_count):
        code, observed = classification_inputs[index % len(classification_inputs)]
        operation_started = time.perf_counter()
        result = service.classify_value_exact(
            context,
            key,
            checksum,
            code,
            observed,
        )
        operation_elapsed = time.perf_counter() - operation_started
        if result.catalog_checksum != checksum:
            raise CatalogAcceptanceError("classification crossed catalog identity")
        classification_counts[result.classification] = (
            classification_counts.get(result.classification, 0) + 1
        )
        classification_timings.append(operation_elapsed)
    classification_elapsed = time.perf_counter() - started

    def reader_worker(worker_number: int) -> tuple[str, int]:
        worker_store, _, worker_service = _service_for(catalog_root)
        worker_catalog = worker_store.load_exact(key, checksum)
        worker_inputs = _classification_inputs(worker_catalog)
        completed = 0
        for index in range(workload.concurrent_operations_per_worker):
            code, observed = worker_inputs[
                (worker_number + index) % len(worker_inputs)
            ]
            attribute = worker_service.get_attribute_exact(
                context,
                key,
                checksum,
                code,
            )
            classified = worker_service.classify_value_exact(
                context,
                key,
                checksum,
                code,
                observed,
            )
            if (
                attribute.catalog_checksum != checksum
                or classified.catalog_checksum != checksum
            ):
                raise CatalogAcceptanceError("concurrent reader crossed catalog identity")
            completed += 2
        return worker_catalog.manifest.catalog_checksum, completed

    concurrent_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workload.reader_workers) as pool:
        worker_results = tuple(
            pool.map(reader_worker, range(workload.reader_workers))
        )
    concurrent_elapsed = time.perf_counter() - concurrent_started
    if any(worker_checksum != checksum for worker_checksum, _ in worker_results):
        raise CatalogAcceptanceError("a concurrent reader loaded a different catalog")

    return {
        "reloads": {
            "requested": workload.reload_count,
            "completed": len(reload_timings),
            **_timing_summary(reload_timings),
        },
        "exact_attribute_lookups": {
            "requested": workload.exact_lookup_count,
            "completed": workload.exact_lookup_count,
            "total_ms": round(lookup_elapsed * 1000.0, 6),
            **_operation_timing_summary(lookup_timings),
        },
        "value_classifications": {
            "requested": workload.classification_count,
            "completed": sum(classification_counts.values()),
            "total_ms": round(classification_elapsed * 1000.0, 6),
            **_operation_timing_summary(classification_timings),
            "classification_counts": dict(sorted(classification_counts.items())),
        },
        "concurrent_readers": {
            "workers_requested": workload.reader_workers,
            "workers_completed": len(worker_results),
            "operations_completed": sum(item[1] for item in worker_results),
            "elapsed_ms": round(concurrent_elapsed * 1000.0, 6),
            "all_exact_identity": True,
        },
        "loader_cache_entries": loader.cache_size(),
    }


def _measure_representative_reload_memory(
    *,
    catalog_root: Path,
    key: BureauCatalogKey,
    checksum: str,
) -> dict[str, Any]:
    """Trace Python allocations for one uncached exact reload only."""

    tracemalloc.start()
    started = time.perf_counter()
    try:
        loaded = BureauCatalogStore(catalog_root).load_exact(key, checksum)
        if loaded.manifest.catalog_checksum != checksum:
            raise CatalogAcceptanceError(
                "representative memory reload crossed catalog identity"
            )
        current, peak = tracemalloc.get_traced_memory()
        elapsed = time.perf_counter() - started
    finally:
        tracemalloc.stop()
    return {
        "scope": "one_uncached_exact_reload_only",
        "reloads_measured": 1,
        "included_in_required_100_reload_count": False,
        "elapsed_ms": round(elapsed * 1000.0, 6),
        "python_tracemalloc_current_bytes": current,
        "python_tracemalloc_peak_bytes": peak,
    }


def _copy_tree_excluding(
    source: Path,
    destination: Path,
    *,
    excluded_relative_files: Iterable[str] = (),
) -> None:
    if destination.exists():
        raise CatalogAcceptanceError("negative-test destination already exists")
    excluded = {Path(value).as_posix() for value in excluded_relative_files}
    for directory in sorted(path for path in source.rglob("*") if path.is_dir()):
        (destination / directory.relative_to(source)).mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        relative = path.relative_to(source).as_posix()
        if relative in excluded:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _expect_failure(
    operation: Callable[[], Any],
    expected: tuple[type[BaseException], ...],
) -> bool:
    try:
        operation()
    except expected:
        return True
    except Exception as exc:
        raise CatalogAcceptanceError(
            "negative test failed with an unexpected safe error category"
        ) from exc
    raise CatalogAcceptanceError("negative test did not fail closed")


def _catalog_manifest(catalog_directory: Path) -> Mapping[str, Any]:
    try:
        value = json.loads((catalog_directory / _ARTIFACT_MANIFEST).read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogAcceptanceError("published manifest could not be inspected") from exc
    if not isinstance(value, dict):
        raise CatalogAcceptanceError("published manifest is not an object")
    return value


def _run_integrity_failures(
    *,
    source_root: Path,
    catalog_directory: Path,
    key: BureauCatalogKey,
    checksum: str,
    negative_root: Path,
) -> dict[str, bool]:
    manifest = _catalog_manifest(catalog_directory)
    attribute_descriptor = manifest.get("attribute_file")
    if not isinstance(attribute_descriptor, dict):
        raise CatalogAcceptanceError("manifest lacks the required attribute descriptor")
    attribute_relative = attribute_descriptor.get("relative_path")
    if not isinstance(attribute_relative, str):
        raise CatalogAcceptanceError("attribute descriptor lacks a relative path")
    catalog_relative = catalog_directory.relative_to(source_root)

    manifest_root = negative_root / "manifest-corruption"
    _copy_tree_excluding(source_root, manifest_root)
    corrupt_manifest = manifest_root / catalog_relative / _ARTIFACT_MANIFEST
    corrupt_manifest.write_bytes(b"{\"schema_version\":")

    data_root = negative_root / "data-corruption"
    _copy_tree_excluding(source_root, data_root)
    corrupt_data = data_root / catalog_relative / attribute_relative
    with corrupt_data.open("ab") as handle:
        handle.write(b" ")
        handle.flush()
        os.fsync(handle.fileno())

    missing_root = negative_root / "missing-required-file"
    excluded = (catalog_relative / attribute_relative).as_posix()
    _copy_tree_excluding(
        source_root,
        missing_root,
        excluded_relative_files=(excluded,),
    )

    partial_root = negative_root / "partial-publication"
    partial_directory = partial_root.joinpath(
        *catalog_relative_directory(key, checksum).parts
    )
    partial_directory.mkdir(parents=True)
    (partial_directory / _ARTIFACT_MANIFEST).write_bytes(
        b"{\"schema_version\":\"1.0\""
    )

    mismatch_key = BureauCatalogKey(
        provider=key.provider,
        product=key.product,
        edition=key.edition,
        dictionary_version=f"{key.dictionary_version}-mismatch",
    )
    wrong_checksum = ("0" if checksum[0] != "0" else "1") + checksum[1:]

    outcomes = {
        "manifest_corruption_rejected": _expect_failure(
            lambda: BureauCatalogStore(manifest_root).load_exact(key, checksum),
            (BureauCatalogIntegrityError,),
        ),
        "data_corruption_rejected": _expect_failure(
            lambda: BureauCatalogStore(data_root).load_exact(key, checksum),
            (BureauCatalogIntegrityError,),
        ),
        "missing_required_file_rejected": _expect_failure(
            lambda: BureauCatalogStore(missing_root).load_exact(key, checksum),
            (BureauCatalogIntegrityError,),
        ),
        "partial_publication_rejected": _expect_failure(
            lambda: BureauCatalogStore(partial_root).load_exact(key, checksum),
            (BureauCatalogIntegrityError,),
        ),
        "exact_version_mismatch_rejected": _expect_failure(
            lambda: BureauCatalogStore(source_root).load_exact(mismatch_key, checksum),
            (BureauCatalogNotFoundError,),
        ),
        "exact_checksum_mismatch_rejected": _expect_failure(
            lambda: BureauCatalogStore(source_root).load_exact(key, wrong_checksum),
            (BureauCatalogNotFoundError,),
        ),
    }
    return outcomes


def _run_safe_retry(
    *,
    pdf: Path,
    csv: Path,
    retry_root: Path,
    config: CatalogBuildConfig,
    expected_checksum: str,
) -> dict[str, Any]:
    original_write = builder_module._write_payload
    call_count = 0

    def fail_during_publication(path: Path, payload: bytes) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise CatalogBuildError("injected acceptance publication failure")
        original_write(path, payload)

    failed_closed = False
    builder_module._write_payload = fail_during_publication
    try:
        try:
            build_catalog(
                pdf_path=pdf,
                csv_path=csv,
                output_directory=retry_root,
                config=config,
            )
        except CatalogBuildError:
            failed_closed = True
    finally:
        builder_module._write_payload = original_write
    if not failed_closed:
        raise CatalogAcceptanceError("injected publication failure did not fail closed")

    expected_directory = retry_root.joinpath(
        *catalog_relative_directory(config.catalog_key(), expected_checksum).parts
    )
    if expected_directory.exists():
        raise CatalogAcceptanceError("failed publication exposed a final catalog")
    # Inspect names directly without emitting any path or source content.
    staging_directories = tuple(
        path
        for path in retry_root.rglob("*")
        if path.is_dir() and ".staging-" in path.name
    ) if retry_root.exists() else ()
    if staging_directories:
        raise CatalogAcceptanceError("failed publication left a staging directory")

    started = time.perf_counter()
    retried = build_catalog(
        pdf_path=pdf,
        csv_path=csv,
        output_directory=retry_root,
        config=config,
    )
    elapsed = time.perf_counter() - started
    if retried.catalog_checksum != expected_checksum:
        raise CatalogAcceptanceError("safe retry produced a different catalog identity")
    BureauCatalogStore(retry_root).load_exact(
        BureauCatalogKey.model_validate(config.catalog_key()),
        expected_checksum,
    )
    return {
        "injected_failure_rejected": True,
        "failed_final_not_published": True,
        "staging_cleanup_verified": True,
        "retry_succeeded": True,
        "retry_exact_checksum": True,
        "retry_elapsed_ms": round(elapsed * 1000.0, 6),
    }


def _write_summary(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise CatalogAcceptanceError("acceptance summary already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.staging-{os.getpid()}-{uuid.uuid4().hex}"
    encoded = (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise CatalogAcceptanceError("acceptance summary appeared during publication")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def run_acceptance(
    settings: AcceptanceSettings,
    *,
    workload: AcceptanceWorkload | None = None,
    build_function: Callable[..., CatalogBuildResult] = build_catalog,
) -> Mapping[str, Any]:
    """Run acceptance and return only aggregate, non-content results."""

    selected_workload = (workload or AcceptanceWorkload()).validate()
    pdf_source, csv_source = _ensure_external_root(settings)
    pdf = pdf_source.path
    csv = csv_source.path
    output_root = Path(settings.output_root).resolve(strict=True)
    summary_path = Path(settings.summary_path).resolve(strict=False)
    # Freeze one timestamp across every build so serialized artifacts, not only
    # normalized content checksums, must be byte-for-byte reproducible.
    config = settings.build_config()

    acceptance_started = time.perf_counter()
    if settings.resume_completed_builds:
        results, inventories, build_timings = _load_completed_builds(
            output_root=output_root,
            config=config,
            expected_checksum=settings.expected_catalog_checksum or "",
            pdf_source=pdf_source,
            csv_source=csv_source,
            explicit_built_at=settings.built_at,
        )
        build_execution_mode = "resumed_after_exact_verification"
        timing_scope = "resume_exact_integrity_verification"
    else:
        results, inventories, build_timings = _run_clean_builds(
            pdf=pdf,
            csv=csv,
            output_root=output_root,
            config=config,
            build_function=build_function,
        )
        build_execution_mode = "three_clean_builds"
        timing_scope = "clean_build_execution"

    first = results[0]
    key = BureauCatalogKey.model_validate(config.catalog_key())
    runtime = _run_runtime_workload(
        catalog_root=output_root / "deterministic-build-01",
        key=key,
        checksum=first.catalog_checksum,
        workload=selected_workload,
    )
    memory = _measure_representative_reload_memory(
        catalog_root=output_root / "deterministic-build-01",
        key=key,
        checksum=first.catalog_checksum,
    )
    integrity = _run_integrity_failures(
        source_root=output_root / "deterministic-build-01",
        catalog_directory=first.output_directory,
        key=key,
        checksum=first.catalog_checksum,
        negative_root=output_root / "negative-integrity-tests",
    )
    retry = _run_safe_retry(
        pdf=pdf,
        csv=csv,
        retry_root=output_root / "safe-retry",
        config=config,
        expected_checksum=first.catalog_checksum,
    )
    elapsed = time.perf_counter() - acceptance_started

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "content_logged": False,
        "source_content_in_summary": False,
        "catalog": {
            "catalog_id": first.catalog_id,
            "catalog_checksum": first.catalog_checksum,
            "dictionary_version": key.dictionary_version,
            "attribute_count": first.attribute_count,
            "special_value_count": first.special_value_count,
            "validation_finding_count": first.validation_finding_count,
            "validation_status": first.validation_status,
        },
        "source_fingerprints": {
            "canonical_pdf_sha256": _safe_sha256(pdf),
            "canonical_pdf_size_bytes": pdf.stat().st_size,
            "csv_staging_sha256": _safe_sha256(csv),
            "csv_staging_size_bytes": csv.stat().st_size,
        },
        "deterministic_builds": {
            "requested": 3,
            "completed": len(results),
            "execution_mode": build_execution_mode,
            "resumed_after_exact_verification": settings.resume_completed_builds,
            "catalog_checksums_equal": len(
                {result.catalog_checksum for result in results}
            )
            == 1,
            "artifact_hashes_equal": all(
                dict(inventory.hashes) == dict(inventories[0].hashes)
                for inventory in inventories[1:]
            ),
            "timing_scope": timing_scope,
            "timing": _timing_summary(build_timings),
            "artifact_hashes": dict(inventories[0].hashes),
            "artifact_sizes_bytes": dict(inventories[0].sizes),
            "artifact_total_bytes": inventories[0].total_bytes,
        },
        "runtime_workload": runtime,
        "integrity_failures": integrity,
        "safe_retry": retry,
        "performance": {
            "total_elapsed_ms": round(elapsed * 1000.0, 6),
            "memory_measurement": memory,
        },
        "exact_only": True,
        "latest_or_first_fallback_used": False,
        "full_catalog_export_used": False,
    }
    _write_summary(summary_path, summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--edition", required=True)
    parser.add_argument("--dictionary-version", required=True)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--built-by", required=True)
    parser.add_argument("--source-control-commit", required=True)
    parser.add_argument("--catalog-id")
    parser.add_argument("--built-at")
    parser.add_argument(
        "--resume-completed-builds",
        action="store_true",
        help=(
            "Resume only after exact verification of deterministic-build-01..03; "
            "requires --expected-catalog-checksum."
        ),
    )
    parser.add_argument("--expected-catalog-checksum")
    return parser


def _safe_failure(error_type: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error_type": error_type,
            "error": "catalog acceptance did not complete; inspect restricted diagnostics",
            "content_logged": False,
        },
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = AcceptanceSettings(
        pdf_path=args.pdf,
        csv_path=args.csv,
        output_root=args.output_root,
        summary_path=args.summary_json,
        provider=args.provider,
        product=args.product,
        edition=args.edition,
        dictionary_version=args.dictionary_version,
        policy_id=args.policy_id,
        policy_version=args.policy_version,
        built_by=args.built_by,
        source_control_commit=args.source_control_commit,
        catalog_id=args.catalog_id,
        built_at=args.built_at,
        resume_completed_builds=args.resume_completed_builds,
        expected_catalog_checksum=args.expected_catalog_checksum,
    )
    try:
        summary = run_acceptance(settings)
    except Exception as exc:
        # Parser and validation exceptions may retain licensed fragments.  The
        # CLI deliberately emits only the safe exception class.
        print(_safe_failure(type(exc).__name__))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "catalog_checksum": summary["catalog"]["catalog_checksum"],
                "attribute_count": summary["catalog"]["attribute_count"],
                "special_value_count": summary["catalog"]["special_value_count"],
                "deterministic_builds": summary["deterministic_builds"]["completed"],
                "reloads": summary["runtime_workload"]["reloads"]["completed"],
                "exact_attribute_lookups": summary["runtime_workload"][
                    "exact_attribute_lookups"
                ]["completed"],
                "value_classifications": summary["runtime_workload"][
                    "value_classifications"
                ]["completed"],
                "reader_workers": summary["runtime_workload"]["concurrent_readers"][
                    "workers_completed"
                ],
                "content_logged": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
