"""Fit and publish the governed MLB Wave 2 player-state prior authority.

This command reads authenticated development-only feature evidence.  It does
not request a target, open final-OOT payload, fit a predictive model, register
a feature set, or adopt a treatment policy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
from server.sports_current_statcast import stage3_player_prior_authority as prior_v1
from server.sports_current_statcast import stage3_player_prior_authority_v2 as prior_v2
from server.sports_current_statcast.stage3_player_prior_artifact_store_v2 import (
    DEFAULT_AUTHORITY_ROOT,
    publish_artifact,
    publish_current_bundle,
)


DEFAULT_DATABASE = Path(r"C:\Users\james\asp-model-studio\.runtime\asp-model-studio\persistence\asp_model_studio.db")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="asp-mtlozhdx")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_AUTHORITY_ROOT)
    return parser.parse_args()


def _rss_bytes() -> int | None:
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            process = kernel32.GetCurrentProcess()
            ok = psapi.GetProcessMemoryInfo(
                process, ctypes.byref(counters), counters.cb
            )
            return int(counters.WorkingSetSize) if ok else None
        except (AttributeError, OSError, TypeError, ValueError):
            return None


def _merge_development(
    gold: pd.DataFrame, companion: pd.DataFrame
) -> pd.DataFrame:
    if len(gold) != prior_v2.DEVELOPMENT_ROWS or len(companion) != prior_v2.DEVELOPMENT_ROWS:
        raise RuntimeError("Gold/companion development row count differs.")
    joined = gold.merge(
        companion,
        on="canonicalPaId",
        how="inner",
        validate="one_to_one",
        suffixes=("", "__companion"),
        sort=False,
    )
    for column in ("game_date", "season", "datasetRole"):
        companion_column = f"{column}__companion"
        if not joined[column].astype(str).equals(joined[companion_column].astype(str)):
            raise RuntimeError(f"Gold/companion {column} identity differs.")
        joined = joined.drop(columns=[companion_column])
    if len(joined) != prior_v2.DEVELOPMENT_ROWS:
        raise RuntimeError("Gold/companion development join is not one-to-one.")
    return joined


def _final_fold_record(frame: pd.DataFrame) -> dict[str, Any]:
    dates = pd.to_datetime(frame["game_date"], errors="raise")
    content = {
        "foldId": "FINAL_DEVELOPMENT",
        "foldNumber": 0,
        "trainStart": dates.min().date().isoformat(),
        "trainEnd": dates.max().date().isoformat(),
        "validationStart": None,
        "validationEnd": None,
        "trainRows": len(frame),
        "validationRows": 0,
        "trainGames": int(frame["canonicalGameId"].nunique()),
        "validationGames": 0,
        "trainingMembershipChecksum": prior_v2._membership_checksum(frame),
        "preprocessingFitScope": "ALL_AUTHORIZED_DEVELOPMENT_ROWS_ONLY",
        "validationStatisticsUsedForTraining": False,
        "finalOotUsed": False,
    }
    return {**content, "checksum": prior_v2._sha256(content)}


def _project_v1_manifest(
    authority: Any,
    source: dict[str, Any],
    companion_binding: dict[str, Any],
) -> dict[str, Any]:
    return prior_v1.project_authority_manifest(
        authority,
        treatment_specification_key=treatment_spec.SPECIFICATION_KEY,
        treatment_source_sha256=str(source["source_content_sha256"]),
        sufficient_statistics_authority=companion_binding,
    )


def main() -> int:
    args = _arguments()
    database = Database(args.database)
    project = ProjectRepository(database).get(args.project_id)
    if not project:
        raise RuntimeError(f"Project {args.project_id} does not exist.")
    authority = eda._resolve_authority(database, args.project_id)
    source = treatment_spec.load_source_specification()
    rss_before = _rss_bytes()

    authentication_started = time.perf_counter()
    authentication = prior_v2.authenticate_companion(database, authority)
    authentication_ms = (time.perf_counter() - authentication_started) * 1000.0
    companion_binding = dict(authentication["bindingAuthority"])
    v1_manifest = _project_v1_manifest(authority, source, companion_binding)

    companion_started = time.perf_counter()
    companion = prior_v2.load_authenticated_development_companion(authentication)
    companion_scan_ms = (time.perf_counter() - companion_started) * 1000.0
    gold_columns = [
        "canonicalPaId",
        "canonicalGameId",
        "game_date",
        "season",
        "datasetRole",
        "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId",
        "batter_prior_missing",
        "pitcher_prior_missing",
        "batter_last100_insufficient",
        "batter_last100_whiff_missing",
        "pitcher_last250_insufficient",
        "pitcher_last250_whiff_missing",
        "pitcher_last250_velocity_missing",
    ]
    if "outcome" in gold_columns:
        raise RuntimeError("Target entered the Wave 2 Gold projection.")
    gold_started = time.perf_counter()
    gold = eda._scan(authority, gold_columns, {})
    gold_scan_ms = (time.perf_counter() - gold_started) * 1000.0
    frame = _merge_development(gold, companion)
    dates = pd.to_datetime(frame["game_date"], errors="raise")
    if dates.max() > pd.Timestamp(prior_v2.DEVELOPMENT_END):
        raise RuntimeError("Development frame crosses final OOT.")

    fold_contract = prior_v2.bind_fold_contract_project(
        prior_v2.build_five_fold_contract(frame), args.project_id
    )
    fold_contract_receipt = publish_artifact(fold_contract, root=args.output_root)
    definition = prior_v2.build_authority_definition(
        authority,
        v1_authority_manifest=v1_manifest,
        companion_authentication=authentication,
        treatment_specification_key=treatment_spec.SPECIFICATION_KEY,
        treatment_source_sha256=str(source["source_content_sha256"]),
        compiler_version=str(source["compiler_version"]),
        compiler_sha256=treatment_spec._normalized_file_sha256(Path(treatment_spec.__file__)),
    )
    definition_receipt = publish_artifact(definition, root=args.output_root)

    fold_children: list[dict[str, Any]] = []
    fold_receipts: list[dict[str, Any]] = []
    fold_performance: list[dict[str, Any]] = []
    for fold in fold_contract["folds"]:
        family_fit_ms: dict[str, float] = {}
        fit_started = time.perf_counter()
        child = prior_v2.fit_fold_authority(
            frame,
            definition,
            fold,
            fold_contract_id=fold_contract["contractId"],
            fold_contract_checksum=fold_contract["contractChecksum"],
            scope_kind="CHRONOLOGICAL_FOLD",
            performance_sink=family_fit_ms,
        )
        fit_ms = (time.perf_counter() - fit_started) * 1000.0
        child_receipt = publish_artifact(child, root=args.output_root)
        training = frame.loc[
            dates.between(pd.Timestamp(fold["trainStart"]), pd.Timestamp(fold["trainEnd"]), inclusive="both")
        ]
        validation = frame.loc[
            dates.between(pd.Timestamp(fold["validationStart"]), pd.Timestamp(fold["validationEnd"]), inclusive="both")
        ]
        family_transform_ms: dict[str, dict[str, float]] = {}
        derived_cells = 0
        for family_id in prior_v2._FAMILIES:
            training_started = time.perf_counter()
            train_output = prior_v2.transform_prior_family(training, child, family_id)
            training_ms = (time.perf_counter() - training_started) * 1000.0
            validation_started = time.perf_counter()
            validation_output = prior_v2.transform_prior_family(validation, child, family_id)
            validation_ms = (time.perf_counter() - validation_started) * 1000.0
            derived_cells += int(train_output.size + validation_output.size)
            family_transform_ms[family_id] = {
                "trainingMs": round(training_ms, 3),
                "validationMs": round(validation_ms, 3),
            }
            del train_output, validation_output
        fold_children.append(child)
        fold_receipts.append(child_receipt)
        fold_performance.append(
            {
                "foldId": fold["foldId"],
                "trainingRows": len(training),
                "validationRows": len(validation),
                "fitTimeMs": round(fit_ms, 3),
                "familyFitTimeMs": family_fit_ms,
                "familyTransformTimeMs": family_transform_ms,
                "derivedCellsEvaluated": derived_cells,
                "fittedId": child["fittedId"],
                "fittedChecksum": child["fittedChecksum"],
                "artifactSha256": child_receipt["sha256"],
            }
        )

    final_record = _final_fold_record(frame)
    final_family_fit_ms: dict[str, float] = {}
    final_fit_started = time.perf_counter()
    final_child = prior_v2.fit_fold_authority(
        frame,
        definition,
        final_record,
        fold_contract_id=fold_contract["contractId"],
        fold_contract_checksum=fold_contract["contractChecksum"],
        scope_kind="FINAL_DEVELOPMENT",
        performance_sink=final_family_fit_ms,
    )
    final_fit_ms = (time.perf_counter() - final_fit_started) * 1000.0
    final_receipt = publish_artifact(final_child, root=args.output_root)

    full_transform_started = time.perf_counter()
    final_family_transform_ms: dict[str, float] = {}
    full_derived_cells = 0
    for family_id in prior_v2._FAMILIES:
        family_started = time.perf_counter()
        output = prior_v2.transform_prior_family(frame, final_child, family_id)
        final_family_transform_ms[family_id] = round(
            (time.perf_counter() - family_started) * 1000.0, 3
        )
        full_derived_cells += int(output.size)
        del output
    full_transform_ms = (time.perf_counter() - full_transform_started) * 1000.0

    diagnostics_started = time.perf_counter()
    diagnostics = prior_v2.development_diagnostics(frame, final_child)
    diagnostics_ms = (time.perf_counter() - diagnostics_started) * 1000.0
    diagnostics_receipt = publish_artifact(diagnostics, root=args.output_root)

    bundle = prior_v2.assemble_fit_bundle(
        definition,
        fold_children,
        final_child,
        fold_contract=fold_contract,
        definition_artifact_sha256=definition_receipt["sha256"],
        fold_contract_artifact_sha256=fold_contract_receipt["sha256"],
        fold_artifact_sha256=[item["sha256"] for item in fold_receipts],
        final_artifact_sha256=final_receipt["sha256"],
    )
    prior_v2._validate_bundle(
        bundle, expected_definition=definition, root=args.output_root
    )
    bundle_receipt = publish_current_bundle(
        args.project_id, bundle, root=args.output_root
    )
    rss_after = _rss_bytes()
    science_bytes = sum(
        int(item["byteCount"])
        for item in [
            fold_contract_receipt,
            definition_receipt,
            *fold_receipts,
            final_receipt,
            diagnostics_receipt,
            bundle_receipt,
        ]
    )
    performance = {
        "schemaVersion": "MLB_PLAYER_STATE_PRIOR_V2_PERFORMANCE_RECEIPT_V1",
        "projectId": args.project_id,
        "authorityId": bundle["authorityId"],
        "authorityChecksum": bundle["authorityChecksum"],
        "bundleArtifactSha256": bundle_receipt["sha256"],
        "companionAuthenticationTimeMs": round(authentication_ms, 3),
        "companionDevelopmentScanTimeMs": round(companion_scan_ms, 3),
        "goldDevelopmentProjectionTimeMs": round(gold_scan_ms, 3),
        "folds": fold_performance,
        "finalDevelopmentFitTimeMs": round(final_fit_ms, 3),
        "finalDevelopmentFamilyFitTimeMs": final_family_fit_ms,
        "fullDevelopmentTransformTimeMs": round(full_transform_ms, 3),
        "fullDevelopmentFamilyTransformTimeMs": final_family_transform_ms,
        "developmentDiagnosticsTimeMs": round(diagnostics_ms, 3),
        "fullDevelopmentDerivedCellsEvaluated": full_derived_cells,
        "inputFrameBytes": int(frame.memory_usage(index=True, deep=True).sum()),
        "rssBeforeBytes": rss_before,
        "rssAfterBytes": rss_after,
        "peakSampledRssBytes": max(value for value in (rss_before, rss_after) if value is not None) if any(value is not None for value in (rss_before, rss_after)) else None,
        "scienceArtifactBytes": science_bytes,
        "implementation": "VECTORIZED_NUMPY_PANDAS_BY_SHARED_FAMILY_NO_PA_ROW_PYTHON_LOOP",
        "targetColumnsRead": [],
        "finalOotPayloadRowsRead": 0,
        "finalOotPayloadRowsTransformed": 0,
        "predictiveModelFits": 0,
        "scores": 0,
        "calibrations": 0,
        "promotions": 0,
        "featureSetsRegistered": 0,
        "policiesAdopted": 0,
    }
    performance_receipt = publish_artifact(
        performance, root=args.output_root / "performance-runs"
    )
    result = {
        "authorityId": bundle["authorityId"],
        "authorityChecksum": bundle["authorityChecksum"],
        "bundleArtifactSha256": bundle_receipt["sha256"],
        "bundlePath": bundle_receipt["path"],
        "definitionId": definition["definitionId"],
        "definitionChecksum": definition["definitionChecksum"],
        "foldContractId": fold_contract["contractId"],
        "foldContractChecksum": fold_contract["contractChecksum"],
        "foldAuthorities": bundle["foldAuthorities"],
        "finalDevelopmentAuthority": bundle["finalDevelopmentAuthority"],
        "diagnosticsSha256": diagnostics_receipt["sha256"],
        "performanceReceiptSha256": performance_receipt["sha256"],
        "performanceReceiptPath": performance_receipt["path"],
        "developmentRows": len(frame),
        "finalOotPayloadRowsRead": 0,
        "predictiveModelFits": 0,
        "scienceObjectWrites": sum(
            int(bool(item.get("created")))
            for item in [
                fold_contract_receipt,
                definition_receipt,
                *fold_receipts,
                final_receipt,
                diagnostics_receipt,
                bundle_receipt,
            ]
        ),
        "currentPointerChanged": bool(bundle_receipt.get("pointerChanged")),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
