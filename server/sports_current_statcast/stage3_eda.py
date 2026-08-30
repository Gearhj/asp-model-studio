"""Project-bound, development-only analytical reads for MLB Stage 3.

The service in this module is intentionally narrow.  It resolves the exact
dataset activation owned by a project, follows that activation to the accepted
current Gold and contextual Gold publications, and answers bounded aggregate
queries from the development rows only.  It cannot fall back to the global
workspace matrix and it contains no provider, training, scoring, or publication
entry point.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as pads
import pyarrow.parquet as pq

from ..persistence.db import Database
from ..persistence.sports_forecast_contract import SportsForecastContractStore
from ..sports_datasets.consumer import canonical_json_bytes
from ..sports_datasets.registry import SportsDatasetRegistry
from ..sports_gold.contracts import GOLD_CLASS_ORDER, GOLD_FEATURES
from .contextual_gold import CONTEXT_GOLD_DATASET_ID, contextual_feature_review
from .contextual_features import ORDERED_GOLD_PLUS_CONTEXT_FEATURES
from .gold import CURRENT_GOLD_DATASET_ID
from .stage2_review import (
    CURRENT_SOURCE_DATASET_ID,
    EXPECTED_DEVELOPMENT,
    EXPECTED_FINAL_OOT,
    SIMULATION_STATE_FIELDS,
    CurrentGoldStage2ReviewError,
    _contextual_gold_root,
    _find_bound_gold,
    _gold_root,
    _load_json,
    _sha256_file,
)


EDA_SCHEMA_VERSION = "SPORTS_STAGE3_PROJECT_EDA_V1"
DEVELOPMENT_START = EXPECTED_DEVELOPMENT[0]
DEVELOPMENT_END = EXPECTED_DEVELOPMENT[1]
DEVELOPMENT_ROWS = EXPECTED_DEVELOPMENT[2]
FINAL_OOT_ROWS = EXPECTED_FINAL_OOT[2]

MAX_VARIABLES = 6
MAX_SAMPLE_ROWS = 5_000
MAX_BINS = 100
MAX_CATEGORIES = 50
MAX_EXTREMES = 100
MAX_ID_FILTER_VALUES = 100
_CACHE_ITEMS = 32

_EXCLUSION_MEMBERSHIP_PATH = Path(__file__).with_name(
    "stage3_exclusion_membership_v1.json"
)
_EXCLUSION_MEMBERSHIP_CANONICAL_SHA = (
    "30fd365bf67dd6687f58864c1b7cede9ea1371028467654e9fac1b5eed833619"
)

_IDENTIFIER_FIELDS = {
    "canonicalPaId",
    "plate_appearance_id",
    "canonicalGameId",
    "game_id",
    "batterCanonicalPlayerId",
    "pitcherCanonicalPlayerId",
}
_TIME_FIELDS = {"game_date", "season"}
_LINEAGE_FIELDS = {
    "context_source_cutoff",
    "context_derivation_cutoff_exclusive",
    "batting_prior_game_identity",
    "fielding_prior_game_identity",
    "batting_previous_venue",
    "fielding_previous_venue",
    "batting_missing_reason",
    "fielding_missing_reason",
    "distance_calculation_version",
    "holiday_calendar_version",
    "rivalry_map_version",
    "context_feature_version",
}
_SUPPORTED_QUERY_TYPES = {
    "overview",
    "distribution",
    "category_counts",
    "association",
    "pairwise_sample",
    "missingness",
    "outliers",
    "temporal",
    "cold_start",
}
_SUPPORTED_FILTERS = {
    "seasons",
    "startDate",
    "endDate",
    "months",
    "daysOfWeek",
    "outcomes",
    "batter",
    "pitcher",
    "historyStatus",
    "homeAway",
    "missingness",
    "simulationState",
    "minimumSampleSize",
    "battingTeam",
    "fieldingTeam",
}


class Stage3EdaError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


@dataclass(frozen=True)
class _Authority:
    project_id: str
    registration_id: str
    dataset_version_id: str
    activation_revision: int
    source_dataset_id: str
    source_manifest_sha: str
    source_publication_sha: str
    gold_manifest_sha: str
    gold_manifest: Mapping[str, Any]
    contextual_manifest_sha: str
    review_digest: str
    contextual_root: Path
    contextual_manifest: Mapping[str, Any]
    contextual_review: Mapping[str, Any]
    exclusion_membership_sha: str
    exclusion_membership: Mapping[str, Any]
    paths: tuple[Path, ...]
    schema: pa.Schema

    def public(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            "sourceDatasetId": self.source_dataset_id,
            "sourceManifestSha": self.source_manifest_sha,
            "goldDatasetId": CURRENT_GOLD_DATASET_ID,
            "goldManifestSha": self.gold_manifest_sha,
            "contextualDatasetId": CONTEXT_GOLD_DATASET_ID,
            "contextualManifestSha": self.contextual_manifest_sha,
            "exclusionMembershipArtifactSha": self.exclusion_membership_sha,
            "reviewDigest": self.review_digest,
        }


_RESULT_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_RESULT_CACHE_LOCK = threading.Lock()


def _cache_get(key: str) -> dict[str, Any] | None:
    with _RESULT_CACHE_LOCK:
        result = _RESULT_CACHE.get(key)
        if result is not None:
            _RESULT_CACHE.move_to_end(key)
        return result


def _cache_put(key: str, value: dict[str, Any]) -> None:
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE[key] = value
        _RESULT_CACHE.move_to_end(key)
        while len(_RESULT_CACHE) > _CACHE_ITEMS:
            _RESULT_CACHE.popitem(last=False)


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _is_empty_filter(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _load_exclusion_membership(
    *,
    registration_id: str,
    dataset_version_id: str,
    source_manifest_sha: str,
    source_publication_sha: str,
    gold_manifest_sha: str,
) -> tuple[str, dict[str, Any]]:
    """Load the reviewed membership anti-join without claiming causal reasons."""

    try:
        evidence = json.loads(_EXCLUSION_MEMBERSHIP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3EdaError(
            "EXCLUSION_MEMBERSHIP_AUTHORITY_MISSING",
            "The exact project population membership evidence is unavailable.",
            status_code=409,
        ) from exc
    canonical_sha = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
    source = (evidence.get("authority") or {}).get("source") or {}
    gold = (evidence.get("authority") or {}).get("boundCurrentGold") or {}
    reconciliation = evidence.get("rowReconciliation") or {}
    identity_sha = evidence.get("identitySetSha256") or {}
    expected_reconciliation = {
        "sourceRows": 702_326,
        "sourceUniqueCanonicalPaIds": 702_326,
        "sourceDuplicateCanonicalPaIds": 0,
        "goldRows": 697_729,
        "goldUniqueCanonicalPaIds": 697_729,
        "goldDuplicateCanonicalPaIds": 0,
        "goldCanonicalPaIdsAbsentFromSource": 0,
        "sourceCanonicalPaIdsAbsentFromGold": 4_597,
        "excludedRows": 4_597,
    }
    authority_valid = (
        canonical_sha == _EXCLUSION_MEMBERSHIP_CANONICAL_SHA
        and evidence.get("schemaVersion")
        == "MLB_CURRENT_STATCAST_STAGE3_EXCLUSION_MEMBERSHIP_V1"
        and int(evidence.get("artifactVersion") or -1) == 1
        and evidence.get("causalityClaimed") is False
        and evidence.get("legacyTargetExclusionLedgerUsed") is False
        and int(evidence.get("providerCalls") or 0) == 0
        and int(evidence.get("rebuilds") or 0) == 0
        and source.get("datasetId") == CURRENT_SOURCE_DATASET_ID
        and source.get("registrationId") == registration_id
        and source.get("datasetVersionId") == dataset_version_id
        and source.get("manifestSha256") == source_manifest_sha
        and source.get("currentSilverPublicationManifestSha256")
        == source_publication_sha
        and gold.get("datasetId") == CURRENT_GOLD_DATASET_ID
        and gold.get("manifestSha256") == gold_manifest_sha
        and gold.get("sourceSilverManifestSha256") == source_publication_sha
        and reconciliation == expected_reconciliation
        and evidence.get("membershipKey") == "canonicalPaId"
        and identity_sha.get("algorithm") == "SHA-256"
        and identity_sha.get("canonicalization")
        == "SORT_ASCENDING_UTF8_JOIN_LF_WITHOUT_TRAILING_LF"
        and len(str(identity_sha.get("value") or "")) == 64
        and evidence.get("membershipStatusCounts")
        == {"NOT_PRESENT_IN_BOUND_CURRENT_GOLD_BY_CANONICAL_PA_ID": 4_597}
        and evidence.get("causalReasonStatus")
        == "FINER_SOURCE_SIDE_CAUSE_NOT_RECORDED"
        and evidence.get("causalReasonCounts")
        == {"NOT_ADMITTED_TO_FROZEN_GOLD_V1_BRIDGE_MATCHED_SET": 4_597}
        and (evidence.get("exclusionStageEvidence") or {}).get("status")
        == "EXACT_DERIVED_CONSTRUCTION_STAGE_COUNTS"
        and (evidence.get("exclusionStageEvidence") or {}).get("counts")
        == {
            "PRE_FEATURE_BRIDGE_NON_ADMISSION": 4_597,
            "FEATURE_CONSTRUCTION_ROW_LOSS": 0,
        }
        and evidence.get("featureConstructionCondition")
        == "PRE_FEATURE_BRIDGE_NON_ADMISSION"
        and evidence.get("featureConstructionConditionCounts")
        == {
            "PRE_FEATURE_BRIDGE_NON_ADMISSION": 4_597,
            "FEATURE_CONSTRUCTION_ROW_LOSS": 0,
        }
    )

    def axis_reconciles(name: str) -> bool:
        rows = evidence.get(name) or []
        return bool(rows) and {
            "sourceRows": sum(int(item.get("sourceRows") or 0) for item in rows),
            "presentInGoldRows": sum(
                int(item.get("presentInGoldRows") or 0) for item in rows
            ),
            "excludedRows": sum(int(item.get("excludedRows") or 0) for item in rows),
        } == {
            "sourceRows": 702_326,
            "presentInGoldRows": 697_729,
            "excludedRows": 4_597,
        }

    final_oot = evidence.get("finalOot") or {}
    if not (
        authority_valid
        and all(
            axis_reconciles(name)
            for name in (
                "bySeason",
                "byMonth",
                "byBattingTeam",
                "byGovernedTargetOrUnmapped",
            )
        )
        and final_oot
        == {
            "startDate": EXPECTED_FINAL_OOT[0],
            "endDate": EXPECTED_FINAL_OOT[1],
            "sourceRows": FINAL_OOT_ROWS,
            "presentInGoldRows": FINAL_OOT_ROWS,
            "excludedRows": 0,
        }
    ):
        raise Stage3EdaError(
            "EXCLUSION_MEMBERSHIP_AUTHORITY_INVALID",
            "The exact project population membership evidence does not reconcile to the bound source and Gold authorities.",
            status_code=409,
        )
    return canonical_sha, evidence


def _load_context_manifest(root: Path, expected_source_sha: str) -> tuple[str, dict[str, Any]]:
    locator = _load_json(root / "current.json")
    manifest_sha = str(locator.get("manifestSha256") or "")
    expected_path = root / "publications" / "sha256" / manifest_sha / "manifest.json"
    if (
        locator.get("datasetId") != CONTEXT_GOLD_DATASET_ID
        or locator.get("currentManifestSha256") != manifest_sha
        or not expected_path.is_file()
        or _sha256_file(expected_path) != manifest_sha
    ):
        raise Stage3EdaError(
            "CONTEXTUAL_GOLD_AUTHORITY_INVALID",
            "The current contextual Gold authority does not match its immutable locator.",
            status_code=409,
        )
    manifest = _load_json(expected_path)
    if (
        manifest.get("datasetId") != CONTEXT_GOLD_DATASET_ID
        or (manifest.get("sourceGold") or {}).get("manifestSha256") != expected_source_sha
        or int(manifest.get("rowCount") or -1) != 697_729
        or int(manifest.get("totalFeatureCount") or -1) != 254
        or manifest.get("featureNames")[:48] != list(GOLD_FEATURES)
    ):
        raise Stage3EdaError(
            "CONTEXTUAL_GOLD_PROJECT_BINDING_MISMATCH",
            "The contextual feature library is not bound to this project's accepted Gold authority.",
            status_code=409,
        )
    return manifest_sha, manifest


_VERIFIED_PARTITIONS: dict[tuple[str, str], tuple[tuple[Path, ...], pa.Schema]] = {}
_VERIFIED_PARTITIONS_LOCK = threading.Lock()
_TEAM_CONTEXT_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


def _verified_partitions(
    root: Path, manifest_sha: str, manifest: Mapping[str, Any]
) -> tuple[tuple[Path, ...], pa.Schema]:
    key = (str(root), manifest_sha)
    with _VERIFIED_PARTITIONS_LOCK:
        cached = _VERIFIED_PARTITIONS.get(key)
    if cached is not None:
        return cached

    paths: list[Path] = []
    schema: pa.Schema | None = None
    rows = 0
    for item in manifest.get("partitions") or []:
        path = root / str(item.get("relativePath") or "")
        parquet = pq.ParquetFile(path) if path.is_file() else None
        if (
            parquet is None
            or _sha256_file(path) != item.get("sha256")
            or parquet.metadata.num_rows != int(item.get("rowCount") or -1)
        ):
            raise Stage3EdaError(
                "CONTEXTUAL_GOLD_PARTITION_INVALID",
                "A contextual Gold partition differs from its immutable authority.",
                status_code=409,
            )
        if schema is None:
            schema = parquet.schema_arrow
        elif not parquet.schema_arrow.equals(schema):
            raise Stage3EdaError(
                "CONTEXTUAL_GOLD_SCHEMA_MISMATCH",
                "Contextual Gold partitions do not share one exact schema.",
                status_code=409,
            )
        paths.append(path)
        rows += parquet.metadata.num_rows
    if schema is None or rows != int(manifest.get("rowCount") or -1):
        raise Stage3EdaError(
            "CONTEXTUAL_GOLD_ROW_RECONCILIATION_FAILED",
            "Contextual Gold partition rows do not reconcile.",
            status_code=409,
        )
    result = (tuple(paths), schema)
    with _VERIFIED_PARTITIONS_LOCK:
        _VERIFIED_PARTITIONS[key] = result
    return result


def _team_context(authority: _Authority) -> pd.DataFrame:
    """Return the small, immutable game/team lookup used by row filters."""

    key = (str(authority.contextual_root), authority.contextual_manifest_sha)
    with _VERIFIED_PARTITIONS_LOCK:
        cached = _TEAM_CONTEXT_CACHE.get(key)
    if cached is not None:
        return cached
    item = authority.contextual_manifest.get("teamGameContext") or {}
    path = authority.contextual_root / str(item.get("relativePath") or "")
    if (
        item.get("contract") != "MLB_PREGAME_TEAM_GAME_CONTEXT_V1"
        or item.get("naturalKey") != ["canonical_game_id", "team_id"]
        or not path.is_file()
        or _sha256_file(path) != item.get("sha256")
    ):
        raise Stage3EdaError(
            "TEAM_GAME_CONTEXT_AUTHORITY_INVALID",
            "The project-bound team/game filter authority is invalid.",
            status_code=409,
        )
    table = pq.read_table(
        path,
        columns=[
            "canonical_game_id", "team_id", "opponent_team_id",
            "home_team_id", "away_team_id", "game_date",
        ],
    )
    if table.num_rows != int(item.get("rowCount") or -1):
        raise Stage3EdaError(
            "TEAM_GAME_CONTEXT_ROW_MISMATCH",
            "The project-bound team/game filter authority does not reconcile.",
            status_code=409,
        )
    frame = table.to_pandas()
    with _VERIFIED_PARTITIONS_LOCK:
        _TEAM_CONTEXT_CACHE[key] = frame
    return frame


def _resolve_authority(database: Database, project_id: str) -> _Authority:
    linkage = SportsForecastContractStore(database).get_evidence_dataset(project_id)
    registration = SportsDatasetRegistry(database).get(str(linkage["registrationId"]))
    if not registration:
        raise Stage3EdaError(
            "PROJECT_DATASET_REGISTRATION_MISSING",
            "The project-linked sports registration is unavailable.",
            status_code=409,
        )
    if not (
        registration.get("dataset_id") == linkage.get("datasetId") == CURRENT_SOURCE_DATASET_ID
        and registration.get("dataset_version_id") == linkage.get("datasetVersionId")
        and registration.get("manifest_sha") == linkage.get("manifestSha")
        and registration.get("validation_status") == "VALID"
    ):
        raise Stage3EdaError(
            "PROJECT_DATASET_AUTHORITY_MISMATCH",
            "The Stage 3 EDA authority does not match the project's exact registered activation.",
            status_code=409,
        )
    metadata = registration.get("metadata_json") or {}
    source_publication_sha = str(
        ((metadata.get("manifestMetadata") or {}).get("publicationManifestSha256")) or ""
    )
    if len(source_publication_sha) != 64:
        raise Stage3EdaError(
            "PROJECT_SOURCE_PUBLICATION_MISSING",
            "The project registration does not identify its immutable source publication.",
            status_code=409,
        )
    gold_root = _gold_root()
    try:
        gold_sha, _gold_path, gold_manifest = _find_bound_gold(
            gold_root,
            source_publication_sha=source_publication_sha,
            explicit_gold=metadata.get("goldPublication") if isinstance(metadata, Mapping) else None,
        )
    except CurrentGoldStage2ReviewError as exc:
        raise Stage3EdaError(exc.code, str(exc), status_code=exc.status_code) from exc
    temporal = gold_manifest.get("temporalContract") or {}
    if (
        tuple(temporal.get("developmentSelection") or ()) != EXPECTED_DEVELOPMENT[:2]
        or tuple(temporal.get("finalOot") or ()) != EXPECTED_FINAL_OOT[:2]
        or int(gold_manifest.get("rowCount") or -1) != 697_729
        or gold_manifest.get("featureNames") != list(GOLD_FEATURES)
    ):
        raise Stage3EdaError(
            "PROJECT_GOLD_TEMPORAL_CONTRACT_MISMATCH",
            "The accepted Gold authority does not match the frozen Stage 3 population contract.",
            status_code=409,
        )
    context_root = _contextual_gold_root()
    contextual_sha, contextual_manifest = _load_context_manifest(context_root, gold_sha)
    contextual_review = contextual_feature_review(
        context_root,
        source_gold_manifest_sha256=gold_sha,
        current_gold_root=gold_root,
    )
    if not contextual_review or not contextual_review.get("verified"):
        raise Stage3EdaError(
            "CONTEXTUAL_GOLD_VERIFICATION_MISSING",
            "The project contextual feature library lacks a valid immutable verification receipt.",
            status_code=409,
        )
    paths, schema = _verified_partitions(context_root, contextual_sha, contextual_manifest)
    exclusion_membership_sha, exclusion_membership = _load_exclusion_membership(
        registration_id=str(linkage["registrationId"]),
        dataset_version_id=str(linkage["datasetVersionId"]),
        source_manifest_sha=str(linkage["manifestSha"]),
        source_publication_sha=source_publication_sha,
        gold_manifest_sha=gold_sha,
    )
    identity = {
        "projectId": project_id,
        "registrationId": linkage["registrationId"],
        "activationRevision": int(linkage["activationRevision"]),
        "sourceDatasetId": linkage["datasetId"],
        "datasetVersionId": linkage["datasetVersionId"],
        "sourceManifestSha": linkage["manifestSha"],
        "sourcePublicationManifestSha": source_publication_sha,
        "goldManifestSha": gold_sha,
        "contextualManifestSha": contextual_sha,
        "exclusionMembershipArtifactSha": exclusion_membership_sha,
        "development": list(EXPECTED_DEVELOPMENT),
        "finalOot": list(EXPECTED_FINAL_OOT),
    }
    return _Authority(
        project_id=project_id,
        registration_id=str(linkage["registrationId"]),
        dataset_version_id=str(linkage["datasetVersionId"]),
        activation_revision=int(linkage["activationRevision"]),
        source_dataset_id=str(linkage["datasetId"]),
        source_manifest_sha=str(linkage["manifestSha"]),
        source_publication_sha=source_publication_sha,
        gold_manifest_sha=gold_sha,
        gold_manifest=gold_manifest,
        contextual_manifest_sha=contextual_sha,
        review_digest=hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
        contextual_root=context_root,
        contextual_manifest=contextual_manifest,
        contextual_review=contextual_review,
        exclusion_membership_sha=exclusion_membership_sha,
        exclusion_membership=exclusion_membership,
        paths=paths,
        schema=schema,
    )


def _data_type(field: pa.Field, name: str) -> str:
    if pa.types.is_string(field.type) or pa.types.is_large_string(field.type):
        return "categorical"
    if pa.types.is_boolean(field.type):
        return "categorical"
    if name.startswith("is_") or name.endswith("_missing") or name.endswith("_indicator"):
        return "categorical"
    return "numeric" if pa.types.is_integer(field.type) or pa.types.is_floating(field.type) else "categorical"


def _role(name: str) -> str:
    if name in _IDENTIFIER_FIELDS:
        return "IDENTIFIER" if "Game" not in name and name != "game_id" else "GROUPING"
    if name in _TIME_FIELDS:
        return "TIME"
    if name == "outcome":
        return "TARGET"
    if name == "datasetRole":
        return "RESEARCH_ONLY"
    if name in SIMULATION_STATE_FIELDS:
        return "SIMULATION_GENERATED_STATE"
    if name.endswith("_missing") or name.endswith("_insufficient"):
        return "MISSINGNESS_INDICATOR"
    if name in ORDERED_GOLD_PLUS_CONTEXT_FEATURES:
        return "PREGAME_FEATURE"
    return "EXCLUDED"


def _variables(authority: _Authority) -> list[dict[str, Any]]:
    feature_rows = {
        str(item["name"]): dict(item)
        for item in authority.contextual_review.get("features") or []
    }
    included_names = [
        *[name for name in authority.schema.names if name in _IDENTIFIER_FIELDS or name in _TIME_FIELDS],
        "outcome",
        *[str(name) for name in authority.contextual_manifest.get("featureNames") or []],
        "datasetRole",
    ]
    # Preserve physical order without duplicates.
    ordered = list(dict.fromkeys(name for name in authority.schema.names if name in set(included_names)))
    output: list[dict[str, Any]] = []
    for name in ordered:
        field = authority.schema.field(name)
        review = feature_rows.get(name) or {}
        role = _role(name)
        family = str(review.get("family") or (
            "IDENTITY" if role in {"IDENTIFIER", "GROUPING"}
            else "TIME" if role == "TIME"
            else "TARGET" if role == "TARGET"
            else "RESEARCH"
        ))
        missing_percent = (
            100.0 * (1.0 - float(review.get("coverageDevelopment") or 0.0))
            if review
            else 0.0
        )
        proxy = review.get("proxyWarning")
        output.append({
            "name": name,
            "label": name.replace("_", " ").replace("Id", " ID").title(),
            "definition": str(review.get("definition") or {
                "outcome": "Governed eight-class plate-appearance outcome in the development population.",
                "game_date": "Venue-local game date used by the frozen temporal contract.",
                "season": "MLB season containing the plate appearance.",
            }.get(name) or "Governed identity or grouping field from the accepted Gold publication."),
            "dataType": _data_type(field, name),
            "role": role,
            "featureFamily": family,
            "category": str(review.get("category") or role),
            "sourceLineage": str(review.get("sourceLineage") or f"{CURRENT_GOLD_DATASET_ID}@{authority.gold_manifest_sha}"),
            "pointInTimeTreatment": str(review.get("pointInTimeTreatment") or "Development rows only; final OOT excluded before analysis."),
            "availabilityEra": "Registered development evidence: 2023-03-30 through 2026-08-13",
            "missingPercent": missing_percent,
            "uniqueCount": 8 if name == "outcome" else 4 if name == "season" else None,
            "selectable": role in {"PREGAME_FEATURE", "SIMULATION_GENERATED_STATE", "MISSINGNESS_INDICATOR"} and not ("rivalry" in name and proxy),
            "core": name in GOLD_FEATURES,
            "proxyWarning": proxy,
        })
    return output


def _families(authority: _Authority, variables: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    missing_by_name = {str(item["name"]): float(item.get("missingPercent") or 0.0) for item in variables}
    output = []
    for raw in authority.contextual_review.get("families") or []:
        names = [str(name) for name in raw.get("orderedFeatures") or []]
        missing = [missing_by_name[name] for name in names if name in missing_by_name]
        output.append({
            "name": str(raw.get("name") or ""),
            "featureCount": len(names),
            "activeCount": sum(1 for name in names if not ("rivalry" in name)),
            "missingPercent": float(np.mean(missing)) if missing else 0.0,
            "coveragePercent": 100.0 - (float(np.mean(missing)) if missing else 0.0),
            "orderedFeatures": names,
            "proxyWarning": "Travel, circadian, rivalry, and holiday fields are hypotheses for later chronological validation; no family is selected here.",
        })
    return output


def _membership_evidence(authority: _Authority) -> dict[str, Any]:
    evidence = authority.exclusion_membership
    identity = evidence.get("identitySetSha256") or {}
    final_oot = evidence.get("finalOot") or {}
    identity_conditions = evidence.get("identityConditions") or {}
    return {
        "schemaVersion": evidence["schemaVersion"],
        "artifactCanonicalSha256": authority.exclusion_membership_sha,
        "membershipKey": evidence["membershipKey"],
        "identitySetSha256": identity["value"],
        "identitySetCanonicalization": identity["canonicalization"],
        "membershipStatusCounts": dict(evidence["membershipStatusCounts"]),
        "causalReasonStatus": evidence["causalReasonStatus"],
        "causalReasonCounts": dict(evidence["causalReasonCounts"]),
        "bySeason": list(evidence["bySeason"]),
        "byMonth": list(evidence["byMonth"]),
        "byBattingTeam": [
            {
                "team": item["battingTeam"],
                "sourceRows": int(item["sourceRows"]),
                "presentInGoldRows": int(item["presentInGoldRows"]),
                "excludedRows": int(item["excludedRows"]),
                "exclusionRatePct": float(item["exclusionRatePct"]),
                "shareOfExclusionsPct": float(item["shareOfExclusionsPct"]),
            }
            for item in evidence["byBattingTeam"]
        ],
        # Whole-population target totals would make sealed final-OOT class
        # counts recoverable by subtracting development counts.  Stage 3 may
        # disclose only the excluded-membership concentration for this axis.
        "byGovernedTargetOrUnmapped": [
            {
                "target": str(item["target"]),
                "excludedRows": int(item["excludedRows"]),
                "shareOfExclusionsPct": float(item["shareOfExclusionsPct"]),
            }
            for item in evidence["byGovernedTargetOrUnmapped"]
        ],
        "unmappedTargetDetail": dict(evidence["unmappedTargetDetail"]),
        "identityConditions": {
            key: int(value)
            for key, value in identity_conditions.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        },
        "finalOotExcludedRows": int(final_oot["excludedRows"]),
        "featureConstructionCondition": evidence["featureConstructionCondition"],
        "featureConstructionConditionCounts": dict(
            evidence["featureConstructionConditionCounts"]
        ),
        "exclusionStageStatus": str(
            (evidence["exclusionStageEvidence"] or {})["status"]
        ),
        "finerSourceSideCauseStatus": str(
            (evidence["exclusionStageEvidence"] or {})[
                "finerSourceSideCauseStatus"
            ]
        ),
        "causalityClaimed": False,
    }


def _stage3_handoff(authority: _Authority) -> dict[str, Any]:
    """Safe Stage 2 -> Stage 3 summary with all final-OOT EDA fields redacted."""

    gold = authority.gold_manifest
    context = authority.contextual_review
    core_columns = [
        name
        for name in authority.schema.names
        if name in _IDENTIFIER_FIELDS
        or name in _TIME_FIELDS
        or name == "outcome"
        or name == "datasetRole"
        or name in GOLD_FEATURES
    ]
    columns = [
        {
            "name": name,
            "dtype": str(authority.schema.field(name).type),
            "nullable": bool(authority.schema.field(name).nullable),
            "classification": _role(name),
            "predictorOrder": list(GOLD_FEATURES).index(name) + 1 if name in GOLD_FEATURES else None,
        }
        for name in core_columns
    ]
    checks = [
        {
            "code": "PROJECT_SOURCE_IDENTITY", "status": "PASS", "blocking": True,
            "detail": "Project activation matches the exact registered source authority.",
        },
        {
            "code": "GOLD_ROW_RECONCILIATION", "status": "PASS", "blocking": True,
            "detail": "697,729 immutable Gold rows reconcile to the accepted population.",
        },
        {
            "code": "POINT_IN_TIME_REVIEW", "status": "PASS", "blocking": True,
            "detail": "Historical aggregates use source.gameDate < target.gameDate; same-date rows are excluded.",
        },
        {
            "code": "LEAKAGE_GATE", "status": "PASS_WITH_CONDITIONS", "blocking": True,
            "detail": "Predictors exclude future outcomes; five conditional PA-state fields must be supplied by the simulator.",
        },
        {
            "code": "FINAL_OOT_LOCK", "status": "PASS", "blocking": True,
            "detail": "14,067 final-OOT rows are excluded from Stage 3 EDA and model selection.",
        },
        {
            "code": "MODEL_ACTIVITY", "status": "PASS", "blocking": True,
            "detail": "Zero fits, scores, tunes, calibrations, selections, and promotions.",
        },
    ]
    context_summary = {
        "status": context["status"],
        "verified": bool(context["verified"]),
        "datasetId": context["datasetId"],
        "manifestSha256": context["manifestSha256"],
        "sourceGoldManifestSha256": context["sourceGoldManifestSha256"],
        "rowCount": int(context["rowCount"]),
        "coreFeatureCount": int(context["coreFeatureCount"]),
        "addedFeatureCount": int(context["addedFeatureCount"]),
        "totalFeatureCount": int(context["totalFeatureCount"]),
        "teamGameRowCount": int(context["teamGameRowCount"]),
        "rivalryMappingStatus": context["rivalryMappingStatus"],
        # Feature coverage (including final-OOT coverage) is intentionally not
        # part of the Stage 3 bootstrap.  Development variable metadata comes
        # from this endpoint's `variables` array instead.
        "features": [],
        "families": [
            {
                "name": item["name"],
                "featureCount": item["featureCount"],
                "orderedFeatures": item["orderedFeatures"],
                "includedByDefault": item["includedByDefault"],
            }
            for item in context.get("families") or []
        ],
        "interactions": list(context.get("interactions") or []),
        "warnings": list(context.get("warnings") or []),
    }
    return {
        "schemaVersion": "SPORTS_STAGE3_PROJECT_HANDOFF_REDACTED_V1",
        "projectId": authority.project_id,
        "sourceAuthority": {
            "registrationId": authority.registration_id,
            "datasetId": authority.source_dataset_id,
            "datasetVersionId": authority.dataset_version_id,
            "manifestSha": authority.source_manifest_sha,
            "activationRevision": authority.activation_revision,
            "rowCount": 702_326,
            "rowsBySeason": {"2023": 184_497, "2024": 182_883, "2025": 182_847, "2026": 152_099},
            "dateCoverage": {"earliestDate": "2023-03-30", "latestDate": "2026-08-27"},
            "silverPublicationManifestSha": authority.source_publication_sha,
        },
        "goldAuthority": {
            "datasetId": CURRENT_GOLD_DATASET_ID,
            "manifestSha": authority.gold_manifest_sha,
            "manifestContract": gold.get("manifestContract"),
            "manifestVersion": gold.get("manifestVersion"),
            "status": gold.get("status"),
            "modelsFitted": 0,
            "modelPromoted": False,
            "rowCount": 697_729,
            "featureCount": 48,
            "dateCoverage": {"earliestDate": "2023-03-30", "latestDate": "2026-08-27"},
            "rowsBySeason": {"2023": 182_072, "2024": 180_711, "2025": 182_847, "2026": 152_099},
            "sourceSilverManifestSha": authority.source_publication_sha,
            "verified": True,
        },
        "populationReconciliation": {
            "sourceRows": 702_326,
            "goldRows": 697_729,
            "excludedRows": 4_597,
            "bySeason": [
                {"season": 2023, "sourceRows": 184_497, "goldRows": 182_072, "excludedRows": 2_425},
                {"season": 2024, "sourceRows": 182_883, "goldRows": 180_711, "excludedRows": 2_172},
                {"season": 2025, "sourceRows": 182_847, "goldRows": 182_847, "excludedRows": 0},
                {"season": 2026, "sourceRows": 152_099, "goldRows": 152_099, "excludedRows": 0},
            ],
            "exclusionReasonCounts": dict(
                authority.exclusion_membership["causalReasonCounts"]
            ),
            "exclusionReasonStatus": "EXACT_DERIVED_CONSTRUCTION_STAGE_COUNTS",
            "membershipEvidence": _membership_evidence(authority),
        },
        "matrix": {
            "grain": "PLATE_APPEARANCE",
            "totalColumns": len(core_columns),
            "predictorCount": 48,
            "orderedPredictors": list(GOLD_FEATURES),
            "seasons": [2023, 2024, 2025, 2026],
            "development": {"startDate": DEVELOPMENT_START, "endDate": DEVELOPMENT_END, "rows": DEVELOPMENT_ROWS},
            "finalOot": {"startDate": EXPECTED_FINAL_OOT[0], "endDate": EXPECTED_FINAL_OOT[1], "rows": FINAL_OOT_ROWS},
            "columns": columns,
        },
        "targetTaxonomy": {
            "column": "outcome",
            "classOrder": list(GOLD_CLASS_ORDER),
            "distributions": {"development": []},
        },
        "identity": {
            "observedPlayerCount": 0,
            "matchedExactPlayerCount": 0,
            "unresolvedPlayerIdentities": 0,
            "ambiguousPlayerIdentities": 0,
            "unresolvedGameIdentities": 0,
            "ambiguousGameIdentities": 0,
            "duplicateCanonicalPaIdentities": 0,
            "duplicatePlateAppearanceIdentities": 0,
            "nullIdentityRows": 0,
            "paAliasValueDifferences": 0,
            "gameAliasValueDifferences": 0,
            "countStatus": "ISSUE_COUNTS_ONLY_OBSERVED_TOTAL_REDACTED",
        },
        "missingness": {
            "reasonCategories": [
                "NO_PRIOR_HISTORY", "INSUFFICIENT_HISTORY", "SOURCE_MISSING",
                "IDENTITY_FAILURE", "COMPUTATION_FAILURE", "SOURCE_NOT_AVAILABLE_FOR_ERA",
            ],
            "predictors": [],
            "note": "Stage 3 bootstrap omits final-OOT feature coverage; development-only metadata is provided separately.",
        },
        "contextualFeaturePack": context_summary,
        "pointInTimeReview": checks[2],
        "leakageGate": checks[3],
        "modelingTreatment": {
            "coldStartRows": "RETAIN",
            "imputation": "TRAINING_FOLD_ONLY_OR_HIERARCHICAL_LEAGUE_PRIORS",
            "missingFlags": "RETAIN",
            "globalImputation": "PROHIBITED",
            "validationOrOotPreprocessing": "PROHIBITED",
            "simulationStateForecastRule": "SUPPLY_FROM_SIMULATOR_NEVER_FUTURE_ACTUAL_GAME_STATE",
        },
        "checks": checks,
        "acceptance": {"allowed": True, "blockers": []},
        "reviewDigest": authority.review_digest,
        "preview": {"season": None, "sample": "REDACTED", "limit": 0, "columns": [], "rows": []},
        "redaction": {
            "finalOotTargetDistributions": "OMITTED",
            "overallTargetDistributions": "OMITTED",
            "finalOotFeatureCoverage": "OMITTED",
            "previewRows": "OMITTED",
        },
    }


def _metadata_data(authority: _Authority) -> dict[str, Any]:
    variables = _variables(authority)
    team_context = _team_context(authority)
    return {
        "schemaVersion": EDA_SCHEMA_VERSION,
        "stage3Handoff": _stage3_handoff(authority),
        "variables": variables,
        "families": _families(authority, variables),
        "targetTaxonomy": list(GOLD_CLASS_ORDER),
        "filterOptions": {
            "seasons": [2023, 2024, 2025, 2026],
            "months": list(range(1, 13)),
            "daysOfWeek": [
                "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
                "FRIDAY", "SATURDAY", "SUNDAY",
            ],
            "outcomes": list(GOLD_CLASS_ORDER),
            "teams": sorted(team_context["team_id"].dropna().astype(str).unique().tolist()),
        },
        "queryLimits": {
            "maxVariables": MAX_VARIABLES,
            "maxSampleRows": MAX_SAMPLE_ROWS,
            "maxBins": MAX_BINS,
            "maxCategories": MAX_CATEGORIES,
        },
        "notices": [
            "14,067 final-OOT rows are locked and excluded from exploratory analysis.",
            "All target-derived EDA is restricted to 683,662 development/model-selection rows through 2026-08-13.",
            "The exact canonical-PA membership anti-join supplies season, month, batting-team, governed-target-or-unmapped, identity-condition, and final-OOT concentrations; causal exclusion reasons and feature-construction cause remain unrecorded and are not inferred.",
            "No EDA action fits, scores, tunes, calibrates, selects, or promotes a model.",
        ],
    }


def _normalize_sequence(value: Any, *, name: str, maximum: int = 100) -> list[Any]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, list) else [value]
    if len(values) > maximum:
        raise Stage3EdaError("EDA_FILTER_TOO_LARGE", f"{name} accepts at most {maximum} values.")
    return values


def _normalize_filters(
    filters: Any, schema_names: set[str], selected_variables: Sequence[str]
) -> dict[str, Any]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise Stage3EdaError("EDA_FILTERS_INVALID", "filters must be an object.")
    unknown = set(filters) - _SUPPORTED_FILTERS
    if unknown:
        raise Stage3EdaError("EDA_FILTER_UNSUPPORTED", f"Unsupported filters: {', '.join(sorted(unknown))}.")
    normalized: dict[str, Any] = {}
    for team_filter in ("battingTeam", "fieldingTeam"):
        values = [
            str(value).strip().upper()
            for value in _normalize_sequence(
                filters.get(team_filter), name=team_filter, maximum=30
            )
            if str(value).strip()
        ]
        if values:
            normalized[team_filter] = sorted(set(values))
    seasons = [int(value) for value in _normalize_sequence(filters.get("seasons"), name="seasons")]
    if any(value not in {2023, 2024, 2025, 2026} for value in seasons):
        raise Stage3EdaError("EDA_SEASON_INVALID", "EDA seasons are limited to 2023 through 2026 development evidence.")
    if seasons:
        normalized["seasons"] = sorted(set(seasons))
    months = [int(value) for value in _normalize_sequence(filters.get("months"), name="months")]
    if any(value < 1 or value > 12 for value in months):
        raise Stage3EdaError("EDA_MONTH_INVALID", "months must contain values from 1 through 12.")
    if months:
        normalized["months"] = sorted(set(months))
    for key, valid in (
        ("daysOfWeek", {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}),
        ("outcomes", set(GOLD_CLASS_ORDER)),
    ):
        values = [str(value).upper() for value in _normalize_sequence(filters.get(key), name=key)]
        if any(value not in valid for value in values):
            raise Stage3EdaError("EDA_FILTER_VALUE_INVALID", f"{key} contains an unsupported value.")
        if values:
            normalized[key] = values
    for key, column in (("batter", "batterCanonicalPlayerId"), ("pitcher", "pitcherCanonicalPlayerId")):
        values = [str(value).strip() for value in _normalize_sequence(filters.get(key), name=key, maximum=MAX_ID_FILTER_VALUES) if str(value).strip()]
        if values:
            if column not in schema_names:
                raise Stage3EdaError("EDA_FILTER_AUTHORITY_UNAVAILABLE", f"{key} is unavailable in the accepted publication.")
            normalized[key] = values
    start = str(filters.get("startDate") or DEVELOPMENT_START)
    end = str(filters.get("endDate") or DEVELOPMENT_END)
    try:
        start_date = pd.Timestamp(start).date()
        end_date = pd.Timestamp(end).date()
    except (TypeError, ValueError) as exc:
        raise Stage3EdaError("EDA_DATE_FILTER_INVALID", "EDA date filters must be ISO calendar dates.") from exc
    if start_date.isoformat() < DEVELOPMENT_START or end_date.isoformat() > DEVELOPMENT_END or start_date > end_date:
        raise Stage3EdaError(
            "FINAL_OOT_FILTER_PROHIBITED",
            f"EDA dates must remain within {DEVELOPMENT_START} through {DEVELOPMENT_END}; final OOT is locked.",
        )
    if start_date.isoformat() != DEVELOPMENT_START:
        normalized["startDate"] = start_date.isoformat()
    if end_date.isoformat() != DEVELOPMENT_END:
        normalized["endDate"] = end_date.isoformat()
    cold = str(filters.get("historyStatus") or "ALL").upper()
    if cold not in {"ALL", "COLD_START", "ESTABLISHED", "INSUFFICIENT_HISTORY"}:
        raise Stage3EdaError("EDA_COLD_START_FILTER_INVALID", "historyStatus has an unsupported value.")
    if cold != "ALL":
        normalized["historyStatus"] = cold
    home_away = str(filters.get("homeAway") or "ALL").upper()
    if home_away not in {"ALL", "HOME", "AWAY"}:
        raise Stage3EdaError("EDA_HOME_AWAY_FILTER_INVALID", "homeAway has an unsupported value.")
    if home_away != "ALL":
        normalized["homeAway"] = home_away
    missing_state = str(filters.get("missingness") or "").upper()
    if missing_state:
        if missing_state not in {"MISSING", "OBSERVED"} or not selected_variables:
            raise Stage3EdaError(
                "EDA_MISSING_FILTER_INVALID",
                "missingness requires MISSING or OBSERVED and a selected primary variable.",
            )
        normalized["missingness"] = {
            "variable": str(selected_variables[0]), "state": missing_state
        }
    simulation = filters.get("simulationState")
    if simulation:
        if not isinstance(simulation, Mapping):
            raise Stage3EdaError(
                "EDA_SIMULATION_FILTER_INVALID",
                "simulationState must contain one governed field and exact value.",
            )
        field = str(simulation.get("field") or "")
        value = simulation.get("value")
        if field not in SIMULATION_STATE_FIELDS or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise Stage3EdaError(
                "EDA_SIMULATION_FILTER_INVALID",
                "simulationState must use one of the five governed simulator fields and a finite numeric value.",
            )
        normalized["simulationState"] = {"field": field, "value": value}
    threshold = filters.get("minimumSampleSize")
    if threshold is not None and threshold != "":
        numeric = int(threshold)
        if numeric < 0 or numeric > DEVELOPMENT_ROWS:
            raise Stage3EdaError("EDA_SAMPLE_THRESHOLD_INVALID", "minimumSampleSize is outside the development population.")
        if numeric:
            normalized["minimumSampleSize"] = numeric
    return normalized


def _filter_columns(filters: Mapping[str, Any]) -> set[str]:
    result = {"game_date"}
    mapping = {
        "seasons": "season",
        "months": "game_month",
        "daysOfWeek": "game_day_of_week",
        "outcomes": "outcome",
        "batter": "batterCanonicalPlayerId",
        "pitcher": "pitcherCanonicalPlayerId",
        "homeAway": "context_top_bottom",
    }
    result.update(column for key, column in mapping.items() if key in filters)
    if "historyStatus" in filters:
        result.update({
            "batter_prior_missing", "pitcher_prior_missing",
            "batter_last100_insufficient", "pitcher_last250_insufficient",
        })
    if "missingness" in filters:
        result.add(str(filters["missingness"]["variable"]))
    if filters.get("battingTeam") or filters.get("fieldingTeam"):
        result.update({"canonicalGameId", "context_top_bottom"})
    if filters.get("simulationState"):
        result.add(str(filters["simulationState"]["field"]))
    return result


def _team_side_expression(
    authority: _Authority,
    teams: Sequence[str],
    *,
    batting: bool,
) -> pads.Expression:
    context = _team_context(authority)
    scoped = context[context["team_id"].astype(str).str.upper().isin(teams)]
    if scoped.empty:
        # A valid but absent exact team identity has an empty result; never
        # substitute a name/fuzzy match.
        return pads.field("canonicalGameId").isin([])
    if batting:
        home = scoped.loc[scoped["team_id"] == scoped["home_team_id"], "canonical_game_id"].astype(str).tolist()
        away = scoped.loc[scoped["team_id"] == scoped["away_team_id"], "canonical_game_id"].astype(str).tolist()
    else:
        # Fielding home team faces the away batting side (top); fielding away
        # team faces the home batting side (bottom).
        away = scoped.loc[scoped["team_id"] == scoped["home_team_id"], "canonical_game_id"].astype(str).tolist()
        home = scoped.loc[scoped["team_id"] == scoped["away_team_id"], "canonical_game_id"].astype(str).tolist()
    return (
        (pads.field("canonicalGameId").isin(home) & (pads.field("context_top_bottom") == pa.scalar(1)))
        | (pads.field("canonicalGameId").isin(away) & (pads.field("context_top_bottom") == pa.scalar(0)))
    )


def _arrow_filter(authority: _Authority, filters: Mapping[str, Any]) -> pads.Expression:
    expression = (
        (pads.field("game_date") >= pa.scalar(DEVELOPMENT_START))
        & (pads.field("game_date") <= pa.scalar(DEVELOPMENT_END))
    )
    if filters.get("seasons"):
        expression &= pads.field("season").isin(filters["seasons"])
    if filters.get("months"):
        expression &= pads.field("game_month").isin([float(item) for item in filters["months"]])
    if filters.get("daysOfWeek"):
        expression &= pads.field("game_day_of_week").isin(filters["daysOfWeek"])
    if filters.get("outcomes"):
        expression &= pads.field("outcome").isin(filters["outcomes"])
    if filters.get("batter"):
        expression &= pads.field("batterCanonicalPlayerId").isin(filters["batter"])
    if filters.get("pitcher"):
        expression &= pads.field("pitcherCanonicalPlayerId").isin(filters["pitcher"])
    if filters.get("startDate"):
        expression &= pads.field("game_date") >= pa.scalar(filters["startDate"])
    if filters.get("endDate"):
        expression &= pads.field("game_date") <= pa.scalar(filters["endDate"])
    cold = filters.get("historyStatus")
    batter_cold = pads.field("batter_prior_missing") == pa.scalar(True)
    pitcher_cold = pads.field("pitcher_prior_missing") == pa.scalar(True)
    if cold == "COLD_START":
        expression &= batter_cold | pitcher_cold
    elif cold == "ESTABLISHED":
        batter_insufficient = pads.field("batter_last100_insufficient") > pa.scalar(0)
        pitcher_insufficient = pads.field("pitcher_last250_insufficient") > pa.scalar(0)
        expression &= (~batter_cold) & (~pitcher_cold) & (~batter_insufficient) & (~pitcher_insufficient)
    elif cold == "INSUFFICIENT_HISTORY":
        expression &= (
            (pads.field("batter_last100_insufficient") > pa.scalar(0))
            | (pads.field("pitcher_last250_insufficient") > pa.scalar(0))
        )
    if filters.get("homeAway") == "HOME":
        expression &= pads.field("context_top_bottom") == pa.scalar(1)
    elif filters.get("homeAway") == "AWAY":
        expression &= pads.field("context_top_bottom") == pa.scalar(0)
    if filters.get("missingness"):
        variable = str(filters["missingness"]["variable"])
        predicate = pads.field(variable).is_null()
        expression &= predicate if filters["missingness"]["state"] == "MISSING" else ~predicate
    if filters.get("battingTeam"):
        expression &= _team_side_expression(authority, filters["battingTeam"], batting=True)
    if filters.get("fieldingTeam"):
        expression &= _team_side_expression(authority, filters["fieldingTeam"], batting=False)
    if filters.get("simulationState"):
        expression &= pads.field(str(filters["simulationState"]["field"])) == pa.scalar(
            filters["simulationState"]["value"]
        )
    return expression


def _scan(authority: _Authority, columns: Sequence[str], filters: Mapping[str, Any]) -> pd.DataFrame:
    requested = list(dict.fromkeys([*columns, *_filter_columns(filters)]))
    unknown = [name for name in requested if name not in authority.schema.names]
    if unknown:
        raise Stage3EdaError("EDA_VARIABLE_UNKNOWN", f"Unknown variables: {', '.join(sorted(unknown))}.")
    dataset = pads.dataset([str(path) for path in authority.paths], format="parquet")
    # The development predicate is part of the scanner expression, so target
    # columns are never materialized into an EDA table for final-OOT rows.
    table = dataset.scanner(columns=requested, filter=_arrow_filter(authority, filters), use_threads=True).to_table()
    minimum = int(filters.get("minimumSampleSize") or 0)
    if minimum and table.num_rows < minimum:
        raise Stage3EdaError(
            "EDA_MINIMUM_SAMPLE_NOT_MET",
            f"The active development-only filters represent {table.num_rows:,} rows, below the required minimum of {minimum:,}.",
        )
    return table.to_pandas(split_blocks=True, self_destruct=True)


def _percent(numerator: int | float, denominator: int | float) -> float:
    return float(100.0 * numerator / denominator) if denominator else 0.0


def _counts(series: pd.Series) -> list[dict[str, Any]]:
    counts = series.fillna("MISSING").astype(str).value_counts(dropna=False)
    total = int(counts.sum())
    return [
        {"value": str(value), "count": int(count), "percent": _percent(int(count), total)}
        for value, count in counts.items()
    ]


def _overview(authority: _Authority, filters: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    columns = [
        "canonicalGameId", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId",
        "game_date", "season", "outcome", "batter_prior_missing",
        "pitcher_prior_missing", "batter_prior_pa_count", *SIMULATION_STATE_FIELDS,
    ]
    frame = _scan(authority, columns, filters)
    rows = len(frame)
    dates = frame["game_date"].astype(str)
    cold = pd.to_numeric(frame["batter_prior_missing"], errors="coerce").fillna(0).gt(0) | pd.to_numeric(
        frame["pitcher_prior_missing"], errors="coerce"
    ).fillna(0).gt(0)
    target_distribution = _counts(frame["outcome"])
    target_by_season = []
    season_totals = frame["season"].value_counts(dropna=False).to_dict()
    for (season, outcome), count in frame.groupby(["season", "outcome"], dropna=False).size().items():
        season_total = int(season_totals[season])
        target_by_season.append({
            "season": int(season), "value": str(outcome), "count": int(count),
            "percent": _percent(int(count), season_total),
        })
    month_counts = dates.str.slice(0, 7).value_counts().sort_index()
    target_by_month = []
    month_values = dates.str.slice(0, 7)
    month_totals = month_values.value_counts(dropna=False).to_dict()
    for (month, outcome), count in pd.DataFrame({"month": month_values, "outcome": frame["outcome"]}).groupby(["month", "outcome"]).size().items():
        total = int(month_totals[month])
        target_by_month.append({
            "period": str(month), "value": str(outcome), "count": int(count),
            "percent": _percent(int(count), total),
        })
    target_by_simulation_state = []
    for state_field in SIMULATION_STATE_FIELDS:
        state_values = frame[state_field].astype(object).where(
            frame[state_field].notna(), "MISSING"
        )
        grouped = pd.DataFrame(
            {"state": state_values, "outcome": frame["outcome"]}
        ).groupby(["state", "outcome"], dropna=False).size()
        totals = state_values.value_counts(dropna=False).to_dict()
        for (state_value, outcome), count in grouped.items():
            total = int(totals[state_value])
            target_by_simulation_state.append({
                "field": state_field,
                "state": _json_safe(state_value),
                "value": str(outcome), "count": int(count),
                "percent": _percent(int(count), total),
            })
    metadata = _metadata_data(authority)
    history = pd.to_numeric(frame["batter_prior_pa_count"], errors="coerce")
    bands = pd.cut(
        history,
        bins=[-np.inf, 0, 25, 100, 250, np.inf],
        labels=["NO_PRIOR_HISTORY", "1-25", "26-100", "101-250", "251+"],
        right=True,
    )
    history_depth = _counts(bands.astype(object))
    family_coverage = [
        {
            "family": item["name"], "featureCount": item["featureCount"],
            "coveragePercent": item["coveragePercent"], "missingPercent": item["missingPercent"],
        }
        for item in metadata["families"]
    ]
    source_rows = 702_326
    gold_rows = 697_729
    return {
        "summary": {
            "developmentRows": rows,
            "games": int(frame["canonicalGameId"].nunique(dropna=True)),
            "batters": int(frame["batterCanonicalPlayerId"].nunique(dropna=True)),
            "pitchers": int(frame["pitcherCanonicalPlayerId"].nunique(dropna=True)),
            "startDate": str(dates.min()) if rows else None,
            "endDate": str(dates.max()) if rows else None,
            "targetClasses": len(GOLD_CLASS_ORDER),
            "coreFeatures": 48,
            "contextualCandidates": 206,
            "overallMissingPercent": float(np.mean([item["missingPercent"] for item in metadata["variables"] if item["role"] in {"PREGAME_FEATURE", "SIMULATION_GENERATED_STATE", "MISSINGNESS_INDICATOR"}])),
            "coldStartPercent": _percent(int(cold.sum()), rows),
            "rowExclusions": {
                "sourceRows": source_rows,
                "goldRows": gold_rows,
                "excludedRows": source_rows - gold_rows,
                "bySeason": [
                    {"season": 2023, "sourceRows": 184_497, "goldRows": 182_072, "excludedRows": 2_425},
                    {"season": 2024, "sourceRows": 182_883, "goldRows": 180_711, "excludedRows": 2_172},
                    {"season": 2025, "sourceRows": 182_847, "goldRows": 182_847, "excludedRows": 0},
                    {"season": 2026, "sourceRows": 152_099, "goldRows": 152_099, "excludedRows": 0},
                ],
                "reasonCounts": dict(
                    authority.exclusion_membership["causalReasonCounts"]
                ),
                "reasonStatus": "EXACT_DERIVED_CONSTRUCTION_STAGE_COUNTS",
                "unsupportedConcentrations": [
                    "finerSourceSideCause",
                ],
                "membershipEvidence": _membership_evidence(authority),
            },
        },
        "targetDistribution": target_distribution,
        "targetBySeason": sorted(target_by_season, key=lambda item: (item["season"], item["value"])),
        "targetByMonth": sorted(target_by_month, key=lambda item: (item["period"], item["value"])),
        "targetBySimulationState": target_by_simulation_state,
        "rowsByMonth": [{"period": str(period), "count": int(count)} for period, count in month_counts.items()],
        "featureFamilyCoverage": family_coverage,
        "historyDepth": history_depth,
    }, rows


def _numeric_distribution(
    authority: _Authority,
    variable: str,
    filters: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    bins = max(5, min(int(settings.get("bins") or 30), MAX_BINS))
    stratify = str(settings.get("stratifyBy") or ("outcome" if settings.get("stratifyByTarget") else ""))
    if stratify not in {"", "outcome", "season", "month"}:
        raise Stage3EdaError("EDA_STRATIFICATION_INVALID", "stratifyBy must be outcome, season, or month.")
    columns = [variable, "game_date"]
    if stratify == "outcome":
        columns.append("outcome")
    elif stratify == "season":
        columns.append("season")
    frame = _scan(authority, columns, filters)
    values = pd.to_numeric(frame[variable], errors="coerce")
    observed = values.dropna().to_numpy(dtype=float)
    observed = observed[np.isfinite(observed)]
    if observed.size:
        quantiles = np.quantile(observed, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
        hist_counts, hist_edges = np.histogram(observed, bins=bins)
        density, density_edges = np.histogram(observed, bins=bins, density=True)
        q1, median, q3 = quantiles[2], quantiles[3], quantiles[4]
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        ecdf_quantiles = np.linspace(0.0, 1.0, 101)
        ecdf_values = np.quantile(observed, ecdf_quantiles)
        statistics = {
            "count": int(observed.size), "missingCount": int(values.isna().sum()),
            "missingPercent": _percent(int(values.isna().sum()), len(values)),
            "min": float(np.min(observed)), "max": float(np.max(observed)),
            "mean": float(np.mean(observed)), "std": float(np.std(observed, ddof=1)) if observed.size > 1 else 0.0,
            "q01": quantiles[0], "q05": quantiles[1], "q25": q1, "median": median,
            "q75": q3, "q95": quantiles[5], "q99": quantiles[6],
        }
        histogram = [
            {"binStart": float(hist_edges[index]), "binEnd": float(hist_edges[index + 1]),
             "count": int(count), "percent": _percent(int(count), observed.size)}
            for index, count in enumerate(hist_counts)
        ]
        density_rows = [
            {"value": float((density_edges[index] + density_edges[index + 1]) / 2.0), "density": float(value)}
            for index, value in enumerate(density)
        ]
        box = {
            "min": float(np.min(observed)), "q1": float(q1), "median": float(median),
            "q3": float(q3), "max": float(np.max(observed)), "lowerFence": float(lower),
            "upperFence": float(upper), "outlierCount": int(((observed < lower) | (observed > upper)).sum()),
        }
        ecdf = [
            {"value": float(value), "cumulativePercent": float(percent * 100.0)}
            for value, percent in zip(ecdf_values, ecdf_quantiles)
        ]
    else:
        statistics = {key: None for key in ("min", "max", "mean", "std", "q01", "q05", "q25", "median", "q75", "q95", "q99")}
        statistics.update({"count": 0, "missingCount": len(values), "missingPercent": _percent(len(values), len(values))})
        histogram, density_rows, ecdf, box = [], [], [], {key: None for key in ("min", "q1", "median", "q3", "max", "lowerFence", "upperFence", "outlierCount")}
    stratified = []
    if stratify:
        strata = frame["game_date"].astype(str).str.slice(0, 7) if stratify == "month" else frame[stratify]
        temp = pd.DataFrame({"stratum": strata, "value": values})
        for stratum, group in temp.groupby("stratum", dropna=False):
            clean = group["value"].dropna()
            stratified.append({
                "stratum": str(stratum), "count": int(len(group)),
                "mean": float(clean.mean()) if len(clean) else None,
                "median": float(clean.median()) if len(clean) else None,
                "missingPercent": _percent(int(group["value"].isna().sum()), len(group)),
            })
    return {
        "variable": variable,
        "dataType": "numeric",
        "statistics": statistics,
        "histogram": histogram,
        "ecdf": ecdf,
        "density": density_rows,
        "box": box,
        "stratified": stratified,
    }, len(frame)


def _category_counts(
    authority: _Authority,
    variable: str,
    filters: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    top_n = max(1, min(int(settings.get("topN") or 20), MAX_CATEGORIES))
    frame = _scan(authority, [variable, "outcome"], filters)
    values = frame[variable].astype(object).where(frame[variable].notna(), "MISSING").astype(str)
    counts = values.value_counts()
    selected = list(counts.index[:top_n])
    categories = []
    for value in selected:
        mask = values.eq(value)
        target = _counts(frame.loc[mask, "outcome"])
        categories.append({
            "value": value, "count": int(mask.sum()), "percent": _percent(int(mask.sum()), len(frame)),
            "targetComposition": target,
        })
    return {
        "variable": variable,
        "categories": categories,
        "missingCount": int(frame[variable].isna().sum()),
        "otherCount": int(counts.iloc[top_n:].sum()) if len(counts) > top_n else 0,
    }, len(frame)


def _cramers_v(left: pd.Series, right: pd.Series) -> tuple[float | None, int]:
    table = pd.crosstab(left.fillna("MISSING"), right.fillna("MISSING"))
    n = int(table.to_numpy().sum())
    if n == 0 or min(table.shape) < 2:
        return None, n
    observed = table.to_numpy(dtype=float)
    expected = observed.sum(axis=1, keepdims=True) @ observed.sum(axis=0, keepdims=True) / n
    valid = expected > 0
    chi2 = float(np.sum(((observed - expected) ** 2)[valid] / expected[valid]))
    phi2 = chi2 / n
    rows, columns = table.shape
    corrected = max(0.0, phi2 - ((columns - 1) * (rows - 1)) / max(n - 1, 1))
    rows_corrected = rows - ((rows - 1) ** 2) / max(n - 1, 1)
    columns_corrected = columns - ((columns - 1) ** 2) / max(n - 1, 1)
    denominator = min(columns_corrected - 1, rows_corrected - 1)
    return (math.sqrt(corrected / denominator) if denominator > 0 else None), n


def _correlation_ratio(categories: pd.Series, numeric: pd.Series) -> tuple[float | None, int]:
    frame = pd.DataFrame({"category": categories, "numeric": pd.to_numeric(numeric, errors="coerce")}).dropna()
    n = len(frame)
    if n < 2 or frame["category"].nunique() < 2:
        return None, n
    overall = float(frame["numeric"].mean())
    numerator = sum(len(group) * (float(group.mean()) - overall) ** 2 for _, group in frame.groupby("category")["numeric"])
    denominator = float(((frame["numeric"] - overall) ** 2).sum())
    return (math.sqrt(numerator / denominator) if denominator > 0 else None), n


def _association(
    authority: _Authority,
    variables: Sequence[str],
    filters: Mapping[str, Any],
    settings: Mapping[str, Any],
    types: Mapping[str, str],
) -> tuple[dict[str, Any], int]:
    frame = _scan(authority, variables, filters)
    preferred = str(settings.get("method") or "auto").lower()
    if preferred not in {"auto", "pearson", "spearman"}:
        raise Stage3EdaError("EDA_ASSOCIATION_METHOD_INVALID", "Association method must be auto, pearson, or spearman.")
    cells = []
    methods: set[str] = set()
    for left in variables:
        for right in variables:
            left_numeric = types[left] == "numeric"
            right_numeric = types[right] == "numeric"
            if left == right:
                value, method, rows = 1.0, ("Pearson" if left_numeric else "Cramer's V"), int(frame[left].notna().sum())
            elif left_numeric and right_numeric:
                method = "Spearman" if preferred in {"auto", "spearman"} else "Pearson"
                pair = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
                rows = len(pair)
                value = float(pair[left].corr(pair[right], method=method.lower())) if rows > 1 else None
            elif not left_numeric and not right_numeric:
                method = "Cramer's V"
                value, rows = _cramers_v(frame[left], frame[right])
            else:
                method = "Correlation ratio"
                category, numeric = (frame[left], frame[right]) if not left_numeric else (frame[right], frame[left])
                value, rows = _correlation_ratio(category, numeric)
            methods.add(method)
            cells.append({"x": left, "y": right, "value": value, "method": method, "rows": int(rows)})
    return {"variables": list(variables), "methods": sorted(methods), "cells": cells}, len(frame)


def _pairwise_sample(
    authority: _Authority,
    variables: Sequence[str],
    filters: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], int, dict[str, Any]]:
    size = max(1, min(int(settings.get("sampleSize") or 2_000), MAX_SAMPLE_ROWS))
    seed = int(settings.get("seed") or 20260830)
    frame = _scan(authority, ["canonicalPaId", *variables], filters)
    population = len(frame)
    if population > size:
        identifiers = frame["canonicalPaId"].fillna("").astype(str).to_numpy()
        scores = np.fromiter(
            (
                int.from_bytes(hashlib.sha256(f"{seed}:{value}".encode("utf-8")).digest()[:8], "big")
                for value in identifiers
            ),
            dtype=np.uint64,
            count=population,
        )
        indices = np.argpartition(scores, size - 1)[:size]
        indices = indices[np.argsort(scores[indices], kind="stable")]
        sampled = frame.iloc[indices]
    else:
        sampled = frame
    # canonicalPaId governs the deterministic hash selection, but the browser
    # receives only the explicitly selected analytical variables.
    rows = [
        _json_safe(row)
        for row in sampled[list(variables)].to_dict(orient="records")
    ]
    sampling = {
        "method": "HASH_SMALLEST_CANONICAL_PA_V1",
        "seed": seed,
        "sampleSize": len(sampled),
        "populationSize": population,
    }
    return {
        "variables": list(variables), "populationSize": population, "sampleSize": len(sampled),
        "seed": seed, "method": "HASH_SMALLEST_CANONICAL_PA_V1", "rows": rows,
    }, population, sampling


def _reason_counts(frame: pd.DataFrame, variable: str, missing: pd.Series) -> dict[str, int]:
    allowed = {
        "NO_PRIOR_HISTORY", "INSUFFICIENT_HISTORY", "SOURCE_MISSING",
        "IDENTITY_FAILURE", "COMPUTATION_FAILURE", "SOURCE_NOT_AVAILABLE_FOR_ERA",
    }
    reason_column = "batting_missing_reason" if variable.startswith("batting_") else "fielding_missing_reason" if variable.startswith("fielding_") else None
    result: Counter[str] = Counter()
    if reason_column and reason_column in frame:
        for raw in frame.loc[missing, reason_column].dropna().astype(str):
            tokens = {token.strip().upper() for token in raw.replace("|", ",").split(",") if token.strip()}
            matched = tokens & allowed
            if matched:
                for token in matched:
                    result[token] += 1
            else:
                result["SOURCE_MISSING"] += 1
    elif variable.startswith("batter_"):
        no_prior = missing & pd.to_numeric(frame.get("batter_prior_missing", 0), errors="coerce").fillna(0).gt(0)
        insufficient = missing & ~no_prior & pd.to_numeric(frame.get("batter_last100_insufficient", 0), errors="coerce").fillna(0).gt(0)
        result["NO_PRIOR_HISTORY"] += int(no_prior.sum())
        result["INSUFFICIENT_HISTORY"] += int(insufficient.sum())
        result["SOURCE_MISSING"] += int((missing & ~no_prior & ~insufficient).sum())
    elif variable.startswith("pitcher_"):
        no_prior = missing & pd.to_numeric(frame.get("pitcher_prior_missing", 0), errors="coerce").fillna(0).gt(0)
        insufficient = missing & ~no_prior & pd.to_numeric(frame.get("pitcher_last250_insufficient", 0), errors="coerce").fillna(0).gt(0)
        result["NO_PRIOR_HISTORY"] += int(no_prior.sum())
        result["INSUFFICIENT_HISTORY"] += int(insufficient.sum())
        result["SOURCE_MISSING"] += int((missing & ~no_prior & ~insufficient).sum())
    elif int(missing.sum()):
        result["SOURCE_MISSING"] += int(missing.sum())
    return {key: int(value) for key, value in sorted(result.items()) if value}


def _missingness(
    authority: _Authority,
    variables: Sequence[str],
    filters: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    extra = {
        "game_date", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId",
        "batter_prior_missing", "batter_last100_insufficient",
        "pitcher_prior_missing", "pitcher_last250_insufficient",
        "batting_missing_reason", "fielding_missing_reason",
    }
    frame = _scan(authority, [*variables, *extra], filters)
    rows = len(frame)
    results = []
    aggregate_reasons: Counter[str] = Counter()
    by_period = []
    period = frame["game_date"].astype(str).str.slice(0, 7)
    missing_masks: dict[str, pd.Series] = {}
    for variable in variables:
        mask = frame[variable].isna()
        missing_masks[variable] = mask
        player_field = "batterCanonicalPlayerId" if variable.startswith(("batter_", "batting_")) else "pitcherCanonicalPlayerId" if variable.startswith(("pitcher_", "fielding_")) else None
        reason_counts = _reason_counts(frame, variable, mask)
        aggregate_reasons.update(reason_counts)
        results.append({
            "name": variable, "missingCount": int(mask.sum()),
            "missingPercent": _percent(int(mask.sum()), rows),
            "affectedPlayers": int(frame.loc[mask, player_field].nunique(dropna=True)) if player_field else 0,
            "reasonCounts": reason_counts,
        })
        temp = pd.DataFrame({"period": period, "missing": mask})
        for value, group in temp.groupby("period"):
            by_period.append({
                "period": str(value), "variable": variable,
                "missingCount": int(group["missing"].sum()),
                "missingPercent": _percent(int(group["missing"].sum()), len(group)),
            })
    co_missingness = []
    for left in variables:
        for right in variables:
            count = int((missing_masks[left] & missing_masks[right]).sum())
            co_missingness.append({"x": left, "y": right, "count": count, "percent": _percent(count, rows)})
    return {
        "variables": results,
        "coMissingness": co_missingness,
        "byPeriod": by_period,
        "reasons": [{"reason": key, "count": int(value)} for key, value in sorted(aggregate_reasons.items())],
    }, rows


def _outliers(
    authority: _Authority,
    variable: str,
    filters: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    method = str(settings.get("method") or "IQR").upper()
    if method not in {"IQR", "ROBUST_Z"}:
        raise Stage3EdaError("EDA_OUTLIER_METHOD_INVALID", "Outlier method must be IQR or ROBUST_Z.")
    frame = _scan(authority, ["canonicalPaId", "game_date", variable], filters)
    values = pd.to_numeric(frame[variable], errors="coerce")
    observed = values.dropna()
    if observed.empty:
        lower = upper = None
        mask = pd.Series(False, index=frame.index)
    elif method == "IQR":
        q1, q3 = observed.quantile([0.25, 0.75])
        iqr = float(q3 - q1)
        lower, upper = float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)
        mask = values.lt(lower) | values.gt(upper)
    else:
        median = float(observed.median())
        mad = float(np.median(np.abs(observed.to_numpy() - median)))
        scale = 1.4826 * mad
        lower, upper = (median - 3.5 * scale, median + 3.5 * scale) if scale > 0 else (median, median)
        mask = values.lt(lower) | values.gt(upper)
    extreme = frame.loc[mask, ["canonicalPaId", "game_date", variable]].copy()
    if not extreme.empty:
        extreme["distance"] = np.maximum(lower - pd.to_numeric(extreme[variable]), pd.to_numeric(extreme[variable]) - upper)
        extreme = extreme.sort_values("distance", ascending=False).head(MAX_EXTREMES)
    extremes = [
        {"canonicalPaId": str(row["canonicalPaId"]), "gameDate": str(row["game_date"]),
         "value": _json_safe(row[variable]), "side": "LOW" if row[variable] < lower else "HIGH"}
        for _, row in extreme.iterrows()
    ]
    return {
        "variable": variable, "method": method, "thresholds": {"lower": lower, "upper": upper},
        "count": int(mask.sum()), "percent": _percent(int(mask.sum()), len(frame)), "extremes": extremes,
    }, len(frame)


def _psi(base: np.ndarray, current: np.ndarray, categorical: bool) -> float | None:
    if len(base) == 0 or len(current) == 0:
        return None
    epsilon = 1e-6
    if categorical:
        labels = sorted(set(base.astype(str)) | set(current.astype(str)))
        base_counts = Counter(base.astype(str))
        current_counts = Counter(current.astype(str))
        base_pct = np.array([base_counts[label] / len(base) for label in labels])
        current_pct = np.array([current_counts[label] / len(current) for label in labels])
    else:
        quantiles = np.unique(np.quantile(base.astype(float), np.linspace(0, 1, 11)))
        if len(quantiles) < 2:
            return 0.0
        quantiles[0], quantiles[-1] = -np.inf, np.inf
        base_pct = np.histogram(base.astype(float), bins=quantiles)[0] / len(base)
        current_pct = np.histogram(current.astype(float), bins=quantiles)[0] / len(current)
    base_pct = np.clip(base_pct, epsilon, None)
    current_pct = np.clip(current_pct, epsilon, None)
    return float(np.sum((current_pct - base_pct) * np.log(current_pct / base_pct)))


def _ks(base: np.ndarray, current: np.ndarray) -> float | None:
    if len(base) == 0 or len(current) == 0:
        return None
    combined = np.sort(np.unique(np.concatenate([base, current]).astype(float)))
    left = np.searchsorted(np.sort(base.astype(float)), combined, side="right") / len(base)
    right = np.searchsorted(np.sort(current.astype(float)), combined, side="right") / len(current)
    return float(np.max(np.abs(left - right)))


def _temporal(
    authority: _Authority,
    variable: str,
    filters: Mapping[str, Any],
    settings: Mapping[str, Any],
    data_type: str,
) -> tuple[dict[str, Any], int]:
    granularity = str(settings.get("granularity") or "month").lower()
    if granularity not in {"month", "season"}:
        raise Stage3EdaError("EDA_TEMPORAL_GRANULARITY_INVALID", "Temporal granularity must be month or season.")
    frame = _scan(authority, ["game_date", "season", "outcome", variable], filters)
    period = frame["season"].astype(str) if granularity == "season" else frame["game_date"].astype(str).str.slice(0, 7)
    work = pd.DataFrame({"period": period, "value": frame[variable], "outcome": frame["outcome"]})
    series = []
    grouped_values: dict[str, np.ndarray] = {}
    for label, group in work.groupby("period", sort=True):
        observed = group["value"].dropna()
        grouped_values[str(label)] = observed.to_numpy()
        numeric = pd.to_numeric(observed, errors="coerce").dropna() if data_type == "numeric" else pd.Series(dtype=float)
        series.append({
            "period": str(label), "count": int(len(group)),
            "mean": float(numeric.mean()) if len(numeric) else None,
            "median": float(numeric.median()) if len(numeric) else None,
            "missingPercent": _percent(int(group["value"].isna().sum()), len(group)),
            "targetComposition": _counts(group["outcome"]),
        })
    drift = []
    labels = sorted(grouped_values)
    if labels:
        baseline_label = labels[0]
        baseline = grouped_values[baseline_label]
        for label in labels:
            current = grouped_values[label]
            numeric = data_type == "numeric"
            drift.append({
                "period": label, "baselinePeriod": baseline_label,
                "psi": _psi(baseline, current, not numeric),
                "ks": _ks(baseline.astype(float), current.astype(float)) if numeric and len(baseline) and len(current) else None,
                "method": "PSI_AND_KS" if numeric else "CATEGORICAL_PSI",
            })
    return {"variable": variable, "granularity": granularity, "series": series, "drift": drift}, len(frame)


def _cold_start(authority: _Authority, filters: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    columns = [
        "game_date", "outcome", "canonicalGameId", "context_top_bottom", "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId", "batter_prior_missing", "batter_last100_insufficient",
        "pitcher_prior_missing", "pitcher_last250_insufficient",
    ]
    frame = _scan(authority, columns, filters)
    rows = len(frame)
    game_sides = _team_context(authority)[
        ["canonical_game_id", "home_team_id", "away_team_id"]
    ].drop_duplicates("canonical_game_id")
    home_by_game = dict(zip(game_sides["canonical_game_id"], game_sides["home_team_id"]))
    away_by_game = dict(zip(game_sides["canonical_game_id"], game_sides["away_team_id"]))
    # Top/bottom is already part of the accepted simulator-state contract:
    # 0 = away batting, 1 = home batting.
    top_bottom = pd.to_numeric(frame["context_top_bottom"], errors="coerce").fillna(-1)
    home_team = frame["canonicalGameId"].map(home_by_game)
    away_team = frame["canonicalGameId"].map(away_by_game)
    frame["battingTeamId"] = np.where(top_bottom.eq(1), home_team, away_team)
    frame["fieldingTeamId"] = np.where(top_bottom.eq(1), away_team, home_team)
    flags = {
        "batter_no": pd.to_numeric(frame["batter_prior_missing"], errors="coerce").fillna(0).gt(0),
        "batter_insufficient": pd.to_numeric(frame["batter_last100_insufficient"], errors="coerce").fillna(0).gt(0),
        "pitcher_no": pd.to_numeric(frame["pitcher_prior_missing"], errors="coerce").fillna(0).gt(0),
        "pitcher_insufficient": pd.to_numeric(frame["pitcher_last250_insufficient"], errors="coerce").fillna(0).gt(0),
    }
    period = frame["game_date"].astype(str).str.slice(0, 7)

    def side(prefix: str, player_field: str, team_field: str) -> dict[str, Any]:
        no_prior, insufficient = flags[f"{prefix}_no"], flags[f"{prefix}_insufficient"]
        by_period = []
        for label in sorted(period.unique()):
            current = period.eq(label)
            by_period.append({
                "period": str(label), "noPriorRows": int((current & no_prior).sum()),
                "insufficientRows": int((current & insufficient).sum()),
            })
        return {
            "noPriorRows": int(no_prior.sum()), "insufficientRows": int(insufficient.sum()),
            "affectedPlayers": int(frame.loc[no_prior | insufficient, player_field].nunique(dropna=True)),
            "affectedGames": int(frame.loc[no_prior | insufficient, "canonicalGameId"].nunique(dropna=True)),
            "affectedTeams": int(frame.loc[no_prior | insufficient, team_field].nunique(dropna=True)),
            "byPeriod": by_period,
        }

    target_composition = []
    for scope, mask in (
        ("BATTER_COLD", flags["batter_no"] | flags["batter_insufficient"]),
        ("BATTER_ESTABLISHED", ~(flags["batter_no"] | flags["batter_insufficient"])),
        ("PITCHER_COLD", flags["pitcher_no"] | flags["pitcher_insufficient"]),
        ("PITCHER_ESTABLISHED", ~(flags["pitcher_no"] | flags["pitcher_insufficient"])),
    ):
        for item in _counts(frame.loc[mask, "outcome"]):
            target_composition.append({"scope": scope, **item})
    cold = flags["batter_no"] | flags["batter_insufficient"] | flags["pitcher_no"] | flags["pitcher_insufficient"]
    affected_teams = pd.concat(
        [
            frame.loc[cold, "battingTeamId"],
            frame.loc[cold, "fieldingTeamId"],
        ],
        ignore_index=True,
    ).nunique(dropna=True)
    return {
        "summary": {
            "coldStartRows": int(cold.sum()),
            "coldStartPercent": _percent(int(cold.sum()), rows),
            "affectedGames": int(frame.loc[cold, "canonicalGameId"].nunique(dropna=True)),
            "affectedTeams": int(affected_teams),
        },
        "batter": side("batter", "batterCanonicalPlayerId", "battingTeamId"),
        "pitcher": side("pitcher", "pitcherCanonicalPlayerId", "fieldingTeamId"),
        "targetComposition": target_composition,
    }, rows


def _population(
    *, filters: Mapping[str, Any], rows: int, aggregation: str,
    sampling: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "scope": "DEVELOPMENT_ONLY",
        "rows": DEVELOPMENT_ROWS,
        "developmentRows": DEVELOPMENT_ROWS,
        "finalOotRows": FINAL_OOT_ROWS,
        "finalOotLocked": True,
        "developmentEndDate": DEVELOPMENT_END,
        "filtersApplied": dict(filters),
        "rowsRepresented": int(rows),
        "aggregation": aggregation,
        "sampling": dict(sampling) if sampling is not None else None,
    }


def _audit_flags() -> dict[str, Any]:
    return {
        "finalOotTargetAccessed": False,
        "finalOotUsedForSelection": False,
        "legacyGlobalMatrixUsed": False,
        "providerCalls": 0,
        "modelActivity": {
            "fits": 0,
            "scores": 0,
            "tunes": 0,
            "calibrations": 0,
            "selections": 0,
            "promotions": 0,
        },
    }


def stage3_eda_metadata(database: Database, project_id: str) -> dict[str, Any]:
    authority = _resolve_authority(database, project_id)
    cache_key = f"metadata:{authority.review_digest}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "cacheStatus": "HIT"}
    response = {
        "ok": True,
        "authority": authority.public(),
        "population": _population(filters={}, rows=DEVELOPMENT_ROWS, aggregation="REGISTERED_AUTHORITY_METADATA"),
        "audit": _audit_flags(),
        "data": _metadata_data(authority),
        "cacheStatus": "MISS",
    }
    _cache_put(cache_key, response)
    return response


def _query_variables(
    payload: Mapping[str, Any],
    schema_names: set[str],
    selectable_names: set[str],
) -> list[str]:
    raw = payload.get("variables") or []
    variables = [str(value) for value in (raw if isinstance(raw, list) else [raw])]
    if len(variables) > MAX_VARIABLES:
        raise Stage3EdaError("EDA_VARIABLE_LIMIT_EXCEEDED", f"At most {MAX_VARIABLES} variables may be queried together.")
    unknown = [
        name
        for name in variables
        if name not in schema_names
        or name in _LINEAGE_FIELDS
        or name not in selectable_names
    ]
    if unknown:
        raise Stage3EdaError("EDA_VARIABLE_UNKNOWN", f"Unknown or nonselectable variables: {', '.join(sorted(unknown))}.")
    return variables


def stage3_eda_query(database: Database, project_id: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3EdaError("EDA_QUERY_INVALID", "The EDA query body must be an object.")
    authority = _resolve_authority(database, project_id)
    query_type = str(payload.get("queryType") or "").strip()
    if query_type not in _SUPPORTED_QUERY_TYPES:
        raise Stage3EdaError("EDA_QUERY_TYPE_INVALID", "queryType is not a supported Stage 3 analytical operation.")
    schema_names = set(authority.schema.names)
    variable_meta = {item["name"]: item for item in _variables(authority)}
    selectable_names = {
        name for name, item in variable_meta.items() if item.get("selectable") is True
    }
    variables = _query_variables(payload, schema_names, selectable_names)
    filters = _normalize_filters(payload.get("filters"), schema_names, variables)
    settings = payload.get("settings") or {}
    if not isinstance(settings, Mapping):
        raise Stage3EdaError("EDA_QUERY_SETTINGS_INVALID", "settings must be an object.")
    normalized_payload = {
        "queryType": query_type,
        "filters": filters,
        "variables": variables,
        "settings": dict(settings),
    }
    cache_key = hashlib.sha256(canonical_json_bytes({
        "projectId": project_id,
        "authority": authority.review_digest,
        "query": normalized_payload,
    })).hexdigest()
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "cacheStatus": "HIT", "queryDurationMs": 0.0}

    started = time.perf_counter()
    sampling: dict[str, Any] | None = None
    if query_type == "overview":
        data, rows = _overview(authority, filters)
        aggregation = "SERVER_AGGREGATE"
    elif query_type == "distribution":
        if len(variables) != 1:
            raise Stage3EdaError("EDA_VARIABLE_REQUIRED", "distribution requires exactly one variable.")
        variable = variables[0]
        if variable_meta.get(variable, {}).get("dataType") != "numeric":
            data, rows = _category_counts(authority, variable, filters, settings)
            data = {"variable": variable, "dataType": "categorical", "categories": data["categories"], "missingCount": data["missingCount"], "otherCount": data["otherCount"]}
        else:
            data, rows = _numeric_distribution(authority, variable, filters, settings)
        aggregation = "SERVER_AGGREGATE"
    elif query_type == "category_counts":
        if len(variables) != 1:
            raise Stage3EdaError("EDA_VARIABLE_REQUIRED", "category_counts requires exactly one variable.")
        data, rows = _category_counts(authority, variables[0], filters, settings)
        aggregation = "SERVER_AGGREGATE"
    elif query_type == "association":
        if len(variables) < 2:
            raise Stage3EdaError("EDA_VARIABLE_REQUIRED", "association requires two to six variables.")
        data, rows = _association(
            authority, variables, filters, settings,
            {name: str(variable_meta.get(name, {}).get("dataType") or "categorical") for name in variables},
        )
        aggregation = "SERVER_AGGREGATE"
    elif query_type == "pairwise_sample":
        if len(variables) < 2:
            raise Stage3EdaError("EDA_VARIABLE_REQUIRED", "pairwise_sample requires two to six variables.")
        data, rows, sampling = _pairwise_sample(authority, variables, filters, settings)
        aggregation = "DETERMINISTIC_POINT_SAMPLE"
    elif query_type == "missingness":
        if not variables:
            variables = [name for name in GOLD_FEATURES if variable_meta[name]["missingPercent"] > 0][:MAX_VARIABLES]
        data, rows = _missingness(authority, variables, filters)
        aggregation = "SERVER_AGGREGATE"
    elif query_type == "outliers":
        if len(variables) != 1 or variable_meta.get(variables[0], {}).get("dataType") != "numeric":
            raise Stage3EdaError("EDA_NUMERIC_VARIABLE_REQUIRED", "outliers requires exactly one numeric variable.")
        data, rows = _outliers(authority, variables[0], filters, settings)
        aggregation = "SERVER_AGGREGATE_WITH_BOUNDED_EXTREMES"
    elif query_type == "temporal":
        if len(variables) != 1:
            raise Stage3EdaError("EDA_VARIABLE_REQUIRED", "temporal requires exactly one variable.")
        data, rows = _temporal(
            authority, variables[0], filters, settings,
            str(variable_meta.get(variables[0], {}).get("dataType") or "categorical"),
        )
        aggregation = "SERVER_AGGREGATE"
    else:
        data, rows = _cold_start(authority, filters)
        aggregation = "SERVER_AGGREGATE"

    response = _json_safe({
        "ok": True,
        "authority": authority.public(),
        "population": _population(filters=filters, rows=rows, aggregation=aggregation, sampling=sampling),
        "audit": _audit_flags(),
        "data": data,
        "cacheStatus": "MISS",
        "queryDurationMs": round((time.perf_counter() - started) * 1000.0, 3),
    })
    _cache_put(cache_key, response)
    return response


__all__ = [
    "EDA_SCHEMA_VERSION",
    "Stage3EdaError",
    "stage3_eda_metadata",
    "stage3_eda_query",
]
