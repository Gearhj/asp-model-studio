"""Benchmark the target-free MLB interaction recomputation authority.

The command requests only the registered parent, governance-indicator, and
date columns.  The Stage 3 scanner applies its development predicate before
materialization, and the authority rejects final-OOT dates before reading
parent values.  This diagnostic fits preprocessing parameters only; it never
fits, scores, calibrates, registers, or promotes a predictive model.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.persistence.db import Database
from server.persistence.repositories.project_repository import ProjectRepository
from server.sports_current_statcast import stage3_eda as eda
from server.sports_current_statcast import stage3_feature_treatment_spec as treatment_spec
from server.sports_current_statcast import (
    stage3_interaction_recomputation_authority as interactions,
)
from server.sports_datasets.consumer import canonical_json_bytes


DEFAULT_DATABASE = Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db")
DEFAULT_OUTPUT_ROOT = Path(
    r".runtime\asp-model-studio\stage3-interaction-authorities"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="asp-mtlozhdx")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def _rss_bytes() -> int | None:
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("pageFaultCount", wintypes.DWORD),
                    ("peakWorkingSetSize", ctypes.c_size_t),
                    ("workingSetSize", ctypes.c_size_t),
                    ("quotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("quotaPagedPoolUsage", ctypes.c_size_t),
                    ("quotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("quotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("pagefileUsage", ctypes.c_size_t),
                    ("peakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            get_current_process = ctypes.windll.kernel32.GetCurrentProcess
            get_current_process.restype = wintypes.HANDLE
            get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
            get_process_memory_info.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            ]
            get_process_memory_info.restype = wintypes.BOOL
            process = get_current_process()
            ok = get_process_memory_info(
                process, ctypes.byref(counters), counters.cb
            )
            return int(counters.workingSetSize) if ok else None
        except (AttributeError, OSError, ValueError):
            return None
    return None


def _fold_boundaries(dates: pd.Series) -> list[dict[str, str]]:
    unique_dates = sorted(
        pd.Timestamp(value).date().isoformat() for value in dates.dropna().unique()
    )
    if len(unique_dates) < 12:
        raise RuntimeError("Development evidence has too few dates for five folds.")
    edges = [
        unique_dates[min(len(unique_dates) - 1, (len(unique_dates) * index) // 6)]
        for index in range(1, 6)
    ]
    ends = edges[1:] + [unique_dates[-1]]
    return [
        {
            "foldId": f"INTERACTION_PERFORMANCE_FOLD_{index}",
            "trainEnd": train_end,
            "validationStart": unique_dates[unique_dates.index(train_end) + 1],
            "validationEnd": validation_end,
        }
        for index, (train_end, validation_end) in enumerate(
            zip(edges, ends, strict=True), start=1
        )
    ]


def _atomic_content_addressed_write(
    root: Path, payload: dict[str, Any], *, pointer_schema: str
) -> tuple[Path, int, str]:
    content = canonical_json_bytes(payload)
    digest = hashlib.sha256(content).hexdigest()
    target = root / "objects" / "sha256" / digest / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != content:
            raise RuntimeError(f"Existing artifact does not match {digest}.")
    else:
        temporary = target.with_name(
            f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    project_id = str(payload.get("projectId") or "").strip()
    if not project_id:
        raise RuntimeError("A project-bound artifact requires projectId.")
    pointer = root / "projects" / project_id / "current.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer_content = canonical_json_bytes(
        {
            "schemaVersion": pointer_schema,
            "artifactSha256": digest,
            "manifestPath": str(target.resolve()),
        }
    )
    pointer_tmp = pointer.with_name(
        f".{pointer.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        pointer_tmp.write_bytes(pointer_content)
        pointer_tmp.replace(pointer)
    finally:
        pointer_tmp.unlink(missing_ok=True)
    return target, len(content), digest


def _stable_fitted(fitted: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fitted.items() if key != "fitDurationMs"}


def main() -> int:
    args = _arguments()
    database = Database(args.database)
    project = ProjectRepository(database).get(args.project_id)
    if not project:
        raise RuntimeError(f"Project {args.project_id} does not exist.")

    compilation_started = time.perf_counter()
    compiled = treatment_spec.compile_project_specification(database, args.project_id)
    compilation_ms = (time.perf_counter() - compilation_started) * 1000.0
    authority = eda._resolve_authority(database, args.project_id)
    authority_manifest = dict(compiled["interactionAuthority"])
    features = list(interactions.INTERACTION_FEATURES)
    columns = list(interactions.required_input_columns(features))
    forbidden_targets = {"outcome", "target", "label", "actual"}
    if forbidden_targets.intersection(columns):
        raise RuntimeError("A target column entered the interaction scan contract.")
    unknown = sorted(set(columns) - set(authority.schema.names))
    if unknown:
        raise RuntimeError(f"Required registered parent columns are absent: {unknown}.")

    rss_samples: list[dict[str, Any]] = []

    def sample(label: str) -> None:
        rss_samples.append({"phase": label, "rssBytes": _rss_bytes()})

    sample("BEFORE_SCAN")
    scan_started = time.perf_counter()
    frame = eda._scan(authority, columns, {})
    scan_ms = (time.perf_counter() - scan_started) * 1000.0
    sample("AFTER_SCAN")
    dates = pd.to_datetime(frame["game_date"], errors="raise")
    if (
        len(frame) != eda.DEVELOPMENT_ROWS
        or dates.min() < pd.Timestamp(interactions.DEVELOPMENT_START)
        or dates.max() > pd.Timestamp(interactions.DEVELOPMENT_END)
    ):
        raise RuntimeError("Development-only scan failed its registered boundary.")

    fold_performance: list[dict[str, Any]] = []
    fold_evidence: list[dict[str, Any]] = []
    for boundary in _fold_boundaries(dates):
        fit_started = time.perf_counter()
        fitted = interactions.fit_interaction_authority(
            frame,
            training_end=boundary["trainEnd"],
            authority_manifest=authority_manifest,
            fold_id=boundary["foldId"],
            model_family="LINEAR",
            features=features,
            scale_interactions=True,
        )
        fit_ms = (time.perf_counter() - fit_started) * 1000.0
        training_mask = dates.le(pd.Timestamp(boundary["trainEnd"]))
        validation_mask = dates.between(
            pd.Timestamp(boundary["validationStart"]),
            pd.Timestamp(boundary["validationEnd"]),
            inclusive="both",
        )
        transform_started = time.perf_counter()
        transformed_training = interactions.transform_interactions(
            frame.loc[training_mask], fitted, features=features
        )
        transformed_validation = interactions.transform_interactions(
            frame.loc[validation_mask], fitted, features=features
        )
        transform_ms = (time.perf_counter() - transform_started) * 1000.0
        transformed_rows = len(transformed_training) + len(transformed_validation)
        if transformed_training.shape[1] != len(features) * 4:
            raise RuntimeError("Fold transform output contract changed unexpectedly.")
        sample(f"AFTER_{boundary['foldId']}")
        fold_performance.append(
            {
                **boundary,
                "trainingRows": int(training_mask.sum()),
                "validationRows": int(validation_mask.sum()),
                "fitTimeMs": round(fit_ms, 3),
                "trainingAndValidationTransformTimeMs": round(transform_ms, 3),
                "transformedRows": transformed_rows,
                "derivedCellsEvaluated": int(
                    transformed_rows * transformed_training.shape[1]
                ),
                "fittedChecksum": fitted["fittedChecksum"],
            }
        )
        fold_evidence.append(
            {
                **boundary,
                "trainingRows": int(training_mask.sum()),
                "validationRows": int(validation_mask.sum()),
                "transformedRows": transformed_rows,
                "fittedChecksum": fitted["fittedChecksum"],
            }
        )
        del transformed_training, transformed_validation, fitted
        gc.collect()

    final_fit_started = time.perf_counter()
    final_fit = interactions.fit_interaction_authority(
        frame,
        training_end=interactions.DEVELOPMENT_END,
        authority_manifest=authority_manifest,
        fold_id="FINAL_DEVELOPMENT_ONLY",
        model_family="LINEAR",
        features=features,
        scale_interactions=True,
    )
    final_fit_ms = (time.perf_counter() - final_fit_started) * 1000.0
    full_transform_started = time.perf_counter()
    full_transformed = interactions.transform_interactions(
        frame, final_fit, features=features
    )
    full_transform_ms = (time.perf_counter() - full_transform_started) * 1000.0
    sample("AFTER_FULL_DEVELOPMENT_TRANSFORM")
    if len(full_transformed) != eda.DEVELOPMENT_ROWS:
        raise RuntimeError("Full-development transform changed row cardinality.")

    authority_path, authority_size, authority_object_sha = (
        _atomic_content_addressed_write(
            args.output_root / "authority-manifests",
            authority_manifest,
            pointer_schema="MLB_INTERACTION_AUTHORITY_POINTER_V1",
        )
    )
    evidence = {
        "schemaVersion": "MLB_INTERACTION_RECOMPUTATION_EVIDENCE_V1",
        "projectId": args.project_id,
        "projectName": str(project.get("project_name") or args.project_id),
        "authorityId": authority_manifest["authorityId"],
        "authorityChecksum": authority_manifest["authorityChecksum"],
        "authorityObjectSha256": authority_object_sha,
        "treatmentSpecificationId": compiled["specificationId"],
        "gold": {
            "datasetId": authority.public()["goldDatasetId"],
            "manifestSha256": authority.gold_manifest_sha,
            "contextualManifestSha256": authority.contextual_manifest_sha,
            "rowsRead": len(frame),
            "rowsMutated": 0,
        },
        "population": {
            "developmentStart": dates.min().date().isoformat(),
            "developmentEnd": dates.max().date().isoformat(),
            "developmentRows": len(frame),
            "finalOotRowsRead": 0,
            "targetColumnsRequested": [],
        },
        "features": features,
        "finalDevelopmentPreprocessor": _stable_fitted(final_fit),
        "foldEvidence": fold_evidence,
        "audit": {
            "preprocessingFits": 6,
            "modelFits": 0,
            "scores": 0,
            "calibrations": 0,
            "promotions": 0,
            "featureSetsRegistered": 0,
            "gameScoringJobs": 0,
            "goldRowsMutated": 0,
            "finalOotRowsOpened": 0,
            "finalOotTargetsAccessed": False,
        },
    }
    evidence_path, evidence_size, evidence_sha = _atomic_content_addressed_write(
        args.output_root,
        evidence,
        pointer_schema="MLB_INTERACTION_EVIDENCE_POINTER_V1",
    )
    rss_values = [
        int(item["rssBytes"])
        for item in rss_samples
        if item["rssBytes"] is not None
    ]
    performance = {
        "schemaVersion": "MLB_INTERACTION_RECOMPUTATION_PERFORMANCE_V1",
        "projectId": args.project_id,
        "authorityId": authority_manifest["authorityId"],
        "scientificEvidenceSha256": evidence_sha,
        "authorityCompilationTimeMs": round(compilation_ms, 3),
        "developmentScanTimeMs": round(scan_ms, 3),
        "foldBenchmarks": fold_performance,
        "finalDevelopmentFitTimeMs": round(final_fit_ms, 3),
        "fullDevelopmentTransformTimeMs": round(full_transform_ms, 3),
        "inputFrameBytes": int(frame.memory_usage(index=True, deep=True).sum()),
        "fullTransformFrameBytes": int(
            full_transformed.memory_usage(index=True, deep=True).sum()
        ),
        "rssSamples": rss_samples,
        "peakSampledRssBytes": max(rss_values) if rss_values else None,
        "memoryMeasurement": "PROCESS_RSS_SAMPLED_AT_PHASE_BOUNDARIES",
        "authorityArtifactSizeBytes": authority_size,
        "authorityArtifactPath": str(authority_path.resolve()),
        "scientificEvidenceArtifactSizeBytes": evidence_size,
        "implementation": "VECTORIZED_NUMPY_PANDAS_NO_ROW_LOOPS",
        "finalOotRowsRead": 0,
        "modelFits": 0,
    }
    performance_path, performance_size, performance_sha = (
        _atomic_content_addressed_write(
            args.output_root / "performance-runs",
            performance,
            pointer_schema="MLB_INTERACTION_PERFORMANCE_POINTER_V1",
        )
    )
    print(
        json.dumps(
            {
                "authorityId": authority_manifest["authorityId"],
                "authorityChecksum": authority_manifest["authorityChecksum"],
                "authorityArtifactSizeBytes": authority_size,
                "authorityArtifactPath": str(authority_path.resolve()),
                "evidenceSha256": evidence_sha,
                "evidencePath": str(evidence_path.resolve()),
                "evidenceSizeBytes": evidence_size,
                "performanceReceiptSha256": performance_sha,
                "performanceReceiptPath": str(performance_path.resolve()),
                "performanceReceiptSizeBytes": performance_size,
                "authorityCompilationTimeMs": round(compilation_ms, 3),
                "developmentScanTimeMs": round(scan_ms, 3),
                "fullDevelopmentFitTimeMs": round(final_fit_ms, 3),
                "fullDevelopmentTransformTimeMs": round(full_transform_ms, 3),
                "peakSampledRssBytes": max(rss_values) if rss_values else None,
                "foldBenchmarks": fold_performance,
                "developmentRows": len(frame),
                "finalOotRowsRead": 0,
                "modelFits": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
