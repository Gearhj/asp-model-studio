"""Build target-free, development-only evidence for the MLB V1 prior authority.

This command is a preprocessing diagnostic.  It never requests ``outcome``,
never opens a final-OOT row (the Stage 3 scanner injects the development date
predicate), and never fits or registers a predictive model.
"""
from __future__ import annotations

import argparse
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
from server.sports_current_statcast import stage3_player_prior_authority as prior
from server.sports_datasets.consumer import canonical_json_bytes


DEFAULT_DATABASE = Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db")
DEFAULT_OUTPUT_ROOT = Path(
    r".runtime\asp-model-studio\stage3-player-prior-authorities"
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
        # Keep the diagnostic dependency-free on the governed Windows host.
        # GetProcessMemoryInfo reports the process working set in bytes.
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
        raise RuntimeError("Development evidence has too few dates for five benchmark folds.")
    # The project has committed to five date-atomic expanding folds but has not
    # registered exact Stage 3 boundaries.  These deterministic 1/6 blocks are
    # timing-only benchmarks; they do not select, tune, score, or persist a
    # split contract.
    edges = [unique_dates[min(len(unique_dates) - 1, (len(unique_dates) * index) // 6)] for index in range(1, 6)]
    ends = edges[1:] + [unique_dates[-1]]
    return [
        {
            "foldId": f"PERFORMANCE_BENCHMARK_FOLD_{index}",
            "trainEnd": train_end,
            "validationStart": unique_dates[unique_dates.index(train_end) + 1],
            "validationEnd": validation_end,
        }
        for index, (train_end, validation_end) in enumerate(zip(edges, ends, strict=True), start=1)
    ]


def _atomic_content_addressed_write(root: Path, payload: dict[str, Any]) -> tuple[Path, int, str]:
    content = canonical_json_bytes(payload)
    digest = hashlib.sha256(content).hexdigest()
    target = root / "objects" / "sha256" / digest / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != content:
            raise RuntimeError(f"Existing content-addressed artifact does not match {digest}.")
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
        raise RuntimeError("A project-bound diagnostic artifact requires projectId.")
    pointer = root / "projects" / project_id / "current.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer_payload = canonical_json_bytes(
        {
            "schemaVersion": "MLB_PLAYER_STATE_PRIOR_DIAGNOSTIC_POINTER_V1",
            "artifactSha256": digest,
            "manifestPath": str(target.resolve()),
        }
    )
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer_tmp = pointer.with_name(
        f".{pointer.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        pointer_tmp.write_bytes(pointer_payload)
        pointer_tmp.replace(pointer)
    finally:
        pointer_tmp.unlink(missing_ok=True)
    return target, len(content), digest


def main() -> int:
    args = _arguments()
    database = Database(args.database)
    project = ProjectRepository(database).get(args.project_id)
    if not project:
        raise RuntimeError(f"Project {args.project_id} does not exist in live persistence.")
    authority = eda._resolve_authority(database, args.project_id)
    compiled = treatment_spec.compile_project_specification(database, args.project_id)
    authority_manifest = dict(compiled["priorAuthority"])
    features = sorted(prior.SUPPORTED_PRIOR_FEATURES)
    columns = list(prior.required_input_columns(features))
    # Missing-reason columns are optional in V1 physical Gold. When a future
    # registered schema materializes them, include them so explicit source and
    # computation failures are excluded from fitted population evidence.
    for feature in features:
        binding = prior.feature_binding(feature) or {}
        reason_column = str(binding.get("missingReasonFeature") or "")
        if reason_column and reason_column in authority.schema.names:
            columns.append(reason_column)
    columns = sorted(set(columns))
    if "outcome" in columns:
        raise RuntimeError("Target outcome entered the prior diagnostic scan contract.")

    scan_started = time.perf_counter()
    rss_before = _rss_bytes()
    frame = eda._scan(authority, columns, {})
    scan_ms = (time.perf_counter() - scan_started) * 1000.0
    rss_after_scan = _rss_bytes()
    dates = pd.to_datetime(frame["game_date"], errors="raise")
    if len(frame) != eda.DEVELOPMENT_ROWS or dates.max() > pd.Timestamp(prior.DEVELOPMENT_END):
        raise RuntimeError("Development-only prior scan failed its population boundary.")

    fold_performance: list[dict[str, Any]] = []
    for boundary in _fold_boundaries(dates):
        fit_started = time.perf_counter()
        fitted = prior.fit_prior_authority(
            frame,
            training_end=boundary["trainEnd"],
            authority_manifest=authority_manifest,
            fold_id=boundary["foldId"],
            features=features,
        )
        fit_ms = (time.perf_counter() - fit_started) * 1000.0
        validation_mask = dates.between(
            pd.Timestamp(boundary["validationStart"]),
            pd.Timestamp(boundary["validationEnd"]),
            inclusive="both",
        )
        validation = frame.loc[validation_mask]
        transform_started = time.perf_counter()
        derived_cells = 0
        for feature in features:
            transformed = prior.transform_prior_feature(validation, fitted, feature)
            derived_cells += int(transformed.shape[0] * transformed.shape[1])
        transform_ms = (time.perf_counter() - transform_started) * 1000.0
        fold_performance.append(
            {
                **boundary,
                "trainingRows": fitted["trainingRows"],
                "validationRows": int(validation_mask.sum()),
                "fitTimeMs": round(fit_ms, 3),
                "transformTimeMs": round(transform_ms, 3),
                "derivedCellsEvaluated": derived_cells,
                "fittedChecksum": fitted["fittedChecksum"],
            }
        )

    final_fit_started = time.perf_counter()
    final_fit = prior.fit_prior_authority(
        frame,
        training_end=prior.DEVELOPMENT_END,
        authority_manifest=authority_manifest,
        fold_id="FINAL_DEVELOPMENT_ONLY",
        features=features,
    )
    final_fit_ms = (time.perf_counter() - final_fit_started) * 1000.0
    diagnostics_started = time.perf_counter()
    diagnostics = prior.development_diagnostics(frame, final_fit, features=features)
    diagnostic_ms = (time.perf_counter() - diagnostics_started) * 1000.0
    rss_after_diagnostics = _rss_bytes()
    observed_rss = [
        value
        for value in (rss_before, rss_after_scan, rss_after_diagnostics)
        if value is not None
    ]
    rss_peak_observed = max(observed_rss) if observed_rss else None

    stable_final_fit = {
        key: value for key, value in final_fit.items() if key != "fitDurationMs"
    }
    stable_diagnostics = {
        key: value for key, value in diagnostics.items() if key != "durationMs"
    }
    fold_evidence = [
        {
            key: value
            for key, value in item.items()
            if key not in {"fitTimeMs", "transformTimeMs"}
        }
        for item in fold_performance
    ]
    artifact = {
        "schemaVersion": "MLB_PLAYER_STATE_PRIOR_AUTHORITY_EVIDENCE_V1",
        "projectId": args.project_id,
        "projectName": str(project.get("project_name") or args.project_id),
        "authority": authority_manifest,
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
        "fittedFinalDevelopmentAuthority": stable_final_fit,
        "diagnostics": stable_diagnostics,
        "foldEvidence": fold_evidence,
        "audit": {
            "preprocessingFits": 6,
            "modelFits": 0,
            "scores": 0,
            "calibrations": 0,
            "promotions": 0,
            "featureSetsRegistered": 0,
            "sourceRowsMutated": 0,
            "goldRowsMutated": 0,
            "finalOotRowsOpened": 0,
            "finalOotTargetsAccessed": False,
        },
    }
    path, artifact_size, digest = _atomic_content_addressed_write(
        args.output_root, artifact
    )
    performance_receipt = {
        "schemaVersion": "MLB_PLAYER_STATE_PRIOR_PERFORMANCE_RECEIPT_V1",
        "projectId": args.project_id,
        "authorityId": authority_manifest["authorityId"],
        "scientificEvidenceSha256": digest,
        "scanTimeMs": round(scan_ms, 3),
        "foldBenchmarks": fold_performance,
        "finalDevelopmentFitTimeMs": round(final_fit_ms, 3),
        "finalDevelopmentDiagnosticTransformTimeMs": round(diagnostic_ms, 3),
        "inputFrameBytes": int(frame.memory_usage(index=True, deep=True).sum()),
        "rssBeforeBytes": rss_before,
        "rssAfterScanBytes": rss_after_scan,
        "rssAfterDiagnosticsBytes": rss_after_diagnostics,
        "peakObservedRssBytes": rss_peak_observed,
        "memoryMeasurement": "PROCESS_WORKING_SET_SAMPLED_AT_PHASE_BOUNDARIES",
        "implementation": "VECTORIZED_NUMPY_PANDAS_FEATURE_BATCHES_NO_ROW_LOOPS",
        "finalOotRowsRead": 0,
        "modelFits": 0,
    }
    performance_path, performance_size, performance_digest = (
        _atomic_content_addressed_write(
            args.output_root / "performance-runs", performance_receipt
        )
    )
    print(
        json.dumps(
            {
                "artifactSha256": digest,
                "artifactPath": str(path.resolve()),
                "artifactSizeBytes": artifact_size,
                "performanceReceiptSha256": performance_digest,
                "performanceReceiptPath": str(performance_path.resolve()),
                "performanceReceiptSizeBytes": performance_size,
                "rows": len(frame),
                "features": len(features),
                "finalFitMs": round(final_fit_ms, 3),
                "diagnosticsMs": round(diagnostic_ms, 3),
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
