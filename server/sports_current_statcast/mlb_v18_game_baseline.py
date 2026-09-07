"""Governed Development-only finalization for the MLB V18 PA/game bridge.

This module deliberately separates three things that are easy to conflate:

* qualification of the already-fitted V18 PA component;
* fold-local estimation/evaluation of the PA-outcome-to-base/out transition;
* readiness to run an actual V18 whole-game forecast.

The last item fails closed when point-in-time participants and prospective V18 feature
templates are absent.  The module never opens Final OOT and never fits a PA estimator.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from server.persistence import Database
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.game_initialization import RngLineage
from server.sports_phase5.whole_game_monte_carlo import (
    FastTransitionSampler,
    GameContribs,
    simulate_game,
)

from . import stage3_eda as eda
from .stage3_game_scoring import game_scoring_summary
from .stage3_model_laboratory import resolve_model_lab_authority


SCHEMA_VERSION = "MLB_V18_PA_GAME_BASELINE_FINALIZATION_V1"
PROJECT_ID = "asp-mtlozhdx"
COMPARISON_SHA256 = "12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d"
V18_RUN_SHA256 = "95d4f0199aff4698f187311266c30670c4a95a66802cfd87ab96f1e120fd66bb"
V18_OOF_SHA256 = "b79a80398ef32a13589a8bb66f5e4e9c698b600195de5369886f7fc07f0dc215"
V14_RUN_SHA256 = "c9ffcc867a73eac6c287309f34889390dedf8484244c3bf5c2ed20dacecaf635"
FINALIST_DISPOSITION = "ADVANCE_AS_QUALIFIED_PA_FINALIST_FOR_GAME_SIMULATION_DEVELOPMENT"
CALIBRATION_DISPOSITION = "RAW_V18_PROBABILITIES_ACCEPTABLE_FOR_BASELINE_SIMULATION"
CALIBRATION_REQUIRED = "CALIBRATION_CHALLENGER_REQUIRED_BEFORE_BASELINE_SIMULATION"
SIMULATOR_DISPOSITION = "V18_GAME_BASELINE_BLOCKED_MISSING_PREGAME_AND_TEMPLATE_AUTHORITY"
TRANSITION_COLUMNS = (
    "canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_id",
    "game_date", "season", "outcome", "context_inning", "context_top_bottom",
    "context_outs_before", "context_base_mask_before",
    "context_batting_score_diff_before",
)
_PA_ORDINAL = re.compile(r":([0-9]+)$")
FD1_REGISTRATION_ID = "sports-dataset-1b58d5d1def2c9b7"
FD1_MANIFEST_SHA256 = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
FD1_LOGICAL_PREFIX = "asp-model-exchange://"
FD1_TRANSITION_COLUMNS = (
    "game_id", "game_date", "plate_appearance_id", "pa_outcome",
    "outs_before", "base_mask_before", "outs_after", "base_mask_after",
    "runs_scored", "play_number",
)


# This policy is constructed and hashed before any evidence is inspected by finalize().
CALIBRATION_CRITERION: Mapping[str, Any] = {
    "schemaVersion": "MLB_RAW_PA_CALIBRATION_BASELINE_CRITERION_V1",
    "purpose": "BASELINE_SIMULATION_ONLY_NOT_PRODUCTION_CALIBRATION_ACCEPTANCE",
    "gates": {
        "overallEceMaximum": 0.010,
        "overallMaximumPerClassAbsoluteCalibrationError": 0.005,
        "overallRareClassAbsoluteCalibrationErrorMaximum": 0.003,
        "rareClasses": ["TRIPLE", "OTHER_REACH"],
        "eachFoldEceMaximum": 0.015,
        "eachFoldMaximumPerClassAbsoluteCalibrationError": 0.015,
        "populatedReliabilityBandMinimumRows": 1000,
        "populatedReliabilityBandAbsoluteGapMaximum": 0.040,
        "stableSubgroupMinimumRows": 10000,
        "stableSubgroupMinimumGames": 500,
        "stableSubgroupEceMaximum": 0.015,
        "stableSubgroupMaximumPerClassAbsoluteCalibrationError": 0.015,
    },
    "nonGatingDiagnostics": {
        "sparseSubgroups": "Report but do not calibrate from overlapping groups below the stable sample gates.",
        "aggregateEceAloneIsSufficient": False,
        "acceptanceMeaning": "Raw probabilities may seed a labeled Development baseline; no production or final calibration claim.",
    },
}


class V18GameBaselineError(RuntimeError):
    """A frozen authority or evidence invariant failed."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(value: Mapping[str, Any]) -> str:
    return _sha_bytes(canonical_json_bytes(dict(value)))


def _native_json(value: Any) -> Any:
    """Normalize NumPy scalars at the immutable artifact boundary."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _native_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native_json(item) for item in value]
    return value


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "relativePath": str(path.resolve().relative_to(root.resolve())).replace("\\", "/"),
        "bytes": len(content),
        "sha256": _sha_bytes(content),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V18GameBaselineError(f"Expected an object at {path}.")
    return value


def _decision_id(prefix: str, body: Mapping[str, Any]) -> str:
    return f"{prefix}-{_sha(body)[:32]}"


def verify_comparison(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    body = dict(value)
    declared = str(body.pop("resultChecksum", ""))
    if declared != COMPARISON_SHA256 or _sha(body) != declared or value.get("status") != "COMPLETE":
        raise V18GameBaselineError("The V18 comparison report does not authenticate.")
    if value.get("additionalFitsStartedByFinalizer") != 0:
        raise V18GameBaselineError("The comparison finalizer recorded an unexpected fit.")
    coverage = value.get("coverage") or {}
    if (
        coverage.get("matchingRows") != 501_539
        or coverage.get("baselineOriginalRows") != 501_590
        or coverage.get("baselineOnlyRows") != 51
        or coverage.get("correctedOnlyRows") != 0
    ):
        raise V18GameBaselineError("The frozen exact-ID OOF population differs.")
    return value


def finalist_decision(comparison: Mapping[str, Any]) -> dict[str, Any]:
    metric = comparison["matchingObservationComparison"]
    uncertainty = comparison["pairedGameClusteredUncertainty"]
    body: dict[str, Any] = {
        "schemaVersion": "MLB_V18_PA_FINALIST_DECISION_V1",
        "projectId": PROJECT_ID,
        "status": "IMMUTABLE_QUALIFIED_PA_FINALIST_DECISION",
        "disposition": FINALIST_DISPOSITION,
        "candidate": {
            "treatment": comparison["recoveryExecutionEvidence"]["treatmentIdentity"],
            "runReceiptSha256": V18_RUN_SHA256,
            "candidateId": comparison["execution"]["candidateId"],
            "eligibleDevelopmentObservations": 683_606,
            "role": "PA_COMPONENT_FINALIST_FOR_DEVELOPMENT_GAME_SIMULATION",
        },
        "matchedComparison": {
            "observations": 501_539,
            "v18LogLoss": metric["corrected"]["multiclassLogLoss"],
            "v14LogLoss": metric["baseline"]["multiclassLogLoss"],
            "v18MinusV14LogLoss": metric["correctedMinusBaseline"]["multiclassLogLoss"],
            "pairedGameClustered95PercentInterval": uncertainty["confidenceInterval"],
            "conclusion": "NO_SUPERIORITY_EQUIVALENCE_OR_NONINFERIORITY_DEMONSTRATED",
        },
        "basis": [
            "V18 implements the adopted governed treatment specification.",
            "V18 preserves semantic missingness and has reproducible fold-local preprocessing, prior, model, and OOF prediction artifacts.",
            "The matched aggregate comparison demonstrates no material degradation, while also demonstrating no predictive improvement.",
            "V14 remains the immutable historical performance baseline; its incorrect treatment paths are not reinstated.",
        ],
        "qualifications": {
            "allSixColdOrNoHistoryPointEstimatesWorse": True,
            "nominalPositiveIntervals": [
                "EITHER_PLAYER_TRUE_COLD_START", "BATTING_NO_PRIOR_GAME",
                "FIELDING_NO_PRIOR_GAME", "EITHER_TEAM_NO_PRIOR_GAME",
            ],
            "teamNoHistoryGameCount": 47,
            "subgroupsOverlapAndAreNotIndependent": True,
            "hybridProhibited": True,
            "coldStartSpecialistResearchDeferred": True,
            "knownZeroOpportunityHold": {
                "developmentRows": 56,
                "reason": "V1_KNOWN_ZERO_PRIOR_PA_UNSUPPORTED_HISTORY_STATE",
                "resolved": False,
                "contained": True,
            },
        },
        "safety": {
            "completeGameModel": False,
            "champion": False,
            "productionModel": False,
            "exportedBundle": False,
            "aispModel": False,
            "finalOotRows": 14_067,
            "finalOotLocked": True,
            "finalOotAccessed": False,
            "newEstimatorFits": 0,
        },
        "sourceComparisonChecksum": COMPARISON_SHA256,
    }
    body["decisionId"] = _decision_id("mlb-v18-pa-finalist", body)
    return body


def _max_class_error(metrics: Mapping[str, Any], names: Sequence[str] | None = None) -> float:
    rows = list(metrics.get("classCalibration") or [])
    if names is not None:
        wanted = set(names)
        rows = [row for row in rows if row.get("class") in wanted]
    if not rows:
        return math.inf
    return max(float(row["absoluteCalibrationError"]) for row in rows)


def _max_band_gap(metrics: Mapping[str, Any], minimum_rows: int) -> float:
    rows = [
        row for row in metrics.get("reliabilityBands") or []
        if int(row.get("observations") or 0) >= minimum_rows
        and row.get("absoluteCalibrationGap") is not None
    ]
    return max((float(row["absoluteCalibrationGap"]) for row in rows), default=0.0)


def _worst_band(
    groups: Sequence[tuple[str, Mapping[str, Any]]], minimum_rows: int
) -> dict[str, Any]:
    candidates = [
        {"group": group, **dict(row)}
        for group, metrics in groups
        for row in metrics.get("reliabilityBands") or []
        if int(row.get("observations") or 0) >= minimum_rows
        and row.get("absoluteCalibrationGap") is not None
    ]
    if not candidates:
        raise V18GameBaselineError("No populated reliability band is available.")
    return max(candidates, key=lambda row: float(row["absoluteCalibrationGap"]))


def calibration_decision(comparison: Mapping[str, Any]) -> dict[str, Any]:
    gates = dict(CALIBRATION_CRITERION["gates"])
    overall = comparison["originalPopulationMetrics"]["corrected"]
    folds = [row["metrics"]["corrected"] for row in comparison["perFold"]]
    stable = [
        row for row in comparison["subgroups"]
        if int(row["observations"]) >= gates["stableSubgroupMinimumRows"]
        and int(row["games"]) >= gates["stableSubgroupMinimumGames"]
    ]
    sparse = [row for row in comparison["subgroups"] if row not in stable]
    checks = {
        "overallEce": {
            "value": float(overall["ece"]),
            "threshold": gates["overallEceMaximum"],
            "pass": float(overall["ece"]) <= gates["overallEceMaximum"],
        },
        "overallMaximumPerClassAbsoluteError": {
            "value": _max_class_error(overall),
            "threshold": gates["overallMaximumPerClassAbsoluteCalibrationError"],
        },
        "rareClassMaximumAbsoluteError": {
            "value": _max_class_error(overall, gates["rareClasses"]),
            "threshold": gates["overallRareClassAbsoluteCalibrationErrorMaximum"],
        },
        "maximumFoldEce": {
            "value": max(float(row["ece"]) for row in folds),
            "threshold": gates["eachFoldEceMaximum"],
        },
        "maximumFoldPerClassAbsoluteError": {
            "value": max(_max_class_error(row) for row in folds),
            "threshold": gates["eachFoldMaximumPerClassAbsoluteCalibrationError"],
        },
        "maximumPopulatedReliabilityBandGap": {
            "value": max(_max_band_gap(row, gates["populatedReliabilityBandMinimumRows"]) for row in [overall, *folds]),
            "threshold": gates["populatedReliabilityBandAbsoluteGapMaximum"],
        },
        "maximumStableSubgroupEce": {
            "value": max(float(row["metrics"]["corrected"]["ece"]) for row in stable),
            "threshold": gates["stableSubgroupEceMaximum"],
        },
        "maximumStableSubgroupPerClassAbsoluteError": {
            "value": max(_max_class_error(row["metrics"]["corrected"]) for row in stable),
            "threshold": gates["stableSubgroupMaximumPerClassAbsoluteCalibrationError"],
        },
    }
    for value in checks.values():
        value.setdefault("pass", value["value"] <= value["threshold"])
    passed = all(row["pass"] for row in checks.values())
    if not passed:
        disposition = CALIBRATION_REQUIRED
    else:
        disposition = CALIBRATION_DISPOSITION
    body: dict[str, Any] = {
        "schemaVersion": "MLB_V18_CALIBRATION_NEEDS_DECISION_V1",
        "projectId": PROJECT_ID,
        "status": "IMMUTABLE_DEVELOPMENT_CALIBRATION_DECISION",
        "disposition": disposition,
        "criterion": dict(CALIBRATION_CRITERION),
        "criterionChecksum": _sha(CALIBRATION_CRITERION),
        "checks": checks,
        "worstPopulatedReliabilityBand": _worst_band(
            [("overall", overall), *[(f"fold-{index}", row) for index, row in enumerate(folds, 1)]],
            gates["populatedReliabilityBandMinimumRows"],
        ),
        "rareClassEvidence": {
            row["class"]: row for row in overall["classCalibration"]
            if row["class"] in set(gates["rareClasses"])
        },
        "stableSubgroups": [
            {
                "name": row["name"], "observations": row["observations"],
                "games": row["games"], "ece": row["metrics"]["corrected"]["ece"],
                "maximumPerClassAbsoluteCalibrationError": _max_class_error(row["metrics"]["corrected"]),
            }
            for row in stable
        ],
        "sparseNonGatingSubgroups": [
            {
                "name": row["name"], "observations": row["observations"],
                "games": row["games"], "ece": row["metrics"]["corrected"]["ece"],
                "maximumPerClassAbsoluteCalibrationError": _max_class_error(row["metrics"]["corrected"]),
            }
            for row in sparse
        ],
        "interpretation": (
            "Raw V18 probabilities meet the predeclared Development-baseline criterion across aggregate, class, rare-class, reliability-band, temporal-fold, and stable cold-start checks. Sparse 47-game no-history diagnostics remain a downstream uncertainty warning, not a fitted calibration target."
            if passed else
            "At least one predeclared practical calibration gate failed. No calibrator was fitted; raw probabilities may only be used as an explicitly uncalibrated research baseline."
        ),
        "calibrationModelFit": False,
        "modelsFit": 0,
        "sourceComparisonChecksum": COMPARISON_SHA256,
        "finalOotLocked": True,
        "finalOotAccessed": False,
    }
    body["decisionId"] = _decision_id("mlb-v18-calibration", body)
    return body


def _ordinal(value: Any) -> int:
    match = _PA_ORDINAL.search(str(value))
    if match is None:
        raise V18GameBaselineError(f"Plate-appearance ordinal is unavailable: {value!r}.")
    return int(match.group(1))


def reconstruct_transitions(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = set(TRANSITION_COLUMNS)
    if set(frame.columns) != required:
        raise V18GameBaselineError("Transition scan columns differ from the fixed contract.")
    work = frame.copy()
    work["pa_ordinal"] = work["plate_appearance_id"].map(_ordinal)
    if bool(work.duplicated(["canonicalGameId", "pa_ordinal"]).any()):
        raise V18GameBaselineError("Game-local plate-appearance ordinals are not unique.")
    work.sort_values(["canonicalGameId", "pa_ordinal"], inplace=True, kind="stable")
    records: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    excluded_ids: dict[str, list[str]] = defaultdict(list)
    for _, game in work.groupby("canonicalGameId", sort=False):
        rows = list(game.to_dict("records"))
        for index, row in enumerate(rows):
            if index + 1 == len(rows):
                reason = "TERMINAL_PA_NO_SUCCESSOR_STATE"
                excluded[reason] += 1
                excluded_ids[reason].append(str(row["canonicalPaId"]))
                continue
            nxt = rows[index + 1]
            if int(nxt["pa_ordinal"]) != int(row["pa_ordinal"]) + 1:
                reason = "NONCONTIGUOUS_GAME_PA_ORDINAL"
                excluded[reason] += 1
                excluded_ids[reason].append(str(row["canonicalPaId"]))
                continue
            same_half = (
                int(nxt["context_inning"]) == int(row["context_inning"])
                and int(nxt["context_top_bottom"]) == int(row["context_top_bottom"])
            )
            if same_half:
                outs_after = int(nxt["context_outs_before"])
                base_after = int(nxt["context_base_mask_before"])
                runs = int(nxt["context_batting_score_diff_before"]) - int(row["context_batting_score_diff_before"])
            else:
                top = int(row["context_top_bottom"])
                next_top = int(nxt["context_top_bottom"])
                inning = int(row["context_inning"])
                next_inning = int(nxt["context_inning"])
                legal_switch = (top == 0 and next_top == 1 and next_inning == inning) or (
                    top == 1 and next_top == 0 and next_inning == inning + 1
                )
                if not legal_switch:
                    reason = "HALF_INNING_SEQUENCE_INVALID"
                    excluded[reason] += 1
                    excluded_ids[reason].append(str(row["canonicalPaId"]))
                    continue
                outs_after = 3
                base_after = 0
                runs = -int(nxt["context_batting_score_diff_before"]) - int(row["context_batting_score_diff_before"])
            transition = (
                outs_after - int(row["context_outs_before"]), base_after, runs,
            )
            if not bt.is_legal(
                int(row["context_outs_before"]), int(row["context_base_mask_before"]), transition
            ):
                reason = "RUNNER_CONSERVATION_OR_STATE_ANOMALY"
                excluded[reason] += 1
                excluded_ids[reason].append(str(row["canonicalPaId"]))
                continue
            records.append({
                "canonicalPaId": str(row["canonicalPaId"]),
                "canonicalGameId": str(row["canonicalGameId"]),
                "game_date": str(row["game_date"]),
                "season": int(row["season"]),
                "pa_outcome": str(row["outcome"]),
                "outs_before": int(row["context_outs_before"]),
                "base_mask_before": int(row["context_base_mask_before"]),
                "outs_after": outs_after,
                "base_mask_after": base_after,
                "runs_scored": runs,
            })
    result = pd.DataFrame.from_records(records)
    ledger = {
        "schemaVersion": "MLB_DEVELOPMENT_TRANSITION_RECONSTRUCTION_LEDGER_V1",
        "sourceRows": len(work),
        "sourceGames": int(work["canonicalGameId"].nunique()),
        "reconstructedRows": len(result),
        "excludedRows": int(sum(excluded.values())),
        "excludedByReason": dict(sorted(excluded.items())),
        "excludedIdentityChecksums": {
            key: _sha_bytes(canonical_json_bytes(sorted(values)))
            for key, values in sorted(excluded_ids.items())
        },
        "ordering": "INTEGER_SUFFIX_OF_RETROSHEET_PLATE_APPEARANCE_ID_WITHIN_CANONICAL_GAME",
        "derivation": {
            "sameHalf": "next pre-PA outs/base and batting-score-difference increment",
            "halfSwitch": "third out, bases cleared, sign-reversed next batting-score differential",
            "terminal": "excluded because no successor pre-PA state exists",
        },
        "targetRowsOutsideDevelopmentRead": 0,
        "finalOotRowsRead": 0,
    }
    return result, ledger


def load_registered_fd1_transitions(
    database_path: Path,
    exchange_root: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load only registered Development-era FD1 transition targets.

    FD1 exposes explicit before/after states and trustworthy Retrosheet ordering through
    2025.  It is retrospective target evidence, so it is used only for fold-local
    transition fitting/evaluation and never as a pregame feature or participant source.
    """
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    try:
        registration = connection.execute(
            "SELECT registration_id, manifest_sha, validation_status, active, logical_package_root "
            "FROM sports_dataset_registrations WHERE registration_id = ?",
            (FD1_REGISTRATION_ID,),
        ).fetchone()
        if registration is None:
            raise V18GameBaselineError("The registered FD1 transition authority is unavailable.")
        if (
            str(registration["manifest_sha"]) != FD1_MANIFEST_SHA256
            or str(registration["validation_status"]) != "VALID"
            or int(registration["active"]) != 1
        ):
            raise V18GameBaselineError("The registered FD1 transition authority differs.")
        partitions = connection.execute(
            "SELECT partition_id, season, month, logical_uri, row_count, minimum_date, "
            "maximum_date, file_sha, schema_id, target_eligibility_json, temporal_classification_json "
            "FROM sports_dataset_partitions WHERE registration_id = ? AND family = 'play_transition' "
            "AND season IN (2023, 2024, 2025) ORDER BY season, month",
            (FD1_REGISTRATION_ID,),
        ).fetchall()
    finally:
        connection.close()
    if len(partitions) != 22:
        raise V18GameBaselineError("FD1 Development transition partition inventory differs.")

    tables: list[pa.Table] = []
    partition_records: list[dict[str, Any]] = []
    root = exchange_root.resolve()
    for row in partitions:
        logical_uri = str(row["logical_uri"])
        if not logical_uri.startswith(FD1_LOGICAL_PREFIX):
            raise V18GameBaselineError("FD1 transition logical URI is outside the registered scheme.")
        relative = PurePosixPath(logical_uri[len(FD1_LOGICAL_PREFIX):])
        path = root.joinpath(*relative.parts).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise V18GameBaselineError("FD1 transition path escapes the exchange root.") from error
        if not path.is_file() or _sha_bytes(path.read_bytes()) != str(row["file_sha"]):
            raise V18GameBaselineError(f"FD1 transition partition bytes differ: {logical_uri}.")
        table = pq.read_table(path, columns=list(FD1_TRANSITION_COLUMNS))
        if table.num_rows != int(row["row_count"]):
            raise V18GameBaselineError(f"FD1 transition partition row count differs: {logical_uri}.")
        tables.append(table)
        partition_records.append({
            "partitionId": str(row["partition_id"]),
            "season": int(row["season"]),
            "month": int(row["month"]),
            "logicalUri": logical_uri,
            "rows": int(row["row_count"]),
            "minimumDate": str(row["minimum_date"]),
            "maximumDate": str(row["maximum_date"]),
            "fileSha256": str(row["file_sha"]),
            "schemaId": str(row["schema_id"]),
            "targetEligibility": json.loads(str(row["target_eligibility_json"])),
            "temporalClassification": json.loads(str(row["temporal_classification_json"])),
        })
    raw = pa.concat_tables(tables).to_pandas()
    eligible = raw.loc[
        raw["plate_appearance_id"].notna()
        & raw["pa_outcome"].isin(PA_CLASS_ORDER)
    ].copy()
    if bool(eligible.duplicated("plate_appearance_id").any()):
        raise V18GameBaselineError("FD1 terminal plate-appearance transition identity is not unique.")
    eligible.rename(columns={
        "game_id": "canonicalGameId",
        "plate_appearance_id": "canonicalPaId",
    }, inplace=True)
    eligible["season"] = eligible["game_date"].astype(str).str.slice(0, 4).astype(int)
    eligible.sort_values(["game_date", "canonicalGameId", "play_number"], inplace=True, kind="stable")
    eligible.reset_index(drop=True, inplace=True)
    ledger = {
        "schemaVersion": "MLB_FD1_REGISTERED_TRANSITION_LOAD_LEDGER_V1",
        "registrationId": FD1_REGISTRATION_ID,
        "manifestSha256": FD1_MANIFEST_SHA256,
        "logicalPackageRoot": str(registration["logical_package_root"]),
        "registrationStatus": "VALID",
        "sourceSemantics": "RETROSPECTIVE_TARGET_ONLY_FOLD_LOCAL_ESTIMATION",
        "rawPlayTransitionRows": len(raw),
        "terminalPaTransitionRows": len(eligible),
        "games": int(eligible["canonicalGameId"].nunique()),
        "minimumDate": str(eligible["game_date"].min()),
        "maximumDate": str(eligible["game_date"].max()),
        "partitionCount": len(partition_records),
        "partitionAuthority": partition_records,
        "excludedNonTerminalOrNonPaRows": int(len(raw) - len(eligible)),
        "currentGoldSequenceAudit": {
            "developmentRows": 683_662,
            "opaquePaIdentityRows": 320_879,
            "opaqueGames": 4_255,
            "affectedSeasons": [2025, 2026],
            "disposition": "NOT_USED_FOR_SEQUENCE_RECONSTRUCTION_NO_HASH_ORDER_INFERENCE",
        },
        "outcomeIndependentV18Hold": {
            "rows": 56,
            "application": "PRESERVED_IN_PA_ESTIMATOR_ELIGIBILITY;_NOT_JOINABLE_TO_FD1_TARGET_IDENTITIES",
            "reason": "Current Gold hold identities are opaque pa-* keys; no unregistered crosswalk or outcome-based matching was invented.",
        },
        "finalOotRowsRead": 0,
    }
    return eligible, ledger


def _model_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "pa_outcome": str(row.pa_outcome),
            "outs_before": int(row.outs_before),
            "base_mask_before": int(row.base_mask_before),
            "outs_after": int(row.outs_after),
            "base_mask_after": int(row.base_mask_after),
            "runs_scored": int(row.runs_scored),
        }
        for row in frame.itertuples(index=False)
    ]


def _null_state_model(frame: pd.DataFrame, alpha: float) -> dict[str, Any]:
    counts: dict[str, Counter[tuple[int, int, int]]] = defaultdict(Counter)
    for row in frame.itertuples(index=False):
        state = f"{int(row.outs_before)}|{int(row.base_mask_before)}"
        transition = (
            int(row.outs_after) - int(row.outs_before),
            int(row.base_mask_after), int(row.runs_scored),
        )
        counts[state][transition] += 1
    payload: dict[str, Any] = {
        "schemaVersion": "MLB_LEAGUE_AVERAGE_STATE_TRANSITION_NULL_V1",
        "alpha": alpha,
        "conditioning": ["outs_before", "base_mask_before"],
        "cells": {},
    }
    for outs in range(3):
        for base in range(8):
            state = f"{outs}|{base}"
            legal = bt.enumerate_legal_transitions(outs, base)
            cell = counts.get(state, Counter())
            total = sum(cell.values()) + alpha * len(legal)
            payload["cells"][state] = {
                "support": int(sum(cell.values())),
                "transitions": [
                    {
                        "outsAdded": t[0], "baseMaskAfter": t[1], "runs": t[2],
                        "count": int(cell[t]), "probability": float((cell[t] + alpha) / total),
                    }
                    for t in legal
                ],
            }
    return payload


def _distribution_map(distribution: Mapping[str, Any]) -> dict[tuple[int, int, int], float]:
    return {
        (int(row["outsAdded"]), int(row["baseMaskAfter"]), int(row["runs"])): float(row["probability"])
        for row in distribution["transitions"]
    }


@dataclass
class _Metric:
    rows: int = 0
    log_loss: float = 0.0
    run_log_loss: float = 0.0
    brier: float = 0.0
    top1: int = 0
    top2: int = 0
    outs: int = 0
    base: int = 0
    inning_end: int = 0
    run_abs: float = 0.0
    entropy: float = 0.0
    calibration_rows: Counter[int] = field(default_factory=Counter)
    calibration_confidence: defaultdict[int, float] = field(default_factory=lambda: defaultdict(float))
    calibration_correct: Counter[int] = field(default_factory=Counter)

    def add(self, dist: Mapping[str, Any], actual: tuple[int, int, int]) -> float:
        probabilities = _distribution_map(dist)
        probability = max(probabilities.get(actual, 0.0), 1e-15)
        ordered = sorted(probabilities, key=lambda key: (-probabilities[key], key))
        best = ordered[0]
        confidence = float(probabilities[best])
        calibration_bin = min(9, int(confidence * 10.0))
        run_probability = max(sum(p for key, p in probabilities.items() if key[2] == actual[2]), 1e-15)
        expected_runs = sum(key[2] * p for key, p in probabilities.items())
        self.rows += 1
        self.log_loss += -math.log(probability)
        self.run_log_loss += -math.log(run_probability)
        self.brier += sum((p - (1.0 if key == actual else 0.0)) ** 2 for key, p in probabilities.items())
        self.top1 += int(best == actual)
        self.top2 += int(actual in ordered[:2])
        self.outs += int(best[0] == actual[0])
        self.base += int(best[1] == actual[1])
        self.inning_end += int((best[0] == 3) == (actual[0] == 3))
        self.run_abs += abs(expected_runs - actual[2])
        self.entropy += -sum(p * math.log(p) for p in probabilities.values() if p > 0)
        self.calibration_rows[calibration_bin] += 1
        self.calibration_confidence[calibration_bin] += confidence
        self.calibration_correct[calibration_bin] += int(best == actual)
        return -math.log(probability)

    def record(self) -> dict[str, Any]:
        n = self.rows
        if not n:
            return {"rows": 0}
        bands = []
        ece = 0.0
        for index in range(10):
            rows = int(self.calibration_rows[index])
            mean_confidence = self.calibration_confidence[index] / rows if rows else None
            observed_accuracy = self.calibration_correct[index] / rows if rows else None
            gap = abs(mean_confidence - observed_accuracy) if rows else None
            if gap is not None:
                ece += rows / n * gap
            bands.append({
                "lowerBound": index / 10.0,
                "upperBound": (index + 1) / 10.0,
                "observations": rows,
                "meanTopTransitionProbability": mean_confidence,
                "observedTopTransitionAccuracy": observed_accuracy,
                "absoluteCalibrationGap": gap,
            })
        return {
            "rows": n,
            "nextTransitionLogLoss": self.log_loss / n,
            "runMarginalLogLoss": self.run_log_loss / n,
            "multiclassBrier": self.brier / n,
            "top1Accuracy": self.top1 / n,
            "top2Coverage": self.top2 / n,
            "outsAddedAccuracy": self.outs / n,
            "baseMaskAfterAccuracy": self.base / n,
            "inningEndingAccuracy": self.inning_end / n,
            "expectedRunsMae": self.run_abs / n,
            "meanPredictiveEntropy": self.entropy / n,
            "topTransitionExpectedCalibrationError": ece,
            "topTransitionReliabilityBands": bands,
        }


def evaluate_transition_model(
    model: bt.TransitionModel,
    null_model: Mapping[str, Any],
    frame: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    cache = {
        (outcome, outs, base): model.distribution(outcome, outs, base)
        for outcome in bt.PA_CLASSES for outs in range(3) for base in range(8)
    }
    null_cache = {
        (outs, base): null_model["cells"][f"{outs}|{base}"]
        for outs in range(3) for base in range(8)
    }
    overall, null_overall = _Metric(), _Metric()
    by_outcome: dict[str, _Metric] = defaultdict(_Metric)
    by_state: dict[str, _Metric] = defaultdict(_Metric)
    fallback: Counter[str] = Counter()
    per_game: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"rows": 0, "transitionLossSum": 0.0, "nullTransitionLossSum": 0.0,
                 "sparseBackoffRows": 0}
    )
    for row in frame.itertuples(index=False):
        key = (str(row.pa_outcome), int(row.outs_before), int(row.base_mask_before))
        actual = (
            int(row.outs_after) - int(row.outs_before),
            int(row.base_mask_after), int(row.runs_scored),
        )
        dist = cache[key]
        null_dist = null_cache[(key[1], key[2])]
        loss = overall.add(dist, actual)
        null_loss = null_overall.add(null_dist, actual)
        by_outcome[key[0]].add(dist, actual)
        by_state[f"{key[1]}|{key[2]}"].add(dist, actual)
        fallback[str(dist["fallbackLevel"])] += 1
        game = per_game[str(row.canonicalGameId)]
        game["rows"] += 1
        game["transitionLossSum"] += loss
        game["nullTransitionLossSum"] += null_loss
        game["sparseBackoffRows"] += int(str(dist["fallbackLevel"]) != "L0_EXACT" and str(dist["fallbackLevel"]) != "DETERMINISTIC_HOME_RUN")
    n = max(1, overall.rows)
    records = pd.DataFrame.from_records([
        {
            "canonicalGameId": game_id,
            "transitionRows": row["rows"],
            "meanTransitionLogLoss": row["transitionLossSum"] / row["rows"],
            "meanNullTransitionLogLoss": row["nullTransitionLossSum"] / row["rows"],
            "transitionImprovementVsNull": (row["nullTransitionLossSum"] - row["transitionLossSum"]) / row["rows"],
            "sparseBackoffRate": row["sparseBackoffRows"] / row["rows"],
        }
        for game_id, row in sorted(per_game.items())
    ])
    result = {
        "model": overall.record(),
        "leagueAverageStateNull": null_overall.record(),
        "modelMinusNullLogLoss": overall.record()["nextTransitionLogLoss"] - null_overall.record()["nextTransitionLogLoss"],
        "fallbackUsage": {key: value / n for key, value in sorted(fallback.items())},
        "perOutcome": {key: value.record() for key, value in sorted(by_outcome.items())},
        "perBaseOutState": {key: value.record() for key, value in sorted(by_state.items())},
    }
    return result, records


def _conformance(
    transition: bt.TransitionModel,
    pa_probabilities: Sequence[float],
    *,
    seed: int,
) -> dict[str, Any]:
    draws = 4096
    zero = np.zeros((130, len(PA_CLASS_ORDER)), dtype=np.float64)
    result = simulate_game(
        game_id="synthetic-neutral-authority-conformance",
        contribs=GameContribs(zero, zero, zero, zero, 9),
        fold=None,
        transition_sampler=FastTransitionSampler(transition),
        rng_lineage=RngLineage(seed, "synthetic-neutral-authority-conformance"),
        n_sims=draws,
        check_legality=True,
        fixed_probs=np.asarray(pa_probabilities, dtype=np.float64),
    )
    prefixes = []
    total = result.away_runs + result.home_runs
    for count in (512, 1024, 2048, 4096):
        home = result.home_win[:count].astype(np.float64)
        run = total[:count].astype(np.float64)
        prefixes.append({
            "draws": count,
            "homeWinProbability": float(home.mean()),
            "homeWinMonteCarloStandardError": float(home.std(ddof=1) / math.sqrt(count)),
            "meanTotalRuns": float(run.mean()),
            "meanTotalRunsMonteCarloStandardError": float(run.std(ddof=1) / math.sqrt(count)),
        })
    return {
        "schemaVersion": "MLB_NULL_SEQUENTIAL_ENGINE_CONFORMANCE_V1",
        "status": "EXECUTABLE_NULL_CONFORMANCE_NOT_A_V18_GAME_FORECAST",
        "stateEngine": "MLB_WHOLE_GAME_MONTE_CARLO_V1",
        "state": {
            "inning": "integer >= 1", "half": ["TOP", "BOTTOM"], "outs": [0, 1, 2],
            "baseMask": "3-bit integer 0..7", "awayScore": "nonnegative integer",
            "homeScore": "nonnegative integer", "battingOrderOrdinal": "per-side nonnegative integer",
            "pitcherState": "provider-owned; unavailable in participant-free null",
            "terminal": "walk-off or completed regulation/extra half with non-tie score",
        },
        "plateAppearanceProbabilities": dict(zip(PA_CLASS_ORDER, map(float, pa_probabilities))),
        "source": "FOLD_1_TRAINING_ONLY_LEAGUE_AVERAGE_PA_OUTCOME_RATES",
        "draws": draws,
        "seed": seed,
        "nestedPrefixConvergence": prefixes,
        "maximumHomeWinProbabilityDifferenceFrom4096": max(abs(row["homeWinProbability"] - prefixes[-1]["homeWinProbability"]) for row in prefixes[:-1]),
        "maximumMeanTotalDifferenceFrom4096": max(abs(row["meanTotalRuns"] - prefixes[-1]["meanTotalRuns"]) for row in prefixes[:-1]),
        "nonterminated": result.nonterminated,
        "illegalStates": result.illegal_states,
        "representativeStatePathsPersisted": 0,
        "pathReason": "No game-level run is authorized without governed participants; this is engine conformance only.",
    }


def capability_matrix(
    repository_root: Path,
    authority: Any,
    scoring: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_files = [
        repository_root / "server/sports_current_statcast/stage3_game_inputs.py",
        repository_root / "server/sports_current_statcast/stage3_game_probability_adapter.py",
        repository_root / "server/sports_current_statcast/stage3_game_scoring.py",
        repository_root / "server/sports_phase5/base_out_transition.py",
        repository_root / "server/sports_phase5/whole_game_monte_carlo.py",
        repository_root / "server/sports_gold/game_simulation_inputs.py",
        repository_root / "server/sports_gold/game_simulation_market_study.py",
    ]
    refs = {path.name: _file_record(path, repository_root) for path in evidence_files}

    def row(capability: str, status: str, evidence: str, implication: str) -> dict[str, str]:
        return {"capability": capability, "classification": status, "evidence": evidence, "implication": implication}

    rows = [
        row("Confirmed pregame batting orders and original knowledge timestamps", "MISSING_AUTHORITY", "Stage3 scoring readiness reports zero games and GOVERNED_PREGAME_LINEUP_STARTER_AUTHORITY_UNAVAILABLE. Retrosheet start rows have no capture timestamp.", "V18 historical and prospective game scoring fails closed."),
        row("Historical Retrosheet starting lineups", "POST_OUTCOME_OR_ORACLE_ONLY", "game_simulation_inputs.py can reconstruct recordType=start participants but explicitly lacks captured-at authority.", "May describe an oracle research analysis only; not used here."),
        row("Starting-pitcher identity and confirmation timestamp", "MISSING_AUTHORITY", "No confirmed/announced starter feed with source, observation, and receipt times is registered.", "No V18 game may be scored."),
        row("Historical starter and reliever identities", "POST_OUTCOME_OR_ORACLE_ONLY", "Historical PA pitcher identities and Retrosheet starts exist after the game sequence is known.", "Not used as pregame evidence."),
        row("Bench and substitution candidates", "MISSING_AUTHORITY", "No timestamped pregame active-roster/bench inventory is bound to Current Gold.", "Substitutions cannot be simulated prospectively."),
        row("Bullpen roster, handedness, quality, availability, and workload", "MISSING_AUTHORITY", "Current selected inputs retain recent-bullpen-workload missing indicators; no reliever selection/availability contract exists.", "Starter-to-bullpen behavior must not be fabricated."),
        row("V18 batter/pitcher features for hypothetical PAs", "MISSING_AUTHORITY", "Five saved fold pipelines expect 246 raw inputs that create 273 treatment inputs; the existing game adapter is fixed to the older 234-feature contract and no V18 prospective template authority exists.", "Saved V18 OOF models cannot legally be driven through a full simulated game."),
        row("Dynamic inning/half/outs/base/score/PA ordinal state", "SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION", "whole_game_monte_carlo.py maintains and validates these simulated fields; V18 includes the five model state inputs.", "Executable when a compatible PA provider is supplied."),
        row("Historical PA outcome and pre/post-PA base/out state", "SUPPORTED_BY_FOLD_LOCAL_HISTORICAL_ESTIMATION", "Registered FD1 play_transition partitions provide explicit Retrosheet-ordered before/after states through 2025. Current Gold has opaque, non-order-bearing PA keys for 2025-2026 and is not hash-sorted.", "Supports exact transition fitting through fold 4 training and complete validation only for folds 1-3; 2026 authority is missing."),
        row("Runner advancement conditional on outcome/base-out state", "SUPPORTED_BY_FOLD_LOCAL_HISTORICAL_ESTIMATION", "FD1 explicit after-state targets are used with fold-local Dirichlet smoothing and governed backoff. They are retrospective targets, never pregame features.", "Transition artifacts are executable for four training folds; evaluation is complete for folds 1-3 only."),
        row("Double plays, sacrifices, errors within a PA", "DEFERRED_SPECIALIST_COMPONENT", "They are represented only through the coarse eight-class outcome and empirical resulting transition, not distinct mechanisms.", "Transition uncertainty is retained; no specialist added."),
        row("Steals, caught stealing, wild pitches, passed balls, pickoffs between PAs", "MISSING_AUTHORITY", "The PA-step engine has no governed between-PA event clock/provider.", "Baseline cannot model these events explicitly."),
        row("Starter workload, fatigue, times through order, removal", "DEFERRED_SPECIALIST_COMPONENT", "No prospective workload/removal provider is connected to V18 game inputs.", "Do not silently hold a starter for a qualified V18 baseline."),
        row("Manager hook and reliever selection", "DEFERRED_SPECIALIST_COMPONENT", "No governed manager/bullpen policy is registered.", "Requires a separately evaluated chronological component."),
        row("Park environment", "MISSING_AUTHORITY", "The V18 selected feature set has no explicit governed park effect input for hypothetical game scoring.", "Park-specific game distributions are unavailable."),
        row("Weather and umpire", "MISSING_AUTHORITY", "Temperature remains a missingness indicator and no timestamped weather/umpire input authority is bound.", "No weather/umpire scenario is asserted."),
        row("League and season context", "SUPPORTED_BY_GOVERNED_PREGAME_AUTHORITY", "Registered Gold carries season/phase and league-alignment context derived under an exclusive cutoff.", "Usable only after a prospective template builder exists."),
        row("Walk-off and regulation completion rules", "SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION", "whole_game_monte_carlo.py implements immediate home walk-off and regulation/extra-inning termination.", "Verified in null conformance."),
        row("Current extra-inning automatic runner", "SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION", "The engine places the automatic runner on second at each extra half-inning.", "Mechanics are available; era/rule version still needs a game authority."),
        row("Gen 1 independent-Poisson comparison", "SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION", "Historical Gen 1/older Phase 7 evidence exists on different cohorts and participant contracts; no same-game current-fold artifact is registered.", "A fair numeric V18 comparison is not reported."),
        row("Richer Gen 2 sequential engine reuse", "SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION", "MLB_WHOLE_GAME_MONTE_CARLO_V1 and state-aware Stage3 seams are present and legality tested.", "Engine code is reused only for participant-free conformance."),
    ]
    return {
        "schemaVersion": "MLB_V18_PA_GAME_CAPABILITY_MATRIX_V1",
        "projectId": PROJECT_ID,
        "sourceDataset": {
            "registrationId": authority.eda_authority.registration_id,
            "datasetVersionId": authority.eda_authority.dataset_version_id,
            "sourceDatasetId": authority.eda_authority.source_dataset_id,
            "goldManifestSha256": authority.eda_authority.gold_manifest_sha,
            "schemaFieldCount": len(authority.eda_authority.schema.names),
        },
        "stage3ScoringReadiness": scoring,
        "implementationEvidence": refs,
        "capabilities": rows,
    }


def simulator_specification(comparison: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "MLB_V18_SEQUENTIAL_GAME_BASELINE_SPECIFICATION_V1",
        "status": SIMULATOR_DISPOSITION,
        "paComponent": {
            "treatmentSpecificationId": "stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638",
            "treatmentManifestSha256": "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3",
            "registeredInputsBeforeFoldLocalEncoding": 273,
            "savedFoldModelCount": 5,
            "rawProbabilities": "UNCALIBRATED_RAW_V18_ALLOWED_ONLY_AS_LABELED_DEVELOPMENT_BASELINE",
        },
        "state": {
            "ordinaryBaseOutStates": 24,
            "fields": ["inning", "halfInning", "outs", "baseMask", "awayScore", "homeScore", "battingOrderPosition", "currentPitcherIdentityOrQualityState", "gameComplete", "walkOff", "extraInning"],
            "baseMaskEncoding": {"range": [0, 7], "bits": {"0": "first", "1": "second", "2": "third"}},
        },
        "intendedPaLoop": [
            "Build a cutoff-valid V18 raw feature row for the current batter, pitcher, and simulated state.",
            "Transform through the corresponding saved fold pipeline and validate the ordered eight probabilities.",
            "Sample the PA outcome, then a fold-local transition and runs.",
            "Advance bases, outs, score, batting order, pitcher state, half-inning, and termination rules.",
        ],
        "transition": {
            "hierarchy": ["L0 outcome + outs + base", "L1 outcome + outs", "L2 outcome", "L3 uniform legal prior"],
            "smoothing": {"type": "DIRICHLET_OVER_LEGAL_TRANSITIONS", "alpha": bt.DEFAULT_ALPHA, "minimumExactCellSupport": bt.MIN_CELL_COUNT},
            "homeRunRule": "deterministic bases clear, no out, occupied runners plus batter score",
            "fitScope": "CORRESPONDING_CHRONOLOGICAL_TRAINING_FOLD_ONLY",
        },
        "participants": {
            "lineup": "FAIL_CLOSED_MISSING_TIMESTAMPED_CONFIRMED_LINEUP_AUTHORITY",
            "starter": "FAIL_CLOSED_MISSING_TIMESTAMPED_ANNOUNCED_STARTER_AUTHORITY",
            "bullpen": "FAIL_CLOSED_MISSING_ROSTER_AVAILABILITY_AND_SELECTION_AUTHORITY",
            "substitutions": "FAIL_CLOSED_MISSING_PREGAME_CANDIDATE_AND_POLICY_AUTHORITY",
            "oracleAnalysisRun": False,
        },
        "simulationProtocol": {
            "folds": 5, "foldSpecificV18ArtifactsRequired": True,
            "commonRandomNumbersAcrossVariants": True, "deterministicSeeds": True,
            "convergenceRequiredBeforeGameEvaluation": True,
            "v18GamesSimulated": 0,
        },
        "blockedEvaluation": {
            "transition": False,
            "inning": True,
            "game": True,
            "gen1SameGameComparison": True,
            "coldNoHistoryGamePropagation": True,
            "reason": "A game forecast cannot be constructed without prospective participants and V18 templates; validation outcomes and actual future PA sequences are prohibited substitutes.",
        },
        "finalOot": comparison["finalOot"],
    }


def _pa_game_losses(oof_path: Path) -> pd.DataFrame:
    columns = ["canonicalGameId", "observedClassIndex", *[f"probability_{name}" for name in PA_CLASS_ORDER]]
    frame = pq.read_table(oof_path, columns=columns).to_pandas(split_blocks=True)
    probabilities = frame[[f"probability_{name}" for name in PA_CLASS_ORDER]].to_numpy(dtype=np.float64)
    observed = frame["observedClassIndex"].to_numpy(dtype=np.int64)
    frame["paMeanLogLoss"] = -np.log(np.clip(probabilities[np.arange(len(frame)), observed], 1e-15, 1.0))
    frame["paEntropy"] = -np.sum(np.where(probabilities > 0.0, probabilities * np.log(probabilities), 0.0), axis=1)
    return frame.groupby("canonicalGameId", sort=True).agg(
        paRows=("paMeanLogLoss", "size"),
        meanPaLogLoss=("paMeanLogLoss", "mean"),
        meanPaEntropy=("paEntropy", "mean"),
    ).reset_index()


def error_atlas(
    game_transitions: Sequence[pd.DataFrame],
    oof_path: Path,
    transition_evaluation: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    transition = pd.concat(game_transitions, ignore_index=True)
    pa = _pa_game_losses(oof_path)
    joined = pa.merge(transition, on="canonicalGameId", how="left", validate="one_to_one")
    joined["missingUnsupportedSimulatorCapability"] = True
    joined["lineupPitcherParticipationError"] = np.nan
    joined["runDistributionError"] = np.nan
    joined["gameCalibrationError"] = np.nan
    records = json.loads(joined.to_json(orient="records"))
    outcome_rows: dict[str, dict[str, float]] = {}
    for fold in transition_evaluation:
        if not fold.get("evaluationCompleted"):
            continue
        for name, values in fold["evaluation"]["perOutcome"].items():
            agg = outcome_rows.setdefault(name, {"rows": 0.0, "lossWeighted": 0.0})
            agg["rows"] += float(values["rows"])
            agg["lossWeighted"] += float(values["rows"]) * float(values["nextTransitionLogLoss"])
    outcome_summary = [
        {"outcome": name, "rows": int(row["rows"]), "meanTransitionLogLoss": row["lossWeighted"] / row["rows"]}
        for name, row in outcome_rows.items()
    ]
    outcome_summary.sort(key=lambda row: (-row["meanTransitionLogLoss"], -row["rows"], row["outcome"]))
    summary = {
        "schemaVersion": "MLB_V18_ERROR_AND_REGIME_ATLAS_FOUNDATION_V1",
        "status": "COMPONENT_ERROR_FOUNDATION_GAME_DISTRIBUTION_ERROR_BLOCKED",
        "games": len(records),
        "availableAttribution": ["PA probability loss", "PA predictive entropy", "state-transition loss", "transition sparse backoff", "missing simulator authority"],
        "notEstimable": ["lineup/pitcher participation error", "run-distribution error", "game calibration error"],
        "transitionOutcomesByLoss": outcome_summary,
        "systematicVsIrreducibleRule": "Repeated high loss with adequate support is a challenger signal; high entropy or sparse support is retained as uncertainty, not labeled systematic bias.",
    }
    return summary, records


def _challengers(transition_evaluation: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, list[float]] = defaultdict(list)
    rows: Counter[str] = Counter()
    for fold in transition_evaluation:
        if not fold.get("evaluationCompleted"):
            continue
        for name, metric in fold["evaluation"]["perOutcome"].items():
            totals[name].append(float(metric["nextTransitionLogLoss"]))
            rows[name] += int(metric["rows"])
    return [
        {"priority": 1, "opportunity": "Timestamped confirmed-lineup and announced-starter authority plus V18 prospective feature-template builder", "effectSize": "Restores coverage from zero to potentially all qualified games", "sampleSize": "0 currently governed games", "stability": "Structural blocker in every fold", "prospectivelyIdentifiable": True, "nextStep": "Capture source/observation/receipt timestamps and build 18 cutoff-valid V18 raw templates."},
        {"priority": 2, "opportunity": "BIP_OUT advancement subtype challenger", "effectSize": float(np.mean(totals["BIP_OUT"])), "effectMetric": "mean fold transition log loss", "sampleSize": rows["BIP_OUT"], "stability": {"minimum": min(totals["BIP_OUT"]), "maximum": max(totals["BIP_OUT"])}, "prospectivelyIdentifiable": "Requires pre-PA batted-ball/contact context; outcome subtype itself must not be post-outcome input."},
        {"priority": 3, "opportunity": "Cold-start PA probability specialist", "effectSize": 0.0006849245018535678, "effectMetric": "V18-minus-V14 log loss, either-player cold start", "sampleSize": 83174, "stability": "Nominal 95% interval [+0.000097594,+0.001276869]", "prospectivelyIdentifiable": True},
        {"priority": 4, "opportunity": "Prospective starter hook and bullpen selection/availability", "effectSize": "Not estimable until participant baseline exists", "sampleSize": "No governed bullpen decisions", "stability": "Structural limitation across all games", "prospectivelyIdentifiable": True, "nextStep": "Register timestamped roster, workload, and availability snapshots before fitting a hook/selection component."},
        {"priority": 5, "opportunity": "OTHER_REACH transition taxonomy", "effectSize": float(np.mean(totals["OTHER_REACH"])), "effectMetric": "mean fold transition log loss", "sampleSize": rows["OTHER_REACH"], "stability": {"minimum": min(totals["OTHER_REACH"]), "maximum": max(totals["OTHER_REACH"])}, "prospectivelyIdentifiable": "Only through pre-PA context; realized error subtype cannot be an input."},
    ]


def finalize(
    *,
    repository_root: Path,
    database_path: Path,
    comparison_path: Path,
    output_root: Path,
    exchange_root: Path,
    starting_commit: str,
) -> dict[str, Any]:
    repo = repository_root.resolve()
    if starting_commit != "227f1a814377a47f5e4defb570b22ca53bdc0faa":
        raise V18GameBaselineError("This finalization must start at the preserved V18 base commit 227f1a8.")
    criterion_checksum = _sha(CALIBRATION_CRITERION)  # pre-data identity
    comparison = verify_comparison(comparison_path)
    database = Database(str(database_path))
    authority = resolve_model_lab_authority(database, PROJECT_ID)
    if (
        authority.split.get("checksum") != "46a2f98ac5e96120855c70489fcd642883e84d9719037ecc44d4760b993b7846"
        or authority.split["finalOot"].get("locked") is not True
    ):
        raise V18GameBaselineError("The registered split or OOT seal differs.")
    scoring = game_scoring_summary(database, PROJECT_ID)
    if scoring["readiness"]["status"] != "BLOCKED_MISSING_GOVERNED_PREGAME_AUTHORITY":
        raise V18GameBaselineError("Stage3 game readiness changed; this fixed request requires review.")

    request = {
        "schemaVersion": "MLB_V18_PA_GAME_BASELINE_REQUEST_V1",
        "projectId": PROJECT_ID,
        "startingCommit": starting_commit,
        "comparisonChecksum": COMPARISON_SHA256,
        "v18RunReceiptSha256": V18_RUN_SHA256,
        "v18OofSha256": V18_OOF_SHA256,
        "v14RunReceiptSha256": V14_RUN_SHA256,
        "calibrationCriterionChecksum": criterion_checksum,
        "transition": {
            "alpha": bt.DEFAULT_ALPHA,
            "minCell": bt.MIN_CELL_COUNT,
            "scheduledFolds": 5,
            "sourceRegistrationId": FD1_REGISTRATION_ID,
            "sourceManifestSha256": FD1_MANIFEST_SHA256,
            "sourceMaximumDate": "2025-09-28",
        },
        "nullConformance": {"fold": 1, "draws": 4096, "seed": 20260907},
        "safety": {"paEstimatorFits": 0, "finalOotAccess": False, "promotion": False, "aispModification": False},
        "implementation": [
            _file_record(repo / "server/sports_current_statcast/mlb_v18_game_baseline.py", repo),
            _file_record(repo / "server/sports_phase5/base_out_transition.py", repo),
            _file_record(repo / "server/sports_phase5/whole_game_monte_carlo.py", repo),
        ],
    }
    request_sha = _sha(request)
    final_root = output_root.resolve() / "sha256" / request_sha
    if final_root.exists():
        manifest = _load_json(final_root / "manifest.json")
        if manifest.get("request") != request:
            raise V18GameBaselineError("Existing result address has a different request.")
        for name, record in manifest["artifacts"].items():
            path = final_root / name
            if not path.is_file() or _sha_bytes(path.read_bytes()) != record["sha256"]:
                raise V18GameBaselineError(f"Existing result artifact differs: {name}.")
        return _load_json(final_root / "results.json")

    transitions, reconstruction = load_registered_fd1_transitions(database_path, exchange_root)
    held = {str(row["canonicalPaId"]) for row in comparison["rowEligibility"]["heldObservations"]}
    if len(held) != 56:
        raise V18GameBaselineError("The frozen 56-row hold is unavailable.")
    if bool(transitions["canonicalPaId"].isin(held).any()):
        raise V18GameBaselineError("An unexpected cross-authority PA identity collision was found.")

    pa_finalist = finalist_decision(comparison)
    calibration = calibration_decision(comparison)
    if calibration["criterionChecksum"] != criterion_checksum:
        raise V18GameBaselineError("Calibration criterion mutated after evidence loading.")
    capability = capability_matrix(repo, authority, scoring)
    simulator = simulator_specification(comparison)

    final_root.mkdir(parents=True, exist_ok=False)
    transition_root = final_root / "transition-folds"
    transition_root.mkdir()
    folds: list[dict[str, Any]] = []
    game_records: list[pd.DataFrame] = []
    fold_one_model: bt.TransitionModel | None = None
    fold_one_pa_rates: list[float] | None = None
    transition_fits = 0
    transition_evaluations = 0
    source_minimum = str(transitions["game_date"].min())
    source_maximum = str(transitions["game_date"].max())
    for fold in authority.split["contract"]["folds"]:
        number = int(fold["foldNumber"])
        train = transitions.loc[transitions["game_date"].between(fold["trainStart"], fold["trainEnd"])].copy()
        validation = transitions.loc[transitions["game_date"].between(fold["validationStart"], fold["validationEnd"])].copy()
        training_complete = str(fold["trainStart"]) >= source_minimum and str(fold["trainEnd"]) <= source_maximum
        validation_complete = str(fold["validationStart"]) >= source_minimum and str(fold["validationEnd"]) <= source_maximum
        if not training_complete:
            folds.append({
                "foldNumber": number,
                "registered": dict(fold),
                "status": "BLOCKED_MISSING_COMPLETE_REGISTERED_TRANSITION_TRAINING_AUTHORITY",
                "availableTrainingTransitions": len(train),
                "availableValidationTransitions": len(validation),
                "sourceMaximumDate": source_maximum,
                "transitionEstimatorFitStarted": False,
                "transitionEstimatorFitCompleted": False,
                "evaluationCompleted": False,
            })
            continue
        model = bt.fit(_model_records(train), alpha=bt.DEFAULT_ALPHA, min_cell=bt.MIN_CELL_COUNT, seasons=sorted(train["season"].unique()))
        transition_fits += 1
        null_model = _null_state_model(train, bt.DEFAULT_ALPHA)
        model_payload = _native_json(model.to_dict())
        model_sha = _sha(model_payload)
        model_path = transition_root / f"fold-{number}-transition-{model_sha}.json"
        model_path.write_bytes(canonical_json_bytes(model_payload))
        null_sha = _sha(null_model)
        null_path = transition_root / f"fold-{number}-null-{null_sha}.json"
        null_path.write_bytes(canonical_json_bytes(null_model))
        reloaded = bt.TransitionModel.from_dict(_load_json(model_path))
        if _sha(reloaded.to_dict()) != model_sha:
            raise V18GameBaselineError("Transition artifact reload differs.")
        for outcome in bt.PA_CLASSES:
            for outs in range(3):
                for base in range(8):
                    bt.validate_distribution(reloaded.distribution(outcome, outs, base), outs, base)
        counts = train["pa_outcome"].value_counts()
        rates = [float(counts.get(name, 0) / len(train)) for name in PA_CLASS_ORDER]
        fold_record = {
            "foldNumber": number,
            "registered": dict(fold),
            "status": (
                "FIT_AND_EVALUATION_COMPLETE"
                if validation_complete
                else "FIT_COMPLETE_EVALUATION_BLOCKED_INCOMPLETE_REGISTERED_TRANSITION_VALIDATION_AUTHORITY"
            ),
            "reconstructedEligibleTrainingTransitions": len(train),
            "availableValidationTransitions": len(validation),
            "trainingGames": int(train["canonicalGameId"].nunique()),
            "availableValidationGames": int(validation["canonicalGameId"].nunique()),
            "paOutcomeRatesTrainingOnly": dict(zip(PA_CLASS_ORDER, rates)),
            "transitionArtifact": {"relativePath": str(model_path.relative_to(final_root)).replace("\\", "/"), "sha256": model_sha, "reloadVerified": True},
            "nullArtifact": {"relativePath": str(null_path.relative_to(final_root)).replace("\\", "/"), "sha256": null_sha},
            "transitionEstimatorFitStarted": True,
            "transitionEstimatorFitCompleted": True,
            "evaluationCompleted": validation_complete,
        }
        if validation_complete:
            evaluation, per_game = evaluate_transition_model(model, null_model, validation)
            transition_evaluations += 1
            per_game["foldNumber"] = number
            game_records.append(per_game)
            fold_record["reconstructedEligibleValidationTransitions"] = len(validation)
            fold_record["validationGames"] = int(validation["canonicalGameId"].nunique())
            fold_record["evaluation"] = evaluation
        else:
            fold_record["evaluation"] = {
                "status": "NOT_RUN_INCOMPLETE_REGISTERED_DATE_COVERAGE",
                "registeredValidationEnd": str(fold["validationEnd"]),
                "sourceMaximumDate": source_maximum,
                "partialRowsNotScoredAsFoldEvidence": len(validation),
            }
        folds.append(fold_record)
        if number == 1:
            fold_one_model, fold_one_pa_rates = reloaded, rates
    if fold_one_model is None or fold_one_pa_rates is None:
        raise V18GameBaselineError("Fold 1 transition conformance authority is absent.")
    conformance = _conformance(fold_one_model, fold_one_pa_rates, seed=20260907)

    runtime_root = repo / ".runtime/asp-model-studio/stage3-model-laboratory"
    oof_path = runtime_root / "objects/oof/sha256" / f"{V18_OOF_SHA256}.parquet"
    if _sha_bytes(oof_path.read_bytes()) != V18_OOF_SHA256:
        raise V18GameBaselineError("The saved V18 OOF artifact differs.")
    atlas, atlas_records = error_atlas(game_records, oof_path, folds)
    challengers = _challengers(folds)
    missing = {
        "schemaVersion": "MLB_V18_GAME_BASELINE_MISSING_AUTHORITY_LEDGER_V1",
        "blocking": [
            "TIMESTAMPED_CONFIRMED_TWO_SIDED_LINEUPS",
            "TIMESTAMPED_ANNOUNCED_STARTERS",
            "V18_PROSPECTIVE_246_RAW_INPUT_TEMPLATE_BUILDER",
            "REGISTERED_ORDERED_2026_PA_TRANSITION_TARGET_AUTHORITY_FOR_FOLDS_4_AND_5",
        ],
        "nonBlockingDeferred": [
            "BENCH_AND_SUBSTITUTION_POLICY", "BULLPEN_ROSTER_AVAILABILITY_AND_SELECTION",
            "STARTER_HOOK_AND_FATIGUE", "BETWEEN_PA_BASERUNNING_EVENTS",
            "PARK_WEATHER_UMPIRE_SPECIALISTS",
        ],
        "smallestNextStep": "Register immutable pregame lineup and starter snapshots with source/observation/receipt timestamps, add ordered 2026 transition targets, then implement and fixture-test an 18-row V18 raw-template builder against each saved fold pipeline before any game evaluation.",
        "oracleSubstituteProhibited": True,
        "transitionCoverage": {
            "scheduledFolds": 5,
            "estimatorFitsCompleted": transition_fits,
            "evaluationsCompleted": transition_evaluations,
            "foldsWithCompleteEvaluation": [row["foldNumber"] for row in folds if row["evaluationCompleted"]],
            "foldsBlocked": [row["foldNumber"] for row in folds if not row["evaluationCompleted"]],
            "reason": "FD1 ends 2025-09-28; registered folds 4 and 5 require 2026 transition targets.",
        },
    }

    files: dict[str, Any] = {
        "request.json": request,
        "pa-finalist-decision.json": pa_finalist,
        "calibration-decision.json": calibration,
        "capability-matrix.json": capability,
        "simulator-specification.json": simulator,
        "transition-reconstruction.json": reconstruction,
        "transition-evaluation.json": {
            "schemaVersion": "MLB_V18_FOLD_LOCAL_TRANSITION_EVALUATION_V1",
            "scheduledFolds": 5,
            "fitsCompleted": transition_fits,
            "evaluationsCompleted": transition_evaluations,
            "folds": folds,
        },
        "null-engine-conformance.json": conformance,
        "error-atlas-summary.json": atlas,
        "prioritized-challengers.json": {"schemaVersion": "MLB_V18_SIMULATOR_CHALLENGER_PRIORITIES_V1", "challengers": challengers},
        "missing-authority-ledger.json": missing,
    }
    for name, value in files.items():
        (final_root / name).write_bytes(canonical_json_bytes(value))
    with (final_root / "error-atlas-games.jsonl").open("wb") as stream:
        for record in atlas_records:
            stream.write(canonical_json_bytes(record) + b"\n")

    results: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PA_FINALIST_AND_PARTIAL_TRANSITION_FOUNDATION_COMPLETE_V18_GAME_EVALUATION_BLOCKED",
        "requestSha256": request_sha,
        "paFinalistDecisionId": pa_finalist["decisionId"],
        "calibrationDecisionId": calibration["decisionId"],
        "calibrationDisposition": calibration["disposition"],
        "simulatorDisposition": SIMULATOR_DISPOSITION,
        "transitionFoldsScheduled": 5,
        "transitionFoldsFit": transition_fits,
        "transitionFoldsEvaluated": transition_evaluations,
        "v18GameSimulations": 0,
        "nullConformanceSimulations": 4096,
        "paEstimatorFits": 0,
        "calibrationFits": 0,
        "transitionFits": transition_fits,
        "finalOotLocked": True,
        "finalOotAccessed": False,
        "gameEvaluation": "NOT_ESTIMABLE_FAIL_CLOSED",
        "inningEvaluation": "NOT_ESTIMABLE_FAIL_CLOSED",
        "gen1Comparison": "NOT_COMPARABLE_ON_CURRENT_FOLDS_AND_AUTHORITY",
        "errorAtlasStatus": atlas["status"],
        "recommendation": missing["smallestNextStep"],
    }
    results["resultChecksum"] = _sha(results)
    (final_root / "results.json").write_bytes(canonical_json_bytes(results))
    report = render_report(results, pa_finalist, calibration, capability, reconstruction, folds, conformance, atlas, challengers, missing)
    (final_root / "report.md").write_text(report, encoding="utf-8", newline="\n")
    artifacts: dict[str, Any] = {}
    for path in sorted(item for item in final_root.rglob("*") if item.is_file() and item.name != "manifest.json"):
        relative = str(path.relative_to(final_root)).replace("\\", "/")
        artifacts[relative] = {"bytes": path.stat().st_size, "sha256": _sha_bytes(path.read_bytes())}
    manifest = {
        "schemaVersion": "MLB_V18_PA_GAME_BASELINE_MANIFEST_V1",
        "request": request,
        "requestSha256": request_sha,
        "resultChecksum": results["resultChecksum"],
        "artifacts": artifacts,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    (final_root / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return results


def render_report(
    results: Mapping[str, Any], finalist: Mapping[str, Any], calibration: Mapping[str, Any],
    capability: Mapping[str, Any], reconstruction: Mapping[str, Any], folds: Sequence[Mapping[str, Any]],
    conformance: Mapping[str, Any], atlas: Mapping[str, Any], challengers: Sequence[Mapping[str, Any]],
    missing: Mapping[str, Any],
) -> str:
    matched = finalist["matchedComparison"]
    lines = [
        "# MLB V18 PA finalist and governed game-baseline foundation", "",
        f"Status: `{results['status']}`.", "",
        "## PA-finalist decision", "",
        f"Disposition: `{finalist['disposition']}`; decision `{finalist['decisionId']}`.", "",
        f"On {matched['observations']:,} matched PAs, V18 log loss was {matched['v18LogLoss']:.12f} versus {matched['v14LogLoss']:.12f} for V14 (difference {matched['v18MinusV14LogLoss']:+.12f}; paired game-clustered 95% CI [{matched['pairedGameClustered95PercentInterval']['lower']:+.12f}, {matched['pairedGameClustered95PercentInterval']['upper']:+.12f}]). V18 did not demonstrate superiority, equivalence, or noninferiority. It advances only as the governed PA-component finalist for Development game-simulation work.", "",
        "All six predefined cold/no-history point estimates were worse. The either-player cold-start and three overlapping 47-game team no-history intervals were nominally positive; they remain uncertainty/qualification risks, not a basis for a V14/V18 hybrid.", "",
        "## Calibration decision", "",
        f"Disposition: `{calibration['disposition']}`; decision `{calibration['decisionId']}`.", "",
        "The predeclared criterion was hashed before evidence loading and evaluates aggregate, class, rare-class, probability-band, fold, and stable-subgroup behavior. One populated temporal-fold reliability-band gate fails, so a calibration challenger is required before the baseline can be qualified. No calibrator was fitted here. Raw V18 probabilities remain permissible only for a clearly labeled uncalibrated Development baseline; sparse no-history groups remain non-gating warnings.", "",
        "| Calibration gate | Observed | Maximum | Pass |", "| --- | ---: | ---: | --- |",
    ]
    for name, value in calibration["checks"].items():
        lines.append(f"| {name} | {value['value']:.9f} | {value['threshold']:.9f} | {value['pass']} |")
    lines += ["", "## Executable authority result", "",
        f"V18 game disposition: `{results['simulatorDisposition']}`. The current Stage3 readiness endpoint reports no registered executable artifact, zero governed games, and missing timestamped lineup/starter authority. A V18 game run therefore fails closed: no realized PA sequence, actual substitutions, or actual relievers were substituted.", "",
        "The repository does support the sequential 24-state engine and fold-local transition estimation. A 4,096-draw, participant-free league-average null conformance run completed with zero illegal and zero nonterminated simulations; it is not a V18 forecast or game-level evaluation.", "",
        "## Capability matrix", "", "| Capability | Classification | Implication |", "| --- | --- | --- |"]
    for row in capability["capabilities"]:
        lines.append(f"| {row['capability']} | `{row['classification']}` | {row['implication']} |")
    lines += ["", "## Fold-local transition evidence", "",
        f"The registered FD1 authority supplied {reconstruction['terminalPaTransitionRows']:,} explicit terminal-PA transitions from {reconstruction['rawPlayTransitionRows']:,} play-transition rows across {reconstruction['games']:,} games, covering {reconstruction['minimumDate']} through {reconstruction['maximumDate']}. It is retrospective target evidence used only inside its corresponding training/evaluation windows. The opaque Current Gold 2025-2026 PA keys were not sorted or inferred.", "",
        "| Fold | Status | Train transitions | Validation transitions | Model log loss | Null log loss | Difference | Transition ECE | Base accuracy | Outs accuracy |", "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for fold in folds:
        if not fold["evaluationCompleted"]:
            lines.append(
                f"| {fold['foldNumber']} | `{fold['status']}` | {fold.get('reconstructedEligibleTrainingTransitions', fold.get('availableTrainingTransitions', 0)):,} | {fold.get('availableValidationTransitions', 0):,} (partial/not scored) | — | — | — | — | — | — |"
            )
            continue
        metric = fold["evaluation"]
        lines.append(
            f"| {fold['foldNumber']} | `{fold['status']}` | {fold['reconstructedEligibleTrainingTransitions']:,} | {fold['reconstructedEligibleValidationTransitions']:,} | {metric['model']['nextTransitionLogLoss']:.6f} | {metric['leagueAverageStateNull']['nextTransitionLogLoss']:.6f} | {metric['modelMinusNullLogLoss']:+.6f} | {metric['model']['topTransitionExpectedCalibrationError']:.6f} | {metric['model']['baseMaskAfterAccuracy']:.4f} | {metric['model']['outsAddedAccuracy']:.4f} |"
        )
    lines += ["", f"Four transition estimators were fitted: folds 1-4 had complete training authority. Only folds 1-3 had complete validation authority and were evaluated. Fold 4 validation extends into 2026 and fold 5 training/validation require 2026, while registered FD1 ends on 2025-09-28. Partial fold-4 rows were not scored as complete-fold evidence. Each fitted JSON artifact contains exact counts and probabilities for outcome × outs × base, outcome × outs, and outcome backoffs, plus a uniform legal prior. Home runs use the deterministic conservation rule. Every artifact was reloaded and all 192 distributions were legality/sum checked.", "",
        "## Inning/game evaluation and comparisons", "",
        "V18 inning and game metrics, team-run distributions, home-win scoring, temporal/park/cold propagation, and representative game paths are **not estimable**. That is a result of missing pregame authority, not a silent omission. The older Gen 1/Phase 7 evidence uses different cohorts, model contracts, and historically reconstructed participants, so no misleading numeric same-game comparison is reported.", "",
        "## Error and Regime Atlas foundation", "",
        f"The component ledger covers {atlas['games']:,} OOF games with saved PA loss/entropy, fold-local transition loss/null improvement, sparse-backoff rate, and an explicit missing-authority flag. Participation, run-distribution, and game-calibration errors remain null because no valid game forecast exists.", "",
        "## Prioritized simulator challengers", ""]
    for row in challengers:
        lines.append(f"{row['priority']}. **{row['opportunity']}** — sample/effect evidence: {row['sampleSize']}; {row['effectSize']}.")
    lines += ["", "## Governance and next step", "",
        f"Smallest next step: {missing['smallestNextStep']}", "",
        f"No PA estimator or calibrator was fitted. {results['transitionFits']} authorized transition fits, {results['transitionFoldsEvaluated']} complete-fold transition evaluations, and one participant-free null conformance simulation were completed. Final OOT remained sealed; no model was promoted, exported, deployed, merged, or registered in AISP.", ""]
    return "\n".join(lines)


__all__ = [
    "CALIBRATION_CRITERION", "CALIBRATION_DISPOSITION", "CALIBRATION_REQUIRED", "FINALIST_DISPOSITION",
    "SIMULATOR_DISPOSITION", "V18GameBaselineError", "calibration_decision",
    "capability_matrix", "evaluate_transition_model", "finalist_decision", "finalize",
    "reconstruct_transitions", "render_report", "simulator_specification",
]
