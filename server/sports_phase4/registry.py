from __future__ import annotations

import copy
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ..persistence.db import Database, decode_row, json_dumps, now_iso
from ..sports_datasets.constants import (
    MANIFEST_SHA,
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    REGISTRATION_ID,
)
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    ALLOWED_PURPOSES,
    BRIDGE_MANIFEST_ID,
    BRIDGE_MANIFEST_SHA,
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
    EXPECTED_LIMITATION_IDS,
    EXPECTED_NAMESPACE_COUNT,
    EXPECTED_PACKAGE_BYTES,
    EXPECTED_PACKAGE_FILES,
    EXPECTED_PRIMARY_GOVERNED_PLAYERS,
    EXPECTED_PRIMARY_PORTABLE_PLAYERS,
    LOGICAL_PACKAGE_ROOT as IDENTITY_BRIDGE_LOGICAL_ROOT,
    PROHIBITED_PURPOSES,
    VALIDATION_REPORT_SHA,
)
from .dynamic_contract import (
    BOOTSTRAP_SEED as DYNAMIC_BOOTSTRAP_SEED,
    CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE,
    CONTRACT_NAME as DYNAMIC_CONTRACT_NAME,
    DECISION_TOLERANCE as DYNAMIC_DECISION_TOLERANCE,
    DECISION_ENUM as DYNAMIC_DECISIONS,
    DESCRIPTOR_SCHEMA_VERSION as DYNAMIC_DESCRIPTOR_SCHEMA_VERSION,
    EXPECTED_SOURCE_PARTITION_COUNT,
    HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION,
    PHASE3_FEATURE_CONTRACT_SHA,
    PHASE3_FEATURE_ARTIFACT_SHA,
    PHASE3_FEATURE_CONTENT_SHA,
    PHASE3_FEATURE_MATERIALIZATION_ID,
    PHASE3_FEATURE_VIEW_ID,
    PHASE3_FOLD_2024_PREDICTION_SHA,
    PHASE3_FOLD_2025_PREDICTION_SHA,
    PHASE3_RUN_ID,
    PHASE3_RUN_SHA,
    REFERENCE_CLASS,
    SEMANTIC_VERSION as DYNAMIC_SEMANTIC_VERSION,
    dynamic_history_index_schema_sha,
    dynamic_state_contract_payload,
    dynamic_state_contract_sha,
    dynamic_state_schema_sha,
    validate_dynamic_component_evidence,
)
from ..sports_modeling.metrics import PA_CLASS_ORDER
from ..sports_modeling.registry import (
    SportsPARegistryError,
    SportsPAResearchRegistry,
    _complete_graph_authority as _phase3_complete_graph_authority,
    _validate_join_audit_authority,
    _validate_metrics as _validate_phase3_metrics,
    _validate_payload as _validate_phase3_payload,
)
from .participation_contract import (
    BULLPEN_CANDIDATES,
    BULLPEN_CONTRACT_NAME,
    BULLPEN_DECISION_ENUM,
    BullpenDecisionEvidence,
    LINEUP_CANDIDATES,
    LINEUP_CONTRACT_NAME,
    LINEUP_DECISION_ENUM,
    LineupDecisionEvidence,
    STARTER_CANDIDATES,
    STARTER_CONTRACT_NAME,
    STARTER_DECISION_ENUM,
    StarterDecisionEvidence,
    bullpen_decision,
    bullpen_contract_payload,
    canonical_sha,
    lineup_decision,
    lineup_contract_payload,
    starter_decision,
    starter_contract_payload,
)


STUDY_SCHEMA_VERSION = "MLB_PHASE4_RESEARCH_STUDY_V1"
STUDY_IDENTITY_SCHEMA_VERSION = "MLB_PHASE4_STUDY_IDENTITY_V1"
STUDY_CORE_SCHEMA_VERSION = "MLB_PHASE4_STUDY_CORE_V1"
RUNTIME_LOGICAL_PREFIX = "asp-model-studio-runtime://sports-phase4/"
PHASE3_EXPERIMENT_ID = (
    "mlb-pa-experiment:sha256:"
    "a7aaf28c180cded23179735ea00ddb45582e58148a49b447f0754c3cb2c9cf7e"
)
PHASE3_FEATURE_CONTRACT_NAME = "MLB_PA_FEATURE_VIEW_V1"
PHASE3_TERMINAL_STATUS = "RESEARCH_BASELINE"
PHASE3_GRAPH_ID = (
    "mlb-pa-model-graph:sha256:"
    "c42cec805870c4eae5f935aa406714e5cecd0f46ff0dfd2ca78d57e2397de18b"
)
PHASE4_JOIN_AUDIT_ID = (
    "sports-identity-join-audit:sha256:"
    "375ef4faef6716a8d66fe68b30c12bf8caff5b9255aa71fc4bd7354f9589b8b9"
)
_PHASE3_RUNTIME_OBJECT_PREFIX = (
    "asp-model-studio-runtime://sports-modeling/mlb-pa-v1/objects/sha256"
)


def _phase3_artifact_authority(
    *,
    artifact_type: str,
    digest: str,
    filename: str,
    byte_count: int,
) -> dict[str, Any]:
    return {
        "artifactId": f"sports-pa-artifact:{artifact_type.casefold()}:sha256:{digest}",
        "artifactType": artifact_type,
        "logicalUri": (
            f"{_PHASE3_RUNTIME_OBJECT_PREFIX}/{digest[:2]}/{digest}/{filename}"
        ),
        "sha256": digest,
        "byteCount": byte_count,
        "mediaType": "application/vnd.apache.parquet",
    }


_PHASE3_FEATURE_ARTIFACT_AUTHORITY = _phase3_artifact_authority(
    artifact_type="FEATURE_VIEW",
    digest=PHASE3_FEATURE_ARTIFACT_SHA,
    filename="mlb-pa-feature-view-v1.parquet",
    byte_count=11_574_290,
)
_PHASE3_D0_ARTIFACT_AUTHORITIES = {
    2024: _phase3_artifact_authority(
        artifact_type="FOLD_2024_PREDICTIONS",
        digest=PHASE3_FOLD_2024_PREDICTION_SHA,
        filename="fold-2024-predictions.parquet",
        byte_count=57_339_406,
    ),
    2025: _phase3_artifact_authority(
        artifact_type="FOLD_2025_PREDICTIONS",
        digest=PHASE3_FOLD_2025_PREDICTION_SHA,
        filename="fold-2025-predictions.parquet",
        byte_count=36_820_708,
    ),
}
_DYNAMIC_FOLD_AUTHORITIES = {
    2024: {
        "foldId": "dynamic-train-2023-validate-2024",
        "trainingSeasons": [2023],
        "trainingRows": 184_104,
        "validationRows": 182_449,
    },
    2025: {
        "foldId": "dynamic-train-through-2024-validate-2025",
        "trainingSeasons": [2023, 2024],
        "trainingRows": 366_553,
        "validationRows": 182_926,
    },
}

COMPONENT_SLOTS = (
    "dynamicState",
    "lineup",
    "starterDuration",
    "bullpenUsage",
)
COMPONENT_KEYS = {
    "componentId",
    "componentType",
    "contractName",
    "contractSha",
    "descriptor",
    "candidates",
    "selected",
    "folds",
    "metrics",
    "calibration",
    "bootstrap",
    "coverage",
    "decision",
    "artifactIds",
}
COMPONENT_POLICIES: dict[str, dict[str, Any]] = {
    "dynamicState": {
        "type": "DYNAMIC_PLAYER_STATE",
        "contract": DYNAMIC_CONTRACT_NAME,
        "sha": dynamic_state_contract_sha(),
        "requiredCandidates": ("D0", "D1", "D2", "D3", "D4"),
        "optionalCandidates": (),
        "decisions": frozenset(DYNAMIC_DECISIONS),
    },
    "lineup": {
        "type": "LINEUP_PROJECTION",
        "contract": LINEUP_CONTRACT_NAME,
        "sha": canonical_sha(lineup_contract_payload()),
        "requiredCandidates": tuple(
            key for key, value in LINEUP_CANDIDATES.items() if not value["optional"]
        ),
        "optionalCandidates": tuple(
            key for key, value in LINEUP_CANDIDATES.items() if value["optional"]
        ),
        "decisions": frozenset(LINEUP_DECISION_ENUM),
    },
    "starterDuration": {
        "type": "STARTER_DURATION",
        "contract": STARTER_CONTRACT_NAME,
        "sha": canonical_sha(starter_contract_payload()),
        "requiredCandidates": tuple(
            key for key, value in STARTER_CANDIDATES.items() if not value["optional"]
        ),
        "optionalCandidates": tuple(
            key for key, value in STARTER_CANDIDATES.items() if value["optional"]
        ),
        "decisions": frozenset(STARTER_DECISION_ENUM),
    },
    "bullpenUsage": {
        "type": "BULLPEN_USAGE",
        "contract": BULLPEN_CONTRACT_NAME,
        "sha": canonical_sha(bullpen_contract_payload()),
        "requiredCandidates": tuple(
            key for key, value in BULLPEN_CANDIDATES.items() if not value["optional"]
        ),
        "optionalCandidates": tuple(
            key for key, value in BULLPEN_CANDIDATES.items() if value["optional"]
        ),
        "decisions": frozenset(BULLPEN_DECISION_ENUM),
    },
}

_TOP_KEYS = {
    "schemaVersion",
    "studyId",
    "studySha",
    "studyIdentity",
    "projectId",
    "dataset",
    "identityBridge",
    "phase3Baseline",
    "components",
    "artifacts",
    "graph",
    "decision",
}
_IDENTITY_KEYS = {"schemaVersion", "coreSha", "createdAt", "codeRevision"}
_DATASET_KEYS = {"registrationId", "manifestSha", "partitionAuthoritySha"}
_BRIDGE_KEYS = {"registrationId", "manifestSha", "joinAuditId"}
_PHASE3_KEYS = {
    "runId",
    "runSha",
    "experimentId",
    "featureContractName",
    "featureContractSha",
    "featureViewId",
    "graphId",
    "status",
}
_ARTIFACT_KEYS = {
    "artifactId",
    "artifactType",
    "logicalUri",
    "sha256",
    "byteCount",
    "mediaType",
}
_GRAPH_KEYS = {"graphId", "parentGraphId", "nodes", "edges"}
_NODE_KEYS = {
    "nodeId",
    "nodeType",
    "label",
    "status",
    "componentId",
    "authorityRef",
}
_EDGE_KEYS = {"edgeId", "sourceNodeId", "targetNodeId", "relation"}
_DECISION_KEYS = {
    "researchOnly",
    "deploymentAuthorized",
    "simulationAuthorized",
    "bundleAuthorized",
    "limitations",
}

_FROZEN_STUDY_DECISION = {
    "researchOnly": True,
    "deploymentAuthorized": False,
    "simulationAuthorized": False,
    "bundleAuthorized": False,
    "limitations": [
        "Phase 4 evidence is retrospective research and is not prospective proof.",
        "Confirmed lineups, probable starters, injuries, handedness, and platoon evidence are not configured.",
        "Base-out transitions, game simulation, residual correction, export bundles, and monitoring are not configured.",
    ],
}

_JSON_MEDIA_TYPE = "application/json"
_PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
_ARTIFACT_FILENAME_RULES: dict[str, tuple[str, re.Pattern[str]]] = {
    "DYNAMIC_PLAYER_STATE": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"mlb-dynamic-player-state-v1\.parquet\Z"),
    ),
    "DYNAMIC_HISTORY_INDEX": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"dynamic-history-index\.parquet\Z"),
    ),
    "DYNAMIC_CONTRACT": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-contract\.json\Z")),
    "DYNAMIC_STATE_SCHEMA": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-state-schema\.json\Z")),
    "DYNAMIC_HISTORY_SCHEMA": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-history-schema\.json\Z")),
    "DYNAMIC_TUNING": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-tuning\.json\Z")),
    "DYNAMIC_STATE_POSTERIOR_PREDICTIVE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"dynamic-state-posterior-predictive\.json\Z"),
    ),
    "DYNAMIC_MODEL_STATE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"model-D[1-4]-validate-(?:2024|2025)\.json\Z"),
    ),
    "DYNAMIC_PREPROCESSOR_STATE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"preprocessor-D[1-4]-validate-(?:2024|2025)\.json\Z"),
    ),
    "DYNAMIC_FOLD_2024_PREDICTIONS": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"dynamic-fold-2024-predictions\.parquet\Z"),
    ),
    "DYNAMIC_FOLD_2025_PREDICTIONS": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"dynamic-fold-2025-predictions\.parquet\Z"),
    ),
    "DYNAMIC_EXPERIMENT_METRICS": (
        _JSON_MEDIA_TYPE,
        re.compile(r"dynamic-experiment-metrics\.json\Z"),
    ),
    "DYNAMIC_CALIBRATION": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-calibration\.json\Z")),
    "DYNAMIC_BOOTSTRAP": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-bootstrap\.json\Z")),
    "DYNAMIC_COVERAGE": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-coverage\.json\Z")),
    "DYNAMIC_LINEAGE": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-lineage\.json\Z")),
    "DYNAMIC_MODEL_CARD": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-model-card\.json\Z")),
    "DYNAMIC_FINAL_CHECKPOINT": (
        _JSON_MEDIA_TYPE,
        re.compile(r"dynamic-final-checkpoint\.json\Z"),
    ),
    "LINEUP_PROJECTION_FEATURE_VIEW": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"lineup-feature-view\.parquet\Z"),
    ),
    "STARTER_DURATION_FEATURE_VIEW": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"starter-feature-view\.parquet\Z"),
    ),
    "BULLPEN_USAGE_FEATURE_VIEW": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"bullpen-feature-view\.parquet\Z"),
    ),
    "PARTICIPATION_CONTRACT_SET": (
        _JSON_MEDIA_TYPE,
        re.compile(r"participation-contract-set\.json\Z"),
    ),
    "DYNAMIC_STATE_BINDING": (_JSON_MEDIA_TYPE, re.compile(r"dynamic-state-binding\.json\Z")),
    "PARTICIPATION_COVERAGE": (_JSON_MEDIA_TYPE, re.compile(r"participation-coverage\.json\Z")),
    "FEATURE_CHECKPOINT": (_JSON_MEDIA_TYPE, re.compile(r"feature-checkpoint\.json\Z")),
    "MODEL_STATE": (
        _JSON_MEDIA_TYPE,
        re.compile(
            r"(?:lineup_projection-L[0-2]|starter_duration-S[0-3]|bullpen_usage-B[0-2])-validate-(?:2024|2025)\.json\Z"
        ),
    ),
    "LINEUP_PROJECTION_FOLD_2024_PREDICTIONS": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"lineup_projection-fold-2024-predictions\.parquet\Z"),
    ),
    "LINEUP_PROJECTION_FOLD_2025_PREDICTIONS": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"lineup_projection-fold-2025-predictions\.parquet\Z"),
    ),
    "STARTER_DURATION_FOLD_2024_PREDICTIONS": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"starter_duration-fold-2024-predictions\.parquet\Z"),
    ),
    "STARTER_DURATION_FOLD_2025_PREDICTIONS": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"starter_duration-fold-2025-predictions\.parquet\Z"),
    ),
    "BULLPEN_USAGE_FOLD_2024_PREDICTIONS": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"bullpen_usage-fold-2024-predictions\.parquet\Z"),
    ),
    "BULLPEN_USAGE_FOLD_2025_PREDICTIONS": (
        _PARQUET_MEDIA_TYPE,
        re.compile(r"bullpen_usage-fold-2025-predictions\.parquet\Z"),
    ),
    "EXPERIMENT_EVIDENCE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"(?:lineup_projection|starter_duration|bullpen_usage)-experiment\.json\Z"),
    ),
    "CANDIDATE_POOL_EVIDENCE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"(?:lineup_projection|starter_duration|bullpen_usage)-candidate-pool\.json\Z"),
    ),
    "METRICS_EVIDENCE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"(?:lineup_projection|starter_duration|bullpen_usage)-metrics\.json\Z"),
    ),
    "CALIBRATION_EVIDENCE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"(?:lineup_projection|starter_duration|bullpen_usage)-calibration\.json\Z"),
    ),
    "LINEAGE_EVIDENCE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"(?:lineup_projection|starter_duration|bullpen_usage)-lineage\.json\Z"),
    ),
    "DECISION_EVIDENCE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"(?:lineup_projection|starter_duration|bullpen_usage)-decision\.json\Z"),
    ),
    "BOOTSTRAP_EVIDENCE": (
        _JSON_MEDIA_TYPE,
        re.compile(r"(?:lineup_projection|starter_duration|bullpen_usage)-bootstrap\.json\Z"),
    ),
    "COMPONENT_CARD": (
        _JSON_MEDIA_TYPE,
        re.compile(r"(?:lineup_projection|starter_duration|bullpen_usage)-component-card\.json\Z"),
    ),
    "FINAL_CHECKPOINT": (_JSON_MEDIA_TYPE, re.compile(r"final-checkpoint\.json\Z")),
}
_DYNAMIC_ARTIFACT_TYPES = {
    artifact_type
    for artifact_type in _ARTIFACT_FILENAME_RULES
    if artifact_type.startswith("DYNAMIC_") and artifact_type != "DYNAMIC_STATE_BINDING"
}
_DYNAMIC_COMPLETED_ARTIFACT_CARDINALITIES = {
    "DYNAMIC_PLAYER_STATE": 1,
    "DYNAMIC_HISTORY_INDEX": 1,
    "DYNAMIC_CONTRACT": 1,
    "DYNAMIC_STATE_SCHEMA": 1,
    "DYNAMIC_HISTORY_SCHEMA": 1,
    "DYNAMIC_TUNING": 1,
    "DYNAMIC_STATE_POSTERIOR_PREDICTIVE": 1,
    "DYNAMIC_MODEL_STATE": 8,
    "DYNAMIC_PREPROCESSOR_STATE": 8,
    "DYNAMIC_FOLD_2024_PREDICTIONS": 1,
    "DYNAMIC_FOLD_2025_PREDICTIONS": 1,
    "DYNAMIC_EXPERIMENT_METRICS": 1,
    "DYNAMIC_CALIBRATION": 1,
    "DYNAMIC_BOOTSTRAP": 1,
    "DYNAMIC_COVERAGE": 1,
    "DYNAMIC_LINEAGE": 1,
    "DYNAMIC_FINAL_CHECKPOINT": 1,
    "DYNAMIC_MODEL_CARD": 1,
}
_DYNAMIC_MODEL_FILENAMES = {
    f"model-D{ordinal}-validate-{season}.json"
    for season in (2024, 2025)
    for ordinal in range(1, 5)
}
_DYNAMIC_PREPROCESSOR_FILENAMES = {
    f"preprocessor-D{ordinal}-validate-{season}.json"
    for season in (2024, 2025)
    for ordinal in range(1, 5)
}
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)^[a-z]:[\\/]")
_EMBEDDED_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?:^|[\\/])[a-z]:[\\/]")
_TOKEN_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:^|[\s'\"`\[\]\(\)\{\}=])(?:[a-z]:[\\/]|\\\\[^\s\\/]|//[^\s/]|/(?!/)[a-z0-9._~-])"
)
_TOKEN_FILE_URI_RE = re.compile(r"(?i)(?:^|[\s'\"`\[\]\(\)\{\}=])file:")
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
_LOCATOR_KEYS = {
    "artifactid",
    "artifactids",
    "artifactsha",
    "artifactbytes",
    "logicaluri",
    "uri",
}


class SportsPhase4RegistryError(RuntimeError):
    """Fail-closed Phase 4 metadata registry error."""


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise SportsPhase4RegistryError(
            f"{label} fields differ (missing={sorted(expected - actual)}, extra={sorted(actual - expected)})"
        )


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise SportsPhase4RegistryError(f"{label} must be an object")
    return dict(value)


def _list(value: Any, *, label: str) -> list[Any]:
    if type(value) is not list:
        raise SportsPhase4RegistryError(f"{label} must be an array")
    return value


def _nonblank(value: Any, *, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise SportsPhase4RegistryError(f"{label} must be a non-blank canonical string")
    return value


def _sha(value: Any, *, label: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise SportsPhase4RegistryError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _scan_public_safety(value: Any, *, path: str = "$") -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise SportsPhase4RegistryError(f"Binary payloads are prohibited at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in _BANNED_NORMALIZED_KEYS:
                raise SportsPhase4RegistryError(
                    f"Prediction, model-byte, or physical-path field is prohibited at {path}"
                )
            _scan_public_safety(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_public_safety(item, path=f"{path}[{index}]")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise SportsPhase4RegistryError(f"Non-finite numerical evidence is prohibited at {path}")
    if isinstance(value, str) and (
        _TOKEN_ABSOLUTE_PATH_RE.search(value)
        or _TOKEN_FILE_URI_RE.search(value)
        or _WINDOWS_ABSOLUTE_RE.match(value)
        or _EMBEDDED_WINDOWS_ABSOLUTE_RE.search(value)
        or "/.runtime/" in value.casefold()
        or "\\.runtime\\" in value.casefold()
    ):
        raise SportsPhase4RegistryError(f"Physical or runtime path is prohibited at {path}")


def _without_locators(value: Any) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in _LOCATOR_KEYS:
                continue
            output[str(key)] = _without_locators(item)
        return output
    if isinstance(value, list):
        return [_without_locators(item) for item in value]
    return copy.deepcopy(value)


def semantic_component_sha(component: Mapping[str, Any]) -> str:
    scientific = _without_locators(component)
    scientific.pop("componentId", None)
    return sha256_bytes(canonical_json_bytes(scientific))


def _component_id(component: Mapping[str, Any]) -> str:
    component_type = re.sub(r"[^a-z0-9]+", "-", str(component["componentType"]).casefold()).strip("-")
    return f"sports-phase4-component:{component_type}:sha256:{semantic_component_sha(component)}"


def semantic_study_core_sha(payload: Mapping[str, Any]) -> str:
    projection = copy.deepcopy(dict(payload))
    projection.pop("studyId", None)
    projection.pop("studySha", None)
    projection.pop("artifacts", None)
    projection.pop("graph", None)
    identity = dict(projection.get("studyIdentity") or {})
    identity.pop("coreSha", None)
    projection["studyIdentity"] = identity
    projection = _without_locators(projection)
    core = {
        "schemaVersion": STUDY_CORE_SCHEMA_VERSION,
        "coreProjection": projection,
    }
    return sha256_bytes(canonical_json_bytes(core))


def semantic_study_sha(payload: Mapping[str, Any]) -> str:
    semantic = copy.deepcopy(dict(payload))
    semantic.pop("studyId", None)
    semantic.pop("studySha", None)
    return sha256_bytes(canonical_json_bytes(semantic))


def _candidate_ids(value: Any, *, label: str) -> list[str]:
    if type(value) is list:
        result: list[str] = []
        for index, item in enumerate(value):
            candidate = _mapping(item, label=f"{label}[{index}]")
            result.append(_nonblank(candidate.get("candidateId"), label=f"{label}[{index}].candidateId"))
        return result
    if type(value) is dict:
        result = []
        for key, item in value.items():
            candidate_id = _nonblank(key, label=f"{label} key")
            if isinstance(item, Mapping) and "candidateId" in item and item["candidateId"] != candidate_id:
                raise SportsPhase4RegistryError(f"{label}.{candidate_id} candidate identity differs")
            result.append(candidate_id)
        return result
    raise SportsPhase4RegistryError(f"{label} must be an array or object")


def _candidate_records(value: Any, *, label: str) -> dict[str, dict[str, Any]]:
    if type(value) is list:
        records: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(value):
            record = _mapping(item, label=f"{label}[{index}]")
            candidate_id = _nonblank(record.get("candidateId"), label=f"{label}[{index}].candidateId")
            if candidate_id in records:
                raise SportsPhase4RegistryError(f"{label} candidate identities must be unique")
            records[candidate_id] = record
        return records
    if type(value) is dict:
        records = {}
        for key, item in value.items():
            record = _mapping(item, label=f"{label}.{key}")
            candidate_id = _nonblank(record.get("candidateId", key), label=f"{label}.{key}.candidateId")
            if candidate_id != key:
                raise SportsPhase4RegistryError(f"{label}.{key} candidate identity differs")
            records[candidate_id] = record
        return records
    raise SportsPhase4RegistryError(f"{label} must be an array or object")


def _metric_value(metrics: Mapping[str, Any], key: str, *, label: str) -> float:
    value = metrics.get(key)
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(float(value)):
        raise SportsPhase4RegistryError(f"{label}.{key} must be finite")
    return float(value)


def _validate_dynamic_metrics(metrics: Any, *, rows: int, label: str) -> dict[str, Any]:
    record = _mapping(metrics, label=label)
    try:
        _validate_phase3_metrics(record, expected_rows=rows, label=label)
    except SportsPARegistryError as exc:
        raise SportsPhase4RegistryError(
            f"{label} differs from the frozen multiclass metric contract: {exc}"
        ) from exc
    _scan_public_safety(record, path=label)
    return record


def _folds_by_season(
    candidate: Mapping[str, Any],
    *,
    candidate_id: str,
) -> dict[int, dict[str, Any]]:
    folds = _list(candidate.get("foldMetrics"), label=f"candidate {candidate_id}.foldMetrics")
    output: dict[int, dict[str, Any]] = {}
    for index, raw in enumerate(folds):
        fold = _mapping(raw, label=f"candidate {candidate_id}.foldMetrics[{index}]")
        season = fold.get("validationSeason")
        if season not in (2024, 2025) or season in output:
            raise SportsPhase4RegistryError(f"candidate {candidate_id} fold seasons differ")
        expected = _DYNAMIC_FOLD_AUTHORITIES[int(season)]
        if (
            fold.get("foldId") != expected["foldId"]
            or fold.get("trainingSeasons") != expected["trainingSeasons"]
        ):
            raise SportsPhase4RegistryError(f"candidate {candidate_id} fold training authority differs")
        training_rows = fold.get("trainingRows")
        if training_rows != expected["trainingRows"]:
            raise SportsPhase4RegistryError(
                f"candidate {candidate_id} trainingRows differ from the frozen fold"
            )
        rows = fold.get("validationRows")
        if rows != expected["validationRows"]:
            raise SportsPhase4RegistryError(f"candidate {candidate_id} validationRows differ from the frozen fold")
        if fold.get("status") not in (None, "COMPLETE"):
            raise SportsPhase4RegistryError(f"candidate {candidate_id} fold is not complete")
        _validate_dynamic_metrics(
            fold.get("metrics"),
            rows=rows,
            label=f"candidate {candidate_id} {season} metrics",
        )
        output[season] = fold
    if set(output) != {2024, 2025}:
        raise SportsPhase4RegistryError(f"candidate {candidate_id} omits a frozen fold")
    return output


def _metrics_nonworse(scaled: Mapping[str, Any], raw: Mapping[str, Any]) -> bool:
    tolerance = 1e-10
    return (
        _metric_value(scaled, "logLoss", label="scaled metrics")
        <= _metric_value(raw, "logLoss", label="raw metrics") + tolerance
        and _metric_value(scaled, "brierScore", label="scaled metrics")
        <= _metric_value(raw, "brierScore", label="raw metrics") + tolerance
    )


def _linear_percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    fraction = position - lower_index
    return ordered[lower_index] + fraction * (
        ordered[upper_index] - ordered[lower_index]
    )


def _validate_replicate_statistics(
    replicates_value: Any,
    *,
    expected_count: int,
    standard_error: Any,
    lower: Any,
    upper: Any,
    label: str,
    mean: Any | None = None,
    probability_better: Any | None = None,
) -> None:
    replicates = _list(replicates_value, label=f"{label}.replicateDifferences")
    if len(replicates) != expected_count:
        raise SportsPhase4RegistryError(f"{label} replicate count differs")
    parsed = [
        _metric_value({"value": value}, "value", label=f"{label}[{index}]")
        for index, value in enumerate(replicates)
    ]
    observed_mean = math.fsum(parsed) / len(parsed)
    observed_standard_error = math.sqrt(
        math.fsum((value - observed_mean) ** 2 for value in parsed)
        / (len(parsed) - 1)
    )
    observed_lower = _linear_percentile(parsed, 0.025)
    observed_upper = _linear_percentile(parsed, 0.975)
    _close(standard_error, observed_standard_error, label=f"{label}.standardError")
    _close(lower, observed_lower, label=f"{label}.interval.lower")
    _close(upper, observed_upper, label=f"{label}.interval.upper")
    if mean is not None:
        _close(mean, observed_mean, label=f"{label}.bootstrapMean")
    if probability_better is not None:
        observed_probability = sum(value < 0.0 for value in parsed) / len(parsed)
        _close(
            probability_better,
            observed_probability,
            label=f"{label}.probabilitySelectedBetter",
        )


def _validate_dynamic_scientific_evidence(component: Mapping[str, Any]) -> None:
    # The runner validator is the first frozen boundary.  Registry component
    # identities intentionally omit artifact locators, so provide the runner's
    # full-evidence identity only to its callback and then apply the stronger
    # registry identity check independently in _validate_component.
    callback_component = copy.deepcopy(dict(component))
    callback_core = dict(callback_component)
    callback_core.pop("componentId", None)
    callback_component["componentId"] = (
        "sports-phase4-component:dynamic-player-state:sha256:"
        + sha256_bytes(canonical_json_bytes(callback_core))
    )
    try:
        validate_dynamic_component_evidence(callback_component)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise SportsPhase4RegistryError(
            f"Dynamic component evidence differs from its frozen runner contract: {exc}"
        ) from exc

    if type(component["candidates"]) is not list or [
        item.get("candidateId") if isinstance(item, Mapping) else None
        for item in component["candidates"]
    ] != ["D0", "D1", "D2", "D3", "D4"]:
        raise SportsPhase4RegistryError("Dynamic candidate order differs")
    candidates = _candidate_records(component["candidates"], label="dynamic candidates")
    if set(candidates) != {"D0", "D1", "D2", "D3", "D4"}:
        raise SportsPhase4RegistryError("Dynamic candidate identities differ")
    folds = {
        candidate_id: _folds_by_season(candidate, candidate_id=candidate_id)
        for candidate_id, candidate in candidates.items()
    }
    ordinals: dict[str, int] = {}
    for expected_ordinal, candidate_id in enumerate(("D0", "D1", "D2", "D3", "D4")):
        ordinal = candidates[candidate_id].get("ordinal")
        if ordinal != expected_ordinal:
            raise SportsPhase4RegistryError("Dynamic candidate ordinals differ")
        ordinals[candidate_id] = ordinal
    d0_config = _mapping(candidates["D0"].get("config"), label="D0 config")
    source_shas = _mapping(d0_config.get("sourceArtifactShas"), label="D0 sourceArtifactShas")
    if source_shas != {
        "2024": PHASE3_FOLD_2024_PREDICTION_SHA,
        "2025": PHASE3_FOLD_2025_PREDICTION_SHA,
    } or d0_config.get("refit") is not False or d0_config.get("relabelled") is not False:
        raise SportsPhase4RegistryError("D0 does not repeat the frozen Phase 3 prediction authorities")

    descriptor = _mapping(component["descriptor"], label="dynamic descriptor")
    tuning_authority = _mapping(descriptor.get("tuning"), label="dynamic descriptor tuning")
    logistic_tuning = _mapping(
        tuning_authority.get("logisticByCandidate"),
        label="dynamic descriptor logistic tuning",
    )
    if set(logistic_tuning) != {"D1", "D2", "D3", "D4"}:
        raise SportsPhase4RegistryError("Dynamic logistic tuning inventory differs")
    for candidate_id in ("D1", "D2", "D3", "D4"):
        candidate = candidates[candidate_id]
        tuning = _list(logistic_tuning[candidate_id], label=f"{candidate_id} inner-2023 tuning")
        if [row.get("C") for row in tuning if isinstance(row, Mapping)] != [0.05, 0.2, 1.0]:
            raise SportsPhase4RegistryError(f"{candidate_id} inner-2023 tuning grid differs")
        config = _mapping(candidate.get("config"), label=f"{candidate_id}.config")
        if config.get("selectedC") not in (0.05, 0.2, 1.0):
            raise SportsPhase4RegistryError(f"{candidate_id} selected C differs")
        winner = min(
            tuning,
            key=lambda row: (
                _metric_value(row["metrics"], "logLoss", label=f"{candidate_id} tuning"),
                _metric_value(row["metrics"], "brierScore", label=f"{candidate_id} tuning"),
                float(row["C"]),
            ),
        )
        if float(config["selectedC"]) != float(winner["C"]):
            raise SportsPhase4RegistryError(f"{candidate_id} selected C does not match inner-2023 evidence")
    expected_selected = min(
        ("D1", "D2", "D3", "D4"),
        key=lambda candidate_id: (
            _metric_value(folds[candidate_id][2024]["metrics"], "logLoss", label=f"{candidate_id} 2024"),
            _metric_value(folds[candidate_id][2024]["metrics"], "brierScore", label=f"{candidate_id} 2024"),
            ordinals[candidate_id],
        ),
    )
    selected_id = _selected_candidate_id(component["selected"], label="dynamic selected")
    if selected_id != expected_selected:
        raise SportsPhase4RegistryError("Dynamic selection differs from the frozen 2024-only policy")
    selected = _mapping(component["selected"], label="dynamic selected")
    if (
        selected.get("selectionSeason") != 2024
        or selected.get("selectionMetric") != "RAW_2024_LOG_LOSS_THEN_BRIER_THEN_ORDINAL"
        or selected.get("probabilityVariant") != "RAW"
    ):
        raise SportsPhase4RegistryError("Dynamic selection policy differs")

    common_folds = _list(component["folds"], label="dynamic common folds")
    if len(common_folds) != 2:
        raise SportsPhase4RegistryError("Dynamic common folds differ")
    common_by_season: dict[int, dict[str, Any]] = {}
    for raw_fold in common_folds:
        fold = _mapping(raw_fold, label="dynamic common fold")
        season = fold.get("validationSeason")
        if season not in (2024, 2025) or season in common_by_season:
            raise SportsPhase4RegistryError("Dynamic common fold seasons differ")
        selected_fold = folds[selected_id][season]
        d0_artifact_id = _nonblank(
            fold.get("d0SourceArtifactId"), label=f"dynamic {season} D0 artifact ID"
        )
        if (
            fold.get("foldId") != selected_fold.get("foldId")
            or fold.get("status") != "COMPLETE"
            or fold.get("trainingSeasons") != selected_fold.get("trainingSeasons")
            or fold.get("trainingRows") != selected_fold.get("trainingRows")
            or fold.get("validationRows") != selected_fold.get("validationRows")
            or fold.get("candidateIds") != ["D0", "D1", "D2", "D3", "D4"]
            or d0_artifact_id
            != _PHASE3_D0_ARTIFACT_AUTHORITIES[season]["artifactId"]
            or fold.get("selectionUse")
            != ("DYNAMIC_SELECTION" if season == 2024 else "FINAL_EVALUATION_ONLY")
        ):
            raise SportsPhase4RegistryError("Dynamic common fold authority differs")
        common_by_season[season] = fold
    if set(common_by_season) != {2024, 2025}:
        raise SportsPhase4RegistryError("Dynamic common folds omit a frozen season")

    metrics_summary = _mapping(component["metrics"], label="dynamic metrics summary")
    _exact_keys(
        metrics_summary,
        {
            "schemaVersion",
            "classOrder",
            "governingProbabilityVariant",
            "selectedCandidateId",
            "baselineCandidateId",
            "statePosteriorPredictive",
            "byCandidate",
        },
        label="dynamic metrics summary",
    )
    if (
        metrics_summary["schemaVersion"] != "MLB_DYNAMIC_PLAYER_STATE_TRAINING_V1"
        or metrics_summary["classOrder"] != list(PA_CLASS_ORDER)
        or metrics_summary["governingProbabilityVariant"] != "RAW"
        or metrics_summary["selectedCandidateId"] != selected_id
        or metrics_summary["baselineCandidateId"] != "D0"
    ):
        raise SportsPhase4RegistryError("Dynamic metrics summary authority differs")
    by_candidate = _list(metrics_summary["byCandidate"], label="dynamic metrics byCandidate")
    expected_summary = [
        {"candidateId": candidate_id, "foldMetrics": candidates[candidate_id]["foldMetrics"]}
        for candidate_id in ("D0", "D1", "D2", "D3", "D4")
    ]
    if by_candidate != expected_summary:
        raise SportsPhase4RegistryError("Dynamic metrics summary differs from candidate folds")

    calibration = _mapping(component["calibration"], label="dynamic calibration")
    fitted_temperature = calibration.get("fittedTemperature")
    if (
        calibration.get("schemaVersion") != "MLB_DYNAMIC_PLAYER_STATE_CALIBRATION_V1"
        or calibration.get("method") != "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES"
        or calibration.get("candidateId") != selected_id
        or calibration.get("fitSeason") != 2024
        or calibration.get("applicationSeason") != 2025
        or isinstance(fitted_temperature, bool)
        or type(fitted_temperature) not in (int, float)
        or not math.isfinite(float(fitted_temperature))
        or float(fitted_temperature) <= 0.0
        or calibration.get("rawAndScaledPreserved") is not True
    ):
        raise SportsPhase4RegistryError("Dynamic calibration authority differs")
    raw = _mapping(calibration.get("raw"), label="dynamic calibration raw")
    scaled = _mapping(calibration.get("scaled"), label="dynamic calibration scaled")
    final = _mapping(calibration.get("final"), label="dynamic calibration final")
    if set(raw) != {"2024", "2025"} or set(scaled) != set(raw) or set(final) != set(raw):
        raise SportsPhase4RegistryError("Dynamic calibration fold inventory differs")
    for season in (2024, 2025):
        key = str(season)
        if raw.get(key) != folds[selected_id][season]["metrics"]:
            raise SportsPhase4RegistryError("Dynamic raw calibration metrics differ from folds")
        rows = int(folds[selected_id][season]["validationRows"])
        _validate_dynamic_metrics(scaled.get(key), rows=rows, label=f"dynamic scaled {season}")
        _validate_dynamic_metrics(final.get(key), rows=rows, label=f"dynamic final {season}")
    eligible_2024 = _metrics_nonworse(scaled["2024"], raw["2024"])
    nonworse_2025 = _metrics_nonworse(scaled["2025"], raw["2025"])
    retained = eligible_2024 and nonworse_2025
    if (
        calibration.get("eligibleOn2024") is not eligible_2024
        or calibration.get("nonWorseningOn2025") is not nonworse_2025
        or calibration.get("retainedAfter2025Gate") is not retained
        or calibration.get("finalVariant") != ("SCALED" if retained else "RAW")
    ):
        raise SportsPhase4RegistryError("Dynamic calibration retention decision differs")
    expected_final = scaled if retained else raw
    if final != expected_final:
        raise SportsPhase4RegistryError("Dynamic final metrics differ from the frozen calibration gate")

    bootstrap = _list(component["bootstrap"], label="dynamic bootstrap")
    by_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    for row in bootstrap:
        item = _mapping(row, label="dynamic bootstrap item")
        _exact_keys(
            item,
            {
                "schemaVersion",
                "candidateId",
                "baselineCandidateId",
                "foldId",
                "validationSeason",
                "probabilityVariant",
                "clusterUnit",
                "resamples",
                "seed",
                "evidence",
            },
            label="dynamic bootstrap item",
        )
        key = (item.get("validationSeason"), item.get("probabilityVariant"))
        if key in by_key or key[0] not in (2024, 2025) or key[1] not in ("RAW", "FINAL"):
            raise SportsPhase4RegistryError("Dynamic bootstrap fold/variant authority differs")
        if (
            item.get("schemaVersion") != "MLB_DYNAMIC_PLAYER_STATE_BOOTSTRAP_V1"
            or item.get("candidateId") != selected_id
            or item.get("baselineCandidateId") != "D0"
            or item.get("foldId") != common_by_season[int(key[0])]["foldId"]
            or item.get("clusterUnit") != "game_id"
            or item.get("resamples") != 500
            or item.get("seed") != DYNAMIC_BOOTSTRAP_SEED
        ):
            raise SportsPhase4RegistryError("Dynamic bootstrap policy differs")
        evidence = _mapping(item.get("evidence"), label="dynamic bootstrap evidence")
        _exact_keys(
            evidence,
            {
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
            },
            label="dynamic bootstrap evidence",
        )
        expected_cluster_count = {2024: 2429, 2025: 2430}[int(key[0])]
        if (
            evidence.get("schemaVersion") != "MLB_PA_GAME_CLUSTER_BOOTSTRAP_V1"
            or evidence.get("classOrder") != list(PA_CLASS_ORDER)
            or evidence.get("differenceConvention")
            != "SELECTED_MINUS_COMPARATOR_NEGATIVE_FAVORS_SELECTED"
            or evidence.get("resamplingUnit") != "game_id"
            or evidence.get("resamplingMethod")
            != "EQUAL_PROBABILITY_CLUSTERS_WITH_REPLACEMENT"
            or evidence.get("rowsSampledIndependently") is not False
            or evidence.get("rowCount") != folds[selected_id][int(key[0])]["validationRows"]
            or evidence.get("clusterCount") != expected_cluster_count
            or evidence.get("clusterDrawsPerReplicate") != expected_cluster_count
            or evidence.get("resampleCount") != 500
            or evidence.get("seed") != DYNAMIC_BOOTSTRAP_SEED
            or evidence.get("confidenceLevel") != 0.95
        ):
            raise SportsPhase4RegistryError("Dynamic bootstrap evidence policy differs")
        selected_metrics = raw[str(key[0])] if key[1] == "RAW" else final[str(key[0])]
        baseline_metrics = folds["D0"][int(key[0])]["metrics"]
        for metric_name, evidence_key in (("logLoss", "logLossDifference"), ("brierScore", "brierScoreDifference")):
            summary = _mapping(evidence.get(evidence_key), label=f"dynamic bootstrap {evidence_key}")
            _exact_keys(
                summary,
                {
                    "pointEstimate",
                    "bootstrapMean",
                    "bootstrapStandardError",
                    "percentileInterval",
                    "probabilitySelectedBetter",
                    "replicateDifferences",
                },
                label=f"dynamic bootstrap {evidence_key}",
            )
            expected_point = _metric_value(selected_metrics, metric_name, label="selected") - _metric_value(baseline_metrics, metric_name, label="baseline")
            if not math.isclose(_metric_value(summary, "pointEstimate", label="bootstrap"), expected_point, rel_tol=0.0, abs_tol=1e-10):
                raise SportsPhase4RegistryError("Dynamic bootstrap point estimate differs from fold metrics")
            interval = _mapping(
                summary.get("percentileInterval"),
                label=f"dynamic bootstrap {evidence_key} interval",
            )
            _exact_keys(
                interval,
                {"confidenceLevel", "lower", "upper"},
                label=f"dynamic bootstrap {evidence_key} interval",
            )
            lower = _metric_value(interval, "lower", label="bootstrap interval")
            upper = _metric_value(interval, "upper", label="bootstrap interval")
            if interval.get("confidenceLevel") != 0.95 or lower > upper:
                raise SportsPhase4RegistryError("Dynamic bootstrap interval differs")
            _validate_replicate_statistics(
                summary["replicateDifferences"],
                expected_count=500,
                standard_error=summary["bootstrapStandardError"],
                lower=lower,
                upper=upper,
                mean=summary["bootstrapMean"],
                probability_better=summary["probabilitySelectedBetter"],
                label=f"dynamic bootstrap {evidence_key}",
            )
        by_key[key] = item
    if set(by_key) != {(2024, "RAW"), (2024, "FINAL"), (2025, "RAW"), (2025, "FINAL")}:
        raise SportsPhase4RegistryError("Dynamic bootstrap evidence is incomplete")

    coverage = _mapping(component["coverage"], label="dynamic coverage")
    expected_prefixes = {
        "D1": ["batter_b"],
        "D2": ["pitcher_b"],
        "D3": ["batter_b", "pitcher_b"],
        "D4": ["batter_c", "pitcher_c"],
    }[selected_id]
    if (
        coverage.get("schemaVersion") != "MLB_DYNAMIC_PLAYER_STATE_COVERAGE_V1"
        or coverage.get("selectedCandidateId") != selected_id
        or coverage.get("selectedStatePrefixes") != expected_prefixes
    ):
        raise SportsPhase4RegistryError("Dynamic coverage selected candidate differs")
    role_rows = _list(coverage.get("roleStateCoverage"), label="dynamic roleStateCoverage")
    subgroup_rows = _list(coverage.get("subgroups"), label="dynamic subgroups")
    for season in (2024, 2025):
        expected_rows = folds[selected_id][season]["validationRows"]
        season_roles = [item for item in role_rows if isinstance(item, Mapping) and item.get("validationSeason") == season]
        if (
            [item.get("statePrefix") for item in season_roles] != expected_prefixes
            or any(item.get("rowCount") != expected_rows for item in season_roles)
        ):
            raise SportsPhase4RegistryError("Dynamic role/state coverage does not reconcile")
        season_groups = [item for item in subgroup_rows if isinstance(item, Mapping) and item.get("validationSeason") == season]
        if {item.get("subgroup") for item in season_groups} != {
            "MISSING_HISTORY",
            "HAS_HISTORY_ESS_LT_100",
            "HAS_HISTORY_ESS_100_TO_299",
            "HAS_HISTORY_ESS_GE_300",
        } or sum(int(item.get("rowCount", -1)) for item in season_groups) != expected_rows:
            raise SportsPhase4RegistryError("Dynamic subgroup coverage does not partition its fold")

    raw_loss_rule = all(
        _metric_value(raw[str(season)], "logLoss", label="dynamic raw")
        < _metric_value(folds["D0"][season]["metrics"], "logLoss", label="D0")
        - DYNAMIC_DECISION_TOLERANCE
        and _metric_value(raw[str(season)], "brierScore", label="dynamic raw")
        <= _metric_value(folds["D0"][season]["metrics"], "brierScore", label="D0")
        + DYNAMIC_DECISION_TOLERANCE
        for season in (2024, 2025)
    )
    calibration_defects = {
        str(season): {
            "topLabelEceExcess": _metric_value(
                raw[str(season)], "topLabelEce", label="dynamic raw"
            )
            - _metric_value(
                folds["D0"][season]["metrics"], "topLabelEce", label="D0"
            ),
            "classwiseEceExcess": {
                class_name: _metric_value(
                    _mapping(raw[str(season)]["classwiseEce"], label="raw classwise ECE"),
                    class_name,
                    label="raw classwise ECE",
                )
                - _metric_value(
                    _mapping(
                        folds["D0"][season]["metrics"]["classwiseEce"],
                        label="D0 classwise ECE",
                    ),
                    class_name,
                    label="D0 classwise ECE",
                )
                for class_name in PA_CLASS_ORDER
            },
        }
        for season in (2024, 2025)
    }
    no_calibration_defect = all(
        evidence["topLabelEceExcess"] <= CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE
        and all(
            value <= CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE
            for value in evidence["classwiseEceExcess"].values()
        )
        for evidence in calibration_defects.values()
    )
    worse = all(
        _metric_value(raw[str(season)], "logLoss", label="dynamic raw")
        > _metric_value(folds["D0"][season]["metrics"], "logLoss", label="D0")
        + DYNAMIC_DECISION_TOLERANCE
        and _metric_value(raw[str(season)], "brierScore", label="dynamic raw")
        > _metric_value(folds["D0"][season]["metrics"], "brierScore", label="D0")
        + DYNAMIC_DECISION_TOLERANCE
        for season in (2024, 2025)
    )
    expected_decision = (
        "DYNAMIC_STATE_RESEARCH_CHALLENGER"
        if raw_loss_rule and no_calibration_defect
        else "DYNAMIC_STATE_REJECTED"
        if worse
        else "DYNAMIC_STATE_RESEARCH_BASELINE"
    )
    decision = _mapping(component["decision"], label="dynamic decision")
    if (
        _decision_value(component, slot="dynamicState") != expected_decision
        or decision.get("selectedCandidateId") != selected_id
        or decision.get("decisionProbabilityVariant") != "RAW"
        or decision.get("rawLossRuleSatisfied") is not raw_loss_rule
        or decision.get("noMeaningfulRawCalibrationDefect") is not no_calibration_defect
        or decision.get("calibrationDefectTolerance")
        != CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE
        or decision.get("calibrationDefects") != calibration_defects
        or decision.get("bootstrapUsedAsDecisionGate") is not False
        or decision.get("bootstrapEvidenceRows") != 4
        or decision.get("scaledEvidenceCanEarnChallenger") is not False
        or decision.get("rejectionRuleSatisfied") is not worse
        or decision.get("researchOnly") is not True
        or decision.get("deploymentAuthorized") is not False
    ):
        raise SportsPhase4RegistryError("Dynamic terminal decision does not reconcile with frozen evidence")


def _participation_fold_metrics(
    candidate: Mapping[str, Any],
    *,
    candidate_id: str,
) -> dict[int, dict[str, Any] | None]:
    rows = _list(candidate.get("foldMetrics"), label=f"{candidate_id}.foldMetrics")
    if len(rows) != 2:
        raise SportsPhase4RegistryError(f"{candidate_id} must preserve two fold records")
    output: dict[int, dict[str, Any] | None] = {}
    for raw in rows:
        fold = _mapping(raw, label=f"{candidate_id} fold")
        _exact_keys(
            fold,
            {
                "foldId",
                "trainingSeasons",
                "validationSeason",
                "trainingRows",
                "validationRows",
                "status",
                "runtimeSeconds",
                "convergence",
                "metrics",
            },
            label=f"{candidate_id} fold",
        )
        season = fold.get("validationSeason")
        if season not in (2024, 2025) or season in output:
            raise SportsPhase4RegistryError(f"{candidate_id} fold seasons differ")
        expected_training = [2023] if season == 2024 else [2023, 2024]
        expected_fold_id = (
            "train-2023-validate-2024"
            if season == 2024
            else "train-through-2024-validate-2025"
        )
        fold_runtime = _metric_value(
            fold, "runtimeSeconds", label=f"{candidate_id} {season} fold"
        )
        convergence = _mapping(
            fold.get("convergence"), label=f"{candidate_id} {season} convergence"
        )
        _exact_keys(
            convergence,
            {"converged", "nIter", "maxIter"},
            label=f"{candidate_id} {season} convergence",
        )
        if (
            fold.get("foldId") != expected_fold_id
            or fold.get("trainingSeasons") != expected_training
            or type(fold.get("trainingRows")) is not int
            or fold["trainingRows"] <= 0
            or type(fold.get("validationRows")) is not int
            or fold["validationRows"] <= 0
            or fold_runtime < 0.0
        ):
            raise SportsPhase4RegistryError(f"{candidate_id} fold temporal rows differ")
        status = fold.get("status")
        metrics = fold.get("metrics")
        if status == "COMPLETE":
            if convergence.get("converged") is not True:
                raise SportsPhase4RegistryError(
                    f"{candidate_id} {season} completed fold did not converge"
                )
            for key in ("nIter", "maxIter"):
                value = convergence.get(key)
                if value is not None and (type(value) is not int or value <= 0):
                    raise SportsPhase4RegistryError(
                        f"{candidate_id} {season} convergence {key} differs"
                    )
            record = _mapping(metrics, label=f"{candidate_id} {season} metrics")
            row_count = record.get("rowCount")
            if (
                record.get("schemaVersion") != "MLB_PARTICIPATION_METRICS_V1"
                or type(row_count) is not int
                or row_count != fold["validationRows"]
            ):
                raise SportsPhase4RegistryError(f"{candidate_id} {season} metric rowCount must be positive")
            _scan_public_safety(record, path=f"{candidate_id}.{season}.metrics")
            output[season] = record
        elif (
            status == "NOT_RUN_BY_POLICY"
            and metrics is None
            and convergence
            == {"converged": None, "nIter": None, "maxIter": None}
        ):
            output[season] = None
        else:
            raise SportsPhase4RegistryError(f"{candidate_id} fold status and metrics disagree")
    if set(output) != {2024, 2025}:
        raise SportsPhase4RegistryError(f"{candidate_id} fold evidence is incomplete")
    return output


def _close(actual: Any, expected: float, *, label: str) -> None:
    if isinstance(actual, bool) or type(actual) not in (int, float) or not math.isfinite(float(actual)):
        raise SportsPhase4RegistryError(f"{label} must be finite")
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-10):
        raise SportsPhase4RegistryError(f"{label} does not reconcile")


def _validate_binary_calibration(
    value: Any,
    *,
    rows: int,
    label: str,
) -> None:
    calibration = _mapping(value, label=label)
    # Governed equal-count calibration (MLB_PARTICIPATION_BINARY_CALIBRATION_V2): deciles are
    # equal-count array splits over probability-then-governed-row-id order, so bins carry
    # sorted start/end offsets and observed min/max probability instead of fixed equal-width
    # bounds. Validate that authoritative schema faithfully.
    _exact_keys(
        calibration,
        {
            "schemaVersion",
            "rowCount",
            "binCount",
            "binningPolicy",
            "sortPolicy",
            "rowsAssignedExactlyOnce",
            "bins",
            "expectedCalibrationError",
            "acceptableThreshold",
            "allBinsFiniteAndNonempty",
            "acceptable",
        },
        label=label,
    )
    bins = _list(calibration.get("bins"), label=f"{label}.bins")
    if (
        calibration.get("schemaVersion")
        != "MLB_PARTICIPATION_BINARY_CALIBRATION_V2"
        or calibration.get("rowCount") != rows
        or calibration.get("binCount") != 10
        or len(bins) != 10
        or calibration.get("acceptableThreshold") != 0.05
        or calibration.get("binningPolicy") != "EQUAL_COUNT_NUMPY_ARRAY_SPLIT"
        or calibration.get("sortPolicy") != "PROBABILITY_ASC_THEN_GOVERNED_ROW_ID_ASC"
        or calibration.get("rowsAssignedExactlyOnce") is not True
    ):
        raise SportsPhase4RegistryError(f"{label} authority differs")
    total = 0
    weighted_gap = 0.0
    all_finite_nonempty = True
    for index, raw_bin in enumerate(bins):
        item = _mapping(raw_bin, label=f"{label}.bins[{index}]")
        _exact_keys(
            item,
            {
                "binIndex",
                "sortedStartInclusive",
                "sortedEndExclusive",
                "count",
                "minimumProbability",
                "maximumProbability",
                "meanProbability",
                "observedRate",
                "absoluteGap",
            },
            label=f"{label}.bins[{index}]",
        )
        count = item.get("count")
        # Equal-count bins tile the sorted rows contiguously: each bin starts where the
        # previous ended and spans exactly its own count.
        if (
            item.get("binIndex") != index
            or item.get("sortedStartInclusive") != total
            or type(count) is not int
            or count < 0
            or item.get("sortedEndExclusive") != total + count
        ):
            raise SportsPhase4RegistryError(f"{label} bin authority differs")
        total += count
        if count == 0:
            if any(
                item.get(key) is not None
                for key in (
                    "minimumProbability",
                    "maximumProbability",
                    "meanProbability",
                    "observedRate",
                    "absoluteGap",
                )
            ):
                raise SportsPhase4RegistryError(f"{label} empty bin differs")
            all_finite_nonempty = False
            continue
        minimum_probability = _metric_value(item, "minimumProbability", label=label)
        maximum_probability = _metric_value(item, "maximumProbability", label=label)
        mean_probability = _metric_value(item, "meanProbability", label=label)
        observed_rate = _metric_value(item, "observedRate", label=label)
        absolute_gap = _metric_value(item, "absoluteGap", label=label)
        if (
            not 0.0 <= minimum_probability <= maximum_probability <= 1.0
            or not minimum_probability <= mean_probability <= maximum_probability
            or not 0.0 <= observed_rate <= 1.0
            or not math.isclose(
                absolute_gap,
                abs(mean_probability - observed_rate),
                rel_tol=0.0,
                abs_tol=1e-10,
            )
        ):
            raise SportsPhase4RegistryError(f"{label} bin values differ")
        weighted_gap += count * absolute_gap
    if total != rows:
        raise SportsPhase4RegistryError(f"{label} bin counts do not reconcile")
    expected_ece = weighted_gap / rows
    _close(
        calibration.get("expectedCalibrationError"),
        expected_ece,
        label=f"{label}.expectedCalibrationError",
    )
    expected_acceptable = expected_ece <= 0.05 and all_finite_nonempty
    if (
        calibration.get("allBinsFiniteAndNonempty") is not all_finite_nonempty
        or calibration.get("acceptable") is not expected_acceptable
    ):
        raise SportsPhase4RegistryError(f"{label} terminal calibration flags differ")


def _validate_participation_metrics(
    metrics: Mapping[str, Any],
    *,
    slot: str,
    label: str,
) -> None:
    rows = int(metrics["rowCount"])
    if slot in ("lineup", "bullpenUsage"):
        binary_keys = {
            "schemaVersion",
            "rowCount",
            "positiveCount",
            "negativeCount",
            "binaryLogLoss",
            "brierScore",
            "averagePrecision",
            "calibration",
            "topLabelCalibration",
        }
        extra_keys = (
            {
                "poolCoverage",
                "uncoveredPositiveCount",
                "totalActualPositiveCount",
                "teamGameCount",
                "completeLineupEligibleTeamGameCount",
                "completeLineupEligibleGameCount",
                "orderMetricGameCount",
                "top9Recall",
                "topNinePrecision",
                "topNineF1",
                "completeLineupRate",
                "completeLineupRecoveryRate",
                "exactLineupRate",
                "exactOrderRate",
                "battingOrderMae",
                "exactBattingPositionRate",
                "exactBattingPositionCount",
                "exactBattingPositionEligibleCount",
                "earlySeasonTop9Recall",
                "laterSeasonTop9Recall",
                "stratifiedMetrics",
                "teamGames",
            }
            if slot == "lineup"
            else {
                "poolCoverage",
                "uncoveredPositiveCount",
                "totalActualPositiveCount",
                "teamGameCount",
                "teamGameSetRecall",
                "teamGameSetJaccard",
                "top3Recall",
                "top5Recall",
                "relieverCountMae",
                "expectedRelieverCountMae",
                "zeroRelieverAccuracy",
                "conditionalBfpMae",
                "conditionalOutsMae",
                "earlySeasonSetRecall",
                "recentUseStratifiedMetrics",
            }
        )
        _exact_keys(metrics, binary_keys | extra_keys, label=label)
        log_loss = _metric_value(metrics, "binaryLogLoss", label=label)
        brier = _metric_value(metrics, "brierScore", label=label)
        coverage = _metric_value(metrics, "poolCoverage", label=label)
        average_precision = _metric_value(metrics, "averagePrecision", label=label)
        positive = metrics.get("positiveCount")
        negative = metrics.get("negativeCount")
        if (
            type(positive) is not int
            or positive < 0
            or type(negative) is not int
            or negative < 0
            or positive + negative != rows
            or log_loss < 0.0
            or not 0.0 <= brier <= 1.0
            or not 0.0 <= average_precision <= 1.0
            or not 0.0 <= coverage <= 1.0
        ):
            raise SportsPhase4RegistryError(f"{label} probability metric range differs")
        _validate_binary_calibration(
            metrics.get("calibration"), rows=rows, label=f"{label}.calibration"
        )
        _validate_binary_calibration(
            metrics.get("topLabelCalibration"),
            rows=rows,
            label=f"{label}.topLabelCalibration",
        )
        if slot == "lineup":
            team_games = _list(metrics["teamGames"], label=f"{label}.teamGames")
            if len(team_games) != metrics.get("teamGameCount"):
                raise SportsPhase4RegistryError(f"{label} team-game count differs")
            hits = 0
            selected_total = 0
            covered_actual = 0
            eligible = complete = recovered = exact_sets = exact_orders = 0
            observed_keys: set[tuple[str, str]] = set()
            # exactLineupRate / exactOrderRate are governed per-GAME (both teams exact among
            # fully-eligible games), unlike the per-team-game complete/recovery rates, so track
            # eligibility and exact flags grouped by game to reconcile them faithfully.
            game_eligible: dict[str, list[bool]] = defaultdict(list)
            game_exact_sets: dict[str, list[bool]] = defaultdict(list)
            game_exact_orders: dict[str, list[bool]] = defaultdict(list)
            for index, raw_game in enumerate(team_games):
                game = _mapping(raw_game, label=f"{label}.teamGames[{index}]")
                _exact_keys(
                    game,
                    {
                        "gameId",
                        "teamId",
                        "candidateCount",
                        "selectedCount",
                        "coveredActualCount",
                        "topNineHits",
                        "completeLineupEligible",
                        "exactSet",
                        "exactOrder",
                        "exactBattingPositionCount",
                        "exactBattingPositionHits",
                    },
                    label=f"{label}.teamGames[{index}]",
                )
                identity = (
                    _nonblank(game["gameId"], label="lineup gameId"),
                    _nonblank(game["teamId"], label="lineup teamId"),
                )
                if identity in observed_keys:
                    raise SportsPhase4RegistryError(f"{label} team-game identity repeats")
                observed_keys.add(identity)
                counts = [game.get(key) for key in ("candidateCount", "selectedCount", "coveredActualCount", "topNineHits")]
                if (
                    any(type(value) is not int or value < 0 for value in counts)
                    or counts[1] > min(9, counts[0])
                    or counts[3] > min(counts[1], counts[2])
                    or type(game.get("completeLineupEligible")) is not bool
                ):
                    raise SportsPhase4RegistryError(f"{label} team-game counts differ")
                is_eligible = game["completeLineupEligible"]
                game_eligible[identity[0]].append(bool(is_eligible))
                if is_eligible:
                    if type(game.get("exactSet")) is not bool or type(game.get("exactOrder")) is not bool:
                        raise SportsPhase4RegistryError(f"{label} eligible exact flags differ")
                    eligible += 1
                    complete += int(counts[1] == 9)
                    recovered += int(counts[3] == 9)
                    exact_sets += int(game["exactSet"])
                    exact_orders += int(game["exactOrder"])
                    game_exact_sets[identity[0]].append(bool(game["exactSet"]))
                    game_exact_orders[identity[0]].append(bool(game["exactOrder"]))
                elif game.get("exactSet") is not None or game.get("exactOrder") is not None:
                    raise SportsPhase4RegistryError(f"{label} ineligible exact flags must be null")
                hits += counts[3]
                selected_total += counts[1]
                covered_actual += counts[2]
            total_actual = metrics.get("totalActualPositiveCount")
            uncovered = metrics.get("uncoveredPositiveCount")
            if (
                type(total_actual) is not int
                or total_actual <= 0
                or type(uncovered) is not int
                or uncovered < 0
                or covered_actual + uncovered != total_actual
                or eligible != metrics.get("completeLineupEligibleTeamGameCount")
            ):
                raise SportsPhase4RegistryError(f"{label} lineup denominators differ")
            precision = hits / selected_total if selected_total else 0.0
            recall = hits / total_actual
            f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
            for key, expected in (
                ("top9Recall", recall),
                ("topNinePrecision", precision),
                ("topNineF1", f1),
            ):
                _close(metrics.get(key), expected, label=f"{label}.{key}")
            # Per-team-game rates use the eligible team-game denominator.
            team_game_rates = {
                "completeLineupRate": complete,
                "completeLineupRecoveryRate": recovered,
            }
            for key, numerator in team_game_rates.items():
                expected = numerator / eligible if eligible else None
                if expected is None:
                    if metrics.get(key) is not None:
                        raise SportsPhase4RegistryError(f"{label}.{key} must be null")
                else:
                    _close(metrics.get(key), expected, label=f"{label}.{key}")
            # Per-game exact rates: a game is eligible only when all of its team-games are
            # eligible, and it is exact only when both teams are exact.
            eligible_games = [
                game_id
                for game_id, flags in game_eligible.items()
                if flags and all(flags)
            ]
            exact_set_games = sum(
                len(game_exact_sets[game_id]) == 2 and all(game_exact_sets[game_id])
                for game_id in eligible_games
            )
            exact_order_games = sum(
                len(game_exact_orders[game_id]) == 2 and all(game_exact_orders[game_id])
                for game_id in eligible_games
            )
            game_rates = {
                "exactLineupRate": exact_set_games,
                "exactOrderRate": exact_order_games,
            }
            for key, numerator in game_rates.items():
                expected = numerator / len(eligible_games) if eligible_games else None
                if expected is None:
                    if metrics.get(key) is not None:
                        raise SportsPhase4RegistryError(f"{label}.{key} must be null")
                else:
                    _close(metrics.get(key), expected, label=f"{label}.{key}")
        else:
            for key in (
                "teamGameSetRecall",
                "teamGameSetJaccard",
                "top3Recall",
                "top5Recall",
            ):
                value = _metric_value(metrics, key, label=label)
                if not 0.0 <= value <= 1.0:
                    raise SportsPhase4RegistryError(f"{label}.{key} differs")
            for key in ("relieverCountMae", "expectedRelieverCountMae"):
                if _metric_value(metrics, key, label=label) < 0.0:
                    raise SportsPhase4RegistryError(f"{label}.{key} differs")
            for key in (
                "zeroRelieverAccuracy",
                "conditionalBfpMae",
                "conditionalOutsMae",
                "earlySeasonSetRecall",
            ):
                value = metrics.get(key)
                if value is None:
                    continue
                number = _metric_value(metrics, key, label=label)
                upper = 1.0 if key in {"zeroRelieverAccuracy", "earlySeasonSetRecall"} else math.inf
                if not 0.0 <= number <= upper:
                    raise SportsPhase4RegistryError(f"{label}.{key} differs")
    else:
        _exact_keys(
            metrics,
            {
                "schemaVersion",
                "rowCount",
                "bfpMae",
                "bfpRmse",
                "bfpMedianAbsoluteError",
                "outsMae",
                "outsRmse",
                "outsMedianAbsoluteError",
                "reach15LogLoss",
                "reach15Brier",
                "reach15Calibration",
                "reach18LogLoss",
                "reach18Brier",
                "reach18Calibration",
                "reach21LogLoss",
                "reach21Brier",
                "reach21Calibration",
                "earlySeasonBfpMae",
                "priorStartHistoryCoverage",
                "historyStratifiedMetrics",
            },
            label=label,
        )
        for metric_name in (
            "bfpMae",
            "bfpRmse",
            "bfpMedianAbsoluteError",
            "outsMae",
            "outsRmse",
            "outsMedianAbsoluteError",
            "reach15LogLoss",
            "reach15Brier",
            "reach18LogLoss",
            "reach18Brier",
            "reach21LogLoss",
            "reach21Brier",
        ):
            if _metric_value(metrics, metric_name, label=label) < 0.0:
                raise SportsPhase4RegistryError(f"{label}.{metric_name} must be non-negative")
        if (
            _metric_value(metrics, "bfpRmse", label=label)
            + 1e-12
            < _metric_value(metrics, "bfpMae", label=label)
            or _metric_value(metrics, "outsRmse", label=label)
            + 1e-12
            < _metric_value(metrics, "outsMae", label=label)
        ):
            raise SportsPhase4RegistryError(f"{label} RMSE cannot be below MAE")
        if metrics.get("earlySeasonBfpMae") is not None and _metric_value(
            metrics, "earlySeasonBfpMae", label=label
        ) < 0.0:
            raise SportsPhase4RegistryError(f"{label}.earlySeasonBfpMae must be non-negative")
        for threshold in (15, 18, 21):
            _validate_binary_calibration(
                metrics.get(f"reach{threshold}Calibration"),
                rows=rows,
                label=f"{label}.reach{threshold}Calibration",
            )


def _validate_participation_scientific_evidence(
    component: Mapping[str, Any],
    *,
    slot: str,
) -> None:
    policy = COMPONENT_POLICIES[slot]
    descriptor = _mapping(component["descriptor"], label=f"{slot} descriptor")
    expected_descriptor_schema = {
        "lineup": "MLB_LINEUP_EXPERIMENT_DESCRIPTOR_V1",
        "starterDuration": "MLB_STARTER_DURATION_EXPERIMENT_DESCRIPTOR_V1",
        "bullpenUsage": "MLB_BULLPEN_EXPERIMENT_DESCRIPTOR_V1",
    }[slot]
    expected_selection_policy = {
        "lineup": "2024_BINARY_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
        "starterDuration": "2024_BFP_MAE_THEN_RMSE_THEN_ORDINAL",
        "bullpenUsage": "2024_RAW_BINARY_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
    }[slot]
    descriptor_keys = {
        "schemaVersion",
        "featureViewContentSha",
        "selectionPolicy",
        "inner2023Tuning",
        "componentRuntimeSeconds",
        "componentRuntimeLimitSeconds",
        "heartbeatMaximumIntervalSeconds",
    } | {
        "lineup": {"orderEstimator"},
        "starterDuration": {
            "conditioning",
            "primaryTarget",
            "secondaryTarget",
            "inningReach",
        },
        "bullpenUsage": {"componentGate"},
    }[slot]
    _exact_keys(descriptor, descriptor_keys, label=f"{slot} descriptor")
    runtime_seconds = _metric_value(
        descriptor,
        "componentRuntimeSeconds",
        label=f"{slot} descriptor",
    )
    expected_runtime_limit = 7200 if slot == "bullpenUsage" else 5400
    if (
        runtime_seconds < 0.0
        or runtime_seconds > expected_runtime_limit
        or descriptor.get("componentRuntimeLimitSeconds") != expected_runtime_limit
        or descriptor.get("heartbeatMaximumIntervalSeconds") != 30
    ):
        raise SportsPhase4RegistryError(f"{slot} runtime authority differs")
    _sha(
        descriptor.get("featureViewContentSha"),
        label=f"{slot} descriptor feature-view content SHA",
    )
    inner_tuning = _mapping(
        descriptor.get("inner2023Tuning"), label=f"{slot} inner-2023 tuning"
    )
    split = _mapping(inner_tuning.get("split"), label=f"{slot} tuning split")
    _exact_keys(
        split,
        {
            "schemaVersion",
            "season",
            "dateAtomic",
            "trainingRows",
            "validationRows",
            "lastTrainingDate",
            "firstValidationDate",
            "selectionUses2024Or2025",
        },
        label=f"{slot} tuning split",
    )
    if (
        descriptor.get("schemaVersion") != expected_descriptor_schema
        or descriptor.get("selectionPolicy") != expected_selection_policy
        or split.get("season") != 2023
        or split.get("dateAtomic") is not True
        or split.get("selectionUses2024Or2025") is not False
        or inner_tuning.get("selectionUses2024Or2025") is not False
        or split.get("schemaVersion")
        != "MLB_PARTICIPATION_DATE_ATOMIC_INNER_2023_V1"
        or type(split.get("trainingRows")) is not int
        or split["trainingRows"] <= 0
        or type(split.get("validationRows")) is not int
        or split["validationRows"] <= 0
        or type(split.get("lastTrainingDate")) is not str
        or type(split.get("firstValidationDate")) is not str
        or split["lastTrainingDate"] >= split["firstValidationDate"]
    ):
        raise SportsPhase4RegistryError(f"{slot} descriptor/tuning authority differs")
    if slot in ("lineup", "bullpenUsage"):
        _exact_keys(
            inner_tuning,
            {
                "schemaVersion",
                "grid",
                "candidates",
                "selectedC",
                "selectionMetric",
                "selectionUses2024Or2025",
                "split",
            },
            label=f"{slot} inner-2023 tuning",
        )
        tuning_candidates = _list(
            inner_tuning.get("candidates"), label=f"{slot} tuning candidates"
        )
        if (
            inner_tuning.get("schemaVersion")
            != "MLB_PARTICIPATION_LOGISTIC_TUNING_V1"
            or inner_tuning.get("grid") != [0.05, 0.2, 1.0]
            or inner_tuning.get("selectionMetric")
            != "LOG_LOSS_THEN_BRIER_THEN_GRID_ORDINAL"
            or len(tuning_candidates) != 3
        ):
            raise SportsPhase4RegistryError(f"{slot} tuning authority differs")
        for ordinal, (row, expected_c) in enumerate(
            zip(tuning_candidates, (0.05, 0.2, 1.0), strict=True)
        ):
            candidate = _mapping(row, label=f"{slot} tuning candidate")
            _exact_keys(
                candidate,
                {"C", "logLoss", "brierScore", "ordinal", "convergence"},
                label=f"{slot} tuning candidate",
            )
            convergence = _mapping(
                candidate["convergence"], label=f"{slot} tuning convergence"
            )
            _exact_keys(
                convergence,
                {"converged", "nIter"},
                label=f"{slot} tuning convergence",
            )
            if (
                candidate.get("C") != expected_c
                or candidate.get("ordinal") != ordinal
                or convergence.get("converged") is not True
                or type(convergence.get("nIter")) is not int
                or convergence["nIter"] <= 0
                or _metric_value(candidate, "logLoss", label=f"{slot} tuning") < 0.0
                or _metric_value(candidate, "brierScore", label=f"{slot} tuning") < 0.0
            ):
                raise SportsPhase4RegistryError(f"{slot} tuning candidate differs")
        tuning_winner = min(
            tuning_candidates,
            key=lambda row: (
                float(row["logLoss"]),
                float(row["brierScore"]),
                int(row["ordinal"]),
            ),
        )
        if inner_tuning.get("selectedC") != tuning_winner["C"]:
            raise SportsPhase4RegistryError(f"{slot} tuning selection differs")
    else:
        _exact_keys(
            inner_tuning,
            {
                "schemaVersion",
                "grid",
                "candidates",
                "selectedAlpha",
                "selectionUses2024Or2025",
                "split",
            },
            label="starterDuration inner-2023 tuning",
        )
        tuning_candidates = _list(
            inner_tuning.get("candidates"), label="starterDuration tuning candidates"
        )
        if (
            inner_tuning.get("schemaVersion") != "MLB_STARTER_RIDGE_TUNING_V1"
            or inner_tuning.get("grid") != [0.1, 1.0, 10.0]
            or len(tuning_candidates) != 3
        ):
            raise SportsPhase4RegistryError("Starter-duration tuning authority differs")
        for ordinal, (row, expected_alpha) in enumerate(
            zip(tuning_candidates, (0.1, 1.0, 10.0), strict=True)
        ):
            candidate = _mapping(row, label="starterDuration tuning candidate")
            _exact_keys(
                candidate,
                {"alpha", "bfpMae", "bfpRmse", "ordinal"},
                label="starterDuration tuning candidate",
            )
            if (
                candidate.get("alpha") != expected_alpha
                or candidate.get("ordinal") != ordinal
                or _metric_value(candidate, "bfpMae", label="starter tuning") < 0.0
                or _metric_value(candidate, "bfpRmse", label="starter tuning") < 0.0
            ):
                raise SportsPhase4RegistryError("Starter-duration tuning candidate differs")
        tuning_winner = min(
            tuning_candidates,
            key=lambda row: (
                float(row["bfpMae"]),
                float(row["bfpRmse"]),
                int(row["ordinal"]),
            ),
        )
        if inner_tuning.get("selectedAlpha") != tuning_winner["alpha"]:
            raise SportsPhase4RegistryError("Starter-duration tuning selection differs")
    if slot == "lineup" and descriptor.get("orderEstimator") != (
        "DETERMINISTIC_PROBABILITY_WEIGHTED_HISTORICAL_ORDER"
    ):
        raise SportsPhase4RegistryError("Lineup order-estimator authority differs")
    if slot == "starterDuration":
        inning_reach = _mapping(
            descriptor.get("inningReach"), label="starterDuration inningReach"
        )
        _exact_keys(
            inning_reach,
            {"estimator", "C", "thresholdOuts"},
            label="starterDuration inningReach",
        )
        if (
            descriptor.get("conditioning")
            != "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY"
            or descriptor.get("primaryTarget") != "stat_p_bfp"
            or descriptor.get("secondaryTarget") != "stat_p_ipouts"
            or inning_reach
            != {
                "estimator": "BOUNDED_LOGISTIC_L2",
                "C": 0.2,
                "thresholdOuts": [15, 18, 21],
            }
        ):
            raise SportsPhase4RegistryError("Starter-duration target authority differs")
    if slot == "bullpenUsage":
        gate = _mapping(descriptor.get("componentGate"), label="bullpen componentGate")
        expected_gate = {
            "rawLogLossStrictlyBetterThanB0BothFolds": True,
            "rawBrierNonWorseThanB0BothFoldsTolerance": 1e-10,
            "coverageMinimum": 0.95,
            "rawTopLabelEceMaximum": 0.05,
            "allTenReliabilityBinsFiniteAndNonempty": True,
            "scaledEvidenceCannotSatisfyGate": True,
        }
        if gate != expected_gate:
            raise SportsPhase4RegistryError("Bullpen component gate differs")
    records = _candidate_records(component["candidates"], label=f"{slot} candidates")
    expected_ids = set(policy["requiredCandidates"]) | set(policy["optionalCandidates"])
    if set(records) != expected_ids:
        raise SportsPhase4RegistryError(f"{slot} candidate inventory differs")
    contract_candidates = {
        "lineup": LINEUP_CANDIDATES,
        "starterDuration": STARTER_CANDIDATES,
        "bullpenUsage": BULLPEN_CANDIDATES,
    }[slot]
    metrics_by_candidate: dict[str, dict[int, dict[str, Any] | None]] = {}
    eligible_ids: list[str] = []
    for candidate_id in contract_candidates:
        record = records[candidate_id]
        governed = contract_candidates[candidate_id]
        _exact_keys(
            record,
            {
                "candidateId",
                "displayName",
                "estimator",
                "featureNames",
                "optional",
                "eligible",
                "rejectionReasons",
                "foldMetrics",
                "runtimeSeconds",
                "convergence",
            },
            label=f"{slot} candidate {candidate_id}",
        )
        candidate_runtime = _metric_value(
            record,
            "runtimeSeconds",
            label=f"{slot} candidate {candidate_id}",
        )
        convergence_summary = _mapping(
            record.get("convergence"),
            label=f"{slot} candidate {candidate_id} convergence",
        )
        _exact_keys(
            convergence_summary,
            {"allCompleteFoldsConverged"},
            label=f"{slot} candidate {candidate_id} convergence",
        )
        if (
            record.get("displayName") != governed["displayName"]
            or record.get("estimator") != governed["estimator"]
            or record.get("featureNames") != list(governed["features"])
            or record.get("optional") is not bool(governed["optional"])
            or type(record.get("eligible")) is not bool
            or type(record.get("rejectionReasons")) is not list
            or candidate_runtime < 0.0
        ):
            raise SportsPhase4RegistryError(f"{slot} candidate {candidate_id} contract differs")
        if not governed["optional"] and record["eligible"] is not True:
            raise SportsPhase4RegistryError(f"{slot} mandatory candidate {candidate_id} is ineligible")
        if record["eligible"]:
            if record["rejectionReasons"]:
                raise SportsPhase4RegistryError(f"{slot} eligible candidate has rejection reasons")
            eligible_ids.append(candidate_id)
        elif record["rejectionReasons"] != ["OPTIONAL_HGB_DISABLED_BY_POLICY"]:
            raise SportsPhase4RegistryError(f"{slot} optional-candidate rejection reason differs")
        metrics_by_candidate[candidate_id] = _participation_fold_metrics(
            record,
            candidate_id=candidate_id,
        )
        complete_folds = [
            fold
            for fold in record["foldMetrics"]
            if fold.get("status") == "COMPLETE"
        ]
        expected_converged = (
            all(fold["convergence"].get("converged") is True for fold in complete_folds)
            if complete_folds
            else None
        )
        if convergence_summary.get("allCompleteFoldsConverged") is not expected_converged:
            raise SportsPhase4RegistryError(
                f"{slot} candidate {candidate_id} convergence summary differs"
            )
        for season, metrics in metrics_by_candidate[candidate_id].items():
            if metrics is not None:
                _validate_participation_metrics(
                    metrics,
                    slot=slot,
                    label=f"{slot} {candidate_id} {season} metrics",
                )
        if record["eligible"] and metrics_by_candidate[candidate_id][2024] is None:
            raise SportsPhase4RegistryError(f"{slot} eligible candidate lacks 2024 evidence")

    if slot in ("lineup", "bullpenUsage"):
        primary, secondary = "binaryLogLoss", "brierScore"
    else:
        primary, secondary = "bfpMae", "bfpRmse"
    selected_expected = min(
        eligible_ids,
        key=lambda candidate_id: (
            _metric_value(metrics_by_candidate[candidate_id][2024], primary, label=f"{slot} {candidate_id}"),
            _metric_value(metrics_by_candidate[candidate_id][2024], secondary, label=f"{slot} {candidate_id}"),
            int(candidate_id[1:]),
        ),
    )
    selected = _mapping(component["selected"], label=f"{slot} selected")
    expected_selection_metric = {
        "lineup": "BINARY_LOG_LOSS_THEN_BRIER",
        "starterDuration": "BFP_MAE_THEN_RMSE",
        "bullpenUsage": "RAW_BINARY_LOG_LOSS_THEN_BRIER",
    }[slot]
    if (
        selected.get("candidateId") != selected_expected
        or selected.get("selectionSeason") != 2024
        or selected.get("selectionMetric") != expected_selection_metric
    ):
        raise SportsPhase4RegistryError(f"{slot} selection differs from the 2024-only policy")
    if metrics_by_candidate[selected_expected][2025] is None:
        raise SportsPhase4RegistryError(f"{slot} selected candidate lacks frozen 2025 evaluation")

    # Required baselines remain evaluable in 2025; every other unselected
    # challenger is intentionally not run after the 2024 selection is frozen.
    baseline_ids = {
        "lineup": {"L0"},
        "starterDuration": {"S0", "S1"},
        "bullpenUsage": {"B0"},
    }[slot]
    for candidate_id, by_season in metrics_by_candidate.items():
        expected_complete = candidate_id in baseline_ids or candidate_id == selected_expected
        if (by_season[2025] is not None) is not expected_complete:
            raise SportsPhase4RegistryError(f"{slot} 2025 execution policy differs")

    folds = _list(component["folds"], label=f"{slot} folds")
    if len(folds) != 2:
        raise SportsPhase4RegistryError(f"{slot} common folds differ")
    by_fold_season = {
        int(item["validationSeason"]): _mapping(item, label=f"{slot} fold")
        for item in folds
    }
    if set(by_fold_season) != {2024, 2025}:
        raise SportsPhase4RegistryError(f"{slot} common fold seasons differ")
    for season, expected_training in ((2024, [2023]), (2025, [2023, 2024])):
        fold = by_fold_season[season]
        _exact_keys(
            fold,
            {
                "foldId",
                "trainingSeasons",
                "validationSeason",
                "trainingRows",
                "validationRows",
                "status",
            },
            label=f"{slot} common fold",
        )
        expected_fold_id = (
            "train-2023-validate-2024"
            if season == 2024
            else "train-through-2024-validate-2025"
        )
        if (
            fold.get("foldId") != expected_fold_id
            or fold.get("trainingSeasons") != expected_training
            or fold.get("status") != "COMPLETE"
            or type(fold.get("trainingRows")) is not int
            or fold["trainingRows"] <= 0
            or fold.get("validationRows")
            != metrics_by_candidate[selected_expected][season]["rowCount"]
        ):
            raise SportsPhase4RegistryError(f"{slot} common fold authority differs")

    metrics = _mapping(component["metrics"], label=f"{slot} metrics")
    selected_2024 = metrics_by_candidate[selected_expected][2024]
    selected_2025 = metrics_by_candidate[selected_expected][2025]
    if metrics != {"selection2024": selected_2024, "final2025": selected_2025}:
        raise SportsPhase4RegistryError(f"{slot} selected metrics differ from candidate folds")
    calibration = _mapping(component["calibration"], label=f"{slot} calibration")
    if slot == "lineup":
        expected_calibration = {
            "selection2024": selected_2024.get("calibration"),
            "final2025": selected_2025.get("calibration"),
        }
    elif slot == "starterDuration":
        calibration_keys = ("reach15Calibration", "reach18Calibration", "reach21Calibration")
        expected_calibration = {
            "selection2024": {key: selected_2024.get(key) for key in calibration_keys},
            "final2025": {key: selected_2025.get(key) for key in calibration_keys},
        }
    else:
        expected_calibration = {
            "selection2024": selected_2024.get("topLabelCalibration"),
            "final2025": selected_2025.get("topLabelCalibration"),
        }
    if calibration != expected_calibration:
        raise SportsPhase4RegistryError(f"{slot} calibration differs from raw fold metrics")

    coverage = _mapping(component["coverage"], label=f"{slot} coverage")
    _exact_keys(
        coverage,
        ({"acceptableThreshold", "bySeason"} if slot in ("lineup", "bullpenUsage") else {"bySeason"}),
        label=f"{slot} coverage",
    )
    coverage_rows = _list(coverage.get("bySeason"), label=f"{slot} coverage.bySeason")
    coverage_by_season = {
        int(item["season"]): _mapping(item, label=f"{slot} coverage row")
        for item in coverage_rows
    }
    if set(coverage_by_season) != {2023, 2024, 2025} or len(coverage_rows) != 3:
        raise SportsPhase4RegistryError(f"{slot} coverage omits a frozen fold")
    coverage_row_keys = {
        "lineup": {
            "season",
            "targetTeamGames",
            "eligibleTargetTeamGames",
            "excludedTargetTeamGames",
            "completeLineupEligibleGames",
            "completeLineupExcludedGames",
            "candidateRows",
            "actualPositiveRows",
            "allTargetActualPositiveRows",
            "coveredPositiveRows",
            "uncoveredPositiveRows",
            "poolCoverage",
            "emptyCandidatePools",
            "completePoolCoverageTeamGames",
        },
        "starterDuration": {
            "season",
            "targetRows",
            "conditioning",
            "dynamicRowsBound",
            "fixtureDefaultDynamicRows",
            "dynamicCoverage",
        },
        "bullpenUsage": {
            "season",
            "targetTeamGames",
            "candidateRows",
            "actualPositiveRows",
            "coveredPositiveRows",
            "uncoveredPositiveRows",
            "poolCoverage",
            "emptyCandidatePools",
            "emptyPoolActualPositiveRows",
            "zeroRelieverTeamGames",
            "emptyPoolZeroRelieverTeamGames",
            "emptyPoolPositiveRelieverTeamGames",
            "earlySeasonTeamGames",
            "earlySeasonActualPositiveRows",
            "completePoolCoverageTeamGames",
        },
    }[slot]
    for season, row in coverage_by_season.items():
        _exact_keys(row, coverage_row_keys, label=f"{slot} {season} coverage")
        if slot in ("lineup", "bullpenUsage"):
            for key in coverage_row_keys - {"season", "poolCoverage"}:
                value = row.get(key)
                if type(value) is not int or value < 0:
                    raise SportsPhase4RegistryError(
                        f"{slot} {season} coverage count {key} differs"
                    )
            actual = row["actualPositiveRows"]
            if (
                row["coveredPositiveRows"] + row["uncoveredPositiveRows"] != actual
                or actual <= 0
            ):
                raise SportsPhase4RegistryError(
                    f"{slot} {season} coverage counts do not reconcile"
                )
            _close(
                row.get("poolCoverage"),
                row["coveredPositiveRows"] / actual,
                label=f"{slot} {season} pool coverage",
            )
    if slot in ("lineup", "bullpenUsage"):
        if coverage.get("acceptableThreshold") != 0.95:
            raise SportsPhase4RegistryError(f"{slot} coverage threshold differs")
        for season, selected_metrics in ((2024, selected_2024), (2025, selected_2025)):
            coverage_row = coverage_by_season[season]
            actual = coverage_row.get("actualPositiveRows")
            covered = coverage_row.get("coveredPositiveRows")
            uncovered = coverage_row.get("uncoveredPositiveRows")
            if (
                type(actual) is not int
                or actual <= 0
                or type(covered) is not int
                or type(uncovered) is not int
                or covered + uncovered != actual
                or selected_metrics.get("totalActualPositiveCount") != actual
                or selected_metrics.get("uncoveredPositiveCount") != uncovered
            ):
                raise SportsPhase4RegistryError(f"{slot} positive coverage counts do not reconcile")
            _close(selected_metrics.get("poolCoverage"), covered / actual, label=f"{slot} pool coverage")
    else:
        for season, selected_metrics in ((2024, selected_2024), (2025, selected_2025)):
            coverage_row = coverage_by_season[season]
            target_rows = coverage_row.get("targetRows")
            dynamic_rows = coverage_row.get("dynamicRowsBound")
            fixture_rows = coverage_row.get("fixtureDefaultDynamicRows")
            if (
                coverage_row.get("conditioning")
                != "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY"
                or target_rows != selected_metrics.get("rowCount")
                or type(dynamic_rows) is not int
                or dynamic_rows < 0
                or type(fixture_rows) is not int
                or fixture_rows < 0
                or dynamic_rows + fixture_rows != target_rows
            ):
                raise SportsPhase4RegistryError("Starter coverage rows do not reconcile")
            _close(
                coverage_row.get("dynamicCoverage"),
                dynamic_rows / target_rows,
                label="Starter dynamic coverage",
            )

    bootstrap = _mapping(component["bootstrap"], label=f"{slot} bootstrap")
    bootstrap_key = {
        "lineup": "comparisonsToL0",
        "starterDuration": "comparisonsToS0AndS1",
        "bullpenUsage": "comparisonsToB0",
    }[slot]
    comparisons = _list(bootstrap.get(bootstrap_key), label=f"{slot} bootstrap comparisons")
    expected_comparison_keys = (
        {(2024, "S0"), (2024, "S1"), (2025, "S0"), (2025, "S1")}
        if slot == "starterDuration"
        else {(2024, next(iter(baseline_ids))), (2025, next(iter(baseline_ids)))}
    )
    observed_comparison_keys: set[tuple[int, str]] = set()
    for comparison in comparisons:
        row = _mapping(comparison, label=f"{slot} bootstrap comparison")
        expected_bootstrap_keys = {
            "validationSeason",
            "schemaVersion",
            "differenceOrder",
            "clusterSamplingPolicy",
            "replicateEstimator",
            "pointEstimate",
            "standardError",
            "confidenceLevel",
            "interval",
            "clusterCount",
            "resamples",
            "seed",
            "replicateDifferences",
        }
        if slot == "starterDuration":
            expected_bootstrap_keys.add("baselineCandidateId")
        _exact_keys(
            row,
            expected_bootstrap_keys,
            label=f"{slot} bootstrap comparison",
        )
        season = row.get("validationSeason")
        baseline_id = row.get("baselineCandidateId", next(iter(baseline_ids)))
        key = (season, baseline_id)
        if key in observed_comparison_keys or key not in expected_comparison_keys:
            raise SportsPhase4RegistryError(f"{slot} bootstrap comparison authority differs")
        if (
            row.get("schemaVersion")
            != "MLB_PARTICIPATION_GAME_CLUSTER_BOOTSTRAP_V2"
            or row.get("differenceOrder")
            != "SELECTED_MINUS_BASELINE_LOWER_IS_BETTER"
            or row.get("clusterSamplingPolicy") != "WHOLE_GAME_IDS_WITH_REPLACEMENT"
            or row.get("replicateEstimator")
            != "TOTAL_SAMPLED_CLUSTER_LOSS_SUM_DIVIDED_BY_TOTAL_SAMPLED_CLUSTER_ROW_COUNT"
            or row.get("resamples") != 500
            or row.get("seed") != 20_260_817 + int(season) + (int(baseline_id[1:]) if slot == "starterDuration" else 0)
            or row.get("confidenceLevel") != 0.95
            or row.get("clusterCount")
            != {2024: 2429, 2025: 2430}[int(season)]
            or type(row.get("replicateDifferences")) is not list
            or len(row["replicateDifferences"]) != 500
        ):
            raise SportsPhase4RegistryError(f"{slot} bootstrap policy differs")
        for value in row["replicateDifferences"]:
            if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(float(value)):
                raise SportsPhase4RegistryError(f"{slot} bootstrap replicates must be finite")
        interval = _mapping(row.get("interval"), label=f"{slot} bootstrap interval")
        _exact_keys(
            interval,
            {"lower", "upper"},
            label=f"{slot} bootstrap interval",
        )
        lower = _metric_value(interval, "lower", label=f"{slot} bootstrap interval")
        upper = _metric_value(interval, "upper", label=f"{slot} bootstrap interval")
        if lower > upper or _metric_value(row, "standardError", label=f"{slot} bootstrap") < 0.0:
            raise SportsPhase4RegistryError(f"{slot} bootstrap interval differs")
        baseline_metrics = metrics_by_candidate[baseline_id][int(season)]
        selected_metrics = metrics_by_candidate[selected_expected][int(season)]
        expected_point = (
            _metric_value(selected_metrics, "bfpMae", label="selected starter")
            - _metric_value(baseline_metrics, "bfpMae", label="baseline starter")
            if slot == "starterDuration"
            else _metric_value(selected_metrics, "binaryLogLoss", label="selected binary")
            - _metric_value(baseline_metrics, "binaryLogLoss", label="baseline binary")
        )
        _close(row.get("pointEstimate"), expected_point, label=f"{slot} bootstrap point estimate")
        _validate_replicate_statistics(
            row["replicateDifferences"],
            expected_count=500,
            standard_error=row["standardError"],
            lower=lower,
            upper=upper,
            label=f"{slot} bootstrap",
        )
        observed_comparison_keys.add(key)
    if observed_comparison_keys != expected_comparison_keys:
        raise SportsPhase4RegistryError(f"{slot} bootstrap comparisons are incomplete")

    decision_record = _mapping(component["decision"], label=f"{slot} decision")
    decision_evidence = _mapping(
        decision_record.get("evidence"), label=f"{slot} decision evidence"
    )
    integrity_failure = decision_evidence.get("integrityFailure")
    if integrity_failure is not None:
        integrity_failure = _nonblank(
            integrity_failure,
            label=f"{slot} decision integrity failure",
        )
    if slot == "lineup":
        baseline_2024 = metrics_by_candidate["L0"][2024]
        baseline_2025 = metrics_by_candidate["L0"][2025]
        improvements = (
            _metric_value(baseline_2024, "binaryLogLoss", label="L0") - _metric_value(selected_2024, "binaryLogLoss", label="selected"),
            _metric_value(baseline_2025, "binaryLogLoss", label="L0") - _metric_value(selected_2025, "binaryLogLoss", label="selected"),
        )
        coverage_values = (
            _metric_value(selected_2024, "poolCoverage", label="lineup"),
            _metric_value(selected_2025, "poolCoverage", label="lineup"),
        )
        expected_decision = lineup_decision(
            LineupDecisionEvidence(
                improvement_2024=improvements[0],
                improvement_2025=improvements[1],
                coverage_2024=coverage_values[0],
                coverage_2025=coverage_values[1],
                integrity_failure=integrity_failure,
            )
        )
    elif slot == "starterDuration":
        comparison_values: dict[str, float] = {}
        for season, selected_metrics in ((2024, selected_2024), (2025, selected_2025)):
            for baseline_id in ("S0", "S1"):
                baseline_metrics = metrics_by_candidate[baseline_id][season]
                for suffix, metric_name in (("Mae", "bfpMae"), ("Rmse", "bfpRmse")):
                    value = _metric_value(baseline_metrics, metric_name, label=baseline_id) - _metric_value(selected_metrics, metric_name, label="selected")
                    comparison_values[f"bfp{suffix}Vs{baseline_id}_{season}"] = value
        expected_decision = starter_decision(
            StarterDecisionEvidence(
                bfp_mae_vs_s0_2024=comparison_values["bfpMaeVsS0_2024"],
                bfp_rmse_vs_s0_2024=comparison_values["bfpRmseVsS0_2024"],
                bfp_mae_vs_s1_2024=comparison_values["bfpMaeVsS1_2024"],
                bfp_rmse_vs_s1_2024=comparison_values["bfpRmseVsS1_2024"],
                bfp_mae_vs_s0_2025=comparison_values["bfpMaeVsS0_2025"],
                bfp_rmse_vs_s0_2025=comparison_values["bfpRmseVsS0_2025"],
                bfp_mae_vs_s1_2025=comparison_values["bfpMaeVsS1_2025"],
                bfp_rmse_vs_s1_2025=comparison_values["bfpRmseVsS1_2025"],
                integrity_failure=integrity_failure,
            )
        )
    else:
        baseline_2024 = metrics_by_candidate["B0"][2024]
        baseline_2025 = metrics_by_candidate["B0"][2025]
        log_improvements = (
            _metric_value(baseline_2024, "binaryLogLoss", label="B0") - _metric_value(selected_2024, "binaryLogLoss", label="selected"),
            _metric_value(baseline_2025, "binaryLogLoss", label="B0") - _metric_value(selected_2025, "binaryLogLoss", label="selected"),
        )
        brier_improvements = (
            _metric_value(baseline_2024, "brierScore", label="B0") - _metric_value(selected_2024, "brierScore", label="selected"),
            _metric_value(baseline_2025, "brierScore", label="B0") - _metric_value(selected_2025, "brierScore", label="selected"),
        )
        coverage_values = (
            _metric_value(selected_2024, "poolCoverage", label="bullpen"),
            _metric_value(selected_2025, "poolCoverage", label="bullpen"),
        )
        calibration_values = (
            bool(selected_2024["topLabelCalibration"]["acceptable"]),
            bool(selected_2025["topLabelCalibration"]["acceptable"]),
        )
        expected_decision = bullpen_decision(
            BullpenDecisionEvidence(
                logloss_improvement_2024=log_improvements[0],
                logloss_improvement_2025=log_improvements[1],
                brier_improvement_2024=brier_improvements[0],
                brier_improvement_2025=brier_improvements[1],
                coverage_2024=coverage_values[0],
                coverage_2025=coverage_values[1],
                calibration_acceptable_2024=calibration_values[0],
                calibration_acceptable_2025=calibration_values[1],
                integrity_failure=integrity_failure,
            )
        )
    if component["decision"] != expected_decision:
        raise SportsPhase4RegistryError(f"{slot} terminal decision does not reconcile")


def _selected_candidate_id(selected: Any, *, label: str) -> str | None:
    if selected is None:
        return None
    selected_mapping = _mapping(selected, label=label)
    return _nonblank(selected_mapping.get("candidateId"), label=f"{label}.candidateId")


def _decision_value(component: Mapping[str, Any], *, slot: str) -> str:
    decision = _mapping(component["decision"], label=f"components.{slot}.decision")
    if slot == "dynamicState":
        value = decision.get("terminalStatus", decision.get("decision"))
    else:
        value = decision.get("decision", decision.get("terminalStatus"))
    return _nonblank(value, label=f"components.{slot}.decision status")


def _component_graph_status(component: Mapping[str, Any] | None, *, slot: str) -> str:
    if component is None:
        return "NOT_CONFIGURED"
    return _decision_value(component, slot=slot)


def _component_materialization_status(
    component: Mapping[str, Any] | None,
    *,
    slot: str,
) -> str:
    if component is None:
        return "NOT_CONFIGURED"
    decision = _decision_value(component, slot=slot)
    return "BLOCKED" if decision.endswith("BLOCKED") else "COMPLETE"


def _walk_fold_evidence(value: Any) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if "validationSeason" in value and "trainingSeasons" in value:
            found.append(value)
        for item in value.values():
            found.extend(_walk_fold_evidence(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_fold_evidence(item))
    return found


def _validate_temporal_folds(value: Any, *, slot: str, blocked: bool) -> None:
    if type(value) not in (dict, list):
        if blocked and value is None:
            return
        raise SportsPhase4RegistryError(f"components.{slot}.folds must be an object or array")
    found = _walk_fold_evidence(value)
    observed_validation: set[int] = set()
    for index, fold in enumerate(found):
        validation = fold["validationSeason"]
        training = fold["trainingSeasons"]
        if type(validation) is not int or type(training) is not list or any(type(item) is not int for item in training):
            raise SportsPhase4RegistryError(f"components.{slot}.folds[{index}] temporal authority is malformed")
        if validation == 2024 and training != [2023]:
            raise SportsPhase4RegistryError(f"components.{slot} 2024 fold authority differs")
        if validation == 2025 and training != [2023, 2024]:
            raise SportsPhase4RegistryError(f"components.{slot} 2025 fold authority differs")
        if validation not in (2024, 2025):
            raise SportsPhase4RegistryError(f"components.{slot} validation season is outside the frozen policy")
        observed_validation.add(validation)
    if not blocked and (not found or observed_validation != {2024, 2025}):
        raise SportsPhase4RegistryError(f"components.{slot} omits a frozen 2024/2025 fold")


def _validate_component(value: Any, *, slot: str) -> dict[str, Any] | None:
    if value is None:
        if slot == "dynamicState":
            raise SportsPhase4RegistryError("components.dynamicState is required")
        return None
    component = _mapping(value, label=f"components.{slot}")
    _exact_keys(component, COMPONENT_KEYS, label=f"components.{slot}")
    policy = COMPONENT_POLICIES[slot]
    if component["componentType"] != policy["type"]:
        raise SportsPhase4RegistryError(f"components.{slot}.componentType differs")
    if component["contractName"] != policy["contract"]:
        raise SportsPhase4RegistryError(f"components.{slot}.contractName differs")
    if component["contractSha"] != policy["sha"]:
        raise SportsPhase4RegistryError(f"components.{slot}.contractSha differs")
    if component["componentId"] != _component_id(component):
        raise SportsPhase4RegistryError(f"components.{slot}.componentId is not content-bound")

    decision = _decision_value(component, slot=slot)
    if decision not in policy["decisions"]:
        raise SportsPhase4RegistryError(f"components.{slot}.decision differs from the frozen enum")
    if slot == "dynamicState" and decision == "DYNAMIC_STATE_BLOCKED":
        # A blocked Milestone A is a CLI/report terminal, not a durable study:
        # without complete dynamic evidence there is no valid Phase 4 parent
        # for any participation component and no active research head to expose.
        raise SportsPhase4RegistryError(
            "DYNAMIC_STATE_BLOCKED is not registrable; preserve the fail-closed run report without activating a Phase 4 study"
        )
    blocked = decision.endswith("BLOCKED") or decision == "BLOCKED"
    candidate_ids = _candidate_ids(component["candidates"], label=f"components.{slot}.candidates")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise SportsPhase4RegistryError(f"components.{slot} candidate identities must be unique")
    required = set(policy["requiredCandidates"])
    optional = set(policy["optionalCandidates"])
    observed = set(candidate_ids)
    if not required.issubset(observed) or not observed.issubset(required | optional):
        raise SportsPhase4RegistryError(f"components.{slot} candidate identities differ")
    selected_id = _selected_candidate_id(component["selected"], label=f"components.{slot}.selected")
    if selected_id is not None and selected_id not in observed:
        raise SportsPhase4RegistryError(f"components.{slot}.selected is not a governed candidate")
    if not blocked and selected_id is None:
        raise SportsPhase4RegistryError(f"components.{slot}.selected is required for completed evidence")
    if type(component["artifactIds"]) is not list or any(
        type(item) is not str or not item for item in component["artifactIds"]
    ):
        raise SportsPhase4RegistryError(f"components.{slot}.artifactIds must be canonical strings")
    if len(component["artifactIds"]) != len(set(component["artifactIds"])):
        raise SportsPhase4RegistryError(f"components.{slot}.artifactIds must be unique")
    if component["descriptor"] is None:
        raise SportsPhase4RegistryError(f"components.{slot}.descriptor is required")
    if slot == "dynamicState":
        _validate_dynamic_descriptor(
            _mapping(component["descriptor"], label="dynamic descriptor")
        )
    _validate_temporal_folds(component["folds"], slot=slot, blocked=blocked)
    for nullable in ("metrics", "calibration", "bootstrap", "coverage"):
        if component[nullable] is not None and type(component[nullable]) not in (dict, list):
            raise SportsPhase4RegistryError(f"components.{slot}.{nullable} must be an object, array, or null")
    if slot == "dynamicState":
        _validate_dynamic_scientific_evidence(component)
    else:
        _validate_participation_scientific_evidence(component, slot=slot)
    _scan_public_safety(component, path=f"$.components.{slot}")
    return component


def _validate_dynamic_policy(value: Any, *, label: str) -> dict[str, Any]:
    policy = _mapping(value, label=label)
    _exact_keys(
        policy,
        {
            "schemaVersion",
            "policyId",
            "halfLifeDays",
            "priorEffectiveSampleSize",
            "availabilityPredicate",
            "sameDateExcluded",
        },
        label=label,
    )
    if (
        policy["schemaVersion"] != "MLB_DYNAMIC_PLAYER_STATE_POLICY_V1"
        or policy["halfLifeDays"] not in (30, 60, 120, None)
        or policy["priorEffectiveSampleSize"] not in (50, 150, 300)
        or policy["availabilityPredicate"]
        != "source.final_available_date < target.game_date"
        or policy["sameDateExcluded"] is not True
    ):
        raise SportsPhase4RegistryError(f"{label} differs from the frozen policy")
    identity_core = {
        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_POLICY_IDENTITY_V1",
        "contractSha": dynamic_state_contract_sha(),
        "halfLifeDays": policy["halfLifeDays"],
        "priorEffectiveSampleSize": policy["priorEffectiveSampleSize"],
    }
    expected_id = "mlb-dynamic-player-state-policy:sha256:" + sha256_bytes(
        canonical_json_bytes(identity_core)
    )
    if policy["policyId"] != expected_id:
        raise SportsPhase4RegistryError(f"{label} identity is not content-bound")
    return policy


def _validate_runtime_artifact_descriptor(
    value: Any,
    *,
    label: str,
    expected_type: str,
    expected_contract_sha: str,
    expected_schema_sha: str,
) -> dict[str, Any]:
    descriptor = _mapping(value, label=label)
    required = {
        "contractName",
        "contractSha",
        "schemaSha",
        "contentSha",
        "artifactId",
        "artifactSha",
        "artifactBytes",
        "logicalUri",
        "mediaType",
        "rowCount",
    }
    if not required.issubset(descriptor):
        raise SportsPhase4RegistryError(f"{label} fields differ")
    content_sha = _sha(descriptor["contentSha"], label=f"{label}.contentSha")
    artifact_sha = _sha(descriptor["artifactSha"], label=f"{label}.artifactSha")
    artifact_id = _nonblank(descriptor["artifactId"], label=f"{label}.artifactId")
    logical_uri = _nonblank(descriptor["logicalUri"], label=f"{label}.logicalUri")
    if (
        descriptor["contractName"] != DYNAMIC_CONTRACT_NAME
        or descriptor["contractSha"] != expected_contract_sha
        or descriptor["schemaSha"] != expected_schema_sha
        or not artifact_id.endswith(f":sha256:{artifact_sha}")
        or not logical_uri.startswith(RUNTIME_LOGICAL_PREFIX)
        or f"/objects/sha256/{artifact_sha[:2]}/{artifact_sha}/" not in logical_uri
        or descriptor["mediaType"] != "application/vnd.apache.parquet"
        or type(descriptor["artifactBytes"]) is not int
        or descriptor["artifactBytes"] <= 0
        or type(descriptor["rowCount"]) is not int
        or descriptor["rowCount"] <= 0
    ):
        raise SportsPhase4RegistryError(f"{label} artifact authority differs")
    _ = content_sha, expected_type
    return descriptor


def _validate_dynamic_descriptor(descriptor: Mapping[str, Any]) -> None:
    _exact_keys(
        descriptor,
        {
            "schemaVersion",
            "semanticVersion",
            "contractSha",
            "stateSchemaSha",
            "historySchemaSha",
            "classOrder",
            "referenceClass",
            "selectedPolicy",
            "tuning",
            "authorityBindings",
            "source",
            "phase3",
            "dynamicState",
            "historyIndex",
            "temporalPolicy",
            "rowIdentityPolicy",
            "runtime",
        },
        label="dynamic descriptor",
    )
    contract = dynamic_state_contract_payload()
    if (
        descriptor["schemaVersion"] != DYNAMIC_DESCRIPTOR_SCHEMA_VERSION
        or descriptor["semanticVersion"] != DYNAMIC_SEMANTIC_VERSION
        or descriptor["contractSha"] != dynamic_state_contract_sha()
        or descriptor["stateSchemaSha"] != dynamic_state_schema_sha()
        or descriptor["historySchemaSha"] != dynamic_history_index_schema_sha()
        or descriptor["classOrder"] != list(PA_CLASS_ORDER)
        or descriptor["referenceClass"] != REFERENCE_CLASS
        or descriptor["authorityBindings"] != contract["authorityBindings"]
        or descriptor["temporalPolicy"] != contract["temporalPolicy"]
        or descriptor["rowIdentityPolicy"]
        != contract["representation"]["rowIdentityPolicy"]
    ):
        raise SportsPhase4RegistryError("Dynamic descriptor contract authority differs")

    selected_policy = _validate_dynamic_policy(
        descriptor["selectedPolicy"], label="dynamic descriptor selectedPolicy"
    )
    tuning = _mapping(descriptor["tuning"], label="dynamic descriptor tuning")
    _exact_keys(
        tuning,
        {"statePolicy", "logisticInner2023Split", "logisticByCandidate"},
        label="dynamic descriptor tuning",
    )
    state_tuning = _mapping(tuning["statePolicy"], label="dynamic state-policy tuning")
    if (
        state_tuning.get("schemaVersion") != "MLB_DYNAMIC_PLAYER_STATE_TUNING_V1"
        or state_tuning.get("objective")
        != "MEAN_BATTER_PITCHER_POSTERIOR_PREDICTIVE_LOG_LOSS"
        or state_tuning.get("selectionUses2024Or2025") is not False
        or state_tuning.get("selectedPolicy") != selected_policy
    ):
        raise SportsPhase4RegistryError("Dynamic state-policy tuning authority differs")
    state_candidates = _list(
        state_tuning.get("candidates"), label="dynamic state-policy candidates"
    )
    observed_grid: set[tuple[int | None, int]] = set()
    for raw_candidate in state_candidates:
        candidate = _mapping(raw_candidate, label="dynamic state-policy candidate")
        half_life = candidate.get("halfLifeDays")
        prior_ess = candidate.get("priorEffectiveSampleSize")
        if (
            half_life not in (30, 60, 120, None)
            or prior_ess not in (50, 150, 300)
            or (half_life, prior_ess) in observed_grid
            or candidate.get("validationRows", 0) <= 0
            or candidate.get("roleObservations", 0) <= 0
            or not math.isfinite(float(candidate.get("posteriorPredictiveLogLoss")))
        ):
            raise SportsPhase4RegistryError("Dynamic state-policy candidate differs")
        observed_grid.add((half_life, prior_ess))
    if observed_grid != {
        (half_life, prior_ess)
        for half_life in (30, 60, 120, None)
        for prior_ess in (50, 150, 300)
    }:
        raise SportsPhase4RegistryError("Dynamic state-policy grid is incomplete")
    winner = min(
        state_candidates,
        key=lambda item: (
            float(item["posteriorPredictiveLogLoss"]),
            int(item["priorEffectiveSampleSize"]),
            int(item["halfLifeGridOrdinal"]),
        ),
    )
    if (
        winner.get("policyId") != selected_policy["policyId"]
        or winner.get("halfLifeDays") != selected_policy["halfLifeDays"]
        or winner.get("priorEffectiveSampleSize")
        != selected_policy["priorEffectiveSampleSize"]
    ):
        raise SportsPhase4RegistryError("Dynamic selected state policy differs from tuning")
    for split_name in ("split",):
        split = _mapping(state_tuning.get(split_name), label="dynamic state tuning split")
        if split.get("sourceSeason") != 2023 or split.get("dateAtomic") is not True:
            raise SportsPhase4RegistryError("Dynamic state tuning is not inner-2023/date-atomic")
    logistic_split = _mapping(
        tuning["logisticInner2023Split"], label="dynamic logistic tuning split"
    )
    if logistic_split.get("sourceSeason") != 2023 or logistic_split.get("dateAtomic") is not True:
        raise SportsPhase4RegistryError("Dynamic logistic tuning is not inner-2023/date-atomic")

    source = _mapping(descriptor["source"], label="dynamic descriptor source")
    partition_ids = _list(source.get("partitionIds"), label="dynamic source partitions")
    if (
        source.get("family") != "plate_appearance"
        or source.get("seasons") != [2021, 2022, 2023, 2024, 2025]
        or source.get("finalAvailabilityField") != "final_available_date"
        or type(source.get("rowCount")) is not int
        or source["rowCount"] <= 0
        or source.get("resolvedReferenceCount") != 2 * source["rowCount"]
        or len(partition_ids) != EXPECTED_SOURCE_PARTITION_COUNT
        or partition_ids != sorted(set(partition_ids))
        or any(type(value) is not str or _SHA_RE.fullmatch(value) is None for value in partition_ids)
    ):
        raise SportsPhase4RegistryError("Dynamic source authority differs")

    phase3 = _mapping(descriptor["phase3"], label="dynamic descriptor Phase 3")
    if (
        phase3.get("runId") != PHASE3_RUN_ID
        or phase3.get("runSha") != PHASE3_RUN_SHA
        or phase3.get("featureViewId") != PHASE3_FEATURE_VIEW_ID
        or phase3.get("featureContentSha") != PHASE3_FEATURE_CONTENT_SHA
        or phase3.get("d0Candidate") != "C4_RAW"
    ):
        raise SportsPhase4RegistryError("Dynamic descriptor Phase 3 authority differs")
    feature_artifact = _mapping(
        phase3.get("featureArtifact"), label="dynamic Phase 3 feature artifact"
    )
    d0_artifacts = _mapping(
        phase3.get("d0PredictionArtifacts"), label="dynamic D0 artifacts"
    )
    if (
        feature_artifact != _PHASE3_FEATURE_ARTIFACT_AUTHORITY
        or set(d0_artifacts) != {"2024", "2025"}
        or d0_artifacts["2024"] != _PHASE3_D0_ARTIFACT_AUTHORITIES[2024]
        or d0_artifacts["2025"] != _PHASE3_D0_ARTIFACT_AUTHORITIES[2025]
    ):
        raise SportsPhase4RegistryError("Dynamic descriptor Phase 3 artifact authority differs")
    feature_source_partition_ids = phase3.get("featureSourcePartitionIds")
    if (
        type(feature_source_partition_ids) is not list
        or len(feature_source_partition_ids) != 26
        or feature_source_partition_ids != sorted(set(feature_source_partition_ids))
        or any(
            type(value) is not str or _SHA_RE.fullmatch(value) is None
            for value in feature_source_partition_ids
        )
    ):
        raise SportsPhase4RegistryError(
            "Dynamic descriptor Phase 3 feature source authority differs"
        )

    dynamic_state = _validate_runtime_artifact_descriptor(
        descriptor["dynamicState"],
        label="dynamic state artifact descriptor",
        expected_type="DYNAMIC_PLAYER_STATE",
        expected_contract_sha=dynamic_state_contract_sha(),
        expected_schema_sha=dynamic_state_schema_sha(),
    )
    history_index = _validate_runtime_artifact_descriptor(
        descriptor["historyIndex"],
        label="dynamic history artifact descriptor",
        expected_type="DYNAMIC_HISTORY_INDEX",
        expected_contract_sha=dynamic_state_contract_sha(),
        expected_schema_sha=dynamic_history_index_schema_sha(),
    )
    if (
        dynamic_state.get("selectedPolicy") != selected_policy
        or dynamic_state.get("sourcePartitionIds") != partition_ids
        or dynamic_state.get("stateKinds")
        != ["A_PRESEASON", "B_CUMULATIVE", "C_RECENCY"]
        or history_index.get("sourcePartitionIds") != partition_ids
        or history_index.get("sourceRowCount") != source["rowCount"]
        or history_index.get("resolvedReferenceCount") != source["resolvedReferenceCount"]
        or history_index.get("authorityBindings")
        != {
            "dataset": contract["authorityBindings"]["dataset"],
            "identityBridge": contract["authorityBindings"]["identityBridge"],
        }
    ):
        raise SportsPhase4RegistryError("Dynamic state/history descriptors do not reconcile")

    runtime = _mapping(descriptor["runtime"], label="dynamic descriptor runtime")
    checkpoint_id = _nonblank(runtime.get("checkpointId"), label="dynamic checkpoint ID")
    if (
        not checkpoint_id.startswith("mlb-dynamic-player-state-checkpoint:sha256:")
        or runtime.get("crossCodeRevisionImmutableReuseAllowed") is not True
        or runtime.get("reuseRequiresExactFreshlyRebuiltBytes") is not True
        or runtime.get("maxModelFitSeconds") != 90 * 60
        or runtime.get("maxOverallSeconds") != 8 * 60 * 60
        or runtime.get("heartbeatSeconds") > 60
    ):
        raise SportsPhase4RegistryError("Dynamic runtime/checkpoint authority differs")
    _nonblank(runtime.get("materializationCodeRevision"), label="dynamic materialization revision")
    _nonblank(runtime.get("currentCodeRevision"), label="dynamic current revision")


def _node(
    node_id: str,
    node_type: str,
    label: str,
    status: str,
    *,
    component_id: str | None = None,
    authority_ref: str | None = None,
) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "nodeType": node_type,
        "label": label,
        "status": status,
        "componentId": component_id,
        "authorityRef": authority_ref,
    }


def _edge(source: str, target: str, relation: str) -> dict[str, Any]:
    digest = sha256_bytes(
        canonical_json_bytes({"sourceNodeId": source, "targetNodeId": target, "relation": relation})
    )
    return {
        "edgeId": f"sports-phase4-graph-edge:sha256:{digest}",
        "sourceNodeId": source,
        "targetNodeId": target,
        "relation": relation,
    }


def build_phase4_graph(
    components: Mapping[str, Mapping[str, Any] | None],
    *,
    phase3_graph_id: str = "PHASE3_GRAPH_ID_REQUIRED_AT_STUDY_BUILD",
) -> dict[str, Any]:
    """Build the only accepted additive Phase 4 graph."""

    if set(components) != set(COMPONENT_SLOTS):
        raise SportsPhase4RegistryError("Phase 4 component slots differ")
    dynamic = components["dynamicState"]
    if dynamic is None:
        raise SportsPhase4RegistryError("Dynamic-state evidence is required")
    statuses = {
        slot: _component_graph_status(components[slot], slot=slot)
        for slot in COMPONENT_SLOTS
    }
    materialization_statuses = {
        slot: _component_materialization_status(components[slot], slot=slot)
        for slot in COMPONENT_SLOTS
    }
    component_ids = {
        slot: (str(components[slot]["componentId"]) if components[slot] is not None else None)
        for slot in COMPONENT_SLOTS
    }
    nodes = [
        _node("dataset", "DATASET", "Registered MLB exchange dataset", "COMPLETE", authority_ref=REGISTRATION_ID),
        _node("identity-bridge", "IDENTITY_BRIDGE", "Registered MLB identity bridge", "COMPLETE", authority_ref=BRIDGE_REGISTRATION_ID),
        _node(
            "exact-identity-join",
            "IDENTITY_JOIN",
            "Exact player identity join audit",
            "COMPLETE",
            authority_ref=PHASE4_JOIN_AUDIT_ID,
        ),
        _node("static-player-prior", "PLAYER_STATE", "Frozen Phase 3 static player prior", "COMPLETE", authority_ref=PHASE3_FEATURE_CONTRACT_SHA),
        _node(
            "phase3-baseline",
            "PARENT_RESEARCH",
            "Frozen Phase 3 raw C4 baseline",
            PHASE3_TERMINAL_STATUS,
            authority_ref=PHASE3_RUN_ID,
        ),
        _node("dynamic-batter-state", "PLAYER_STATE", "Prior-date dynamic batter state", materialization_statuses["dynamicState"], component_id=component_ids["dynamicState"]),
        _node("dynamic-pitcher-state", "PLAYER_STATE", "Prior-date dynamic pitcher state", materialization_statuses["dynamicState"], component_id=component_ids["dynamicState"]),
        _node("dynamic-pa-research", "EVENT_MODEL", "Dynamic plate-appearance research", statuses["dynamicState"], component_id=component_ids["dynamicState"]),
        _node("retrospective-evaluation", "EVALUATION", "Retrospective 2024/2025 evaluation", statuses["dynamicState"], component_id=component_ids["dynamicState"]),
        _node("prior-participation", "PRIOR_USAGE", "Prior-date participation history", materialization_statuses["lineup"], component_id=component_ids["lineup"]),
        _node("lineup-projection", "PARTICIPATION_MODEL", "Lineup projection research", statuses["lineup"], component_id=component_ids["lineup"]),
        _node("prior-starter-workload", "PRIOR_USAGE", "Prior-date starter workload", materialization_statuses["starterDuration"], component_id=component_ids["starterDuration"]),
        _node("starter-duration", "USAGE_MODEL", "Starter duration research", statuses["starterDuration"], component_id=component_ids["starterDuration"]),
        _node("prior-relief-workload", "PRIOR_USAGE", "Prior-date relief workload", materialization_statuses["bullpenUsage"], component_id=component_ids["bullpenUsage"]),
        _node("bullpen-usage", "USAGE_MODEL", "Bullpen usage research", statuses["bullpenUsage"], component_id=component_ids["bullpenUsage"]),
        _node("confirmed-lineup", "FUTURE_INPUT", "Confirmed lineup", "NOT_CONFIGURED"),
        _node("probable-starter", "FUTURE_INPUT", "Probable starter", "NOT_CONFIGURED"),
        _node("injury-feed", "FUTURE_INPUT", "Injury and transaction feed", "NOT_CONFIGURED"),
        _node("platoon", "FUTURE_COMPONENT", "Handedness and platoon component", "NOT_CONFIGURED"),
        _node("base-out-transition", "FUTURE_COMPONENT", "Base-out transition component", "NOT_CONFIGURED"),
        _node("game-simulator", "FUTURE_COMPONENT", "Game simulator", "NOT_CONFIGURED"),
        _node("residual-layer", "FUTURE_COMPONENT", "Residual correction layer", "NOT_CONFIGURED"),
        _node("export-bundle", "FUTURE_OUTPUT", "ASP export bundle", "NOT_CONFIGURED"),
        _node("monitoring", "FUTURE_OUTPUT", "Prospective monitoring", "NOT_CONFIGURED"),
    ]
    edges = [
        _edge("dataset", "identity-bridge", "HAS_REGISTERED_BRIDGE"),
        _edge("identity-bridge", "exact-identity-join", "VALIDATED_BY"),
        _edge("exact-identity-join", "static-player-prior", "SUPPORTS"),
        _edge("static-player-prior", "phase3-baseline", "FEATURES"),
        _edge("phase3-baseline", "dynamic-pa-research", "FROZEN_COMPARATOR_FOR"),
        _edge("static-player-prior", "dynamic-batter-state", "INITIALIZES"),
        _edge("static-player-prior", "dynamic-pitcher-state", "INITIALIZES"),
        _edge("dynamic-batter-state", "dynamic-pa-research", "FEATURES"),
        _edge("dynamic-pitcher-state", "dynamic-pa-research", "FEATURES"),
        _edge("dynamic-pa-research", "retrospective-evaluation", "EVALUATED_BY"),
        _edge("dataset", "prior-participation", "HISTORICAL_ONLY"),
        _edge("prior-participation", "lineup-projection", "FEATURES"),
        _edge("dynamic-batter-state", "lineup-projection", "AVAILABILITY_FEATURES"),
        _edge("dataset", "prior-starter-workload", "HISTORICAL_ONLY"),
        _edge("prior-starter-workload", "starter-duration", "FEATURES"),
        _edge("dynamic-pitcher-state", "starter-duration", "AVAILABILITY_FEATURES"),
        _edge("dataset", "prior-relief-workload", "HISTORICAL_ONLY"),
        _edge("prior-relief-workload", "bullpen-usage", "FEATURES"),
        _edge("dynamic-pitcher-state", "bullpen-usage", "AVAILABILITY_FEATURES"),
        _edge("lineup-projection", "game-simulator", "FUTURE_INPUT_TO"),
        _edge("starter-duration", "game-simulator", "FUTURE_INPUT_TO"),
        _edge("bullpen-usage", "game-simulator", "FUTURE_INPUT_TO"),
        _edge("base-out-transition", "game-simulator", "FUTURE_INPUT_TO"),
        _edge("game-simulator", "residual-layer", "FUTURE_INPUT_TO"),
        _edge("residual-layer", "export-bundle", "FUTURE_INPUT_TO"),
        _edge("export-bundle", "monitoring", "FUTURE_MONITORED_BY"),
    ]
    graph_core = {
        "parentGraphId": phase3_graph_id,
        "nodes": nodes,
        "edges": edges,
    }
    graph_sha = sha256_bytes(canonical_json_bytes(graph_core))
    return {
        "graphId": f"sports-phase4-model-graph:sha256:{graph_sha}",
        **graph_core,
    }


def _bind_component(component: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if component is None:
        return None
    bound = copy.deepcopy(dict(component))
    bound["componentId"] = _component_id(bound)
    return bound


def build_phase4_study_payload(
    *,
    phase3_baseline: Mapping[str, Any],
    dynamic_state: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    created_at: str,
    code_revision: str,
    lineup: Mapping[str, Any] | None = None,
    starter_duration: Mapping[str, Any] | None = None,
    bullpen_usage: Mapping[str, Any] | None = None,
    project_id: str = PROJECT_ID,
    dataset: Mapping[str, Any] | None = None,
    identity_bridge: Mapping[str, Any] | None = None,
    decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind runner evidence to deterministic study, component, and graph IDs."""

    if decision is not None and dict(decision) != _FROZEN_STUDY_DECISION:
        raise SportsPhase4RegistryError(
            "Phase 4 study decision is registry-governed and may not be overridden"
        )

    baseline = copy.deepcopy(dict(phase3_baseline))
    components: dict[str, dict[str, Any] | None] = {
        "dynamicState": _bind_component(dynamic_state),
        "lineup": _bind_component(lineup),
        "starterDuration": _bind_component(starter_duration),
        "bullpenUsage": _bind_component(bullpen_usage),
    }
    payload: dict[str, Any] = {
        "schemaVersion": STUDY_SCHEMA_VERSION,
        "studyId": "",
        "studySha": "",
        "studyIdentity": {
            "schemaVersion": STUDY_IDENTITY_SCHEMA_VERSION,
            "coreSha": "",
            "createdAt": created_at,
            "codeRevision": code_revision,
        },
        "projectId": project_id,
        "dataset": copy.deepcopy(
            dict(dataset)
            if dataset is not None
            else {
                "registrationId": REGISTRATION_ID,
                "manifestSha": MANIFEST_SHA,
                "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
            }
        ),
        "identityBridge": copy.deepcopy(
            dict(identity_bridge)
            if identity_bridge is not None
            else {
                "registrationId": BRIDGE_REGISTRATION_ID,
                "manifestSha": BRIDGE_MANIFEST_SHA,
                "joinAuditId": dynamic_state["descriptor"]["authorityBindings"][
                    "identityBridge"
                ]["joinAuditId"],
            }
        ),
        "phase3Baseline": baseline,
        "components": components,
        "artifacts": sorted(
            (copy.deepcopy(dict(item)) for item in artifacts),
            key=lambda item: str(item.get("artifactId", "")),
        ),
        "graph": build_phase4_graph(components, phase3_graph_id=str(baseline["graphId"])),
        "decision": copy.deepcopy(_FROZEN_STUDY_DECISION),
    }
    core_sha = semantic_study_core_sha(payload)
    payload["studyIdentity"]["coreSha"] = core_sha
    payload["studyId"] = f"sports-phase4-study:sha256:{core_sha}"
    payload["studySha"] = semantic_study_sha(payload)
    return payload


def _validate_artifacts(value: Any) -> tuple[list[dict[str, Any]], set[str]]:
    artifacts = _list(value, label="artifacts")
    if artifacts != sorted(artifacts, key=lambda item: str(item.get("artifactId", "")) if isinstance(item, Mapping) else ""):
        raise SportsPhase4RegistryError("Artifacts must be in canonical artifactId order")
    validated: list[dict[str, Any]] = []
    ids: set[str] = set()
    uris: set[str] = set()
    hashes: set[str] = set()
    for index, raw in enumerate(artifacts):
        artifact = _mapping(raw, label=f"artifacts[{index}]")
        _exact_keys(artifact, _ARTIFACT_KEYS, label=f"artifacts[{index}]")
        artifact_id = _nonblank(artifact["artifactId"], label=f"artifacts[{index}].artifactId")
        artifact_type = _nonblank(artifact["artifactType"], label=f"artifacts[{index}].artifactType")
        digest = _sha(artifact["sha256"], label=f"artifacts[{index}].sha256")
        uri = _nonblank(artifact["logicalUri"], label=f"artifacts[{index}].logicalUri")
        rule = _ARTIFACT_FILENAME_RULES.get(artifact_type)
        filename = uri.rsplit("/", 1)[-1]
        runtime_namespace = (
            "mlb-dynamic-player-state-v1"
            if artifact_type in _DYNAMIC_ARTIFACT_TYPES
            else "mlb-participation-usage-v1"
        )
        governed_object_prefix = (
            f"{RUNTIME_LOGICAL_PREFIX}{runtime_namespace}/objects/sha256/"
            f"{digest[:2]}/{digest}/"
        )
        if (
            not uri.startswith(governed_object_prefix)
            or "\\" in uri
            or "?" in uri
            or "#" in uri
            or "%" in uri
            or any(part in {"", ".", ".."} for part in uri[len(RUNTIME_LOGICAL_PREFIX):].split("/"))
            or uri.count(governed_object_prefix) != 1
        ):
            raise SportsPhase4RegistryError(f"artifacts[{index}].logicalUri differs from the governed namespace")
        if artifact_id != f"sports-phase4-artifact:{artifact_type.casefold()}:sha256:{digest}":
            raise SportsPhase4RegistryError(f"artifacts[{index}].artifactId is not content-bound")
        if rule is None:
            raise SportsPhase4RegistryError(f"artifacts[{index}].artifactType is not governed")
        expected_media_type, filename_rule = rule
        if artifact["mediaType"] != expected_media_type or filename_rule.fullmatch(filename) is None:
            raise SportsPhase4RegistryError(
                f"artifacts[{index}] media type or governed filename differs for {artifact_type}"
            )
        if type(artifact["byteCount"]) is not int or artifact["byteCount"] < 0:
            raise SportsPhase4RegistryError(f"artifacts[{index}].byteCount must be non-negative")
        if artifact_id in ids or uri in uris or digest in hashes:
            raise SportsPhase4RegistryError("Artifact identities, logical URIs, and hashes must be unique")
        ids.add(artifact_id)
        uris.add(uri)
        hashes.add(digest)
        validated.append(artifact)
    if not validated:
        raise SportsPhase4RegistryError("At least one Phase 4 artifact reference is required")
    return validated, ids


def _validate_dynamic_artifact_inventory(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    completed: bool,
) -> None:
    if not completed:
        return
    type_counts = Counter(str(item["artifactType"]) for item in artifacts)
    if dict(type_counts) != _DYNAMIC_COMPLETED_ARTIFACT_CARDINALITIES:
        raise SportsPhase4RegistryError(
            "Completed dynamic artifact cardinality differs from the frozen 32-reference inventory"
        )
    filenames_by_type: dict[str, set[str]] = {
        "DYNAMIC_MODEL_STATE": set(),
        "DYNAMIC_PREPROCESSOR_STATE": set(),
    }
    for artifact in artifacts:
        artifact_type = str(artifact["artifactType"])
        if artifact_type in filenames_by_type:
            filenames_by_type[artifact_type].add(
                str(artifact["logicalUri"]).rsplit("/", 1)[-1]
            )
    if (
        filenames_by_type["DYNAMIC_MODEL_STATE"] != _DYNAMIC_MODEL_FILENAMES
        or filenames_by_type["DYNAMIC_PREPROCESSOR_STATE"]
        != _DYNAMIC_PREPROCESSOR_FILENAMES
    ):
        raise SportsPhase4RegistryError(
            "Completed dynamic model/preprocessor artifact coverage differs"
        )


def _expected_participation_artifact_pairs(
    component: Mapping[str, Any],
    *,
    slot: str,
) -> set[tuple[str, str]]:
    component_type = str(component["componentType"])
    token = component_type.casefold()
    feature_type, feature_filename = {
        "lineup": ("LINEUP_PROJECTION_FEATURE_VIEW", "lineup-feature-view.parquet"),
        "starterDuration": (
            "STARTER_DURATION_FEATURE_VIEW",
            "starter-feature-view.parquet",
        ),
        "bullpenUsage": (
            "BULLPEN_USAGE_FEATURE_VIEW",
            "bullpen-feature-view.parquet",
        ),
    }[slot]
    expected = {
        (feature_type, feature_filename),
        ("PARTICIPATION_CONTRACT_SET", "participation-contract-set.json"),
        ("DYNAMIC_STATE_BINDING", "dynamic-state-binding.json"),
        ("PARTICIPATION_COVERAGE", "participation-coverage.json"),
        ("FEATURE_CHECKPOINT", "feature-checkpoint.json"),
        (
            f"{component_type}_FOLD_2024_PREDICTIONS",
            f"{token}-fold-2024-predictions.parquet",
        ),
        (
            f"{component_type}_FOLD_2025_PREDICTIONS",
            f"{token}-fold-2025-predictions.parquet",
        ),
        ("EXPERIMENT_EVIDENCE", f"{token}-experiment.json"),
        ("CANDIDATE_POOL_EVIDENCE", f"{token}-candidate-pool.json"),
        ("METRICS_EVIDENCE", f"{token}-metrics.json"),
        ("CALIBRATION_EVIDENCE", f"{token}-calibration.json"),
        ("LINEAGE_EVIDENCE", f"{token}-lineage.json"),
        ("DECISION_EVIDENCE", f"{token}-decision.json"),
        ("BOOTSTRAP_EVIDENCE", f"{token}-bootstrap.json"),
        ("COMPONENT_CARD", f"{token}-component-card.json"),
        ("FINAL_CHECKPOINT", "final-checkpoint.json"),
    }
    for candidate in _list(component["candidates"], label=f"{slot} candidates"):
        candidate_row = _mapping(candidate, label=f"{slot} candidate")
        candidate_id = _nonblank(
            candidate_row.get("candidateId"), label=f"{slot} candidate ID"
        )
        for fold in _list(
            candidate_row.get("foldMetrics"),
            label=f"{slot} {candidate_id} folds",
        ):
            fold_row = _mapping(fold, label=f"{slot} {candidate_id} fold")
            if fold_row.get("status") == "COMPLETE":
                season = fold_row.get("validationSeason")
                expected.add(
                    (
                        "MODEL_STATE",
                        f"{token}-{candidate_id}-validate-{season}.json",
                    )
                )
    return expected


def _validate_participation_artifact_inventory(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    components: Mapping[str, Mapping[str, Any] | None],
) -> None:
    participation_slots = ("lineup", "starterDuration", "bullpenUsage")
    configured = {
        slot: components[slot]
        for slot in participation_slots
        if components[slot] is not None
    }
    participation_artifacts = [
        artifact
        for artifact in artifacts
        if artifact["artifactType"] not in _DYNAMIC_ARTIFACT_TYPES
    ]
    if not configured:
        if participation_artifacts:
            raise SportsPhase4RegistryError(
                "Participation artifacts require governed participation components"
            )
        return
    by_id = {str(artifact["artifactId"]): artifact for artifact in participation_artifacts}
    by_pair: dict[tuple[str, str], Mapping[str, Any]] = {}
    for artifact in participation_artifacts:
        pair = (
            str(artifact["artifactType"]),
            str(artifact["logicalUri"]).rsplit("/", 1)[-1],
        )
        if pair in by_pair:
            raise SportsPhase4RegistryError(
                "Participation artifact type/filename identities must be unique"
            )
        by_pair[pair] = artifact
    expected_union: set[tuple[str, str]] = set()
    for slot, component in configured.items():
        assert component is not None
        expected = _expected_participation_artifact_pairs(component, slot=slot)
        expected_union.update(expected)
        owned_pairs: set[tuple[str, str]] = set()
        for artifact_id in component["artifactIds"]:
            artifact = by_id.get(str(artifact_id))
            if artifact is None:
                raise SportsPhase4RegistryError(
                    f"components.{slot} owns a non-participation artifact"
                )
            owned_pairs.add(
                (
                    str(artifact["artifactType"]),
                    str(artifact["logicalUri"]).rsplit("/", 1)[-1],
                )
            )
        if owned_pairs != expected:
            raise SportsPhase4RegistryError(
                f"components.{slot} artifact ownership differs from its frozen runner inventory"
            )
    if set(by_pair) != expected_union:
        raise SportsPhase4RegistryError(
            "Participation artifact union differs from the frozen runner inventory"
        )


def _validate_graph(
    value: Any,
    *,
    components: Mapping[str, Mapping[str, Any] | None],
    phase3_graph_id: str,
) -> dict[str, Any]:
    graph = _mapping(value, label="graph")
    _exact_keys(graph, _GRAPH_KEYS, label="graph")
    expected = build_phase4_graph(components, phase3_graph_id=phase3_graph_id)
    if graph != expected:
        raise SportsPhase4RegistryError("Phase 4 graph differs from registry-derived authority")
    for index, node in enumerate(graph["nodes"]):
        _exact_keys(_mapping(node, label=f"graph.nodes[{index}]"), _NODE_KEYS, label=f"graph.nodes[{index}]")
    for index, edge in enumerate(graph["edges"]):
        _exact_keys(_mapping(edge, label=f"graph.edges[{index}]"), _EDGE_KEYS, label=f"graph.edges[{index}]")
    return graph


def validate_phase4_study_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, label="Phase 4 study")
    _exact_keys(payload, _TOP_KEYS, label="Phase 4 study")
    if payload["schemaVersion"] != STUDY_SCHEMA_VERSION:
        raise SportsPhase4RegistryError("Phase 4 study schema version differs")
    identity = _mapping(payload["studyIdentity"], label="studyIdentity")
    _exact_keys(identity, _IDENTITY_KEYS, label="studyIdentity")
    if identity["schemaVersion"] != STUDY_IDENTITY_SCHEMA_VERSION:
        raise SportsPhase4RegistryError("Study identity schema version differs")
    try:
        parsed_created_at = datetime.fromisoformat(_nonblank(identity["createdAt"], label="studyIdentity.createdAt"))
    except ValueError as exc:
        raise SportsPhase4RegistryError("studyIdentity.createdAt must be ISO-8601") from exc
    if parsed_created_at.utcoffset() is None:
        raise SportsPhase4RegistryError("studyIdentity.createdAt must include a UTC offset")
    _nonblank(identity["codeRevision"], label="studyIdentity.codeRevision")
    expected_core = semantic_study_core_sha(payload)
    if identity["coreSha"] != expected_core:
        raise SportsPhase4RegistryError("Study identity core digest differs")
    if payload["studyId"] != f"sports-phase4-study:sha256:{expected_core}":
        raise SportsPhase4RegistryError("studyId is not bound to the governed core")
    if payload["studySha"] != semantic_study_sha(payload):
        raise SportsPhase4RegistryError("studySha differs from the full study payload")
    if payload["projectId"] != PROJECT_ID:
        raise SportsPhase4RegistryError("Phase 4 project authority differs")

    dataset = _mapping(payload["dataset"], label="dataset")
    _exact_keys(dataset, _DATASET_KEYS, label="dataset")
    if dataset != {
        "registrationId": REGISTRATION_ID,
        "manifestSha": MANIFEST_SHA,
        "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
    }:
        raise SportsPhase4RegistryError("Phase 4 dataset authority differs")
    bridge = _mapping(payload["identityBridge"], label="identityBridge")
    _exact_keys(bridge, _BRIDGE_KEYS, label="identityBridge")
    if bridge["registrationId"] != BRIDGE_REGISTRATION_ID or bridge["manifestSha"] != BRIDGE_MANIFEST_SHA:
        raise SportsPhase4RegistryError("Phase 4 identity-bridge authority differs")
    if bridge["joinAuditId"] != PHASE4_JOIN_AUDIT_ID:
        raise SportsPhase4RegistryError("Phase 4 identity join-audit authority differs")

    phase3 = _mapping(payload["phase3Baseline"], label="phase3Baseline")
    _exact_keys(phase3, _PHASE3_KEYS, label="phase3Baseline")
    if (
        phase3["runId"] != PHASE3_RUN_ID
        or phase3["runSha"] != PHASE3_RUN_SHA
        or phase3["experimentId"] != PHASE3_EXPERIMENT_ID
        or phase3["featureContractName"] != PHASE3_FEATURE_CONTRACT_NAME
        or phase3["featureContractSha"] != PHASE3_FEATURE_CONTRACT_SHA
        or phase3["featureViewId"] != PHASE3_FEATURE_VIEW_ID
        or phase3["graphId"] != PHASE3_GRAPH_ID
        or phase3["status"] != PHASE3_TERMINAL_STATUS
    ):
        raise SportsPhase4RegistryError("Frozen Phase 3 baseline authority differs")
    for key in ("experimentId", "featureContractName", "graphId"):
        _nonblank(phase3[key], label=f"phase3Baseline.{key}")

    components = _mapping(payload["components"], label="components")
    if set(components) != set(COMPONENT_SLOTS):
        raise SportsPhase4RegistryError("Phase 4 component slots differ")
    validated_components = {
        slot: _validate_component(components[slot], slot=slot)
        for slot in COMPONENT_SLOTS
    }
    dynamic_descriptor = validated_components["dynamicState"]["descriptor"]
    dynamic_bindings = _mapping(
        dynamic_descriptor["authorityBindings"], label="dynamic authority bindings"
    )
    dynamic_dataset = _mapping(
        dynamic_bindings["dataset"], label="dynamic dataset authority"
    )
    dynamic_bridge = _mapping(
        dynamic_bindings["identityBridge"], label="dynamic bridge authority"
    )
    dynamic_phase3 = _mapping(
        dynamic_bindings["phase3"], label="dynamic Phase 3 authority"
    )
    if (
        dynamic_dataset.get("registrationId") != dataset["registrationId"]
        or dynamic_dataset.get("manifestSha") != dataset["manifestSha"]
        or dynamic_dataset.get("partitionAuthoritySha") != dataset["partitionAuthoritySha"]
        or dynamic_bridge.get("registrationId") != bridge["registrationId"]
        or dynamic_bridge.get("manifestSha") != bridge["manifestSha"]
        or dynamic_bridge.get("joinAuditId") != bridge["joinAuditId"]
        or dynamic_phase3.get("runId") != phase3["runId"]
        or dynamic_phase3.get("runSha") != phase3["runSha"]
        or dynamic_phase3.get("featureContractSha") != phase3["featureContractSha"]
        or dynamic_phase3.get("featureViewId") != phase3["featureViewId"]
    ):
        raise SportsPhase4RegistryError("Dynamic descriptor does not repeat the exact study authorities")

    artifacts, artifact_ids = _validate_artifacts(payload["artifacts"])
    used_artifacts: set[str] = set()
    for slot, component in validated_components.items():
        if component is None:
            continue
        references = set(component["artifactIds"])
        if not references.issubset(artifact_ids):
            raise SportsPhase4RegistryError(f"components.{slot} references an unregistered artifact")
        used_artifacts.update(references)
    if used_artifacts != artifact_ids:
        raise SportsPhase4RegistryError("Every Phase 4 artifact must be owned by a component")
    artifacts_by_id = {artifact["artifactId"]: artifact for artifact in artifacts}
    dynamic_component = validated_components["dynamicState"]
    assert dynamic_component is not None
    dynamic_artifacts = [
        artifact
        for artifact in artifacts
        if artifact["artifactType"] in _DYNAMIC_ARTIFACT_TYPES
    ]
    dynamic_artifact_ids = {
        artifact["artifactId"] for artifact in dynamic_artifacts
    }
    if set(dynamic_component["artifactIds"]) != dynamic_artifact_ids:
        raise SportsPhase4RegistryError(
            "Dynamic component artifact inventory differs from the governed dynamic namespace"
        )
    dynamic_decision = _decision_value(dynamic_component, slot="dynamicState")
    _validate_dynamic_artifact_inventory(
        dynamic_artifacts,
        completed=not dynamic_decision.endswith("BLOCKED"),
    )
    callback_component = copy.deepcopy(dict(dynamic_component))
    callback_core = dict(callback_component)
    callback_core.pop("componentId", None)
    callback_component["componentId"] = (
        "sports-phase4-component:dynamic-player-state:sha256:"
        + sha256_bytes(canonical_json_bytes(callback_core))
    )
    try:
        validate_dynamic_component_evidence(
            callback_component,
            artifact_references=dynamic_artifacts,
        )
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise SportsPhase4RegistryError(
            f"Dynamic artifact inventory differs from its frozen runner contract: {exc}"
        ) from exc
    _validate_participation_artifact_inventory(
        artifacts,
        components=validated_components,
    )
    for label, descriptor_name in (
        ("dynamic state", "dynamicState"),
        ("dynamic history", "historyIndex"),
    ):
        reference = _mapping(
            dynamic_descriptor[descriptor_name], label=f"{label} descriptor"
        )
        registered = artifacts_by_id.get(reference.get("artifactId"))
        if registered is None or registered != {
            "artifactId": reference["artifactId"],
            "artifactType": (
                "DYNAMIC_PLAYER_STATE"
                if descriptor_name == "dynamicState"
                else "DYNAMIC_HISTORY_INDEX"
            ),
            "logicalUri": reference["logicalUri"],
            "sha256": reference["artifactSha"],
            "byteCount": reference["artifactBytes"],
            "mediaType": reference["mediaType"],
        }:
            raise SportsPhase4RegistryError(
                f"{label} descriptor does not match its registered artifact"
            )

    _validate_graph(
        payload["graph"],
        components=validated_components,
        phase3_graph_id=phase3["graphId"],
    )
    decision = _mapping(payload["decision"], label="decision")
    _exact_keys(decision, _DECISION_KEYS, label="decision")
    if decision != _FROZEN_STUDY_DECISION:
        raise SportsPhase4RegistryError("Phase 4 research decision authority differs")
    _scan_public_safety(payload)
    return copy.deepcopy(payload)


class SportsPhase4Registry:
    def __init__(self, database: Database) -> None:
        self.database = database

    def validate_registered_authorities(self) -> dict[str, str]:
        """Read-only fail-closed preflight for every frozen Phase 4 parent."""

        authorities = {
            "projectId": PROJECT_ID,
            "dataset": {
                "registrationId": REGISTRATION_ID,
                "manifestSha": MANIFEST_SHA,
                "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
            },
            "identityBridge": {
                "registrationId": BRIDGE_REGISTRATION_ID,
                "manifestSha": BRIDGE_MANIFEST_SHA,
                "joinAuditId": PHASE4_JOIN_AUDIT_ID,
            },
            "phase3Baseline": {
                "runId": PHASE3_RUN_ID,
                "runSha": PHASE3_RUN_SHA,
                "experimentId": PHASE3_EXPERIMENT_ID,
                "featureContractName": PHASE3_FEATURE_CONTRACT_NAME,
                "featureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
                "featureViewId": PHASE3_FEATURE_VIEW_ID,
                "graphId": PHASE3_GRAPH_ID,
                "status": PHASE3_TERMINAL_STATUS,
            },
        }
        with self.database.connection() as connection:
            self._require_authorities(connection, authorities)
        phase3_payload = self._validated_phase3_parent_payload()
        with self.database.connection() as connection:
            self._assert_phase3_parent_rows(connection, phase3_payload)
        return {
            "datasetRegistrationId": REGISTRATION_ID,
            "projectId": PROJECT_ID,
            "identityBridgeRegistrationId": BRIDGE_REGISTRATION_ID,
            "joinAuditId": PHASE4_JOIN_AUDIT_ID,
            "phase3RunId": PHASE3_RUN_ID,
            "phase3FeatureViewId": PHASE3_FEATURE_VIEW_ID,
            "phase3GraphId": PHASE3_GRAPH_ID,
        }

    def _validated_phase3_parent_payload(self) -> dict[str, Any]:
        public = SportsPAResearchRegistry(self.database).public_active()
        baseline = (
            public.get("paBaseline") if isinstance(public, Mapping) else None
        )
        if not isinstance(baseline, Mapping):
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 public parent is unavailable"
            )
        run = baseline.get("run")
        registry = baseline.get("registry")
        feature = baseline.get("featureView")
        if not all(
            isinstance(value, Mapping) for value in (run, registry, feature)
        ):
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 public parent is incomplete"
            )
        feature_payload = dict(feature)
        feature_payload.pop("contractSha", None)
        candidates: list[dict[str, Any]] = []
        for raw_candidate in baseline.get("candidates") or []:
            if not isinstance(raw_candidate, Mapping):
                raise SportsPhase4RegistryError(
                    "Exact active frozen Phase 3 candidate evidence is malformed"
                )
            candidate = copy.deepcopy(dict(raw_candidate))
            candidate.pop("selected", None)
            for fold in candidate.get("foldMetrics") or []:
                if not isinstance(fold, dict):
                    raise SportsPhase4RegistryError(
                        "Exact active frozen Phase 3 fold evidence is malformed"
                    )
                fold.pop("predictionArtifact", None)
            candidates.append(candidate)

        # Phase 3 intentionally persists child rows without caller list ordinals.
        # Reconstruct the one governed runner order before recomputing its
        # content digests, while retaining every persisted child body so a
        # direct-SQL mutation is still observed by the Phase 3 validator.
        selected = baseline.get("selected")
        graph_payload = copy.deepcopy(baseline.get("graph"))
        if not isinstance(selected, Mapping) or not isinstance(graph_payload, Mapping):
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 graph authority is incomplete"
            )
        selected_candidate_id = selected.get("candidateId")
        candidates_by_id = {
            str(candidate.get("candidateId")): candidate
            for candidate in candidates
        }
        if type(selected_candidate_id) is not str or selected_candidate_id not in candidates_by_id:
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 selection authority is incomplete"
            )
        expected_nodes, expected_edges = _phase3_complete_graph_authority(
            candidates_by_id,
            selected_id=selected_candidate_id,
        )
        observed_nodes = graph_payload.get("nodes")
        observed_edges = graph_payload.get("edges")
        if not isinstance(observed_nodes, list) or not isinstance(observed_edges, list):
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 graph child rows are malformed"
            )
        nodes_by_id = {
            item.get("nodeId"): copy.deepcopy(item)
            for item in observed_nodes
            if isinstance(item, Mapping) and type(item.get("nodeId")) is str
        }
        edges_by_id = {
            item.get("edgeId"): copy.deepcopy(item)
            for item in observed_edges
            if isinstance(item, Mapping) and type(item.get("edgeId")) is str
        }
        if (
            len(nodes_by_id) != len(observed_nodes)
            or set(nodes_by_id) != {item["nodeId"] for item in expected_nodes}
            or len(edges_by_id) != len(observed_edges)
            or set(edges_by_id) != {item["edgeId"] for item in expected_edges}
        ):
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 graph child identities differ"
            )
        graph_payload["nodes"] = [
            nodes_by_id[item["nodeId"]] for item in expected_nodes
        ]
        graph_payload["edges"] = [
            edges_by_id[item["edgeId"]] for item in expected_edges
        ]

        artifacts = registry.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 artifact authority is incomplete"
            )
        artifact_rows = [copy.deepcopy(item) for item in artifacts]
        if not all(isinstance(item, Mapping) for item in artifact_rows):
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 artifact child rows are malformed"
            )
        generic_ordinals: list[int] = []
        generic_order = True
        for item in artifact_rows:
            if item.get("artifactType") == "FEATURE_VIEW":
                generic_ordinals.append(-1)
                continue
            filename = str(item.get("logicalUri", "")).rsplit("/", 1)[-1]
            match = re.fullmatch(r"artifact-(\d+)\.(?:json|parquet)", filename)
            if match is None:
                generic_order = False
                break
            generic_ordinals.append(int(match.group(1)))
        if generic_order:
            artifact_rows = [
                row
                for _, row in sorted(
                    zip(generic_ordinals, artifact_rows, strict=True),
                    key=lambda pair: pair[0],
                )
            ]
        else:
            fixed_artifact_order = {
                "FEATURE_VIEW": 0,
                "FEATURE_VIEW_RUN_BINDING": 1,
                "FEATURE_CONTRACT": 2,
                "FEATURE_SCHEMA": 3,
                "CLASS_ORDER": 4,
                "FOLD_2024_PREDICTIONS": 6,
                "FOLD_2025_PREDICTIONS": 7,
                "EXPERIMENT_METRICS": 8,
                "CONFUSION_MATRICES": 9,
                "CALIBRATION_EVIDENCE": 10,
                "BOOTSTRAP_EVIDENCE": 11,
                "LINEAGE": 12,
                "MODEL_CARD": 13,
                "FINAL_CHECKPOINT": 14,
            }

            def runner_artifact_order(item: Mapping[str, Any]) -> tuple[Any, ...]:
                artifact_type = str(item.get("artifactType", ""))
                filename = str(item.get("logicalUri", "")).rsplit("/", 1)[-1]
                model_match = re.fullmatch(
                    r"(model|preprocessor)-(C\d+)-validate-(2024|2025)\.json",
                    filename,
                )
                if model_match is not None and artifact_type in {
                    "MODEL_STATE",
                    "PREPROCESSOR_STATE",
                }:
                    return (
                        5,
                        int(model_match.group(3)),
                        model_match.group(2),
                        0 if model_match.group(1) == "model" else 1,
                    )
                return (
                    fixed_artifact_order.get(artifact_type, 99),
                    0,
                    "",
                    filename,
                )

            artifact_rows.sort(key=runner_artifact_order)
        payload = {
            "schemaVersion": run.get("schemaVersion"),
            "runId": run.get("runId"),
            "runSha": run.get("runSha"),
            "runIdentity": run.get("runIdentity"),
            "projectId": run.get("projectId"),
            "parent": run.get("parent"),
            "identityBridge": run.get("identityBridge"),
            "classOrder": run.get("classOrder"),
            "featureView": feature_payload,
            "experiment": run.get("experiment"),
            "candidates": candidates,
            "selected": selected,
            "calibration": baseline.get("calibration"),
            "bootstrapComparisons": baseline.get("bootstrapComparisons"),
            "artifacts": artifact_rows,
            "graph": graph_payload,
            "decision": baseline.get("decision"),
        }
        try:
            validated = _validate_phase3_payload(payload)
        except SportsPARegistryError as exc:
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 child evidence differs"
            ) from exc
        if (
            validated["runId"] != PHASE3_RUN_ID
            or validated["runSha"] != PHASE3_RUN_SHA
            or validated["featureView"]["featureViewId"] != PHASE3_FEATURE_VIEW_ID
            or validated["graph"]["graphId"] != PHASE3_GRAPH_ID
        ):
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 public authority differs"
            )
        return validated

    def _assert_phase3_parent_rows(
        self,
        connection: Any,
        phase3_payload: Mapping[str, Any],
    ) -> None:
        existing = decode_row(
            connection.execute(
                "SELECT * FROM sports_pa_research_runs WHERE run_id = ?",
                (PHASE3_RUN_ID,),
            ).fetchone()
        )
        if existing is None:
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 row is unavailable"
            )
        try:
            SportsPAResearchRegistry(self.database)._assert_existing_run(
                connection,
                existing,
                phase3_payload,
            )
        except SportsPARegistryError as exc:
            raise SportsPhase4RegistryError(
                "Exact active frozen Phase 3 persisted child rows differ"
            ) from exc

    @staticmethod
    def _require_study_partition_authorities(
        connection: Any,
        payload: Mapping[str, Any],
    ) -> None:
        descriptor = _mapping(
            payload["components"]["dynamicState"]["descriptor"],
            label="dynamic descriptor",
        )
        source = _mapping(descriptor["source"], label="dynamic source")
        phase3 = _mapping(descriptor["phase3"], label="dynamic Phase 3 source")
        dynamic_ids = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT partition_id
                FROM sports_dataset_partitions
                WHERE registration_id = ?
                  AND family = 'plate_appearance'
                  AND season BETWEEN 2021 AND 2025
                ORDER BY partition_id
                """,
                (REGISTRATION_ID,),
            ).fetchall()
        ]
        phase3_ids = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT partition_id
                FROM sports_dataset_partitions
                WHERE registration_id = ?
                  AND (
                    (family = 'plate_appearance' AND season BETWEEN 2023 AND 2025)
                    OR (family = 'player_prior' AND season BETWEEN 2021 AND 2024)
                  )
                ORDER BY partition_id
                """,
                (REGISTRATION_ID,),
            ).fetchall()
        ]
        if (
            len(dynamic_ids) != EXPECTED_SOURCE_PARTITION_COUNT
            or source.get("partitionIds") != dynamic_ids
            or len(phase3_ids) != 26
            or phase3.get("featureSourcePartitionIds") != phase3_ids
        ):
            raise SportsPhase4RegistryError(
                "Dynamic and Phase 3 source partition lineage differs from the registered dataset"
            )

    @staticmethod
    def _require_authorities(connection: Any, payload: Mapping[str, Any]) -> None:
        dataset = decode_row(
            connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE registration_id = ?",
                (payload["dataset"]["registrationId"],),
            ).fetchone()
        )
        project = decode_row(
            connection.execute(
                "SELECT * FROM sports_research_projects WHERE project_id = ?",
                (payload["projectId"],),
            ).fetchone()
        )
        bridge = decode_row(
            connection.execute(
                "SELECT * FROM sports_identity_bridge_registrations WHERE bridge_registration_id = ?",
                (payload["identityBridge"]["registrationId"],),
            ).fetchone()
        )
        audit = decode_row(
            connection.execute(
                "SELECT * FROM sports_identity_join_audits WHERE join_audit_id = ?",
                (payload["identityBridge"]["joinAuditId"],),
            ).fetchone()
        )
        parent_metadata = (dataset or {}).get("metadata_json") or {}
        if (
            not dataset
            or dataset.get("manifest_sha") != MANIFEST_SHA
            or dataset.get("validation_status") != "VALID"
            or int(dataset.get("active", 0)) != 1
            or parent_metadata.get("partitionAuthoritySha") != PARTITION_AUTHORITY_SHA
        ):
            raise SportsPhase4RegistryError("Exact active parent dataset registration is unavailable")
        if not project or project.get("registration_id") != REGISTRATION_ID:
            raise SportsPhase4RegistryError("Exact sports research project is unavailable")
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
        limitation_ids = tuple(
            item.get("limitation_id") if type(item) is dict else None
            for item in ((bridge or {}).get("limitations_json") or [])
        )
        if (
            not bridge
            or any(
                bridge.get(key) != expected
                for key, expected in expected_bridge.items()
            )
            or bridge.get("rights_json") != expected_rights
            or limitation_ids != EXPECTED_LIMITATION_IDS
        ):
            raise SportsPhase4RegistryError("Exact active identity bridge is unavailable")
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
            raise SportsPhase4RegistryError("Exact passing identity join audit is unavailable")
        try:
            _validate_join_audit_authority(
                audit,
                bridge=bridge,
                class_order=list(PA_CLASS_ORDER),
            )
        except SportsPARegistryError as exc:
            raise SportsPhase4RegistryError(
                "Exact passing identity join audit authority differs"
            ) from exc

        phase3 = payload["phase3Baseline"]
        run = decode_row(
            connection.execute(
                "SELECT * FROM sports_pa_research_runs WHERE run_id = ?",
                (phase3["runId"],),
            ).fetchone()
        )
        experiment = decode_row(
            connection.execute(
                "SELECT * FROM sports_pa_experiments WHERE run_id = ? AND experiment_id = ?",
                (phase3["runId"], phase3["experimentId"]),
            ).fetchone()
        )
        feature = decode_row(
            connection.execute(
                "SELECT * FROM sports_pa_feature_views WHERE feature_view_id = ?",
                (phase3["featureViewId"],),
            ).fetchone()
        )
        graph = decode_row(
            connection.execute(
                "SELECT * FROM sports_pa_model_graphs WHERE run_id = ? AND graph_id = ?",
                (phase3["runId"], phase3["graphId"]),
            ).fetchone()
        )
        if (
            not run
            or run.get("run_sha") != phase3["runSha"]
            or run.get("project_id") != PROJECT_ID
            or run.get("parent_dataset_registration_id") != REGISTRATION_ID
            or run.get("parent_manifest_sha") != MANIFEST_SHA
            or run.get("parent_partition_authority_sha") != PARTITION_AUTHORITY_SHA
            or run.get("identity_bridge_registration_id") != BRIDGE_REGISTRATION_ID
            or run.get("identity_bridge_manifest_sha") != BRIDGE_MANIFEST_SHA
            or run.get("identity_join_audit_id") != payload["identityBridge"]["joinAuditId"]
            or run.get("feature_view_id") != phase3["featureViewId"]
            or run.get("class_order_json") != list(PA_CLASS_ORDER)
            or run.get("terminal_status") != PHASE3_TERMINAL_STATUS
            or int(run.get("active", 0)) != 1
            or experiment is None
            or graph is None
            or feature is None
            or feature.get("project_id") != PROJECT_ID
            or feature.get("parent_dataset_registration_id") != REGISTRATION_ID
            or feature.get("identity_bridge_registration_id") != BRIDGE_REGISTRATION_ID
            or feature.get("contract_name") != "MLB_PA_FEATURE_VIEW"
            or feature.get("contract_version") != phase3["featureContractName"]
            or feature.get("contract_sha") != phase3["featureContractSha"]
            or feature.get("content_sha") != PHASE3_FEATURE_CONTENT_SHA
            or feature.get("artifact_sha") != PHASE3_FEATURE_ARTIFACT_SHA
        ):
            raise SportsPhase4RegistryError("Exact active frozen Phase 3 parent is unavailable")

    @staticmethod
    def _study_row(payload: Mapping[str, Any], *, recorded_at: str, user_id: str) -> dict[str, Any]:
        identity = payload["studyIdentity"]
        dataset = payload["dataset"]
        bridge = payload["identityBridge"]
        phase3 = payload["phase3Baseline"]
        return {
            "study_id": payload["studyId"],
            "study_sha": payload["studySha"],
            "core_sha": identity["coreSha"],
            "identity_schema_version": identity["schemaVersion"],
            "study_created_at": identity["createdAt"],
            "code_revision": identity["codeRevision"],
            "schema_version": payload["schemaVersion"],
            "project_id": payload["projectId"],
            "dataset_registration_id": dataset["registrationId"],
            "dataset_manifest_sha": dataset["manifestSha"],
            "dataset_partition_authority_sha": dataset["partitionAuthoritySha"],
            "identity_bridge_registration_id": bridge["registrationId"],
            "identity_bridge_manifest_sha": bridge["manifestSha"],
            "identity_join_audit_id": bridge["joinAuditId"],
            "phase3_run_id": phase3["runId"],
            "phase3_run_sha": phase3["runSha"],
            "phase3_experiment_id": phase3["experimentId"],
            "phase3_feature_contract_name": phase3["featureContractName"],
            "phase3_feature_contract_sha": phase3["featureContractSha"],
            "phase3_feature_view_id": phase3["featureViewId"],
            "phase3_graph_id": phase3["graphId"],
            "phase3_status": phase3["status"],
            "decision_json": payload["decision"],
            "registered_at": recorded_at,
            "last_validated_at": recorded_at,
            "registered_by": user_id,
            "active": 1,
        }

    @staticmethod
    def _terminal_status(component: Mapping[str, Any], *, slot: str) -> str:
        return _decision_value(component, slot=slot)

    @staticmethod
    def _phase4_workflow_overlay(
        workflow: Mapping[str, Any],
        *,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        updated = copy.deepcopy(dict(workflow))
        components = payload["components"]
        study_id = payload["studyId"]
        phase3_run_id = payload["phase3Baseline"]["runId"]
        graph_id = payload["graph"]["graphId"]
        dynamic = components["dynamicState"]
        dynamic_decision = _decision_value(dynamic, slot="dynamicState")
        dynamic_status = "BLOCKED" if dynamic_decision.endswith("BLOCKED") else "COMPLETE"
        participation_slots = ("lineup", "starterDuration", "bullpenUsage")
        configured = {
            slot: components[slot]
            for slot in participation_slots
            if components[slot] is not None
        }
        participation_decisions = {
            slot: _decision_value(component, slot=slot)
            for slot, component in configured.items()
        }
        if not configured:
            participation_status = "NOT_CONFIGURED"
        elif all(value.endswith("BLOCKED") for value in participation_decisions.values()):
            participation_status = "BLOCKED"
        elif len(configured) == len(participation_slots) and not any(
            value.endswith("BLOCKED") for value in participation_decisions.values()
        ):
            participation_status = "COMPLETE"
        else:
            participation_status = "PARTIAL"
        component_ids = {
            slot: component["componentId"]
            for slot, component in components.items()
            if component is not None
        }
        common_scope = {
            "studyId": study_id,
            "phase3RunId": phase3_run_id,
            "graphId": graph_id,
            "componentIds": component_ids,
            "researchOnly": True,
            "deploymentAuthorized": False,
        }
        updated["player_team_state"] = {
            "status": dynamic_status,
            "evidence": (
                "Dynamic batter and pitcher state was evaluated and registered as governed retrospective research."
                if dynamic_status == "COMPLETE"
                else "Dynamic player-state evaluation is blocked under its governed terminal decision."
            ),
            **common_scope,
            "componentId": dynamic["componentId"],
            "decision": dynamic_decision,
        }
        updated["participation_usage"] = {
            "status": participation_status,
            "evidence": {
                "configuredComponents": list(configured),
                "requiredComponents": list(participation_slots),
                "decisions": participation_decisions,
            },
            **common_scope,
        }
        scoped_evidence = {
            "event_models": "The exact Phase 3 PA parent and Phase 4 dynamic-state evaluation remain research-only.",
            "candidate_models_experiments": "Frozen 2024 selection and 2025 final evaluation evidence is registered for each configured Phase 4 component.",
            "temporal_validation": "Phase 4 preserves only the governed 2024 and 2025 rolling-origin folds.",
            "calibration_reliability": "Raw calibration evidence and governed retention gates remain inspectable for configured components.",
            "model_graph_decision": f"The additive Phase 4 graph records terminal dynamic decision {dynamic_decision}.",
        }
        for stage, evidence in scoped_evidence.items():
            if stage == "model_graph_decision":
                status = "COMPLETE"
            elif dynamic_status == "BLOCKED":
                status = "BLOCKED"
            elif stage == "event_models":
                status = "COMPLETE"
            elif participation_status == "COMPLETE":
                status = "COMPLETE"
            else:
                status = "PARTIAL"
            updated[stage] = {
                "status": status,
                "evidence": evidence,
                **common_scope,
                "dynamicDecision": dynamic_decision,
                "participationStatus": participation_status,
            }
        updated["game_simulation"] = {
            "status": "NOT_CONFIGURED",
            "studyId": study_id,
            "evidence": "Base-out transitions and the game simulator are not configured in Phase 4.",
        }
        updated["export_to_asp"] = {
            "status": "NOT_CONFIGURED",
            "studyId": study_id,
            "evidence": "No deployment or ASP export bundle is authorized by Phase 4 research evidence.",
        }
        updated["monitoring"] = {
            "status": "NOT_CONFIGURED",
            "studyId": study_id,
        }
        return updated

    @classmethod
    def _assert_existing(cls, connection: Any, payload: Mapping[str, Any]) -> None:
        existing = decode_row(
            connection.execute(
                "SELECT * FROM sports_phase4_studies WHERE study_id = ?",
                (payload["studyId"],),
            ).fetchone()
        )
        if existing is None:
            raise SportsPhase4RegistryError("Phase 4 study identity conflict")
        expected = cls._study_row(
            payload,
            recorded_at=existing["registered_at"],
            user_id=existing["registered_by"],
        )
        expected["last_validated_at"] = existing["last_validated_at"]
        expected["active"] = existing["active"]
        if existing != expected:
            raise SportsPhase4RegistryError("Existing Phase 4 study conflicts with its content identity")

        observed_components = [
            decode_row(row)
            for row in connection.execute(
                "SELECT component_slot, component_id, component_type, contract_name, contract_sha, terminal_status, payload_json FROM sports_phase4_components WHERE study_id = ? ORDER BY component_slot",
                (payload["studyId"],),
            ).fetchall()
        ]
        expected_components = [
            {
                "component_slot": slot,
                "component_id": component["componentId"],
                "component_type": component["componentType"],
                "contract_name": component["contractName"],
                "contract_sha": component["contractSha"],
                "terminal_status": cls._terminal_status(component, slot=slot),
                "payload_json": component,
            }
            for slot in sorted(COMPONENT_SLOTS)
            if (component := payload["components"][slot]) is not None
        ]
        if observed_components != expected_components:
            raise SportsPhase4RegistryError("Existing Phase 4 component rows conflict with the payload")

        observed_artifacts = [
            decode_row(row)
            for row in connection.execute(
                "SELECT artifact_id, artifact_type, logical_uri, artifact_sha, artifact_byte_count, media_type, payload_json FROM sports_phase4_artifact_references WHERE study_id = ? ORDER BY artifact_id",
                (payload["studyId"],),
            ).fetchall()
        ]
        expected_artifacts = [
            {
                "artifact_id": artifact["artifactId"],
                "artifact_type": artifact["artifactType"],
                "logical_uri": artifact["logicalUri"],
                "artifact_sha": artifact["sha256"],
                "artifact_byte_count": artifact["byteCount"],
                "media_type": artifact["mediaType"],
                "payload_json": artifact,
            }
            for artifact in sorted(payload["artifacts"], key=lambda item: item["artifactId"])
        ]
        if observed_artifacts != expected_artifacts:
            raise SportsPhase4RegistryError("Existing Phase 4 artifact rows conflict with the payload")

        graph = decode_row(
            connection.execute(
                "SELECT graph_id, parent_phase3_graph_id FROM sports_phase4_model_graphs WHERE study_id = ?",
                (payload["studyId"],),
            ).fetchone()
        )
        if graph != {
            "graph_id": payload["graph"]["graphId"],
            "parent_phase3_graph_id": payload["graph"]["parentGraphId"],
        }:
            raise SportsPhase4RegistryError("Existing Phase 4 graph authority conflicts")
        observed_nodes = [
            decode_row(row)
            for row in connection.execute(
                """
                SELECT study_id, graph_id, node_id, node_type, label, status,
                       component_id, authority_ref, payload_json
                FROM sports_phase4_model_graph_nodes
                WHERE study_id = ? ORDER BY node_id
                """,
                (payload["studyId"],),
            ).fetchall()
        ]
        expected_nodes = [
            {
                "study_id": payload["studyId"],
                "graph_id": payload["graph"]["graphId"],
                "node_id": node["nodeId"],
                "node_type": node["nodeType"],
                "label": node["label"],
                "status": node["status"],
                "component_id": node["componentId"],
                "authority_ref": node["authorityRef"],
                "payload_json": node,
            }
            for node in sorted(payload["graph"]["nodes"], key=lambda item: item["nodeId"])
        ]
        if observed_nodes != expected_nodes:
            raise SportsPhase4RegistryError("Existing Phase 4 graph nodes conflict")

        observed_edges = [
            decode_row(row)
            for row in connection.execute(
                """
                SELECT study_id, graph_id, edge_id, source_node_id,
                       target_node_id, relation, payload_json
                FROM sports_phase4_model_graph_edges
                WHERE study_id = ? ORDER BY edge_id
                """,
                (payload["studyId"],),
            ).fetchall()
        ]
        expected_edges = [
            {
                "study_id": payload["studyId"],
                "graph_id": payload["graph"]["graphId"],
                "edge_id": edge["edgeId"],
                "source_node_id": edge["sourceNodeId"],
                "target_node_id": edge["targetNodeId"],
                "relation": edge["relation"],
                "payload_json": edge,
            }
            for edge in sorted(payload["graph"]["edges"], key=lambda item: item["edgeId"])
        ]
        if observed_edges != expected_edges:
            raise SportsPhase4RegistryError("Existing Phase 4 graph edges conflict")

    def register(self, payload: Mapping[str, Any], user_id: str) -> dict[str, Any]:
        validated = validate_phase4_study_payload(payload)
        phase3_parent_payload = self._validated_phase3_parent_payload()
        registered_by = _nonblank(user_id, label="user_id")
        recorded_at = now_iso()
        with self.database.transaction() as connection:
            # Acquire the SQLite writer reservation before reading any mutable
            # parent authority.  This makes validation plus the active-head
            # swap one snapshot: another connection cannot rewrite a parent
            # row after it was checked but before this study is recorded.
            connection.execute("BEGIN IMMEDIATE")
            self._require_authorities(connection, validated)
            self._assert_phase3_parent_rows(connection, phase3_parent_payload)
            self._require_study_partition_authorities(connection, validated)
            collision = decode_row(
                connection.execute(
                    "SELECT * FROM sports_phase4_studies WHERE study_id = ? OR core_sha = ? OR study_sha = ?",
                    (
                        validated["studyId"],
                        validated["studyIdentity"]["coreSha"],
                        validated["studySha"],
                    ),
                ).fetchone()
            )
            if collision is not None:
                self._assert_existing(connection, validated)
                connection.execute(
                    "UPDATE sports_phase4_studies SET active = 0 WHERE project_id = ? AND study_id <> ?",
                    (PROJECT_ID, validated["studyId"]),
                )
                connection.execute(
                    "UPDATE sports_phase4_studies SET active = 1, last_validated_at = ? WHERE study_id = ?",
                    (recorded_at, validated["studyId"]),
                )
            else:
                connection.execute(
                    "UPDATE sports_phase4_studies SET active = 0 WHERE project_id = ?",
                    (PROJECT_ID,),
                )
                row = self._study_row(validated, recorded_at=recorded_at, user_id=registered_by)
                columns = tuple(row)
                connection.execute(
                    f"INSERT INTO sports_phase4_studies ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    tuple(json_dumps(value, {}) if key.endswith("_json") else value for key, value in row.items()),
                )
                for slot in COMPONENT_SLOTS:
                    component = validated["components"][slot]
                    if component is None:
                        continue
                    connection.execute(
                        """
                        INSERT INTO sports_phase4_components (
                          study_id, component_slot, component_id, component_type,
                          contract_name, contract_sha, terminal_status, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            validated["studyId"],
                            slot,
                            component["componentId"],
                            component["componentType"],
                            component["contractName"],
                            component["contractSha"],
                            self._terminal_status(component, slot=slot),
                            json_dumps(component, {}),
                        ),
                    )
                for artifact in validated["artifacts"]:
                    connection.execute(
                        """
                        INSERT INTO sports_phase4_artifact_references (
                          study_id, artifact_id, artifact_type, logical_uri,
                          artifact_sha, artifact_byte_count, media_type, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            validated["studyId"],
                            artifact["artifactId"],
                            artifact["artifactType"],
                            artifact["logicalUri"],
                            artifact["sha256"],
                            artifact["byteCount"],
                            artifact["mediaType"],
                            json_dumps(artifact, {}),
                        ),
                    )
                graph = validated["graph"]
                connection.execute(
                    "INSERT INTO sports_phase4_model_graphs (study_id, graph_id, parent_phase3_graph_id) VALUES (?, ?, ?)",
                    (validated["studyId"], graph["graphId"], graph["parentGraphId"]),
                )
                for node in graph["nodes"]:
                    connection.execute(
                        """
                        INSERT INTO sports_phase4_model_graph_nodes (
                          study_id, graph_id, node_id, node_type, label, status,
                          component_id, authority_ref, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            validated["studyId"],
                            graph["graphId"],
                            node["nodeId"],
                            node["nodeType"],
                            node["label"],
                            node["status"],
                            node["componentId"],
                            node["authorityRef"],
                            json_dumps(node, {}),
                        ),
                    )
                for edge in graph["edges"]:
                    connection.execute(
                        """
                        INSERT INTO sports_phase4_model_graph_edges (
                          study_id, graph_id, edge_id, source_node_id,
                          target_node_id, relation, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            validated["studyId"],
                            graph["graphId"],
                            edge["edgeId"],
                            edge["sourceNodeId"],
                            edge["targetNodeId"],
                            edge["relation"],
                            json_dumps(edge, {}),
                        ),
                    )
            project = decode_row(
                connection.execute(
                    "SELECT workflow_evidence_json FROM sports_research_projects WHERE project_id = ?",
                    (PROJECT_ID,),
                ).fetchone()
            )
            if project is None:
                raise SportsPhase4RegistryError("Phase 4 project authority is absent")
            workflow = self._phase4_workflow_overlay(
                project.get("workflow_evidence_json") or {},
                payload=validated,
            )
            connection.execute(
                "UPDATE sports_research_projects SET workflow_evidence_json = ?, updated_at = ? WHERE project_id = ?",
                (json_dumps(workflow, {}), recorded_at, PROJECT_ID),
            )
        public = self._public_study(validated["studyId"])
        if public is None:
            raise SportsPhase4RegistryError("Phase 4 study was not durably registered")
        return {"phase4": public}

    def _public_study(self, study_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = decode_row(
                connection.execute(
                    "SELECT * FROM sports_phase4_studies WHERE study_id = ?",
                    (study_id,),
                ).fetchone()
            )
            if row is None:
                return None
            component_rows = [
                decode_row(item)
                for item in connection.execute(
                    "SELECT component_slot, payload_json FROM sports_phase4_components WHERE study_id = ? ORDER BY component_slot",
                    (study_id,),
                ).fetchall()
            ]
            artifacts = [
                decode_row(item)["payload_json"]
                for item in connection.execute(
                    "SELECT payload_json FROM sports_phase4_artifact_references WHERE study_id = ? ORDER BY artifact_id",
                    (study_id,),
                ).fetchall()
            ]
            graph_row = decode_row(
                connection.execute(
                    "SELECT graph_id, parent_phase3_graph_id FROM sports_phase4_model_graphs WHERE study_id = ?",
                    (study_id,),
                ).fetchone()
            )
            nodes = [
                decode_row(item)["payload_json"]
                for item in connection.execute(
                    "SELECT payload_json FROM sports_phase4_model_graph_nodes WHERE study_id = ? ORDER BY node_id",
                    (study_id,),
                ).fetchall()
            ]
            edges = [
                decode_row(item)["payload_json"]
                for item in connection.execute(
                    "SELECT payload_json FROM sports_phase4_model_graph_edges WHERE study_id = ? ORDER BY edge_id",
                    (study_id,),
                ).fetchall()
            ]
        components: dict[str, Any] = {slot: None for slot in COMPONENT_SLOTS}
        observed_slots: set[str] = set()
        for item in component_rows:
            slot = item["component_slot"]
            if slot not in components or slot in observed_slots:
                raise SportsPhase4RegistryError(
                    "Persisted Phase 4 component cardinality differs"
                )
            observed_slots.add(slot)
            components[slot] = item["payload_json"]
        if graph_row is None:
            raise SportsPhase4RegistryError("Persisted Phase 4 graph is missing")
        expected_graph = build_phase4_graph(
            components,
            phase3_graph_id=row["phase3_graph_id"],
        )
        nodes_by_id = {item["nodeId"]: item for item in nodes}
        edges_by_id = {item["edgeId"]: item for item in edges}
        if (
            len(nodes_by_id) != len(nodes)
            or len(edges_by_id) != len(edges)
            or set(nodes_by_id) != {item["nodeId"] for item in expected_graph["nodes"]}
            or set(edges_by_id) != {item["edgeId"] for item in expected_graph["edges"]}
        ):
            raise SportsPhase4RegistryError(
                "Persisted Phase 4 graph child cardinality differs"
            )
        nodes = [nodes_by_id[item["nodeId"]] for item in expected_graph["nodes"]]
        edges = [edges_by_id[item["edgeId"]] for item in expected_graph["edges"]]
        public = {
            "schemaVersion": row["schema_version"],
            "studyId": row["study_id"],
            "studySha": row["study_sha"],
            "studyIdentity": {
                "schemaVersion": row["identity_schema_version"],
                "coreSha": row["core_sha"],
                "createdAt": row["study_created_at"],
                "codeRevision": row["code_revision"],
            },
            "projectId": row["project_id"],
            "dataset": {
                "registrationId": row["dataset_registration_id"],
                "manifestSha": row["dataset_manifest_sha"],
                "partitionAuthoritySha": row["dataset_partition_authority_sha"],
            },
            "identityBridge": {
                "registrationId": row["identity_bridge_registration_id"],
                "manifestSha": row["identity_bridge_manifest_sha"],
                "joinAuditId": row["identity_join_audit_id"],
            },
            "phase3Baseline": {
                "runId": row["phase3_run_id"],
                "runSha": row["phase3_run_sha"],
                "experimentId": row["phase3_experiment_id"],
                "featureContractName": row["phase3_feature_contract_name"],
                "featureContractSha": row["phase3_feature_contract_sha"],
                "featureViewId": row["phase3_feature_view_id"],
                "graphId": row["phase3_graph_id"],
                "status": row["phase3_status"],
            },
            "components": components,
            "artifacts": artifacts,
            "graph": {
                "graphId": graph_row["graph_id"],
                "parentGraphId": graph_row["parent_phase3_graph_id"],
                "nodes": nodes,
                "edges": edges,
            },
            "decision": row["decision_json"],
        }
        validated = validate_phase4_study_payload(public)
        with self.database.connection() as connection:
            self._require_study_partition_authorities(connection, validated)
            self._assert_existing(connection, validated)
        return validated

    def public_active(self) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT study_id FROM sports_phase4_studies WHERE project_id = ? AND active = 1 ORDER BY registered_at DESC LIMIT 1",
                (PROJECT_ID,),
            ).fetchone()
        if row is None:
            return None
        # Public Phase 4 evidence is valid only while every mutable parent row
        # still resolves to the exact frozen authority used at registration.
        self.validate_registered_authorities()
        public = self._public_study(str(row[0]))
        return {"phase4": public} if public is not None else None


__all__ = [
    "COMPONENT_KEYS",
    "COMPONENT_POLICIES",
    "COMPONENT_SLOTS",
    "RUNTIME_LOGICAL_PREFIX",
    "STUDY_CORE_SCHEMA_VERSION",
    "STUDY_IDENTITY_SCHEMA_VERSION",
    "STUDY_SCHEMA_VERSION",
    "SportsPhase4Registry",
    "SportsPhase4RegistryError",
    "build_phase4_graph",
    "build_phase4_study_payload",
    "semantic_component_sha",
    "semantic_study_core_sha",
    "semantic_study_sha",
    "validate_phase4_study_payload",
]
