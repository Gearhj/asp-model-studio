from __future__ import annotations

import copy
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ..persistence.db import Database, decode_row, json_dumps, now_iso
from ..sports_datasets.constants import (
    EXPECTED_FOLDS,
    MANIFEST_SHA,
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    REGISTRATION_ID,
)
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    BRIDGE_MANIFEST_SHA,
    BRIDGE_MANIFEST_ID,
    BRIDGE_PACKAGE_ID,
    BRIDGE_REGISTRATION_ID,
    CONTRACT_NAME as IDENTITY_BRIDGE_CONTRACT_NAME,
    CONTRACT_VERSION as IDENTITY_BRIDGE_CONTRACT_VERSION,
    DIMENSION_AUTHORITY_SHA,
    EXPECTED_ACTIVE_PLAYER_ROWS,
    EXPECTED_ALIAS_ROWS,
    EXPECTED_GOVERNED_ACTIVE_PLAYERS,
    EXPECTED_JOIN_CONTRACTS,
    EXPECTED_JOIN_REFERENCES,
    EXPECTED_JOIN_VALIDATION,
    EXPECTED_LIMITATION_IDS,
    EXPECTED_NAMESPACE_COUNT,
    EXPECTED_PACKAGE_BYTES,
    EXPECTED_PACKAGE_FILES,
    EXPECTED_PRIMARY_GOVERNED_PLAYERS,
    EXPECTED_PRIMARY_PORTABLE_PLAYERS,
    EXPECTED_Y_MINUS_1,
    LOGICAL_PACKAGE_ROOT as IDENTITY_BRIDGE_LOGICAL_ROOT,
    ALLOWED_PURPOSES,
    PROHIBITED_PURPOSES,
    VALIDATION_REPORT_SHA,
)
from .bootstrap import (
    BOOTSTRAP_SCHEMA_VERSION,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CONFIDENCE_LEVEL,
)
from .calibration import (
    CALIBRATION_RETENTION_TOLERANCE,
    CALIBRATION_SCHEMA_VERSION,
    DEFAULT_TEMPERATURE_BOUNDS,
)
from .feature_contract import (
    CANDIDATE_FEATURES,
    C_GRID,
    FEATURE_NAMES,
    feature_contract_sha,
)
from .metrics import (
    DEFAULT_CALIBRATION_BINS,
    METRICS_SCHEMA_VERSION,
    PA_CLASS_ORDER,
)
from .training import DEFAULT_MAX_ITER, DEFAULT_TOLERANCE


RUN_SCHEMA_VERSION = "MLB_PA_RESEARCH_RUN_V1"
RUN_IDENTITY_SCHEMA_VERSION = "MLB_PA_RUN_IDENTITY_V1"
RUN_IDENTITY_CORE_SCHEMA_VERSION = "MLB_PA_RUN_IDENTITY_CORE_V1"
FEATURE_VIEW_CONTRACT_NAME = "MLB_PA_FEATURE_VIEW"
FEATURE_VIEW_CONTRACT_VERSION = "MLB_PA_FEATURE_VIEW_V1"
EXPECTED_FEATURE_VIEW_ROWS = 549_479
EXPECTED_FEATURE_VIEW_SEASONS = (2023, 2024, 2025)
EXPECTED_CANDIDATES = ("C0", "C1", "C2", "C3", "C4")
EXPECTED_CANDIDATE_TYPES = {
    "C0": "GLOBAL_CLASS_FREQUENCY",
    "C1": "MULTINOMIAL_LOGISTIC_L2",
    "C2": "MULTINOMIAL_LOGISTIC_L2",
    "C3": "MULTINOMIAL_LOGISTIC_L2",
    "C4": "MULTINOMIAL_LOGISTIC_L2",
}
EXPECTED_CANDIDATE_LABELS = {
    "C0": "Global eight-class frequency",
    "C1": "Conditional PA-state context",
    "C2": "PA-state context plus batter prior",
    "C3": "PA-state context plus pitcher prior",
    "C4": "Combined PA-state and batter/pitcher priors",
}
TERMINAL_STATUSES = frozenset(
    {
        "RESEARCH_CHALLENGER",
        "RESEARCH_BASELINE",
        "REJECTED_BASELINE",
        "BLOCKED",
    }
)
COMPLETE_TERMINAL_STATUSES = TERMINAL_STATUSES - {"BLOCKED"}
TERMINAL_METRIC_TOLERANCE = 1e-10
EXPECTED_VALIDATION_GAME_COUNTS = {2024: 2_429, 2025: 2_430}
ALLOWED_LOGICAL_SCHEMES = (
    "asp-model-studio-runtime://",
    "asp-model-exchange://",
    "target-local://",
)

_SHA_RE = re.compile(r"[0-9a-f]{64}")
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)^[a-z]:[\\/]")
_EMBEDDED_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?:^|[\\/])[a-z]:[\\/]")
_TOKEN_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:^|[\s'\"`\[\]\(\)\{\}=])(?:[a-z]:[\\/]|\\\\[^\s\\/]|//[^\s/]|/(?!/)[a-z0-9._~-])"
)
_TOKEN_FILE_URI_RE = re.compile(r"(?i)(?:^|[\s'\"`\[\]\(\)\{\}=])file:")
_TOP_KEYS = {
    "schemaVersion",
    "runId",
    "runSha",
    "runIdentity",
    "projectId",
    "parent",
    "identityBridge",
    "classOrder",
    "featureView",
    "experiment",
    "candidates",
    "selected",
    "calibration",
    "bootstrapComparisons",
    "artifacts",
    "graph",
    "decision",
}
_RUN_IDENTITY_KEYS = {"schemaVersion", "coreSha", "createdAt", "codeRevision"}
_RUN_IDENTITY_CORE_FIELDS = (
    "schemaVersion",
    "projectId",
    "parent",
    "identityBridge",
    "classOrder",
    "featureView",
    "experiment",
    "candidates",
    "selected",
    "calibration",
    "bootstrapComparisons",
    "graph",
    "decision",
)
_FEATURE_ARTIFACT_LOCATOR_FIELDS = {"logicalUri", "artifactSha", "artifactBytes"}
_PARENT_KEYS = {"registrationId", "manifestSha", "partitionAuthoritySha"}
_BRIDGE_KEYS = {"registrationId", "manifestSha", "joinAuditId"}
_FEATURE_KEYS = {
    "featureViewId",
    "contractName",
    "contractVersion",
    "contentSha",
    "rowCount",
    "featureCount",
    "featureNames",
    "population",
    "seasons",
    "logicalUri",
    "artifactSha",
    "artifactBytes",
}
_EXPERIMENT_KEYS = {"experimentId", "objective", "seed", "trainingContractVersion"}
_CANDIDATE_KEYS = {
    "candidateId",
    "candidateType",
    "displayName",
    "ordinal",
    "config",
    "configSha",
    "runtimeSeconds",
    "convergence",
    "foldMetrics",
    "aggregateMetrics",
    "eligible",
    "rejectionReasons",
}
_FOLD_KEYS = {
    "foldId",
    "status",
    "trainingSeasons",
    "validationSeason",
    "trainingRows",
    "validationRows",
    "metrics",
}
_CONVERGENCE_KEYS = {"status", "converged", "nIter", "maxIter", "solver"}
_AGGREGATE_METRICS_KEYS = {"selection2024", "inner2023Tuning", "final2025"}
_TUNING_EVIDENCE_KEYS = {"C", "trainingRows", "validationRows", "metrics", "nIter"}
_SELECTED_KEYS = {"candidateId", "selectionMetric", "rationale"}
_CALIBRATION_KEYS = {
    "schemaVersion",
    "decision",
    "method",
    "sourceSeason",
    "candidateId",
    "fittedTemperature",
    "retainedTemperature",
    "retained",
    "raw2024",
    "scaled2024",
    "raw2025",
    "scaled2025",
    "final2025",
    "rationale",
}
_BOOTSTRAP_KEYS = {
    "schemaVersion",
    "candidateId",
    "baselineCandidateId",
    "foldId",
    "validationSeason",
    "clusterUnit",
    "seed",
    "resamples",
    "confidenceLevel",
    "evidence",
}
_BOOTSTRAP_EVIDENCE_KEYS = {
    "schemaVersion",
    "classOrder",
    "differenceConvention",
    "resamplingUnit",
    "resamplingMethod",
    "rowsSampledIndependently",
    "rowCount",
    "clusterCount",
    "clusterDrawsPerReplicate",
    "resampleCount",
    "seed",
    "confidenceLevel",
    "logLossDifference",
    "brierScoreDifference",
}
_BOOTSTRAP_SUMMARY_KEYS = {
    "pointEstimate",
    "bootstrapMean",
    "bootstrapStandardError",
    "percentileInterval",
    "probabilitySelectedBetter",
    "replicateDifferences",
}
_BOOTSTRAP_INTERVAL_KEYS = {"confidenceLevel", "lower", "upper"}
_ARTIFACT_KEYS = {
    "artifactId",
    "artifactType",
    "logicalUri",
    "sha256",
    "byteCount",
    "mediaType",
}
_COMPLETED_ARTIFACT_CARDINALITIES = {
    "FEATURE_VIEW": 1,
    "FEATURE_VIEW_RUN_BINDING": 1,
    "FEATURE_CONTRACT": 1,
    "FEATURE_SCHEMA": 1,
    "CLASS_ORDER": 1,
    "MODEL_STATE": 8,
    "PREPROCESSOR_STATE": 6,
    "FOLD_2024_PREDICTIONS": 1,
    "FOLD_2025_PREDICTIONS": 1,
    "EXPERIMENT_METRICS": 1,
    "CONFUSION_MATRICES": 1,
    "CALIBRATION_EVIDENCE": 1,
    "BOOTSTRAP_EVIDENCE": 1,
    "LINEAGE": 1,
    "MODEL_CARD": 1,
    "FINAL_CHECKPOINT": 1,
}
_METRICS_KEYS = {
    "schemaVersion",
    "classOrder",
    "rowCount",
    "binCount",
    "binningRule",
    "logLoss",
    "brierScore",
    "brierDefinition",
    "classwiseBrier",
    "topLabelEce",
    "classwiseEce",
    "top1Accuracy",
    "balancedAccuracy",
    "macroF1",
    "weightedF1",
    "perClass",
    "confusionMatrix",
    "confusionMatrixAxes",
    "realizedPrevalence",
    "predictedPrevalence",
    "argmaxPrevalence",
    "topLabelReliability",
    "classwiseReliability",
    "probabilityHistograms",
}
_PER_CLASS_METRIC_KEYS = {"precision", "recall", "f1", "support"}
_BIN_BASE_KEYS = {
    "binIndex",
    "lowerBound",
    "upperBound",
    "upperBoundInclusive",
    "count",
}
_TOP_LABEL_BIN_KEYS = _BIN_BASE_KEYS | {
    "meanConfidence",
    "accuracy",
    "gap",
    "absoluteGap",
}
_CLASSWISE_BIN_KEYS = _BIN_BASE_KEYS | {
    "meanProbability",
    "realizedFrequency",
    "gap",
    "absoluteGap",
}
_HISTOGRAM_BIN_KEYS = _BIN_BASE_KEYS | {"populationShare"}

_COMPLETE_DECISION_RATIONALES = {
    "RESEARCH_CHALLENGER": (
        "The frozen selected model strictly improves global-baseline log loss, does not "
        "worsen Brier or top-label ECE, and has finite classwise calibration in both "
        "rolling-origin validation folds. This remains research evidence only."
    ),
    "REJECTED_BASELINE": (
        "Every substantive contextual/prior candidate is worse than the global baseline "
        "on both 2024 governing losses, and the frozen selected pipeline is also worse "
        "on both losses in 2025."
    ),
    "RESEARCH_BASELINE": (
        "The run is valid, but frozen-fold evidence is mixed, small, or uncertain under "
        "the predeclared challenger and rejection predicates."
    ),
}
_GOVERNED_DECISION_LIMITATIONS = [
    "This is a conditional plate appearance component, not a standalone pregame or game forecast.",
    "Handedness and platoon fields are absent from the approved FD1 inputs.",
    "Future participation, simulation, and export are not configured by this research run.",
    "Retrospective reconstruction is not prospective availability or performance evidence.",
]
_GOVERNED_DECISION_NEXT_STEP = (
    "Review fold metrics, calibration, and whole-game bootstrap evidence before any "
    "separate simulator, prospective-validation, or deployment authorization work."
)
_BLOCKED_SUITABILITY_RE = re.compile(
    r"(?i)(?:\b(?:production[- ]ready|betting|wagering|sportsbook)\b|"
    r"\b(?:deployment|production)\s+(?:ready|suitable|approved|authorized|eligible|safe)\b|"
    r"\b(?:ready|suitable|approved|authorized|eligible|safe)\s+for\s+(?:deployment|production)\b)"
)
_GRAPH_KEYS = {"graphId", "nodes", "edges"}
_NODE_KEYS = {"nodeId", "nodeType", "label", "status", "candidateId"}
_EDGE_KEYS = {"edgeId", "sourceNodeId", "targetNodeId", "relation"}
_DECISION_KEYS = {
    "terminalStatus",
    "rationale",
    "researchOnly",
    "deploymentAuthorized",
    "limitations",
    "recommendedNextStep",
}
_BANNED_NORMALIZED_KEYS = {
    "physicalpath",
    "filepath",
    "localpath",
    "packageroot",
    "exchangeroot",
    "predictionrows",
    "predictions",
    "modelbytes",
    "modelblob",
    "serializedmodel",
    "fittedmodelbytes",
    "estimatorbytes",
    "picklebytes",
    "joblibbytes",
    "onnxbytes",
}


class SportsPARegistryError(RuntimeError):
    """Fail-closed metadata registry error with no physical path detail."""


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise SportsPARegistryError(
            f"{label} fields differ (missing={sorted(expected - actual)}, extra={sorted(actual - expected)})"
        )


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise SportsPARegistryError(f"{label} must be an object")
    return value


def _list(value: Any, *, label: str) -> list[Any]:
    if type(value) is not list:
        raise SportsPARegistryError(f"{label} must be an array")
    return value


def _nonblank(value: Any, *, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise SportsPARegistryError(f"{label} must be a non-blank canonical string")
    return value


def _integer(value: Any, *, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise SportsPARegistryError(f"{label} must be an integer greater than or equal to {minimum}")
    return value


def _finite(value: Any, *, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise SportsPARegistryError(f"{label} must be a finite number")
    return float(value)


def _sha(value: Any, *, label: str) -> str:
    if type(value) is not str or not _SHA_RE.fullmatch(value):
        raise SportsPARegistryError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _logical_uri(value: Any, *, label: str) -> str:
    uri = _nonblank(value, label=label)
    scheme = next((item for item in ALLOWED_LOGICAL_SCHEMES if uri.startswith(item)), None)
    if scheme is None or "\\" in uri:
        raise SportsPARegistryError(f"{label} must be an approved logical URI")
    suffix = uri[len(scheme):]
    if (
        not suffix
        or suffix.startswith("/")
        or any(character in suffix for character in (":", "%", "?", "#"))
        or any(part in {"", ".", ".."} for part in suffix.split("/"))
        or _EMBEDDED_WINDOWS_ABSOLUTE_RE.search(suffix)
    ):
        raise SportsPARegistryError(f"{label} must be a normalized logical URI")
    return uri


def _scan_public_safety(value: Any, *, path: str = "$") -> None:
    if isinstance(value, bytes):
        raise SportsPARegistryError(f"Binary payloads are prohibited at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in _BANNED_NORMALIZED_KEYS:
                raise SportsPARegistryError(f"Prediction, model-byte, or physical-path field is prohibited at {path}")
            _scan_public_safety(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_public_safety(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        if (
            _TOKEN_ABSOLUTE_PATH_RE.search(value)
            or _TOKEN_FILE_URI_RE.search(value)
            or _WINDOWS_ABSOLUTE_RE.match(value)
            or _EMBEDDED_WINDOWS_ABSOLUTE_RE.search(value)
            or "/.runtime/" in value.casefold()
            or "\\.runtime\\" in value.casefold()
        ):
            raise SportsPARegistryError(f"Physical or runtime path is prohibited at {path}")


def semantic_run_sha(payload: Mapping[str, Any]) -> str:
    semantic = copy.deepcopy(dict(payload))
    semantic.pop("runId", None)
    semantic.pop("runSha", None)
    try:
        return sha256_bytes(canonical_json_bytes(semantic))
    except Exception as exc:
        raise SportsPARegistryError("Run payload is not canonical JSON") from exc


def semantic_run_identity_sha(
    payload: Mapping[str, Any],
    *,
    created_at: str,
    code_revision: str,
) -> str:
    """Hash the exact pre-artifact governed execution core used for runId."""

    try:
        core_projection = {
            field: copy.deepcopy(payload[field])
            for field in _RUN_IDENTITY_CORE_FIELDS
        }
        feature_view = dict(
            _mapping(core_projection["featureView"], label="run identity featureView")
        )
        for field in _FEATURE_ARTIFACT_LOCATOR_FIELDS:
            feature_view.pop(field, None)
        core_projection["featureView"] = feature_view
        core = {
            "schemaVersion": RUN_IDENTITY_CORE_SCHEMA_VERSION,
            "createdAt": created_at,
            "codeRevision": code_revision,
            "coreProjection": core_projection,
        }
        return sha256_bytes(canonical_json_bytes(core))
    except SportsPARegistryError:
        raise
    except Exception as exc:
        raise SportsPARegistryError("Run identity core is not canonical JSON") from exc


def _validate_run_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    identity = dict(_mapping(payload["runIdentity"], label="runIdentity"))
    _exact_keys(identity, _RUN_IDENTITY_KEYS, label="runIdentity")
    if identity["schemaVersion"] != RUN_IDENTITY_SCHEMA_VERSION:
        raise SportsPARegistryError("Run identity schema version differs")
    created_at = _nonblank(identity["createdAt"], label="runIdentity.createdAt")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SportsPARegistryError("runIdentity.createdAt must be an ISO-8601 timestamp") from exc
    if parsed_created_at.tzinfo is None or parsed_created_at.utcoffset() is None:
        raise SportsPARegistryError("runIdentity.createdAt must include a UTC offset")
    code_revision = _nonblank(identity["codeRevision"], label="runIdentity.codeRevision")
    claimed_core_sha = _sha(identity["coreSha"], label="runIdentity.coreSha")
    expected_core_sha = semantic_run_identity_sha(
        payload,
        created_at=created_at,
        code_revision=code_revision,
    )
    if claimed_core_sha != expected_core_sha:
        raise SportsPARegistryError("Run identity core digest differs")
    if payload["runId"] != f"sports-pa-research-run:sha256:{expected_core_sha}":
        raise SportsPARegistryError("runId is not bound to the governed pre-artifact core")
    return identity


def _close(left: float, right: float, *, tolerance: float = 1e-10) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def _validate_class_number_mapping(
    value: Any,
    *,
    label: str,
    maximum: float = 1.0,
) -> dict[str, float]:
    rows = dict(_mapping(value, label=label))
    _exact_keys(rows, set(PA_CLASS_ORDER), label=label)
    output: dict[str, float] = {}
    for class_name in PA_CLASS_ORDER:
        number = _finite(rows[class_name], label=f"{label}.{class_name}")
        if not 0.0 <= number <= maximum:
            raise SportsPARegistryError(f"{label}.{class_name} must be within [0, {maximum:g}]")
        output[class_name] = number
    return output


def _validate_metric_bins(
    value: Any,
    *,
    expected_rows: int,
    label: str,
    kind: str,
) -> tuple[float, float, float] | None:
    rows = _list(value, label=label)
    if len(rows) != DEFAULT_CALIBRATION_BINS:
        raise SportsPARegistryError(f"{label} must contain the frozen calibration bins")
    if kind == "top-label":
        expected_keys = _TOP_LABEL_BIN_KEYS
        mean_key, outcome_key = "meanConfidence", "accuracy"
    elif kind == "classwise":
        expected_keys = _CLASSWISE_BIN_KEYS
        mean_key, outcome_key = "meanProbability", "realizedFrequency"
    elif kind == "histogram":
        expected_keys = _HISTOGRAM_BIN_KEYS
        mean_key = outcome_key = ""
    else:  # pragma: no cover - internal misuse guard
        raise AssertionError(f"unknown metric-bin kind: {kind}")

    total_count = 0
    weighted_gap = 0.0
    weighted_mean = 0.0
    weighted_outcome = 0.0
    population_share_sum = 0.0
    for expected_index, raw in enumerate(rows):
        item = dict(_mapping(raw, label=f"{label}[{expected_index}]"))
        _exact_keys(item, expected_keys, label=f"{label}[{expected_index}]")
        if item["binIndex"] != expected_index:
            raise SportsPARegistryError(f"{label} bin indices differ from frozen order")
        lower = _finite(item["lowerBound"], label=f"{label}[{expected_index}].lowerBound")
        upper = _finite(item["upperBound"], label=f"{label}[{expected_index}].upperBound")
        expected_lower = expected_index / DEFAULT_CALIBRATION_BINS
        expected_upper = (expected_index + 1) / DEFAULT_CALIBRATION_BINS
        if (
            not _close(lower, expected_lower)
            or not _close(upper, expected_upper)
            or item["upperBoundInclusive"] is not (expected_index == DEFAULT_CALIBRATION_BINS - 1)
        ):
            raise SportsPARegistryError(f"{label} bin-boundary policy differs")
        count = _integer(item["count"], label=f"{label}[{expected_index}].count")
        total_count += count

        if kind == "histogram":
            share = _finite(
                item["populationShare"],
                label=f"{label}[{expected_index}].populationShare",
            )
            if not 0.0 <= share <= 1.0 or not _close(share, count / expected_rows):
                raise SportsPARegistryError(f"{label} population share does not reconcile to count")
            population_share_sum += share
            continue

        statistic_keys = (mean_key, outcome_key, "gap", "absoluteGap")
        if count == 0:
            if any(item[key] is not None for key in statistic_keys):
                raise SportsPARegistryError(f"{label} empty bins must contain null statistics")
            continue
        if any(item[key] is None for key in statistic_keys):
            raise SportsPARegistryError(f"{label} populated bins require complete statistics")
        mean = _finite(item[mean_key], label=f"{label}[{expected_index}].{mean_key}")
        outcome = _finite(item[outcome_key], label=f"{label}[{expected_index}].{outcome_key}")
        gap = _finite(item["gap"], label=f"{label}[{expected_index}].gap")
        absolute_gap = _finite(
            item["absoluteGap"],
            label=f"{label}[{expected_index}].absoluteGap",
        )
        if not 0.0 <= mean <= 1.0 or not 0.0 <= outcome <= 1.0:
            raise SportsPARegistryError(f"{label} probabilities and frequencies must be within [0, 1]")
        if mean < lower - 1e-12 or mean > upper + 1e-12 or (
            expected_index < DEFAULT_CALIBRATION_BINS - 1 and mean >= upper
        ):
            raise SportsPARegistryError(f"{label} mean lies outside its frozen bin")
        if not _close(gap, outcome - mean) or not _close(absolute_gap, abs(gap)):
            raise SportsPARegistryError(f"{label} gap statistics do not reconcile")
        weighted_gap += count * absolute_gap
        weighted_mean += count * mean
        weighted_outcome += count * outcome

    if total_count != expected_rows:
        raise SportsPARegistryError(f"{label} bin counts do not reconcile to rowCount")
    if kind == "histogram":
        if not _close(population_share_sum, 1.0):
            raise SportsPARegistryError(f"{label} population shares must sum to one")
        return None
    return (
        weighted_gap / expected_rows,
        weighted_mean / expected_rows,
        weighted_outcome / expected_rows,
    )


def _validate_metrics(value: Any, *, expected_rows: int, label: str) -> dict[str, Any]:
    metrics = dict(_mapping(value, label=label))
    _exact_keys(metrics, _METRICS_KEYS, label=label)
    if metrics["schemaVersion"] != METRICS_SCHEMA_VERSION:
        raise SportsPARegistryError(f"{label} schema version differs")
    if metrics["classOrder"] != list(PA_CLASS_ORDER):
        raise SportsPARegistryError(f"{label} class order differs")
    if metrics["rowCount"] != expected_rows:
        raise SportsPARegistryError(f"{label} row count differs")
    if metrics["binCount"] != DEFAULT_CALIBRATION_BINS or metrics["binningRule"] != (
        "FIXED_EQUAL_WIDTH_LEFT_CLOSED_FINAL_RIGHT_CLOSED"
    ):
        raise SportsPARegistryError(f"{label} calibration-bin policy differs")
    if metrics["brierDefinition"] != "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR":
        raise SportsPARegistryError(f"{label} Brier-score policy differs")

    log_loss = _finite(metrics["logLoss"], label=f"{label}.logLoss")
    brier_score = _finite(metrics["brierScore"], label=f"{label}.brierScore")
    if log_loss < 0.0 or not 0.0 <= brier_score <= 2.0:
        raise SportsPARegistryError(f"{label} loss values are outside governed ranges")
    bounded_metrics: dict[str, float] = {}
    for key in (
        "topLabelEce",
        "top1Accuracy",
        "balancedAccuracy",
        "macroF1",
        "weightedF1",
    ):
        number = _finite(metrics[key], label=f"{label}.{key}")
        if not 0.0 <= number <= 1.0:
            raise SportsPARegistryError(f"{label}.{key} must be within [0, 1]")
        bounded_metrics[key] = number

    classwise_brier = _validate_class_number_mapping(
        metrics["classwiseBrier"], label=f"{label}.classwiseBrier"
    )
    if not _close(math.fsum(classwise_brier.values()), brier_score):
        raise SportsPARegistryError(f"{label} classwise Brier values do not sum to brierScore")
    classwise_ece = _validate_class_number_mapping(
        metrics["classwiseEce"], label=f"{label}.classwiseEce"
    )

    confusion_raw = _list(metrics["confusionMatrix"], label=f"{label}.confusionMatrix")
    if len(confusion_raw) != len(PA_CLASS_ORDER):
        raise SportsPARegistryError(f"{label} confusion matrix must be 8x8")
    confusion: list[list[int]] = []
    for row_index, raw_row in enumerate(confusion_raw):
        row = _list(raw_row, label=f"{label}.confusionMatrix[{row_index}]")
        if len(row) != len(PA_CLASS_ORDER):
            raise SportsPARegistryError(f"{label} confusion matrix must be 8x8")
        confusion.append(
            [
                _integer(count, label=f"{label}.confusionMatrix[{row_index}][{column_index}]")
                for column_index, count in enumerate(row)
            ]
        )
    if sum(map(sum, confusion)) != expected_rows:
        raise SportsPARegistryError(f"{label} confusion matrix total differs from rowCount")
    if metrics["confusionMatrixAxes"] != {"rows": "realized", "columns": "predicted"}:
        raise SportsPARegistryError(f"{label} confusion-matrix axes differ")

    per_class = dict(_mapping(metrics["perClass"], label=f"{label}.perClass"))
    _exact_keys(per_class, set(PA_CLASS_ORDER), label=f"{label}.perClass")
    supports: dict[str, int] = {}
    class_f1: dict[str, float] = {}
    class_recall: dict[str, float] = {}
    column_counts = [sum(row[index] for row in confusion) for index in range(len(PA_CLASS_ORDER))]
    for index, class_name in enumerate(PA_CLASS_ORDER):
        item = dict(_mapping(per_class[class_name], label=f"{label}.perClass.{class_name}"))
        _exact_keys(item, _PER_CLASS_METRIC_KEYS, label=f"{label}.perClass.{class_name}")
        support = _integer(item["support"], label=f"{label}.perClass.{class_name}.support")
        if support != sum(confusion[index]):
            raise SportsPARegistryError(f"{label} per-class support differs from confusion matrix")
        values = {
            key: _finite(item[key], label=f"{label}.perClass.{class_name}.{key}")
            for key in ("precision", "recall", "f1")
        }
        if any(not 0.0 <= number <= 1.0 for number in values.values()):
            raise SportsPARegistryError(f"{label} per-class metrics must be within [0, 1]")
        true_positive = confusion[index][index]
        expected_precision = true_positive / column_counts[index] if column_counts[index] else 0.0
        expected_recall = true_positive / support if support else 0.0
        expected_f1 = (
            2.0 * expected_precision * expected_recall / (expected_precision + expected_recall)
            if expected_precision + expected_recall
            else 0.0
        )
        if (
            not _close(values["precision"], expected_precision)
            or not _close(values["recall"], expected_recall)
            or not _close(values["f1"], expected_f1)
        ):
            raise SportsPARegistryError(f"{label} per-class metrics do not reconcile to confusion matrix")
        supports[class_name] = support
        class_f1[class_name] = values["f1"]
        class_recall[class_name] = values["recall"]
    if sum(supports.values()) != expected_rows:
        raise SportsPARegistryError(f"{label} supports do not sum to rowCount")

    realized_prevalence = _validate_class_number_mapping(
        metrics["realizedPrevalence"], label=f"{label}.realizedPrevalence"
    )
    predicted_prevalence = _validate_class_number_mapping(
        metrics["predictedPrevalence"], label=f"{label}.predictedPrevalence"
    )
    argmax_prevalence = _validate_class_number_mapping(
        metrics["argmaxPrevalence"], label=f"{label}.argmaxPrevalence"
    )
    for name, mapping in (
        ("realizedPrevalence", realized_prevalence),
        ("predictedPrevalence", predicted_prevalence),
        ("argmaxPrevalence", argmax_prevalence),
    ):
        if not _close(math.fsum(mapping.values()), 1.0):
            raise SportsPARegistryError(f"{label}.{name} must sum to one")
    for index, class_name in enumerate(PA_CLASS_ORDER):
        if not _close(realized_prevalence[class_name], supports[class_name] / expected_rows):
            raise SportsPARegistryError(f"{label} realized prevalence differs from support")
        if not _close(argmax_prevalence[class_name], column_counts[index] / expected_rows):
            raise SportsPARegistryError(f"{label} argmax prevalence differs from confusion matrix")

    top_reliability = _validate_metric_bins(
        metrics["topLabelReliability"],
        expected_rows=expected_rows,
        label=f"{label}.topLabelReliability",
        kind="top-label",
    )
    assert top_reliability is not None
    if (
        not _close(top_reliability[0], bounded_metrics["topLabelEce"])
        or not _close(top_reliability[2], bounded_metrics["top1Accuracy"])
    ):
        raise SportsPARegistryError(f"{label} top-label reliability does not reconcile")

    classwise_reliability = dict(
        _mapping(metrics["classwiseReliability"], label=f"{label}.classwiseReliability")
    )
    probability_histograms = dict(
        _mapping(metrics["probabilityHistograms"], label=f"{label}.probabilityHistograms")
    )
    _exact_keys(classwise_reliability, set(PA_CLASS_ORDER), label=f"{label}.classwiseReliability")
    _exact_keys(probability_histograms, set(PA_CLASS_ORDER), label=f"{label}.probabilityHistograms")
    for class_name in PA_CLASS_ORDER:
        reliability = _validate_metric_bins(
            classwise_reliability[class_name],
            expected_rows=expected_rows,
            label=f"{label}.classwiseReliability.{class_name}",
            kind="classwise",
        )
        assert reliability is not None
        if (
            not _close(reliability[0], classwise_ece[class_name])
            or not _close(reliability[1], predicted_prevalence[class_name])
            or not _close(reliability[2], realized_prevalence[class_name])
        ):
            raise SportsPARegistryError(f"{label} classwise reliability does not reconcile")
        _validate_metric_bins(
            probability_histograms[class_name],
            expected_rows=expected_rows,
            label=f"{label}.probabilityHistograms.{class_name}",
            kind="histogram",
        )

    diagonal = sum(confusion[index][index] for index in range(len(PA_CLASS_ORDER)))
    active_recalls = [class_recall[name] for name in PA_CLASS_ORDER if supports[name] > 0]
    expected_balanced = math.fsum(active_recalls) / len(active_recalls) if active_recalls else 0.0
    expected_macro_f1 = math.fsum(class_f1.values()) / len(PA_CLASS_ORDER)
    expected_weighted_f1 = math.fsum(
        class_f1[name] * supports[name] for name in PA_CLASS_ORDER
    ) / expected_rows
    if (
        not _close(bounded_metrics["top1Accuracy"], diagonal / expected_rows)
        or not _close(bounded_metrics["balancedAccuracy"], expected_balanced)
        or not _close(bounded_metrics["macroF1"], expected_macro_f1)
        or not _close(bounded_metrics["weightedF1"], expected_weighted_f1)
    ):
        raise SportsPARegistryError(f"{label} aggregate classification metrics do not reconcile")
    return metrics


def _validate_feature_view(value: Any) -> dict[str, Any]:
    feature = dict(_mapping(value, label="featureView"))
    _exact_keys(feature, _FEATURE_KEYS, label="featureView")
    content_sha = _sha(feature["contentSha"], label="featureView.contentSha")
    feature_id = _nonblank(feature["featureViewId"], label="featureView.featureViewId")
    if not feature_id.endswith(content_sha):
        raise SportsPARegistryError("featureViewId must be content-bound to contentSha")
    if feature["contractName"] != FEATURE_VIEW_CONTRACT_NAME or feature["contractVersion"] != FEATURE_VIEW_CONTRACT_VERSION:
        raise SportsPARegistryError("Feature-view contract identity differs")
    if feature["rowCount"] != EXPECTED_FEATURE_VIEW_ROWS:
        raise SportsPARegistryError("Feature-view row count differs")
    names = _list(feature["featureNames"], label="featureView.featureNames")
    if names != list(FEATURE_NAMES):
        raise SportsPARegistryError("Feature names or order differ from MLB_PA_FEATURE_VIEW_V1")
    if feature["featureCount"] != len(names):
        raise SportsPARegistryError("Feature count does not reconcile")
    if feature["population"] != "strict_deployable" or feature["seasons"] != list(EXPECTED_FEATURE_VIEW_SEASONS):
        raise SportsPARegistryError("Feature population or seasons differ")
    _logical_uri(feature["logicalUri"], label="featureView.logicalUri")
    _sha(feature["artifactSha"], label="featureView.artifactSha")
    _integer(feature["artifactBytes"], label="featureView.artifactBytes", minimum=1)
    return feature


def _validate_experiment(value: Any, *, feature_content_sha: str) -> dict[str, Any]:
    experiment = dict(_mapping(value, label="experiment"))
    _exact_keys(experiment, _EXPERIMENT_KEYS, label="experiment")
    expected_semantic = {
        "featureContentSha": feature_content_sha,
        "objective": "Eight-class conditional terminal plate-appearance outcome research",
        "seed": DEFAULT_BOOTSTRAP_SEED,
        "trainingContractVersion": FEATURE_VIEW_CONTRACT_VERSION,
    }
    expected_id = (
        "mlb-pa-experiment:sha256:"
        + sha256_bytes(canonical_json_bytes(expected_semantic))
    )
    expected_payload = {
        "experimentId": expected_id,
        "objective": expected_semantic["objective"],
        "seed": expected_semantic["seed"],
        "trainingContractVersion": expected_semantic["trainingContractVersion"],
    }
    if experiment != expected_payload:
        raise SportsPARegistryError("Experiment identity or frozen policy authority differs")
    return experiment


def _validate_candidate_config(candidate_id: str, value: Any) -> tuple[dict[str, Any], float | None]:
    config = dict(_mapping(value, label=f"candidate {candidate_id} config"))
    if candidate_id == "C0":
        expected = {
            "estimator": "GLOBAL_TRAINING_CLASS_FREQUENCY",
            "classOrder": list(PA_CLASS_ORDER),
            "featureNames": [],
            "trainingScope": "2023",
        }
        if config != expected:
            raise SportsPARegistryError("C0 config differs from the governed frequency baseline")
        return config, None

    expected_keys = {
        "estimator",
        "multiclass",
        "penalty",
        "solver",
        "CGrid",
        "selectedC",
        "maxIter",
        "tolerance",
        "featureNames",
        "preprocessing",
    }
    _exact_keys(config, expected_keys, label=f"candidate {candidate_id} config")
    selected_c = _finite(config["selectedC"], label=f"candidate {candidate_id} config.selectedC")
    if type(config["selectedC"]) is not float or selected_c not in C_GRID:
        raise SportsPARegistryError("Candidate selectedC must come from the frozen C grid")
    if (
        type(config["CGrid"]) is not list
        or any(type(item) is not float for item in config["CGrid"])
        or config["CGrid"] != list(C_GRID)
    ):
        raise SportsPARegistryError("Candidate C grid differs from the frozen authority")
    expected = {
        "estimator": "sklearn.linear_model.LogisticRegression",
        "multiclass": "TRUE_MULTINOMIAL",
        "penalty": "l2",
        "solver": "lbfgs",
        "CGrid": list(C_GRID),
        "selectedC": selected_c,
        "maxIter": DEFAULT_MAX_ITER,
        "tolerance": DEFAULT_TOLERANCE,
        "featureNames": list(CANDIDATE_FEATURES[candidate_id]),
        "preprocessing": "FOLD_LOCAL_MEAN_IMPUTE_STANDARDIZE_FIXED_ONE_HOT",
    }
    if config != expected:
        raise SportsPARegistryError("Candidate config differs from the governed training contract")
    return config, selected_c


def _validate_aggregate_metrics(
    candidate_id: str,
    value: Any,
    *,
    folds: Sequence[Mapping[str, Any]],
    selected_c: float | None,
    convergence: Mapping[str, Any],
    blocked: bool,
) -> tuple[dict[str, Any], tuple[int, int] | None]:
    aggregate = dict(_mapping(value, label=f"candidate {candidate_id} aggregateMetrics"))
    _exact_keys(
        aggregate,
        _AGGREGATE_METRICS_KEYS,
        label=f"candidate {candidate_id} aggregateMetrics",
    )
    selection_fold, final_fold = folds
    if aggregate["selection2024"] != selection_fold["metrics"]:
        raise SportsPARegistryError("Candidate selection2024 aggregate differs from its 2024 fold")
    if aggregate["final2025"] != final_fold["metrics"]:
        raise SportsPARegistryError("Candidate final2025 aggregate differs from its 2025 fold")

    tuning = _list(
        aggregate["inner2023Tuning"],
        label=f"candidate {candidate_id} aggregateMetrics.inner2023Tuning",
    )
    if candidate_id == "C0":
        if tuning:
            raise SportsPARegistryError("C0 may not claim logistic tuning evidence")
        return aggregate, None
    if blocked and selection_fold["status"] == "NOT_RUN_BY_POLICY" and not tuning:
        return aggregate, None
    if len(tuning) != len(C_GRID):
        raise SportsPARegistryError("Logistic candidates require every frozen C-grid tuning result")

    split_authority: tuple[int, int] | None = None
    validated_tuning: list[dict[str, Any]] = []
    maximum_tuning_iterations = 0
    for index, (raw, expected_c) in enumerate(zip(tuning, C_GRID, strict=True)):
        item = dict(_mapping(raw, label=f"candidate {candidate_id} tuning[{index}]"))
        _exact_keys(item, _TUNING_EVIDENCE_KEYS, label=f"candidate {candidate_id} tuning[{index}]")
        if type(item["C"]) is not float or item["C"] != expected_c:
            raise SportsPARegistryError("Candidate tuning evidence differs from frozen C-grid order")
        training_rows = _integer(
            item["trainingRows"],
            label=f"candidate {candidate_id} tuning[{index}].trainingRows",
            minimum=1,
        )
        validation_rows = _integer(
            item["validationRows"],
            label=f"candidate {candidate_id} tuning[{index}].validationRows",
            minimum=1,
        )
        if training_rows + validation_rows != selection_fold["trainingRows"]:
            raise SportsPARegistryError("Candidate tuning rows do not partition the frozen 2023 training fold")
        observed_split = (training_rows, validation_rows)
        if split_authority is None:
            split_authority = observed_split
        elif split_authority != observed_split:
            raise SportsPARegistryError("Candidate tuning split changes across the frozen C grid")
        item["metrics"] = _validate_metrics(
            item["metrics"],
            expected_rows=validation_rows,
            label=f"{candidate_id}.inner2023Tuning[{index}].metrics",
        )
        n_iter = _integer(
            item["nIter"],
            label=f"candidate {candidate_id} tuning[{index}].nIter",
            minimum=1,
        )
        if n_iter > DEFAULT_MAX_ITER:
            raise SportsPARegistryError("Candidate tuning iterations exceed governed maxIter")
        maximum_tuning_iterations = max(maximum_tuning_iterations, n_iter)
        validated_tuning.append(item)
    winner = min(
        validated_tuning,
        key=lambda item: (
            item["metrics"]["logLoss"],
            item["metrics"]["brierScore"],
            item["C"],
        ),
    )
    if selected_c != winner["C"]:
        raise SportsPARegistryError("Candidate selectedC differs from frozen inner-2023 tuning evidence")
    if convergence["nIter"] < maximum_tuning_iterations:
        raise SportsPARegistryError("Candidate convergence nIter omits a tuning fit")
    aggregate["inner2023Tuning"] = validated_tuning
    return aggregate, split_authority


def _validate_candidate_rows(
    value: Any,
    *,
    blocked: bool,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = _list(value, label="candidates")
    if len(rows) != len(EXPECTED_CANDIDATES):
        raise SportsPARegistryError("Exactly five governed candidates C0-C4 are required")
    materialized: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    config_shas: set[str] = set()
    tuning_split_authority: tuple[int, int] | None = None
    for expected_ordinal, raw in enumerate(rows):
        candidate = dict(_mapping(raw, label="candidate"))
        _exact_keys(candidate, _CANDIDATE_KEYS, label="candidate")
        candidate_id = _nonblank(candidate["candidateId"], label="candidate.candidateId")
        if candidate_id != EXPECTED_CANDIDATES[expected_ordinal] or candidate["ordinal"] != expected_ordinal:
            raise SportsPARegistryError("Candidate identities and ordinals must remain C0-C4")
        if (
            candidate["candidateType"] != EXPECTED_CANDIDATE_TYPES[candidate_id]
            or candidate["displayName"] != EXPECTED_CANDIDATE_LABELS[candidate_id]
        ):
            raise SportsPARegistryError("Candidate type or display label differs from the frozen authority")
        config, selected_c = _validate_candidate_config(candidate_id, candidate["config"])
        config_sha = _sha(candidate["configSha"], label=f"candidate {candidate_id} configSha")
        if sha256_bytes(canonical_json_bytes(config)) != config_sha or config_sha in config_shas:
            raise SportsPARegistryError("Candidate config digest differs or is duplicated")
        config_shas.add(config_sha)
        if type(candidate["eligible"]) is not bool:
            raise SportsPARegistryError("Candidate eligible flag must be boolean")
        runtime_seconds = _finite(
            candidate["runtimeSeconds"],
            label=f"candidate {candidate_id} runtimeSeconds",
        )
        if runtime_seconds < 0.0:
            raise SportsPARegistryError("Candidate runtimeSeconds must be non-negative")
        convergence = dict(
            _mapping(candidate["convergence"], label=f"candidate {candidate_id} convergence")
        )
        _exact_keys(convergence, _CONVERGENCE_KEYS, label="candidate convergence")
        if candidate_id in {"C1", "C2", "C3", "C4"}:
            if convergence["status"] == "CONVERGED" and convergence["converged"] is True:
                if convergence["solver"] != "lbfgs":
                    raise SportsPARegistryError("Logistic candidates must use the governed lbfgs solver")
                n_iter = _integer(convergence["nIter"], label="candidate convergence nIter", minimum=1)
                max_iter = _integer(convergence["maxIter"], label="candidate convergence maxIter", minimum=1)
                if max_iter != DEFAULT_MAX_ITER or config["maxIter"] != max_iter:
                    raise SportsPARegistryError("Candidate convergence maxIter differs from config authority")
                if n_iter > max_iter:
                    raise SportsPARegistryError("Candidate convergence iterations exceed maxIter")
            elif blocked and convergence["status"] in {"FAILED", "BLOCKED"} and convergence["converged"] is False:
                if convergence["solver"] != "lbfgs":
                    raise SportsPARegistryError("Blocked logistic evidence must identify the governed lbfgs solver")
                if convergence["nIter"] is not None:
                    _integer(convergence["nIter"], label="candidate convergence nIter")
                if convergence["maxIter"] is not None:
                    _integer(convergence["maxIter"], label="candidate convergence maxIter", minimum=1)
            else:
                raise SportsPARegistryError("Logistic candidates must prove convergence")
        elif convergence != {
            "status": "NOT_APPLICABLE",
            "converged": None,
            "nIter": None,
            "maxIter": None,
            "solver": None,
        }:
            raise SportsPARegistryError("C0 frequency baseline must mark convergence NOT_APPLICABLE")
        candidate["convergence"] = convergence
        reasons = _list(candidate["rejectionReasons"], label="candidate.rejectionReasons")
        if any(type(item) is not str or not item for item in reasons):
            raise SportsPARegistryError("Candidate rejection reasons must be non-empty strings")
        if not blocked and (candidate["eligible"] is not True or reasons):
            raise SportsPARegistryError("Complete runs require every governed candidate to remain eligible")

        folds = _list(candidate["foldMetrics"], label=f"candidate {candidate_id} foldMetrics")
        if len(folds) != len(EXPECTED_FOLDS):
            raise SportsPARegistryError("Each candidate must preserve both frozen folds")
        validated_folds: list[dict[str, Any]] = []
        for raw_fold, (fold_id, expected) in zip(folds, EXPECTED_FOLDS.items(), strict=True):
            fold = dict(_mapping(raw_fold, label="candidate fold"))
            _exact_keys(fold, _FOLD_KEYS, label="candidate fold")
            if (
                fold["foldId"] != fold_id
                or fold["trainingSeasons"] != expected["training_seasons"]
                or fold["validationSeason"] != expected["validation_season"]
                or fold["trainingRows"] != expected["training_rows"]
                or fold["validationRows"] != expected["validation_rows"]
            ):
                raise SportsPARegistryError(f"Frozen fold authority differs: {fold_id}")
            status = fold["status"]
            if status == "COMPLETE":
                fold["metrics"] = _validate_metrics(
                    fold["metrics"],
                    expected_rows=expected["validation_rows"],
                    label=f"{candidate_id}.{fold_id}.metrics",
                )
            elif status == "NOT_RUN_BY_POLICY" and fold["metrics"] is None:
                pass
            else:
                raise SportsPARegistryError("Fold metrics may be null only with NOT_RUN_BY_POLICY")
            validated_folds.append(fold)
        candidate["foldMetrics"] = validated_folds
        aggregate, observed_tuning_split = _validate_aggregate_metrics(
            candidate_id,
            candidate["aggregateMetrics"],
            folds=validated_folds,
            selected_c=selected_c,
            convergence=convergence,
            blocked=blocked,
        )
        if observed_tuning_split is not None:
            if tuning_split_authority is None:
                tuning_split_authority = observed_tuning_split
            elif tuning_split_authority != observed_tuning_split:
                raise SportsPARegistryError("Inner-2023 tuning split differs across candidates")
        candidate["aggregateMetrics"] = aggregate
        candidate["config"] = config
        materialized.append(candidate)
        by_id[candidate_id] = candidate
    return materialized, by_id


def _validate_selected(
    value: Any,
    *,
    candidates: Mapping[str, Mapping[str, Any]],
    blocked: bool,
) -> dict[str, Any] | None:
    if blocked:
        if value is not None:
            raise SportsPARegistryError("A BLOCKED run may not claim a selected candidate")
        return None
    selected = dict(_mapping(value, label="selected"))
    _exact_keys(selected, _SELECTED_KEYS, label="selected")
    candidate_id = _nonblank(selected["candidateId"], label="selected.candidateId")
    if candidate_id not in {"C1", "C2", "C3", "C4"} or candidates[candidate_id]["eligible"] is not True:
        raise SportsPARegistryError("Selected candidate must be an eligible governed candidate")
    if selected["selectionMetric"] != "2024_LOG_LOSS_THEN_BRIER_THEN_ORDINAL":
        raise SportsPARegistryError("Selected candidate metric differs from frozen 2024-only policy")
    _nonblank(selected["rationale"], label="selected.rationale")
    eligible = [
        candidate
        for governed_id, candidate in candidates.items()
        if governed_id != "C0"
        and candidate["eligible"] is True
        and candidate["convergence"]["status"] == "CONVERGED"
        and candidate["convergence"]["converged"] is True
    ]
    if not eligible:
        raise SportsPARegistryError("No eligible converged substantive candidate is available")
    expected = min(
        eligible,
        key=lambda candidate: (
            candidate["foldMetrics"][0]["metrics"]["logLoss"],
            candidate["foldMetrics"][0]["metrics"]["brierScore"],
            candidate["ordinal"],
        ),
    )
    if candidate_id != expected["candidateId"]:
        raise SportsPARegistryError("Selected candidate differs from the frozen 2024 argmin policy")
    return selected


def _validate_fold_execution_policy(
    candidates: Mapping[str, Mapping[str, Any]],
    selected_id: str | None,
    *,
    blocked: bool,
) -> None:
    for candidate_id, candidate in candidates.items():
        by_fold = {item["foldId"]: item for item in candidate["foldMetrics"]}
        first = by_fold["train-2023-validate-2024"]
        second = by_fold["train-through-2024-validate-2025"]
        if not blocked and first["status"] != "COMPLETE":
            raise SportsPARegistryError("Every governed candidate must complete the 2024 selection fold")
        if not blocked:
            should_run_2025 = candidate_id in {"C0", "C1", selected_id}
            expected_status = "COMPLETE" if should_run_2025 else "NOT_RUN_BY_POLICY"
            if second["status"] != expected_status:
                raise SportsPARegistryError(
                    "2025 fold execution differs from the frozen C0/C1/selected-only policy"
                )


def _validate_calibration(
    value: Any,
    *,
    selected_id: str | None,
    blocked: bool,
) -> dict[str, Any] | None:
    if blocked:
        if value is not None:
            raise SportsPARegistryError("A BLOCKED run may not claim calibration completion")
        return None
    calibration = dict(_mapping(value, label="calibration"))
    _exact_keys(calibration, _CALIBRATION_KEYS, label="calibration")
    if (
        calibration["schemaVersion"] != CALIBRATION_SCHEMA_VERSION
        or calibration["sourceSeason"] != 2024
        or calibration["candidateId"] != selected_id
        or calibration["method"] != "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES"
    ):
        raise SportsPARegistryError("Calibration authority differs")
    _nonblank(calibration["rationale"], label="calibration.rationale")
    fitted = _finite(calibration["fittedTemperature"], label="calibration.fittedTemperature")
    retained_temperature = _finite(
        calibration["retainedTemperature"],
        label="calibration.retainedTemperature",
    )
    if (
        not DEFAULT_TEMPERATURE_BOUNDS[0] <= fitted <= DEFAULT_TEMPERATURE_BOUNDS[1]
        or retained_temperature <= 0.0
        or type(calibration["retained"]) is not bool
    ):
        raise SportsPARegistryError("Calibration temperatures and retained flag are invalid")
    retained = calibration["retained"]
    if calibration["decision"] != ("RETAINED" if retained else "REJECTED"):
        raise SportsPARegistryError("Calibration decision does not reconcile to retained policy")
    if retained and retained_temperature != fitted:
        raise SportsPARegistryError("Retained calibration must retain the fitted 2024 temperature")
    if not retained and retained_temperature != 1.0:
        raise SportsPARegistryError("Rejected calibration must retain raw temperature 1.0")

    raw_2024 = _validate_metrics(calibration["raw2024"], expected_rows=182_449, label="calibration.raw2024")
    scaled_2024 = _validate_metrics(calibration["scaled2024"], expected_rows=182_449, label="calibration.scaled2024")
    raw_2025 = _validate_metrics(calibration["raw2025"], expected_rows=182_926, label="calibration.raw2025")
    scaled_2025 = _validate_metrics(calibration["scaled2025"], expected_rows=182_926, label="calibration.scaled2025")
    final_2025 = _validate_metrics(calibration["final2025"], expected_rows=182_926, label="calibration.final2025")
    if retained:
        if (
            scaled_2024["logLoss"] > raw_2024["logLoss"] + CALIBRATION_RETENTION_TOLERANCE
            or scaled_2024["brierScore"] > raw_2024["brierScore"] + CALIBRATION_RETENTION_TOLERANCE
        ):
            raise SportsPARegistryError("Retained calibration worsens a governing 2024 metric")
        if final_2025 != scaled_2025:
            raise SportsPARegistryError("Retained calibration final2025 must equal frozen-temperature scaled2025")
    elif final_2025 != raw_2025:
        raise SportsPARegistryError("Rejected calibration final2025 must equal raw2025")
    calibration.update(
        {
            "raw2024": raw_2024,
            "scaled2024": scaled_2024,
            "raw2025": raw_2025,
            "scaled2025": scaled_2025,
            "final2025": final_2025,
        }
    )
    return calibration


def _validate_bootstrap_comparisons(
    value: Any,
    *,
    selected_id: str | None,
    candidates: Mapping[str, Mapping[str, Any]],
    blocked: bool,
) -> list[dict[str, Any]]:
    rows = _list(value, label="bootstrapComparisons")
    if blocked:
        if rows:
            raise SportsPARegistryError("A BLOCKED run may not claim bootstrap completion")
        return []
    if len(rows) != 4:
        raise SportsPARegistryError("Exactly four fold-specific C0/C1 bootstrap comparisons are required")
    expected_keys = {
        (
            fold_id,
            int(fold["validation_season"]),
            comparator,
        )
        for fold_id, fold in EXPECTED_FOLDS.items()
        for comparator in ("C0", "C1")
    }
    observed: set[tuple[str, int, str]] = set()
    output: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(_mapping(raw, label="bootstrap comparison"))
        _exact_keys(item, _BOOTSTRAP_KEYS, label="bootstrap comparison")
        key = (item["foldId"], item["validationSeason"], item["baselineCandidateId"])
        if key not in expected_keys or key in observed or item["candidateId"] != selected_id:
            raise SportsPARegistryError("Bootstrap comparison fold/candidate authority differs")
        observed.add(key)
        if (
            item["schemaVersion"] != BOOTSTRAP_SCHEMA_VERSION
            or item["clusterUnit"] != "game_id"
            or item["seed"] != DEFAULT_BOOTSTRAP_SEED
            or item["resamples"] != DEFAULT_BOOTSTRAP_RESAMPLES
            or item["confidenceLevel"] != DEFAULT_CONFIDENCE_LEVEL
        ):
            raise SportsPARegistryError("Bootstrap policy authority differs")
        evidence = dict(_mapping(item["evidence"], label="bootstrap evidence"))
        _exact_keys(evidence, _BOOTSTRAP_EVIDENCE_KEYS, label="bootstrap evidence")
        expected_rows = int(EXPECTED_FOLDS[item["foldId"]]["validation_rows"])
        if (
            evidence.get("schemaVersion") != BOOTSTRAP_SCHEMA_VERSION
            or evidence.get("classOrder") != list(PA_CLASS_ORDER)
            or evidence.get("differenceConvention")
            != "SELECTED_MINUS_COMPARATOR_NEGATIVE_FAVORS_SELECTED"
            or evidence.get("rowCount") != expected_rows
            or evidence.get("resamplingUnit") != "game_id"
            or evidence.get("resamplingMethod")
            != "EQUAL_PROBABILITY_CLUSTERS_WITH_REPLACEMENT"
            or evidence.get("rowsSampledIndependently") is not False
            or evidence.get("resampleCount") != item["resamples"]
            or evidence.get("seed") != item["seed"]
            or evidence.get("confidenceLevel") != item["confidenceLevel"]
        ):
            raise SportsPARegistryError("Bootstrap evidence does not reconcile with its fold policy")
        cluster_count = _integer(
            evidence["clusterCount"],
            label="bootstrap evidence clusterCount",
            minimum=2,
        )
        if (
            cluster_count != EXPECTED_VALIDATION_GAME_COUNTS[item["validationSeason"]]
            or evidence["clusterDrawsPerReplicate"] != cluster_count
        ):
            raise SportsPARegistryError("Bootstrap cluster count differs from frozen validation-game authority")
        selected_fold = next(
            fold
            for fold in candidates[str(selected_id)]["foldMetrics"]
            if fold["foldId"] == item["foldId"]
        )
        comparator_fold = next(
            fold
            for fold in candidates[item["baselineCandidateId"]]["foldMetrics"]
            if fold["foldId"] == item["foldId"]
        )
        if selected_fold["metrics"] is None or comparator_fold["metrics"] is None:
            raise SportsPARegistryError("Bootstrap comparisons require complete raw fold evidence")
        expected_points = {
            "logLossDifference": (
                selected_fold["metrics"]["logLoss"] - comparator_fold["metrics"]["logLoss"]
            ),
            "brierScoreDifference": (
                selected_fold["metrics"]["brierScore"] - comparator_fold["metrics"]["brierScore"]
            ),
        }
        for metric in ("logLossDifference", "brierScoreDifference"):
            summary = dict(_mapping(evidence.get(metric), label=f"bootstrap evidence {metric}"))
            _exact_keys(summary, _BOOTSTRAP_SUMMARY_KEYS, label=f"bootstrap evidence {metric}")
            point_estimate = _finite(summary["pointEstimate"], label=f"{metric}.pointEstimate")
            if not _close(point_estimate, expected_points[metric], tolerance=1e-12):
                raise SportsPARegistryError("Bootstrap point estimate differs from raw fold metrics")
            bootstrap_mean = _finite(summary["bootstrapMean"], label=f"{metric}.bootstrapMean")
            standard_error = _finite(
                summary["bootstrapStandardError"],
                label=f"{metric}.bootstrapStandardError",
            )
            if standard_error < 0.0:
                raise SportsPARegistryError("Bootstrap standard error must be non-negative")
            probability = _finite(
                summary["probabilitySelectedBetter"],
                label=f"{metric}.probabilitySelectedBetter",
            )
            if not 0.0 <= probability <= 1.0:
                raise SportsPARegistryError("Bootstrap probability must be within [0, 1]")
            interval = dict(
                _mapping(summary["percentileInterval"], label=f"{metric}.percentileInterval")
            )
            _exact_keys(interval, _BOOTSTRAP_INTERVAL_KEYS, label=f"{metric}.percentileInterval")
            if interval["confidenceLevel"] != item["confidenceLevel"]:
                raise SportsPARegistryError("Bootstrap interval confidence level differs")
            lower = _finite(interval["lower"], label=f"{metric}.percentileInterval.lower")
            upper = _finite(interval["upper"], label=f"{metric}.percentileInterval.upper")
            if lower > upper:
                raise SportsPARegistryError("Bootstrap percentile interval is inverted")
            replicates = _list(
                summary["replicateDifferences"],
                label=f"{metric}.replicateDifferences",
            )
            if len(replicates) != item["resamples"]:
                raise SportsPARegistryError("Bootstrap replicate count differs")
            parsed_replicates = [
                _finite(value, label=f"{metric}.replicateDifferences[{index}]")
                for index, value in enumerate(replicates)
            ]
            observed_mean = math.fsum(parsed_replicates) / len(parsed_replicates)
            observed_standard_error = math.sqrt(
                math.fsum((value - observed_mean) ** 2 for value in parsed_replicates)
                / (len(parsed_replicates) - 1)
            )
            ordered = sorted(parsed_replicates)

            def linear_percentile(probability_value: float) -> float:
                position = (len(ordered) - 1) * probability_value
                lower_index = math.floor(position)
                upper_index = math.ceil(position)
                fraction = position - lower_index
                return ordered[lower_index] + fraction * (
                    ordered[upper_index] - ordered[lower_index]
                )

            alpha = 1.0 - item["confidenceLevel"]
            observed_lower = linear_percentile(alpha / 2.0)
            observed_upper = linear_percentile(1.0 - alpha / 2.0)
            observed_probability = sum(value < 0.0 for value in parsed_replicates) / len(parsed_replicates)
            if not math.isclose(bootstrap_mean, observed_mean, rel_tol=1e-12, abs_tol=1e-12):
                raise SportsPARegistryError("Bootstrap mean does not reconcile to its replicates")
            if not math.isclose(
                standard_error,
                observed_standard_error,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise SportsPARegistryError("Bootstrap standard error does not reconcile to its replicates")
            if not math.isclose(lower, observed_lower, rel_tol=1e-12, abs_tol=1e-12) or not math.isclose(
                upper,
                observed_upper,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise SportsPARegistryError("Bootstrap percentile interval does not reconcile to its replicates")
            if not math.isclose(probability, observed_probability, rel_tol=0.0, abs_tol=1e-12):
                raise SportsPARegistryError("Bootstrap probability does not reconcile to its replicates")
        item["evidence"] = evidence
        output.append(item)
    if observed != expected_keys:
        raise SportsPARegistryError("Bootstrap comparisons do not cover both frozen folds and comparators")
    return output


def _validate_artifacts(
    value: Any,
    *,
    feature_view: Mapping[str, Any],
    selected_id: str | None,
    blocked: bool,
) -> list[dict[str, Any]]:
    rows = _list(value, label="artifacts")
    if not rows:
        raise SportsPARegistryError("At least one governed logical artifact reference is required")
    output: list[dict[str, Any]] = []
    ids: set[str] = set()
    uris: set[str] = set()
    hashes: set[str] = set()
    feature_match = False
    feature_match_count = 0
    feature_run_binding_count = 0
    type_counts: dict[str, int] = defaultdict(int)
    for raw in rows:
        item = dict(_mapping(raw, label="artifact"))
        _exact_keys(item, _ARTIFACT_KEYS, label="artifact")
        digest = _sha(item["sha256"], label="artifact.sha256")
        artifact_id = _nonblank(item["artifactId"], label="artifact.artifactId")
        uri = _logical_uri(item["logicalUri"], label="artifact.logicalUri")
        artifact_type = _nonblank(item["artifactType"], label="artifact.artifactType")
        if artifact_type not in _COMPLETED_ARTIFACT_CARDINALITIES:
            raise SportsPARegistryError("Artifact type differs from the governed runner inventory")
        expected_artifact_id = f"sports-pa-artifact:{artifact_type.lower()}:sha256:{digest}"
        if artifact_id != expected_artifact_id:
            raise SportsPARegistryError("Artifact ID differs from its governed type/SHA identity")
        if artifact_id in ids or uri in uris or digest in hashes:
            raise SportsPARegistryError("Artifact identities, logical URIs, and hashes must be unique")
        ids.add(artifact_id)
        uris.add(uri)
        hashes.add(digest)
        expected_media_type = (
            "application/vnd.apache.parquet"
            if artifact_type in {"FEATURE_VIEW", "FOLD_2024_PREDICTIONS", "FOLD_2025_PREDICTIONS"}
            else "application/json"
        )
        if item["mediaType"] != expected_media_type:
            raise SportsPARegistryError("Artifact media type differs from the governed runner contract")
        expected_uri_prefix = (
            f"asp-model-studio-runtime://sports-modeling/mlb-pa-v1/objects/sha256/"
            f"{digest[:2]}/{digest}/"
        )
        if not uri.startswith(expected_uri_prefix) or "/" in uri[len(expected_uri_prefix):]:
            raise SportsPARegistryError("Artifact URI differs from the governed runtime object namespace")
        _integer(item["byteCount"], label="artifact.byteCount", minimum=1)
        if (
            artifact_type == "FEATURE_VIEW"
            and uri == feature_view["logicalUri"]
            and digest == feature_view["artifactSha"]
            and item["byteCount"] == feature_view["artifactBytes"]
        ):
            feature_match = True
            feature_match_count += 1
        if artifact_type == "FEATURE_VIEW_RUN_BINDING":
            feature_run_binding_count += 1
        type_counts[artifact_type] += 1
        output.append(item)
    if not feature_match or feature_match_count != 1:
        raise SportsPARegistryError("Feature-view artifact declaration does not reconcile")
    if feature_run_binding_count != 1:
        raise SportsPARegistryError("Exactly one final-run feature-view binding artifact is required")
    if not blocked:
        expected_cardinalities = dict(_COMPLETED_ARTIFACT_CARDINALITIES)
        if selected_id == "C1":
            expected_cardinalities["MODEL_STATE"] = 7
            expected_cardinalities["PREPROCESSOR_STATE"] = 5
        if dict(type_counts) != expected_cardinalities:
            expected_total = sum(expected_cardinalities.values())
            raise SportsPARegistryError(
                f"Completed artifact inventory differs from the governed {expected_total}-reference contract"
            )
    return output


def _complete_graph_authority(
    candidates: Mapping[str, Mapping[str, Any]],
    *,
    selected_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        {"nodeId": "dataset-manifest", "nodeType": "DATASET_MANIFEST", "label": "MLB FD1 Dataset Manifest", "status": "COMPLETE", "candidateId": None},
        {"nodeId": "identity-bridge", "nodeType": "IDENTITY_BRIDGE", "label": "SPORTS_IDENTITY_BRIDGE_V1", "status": "COMPLETE", "candidateId": None},
        {"nodeId": "y-minus-1-prior-join", "nodeType": "PRIOR_JOIN", "label": "Exact Y-minus-1 Prior Join", "status": "COMPLETE", "candidateId": None},
        {"nodeId": "feature-view", "nodeType": "FEATURE_VIEW", "label": "MLB_PA_FEATURE_VIEW_V1", "status": "COMPLETE", "candidateId": None},
        {"nodeId": "selected-pa-baseline", "nodeType": "SELECTED_MODEL", "label": "Selected Multinomial PA Baseline", "status": "COMPLETE", "candidateId": selected_id},
        {"nodeId": "temperature-calibration", "nodeType": "CALIBRATION", "label": "Optional Temperature Calibration", "status": "COMPLETE", "candidateId": selected_id},
        {"nodeId": "retrospective-evaluation", "nodeType": "EVALUATION", "label": "Retrospective Evaluation Evidence", "status": "COMPLETE", "candidateId": selected_id},
    ]
    nodes.extend(
        {
            "nodeId": f"candidate-{candidate_id.casefold()}",
            "nodeType": "MODEL_CANDIDATE",
            "label": candidates[candidate_id]["displayName"],
            "status": "EVALUATED",
            "candidateId": candidate_id,
        }
        for candidate_id in EXPECTED_CANDIDATES
    )
    nodes.extend(
        {
            "nodeId": node_id,
            "nodeType": "FUTURE_COMPONENT",
            "label": label,
            "status": "NOT_CONFIGURED",
            "candidateId": None,
        }
        for node_id, label in (
            ("future-dynamic-player-state", "Dynamic Player State"),
            ("future-lineup-model", "Lineup Model"),
            ("future-starter-duration", "Starter-Duration"),
            ("future-bullpen-usage", "Bullpen-Usage"),
            ("future-base-out-transition", "Base-Out Transition"),
            ("future-game-simulator", "Game Simulator"),
            ("future-residual-model", "Residual Model"),
            ("future-standalone-asp-bundle", "Standalone ASP Bundle"),
        )
    )
    edges = [
        {"edgeId": "chain-01-dataset-to-bridge", "sourceNodeId": "dataset-manifest", "targetNodeId": "identity-bridge", "relation": "BINDS_IDENTITY"},
        {"edgeId": "chain-02-bridge-to-prior-join", "sourceNodeId": "identity-bridge", "targetNodeId": "y-minus-1-prior-join", "relation": "ENABLES_EXACT_JOIN"},
        {"edgeId": "chain-03-prior-join-to-feature-view", "sourceNodeId": "y-minus-1-prior-join", "targetNodeId": "feature-view", "relation": "MATERIALIZES"},
        {"edgeId": "chain-04-feature-to-selected", "sourceNodeId": "feature-view", "targetNodeId": "selected-pa-baseline", "relation": "TRAINS_FROZEN_SELECTION"},
        {"edgeId": "chain-05-selected-to-calibration", "sourceNodeId": "selected-pa-baseline", "targetNodeId": "temperature-calibration", "relation": "OPTIONALLY_CALIBRATES"},
        {"edgeId": "chain-06-calibration-to-evaluation", "sourceNodeId": "temperature-calibration", "targetNodeId": "retrospective-evaluation", "relation": "PRODUCES_RETROSPECTIVE_EVIDENCE"},
    ]
    for candidate_id in EXPECTED_CANDIDATES:
        normalized = candidate_id.casefold()
        edges.extend(
            [
                {"edgeId": f"branch-feature-to-{normalized}", "sourceNodeId": "feature-view", "targetNodeId": f"candidate-{normalized}", "relation": "EVALUATES_CANDIDATE"},
                {"edgeId": f"branch-{normalized}-to-evaluation", "sourceNodeId": f"candidate-{normalized}", "targetNodeId": "retrospective-evaluation", "relation": "CONTRIBUTES_COMPARATOR_EVIDENCE"},
            ]
        )
    edges.extend(
        [
            {"edgeId": "future-evaluation-to-dynamic-state", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-dynamic-player-state", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-evaluation-to-lineup", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-lineup-model", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-evaluation-to-starter", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-starter-duration", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-evaluation-to-bullpen", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-bullpen-usage", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-evaluation-to-base-out", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-base-out-transition", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-dynamic-to-simulator", "sourceNodeId": "future-dynamic-player-state", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-lineup-to-simulator", "sourceNodeId": "future-lineup-model", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-starter-to-simulator", "sourceNodeId": "future-starter-duration", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-bullpen-to-simulator", "sourceNodeId": "future-bullpen-usage", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-base-out-to-simulator", "sourceNodeId": "future-base-out-transition", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-simulator-to-residual", "sourceNodeId": "future-game-simulator", "targetNodeId": "future-residual-model", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-residual-to-bundle", "sourceNodeId": "future-residual-model", "targetNodeId": "future-standalone-asp-bundle", "relation": "FUTURE_DEPENDENCY"},
        ]
    )
    return nodes, edges


def _validate_graph(
    value: Any,
    *,
    candidates: Mapping[str, Mapping[str, Any]],
    selected_id: str | None,
    feature_content_sha: str,
    blocked: bool,
) -> dict[str, Any]:
    graph = dict(_mapping(value, label="graph"))
    _exact_keys(graph, _GRAPH_KEYS, label="graph")
    _nonblank(graph["graphId"], label="graph.graphId")
    raw_nodes = _list(graph["nodes"], label="graph.nodes")
    raw_edges = _list(graph["edges"], label="graph.edges")
    if not raw_nodes:
        raise SportsPARegistryError("Research graph must contain governed nodes")
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    candidate_nodes: set[str] = set()
    for raw in raw_nodes:
        node = dict(_mapping(raw, label="graph node"))
        _exact_keys(node, _NODE_KEYS, label="graph node")
        node_id = _nonblank(node["nodeId"], label="graph node ID")
        if node_id in node_ids:
            raise SportsPARegistryError("Graph node IDs must be unique")
        node_ids.add(node_id)
        for field in ("nodeType", "label", "status"):
            _nonblank(node[field], label=f"graph node {field}")
        candidate_id = node["candidateId"]
        if candidate_id is not None:
            if candidate_id not in candidates:
                raise SportsPARegistryError("Graph candidate node references an unknown candidate")
            candidate_nodes.add(candidate_id)
        nodes.append(node)
    if not blocked and candidate_nodes != set(candidates):
        raise SportsPARegistryError("Complete research graph must represent every governed candidate")

    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    adjacency: dict[str, set[str]] = defaultdict(set)
    for raw in raw_edges:
        edge = dict(_mapping(raw, label="graph edge"))
        _exact_keys(edge, _EDGE_KEYS, label="graph edge")
        edge_id = _nonblank(edge["edgeId"], label="graph edge ID")
        source = edge["sourceNodeId"]
        target = edge["targetNodeId"]
        if edge_id in edge_ids or source not in node_ids or target not in node_ids or source == target:
            raise SportsPARegistryError("Graph edge identity or endpoints are invalid")
        edge_ids.add(edge_id)
        _nonblank(edge["relation"], label="graph edge relation")
        adjacency[source].add(target)
        edges.append(edge)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise SportsPARegistryError("Research graph must remain acyclic")
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in adjacency.get(node_id, set()):
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in node_ids:
        visit(node_id)
    if not blocked:
        if selected_id is None:
            raise SportsPARegistryError("Complete research graph requires a selected candidate")
        expected_nodes, expected_edges = _complete_graph_authority(
            candidates,
            selected_id=selected_id,
        )
        if nodes != expected_nodes or edges != expected_edges:
            raise SportsPARegistryError("Research graph differs from the frozen completed/future authority")
        expected_graph_sha = sha256_bytes(
            canonical_json_bytes(
                {
                    "featureContentSha": feature_content_sha,
                    "nodes": expected_nodes,
                    "edges": expected_edges,
                }
            )
        )
        if graph["graphId"] != f"mlb-pa-model-graph:sha256:{expected_graph_sha}":
            raise SportsPARegistryError("Research graph ID is not content-bound")
    graph["nodes"] = nodes
    graph["edges"] = edges
    return graph


def _validate_decision(value: Any) -> dict[str, Any]:
    decision = dict(_mapping(value, label="decision"))
    _exact_keys(decision, _DECISION_KEYS, label="decision")
    if decision["terminalStatus"] not in TERMINAL_STATUSES:
        raise SportsPARegistryError("Research decision terminal status is not governed")
    _nonblank(decision["rationale"], label="decision.rationale")
    _nonblank(decision["recommendedNextStep"], label="decision.recommendedNextStep")
    limitations = _list(decision["limitations"], label="decision.limitations")
    if not limitations or any(type(item) is not str or not item.strip() for item in limitations):
        raise SportsPARegistryError("Research decision limitations must be non-empty strings")
    limitation_text = " ".join(limitations).casefold()
    required_concepts = (
        "conditional" in limitation_text
        and "plate appearance" in limitation_text
        and "standalone" in limitation_text
        and ("pregame" in limitation_text or "game forecast" in limitation_text),
        "handedness" in limitation_text or "platoon" in limitation_text,
        "simulation" in limitation_text and "export" in limitation_text,
        "prospective" in limitation_text,
    )
    if not all(required_concepts):
        raise SportsPARegistryError("Research decision limitations omit a mandatory model-card boundary")
    if decision["researchOnly"] is not True or decision["deploymentAuthorized"] is not False:
        raise SportsPARegistryError("Sports PA registry is research-only and cannot authorize deployment")
    terminal_status = decision["terminalStatus"]
    if terminal_status in COMPLETE_TERMINAL_STATUSES:
        if (
            decision["rationale"] != _COMPLETE_DECISION_RATIONALES[terminal_status]
            or limitations != _GOVERNED_DECISION_LIMITATIONS
            or decision["recommendedNextStep"] != _GOVERNED_DECISION_NEXT_STEP
        ):
            raise SportsPARegistryError(
                f"{terminal_status} public decision prose differs from the governed runner policy"
            )
    else:
        blocked_prose = " ".join(
            [decision["rationale"], *limitations, decision["recommendedNextStep"]]
        )
        if _BLOCKED_SUITABILITY_RE.search(blocked_prose):
            raise SportsPARegistryError(
                "BLOCKED diagnostics may not claim deployment, production, or betting suitability"
            )
    return decision


def _validate_terminal_evidence(
    *,
    terminal_status: str,
    candidates: Mapping[str, Mapping[str, Any]],
    selected: Mapping[str, Any] | None,
    calibration: Mapping[str, Any] | None,
) -> None:
    if terminal_status == "BLOCKED":
        return
    if selected is None or calibration is None:
        raise SportsPARegistryError("Complete terminal decisions require selected and calibration evidence")
    selected_candidate = candidates[selected["candidateId"]]
    selected_folds = {item["validationSeason"]: item for item in selected_candidate["foldMetrics"]}
    c0_folds = {item["validationSeason"]: item for item in candidates["C0"]["foldMetrics"]}
    if selected_folds[2024]["metrics"] != calibration["raw2024"]:
        raise SportsPARegistryError("Calibration raw2024 does not reconcile to selected fold evidence")
    if selected_folds[2025]["metrics"] != calibration["raw2025"]:
        raise SportsPARegistryError("Calibration raw2025 does not reconcile to selected fold evidence")
    if c0_folds[2024]["metrics"] is None or c0_folds[2025]["metrics"] is None:
        raise SportsPARegistryError("Global C0 requires both comparator folds")

    final_2024 = calibration["scaled2024"] if calibration["retained"] else calibration["raw2024"]
    final_2025 = calibration["final2025"]
    comparator_2024 = c0_folds[2024]["metrics"]
    comparator_2025 = c0_folds[2025]["metrics"]

    def beats_global(selected_metrics: Mapping[str, Any], comparator: Mapping[str, Any]) -> bool:
        return (
            selected_metrics["logLoss"]
            < comparator["logLoss"] - TERMINAL_METRIC_TOLERANCE
            and selected_metrics["brierScore"]
            <= comparator["brierScore"] + TERMINAL_METRIC_TOLERANCE
            and selected_metrics["topLabelEce"]
            <= comparator["topLabelEce"] + TERMINAL_METRIC_TOLERANCE
            and all(
                math.isfinite(float(selected_metrics["classwiseEce"][class_name]))
                for class_name in PA_CLASS_ORDER
            )
        )

    selected_integrity = (
        selected_candidate["eligible"] is True
        and selected_candidate["convergence"]["status"] == "CONVERGED"
        and selected_candidate["convergence"]["converged"] is True
    )
    challenger = (
        selected_integrity
        and beats_global(final_2024, comparator_2024)
        and beats_global(final_2025, comparator_2025)
    )
    if terminal_status == "RESEARCH_CHALLENGER" and not challenger:
        raise SportsPARegistryError("RESEARCH_CHALLENGER is not supported by both frozen-fold governing metrics")
    def consistently_worse(
        candidate_metrics: Mapping[str, Any],
        comparator: Mapping[str, Any],
    ) -> bool:
        return (
            candidate_metrics["logLoss"]
            > comparator["logLoss"] + TERMINAL_METRIC_TOLERANCE
            and candidate_metrics["brierScore"]
            > comparator["brierScore"] + TERMINAL_METRIC_TOLERANCE
        )

    substantive_2024_failures = all(
        candidate["eligible"] is not True
        or candidate["convergence"]["status"] != "CONVERGED"
        or candidate["foldMetrics"][0]["metrics"] is None
        or consistently_worse(candidate["foldMetrics"][0]["metrics"], comparator_2024)
        for candidate_id, candidate in candidates.items()
        if candidate_id != "C0"
    )
    selected_consistently_worse_2025 = (
        consistently_worse(final_2025, comparator_2025)
    )
    rejected = substantive_2024_failures and selected_consistently_worse_2025
    if terminal_status == "REJECTED_BASELINE" and not rejected:
        raise SportsPARegistryError("REJECTED_BASELINE is not supported by frozen-fold rejection evidence")
    if terminal_status == "RESEARCH_BASELINE" and (challenger or rejected):
        raise SportsPARegistryError("RESEARCH_BASELINE is inconsistent with the frozen terminal predicate")


def _validate_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(_mapping(value, label="run payload"))
    _exact_keys(payload, _TOP_KEYS, label="run payload")
    _scan_public_safety(payload)
    if payload["schemaVersion"] != RUN_SCHEMA_VERSION:
        raise SportsPARegistryError("Research run schema version differs")
    decision = _validate_decision(payload["decision"])
    blocked = decision["terminalStatus"] == "BLOCKED"

    if payload["projectId"] != PROJECT_ID:
        raise SportsPARegistryError("Research project anchor differs")
    parent = dict(_mapping(payload["parent"], label="parent"))
    _exact_keys(parent, _PARENT_KEYS, label="parent")
    if parent != {
        "registrationId": REGISTRATION_ID,
        "manifestSha": MANIFEST_SHA,
        "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
    }:
        raise SportsPARegistryError("Parent dataset anchors differ")
    bridge = dict(_mapping(payload["identityBridge"], label="identityBridge"))
    _exact_keys(bridge, _BRIDGE_KEYS, label="identityBridge")
    if bridge["registrationId"] != BRIDGE_REGISTRATION_ID or bridge["manifestSha"] != BRIDGE_MANIFEST_SHA:
        raise SportsPARegistryError("Identity-bridge anchors differ")
    _nonblank(bridge["joinAuditId"], label="identityBridge.joinAuditId")
    if payload["classOrder"] != list(PA_CLASS_ORDER):
        raise SportsPARegistryError("Frozen plate-appearance class order differs")

    run_identity = _validate_run_identity(payload)
    claimed_sha = _sha(payload["runSha"], label="runSha")
    expected_sha = semantic_run_sha(payload)
    if claimed_sha != expected_sha:
        raise SportsPARegistryError("Research run content identity differs")

    feature_view = _validate_feature_view(payload["featureView"])
    experiment = _validate_experiment(
        payload["experiment"],
        feature_content_sha=feature_view["contentSha"],
    )
    candidates, candidates_by_id = _validate_candidate_rows(payload["candidates"], blocked=blocked)
    selected = _validate_selected(payload["selected"], candidates=candidates_by_id, blocked=blocked)
    selected_id = selected["candidateId"] if selected else None
    _validate_fold_execution_policy(candidates_by_id, selected_id, blocked=blocked)
    calibration = _validate_calibration(payload["calibration"], selected_id=selected_id, blocked=blocked)
    bootstrap = _validate_bootstrap_comparisons(
        payload["bootstrapComparisons"],
        selected_id=selected_id,
        candidates=candidates_by_id,
        blocked=blocked,
    )
    artifacts = _validate_artifacts(
        payload["artifacts"],
        feature_view=feature_view,
        selected_id=selected_id,
        blocked=blocked,
    )
    graph = _validate_graph(
        payload["graph"],
        candidates=candidates_by_id,
        selected_id=selected_id,
        feature_content_sha=feature_view["contentSha"],
        blocked=blocked,
    )
    _validate_terminal_evidence(
        terminal_status=decision["terminalStatus"],
        candidates=candidates_by_id,
        selected=selected,
        calibration=calibration,
    )
    payload.update(
        {
            "parent": parent,
            "identityBridge": bridge,
            "runIdentity": run_identity,
            "featureView": feature_view,
            "experiment": experiment,
            "candidates": candidates,
            "selected": selected,
            "calibration": calibration,
            "bootstrapComparisons": bootstrap,
            "artifacts": artifacts,
            "graph": graph,
            "decision": decision,
        }
    )
    return payload


def _validate_join_audit_authority(
    audit: Mapping[str, Any],
    *,
    bridge: Mapping[str, Any],
    class_order: Any,
) -> None:
    digest = _sha(audit.get("artifact_sha"), label="identity join audit artifact SHA")
    audit_id = _nonblank(audit.get("join_audit_id"), label="identity join audit ID")
    byte_count = _integer(
        audit.get("artifact_byte_count"),
        label="identity join audit artifact bytes",
        minimum=1,
    )
    expected_id = f"sports-identity-join-audit:sha256:{digest}"
    expected_uri = (
        "asp-model-studio-runtime://sports-modeling/identity-bridges/"
        f"{BRIDGE_REGISTRATION_ID}/join-audits/sha256-{digest}/join-audit.json"
    )
    metadata = bridge.get("metadata_json") or {}
    if (
        audit_id != expected_id
        or audit.get("logical_uri") != expected_uri
        or metadata.get("joinAuditId") != audit_id
        or metadata.get("joinAuditBytes") != byte_count
        or class_order != list(PA_CLASS_ORDER)
    ):
        raise SportsPARegistryError("Identity join audit artifact binding differs")

    evidence = dict(_mapping(audit.get("evidence_json"), label="identity join audit evidence"))
    expected_evidence_keys = {
        "status",
        "parentManifestSha",
        "parentPartitionAuthoritySha",
        "bridgeManifestSha",
        "totalReferences",
        "resolvedReferences",
        "mappingRate",
        "unresolvedReferences",
        "ambiguousReferences",
        "multiplyMappedReferences",
        "joins",
        "yMinus1Coverage",
        "noNamesOrFuzzyMatching",
    }
    _exact_keys(evidence, expected_evidence_keys, label="identity join audit evidence")
    if (
        evidence["status"] != "PASS"
        or evidence["parentManifestSha"] != MANIFEST_SHA
        or evidence["parentPartitionAuthoritySha"] != PARTITION_AUTHORITY_SHA
        or evidence["bridgeManifestSha"] != BRIDGE_MANIFEST_SHA
        or evidence["totalReferences"] != EXPECTED_JOIN_REFERENCES
        or evidence["resolvedReferences"] != EXPECTED_JOIN_REFERENCES
        or evidence["mappingRate"] != 1.0
        or evidence["unresolvedReferences"] != 0
        or evidence["ambiguousReferences"] != 0
        or evidence["multiplyMappedReferences"] != 0
        or evidence["noNamesOrFuzzyMatching"] is not True
    ):
        raise SportsPARegistryError("Identity join audit manifest/count authority differs")

    joins = _list(evidence["joins"], label="identity join audit joins")
    if len(joins) != EXPECTED_JOIN_CONTRACTS:
        raise SportsPARegistryError("Identity join audit contract count differs")
    seen: set[str] = set()
    join_keys = {
        "joinContractId",
        "sourceFamily",
        "physicalFieldName",
        "namespace",
        "joinType",
        "referenceCount",
        "resolvedReferenceCount",
        "mappingRate",
        "unresolvedReferenceCount",
        "ambiguousReferenceCount",
        "multiplyMappedReferenceCount",
        "uniqueSourceIds",
        "uniqueCanonicalPlayers",
        "seasons",
    }
    for raw in joins:
        item = dict(_mapping(raw, label="identity join audit contract"))
        _exact_keys(item, join_keys, label="identity join audit contract")
        contract_id = item["joinContractId"]
        expected = EXPECTED_JOIN_VALIDATION.get(contract_id)
        if expected is None or contract_id in seen:
            raise SportsPARegistryError("Identity join audit contract identity differs")
        seen.add(contract_id)
        references, unique_source_ids, unique_players = expected
        source_family, remainder = contract_id.split(".", 1)
        physical_field = remainder.split(".", 1)[0]
        canonical_dimension = contract_id == "player_prior.canonical_player_id.canonical-to-dimension"
        if (
            item["sourceFamily"] != source_family
            or item["physicalFieldName"] != physical_field
            or item["namespace"] != ("CHADWICK" if canonical_dimension else "RETROSHEET")
            or item["joinType"] != ("EXACT_CANONICAL_UUID" if canonical_dimension else "EXACT_PARENT_JOIN_KEY_TO_ALIAS")
            or item["referenceCount"] != references
            or item["resolvedReferenceCount"] != references
            or item["mappingRate"] != 1.0
            or item["unresolvedReferenceCount"] != 0
            or item["ambiguousReferenceCount"] != 0
            or item["multiplyMappedReferenceCount"] != 0
            or item["uniqueSourceIds"] != unique_source_ids
            or item["uniqueCanonicalPlayers"] != unique_players
            or item["seasons"] != [2021, 2022, 2023, 2024, 2025]
        ):
            raise SportsPARegistryError("Identity join audit contract authority differs")
    if seen != set(EXPECTED_JOIN_VALIDATION):
        raise SportsPARegistryError("Identity join audit contract coverage differs")

    coverage = _list(evidence["yMinus1Coverage"], label="identity join audit Y-minus-1 coverage")
    if len(coverage) != len(EXPECTED_Y_MINUS_1):
        raise SportsPARegistryError("Identity join audit Y-minus-1 coverage count differs")
    coverage_keys = {
        "targetSeason",
        "role",
        "referenceRows",
        "rowsWithEligiblePrior",
        "legitimateMissingPriorRows",
        "eligiblePriorRate",
        "unresolvedIdentityRows",
        "ambiguousIdentityRows",
        "multiplyMappedIdentityRows",
        "maximumEligiblePriorSeason",
    }
    observed_coverage: set[tuple[int, str]] = set()
    for raw in coverage:
        item = dict(_mapping(raw, label="identity join audit Y-minus-1 row"))
        _exact_keys(item, coverage_keys, label="identity join audit Y-minus-1 row")
        key = (item["targetSeason"], item["role"])
        expected = EXPECTED_Y_MINUS_1.get(key)
        if expected is None or key in observed_coverage:
            raise SportsPARegistryError("Identity join audit Y-minus-1 identity differs")
        observed_coverage.add(key)
        references, eligible, missing, maximum = expected
        if (
            item["referenceRows"] != references
            or item["rowsWithEligiblePrior"] != eligible
            or item["legitimateMissingPriorRows"] != missing
            or item["eligiblePriorRate"] != eligible / references
            or item["unresolvedIdentityRows"] != 0
            or item["ambiguousIdentityRows"] != 0
            or item["multiplyMappedIdentityRows"] != 0
            or item["maximumEligiblePriorSeason"] != maximum
        ):
            raise SportsPARegistryError("Identity join audit Y-minus-1 authority differs")
    if observed_coverage != set(EXPECTED_Y_MINUS_1):
        raise SportsPARegistryError("Identity join audit Y-minus-1 coverage differs")


class SportsPAResearchRegistry:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _require_authorities(connection: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        parent = decode_row(
            connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE registration_id = ?",
                (REGISTRATION_ID,),
            ).fetchone()
        )
        project = decode_row(
            connection.execute(
                "SELECT * FROM sports_research_projects WHERE project_id = ?",
                (PROJECT_ID,),
            ).fetchone()
        )
        bridge = decode_row(
            connection.execute(
                "SELECT * FROM sports_identity_bridge_registrations WHERE bridge_registration_id = ?",
                (BRIDGE_REGISTRATION_ID,),
            ).fetchone()
        )
        audit_id = payload["identityBridge"]["joinAuditId"]
        audit = decode_row(
            connection.execute(
                "SELECT * FROM sports_identity_join_audits WHERE join_audit_id = ?",
                (audit_id,),
            ).fetchone()
        )
        parent_metadata = (parent or {}).get("metadata_json") or {}
        if (
            not parent
            or parent.get("manifest_sha") != MANIFEST_SHA
            or parent.get("validation_status") != "VALID"
            or int(parent.get("active", 0)) != 1
            or parent_metadata.get("partitionAuthoritySha") != PARTITION_AUTHORITY_SHA
        ):
            raise SportsPARegistryError("Exact active parent dataset registration is unavailable")
        if not project or project.get("registration_id") != REGISTRATION_ID:
            raise SportsPARegistryError("Exact sports research project is unavailable")
        expected_bridge = {
            "bridge_registration_id": BRIDGE_REGISTRATION_ID,
            "contract_name": IDENTITY_BRIDGE_CONTRACT_NAME,
            "contract_version": IDENTITY_BRIDGE_CONTRACT_VERSION,
            "bridge_manifest_id": BRIDGE_MANIFEST_ID,
            "bridge_manifest_sha": BRIDGE_MANIFEST_SHA,
            "bridge_package_id": BRIDGE_PACKAGE_ID,
            "parent_dataset_registration_id": REGISTRATION_ID,
            "parent_project_id": PROJECT_ID,
            "parent_manifest_sha": MANIFEST_SHA,
            "parent_partition_authority_sha": PARTITION_AUTHORITY_SHA,
            "alias_row_authority_sha": ALIAS_AUTHORITY_SHA,
            "dimension_row_authority_sha": DIMENSION_AUTHORITY_SHA,
            "validation_report_sha": VALIDATION_REPORT_SHA,
            "logical_bridge_root": IDENTITY_BRIDGE_LOGICAL_ROOT,
            "validation_status": "PASS",
            "package_file_count": EXPECTED_PACKAGE_FILES,
            "package_byte_count": EXPECTED_PACKAGE_BYTES,
            "alias_count": EXPECTED_ALIAS_ROWS,
            "active_player_count": EXPECTED_ACTIVE_PLAYER_ROWS,
            "governed_active_player_count": EXPECTED_GOVERNED_ACTIVE_PLAYERS,
            "primary_portable_player_count": EXPECTED_PRIMARY_PORTABLE_PLAYERS,
            "primary_governed_player_count": EXPECTED_PRIMARY_GOVERNED_PLAYERS,
            "namespace_count": EXPECTED_NAMESPACE_COUNT,
            "join_contract_count": EXPECTED_JOIN_CONTRACTS,
            "join_reference_count": EXPECTED_JOIN_REFERENCES,
            "rights_status": "APPROVED_FOR_REGISTERED_USES",
            "active": 1,
        }
        expected_rights = {
            "status": "APPROVED_FOR_REGISTERED_USES",
            "allowedPurposes": list(ALLOWED_PURPOSES),
            "prohibitedPurposes": list(PROHIBITED_PURPOSES),
        }
        bridge_limitations = (bridge or {}).get("limitations_json") or []
        limitation_ids = tuple(
            item.get("limitation_id") if type(item) is dict else None
            for item in bridge_limitations
        )
        if (
            not bridge
            or any(bridge.get(key) != expected for key, expected in expected_bridge.items())
            or bridge.get("rights_json") != expected_rights
            or limitation_ids != EXPECTED_LIMITATION_IDS
        ):
            raise SportsPARegistryError("Exact active identity-bridge registration is unavailable")
        if (
            not audit
            or audit.get("bridge_registration_id") != BRIDGE_REGISTRATION_ID
            or audit.get("status") != "PASS"
            or int(audit.get("total_references", -1)) != EXPECTED_JOIN_REFERENCES
            or int(audit.get("resolved_references", -1)) != EXPECTED_JOIN_REFERENCES
            or int(audit.get("unresolved_references", -1)) != 0
            or int(audit.get("ambiguous_references", -1)) != 0
            or int(audit.get("multiply_mapped_references", -1)) != 0
            or float(audit.get("mapping_rate", -1.0)) != 1.0
        ):
            raise SportsPARegistryError("Exact passing identity join audit is unavailable")
        _validate_join_audit_authority(
            audit,
            bridge=bridge,
            class_order=payload["classOrder"],
        )
        return project

    @staticmethod
    def _feature_row_values(feature: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "feature_view_id": feature["featureViewId"],
            "project_id": PROJECT_ID,
            "parent_dataset_registration_id": REGISTRATION_ID,
            "identity_bridge_registration_id": BRIDGE_REGISTRATION_ID,
            "contract_name": feature["contractName"],
            "contract_version": feature["contractVersion"],
            "contract_sha": feature_contract_sha(),
            "content_sha": feature["contentSha"],
            "row_count": feature["rowCount"],
            "feature_count": feature["featureCount"],
            "feature_names_json": feature["featureNames"],
            "population": feature["population"],
            "seasons_json": feature["seasons"],
            "logical_uri": feature["logicalUri"],
            "artifact_sha": feature["artifactSha"],
            "artifact_byte_count": feature["artifactBytes"],
        }

    @classmethod
    def _upsert_feature_view(
        cls,
        connection: Any,
        feature: Mapping[str, Any],
        *,
        created_at: str,
    ) -> None:
        expected = cls._feature_row_values(feature)
        existing = decode_row(
            connection.execute(
                "SELECT * FROM sports_pa_feature_views WHERE feature_view_id = ? OR content_sha = ? OR logical_uri = ?",
                (feature["featureViewId"], feature["contentSha"], feature["logicalUri"]),
            ).fetchone()
        )
        if existing:
            for key, value in expected.items():
                if existing.get(key) != value:
                    raise SportsPARegistryError("Existing feature-view authority conflicts with the run payload")
            return
        connection.execute(
            """
            INSERT INTO sports_pa_feature_views (
              feature_view_id, project_id, parent_dataset_registration_id,
              identity_bridge_registration_id, contract_name, contract_version,
              contract_sha, content_sha, row_count, feature_count, feature_names_json,
              population, seasons_json, logical_uri, artifact_sha,
              artifact_byte_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feature["featureViewId"],
                PROJECT_ID,
                REGISTRATION_ID,
                BRIDGE_REGISTRATION_ID,
                feature["contractName"],
                feature["contractVersion"],
                feature_contract_sha(),
                feature["contentSha"],
                feature["rowCount"],
                feature["featureCount"],
                json_dumps(feature["featureNames"], []),
                feature["population"],
                json_dumps(feature["seasons"], []),
                feature["logicalUri"],
                feature["artifactSha"],
                feature["artifactBytes"],
                created_at,
            ),
        )

    @staticmethod
    def _complete_workflow(
        workflow: Mapping[str, Any],
        *,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        updated = copy.deepcopy(dict(workflow))
        run_id = payload["runId"]
        terminal_status = payload["decision"]["terminalStatus"]
        selected_id = payload["selected"]["candidateId"]
        updated.update(
            {
                "player_team_state": {
                    "status": "COMPLETE",
                    "evidence": "Governed Y-minus-one player state is materialized in the registered MLB_PA_FEATURE_VIEW_V1 evidence.",
                    "runId": run_id,
                },
                "event_models": {
                    "status": "COMPLETE",
                    "evidence": f"Conditional plate-appearance research candidate {selected_id} completed governed evaluation.",
                    "runId": run_id,
                },
                "candidate_models_experiments": {
                    "status": "COMPLETE",
                    "evidence": "C0-C4 configurations, runtimes, convergence, and fold metrics are registered.",
                    "runId": run_id,
                },
                "temporal_validation": {
                    "status": "COMPLETE",
                    "evidence": "Both frozen rolling-origin validation folds are registered without 2025 candidate-selection reuse.",
                    "runId": run_id,
                },
                "calibration_reliability": {
                    "status": "COMPLETE",
                    "evidence": "Raw and frozen-temperature scaled policies remain inspectable for 2024 and 2025.",
                    "runId": run_id,
                },
                "model_graph_decision": {
                    "status": "COMPLETE",
                    "evidence": f"Research graph terminal decision: {terminal_status}.",
                    "runId": run_id,
                },
                "participation_usage": {"status": "NOT_CONFIGURED"},
                "game_simulation": {"status": "NOT_CONFIGURED"},
                "export_to_asp": {"status": "NOT_CONFIGURED"},
                "monitoring": {"status": "NOT_CONFIGURED"},
                "pa_research_baseline": {
                    "status": terminal_status,
                    "runId": run_id,
                    "runCreatedAt": payload["runIdentity"]["createdAt"],
                    "codeRevision": payload["runIdentity"]["codeRevision"],
                    "selectedCandidateId": selected_id,
                    "researchOnly": True,
                    "deploymentAuthorized": False,
                },
            }
        )
        return updated

    @staticmethod
    def _assert_existing_run(
        connection: Any,
        existing: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> None:
        exact = {
            "run_sha": payload["runSha"],
            "run_identity_sha": payload["runIdentity"]["coreSha"],
            "run_created_at": payload["runIdentity"]["createdAt"],
            "code_revision": payload["runIdentity"]["codeRevision"],
            "schema_version": RUN_SCHEMA_VERSION,
            "project_id": PROJECT_ID,
            "parent_dataset_registration_id": REGISTRATION_ID,
            "parent_manifest_sha": MANIFEST_SHA,
            "parent_partition_authority_sha": PARTITION_AUTHORITY_SHA,
            "identity_bridge_registration_id": BRIDGE_REGISTRATION_ID,
            "identity_bridge_manifest_sha": BRIDGE_MANIFEST_SHA,
            "identity_join_audit_id": payload["identityBridge"]["joinAuditId"],
            "feature_view_id": payload["featureView"]["featureViewId"],
            "class_order_json": list(PA_CLASS_ORDER),
            "terminal_status": payload["decision"]["terminalStatus"],
            "selected_candidate_id": payload["selected"]["candidateId"] if payload["selected"] else None,
            "selection_metric": payload["selected"]["selectionMetric"] if payload["selected"] else None,
            "selection_rationale": payload["selected"]["rationale"] if payload["selected"] else None,
            "calibration_json": payload["calibration"] or {},
            "bootstrap_comparisons_json": payload["bootstrapComparisons"],
            "research_decision_json": payload["decision"],
        }
        if any(existing.get(key) != value for key, value in exact.items()):
            raise SportsPARegistryError("Existing research run conflicts with its content identity")

        def assert_rows(query: str, expected: list[dict[str, Any]], *, label: str) -> None:
            observed = [
                decode_row(row)
                for row in connection.execute(query, (payload["runId"],)).fetchall()
            ]
            if observed != expected:
                raise SportsPARegistryError(f"Existing research run {label} conflicts with its payload")

        experiment = payload["experiment"]
        assert_rows(
            """
            SELECT experiment_id, run_id, objective, seed, training_contract_version
            FROM sports_pa_experiments WHERE run_id = ? ORDER BY experiment_id
            """,
            [
                {
                    "experiment_id": experiment["experimentId"],
                    "run_id": payload["runId"],
                    "objective": experiment["objective"],
                    "seed": experiment["seed"],
                    "training_contract_version": experiment["trainingContractVersion"],
                }
            ],
            label="experiment evidence",
        )
        selected_id = payload["selected"]["candidateId"] if payload["selected"] else None
        expected_candidates = [
            {
                "run_id": payload["runId"],
                "candidate_id": candidate["candidateId"],
                "experiment_id": experiment["experimentId"],
                "candidate_type": candidate["candidateType"],
                "display_name": candidate["displayName"],
                "ordinal": candidate["ordinal"],
                "config_sha": candidate["configSha"],
                "config_json": candidate["config"],
                "runtime_seconds": candidate["runtimeSeconds"],
                "convergence_json": candidate["convergence"],
                "aggregate_metrics_json": candidate["aggregateMetrics"],
                "eligible": int(candidate["eligible"]),
                "selected": int(candidate["candidateId"] == selected_id),
                "rejection_reasons_json": candidate["rejectionReasons"],
            }
            for candidate in payload["candidates"]
        ]
        assert_rows(
            """
            SELECT run_id, candidate_id, experiment_id, candidate_type, display_name,
                   ordinal, config_sha, config_json, runtime_seconds, convergence_json,
                   aggregate_metrics_json, eligible, selected, rejection_reasons_json
            FROM sports_pa_candidates WHERE run_id = ? ORDER BY ordinal
            """,
            expected_candidates,
            label="candidate evidence",
        )
        expected_folds = sorted(
            [
                {
                    "run_id": payload["runId"],
                    "candidate_id": candidate["candidateId"],
                    "fold_id": fold["foldId"],
                    "status": fold["status"],
                    "training_seasons_json": fold["trainingSeasons"],
                    "validation_season": fold["validationSeason"],
                    "training_rows": fold["trainingRows"],
                    "validation_rows": fold["validationRows"],
                    "metrics_json": fold["metrics"] or {},
                }
                for candidate in payload["candidates"]
                for fold in candidate["foldMetrics"]
            ],
            key=lambda item: (item["candidate_id"], item["validation_season"]),
        )
        assert_rows(
            """
            SELECT run_id, candidate_id, fold_id, status, training_seasons_json,
                   validation_season, training_rows, validation_rows, metrics_json
            FROM sports_pa_candidate_fold_metrics
            WHERE run_id = ? ORDER BY candidate_id, validation_season
            """,
            expected_folds,
            label="fold evidence",
        )
        expected_artifacts = sorted(
            [
                {
                    "run_id": payload["runId"],
                    "artifact_id": artifact["artifactId"],
                    "artifact_type": artifact["artifactType"],
                    "logical_uri": artifact["logicalUri"],
                    "artifact_sha": artifact["sha256"],
                    "artifact_byte_count": artifact["byteCount"],
                    "media_type": artifact["mediaType"],
                }
                for artifact in payload["artifacts"]
            ],
            key=lambda item: (item["artifact_type"], item["artifact_id"]),
        )
        assert_rows(
            """
            SELECT run_id, artifact_id, artifact_type, logical_uri, artifact_sha,
                   artifact_byte_count, media_type
            FROM sports_pa_artifact_references
            WHERE run_id = ? ORDER BY artifact_type, artifact_id
            """,
            expected_artifacts,
            label="artifact evidence",
        )
        graph = payload["graph"]
        assert_rows(
            "SELECT run_id, graph_id FROM sports_pa_model_graphs WHERE run_id = ? ORDER BY graph_id",
            [{"run_id": payload["runId"], "graph_id": graph["graphId"]}],
            label="graph identity",
        )
        expected_nodes = sorted(
            [
                {
                    "run_id": payload["runId"],
                    "graph_id": graph["graphId"],
                    "node_id": node["nodeId"],
                    "node_type": node["nodeType"],
                    "label": node["label"],
                    "status": node["status"],
                    "candidate_id": node["candidateId"],
                }
                for node in graph["nodes"]
            ],
            key=lambda item: item["node_id"],
        )
        assert_rows(
            """
            SELECT run_id, graph_id, node_id, node_type, label, status, candidate_id
            FROM sports_pa_model_graph_nodes WHERE run_id = ? ORDER BY node_id
            """,
            expected_nodes,
            label="graph-node evidence",
        )
        expected_edges = sorted(
            [
                {
                    "run_id": payload["runId"],
                    "graph_id": graph["graphId"],
                    "edge_id": edge["edgeId"],
                    "source_node_id": edge["sourceNodeId"],
                    "target_node_id": edge["targetNodeId"],
                    "relation": edge["relation"],
                }
                for edge in graph["edges"]
            ],
            key=lambda item: item["edge_id"],
        )
        assert_rows(
            """
            SELECT run_id, graph_id, edge_id, source_node_id, target_node_id, relation
            FROM sports_pa_model_graph_edges WHERE run_id = ? ORDER BY edge_id
            """,
            expected_edges,
            label="graph-edge evidence",
        )

    def register(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: str,
    ) -> dict[str, Any]:
        validated = _validate_payload(payload)
        registered_by = _nonblank(user_id, label="user_id")
        _scan_public_safety(registered_by, path="user_id")
        recorded_at = now_iso()
        disposition = "CREATED"
        update_project_workflow = validated["decision"]["terminalStatus"] in COMPLETE_TERMINAL_STATUSES

        with self.database.transaction() as connection:
            project = self._require_authorities(connection, validated)
            self._upsert_feature_view(
                connection,
                validated["featureView"],
                created_at=recorded_at,
            )
            existing = decode_row(
                connection.execute(
                    "SELECT * FROM sports_pa_research_runs WHERE run_id = ? OR run_sha = ?",
                    (validated["runId"], validated["runSha"]),
                ).fetchone()
            )
            if existing:
                self._assert_existing_run(connection, existing, validated)
                connection.execute(
                    "UPDATE sports_pa_research_runs SET last_validated_at = ? WHERE run_id = ?",
                    (recorded_at, validated["runId"]),
                )
                disposition = "REUSED"
                update_project_workflow = update_project_workflow and bool(existing.get("active"))
            else:
                connection.execute(
                    "UPDATE sports_pa_research_runs SET active = 0 WHERE project_id = ? AND active = 1",
                    (PROJECT_ID,),
                )
                selected = validated["selected"]
                connection.execute(
                    """
                    INSERT INTO sports_pa_research_runs (
                      run_id, run_sha, run_identity_sha, run_created_at,
                      code_revision, schema_version, project_id,
                      parent_dataset_registration_id, parent_manifest_sha,
                      parent_partition_authority_sha, identity_bridge_registration_id,
                      identity_bridge_manifest_sha, identity_join_audit_id,
                      feature_view_id, class_order_json, terminal_status,
                      selected_candidate_id, selection_metric, selection_rationale,
                      calibration_json, bootstrap_comparisons_json,
                      research_decision_json, registered_at, last_validated_at,
                      registered_by, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        validated["runId"],
                        validated["runSha"],
                        validated["runIdentity"]["coreSha"],
                        validated["runIdentity"]["createdAt"],
                        validated["runIdentity"]["codeRevision"],
                        RUN_SCHEMA_VERSION,
                        PROJECT_ID,
                        REGISTRATION_ID,
                        MANIFEST_SHA,
                        PARTITION_AUTHORITY_SHA,
                        BRIDGE_REGISTRATION_ID,
                        BRIDGE_MANIFEST_SHA,
                        validated["identityBridge"]["joinAuditId"],
                        validated["featureView"]["featureViewId"],
                        json_dumps(list(PA_CLASS_ORDER), []),
                        validated["decision"]["terminalStatus"],
                        selected["candidateId"] if selected else None,
                        selected["selectionMetric"] if selected else None,
                        selected["rationale"] if selected else None,
                        json_dumps(validated["calibration"], {}) if validated["calibration"] else None,
                        json_dumps(validated["bootstrapComparisons"], []),
                        json_dumps(validated["decision"], {}),
                        recorded_at,
                        recorded_at,
                        registered_by,
                    ),
                )
                experiment = validated["experiment"]
                connection.execute(
                    """
                    INSERT INTO sports_pa_experiments (
                      experiment_id, run_id, objective, seed, training_contract_version
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        experiment["experimentId"],
                        validated["runId"],
                        experiment["objective"],
                        experiment["seed"],
                        experiment["trainingContractVersion"],
                    ),
                )
                selected_id = selected["candidateId"] if selected else None
                for candidate in validated["candidates"]:
                    connection.execute(
                        """
                        INSERT INTO sports_pa_candidates (
                          run_id, candidate_id, experiment_id, candidate_type,
                          display_name, ordinal, config_sha, config_json,
                          runtime_seconds, convergence_json, aggregate_metrics_json,
                          eligible, selected, rejection_reasons_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            validated["runId"],
                            candidate["candidateId"],
                            experiment["experimentId"],
                            candidate["candidateType"],
                            candidate["displayName"],
                            candidate["ordinal"],
                            candidate["configSha"],
                            json_dumps(candidate["config"], {}),
                            candidate["runtimeSeconds"],
                            json_dumps(candidate["convergence"], {}),
                            json_dumps(candidate["aggregateMetrics"], {}),
                            int(candidate["eligible"]),
                            int(candidate["candidateId"] == selected_id),
                            json_dumps(candidate["rejectionReasons"], []),
                        ),
                    )
                    for fold in candidate["foldMetrics"]:
                        connection.execute(
                            """
                            INSERT INTO sports_pa_candidate_fold_metrics (
                              run_id, candidate_id, fold_id, status,
                              training_seasons_json, validation_season,
                              training_rows, validation_rows, metrics_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                validated["runId"],
                                candidate["candidateId"],
                                fold["foldId"],
                                fold["status"],
                                json_dumps(fold["trainingSeasons"], []),
                                fold["validationSeason"],
                                fold["trainingRows"],
                                fold["validationRows"],
                                json_dumps(fold["metrics"], {}) if fold["metrics"] is not None else None,
                            ),
                        )
                for artifact in validated["artifacts"]:
                    connection.execute(
                        """
                        INSERT INTO sports_pa_artifact_references (
                          run_id, artifact_id, artifact_type, logical_uri,
                          artifact_sha, artifact_byte_count, media_type
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            validated["runId"],
                            artifact["artifactId"],
                            artifact["artifactType"],
                            artifact["logicalUri"],
                            artifact["sha256"],
                            artifact["byteCount"],
                            artifact["mediaType"],
                        ),
                    )
                graph = validated["graph"]
                connection.execute(
                    "INSERT INTO sports_pa_model_graphs (run_id, graph_id) VALUES (?, ?)",
                    (validated["runId"], graph["graphId"]),
                )
                for node in graph["nodes"]:
                    connection.execute(
                        """
                        INSERT INTO sports_pa_model_graph_nodes (
                          run_id, graph_id, node_id, node_type, label, status, candidate_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            validated["runId"],
                            graph["graphId"],
                            node["nodeId"],
                            node["nodeType"],
                            node["label"],
                            node["status"],
                            node["candidateId"],
                        ),
                    )
                for edge in graph["edges"]:
                    connection.execute(
                        """
                        INSERT INTO sports_pa_model_graph_edges (
                          run_id, graph_id, edge_id, source_node_id,
                          target_node_id, relation
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            validated["runId"],
                            graph["graphId"],
                            edge["edgeId"],
                            edge["sourceNodeId"],
                            edge["targetNodeId"],
                            edge["relation"],
                        ),
                    )

            if update_project_workflow:
                workflow = self._complete_workflow(
                    project.get("workflow_evidence_json") or {},
                    payload=validated,
                )
                connection.execute(
                    "UPDATE sports_research_projects SET workflow_evidence_json = ?, updated_at = ? WHERE project_id = ?",
                    (json_dumps(workflow, {}), recorded_at, PROJECT_ID),
                )

        public = self._public_run(validated["runId"])
        if public is None:
            raise SportsPARegistryError("Research run was not durably registered")
        public["paBaseline"]["registry"]["registrationDisposition"] = disposition
        return public

    def _public_run(self, run_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            run = decode_row(
                connection.execute(
                    "SELECT * FROM sports_pa_research_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            )
            if not run:
                return None
            feature = decode_row(
                connection.execute(
                    "SELECT * FROM sports_pa_feature_views WHERE feature_view_id = ?",
                    (run["feature_view_id"],),
                ).fetchone()
            )
            experiment = decode_row(
                connection.execute(
                    "SELECT * FROM sports_pa_experiments WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            )
            candidate_rows = [
                decode_row(row)
                for row in connection.execute(
                    "SELECT * FROM sports_pa_candidates WHERE run_id = ? ORDER BY ordinal",
                    (run_id,),
                ).fetchall()
            ]
            fold_rows = [
                decode_row(row)
                for row in connection.execute(
                    "SELECT * FROM sports_pa_candidate_fold_metrics WHERE run_id = ? ORDER BY candidate_id, validation_season",
                    (run_id,),
                ).fetchall()
            ]
            artifact_rows = [
                decode_row(row)
                for row in connection.execute(
                    "SELECT * FROM sports_pa_artifact_references WHERE run_id = ? ORDER BY artifact_type, artifact_id",
                    (run_id,),
                ).fetchall()
            ]
            graph = decode_row(
                connection.execute(
                    "SELECT * FROM sports_pa_model_graphs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            )
            node_rows = [
                decode_row(row)
                for row in connection.execute(
                    "SELECT * FROM sports_pa_model_graph_nodes WHERE run_id = ? ORDER BY node_id",
                    (run_id,),
                ).fetchall()
            ]
            edge_rows = [
                decode_row(row)
                for row in connection.execute(
                    "SELECT * FROM sports_pa_model_graph_edges WHERE run_id = ? ORDER BY edge_id",
                    (run_id,),
                ).fetchall()
            ]
            project = decode_row(
                connection.execute(
                    "SELECT * FROM sports_research_projects WHERE project_id = ?",
                    (run["project_id"],),
                ).fetchone()
            )

        public_artifacts = [
            {
                "artifactId": item["artifact_id"],
                "artifactType": item["artifact_type"],
                "logicalUri": item["logical_uri"],
                "sha256": item["artifact_sha"],
                "byteCount": item["artifact_byte_count"],
                "mediaType": item["media_type"],
            }
            for item in artifact_rows
            if item is not None
        ]
        prediction_artifacts = {
            season: next(
                (
                    item
                    for item in public_artifacts
                    if item["artifactType"] == f"FOLD_{season}_PREDICTIONS"
                ),
                None,
            )
            for season in (2024, 2025)
        }

        folds_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fold in fold_rows:
            assert fold is not None
            validation_season = int(fold["validation_season"])
            folds_by_candidate[str(fold["candidate_id"])].append(
                {
                    "foldId": fold["fold_id"],
                    "status": fold["status"],
                    "trainingSeasons": fold["training_seasons_json"],
                    "validationSeason": validation_season,
                    "trainingRows": fold["training_rows"],
                    "validationRows": fold["validation_rows"],
                    "metrics": fold["metrics_json"] if fold["status"] == "COMPLETE" else None,
                    "predictionArtifact": (
                        prediction_artifacts.get(validation_season)
                        if fold["status"] == "COMPLETE"
                        else None
                    ),
                }
            )
        candidates: list[dict[str, Any]] = []
        for candidate in candidate_rows:
            assert candidate is not None
            candidates.append(
                {
                    "candidateId": candidate["candidate_id"],
                    "candidateType": candidate["candidate_type"],
                    "displayName": candidate["display_name"],
                    "ordinal": candidate["ordinal"],
                    "config": candidate["config_json"],
                    "configSha": candidate["config_sha"],
                    "runtimeSeconds": candidate["runtime_seconds"],
                    "convergence": candidate["convergence_json"],
                    "foldMetrics": folds_by_candidate[str(candidate["candidate_id"])],
                    "aggregateMetrics": candidate["aggregate_metrics_json"],
                    "eligible": bool(candidate["eligible"]),
                    "selected": bool(candidate["selected"]),
                    "rejectionReasons": candidate["rejection_reasons_json"],
                }
            )
        selected = None
        if run["selected_candidate_id"] is not None:
            selected = {
                "candidateId": run["selected_candidate_id"],
                "selectionMetric": run["selection_metric"],
                "rationale": run["selection_rationale"],
            }
        decision = run["research_decision_json"]
        calibration = run["calibration_json"] if run["terminal_status"] != "BLOCKED" else None
        bootstrap = run["bootstrap_comparisons_json"]
        workflow = copy.deepcopy((project or {}).get("workflow_evidence_json") or {})
        if run["terminal_status"] == "BLOCKED":
            workflow["pa_research_baseline"] = {
                "status": "BLOCKED",
                "runId": run["run_id"],
                "runCreatedAt": run["run_created_at"],
                "codeRevision": run["code_revision"],
                "evidence": decision.get("rationale", "Governed research run is blocked."),
                "researchOnly": True,
                "deploymentAuthorized": False,
            }
        assert feature is not None and experiment is not None and graph is not None
        public = {
            "paBaseline": {
                "run": {
                    "schemaVersion": run["schema_version"],
                    "runId": run["run_id"],
                    "runSha": run["run_sha"],
                    "runIdentity": {
                        "schemaVersion": RUN_IDENTITY_SCHEMA_VERSION,
                        "coreSha": run["run_identity_sha"],
                        "createdAt": run["run_created_at"],
                        "codeRevision": run["code_revision"],
                    },
                    "projectId": run["project_id"],
                    "terminalStatus": run["terminal_status"],
                    "parent": {
                        "registrationId": run["parent_dataset_registration_id"],
                        "manifestSha": run["parent_manifest_sha"],
                        "partitionAuthoritySha": run["parent_partition_authority_sha"],
                    },
                    "identityBridge": {
                        "registrationId": run["identity_bridge_registration_id"],
                        "manifestSha": run["identity_bridge_manifest_sha"],
                        "joinAuditId": run["identity_join_audit_id"],
                    },
                    "classOrder": run["class_order_json"],
                    "experiment": {
                        "experimentId": experiment["experiment_id"],
                        "objective": experiment["objective"],
                        "seed": experiment["seed"],
                        "trainingContractVersion": experiment["training_contract_version"],
                    },
                },
                "featureView": {
                    "featureViewId": feature["feature_view_id"],
                    "contractName": feature["contract_name"],
                    "contractVersion": feature["contract_version"],
                    "contractSha": feature["contract_sha"],
                    "contentSha": feature["content_sha"],
                    "rowCount": feature["row_count"],
                    "featureCount": feature["feature_count"],
                    "featureNames": feature["feature_names_json"],
                    "population": feature["population"],
                    "seasons": feature["seasons_json"],
                    "logicalUri": feature["logical_uri"],
                    "artifactSha": feature["artifact_sha"],
                    "artifactBytes": feature["artifact_byte_count"],
                },
                "candidates": candidates,
                "selected": selected,
                "calibration": calibration,
                "bootstrap": bootstrap,
                "bootstrapComparisons": bootstrap,
                "decision": decision,
                "registry": {
                    "runCreatedAt": run["run_created_at"],
                    "codeRevision": run["code_revision"],
                    "registeredAt": run["registered_at"],
                    "lastValidatedAt": run["last_validated_at"],
                    "registeredBy": run["registered_by"],
                    "active": bool(run["active"]),
                    "artifacts": public_artifacts,
                },
                "graph": {
                    "graphId": graph["graph_id"],
                    "nodes": [
                        {
                            "nodeId": item["node_id"],
                            "nodeType": item["node_type"],
                            "label": item["label"],
                            "status": item["status"],
                            "candidateId": item["candidate_id"],
                        }
                        for item in node_rows
                        if item is not None
                    ],
                    "edges": [
                        {
                            "edgeId": item["edge_id"],
                            "sourceNodeId": item["source_node_id"],
                            "targetNodeId": item["target_node_id"],
                            "relation": item["relation"],
                        }
                        for item in edge_rows
                        if item is not None
                    ],
                },
                "workflow": workflow,
            }
        }
        _scan_public_safety(public)
        return public

    def public_active(self) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT run_id FROM sports_pa_research_runs
                WHERE project_id = ? AND active = 1
                ORDER BY registered_at DESC LIMIT 1
                """,
                (PROJECT_ID,),
            ).fetchone()
        return self._public_run(str(row[0])) if row else None


__all__ = [
    "FEATURE_VIEW_CONTRACT_NAME",
    "FEATURE_VIEW_CONTRACT_VERSION",
    "RUN_IDENTITY_CORE_SCHEMA_VERSION",
    "RUN_IDENTITY_SCHEMA_VERSION",
    "RUN_SCHEMA_VERSION",
    "SportsPARegistryError",
    "SportsPAResearchRegistry",
    "semantic_run_identity_sha",
    "semantic_run_sha",
]
