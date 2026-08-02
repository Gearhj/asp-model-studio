from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..analytics.analysis_scope import scope_identity, workspace_fingerprint, workspace_scope
from ..analytics.target_intelligence_service import (
    assess_class_balance,
    classify_monotonicity,
    wilson_score_interval,
)
from ..core.dataset_store import DATASTORE
from ..datasets.dataset_identity import assert_expected_active_identity
from ..evidence.evidence_store import upsert_evidence
from ..preprocessing.bureau_registry import BUREAU_SPECIAL_VALUES, name_signals
from ..preprocessing.feature_profile_service import information_value
from ..preprocessing.quality_profile_service import governed_time_field
from ..analytics.target_intelligence_service import (
    MAX_TOP_CATEGORIES,
    SMALL_GROUP_MIN_EVENTS,
    SMALL_GROUP_MIN_ROWS,
    summarize_target_by_predictor,
)
from .workspace_types import (
    EDARelationshipSampleRequest,
    EDAVifResolutionDecisionRequest,
    EDAVifResolutionPlanRequest,
    EDAVifSimulationRequest,
    EDAWorkspaceRequest,
    TargetByPredictorRequest,
)
from .vif_plan_store import (
    get_feature_recommendations,
    get_plan,
    list_feature_recommendations,
    record_plan_decision,
    save_generated_plan,
)
from .vif_resolution import build_vif_resolution_plan, plan_hash
from .analytical_contract import (
    EDAAnalyticalContractError,
    build_governed_eda_contract,
    classify_feature_values,
    resolve_development_partition,
)


_DATE_NAME = re.compile(r"(^|_)(date|month|year|period|timestamp|time)($|_)", re.IGNORECASE)
_ID_NAME = re.compile(r"(^|_)(id|key|uuid|account|customer|application|transaction)(_?id)?($|_)", re.IGNORECASE)
_LEAKAGE_NAME = re.compile(r"target|outcome|response|label|post[_ ]|future|approved|declined", re.IGNORECASE)
_SPLIT_NAME = re.compile(r"(^|_)(split|fold|partition|sample_role)($|_)", re.IGNORECASE)
_SYSTEM_NAME = re.compile(r"(^|_)(__|row_number|source_file|ingested_at|created_at|updated_at)($|_)", re.IGNORECASE)
_TARGET_SOURCE_MAX_DISTINCT = 50

# Part I: two conservative name families, kept separate because they mean
# different things to a reviewer. A target-derived name suggests the column was
# computed FROM the outcome; a post-outcome name suggests it was recorded AFTER
# the outcome was known. Neither is evidence of leakage on its own -- both only
# ever produce a "Review recommended" state.
_TARGET_DERIVED_NAME = re.compile(r"target|label|outcome|response|_y$|^y_|class(_|$)|score|probability|pred", re.IGNORECASE)
_POST_OUTCOME_NAME = re.compile(r"post[_ ]|future|after[_ ]|_final$|closed|settle|resolution|charge.?off|recover|writeoff|write.?off", re.IGNORECASE)

# Leakage assessment states, ordered by strength of claim. `confirmed_leakage`
# is never produced by a rule -- it exists so a reviewer's explicit confirmation
# has somewhere to live.
LEAKAGE_STATES = ("no_signal", "review_recommended", "likely_leakage", "confirmed_leakage")

# A perfect-separation check is only meaningful on a low-cardinality column: a
# near-unique identifier trivially separates every row and would otherwise be
# reported as leakage in every dataset.
MAX_SEPARATION_CARDINALITY = 50
MIN_SEPARATION_ROWS = 100
# Correlation this close to +/-1 with a numeric target is not a predictor.
PERFECT_CORRELATION_THRESHOLD = 0.999
PREDICTOR_VISUAL_CONTRACT_VERSION = "eda-predictor-visual-v1"


class RelationshipSampleValidationError(ValueError):
    """Safe, structured rejection for a crafted relationship sample request."""

    def __init__(self, rejected_fields: list[dict[str, str]]) -> None:
        self.rejected_fields = rejected_fields
        super().__init__(
            "One or more requested relationship fields are not authorized for "
            "this governed dataset."
        )


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return _finite(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _problem_type(target: pd.Series, requested: str | None) -> str:
    if requested in {"classification", "regression"}:
        return requested
    unique = int(target.dropna().nunique())
    return "classification" if 1 < unique <= 20 else "regression"


def _event_value(target: pd.Series, requested: Any) -> Any:
    values = list(pd.unique(target.dropna()))
    if requested is not None and any(str(value) == str(requested) for value in values):
        return next(value for value in values if str(value) == str(requested))
    for candidate in values:
        if str(candidate).strip().lower() in {"1", "true", "yes", "event", "bad", "fraud"}:
            return candidate
    if len(values) == 2:
        counts = target.value_counts(dropna=True)
        return counts.index[-1]
    return None


def _numeric_series(series: pd.Series) -> tuple[pd.Series, bool]:
    numeric = pd.to_numeric(series, errors="coerce")
    nonmissing = int(series.notna().sum())
    numeric_rate = float(numeric.notna().sum()) / max(nonmissing, 1)
    return numeric, bool(pd.api.types.is_numeric_dtype(series) or numeric_rate >= 0.8)


def _series_quantiles(series: pd.Series) -> dict[str, float | None]:
    clean = series.dropna()
    if clean.empty:
        return {"q1": None, "median": None, "q3": None}
    values = clean.quantile([0.25, 0.5, 0.75])
    return {
        "q1": _finite(values.loc[0.25]),
        "median": _finite(values.loc[0.5]),
        "q3": _finite(values.loc[0.75]),
    }


def _event_rate(values: pd.Series, event: Any) -> float | None:
    valid = values.dropna()
    if valid.empty or event is None:
        return None
    return float((valid.astype(str) == str(event)).mean())


def _bureau_special_profile(
    feature: str,
    series: pd.Series,
    numeric: pd.Series,
    target: pd.Series,
    event: Any,
) -> tuple[pd.Series, dict[str, Any]]:
    """Profile meaning-bearing bureau codes separately from null missingness.

    A configured numeric code is only treated as a bureau special value when
    the server has a bureau signal for the feature, an existing governed bureau
    review identifies it, or the registered source is explicitly HELOC. This
    avoids reclassifying an ordinary value such as 99 in an unrelated numeric
    field merely because it appears in the shared bureau registry.
    """

    classification = classify_feature_values(
        feature,
        series,
        meta=DATASTORE.meta,
        target=target,
        event_value=event,
    )
    special_mask = classification["masks"]["bureau_special_value"]
    special_count = int(special_mask.sum())
    regular_mask = classification["masks"]["ordinary_valid_value"]
    regular_event_rate = classification["ordinary_event_rate"]
    value_rows = [
        {
            "value": group["code"],
            "definition": group["definition"],
            "count": group["rows"],
            "prevalence": group["population_share"],
            "event_rate": group["event_rate"],
            "event_count": group["event_count"],
            "valid_value_event_rate_difference": group[
                "valid_value_event_rate_difference"
            ],
            "event_rate_confidence_interval_95": group[
                "event_rate_confidence_interval_95"
            ],
        }
        for group in classification["special_groups"]
    ]
    return special_mask, {
        "identified": bool(classification["special_identification_basis"]),
        "count": special_count,
        "prevalence": special_count / max(len(series), 1),
        "regular_numeric_count": int(regular_mask.sum()),
        "regular_event_rate": regular_event_rate,
        "values": value_rows,
        "identification_basis": classification["special_identification_basis"],
        "missing_values_included": False,
    }


def _predictor_event_shape(
    *,
    kind: str,
    source_rows: list[dict[str, Any]],
    population_rows: int,
    limit: int,
    special_value_labels: set[str] | None = None,
) -> dict[str, Any]:
    """Return a bounded chart-ready event-rate shape without raw observations."""

    special_labels = special_value_labels or set()
    groups: list[dict[str, Any]] = []
    for row in source_rows:
        level = str(row.get("level") or "")
        if level == "__MISSING__" or level in special_labels:
            continue
        count = int(row.get("count") or 0)
        group = {
            "label": (
                f"Q{len(groups) + 1}"
                if kind == "quantile"
                else level
            ),
            "count": count,
            "population_rate": count / max(population_rows, 1),
            "event_rate": _finite(row.get("event_rate")),
        }
        if kind == "quantile":
            group.update(
                {
                    "minimum": _finite(row.get("minimum")),
                    "maximum": _finite(row.get("maximum")),
                    "event_count": int(row.get("events") or 0),
                }
            )
        groups.append(group)
        if len(groups) >= limit:
            break
    return {
        "kind": kind,
        "scope": "full_dataset_aggregates",
        "limit": limit,
        "groups": groups,
        "returned_groups": len(groups),
        "truncated": len(source_rows) > len(groups),
        "raw_observations_included": False,
    }


def _detect_frame_target_sources(
    frame: pd.DataFrame,
    target: str,
    candidates: list[str],
) -> dict[str, dict[str, Any]]:
    """Derive deterministic target lineage from the current backend frame.

    This mirrors the governed-profile rule without trusting a client flag or a
    HELOC-specific name.  A low-cardinality field is a target source only when
    every observed source value maps to exactly one observed target value.
    """

    found: dict[str, dict[str, Any]] = {}
    if target not in frame.columns:
        return found
    for column in candidates:
        if column == target or column not in frame.columns:
            continue
        paired = frame[[column, target]].dropna()
        distinct = int(paired[column].nunique(dropna=True))
        if paired.empty or distinct < 2 or distinct > _TARGET_SOURCE_MAX_DISTINCT:
            continue
        grouped = (
            paired.assign(
                __source__=paired[column].astype(str),
                __target__=paired[target].astype(str),
            )
            .groupby("__source__", dropna=False)
            .agg(target_count=("__target__", "nunique"), target_value=("__target__", "first"), row_count=("__target__", "size"))
        )
        if grouped.empty or int(grouped["target_count"].max()) > 1:
            continue
        found[str(column)] = {
            "field": str(column),
            "target": target,
            "relationship": "deterministic_target_source",
            "mapping": [
                {
                    "sourceValue": str(index),
                    "targetValue": str(row["target_value"]),
                    "rowCount": int(row["row_count"]),
                }
                for index, row in grouped.sort_values("row_count", ascending=False).iterrows()
            ],
        }
    return found


def _predictor_authorization(
    frame: pd.DataFrame,
    target: str,
    lineage_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Return the server-authored predictor manifest for EDA.

    Browser ``selected_features`` values can narrow this list later, but can
    never add to it.  Existing Feature Manifest decisions take precedence over
    the older Data Acquisition selected-column list.  In legacy workspaces with
    no manifest, the server-held active columns are the authoritative fallback.
    """

    active_candidates = [str(column) for column in frame.columns if str(column) != target]
    selected = [column for column in DATASTORE.get_selected_columns() if column in frame.columns and column != target]
    candidates = selected or active_candidates

    manifest = DATASTORE.meta.get("feature_manifest")
    manifest = manifest if isinstance(manifest, dict) else {}
    manifest_rows = [row for row in manifest.get("features", []) if isinstance(row, dict) and row.get("feature_name")]
    manifest_by_name = {str(row["feature_name"]): row for row in manifest_rows}
    if manifest_rows:
        candidates = [
            column
            for column in candidates
            if (
                column in manifest_by_name
                and bool(manifest_by_name[column].get("selected"))
                and str(manifest_by_name[column].get("eligibility_status") or "eligible") == "eligible"
                and str(manifest_by_name[column].get("leakage_status") or "reviewed") != "locked"
            )
        ]

    prohibited = {
        str(value)
        for value in (
            (DATASTORE.meta.get("source") or {}).get("prohibitedVariables", [])
            if isinstance(DATASTORE.meta.get("source"), dict)
            else []
        )
    }
    role_excluded: dict[str, dict[str, Any]] = {}
    preliminary: list[str] = []
    for column in candidates:
        if _SPLIT_NAME.search(column):
            role_excluded[column] = {"feature": column, "role": "split_indicator", "reason": "Split or fold metadata"}
        elif _SYSTEM_NAME.search(column):
            role_excluded[column] = {"feature": column, "role": "system_metadata", "reason": "System metadata"}
        elif column in prohibited:
            role_excluded[column] = {"feature": column, "role": "prohibited", "reason": "Explicitly prohibited variable"}
        else:
            preliminary.append(column)

    # Preserve explicit upstream target-source decisions first. Dynamic
    # deterministic-source detection is itself target-directed, so it may use
    # only the exact materialized development indices/target. It never scans
    # the full lineage frame or sealed holdout.
    target_sources: dict[str, dict[str, Any]] = {}
    for name, row in manifest_by_name.items():
        reason = str(row.get("exclusion_reason") or "")
        role = str(row.get("role") or row.get("feature_role") or "")
        explicitly_target_source = bool(
            row.get("is_target_source")
            or role.casefold() == "target_source"
            or "target source" in reason.casefold()
            or "deterministic source" in reason.casefold()
        )
        if explicitly_target_source:
            target_sources[name] = {
                "field": name,
                "target": target,
                "relationship": "governed_upstream_target_source",
                "mapping": [],
            }

    scoped_store = DATASTORE.current()
    development_features = scoped_store.X_train
    development_target = scoped_store.y_train
    if (
        isinstance(development_features, pd.DataFrame)
        and isinstance(development_target, pd.Series)
        and not development_features.empty
        and development_features.index.equals(development_target.index)
    ):
        if (
            lineage_frame is not None
            and not lineage_frame.empty
            and development_features.index.isin(lineage_frame.index).all()
        ):
            detection_frame = lineage_frame.loc[development_features.index].copy()
        else:
            detection_frame = development_features.copy()
        detection_frame[target] = development_target
        lineage_candidates = [
            str(column) for column in detection_frame.columns if str(column) != target
        ]
        detected = _detect_frame_target_sources(
            detection_frame,
            target,
            lineage_candidates,
        )
        target_sources.update(
            {
                name: {**payload, "analysis_scope": "development_population"}
                for name, payload in detected.items()
            }
        )
    authorized = [column for column in preliminary if column not in target_sources]

    manifest_excluded: dict[str, dict[str, Any]] = {}
    for name, row in manifest_by_name.items():
        if name == target or name in authorized or name in target_sources:
            continue
        manifest_excluded[name] = {
            "feature": name,
            "role": str(row.get("eligibility_status") or "excluded"),
            "reason": str(row.get("exclusion_reason") or "Not selected in the server feature manifest"),
        }

    exclusion_rows = [
        {"feature": target, "role": "target", "reason": "Modeling target"},
        *[
            {
                "feature": name,
                "role": "target_source",
                "reason": "Deterministic source of modeling target",
            }
            for name in sorted(target_sources)
        ],
        *[role_excluded[name] for name in sorted(role_excluded)],
        *[manifest_excluded[name] for name in sorted(manifest_excluded)],
    ]
    stable = {
        "target": target,
        "authorized": authorized,
        "excluded": exclusion_rows,
        "upstream": manifest.get("manifest_version"),
        "dataset_id": DATASTORE.meta.get("dataset_id"),
        "dataset_version_id": DATASTORE.meta.get("dataset_version_id"),
    }
    version = str(manifest.get("manifest_version") or f"eda-pm-{hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}")
    return {
        "manifest_version": version,
        "source": "feature_manifest" if manifest_rows else "data_acquisition_selection",
        "target": target,
        "authorized_predictors": authorized,
        "excluded": exclusion_rows,
        "target_source_fields": list(target_sources.values()),
        "target_source_excluded": sorted(target_sources),
    }


def _quantile_event_table(feature: pd.Series, target: pd.Series, event: Any, bins: int = 10) -> list[dict[str, Any]]:
    numeric = pd.to_numeric(feature, errors="coerce")
    frame = pd.DataFrame({"value": numeric, "target": target}).dropna(subset=["value", "target"])
    if frame.empty:
        return []
    try:
        frame["bucket"] = pd.qcut(frame["value"].rank(method="first"), q=min(bins, len(frame)), duplicates="drop")
    except ValueError:
        frame["bucket"] = frame["value"].astype(str)
    frame["event"] = frame["target"].astype(str) == str(event)
    grouped = frame.groupby("bucket", observed=True, dropna=False).agg(
        count=("event", "size"),
        events=("event", "sum"),
        minimum=("value", "min"),
        maximum=("value", "max"),
    )
    return [
        {
            "bucket": str(index),
            "count": int(row["count"]),
            "events": int(row["events"]),
            "event_rate": float(row["events"] / row["count"]) if row["count"] else None,
            "minimum": _finite(row["minimum"]),
            "maximum": _finite(row["maximum"]),
        }
        for index, row in grouped.iterrows()
    ]


def _histogram_bins(series: pd.Series, bins: int = 20) -> list[dict[str, Any]]:
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return []
    requested_bins = min(max(5, int(bins)), 60)
    counts, edges = np.histogram(numeric.to_numpy(dtype=float), bins=requested_bins)
    return [
        {
            "bin": index + 1,
            "lower": _finite(edges[index]),
            "upper": _finite(edges[index + 1]),
            "count": int(count),
        }
        for index, count in enumerate(counts)
    ]


def _monotonicity(rows: list[dict[str, Any]]) -> str:
    """Delegates to the single shared implementation so the Predictor tab and the
    Target tab can never label the same band table differently."""
    return classify_monotonicity([row.get("event_rate") for row in rows])


class EDAWorkspaceService:
    def __init__(self, max_cache_entries: int = 36) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._contract_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_cache_entries = max_cache_entries

    def _dataset(self, request: EDAWorkspaceRequest) -> tuple[pd.DataFrame, str, pd.Series, str, Any, dict[str, Any]]:
        # Every EDA calculation is downstream of activation. Resolve the exact
        # immutable Library version before reading the ambient frame so stale
        # checkpoints and legacy browser pseudo-versions fail closed.
        assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=getattr(request, "expected_dataset_id", None),
            expected_dataset_version_id=getattr(
                request,
                "expected_dataset_version_id",
                None,
            ),
            legacy_dataset_version=getattr(request, "dataset_version", None),
            require_expected=True,
        )
        active = DATASTORE.get_active_df()
        if active is None or active.empty:
            raise ValueError("No full backend dataset is loaded.")
        governed_target = str(DATASTORE.target or "").strip()
        if not governed_target or governed_target not in active.columns:
            raise ValueError(
                "The server-governed modeling target is unavailable. "
                "Return to Data Acquisition and confirm the target before running EDA."
            )
        if request.target and str(request.target) != governed_target:
            raise ValueError("The requested target does not match the server-governed modeling target.")
        target = governed_target
        base = DATASTORE.get_base_df()
        raw = DATASTORE.raw_df
        lineage_frame = (
            raw
            if raw is not None and not raw.empty and target in raw.columns
            else base
        )
        authorization = _predictor_authorization(active, target, lineage_frame)
        keep = [
            column
            for column in authorization["authorized_predictors"]
            if column in active.columns and column != target
        ]
        df = active.loc[:, [*keep, target]].copy()
        y = df[target]
        scoped_store = DATASTORE.current()
        development_target = scoped_store.y_train
        target_for_decision = (
            development_target
            if isinstance(development_target, pd.Series)
            and not development_target.empty
            else y
        )
        problem = _problem_type(target_for_decision, request.problem_type)
        event = (
            _event_value(target_for_decision, request.event_value)
            if problem == "classification"
            else None
        )
        return df, str(target), y, problem, event, authorization

    def _workspace_scope(
        self,
        df: pd.DataFrame,
        target: str,
        project_id: str,
        analysis_source: str,
        fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """Draft scope for the in-memory population.

        Always `workspace_draft`, even when the frame was loaded FROM a Library
        version: the in-memory frame can have been mutated since it was loaded,
        so it is not the immutable artifact. The originating version is carried
        as a suggestion only, so the UI can offer a one-click governed rerun.
        """
        source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta.get("source"), dict) else {}
        return workspace_scope(
            project_id=project_id,
            target=target,
            population_rows=int(len(df)),
            fingerprint=fingerprint or self._fingerprint(df, target, source),
            dataset_name=str(source.get("filename") or "Workspace dataset"),
            analysis_source=analysis_source,
            exact=True,
            linked_dataset_id=(
                source.get("dataset_id") or source.get("datasetId")
                if source.get("kind") == "dataset_library"
                else None
            ),
            linked_version_id=(
                source.get("dataset_version_id") or source.get("versionId")
                if source.get("kind") == "dataset_library"
                else None
            ),
        )

    def _fingerprint(self, df: pd.DataFrame, target: str, source: dict[str, Any]) -> str:
        """Compute a bounded content fingerprint for the current request.

        Do not memoize by shape or filename: a replacement upload can share both
        and must never inherit a previous analysis cache entry.
        """
        return workspace_fingerprint(df, target, source)

    def _key(
        self,
        section: str,
        request: EDAWorkspaceRequest,
        df: pd.DataFrame,
        target: str,
        authorization: dict[str, Any],
        fingerprint: str,
    ) -> str:
        source_frame = DATASTORE.get_base_df()
        scoped_store = DATASTORE.current()
        split_record = (
            scoped_store.meta.get("split_record")
            if isinstance(scoped_store.meta.get("split_record"), dict)
            else {}
        )
        development_fingerprint = None
        if (
            isinstance(scoped_store.X_train, pd.DataFrame)
            and isinstance(scoped_store.y_train, pd.Series)
        ):
            digest = hashlib.sha256()
            digest.update(
                pd.util.hash_pandas_object(
                    scoped_store.X_train,
                    index=True,
                ).values.tobytes()
            )
            digest.update(
                pd.util.hash_pandas_object(
                    scoped_store.y_train,
                    index=True,
                ).values.tobytes()
            )
            development_fingerprint = digest.hexdigest()
        payload = {
            "section": section,
            "project_id": request.project_id,
            # The EDA service is process-global while DatasetStore is scoped.
            # A source-frame identity plus monotonic revision prevents one
            # authorized workspace from reusing another workspace's response.
            "workspace_instance": id(source_frame) if source_frame is not None else None,
            "data_revision": int(getattr(DATASTORE, "data_revision", 0)),
            "split_id": split_record.get("split_id"),
            "split_status": scoped_store.meta.get("split_status"),
            "development_fingerprint": development_fingerprint,
            # Content identity, so a replacement upload with the same shape can
            # never be served the previous dataset's cached section.
            "workspace_fingerprint": fingerprint,
            "dataset_id": DATASTORE.meta.get("dataset_id"),
            "dataset_version_id": DATASTORE.meta.get("dataset_version_id"),
            "shape": list(df.shape),
            "target": target,
            "event_value": request.event_value,
            "problem_type": request.problem_type,
            "selected_features": sorted(request.selected_features),
            "pairwise_features": request.pairwise_features,
            "segment_field": request.segment_field,
            "date_field": request.date_field,
            "histogram_bins": request.histogram_bins,
            "predictor_visual_shape_limit": request.predictor_visual_shape_limit,
            "rendered_sample_limit": request.rendered_sample_limit,
            "manifest_version": (DATASTORE.meta.get("feature_manifest") or {}).get("manifest_version") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else None,
            "predictor_authorization": authorization,
            "feature": request.feature,
            "selection_min": request.selection_min,
            "selection_max": request.selection_max,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _governed_contract(
        self,
        *,
        request: EDAWorkspaceRequest,
        df: pd.DataFrame,
        target: str,
        event: Any,
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve the single development-scoped artifact shared by all tabs."""

        scoped_store = DATASTORE.current()
        split_record = (
            scoped_store.meta.get("split_record")
            if isinstance(scoped_store.meta.get("split_record"), dict)
            else {}
        )
        development_digest = hashlib.sha256()
        if isinstance(scoped_store.X_train, pd.DataFrame):
            development_digest.update(
                pd.util.hash_pandas_object(
                    scoped_store.X_train,
                    index=True,
                ).values.tobytes()
            )
        if isinstance(scoped_store.y_train, pd.Series):
            development_digest.update(
                pd.util.hash_pandas_object(
                    scoped_store.y_train,
                    index=True,
                ).values.tobytes()
            )
        source = (
            scoped_store.meta.get("source")
            if isinstance(scoped_store.meta.get("source"), dict)
            else {}
        )
        cache_identity = {
            "project_id": request.project_id,
            "dataset_id": scoped_store.meta.get("dataset_id"),
            "dataset_version_id": scoped_store.meta.get("dataset_version_id"),
            "target": target,
            "event": event,
            "predictor_manifest_id": authorization.get("manifest_version"),
            "split_id": split_record.get("split_id"),
            "split_status": scoped_store.meta.get("split_status"),
            "data_revision": int(getattr(scoped_store, "data_revision", 0)),
            "development_fingerprint": development_digest.hexdigest(),
            "full_population_fingerprint": self._fingerprint(df, target, source),
        }
        cache_key = hashlib.sha256(
            json.dumps(cache_identity, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if cache_key in self._contract_cache:
            contract = self._contract_cache.pop(cache_key)
            self._contract_cache[cache_key] = contract
            return contract
        contract = build_governed_eda_contract(
            project_id=request.project_id,
            full_frame=df,
            target=target,
            event_value=event,
            authorization=authorization,
            store=scoped_store,
            requested_bins=10,
        )
        self._contract_cache[cache_key] = contract
        while len(self._contract_cache) > min(self._max_cache_entries, 12):
            self._contract_cache.popitem(last=False)
        return contract

    @staticmethod
    def _legacy_special_profile(artifact: dict[str, Any]) -> dict[str, Any]:
        special = artifact.get("special_values") or {}
        groups = special.get("groups") or []
        counts = (
            (artifact.get("value_classification") or {}).get(
                "development_counts"
            )
            or {}
        )
        return {
            "identified": bool(groups),
            "count": int(counts.get("bureau_special_value") or 0),
            "prevalence": sum(
                float(group.get("population_share") or 0) for group in groups
            ),
            "regular_numeric_count": int(counts.get("ordinary_valid_value") or 0),
            "regular_event_rate": (artifact.get("special_values") or {}).get(
                "ordinary_valid_event_rate"
            ),
            "values": [
                {
                    "value": group.get("code"),
                    "definition": group.get("definition"),
                    "count": int(group.get("rows") or 0),
                    "prevalence": group.get("population_share"),
                    "event_rate": group.get("event_rate"),
                    "valid_value_event_rate_difference": group.get(
                        "valid_value_event_rate_difference"
                    ),
                    "event_rate_confidence_interval_95": group.get(
                        "event_rate_confidence_interval_95"
                    ),
                }
                for group in groups
            ],
            "identification_basis": special.get("identified_by") or [],
            "missing_values_included": False,
            "policy_id": special.get("policy"),
        }

    def _harmonize_with_governed_contract(
        self,
        *,
        section: str,
        result: dict[str, Any],
        contract: dict[str, Any],
        request: EDAWorkspaceRequest,
    ) -> None:
        """Keep compatibility fields aligned with one authoritative artifact."""

        predictor_artifacts = contract["predictor_artifacts"]
        relationship = contract["relationship_artifact"]
        result["governed_analytical_contract"] = contract
        result["governed_target_artifact"] = contract["target_artifact"]
        result["governed_predictor_artifacts"] = predictor_artifacts
        result["governed_relationship_artifact"] = relationship
        result["governed_analysis_scope"] = {
            "analysis_scope": contract["analysis_scope"],
            "analysis_population_id": contract["analysis_population_id"],
            "population_rows": contract["population_rows"],
            "rows_used": contract["rows_used"],
            "rows_excluded": contract["rows_excluded"],
            "exclusion_reasons": contract["exclusion_reasons"],
            "split_id": contract["split_id"],
            "final_holdout_accessed": False,
            "final_holdout_used_for_selection": False,
        }

        if section == "target":
            result["development_target_profile"] = contract["target_artifact"]

        if section == "target" and isinstance(result.get("predictor_preview"), dict):
            ranked = sorted(
                predictor_artifacts.values(),
                key=lambda item: abs(float(item.get("iv") or 0)),
                reverse=True,
            )
            preview_limit = min(5, len(ranked))
            preview_rows = []
            for artifact in ranked[:preview_limit]:
                ordinary_bin_type = (
                    "ordinary_valid_range"
                    if artifact.get("is_numeric")
                    else "ordinary_category"
                )
                ordinary_bins = [
                    row
                    for row in (artifact.get("iv_woe") or {}).get("bins") or []
                    if row.get("bin_type") == ordinary_bin_type
                ][: int(request.predictor_visual_shape_limit)]
                preview_rows.append(
                    {
                        "feature": artifact["feature"],
                        "kind": "numeric" if artifact.get("is_numeric") else "categorical",
                        "iv": artifact["iv"],
                        "iv_artifact_id": artifact["iv_artifact_id"],
                        "monotonicity": (
                            artifact.get("monotonicity") or {}
                        ).get("valid_value_shape"),
                        "monotonicity_artifact_id": artifact[
                            "monotonicity_artifact_id"
                        ],
                        "event_rate_spread": (
                            max(
                                float(row["event_rate"])
                                for row in ordinary_bins
                                if row.get("event_rate") is not None
                            )
                            - min(
                                float(row["event_rate"])
                                for row in ordinary_bins
                                if row.get("event_rate") is not None
                            )
                            if sum(
                                row.get("event_rate") is not None
                                for row in ordinary_bins
                            )
                            >= 2
                            else None
                        ),
                        "groups": [
                            {
                                "label": row["label"],
                                "count": row["count"],
                                "event_count": row["event_count"],
                                "event_rate": row["event_rate"],
                                "minimum": row.get("lower"),
                                "maximum": row.get("upper"),
                            }
                            for row in ordinary_bins
                        ],
                    }
                )
            result["predictor_preview"] = {
                "scope": "development_population",
                "analysis_population_id": contract["analysis_population_id"],
                "split_id": contract["split_id"],
                "population_rows": contract["rows_used"],
                "predictor_limit": preview_limit,
                "shape_limit": int(request.predictor_visual_shape_limit),
                "candidate_count": len(ranked),
                "returned_predictors": len(preview_rows),
                "request_mode": "governed_shared_analytical_contract",
                "server_authorized_predictors_only": True,
                "target_excluded": True,
                "final_holdout_accessed": False,
                "raw_observations_included": False,
                "predictors": preview_rows,
            }

        if section == "predictors":
            vif_by_feature = relationship.get("vif_by_feature") or {}
            for collection in [
                *(result.get("numeric") or []),
                *(result.get("categorical") or []),
            ]:
                feature = str(collection.get("feature") or "")
                artifact = predictor_artifacts.get(feature)
                if not artifact:
                    continue
                iv_woe = artifact["iv_woe"]
                monotonicity = artifact["monotonicity"]
                ordinary_bin_type = (
                    "ordinary_valid_range"
                    if artifact.get("is_numeric")
                    else "ordinary_category"
                )
                ordinary_bins = [
                    row
                    for row in iv_woe["bins"]
                    if row.get("bin_type") == ordinary_bin_type
                ]
                collection.update(
                    {
                        "missing_count": int(
                            (
                                artifact.get("value_classification") or {}
                            ).get("full_population_counts", {}).get("true_null")
                            or 0
                        ),
                        "missing_rate": int(
                            (
                                artifact.get("value_classification") or {}
                            ).get("full_population_counts", {}).get("true_null")
                            or 0
                        )
                        / max(contract["population_rows"], 1),
                        "iv": artifact["iv"],
                        "correlation_with_target": artifact.get(
                            "correlation_with_target"
                        ),
                        "iv_artifact_id": artifact["iv_artifact_id"],
                        "iv_woe": iv_woe,
                        "monotonicity": monotonicity["valid_value_shape"],
                        "regular_monotonicity": monotonicity[
                            "valid_value_shape"
                        ],
                        "monotonicity_artifact_id": monotonicity["artifact_id"],
                        "analysis_scope": "development_population",
                        "analysis_population_id": contract[
                            "analysis_population_id"
                        ],
                        "event_rate_by_quantile": [
                            {
                                "bucket": row["label"],
                                "count": row["count"],
                                "events": row["event_count"],
                                "event_rate": row["event_rate"],
                                "minimum": row["lower"],
                                "maximum": row["upper"],
                            }
                            for row in ordinary_bins
                        ],
                        "bureau_special": self._legacy_special_profile(artifact),
                        "ordinary_outlier_count": artifact[
                            "ordinary_outlier"
                        ]["count"],
                        "ordinary_outlier_rate": artifact[
                            "ordinary_outlier"
                        ]["rate"],
                        "ordinary_outlier_denominator": artifact[
                            "ordinary_outlier"
                        ]["denominator"],
                        "vif": (vif_by_feature.get(feature) or {}).get("vif"),
                        "vif_status": (vif_by_feature.get(feature) or {}).get(
                            "status", "not_available"
                        ),
                    }
                )
            for visual in result.get("predictor_visual_profiles") or []:
                feature = str(visual.get("feature") or "")
                artifact = predictor_artifacts.get(feature)
                if not artifact:
                    continue
                metrics = visual.setdefault("metrics", {})
                full_counts = (
                    (artifact.get("value_classification") or {}).get(
                        "full_population_counts"
                    )
                    or {}
                )
                development_counts = (
                    (artifact.get("value_classification") or {}).get(
                        "development_counts"
                    )
                    or {}
                )
                full_missing = int(full_counts.get("true_null") or 0)
                visual["missing"] = {
                    **(visual.get("missing") or {}),
                    "count": full_missing,
                    "rate": full_missing / max(contract["population_rows"], 1),
                    "development_count": int(
                        development_counts.get("true_null") or 0
                    ),
                    "structural_scope": "full_governed_population",
                    "event_rate_scope": "development_population",
                    "semantics": "null_only",
                }
                decision_special = self._legacy_special_profile(artifact)
                full_special = int(full_counts.get("bureau_special_value") or 0)
                decision_special.update(
                    {
                        "count": full_special,
                        "prevalence": full_special
                        / max(contract["population_rows"], 1),
                        "regular_numeric_count": int(
                            full_counts.get("ordinary_valid_value") or 0
                        ),
                        "development_count": int(
                            development_counts.get("bureau_special_value") or 0
                        ),
                        "structural_scope": "full_governed_population",
                        "event_rate_scope": "development_population",
                    }
                )
                visual["bureau_special"] = decision_special
                visual["ordinary_outlier"] = {
                    "count": int(artifact["ordinary_outlier"]["count"] or 0),
                    "rate": artifact["ordinary_outlier"]["rate"],
                    "denominator": int(
                        artifact["ordinary_outlier"]["denominator"] or 0
                    ),
                    "excludes_nulls": True,
                    "excludes_bureau_special_values": True,
                    "semantics": "regular_numeric_iqr_only",
                    "structural_scope": "full_governed_population",
                }
                metrics.update(
                    {
                        "iv": artifact["iv"],
                        "missing_rate": visual["missing"]["rate"],
                        "special_prevalence": decision_special["prevalence"],
                        "monotonicity": artifact["monotonicity"][
                            "valid_value_shape"
                        ],
                        "vif": (
                            (vif_by_feature.get(feature) or {}).get("vif")
                            if artifact.get("is_numeric")
                            else None
                        ),
                        "vif_status": (
                            (vif_by_feature.get(feature) or {}).get(
                                "status", "not_available"
                            )
                            if artifact.get("is_numeric")
                            else "not_applicable_categorical"
                        ),
                    }
                )
                ordinary_bin_type = (
                    "ordinary_valid_range"
                    if artifact.get("is_numeric")
                    else "ordinary_category"
                )
                shape_rows = [
                    row
                    for row in artifact["iv_woe"]["bins"]
                    if row.get("bin_type") == ordinary_bin_type
                ][: int(request.predictor_visual_shape_limit)]
                visual["event_rate_shape"] = {
                    "kind": "quantile" if artifact.get("is_numeric") else "top_levels",
                    "scope": "development_population",
                    "analysis_population_id": contract["analysis_population_id"],
                    "population_rows": contract["rows_used"],
                    "limit": int(request.predictor_visual_shape_limit),
                    "groups": [
                        {
                            "label": row["label"],
                            "count": row["count"],
                            "population_rate": row["count"] / max(contract["rows_used"], 1),
                            "event_rate": row["event_rate"],
                            "event_count": row["event_count"],
                            "minimum": row.get("lower"),
                            "maximum": row.get("upper"),
                        }
                        for row in shape_rows
                    ],
                    "returned_groups": len(shape_rows),
                    "truncated": len(shape_rows) < artifact["iv_woe"]["effective_nonempty_bins"],
                    "raw_observations_included": False,
                    "final_holdout_accessed": False,
                }
                visual["scope"] = "governed_mixed_scope"
                visual["population_rows"] = contract["population_rows"]
                visual["descriptive_scope"] = "full_governed_population"
                visual["target_directed_scope"] = "development_population"
                visual["target_directed_rows"] = contract["rows_used"]
                visual["artifact_id"] = artifact["artifact_id"]

        if section == "relationships":
            correlation = relationship["correlation"]
            strong_pairs: list[dict[str, Any]] = []
            correlation_columns = correlation["columns"]
            pearson_matrix = correlation["pearson_matrix"]
            for left_index, left in enumerate(correlation_columns):
                for right_index in range(left_index + 1, len(correlation_columns)):
                    value = pearson_matrix[left_index][right_index]
                    if value is not None and abs(float(value)) >= 0.7:
                        strong_pairs.append(
                            {
                                "feature_a": left,
                                "feature_b": correlation_columns[right_index],
                                "correlation": value,
                                "relationship_artifact_id": relationship["artifact_id"],
                            }
                        )
            strong_pairs.sort(
                key=lambda row: abs(float(row["correlation"])), reverse=True
            )
            pairwise_features = [
                str(feature)
                for feature in request.pairwise_features[:6]
                if feature in predictor_artifacts
                and (predictor_artifacts[feature] or {}).get("is_numeric")
            ]
            pairwise_records: list[dict[str, Any]] = []
            pairwise_eligible_rows = 0
            if pairwise_features:
                scoped_store = DATASTORE.current()
                development_features = scoped_store.X_train
                development_target = scoped_store.y_train
                if isinstance(development_features, pd.DataFrame) and isinstance(development_target, pd.Series):
                    sample = development_features.loc[:, pairwise_features].apply(
                        pd.to_numeric, errors="coerce"
                    )
                    for feature in pairwise_features:
                        codes = {
                            float(group["code"])
                            for group in (
                                predictor_artifacts[feature].get("special_values")
                                or {}
                            ).get("development_groups")
                            or []
                        }
                        if codes:
                            sample[feature] = sample[feature].mask(
                                sample[feature].isin(codes)
                            )
                    sample["__event__"] = development_target.astype(str).eq(
                        str(contract["positive_value"])
                    )
                    sample = sample.dropna(subset=pairwise_features)
                    pairwise_eligible_rows = int(len(sample))
                    bounded = sample.head(request.rendered_sample_limit)
                    pairwise_records = [
                        {
                            str(key): _json_value(value)
                            for key, value in row.items()
                        }
                        for row in bounded.to_dict(orient="records")
                    ]
            result.update(
                {
                    "correlation_columns": correlation["columns"],
                    "correlation_matrix": correlation["pearson_matrix"],
                    "correlation_spearman_matrix": correlation[
                        "spearman_matrix"
                    ],
                    "correlation_n_matrix": correlation[
                        "pairwise_row_counts"
                    ],
                    "correlation_scope": correlation,
                    "strong_pairs": strong_pairs[:100],
                    "vif": relationship["vif"],
                    "vif_scope": relationship["vif_scope"],
                    "target_association": [
                        {
                            "feature": artifact["feature"],
                            "iv": artifact["iv"],
                            "iv_artifact_id": artifact["iv_artifact_id"],
                            "correlation_with_target": artifact.get(
                                "correlation_with_target"
                            ),
                            "monotonicity": artifact["monotonicity"][
                                "valid_value_shape"
                            ],
                            "monotonicity_artifact_id": artifact[
                                "monotonicity_artifact_id"
                            ],
                            "analysis_scope": "development_population",
                        }
                        for artifact in sorted(
                            predictor_artifacts.values(),
                            key=lambda item: abs(
                                float(
                                    item.get("iv")
                                    or item.get("correlation_with_target")
                                    or 0
                                )
                            ),
                            reverse=True,
                        )
                    ],
                    "pairwise_features": pairwise_features,
                    "pairwise_sample": pairwise_records,
                    "pairwise_scope": (
                        "bounded_visual_sample" if pairwise_features else "unavailable"
                    ),
                    "pairwise_rows": len(pairwise_records),
                    "pairwise_event_rows": sum(
                        bool(row.get("__event__")) for row in pairwise_records
                    ),
                    "pairwise_scope_disclosure": {
                        "source_population": "development_population",
                        "analysis_population_id": contract[
                            "analysis_population_id"
                        ],
                        "population_rows": contract["rows_used"],
                        "eligible_rows": pairwise_eligible_rows,
                        "rows_excluded": contract["rows_used"]
                        - pairwise_eligible_rows,
                        "exclusion_reasons": [
                            "true_null",
                            "bureau_special_value",
                            "parse_failure",
                            "non_finite",
                            "incomplete_pairwise_case",
                        ],
                        "rendered_rows": len(pairwise_records),
                        "sample_limit": request.rendered_sample_limit,
                        "special_value_representation": "excluded",
                        "final_holdout_accessed": False,
                    },
                }
            )

        if section == "distribution":
            feature = str(result.get("feature") or request.feature or "")
            artifact = predictor_artifacts.get(feature)
            if artifact:
                ordinary_distribution = artifact.get("ordinary_distribution") or {}
                ordinary_histogram = [
                    {
                        **row,
                        "key": f"ordinary:{row.get('bin')}:{row.get('lower')}:{row.get('upper')}",
                        "valid_share": row.get("share"),
                        "event_count": None,
                        "non_event_count": None,
                        "event_rate": None,
                    }
                    for row in ordinary_distribution.get("histogram") or []
                ]
                result.update(
                    {
                        "engine": "governed_eda_analytical_contract",
                        "iv": artifact["iv"],
                        "iv_by_bin": artifact["iv_woe"]["bins"],
                        "requested_bins": artifact["iv_woe"]["requested_bins"],
                        "returned_bins": artifact["iv_woe"][
                            "effective_nonempty_bins"
                        ],
                        "effective_bins": artifact["iv_woe"][
                            "effective_nonempty_bins"
                        ],
                        "binning_specification": artifact["iv_woe"],
                        "special_value_groups": artifact["special_values"][
                            "groups"
                        ],
                        "histogram": ordinary_histogram,
                        "bins": ordinary_histogram,
                        "ordinary_distribution": ordinary_distribution,
                        "ordinary_outlier": artifact["ordinary_outlier"],
                        "predictor_artifact_id": artifact["artifact_id"],
                        "target_directed_scope": "development_population",
                    }
                )
                selected_subset = result.get("selected_subset") or {}
                full_frame = DATASTORE.get_active_df()
                if isinstance(full_frame, pd.DataFrame) and feature in full_frame.columns:
                    full_numeric = pd.to_numeric(
                        full_frame[feature], errors="coerce"
                    ).replace([np.inf, -np.inf], np.nan)
                    full_codes = {
                        float(group["code"])
                        for group in (
                            artifact.get("special_values") or {}
                        ).get("full_population_groups")
                        or []
                    }
                    ordinary_mask = full_numeric.notna() & ~full_numeric.isin(full_codes)
                    ordinary_values = full_numeric[ordinary_mask]
                    lower = selected_subset.get("minimum")
                    upper = selected_subset.get("maximum")
                    selection_mask = ordinary_mask
                    if lower is not None:
                        selection_mask &= full_numeric.ge(float(lower))
                    if upper is not None:
                        selection_mask &= full_numeric.le(float(upper))
                    selected_values = full_numeric[selection_mask]
                    development_row_count = int(
                        selected_subset.get("row_count") or 0
                    )
                    development_event_count = selected_subset.get("event_count")
                    development_target_rate = selected_subset.get("target_rate")
                    quantiles = (
                        selected_values.quantile([0.25, 0.5, 0.75])
                        if len(selected_values)
                        else pd.Series(dtype=float)
                    )
                    selected_subset.update(
                        {
                            "row_count": int(len(selected_values)),
                            "population_share": len(selected_values)
                            / max(contract["population_rows"], 1),
                            "valid_share": len(selected_values)
                            / max(len(ordinary_values), 1),
                            "mean": _finite(selected_values.mean()),
                            "median": _finite(selected_values.median()),
                            "standard_deviation": _finite(selected_values.std()),
                            "q1": _finite(quantiles.loc[0.25])
                            if len(selected_values)
                            else None,
                            "q3": _finite(quantiles.loc[0.75])
                            if len(selected_values)
                            else None,
                            "minimum_value": _finite(selected_values.min()),
                            "maximum_value": _finite(selected_values.max()),
                            "development_row_count": development_row_count,
                            "development_event_count": development_event_count,
                            "target_rate": development_target_rate,
                            "target_rate_scope": "development_population",
                            "descriptive_scope": "full_governed_population",
                            "lower_percentile": float(
                                (ordinary_values < float(lower)).mean()
                            )
                            if len(ordinary_values) and lower is not None
                            else None,
                            "upper_percentile": float(
                                (ordinary_values <= float(upper)).mean()
                            )
                            if len(ordinary_values) and upper is not None
                            else None,
                        }
                    )
                    result["selected_subset"] = selected_subset
                    result["selected_range"] = selected_subset
                statistics = result.setdefault("statistics", {})
                full_counts = (
                    artifact.get("value_classification") or {}
                ).get("full_population_counts") or {}
                missing_bucket = result.setdefault("missing_bucket", {})
                development_missing_count = int(
                    missing_bucket.get("count") or 0
                )
                development_missing_events = missing_bucket.get("event_count")
                development_missing_rate = missing_bucket.get("event_rate")
                structural_missing = int(full_counts.get("true_null") or 0) + int(
                    full_counts.get("parse_failure") or 0
                )
                missing_bucket.update(
                    {
                        "count": structural_missing,
                        "share": structural_missing
                        / max(contract["population_rows"], 1),
                        "development_count": development_missing_count,
                        "development_event_count": development_missing_events,
                        "event_rate": development_missing_rate,
                        "event_rate_scope": "development_population",
                        "descriptive_scope": "full_governed_population",
                    }
                )
                statistics.update(
                    {
                        "count": int(full_counts.get("ordinary_valid_value") or 0),
                        "missing_count": int(full_counts.get("true_null") or 0),
                        "parse_failure_count": int(full_counts.get("parse_failure") or 0),
                        "bureau_special_value_count": int(full_counts.get("bureau_special_value") or 0),
                        "outlier_lower": artifact["ordinary_outlier"]["lower_cutoff"],
                        "outlier_upper": artifact["ordinary_outlier"]["upper_cutoff"],
                        "outlier_count": artifact["ordinary_outlier"]["count"],
                        "ordinary_outlier_rate": artifact["ordinary_outlier"]["rate"],
                    }
                )

    def _cached(self, section: str, request: EDAWorkspaceRequest, factory: Callable[..., dict[str, Any]]) -> dict[str, Any]:
        df, target, y, problem, event, authorization = self._dataset(request)
        source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta.get("source"), dict) else {}
        fingerprint = self._fingerprint(df, target, source)
        # Resolve and validate the exact governed development contract before
        # any section factory runs.  Legacy factories contain target-directed
        # calculations; feeding them the full frame would let the sealed final
        # holdout influence a result even when the harmonizer later replaced
        # the serialized field. Only the descriptive Overview factory retains
        # the full governed population; decision-facing Findings are generated
        # from development so holdout-only changes cannot alter recommendations.
        contract = self._governed_contract(
            request=request,
            df=df,
            target=target,
            event=event,
            authorization=authorization,
        )
        key = self._key(section, request, df, target, authorization, fingerprint)
        if key in self._cache:
            cached = self._cache.pop(key)
            self._cache[key] = cached
            return {**cached, "cache_status": "hit"}
        started = time.perf_counter()
        if section == "overview":
            factory_df = df
            factory_y = y
        else:
            development, development_target, _development_scope = resolve_development_partition(
                store=DATASTORE.current(),
                identity={
                    "project_id": contract["project_id"],
                    "dataset_id": contract["dataset_id"],
                    "dataset_version_id": contract["dataset_version_id"],
                },
                target=target,
                authorized_predictors=authorization["authorized_predictors"],
                predictor_manifest_id=contract["predictor_manifest_id"],
            )
            factory_df = development.copy(deep=True)
            factory_df[target] = development_target
            factory_y = development_target
        result = factory(factory_df, target, factory_y, problem, event, request)
        if section == "target":
            # Full-population class prevalence and target-only quality are
            # descriptive and may remain available. Predictor, segment, and
            # time comparisons above were calculated on development only.
            full_profile = (
                self._classification_target(y, event)
                if problem == "classification"
                else self._regression_target(y, request.histogram_bins)
            )
            development_quality = dict(result.get("target_quality") or {})
            full_quality = self._target_quality(
                df,
                target,
                y,
                problem,
                event,
                full_profile,
                include_leakage=False,
            )
            for key in (
                "target_derived_candidates",
                "post_outcome_candidates",
                "perfect_relationship_candidates",
            ):
                full_quality[key] = development_quality.get(key, [])
            full_quality.update(
                {
                    "structural_scope": "full_governed_population",
                    "target_directed_scope": "development_population",
                    "target_directed_rows": contract["rows_used"],
                    "split_id": contract["split_id"],
                    "final_holdout_accessed": False,
                }
            )
            result.update(
                {
                    "profile": full_profile,
                    "identity": self._target_identity(
                        df, target, y, problem, event, full_profile
                    ),
                    "full_population_assessment": self._full_population_assessment(
                        target, problem, full_profile
                    ),
                    "target_quality": full_quality,
                    "target_directed_scope": "development_population",
                }
            )
        self._harmonize_with_governed_contract(
            section=section,
            result=result,
            contract=contract,
            request=request,
        )
        scope = self._workspace_scope(
            df,
            target,
            request.project_id,
            f"eda.workspace.{section}",
            fingerprint,
        )
        decision_scope = {
            "contractVersion": contract["contract_version"],
            "mode": "governed_version",
            "label": "Development Population",
            "projectId": contract["project_id"],
            "datasetId": contract["dataset_id"],
            "datasetVersionId": contract["dataset_version_id"],
            "target": contract["target"],
            "populationRows": contract["rows_used"],
            "fullGovernedPopulationRows": contract["population_rows"],
            "rowsExcluded": contract["rows_excluded"],
            "exclusionReasons": contract["exclusion_reasons"],
            "analysisPopulationId": contract["analysis_population_id"],
            "splitId": contract["split_id"],
            "exact": True,
            "sampled": False,
            "immutableVersion": True,
            "evidenceEligible": True,
            "mddEligible": True,
            "decisionReady": True,
            "analysisSource": f"eda.governed_analytical_contract.{section}",
            "artifactId": contract["artifact_id"],
            "artifactHash": contract["artifact_hash"],
            "finalHoldoutAccessed": False,
            "finalHoldoutUsedForSelection": False,
        }
        result.update({
            "ok": True,
            "section": section,
            "scope": "development_population",
            "descriptive_scope": "full_governed_population",
            # `analysis_scope` is the authoritative decision scope. Preserve
            # the old in-memory workspace descriptor only under an explicitly
            # compatibility-labeled field so it cannot contradict governance.
            "analysis_scope": decision_scope,
            "workspace_compatibility_scope": scope,
            "scope_identity": f"governed-eda:{contract['artifact_hash']}",
            "row_count": int(len(df)),
            "column_count": int(df.shape[1]),
            "project_id": request.project_id,
            "target": target,
            "problem_type": problem,
            "event_value": _json_value(event),
            "dataset_id": DATASTORE.meta.get("dataset_id"),
            "dataset_version_id": DATASTORE.meta.get("dataset_version_id"),
            "dataset_version": str(DATASTORE.meta.get("dataset_version_id") or "unresolved"),
            "generated_at": _now(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "cache_status": "miss",
            "requested_histogram_bins": int(request.histogram_bins),
            "predictor_authorization": authorization,
            "target_source_fields": authorization["target_source_fields"],
            "target_source_excluded": authorization["target_source_excluded"],
            "rejected_requested_features": [
                feature
                for feature in request.selected_features
                if feature not in authorization["authorized_predictors"]
            ],
        })
        self._cache[key] = result
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)
        return result

    def section(self, section: str, request: EDAWorkspaceRequest) -> dict[str, Any]:
        factories: dict[str, Callable[..., dict[str, Any]]] = {
            "overview": self._overview,
            "target": self._target,
            "predictors": self._predictors,
            "distribution": self._distribution,
            "relationships": self._relationships,
            "stability": self._stability,
            "findings": self._findings,
        }
        if section not in factories:
            raise ValueError(f"Unsupported EDA section '{section}'.")
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return self._cached(section, request, factories[section])

    def authorized_dataset(
        self,
        request: EDAWorkspaceRequest,
    ) -> tuple[pd.DataFrame, str, pd.Series, str, Any, dict[str, Any]]:
        """Resolve the server-governed EDA frame for legacy read endpoints."""

        return self._dataset(request)

    def _overview(self, df, target, y, problem, event, request) -> dict[str, Any]:
        duplicate_rows = int(df.duplicated().sum())
        feature_columns = [column for column in df.columns if column != target]
        numeric_columns: list[str] = []
        categorical_columns: list[str] = []
        constants: list[str] = []
        identifier_candidates: list[dict[str, Any]] = []
        leakage_candidates: list[dict[str, Any]] = []
        invalid_numeric: list[dict[str, Any]] = []
        for column in feature_columns:
            series = df[column]
            numeric, is_numeric = _numeric_series(series)
            (numeric_columns if is_numeric else categorical_columns).append(str(column))
            distinct = int(series.nunique(dropna=True))
            if distinct <= 1:
                constants.append(str(column))
            uniqueness = distinct / max(int(series.notna().sum()), 1)
            if _ID_NAME.search(str(column)) or (uniqueness >= 0.98 and distinct > 20):
                identifier_candidates.append({"feature": str(column), "distinct_count": distinct, "uniqueness": uniqueness})
            if _LEAKAGE_NAME.search(str(column)) or _SPLIT_NAME.search(str(column)):
                leakage_candidates.append({"feature": str(column), "reason": "Name indicates a target, post-outcome, or split relationship."})
            if not is_numeric and numeric.notna().any():
                failures = int(series.notna().sum() - numeric.notna().sum())
                if failures:
                    invalid_numeric.append({"feature": str(column), "unparsed_count": failures})
        missing_cells = int(df.isna().sum().sum())
        target_payload = self._classification_target(y, event) if problem == "classification" else self._regression_target(y, request.histogram_bins)
        return {
            "headline": {
                "rows": int(len(df)),
                "predictors": len(feature_columns),
                "numeric_predictors": len(numeric_columns),
                "categorical_predictors": len(categorical_columns),
                "missing_cells": missing_cells,
                "missing_cell_rate": missing_cells / max(int(df.shape[0] * df.shape[1]), 1),
                "duplicate_rows": duplicate_rows,
            },
            "target_profile": target_payload,
            "data_integrity": {
                "duplicate_rows": duplicate_rows,
                "constant_columns": constants,
                "identifier_candidates": identifier_candidates[:50],
                "leakage_candidates": leakage_candidates[:50],
                "invalid_numeric_parsing": invalid_numeric[:50],
                "unsupported_types": [str(column) for column in df.columns if str(df[column].dtype) in {"complex64", "complex128"}],
            },
            "available_fields": {
                "numeric": numeric_columns,
                "categorical": categorical_columns,
                "date_candidates": [str(column) for column in df.columns if _DATE_NAME.search(str(column))],
                "segment_candidates": [str(column) for column in categorical_columns if 1 < df[column].nunique(dropna=True) <= 100],
            },
        }

    def _classification_target(self, y: pd.Series, event: Any) -> dict[str, Any]:
        valid = y.dropna()
        counts = valid.astype(str).value_counts()
        event_count = int((valid.astype(str) == str(event)).sum()) if event is not None else 0
        non_event_count = int(len(valid) - event_count)
        event_rate = event_count / len(valid) if len(valid) else None
        unexpected = [str(value) for value in pd.unique(valid) if event is not None and len(counts) <= 2 and str(value) not in {str(event), str(next((item for item in pd.unique(valid) if str(item) != str(event)), ""))}]
        min_events_for_five_fold = event_count >= 10 and non_event_count >= 10
        metrics = ["PR-AUC", "Recall", "Lift", "KS", "Calibration"] if event_rate is not None and event_rate < 0.05 else ["ROC-AUC", "PR-AUC", "F1", "Calibration"]
        return {
            "valid_count": int(len(valid)),
            "missing_count": int(y.isna().sum()),
            "class_count": int(valid.nunique()),
            "class_distribution": [{"value": str(index), "count": int(value), "rate": float(value / len(valid))} for index, value in counts.items()],
            "positive_class": _json_value(event),
            "negative_class": _json_value(next((value for value in pd.unique(valid) if str(value) != str(event)), None)),
            "event_count": event_count,
            "non_event_count": non_event_count,
            "event_rate": event_rate,
            "non_event_rate": 1 - event_rate if event_rate is not None else None,
            "event_to_non_event_ratio": event_count / non_event_count if non_event_count else None,
            "unexpected_values": unexpected,
            "rare_event": bool(event_rate is not None and event_rate < 0.01),
            "split_sufficiency": event_count >= 2 and non_event_count >= 2,
            "five_fold_sufficiency": min_events_for_five_fold,
            "recommended_metrics": metrics,
        }

    def _regression_target(self, y: pd.Series, histogram_bins: int = 20) -> dict[str, Any]:
        numeric = pd.to_numeric(y, errors="coerce")
        clean = numeric.dropna()
        quantiles = _series_quantiles(clean)
        q1, q3 = quantiles["q1"], quantiles["q3"]
        iqr = (q3 - q1) if q1 is not None and q3 is not None else None
        outlier_rate = float(((clean < q1 - 1.5 * iqr) | (clean > q3 + 1.5 * iqr)).mean()) if iqr is not None else None
        return {
            "valid_count": int(len(clean)),
            "missing_count": int(y.isna().sum() + (y.notna() & numeric.isna()).sum()),
            "mean": _finite(clean.mean()),
            "standard_deviation": _finite(clean.std()),
            "minimum": _finite(clean.min()),
            **quantiles,
            "maximum": _finite(clean.max()),
            "skewness": _finite(clean.skew()),
            "kurtosis": _finite(clean.kurt()),
            "zero_proportion": float((clean == 0).mean()) if len(clean) else None,
            "negative_proportion": float((clean < 0).mean()) if len(clean) else None,
            "extreme_value_prevalence": outlier_rate,
            "histogram": _histogram_bins(clean, bins=histogram_bins),
        }

    def _target(self, df, target, y, problem, event, request) -> dict[str, Any]:
        profile = self._classification_target(y, event) if problem == "classification" else self._regression_target(y, request.histogram_bins)

        # Part H: a time field is only offered when it is genuinely a time field.
        # `request.date_field` being present in the frame is not sufficient --
        # the governed rule must also accept it, so a numeric "Time" column
        # holding elapsed seconds can never be charted as a calendar axis.
        governed_time_fields = self._governed_time_fields(df)
        governed_time_names = {item["field"] for item in governed_time_fields}
        requested_date = request.date_field if request.date_field in df.columns else None
        date_field = requested_date if requested_date in governed_time_names else None
        rejected_date_field = (
            {"field": requested_date, "reason": "This field is not a governed time field. ATLAS does not infer dates from numeric or non-date-formatted values."}
            if requested_date and requested_date not in governed_time_names
            else None
        )

        segment_field = request.segment_field if request.segment_field in df.columns else None
        segment_rows = self._group_target(df, target, event, segment_field, False) if segment_field else []
        if segment_rows:
            population_rate = profile.get("event_rate") if problem == "classification" else None
            for row in segment_rows:
                row["population_event_rate"] = population_rate
                row["difference_from_population"] = (
                    row["event_rate"] - population_rate if population_rate is not None else None
                )
                row["small_segment"] = row["count"] < 30 or row["events"] < 5
            missing_row = next((row for row in segment_rows if row["group"] == "__MISSING__"), None)
            segment_missing_count = missing_row["count"] if missing_row else 0
        else:
            segment_missing_count = 0

        time_rows = (
            self._group_target(df, target, event, date_field, True)
            if problem == "classification" and date_field
            else []
        )
        return {
            "profile": profile,
            "identity": self._target_identity(df, target, y, problem, event, profile),
            "full_population_assessment": self._full_population_assessment(target, problem, profile),
            "target_quality": self._target_quality(df, target, y, problem, event, profile),
            "predictor_preview": (
                self._target_predictor_preview(
                    df,
                    target,
                    y,
                    event,
                    predictor_limit=5,
                    shape_limit=request.predictor_visual_shape_limit,
                )
                if problem == "classification"
                else None
            ),
            "governed_time_fields": governed_time_fields,
            "rejected_time_field": rejected_date_field,
            "event_rate_by_time": time_rows,
            "time_stability": self._time_stability(time_rows, df, date_field),
            "target_by_segment": segment_rows,
            "segment_missing_count": segment_missing_count,
            "date_field": date_field,
            "segment_field": segment_field,
        }

    def _target_predictor_preview(
        self,
        df: pd.DataFrame,
        target: str,
        y: pd.Series,
        event: Any,
        *,
        predictor_limit: int = 5,
        shape_limit: int = 8,
    ) -> dict[str, Any]:
        """One bounded, full-population preview for initial Target entry.

        The Target page used to rely on ``predictorOptions.iv``, but those IV
        values exist only after the separate Predictors tab has been opened.
        That made the preview empty on the first Target visit. This aggregate is
        computed as part of the already-batched Target workspace response. It
        evaluates only the server-authorized frame produced by ``_dataset``;
        consequently the target and deterministic sources such as
        ``RiskPerformance`` cannot enter the result.
        """
        bounded_predictor_limit = min(max(1, int(predictor_limit)), 5)
        bounded_shape_limit = min(max(3, int(shape_limit)), 10)
        ranked: list[dict[str, Any]] = []

        for column in df.columns:
            feature = str(column)
            if feature == str(target):
                continue
            series = df[column]
            try:
                iv, _ = information_value(series, y, event)
            except (TypeError, ValueError):
                iv = None
            if iv is None or not np.isfinite(float(iv)):
                continue

            numeric, is_numeric = _numeric_series(series)
            if is_numeric:
                source_groups = _quantile_event_table(
                    numeric,
                    y,
                    event,
                    bins=bounded_shape_limit,
                )
                groups = [
                    {
                        "label": f"Q{index + 1}",
                        "count": int(row.get("count") or 0),
                        "event_count": int(row.get("events") or 0),
                        "event_rate": _finite(row.get("event_rate")),
                    }
                    for index, row in enumerate(source_groups)
                ]
                monotonicity = _monotonicity(source_groups) if source_groups else "Not available"
                kind = "numeric"
            else:
                values = (
                    series.astype("object")
                    .where(series.notna(), "__MISSING__")
                    .astype(str)
                )
                frame = pd.DataFrame({"value": values, "target": y}).dropna(
                    subset=["target"]
                )
                frame["event"] = frame["target"].astype(str) == str(event)
                grouped = (
                    frame.groupby("value", dropna=False)["event"]
                    .agg(["size", "sum"])
                    .sort_values("size", ascending=False)
                    .head(bounded_shape_limit)
                )
                groups = [
                    {
                        "label": str(index),
                        "count": int(row["size"]),
                        "event_count": int(row["sum"]),
                        "event_rate": (
                            float(row["sum"] / row["size"])
                            if row["size"]
                            else None
                        ),
                    }
                    for index, row in grouped.iterrows()
                ]
                monotonicity = "Not ordered (categorical)"
                kind = "categorical"

            rates = [
                float(row["event_rate"])
                for row in groups
                if row.get("event_rate") is not None
            ]
            ranked.append(
                {
                    "feature": feature,
                    "kind": kind,
                    "iv": _finite(iv),
                    "monotonicity": monotonicity,
                    "event_rate_spread": (
                        max(rates) - min(rates) if len(rates) >= 2 else None
                    ),
                    "groups": groups,
                }
            )

        ranked.sort(
            key=lambda row: abs(float(row.get("iv") or 0)),
            reverse=True,
        )
        preview = ranked[:bounded_predictor_limit]
        return {
            "scope": "full_dataset_aggregates",
            "population_rows": int(len(df)),
            "predictor_limit": bounded_predictor_limit,
            "shape_limit": bounded_shape_limit,
            "candidate_count": len(ranked),
            "returned_predictors": len(preview),
            "request_mode": "single_batched_target_workspace_request",
            "server_authorized_predictors_only": True,
            "target_excluded": True,
            "raw_observations_included": False,
            "predictors": preview,
        }

    def target_by_predictor(self, request: TargetByPredictorRequest) -> dict[str, Any]:
        """On-demand grouped event rate over the exact development population.

        The durable split must be current and identity-matched. Only grouped
        counts leave the server; final-holdout frames are never read.
        """
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return self._target_by_predictor_locked(request)

    def _target_by_predictor_locked(
        self,
        request: TargetByPredictorRequest,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        base = EDAWorkspaceRequest(
            project_id=request.project_id, target=request.target,
            event_value=request.event_value, problem_type=request.problem_type,
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
            dataset_version=request.dataset_version,
        )
        df, target, y, problem, event, _authorization = self._dataset(base)

        predictor = request.predictor
        if predictor not in df.columns:
            raise ValueError(f"'{predictor}' is not a column in the loaded dataset.")
        if predictor == target:
            raise ValueError("The target cannot be analyzed against itself.")
        if problem != "classification" or event is None:
            raise ValueError("Target-by-predictor event rates apply to classification targets with a resolved event value.")
        if request.analysis_type not in {"numeric_quantile", "categorical"}:
            raise ValueError("Unsupported analysis type. Use 'numeric_quantile' or 'categorical'.")

        contract = self._governed_contract(
            request=base,
            df=df,
            target=target,
            event=event,
            authorization=_authorization,
        )
        artifact = contract["predictor_artifacts"].get(predictor)
        if not artifact:
            raise EDAAnalyticalContractError(
                f"No current governed predictor artifact exists for '{predictor}'."
            )
        scoped_store = DATASTORE.current()
        development_features = scoped_store.X_train
        development_target = scoped_store.y_train
        # `_governed_contract` has already validated exact identity, split,
        # feature manifest, row count, and index alignment. Read only the two
        # development objects here for the bounded display groups.
        if not isinstance(development_features, pd.DataFrame) or not isinstance(development_target, pd.Series):
            raise EDAAnalyticalContractError("The governed development partition is unavailable.")
        frame = pd.DataFrame(
            {
                "value": development_features[predictor],
                "event": development_target.astype(str).eq(str(event)).astype(int),
            }
        )
        frame = frame[development_target.notna()]
        analyzed_rows = int(len(frame))

        rows: list[dict[str, Any]] = []
        missing_group: dict[str, Any] | None = None
        other_group: dict[str, Any] | None = None
        extras: dict[str, Any] = {}

        def _entry(label_key: str, label: str, subset: pd.DataFrame, **fields: Any) -> dict[str, Any]:
            population = int(len(subset))
            events = int(subset["event"].sum())
            return {
                label_key: label,
                "population": population,
                "eventCount": events,
                "eventRate": (events / population) if population else None,
                "smallGroup": population < SMALL_GROUP_MIN_ROWS or events < SMALL_GROUP_MIN_EVENTS,
                **fields,
            }

        if request.analysis_type == "numeric_quantile":
            iv_bins = (artifact.get("iv_woe") or {}).get("bins") or []
            ordinary_bins = [
                row for row in iv_bins
                if row.get("bin_type") == "ordinary_valid_range"
            ]
            numeric = pd.to_numeric(frame["value"], errors="coerce")
            special_codes = {
                str(group.get("code"))
                for group in (artifact.get("special_values") or {}).get("development_groups") or []
            }
            special_mask = numeric.map(lambda value: str(int(value)) if pd.notna(value) and float(value).is_integer() else str(value)).isin(special_codes)
            present = frame[numeric.notna() & ~special_mask].assign(
                numeric=numeric[numeric.notna() & ~special_mask]
            )
            absent = frame[numeric.isna()]
            if present.empty:
                raise ValueError(f"'{predictor}' has no numeric values to band.")
            bands = max(2, min(int(request.bands), 20))
            for row in ordinary_bins:
                rows.append(
                    {
                        "label": row["label"],
                        "population": int(row["count"]),
                        "eventCount": int(row["event_count"]),
                        "eventRate": row["event_rate"],
                        "smallGroup": int(row["count"]) < SMALL_GROUP_MIN_ROWS or int(row["event_count"]) < SMALL_GROUP_MIN_EVENTS,
                        "band": int(row["bin_index"]),
                        "lowerBound": row["lower"],
                        "upperBound": row["upper"],
                        "meanValue": None,
                        "isMissingGroup": False,
                        "isBureauSpecialGroup": False,
                        "governedBinLabel": True,
                    }
                )
            for group in (artifact.get("special_values") or {}).get("development_groups") or []:
                rows.append(
                    {
                        "label": f"{group['code']}: {group['definition']}",
                        "population": int(group["rows"]),
                        "eventCount": int(group["event_count"]),
                        "eventRate": group["event_rate"],
                        "smallGroup": int(group["rows"]) < SMALL_GROUP_MIN_ROWS or int(group["event_count"]) < SMALL_GROUP_MIN_EVENTS,
                        "band": 0,
                        "lowerBound": None,
                        "upperBound": None,
                        "meanValue": None,
                        "isMissingGroup": False,
                        "isBureauSpecialGroup": True,
                    }
                )
            if len(absent):
                missing_group = _entry("label", "Missing", absent, band=0, lowerBound=None, upperBound=None, meanValue=None, isMissingGroup=True)
            label_key = "label"
            box_plot_by_target: list[dict[str, Any]] = []
            for event_group, subset in present.groupby("event", sort=True):
                values = subset["numeric"].astype(float).dropna()
                if values.empty:
                    continue
                q1 = float(values.quantile(0.25))
                median = float(values.quantile(0.50))
                q3 = float(values.quantile(0.75))
                lower_fence = q1 - 1.5 * (q3 - q1)
                upper_fence = q3 + 1.5 * (q3 - q1)
                inliers = values[(values >= lower_fence) & (values <= upper_fence)]
                is_event_group = int(event_group) == 1
                box_plot_by_target.append({
                    "targetClass": "event" if is_event_group else "non_event",
                    "label": f"Event ({event})" if is_event_group else "Non-event",
                    "population": int(len(values)),
                    "minimum": _finite(values.min()),
                    "q1": _finite(q1),
                    "median": _finite(median),
                    "q3": _finite(q3),
                    "maximum": _finite(values.max()),
                    "whiskerLow": _finite(inliers.min()) if len(inliers) else _finite(values.min()),
                    "whiskerHigh": _finite(inliers.max()) if len(inliers) else _finite(values.max()),
                    "outlierCount": int(((values < lower_fence) | (values > upper_fence)).sum()),
                })
            extras = {
                "requestedBands": bands,
                "returnedBands": len(ordinary_bins),
                "effectiveBands": len(ordinary_bins),
                "collapsedBoundaryExplanation": (artifact.get("iv_woe") or {}).get("collapsed_boundary_explanation"),
                "boxPlotByTarget": box_plot_by_target,
            }
        else:
            values = frame["value"].astype("object")
            is_missing = values.isna()
            distinct = int(values[~is_missing].astype(str).nunique())
            top_n = max(2, min(int(request.top_categories), MAX_TOP_CATEGORIES))
            present = frame[~is_missing].assign(category=values[~is_missing].astype(str))
            ordered = present["category"].value_counts()
            keep = list(ordered.head(top_n).index)
            for category in keep:
                rows.append(_entry("category", str(category), present[present["category"] == category], isMissingGroup=False, isOtherGroup=False))
            collapsed = present[~present["category"].isin(keep)]
            if len(collapsed):
                other_group = _entry(
                    "category", "Other", collapsed,
                    isMissingGroup=False, isOtherGroup=True,
                    collapsedCategoryCount=int(collapsed["category"].nunique()),
                )
            if int(is_missing.sum()):
                missing_group = _entry("category", "Missing", frame[is_missing], isMissingGroup=True, isOtherGroup=False)
            label_key = "category"
            extras = {
                "requestedTopCategories": top_n,
                "returnedCategories": len(rows),
                "distinctCategoryCount": distinct,
                "topNApplied": bool(other_group),
                "rareCategoryWarning": bool(distinct > top_n or any(row["smallGroup"] for row in rows)),
            }

        if not request.include_missing:
            missing_group = None

        total_population = sum(row["population"] for row in rows) + sum(
            int(extra["population"]) for extra in (missing_group, other_group) if extra
        )
        total_events = sum(row["eventCount"] for row in rows) + sum(
            int(extra["eventCount"]) for extra in (missing_group, other_group) if extra
        )
        population_event_rate = (total_events / total_population) if total_population else None

        scope = {
            "contractVersion": contract["contract_version"],
            "mode": "governed_version",
            "label": "Development Population",
            "projectId": contract["project_id"],
            "datasetId": contract["dataset_id"],
            "datasetVersionId": contract["dataset_version_id"],
            "target": contract["target"],
            "populationRows": contract["rows_used"],
            "analysisPopulationId": contract["analysis_population_id"],
            "splitId": contract["split_id"],
            "exact": True,
            "sampled": False,
            "immutableVersion": True,
            "evidenceEligible": True,
            "mddEligible": True,
            "analysisSource": "eda.governed_analytical_contract.target_by_predictor",
            "finalHoldoutAccessed": False,
        }
        return {
            "ok": True,
            "supported": bool(rows),
            "source": "eda_exact_development_population",
            "analysisScope": scope,
            "scopeIdentity": scope_identity(scope),
            "project_id": request.project_id,
            "dataset_id": DATASTORE.meta.get("dataset_id"),
            "dataset_version_id": DATASTORE.meta.get("dataset_version_id"),
            "dataset_version": DATASTORE.meta.get("dataset_version_id"),
            "datasetId": DATASTORE.meta.get("dataset_id"),
            "versionId": DATASTORE.meta.get("dataset_version_id"),
            "target": str(target),
            "predictor": str(predictor),
            "analysisType": request.analysis_type,
            "eventValue": str(event),
            "includeMissing": bool(request.include_missing),
            "rows": rows,
            "missingGroup": missing_group,
            "otherGroup": other_group,
            "populationEventRate": population_event_rate,
            "analyzedRowCount": total_population,
            "analyzedEventCount": total_events,
            "summary": summarize_target_by_predictor(
                rows, label_key=label_key, missing_group=missing_group, other_group=other_group,
                population_event_rate=population_event_rate, analysis_type=request.analysis_type,
            ),
            "engine": "governed_eda_analytical_contract",
            "resolution": "exact",
            "scope": "development_population",
            "sourceRowCount": analyzed_rows,
            "artifactId": artifact["artifact_id"],
            "artifactHash": artifact["artifact_hash"],
            "ivArtifactId": artifact["iv_artifact_id"],
            "monotonicityArtifactId": artifact["monotonicity_artifact_id"],
            "governed_analytical_contract": contract,
            "finalHoldoutAccessed": False,
            "finalHoldoutUsedForSelection": False,
            "cached": False,
            "durationMs": int((time.perf_counter() - started) * 1000),
            **extras,
        }

    def vif_simulation(self, request: EDAVifSimulationRequest) -> dict[str, Any]:
        """Recompute VIF after a temporary exclusion without mutating DATASTORE."""

        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return self._vif_simulation_locked(request)

    def _vif_simulation_locked(
        self,
        request: EDAVifSimulationRequest,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        base = EDAWorkspaceRequest(
            project_id=request.project_id,
            target=request.target,
            event_value=request.event_value,
            problem_type=request.problem_type,
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
            dataset_version=request.dataset_version,
        )
        df, target, _y, _problem, event, authorization = self._dataset(base)
        contract = self._governed_contract(
            request=base,
            df=df,
            target=target,
            event=event,
            authorization=authorization,
        )
        excluded = str(request.excluded_feature or "").strip()
        if excluded == target or excluded not in authorization["authorized_predictors"] or excluded not in df.columns:
            raise ValueError(f"Predictor '{excluded}' is not authorized for a VIF scenario.")

        development, _development_target, _scope = resolve_development_partition(
            store=DATASTORE.current(),
            identity={
                "project_id": contract["project_id"],
                "dataset_id": contract["dataset_id"],
                "dataset_version_id": contract["dataset_version_id"],
            },
            target=target,
            authorized_predictors=authorization["authorized_predictors"],
            predictor_manifest_id=contract["predictor_manifest_id"],
        )
        numeric_df = self._governed_ordinary_numeric_frame(
            development,
            contract,
            authorization["authorized_predictors"],
        )
        vif_frame, vif_scope = self._prepare_vif_frame(
            numeric_df,
            required_feature=excluded,
        )
        if excluded not in vif_frame.columns:
            raise ValueError(
                f"Predictor '{excluded}' is not eligible for the bounded VIF scenario."
            )
        before = self._vif(vif_frame)
        after = self._vif(vif_frame.drop(columns=[excluded], errors="ignore"))
        before_by_feature = {row["feature"]: row for row in before}
        rows = [
            {
                **row,
                "before_vif": before_by_feature.get(row["feature"], {}).get("vif"),
                "delta": (
                    _finite(float(row["vif"]) - float(before_by_feature[row["feature"]]["vif"]))
                    if row.get("vif") is not None
                    and before_by_feature.get(row["feature"], {}).get("vif") is not None
                    else None
                ),
            }
            for row in after
        ]

        def _largest(source: list[dict[str, Any]]) -> float | None:
            finite_values = [float(row["vif"]) for row in source if row.get("vif") is not None]
            return max(finite_values) if finite_values else None

        return {
            "ok": True,
            "project_id": request.project_id,
            "dataset_id": DATASTORE.meta.get("dataset_id"),
            "dataset_version_id": DATASTORE.meta.get("dataset_version_id"),
            "dataset_version": DATASTORE.meta.get("dataset_version_id"),
            "non_mutating": True,
            "excluded_feature": excluded,
            "before": before,
            "after": rows,
            "summary": {
                "before_max_vif": _finite(_largest(before)),
                "after_max_vif": _finite(_largest(after)),
                "remaining_predictors": len(after),
            },
            "predictor_authorization": authorization,
            "scope": "development_population",
            "vif_scope": vif_scope,
            "governed_relationship_artifact_id": contract[
                "relationship_artifact"
            ]["artifact_id"],
            "current_vif_artifact_basis": "governed_development_ordinary_numeric_complete_case",
            "final_holdout_accessed": False,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }

    def vif_resolution_plan(
        self,
        request: EDAVifResolutionPlanRequest,
    ) -> dict[str, Any]:
        """Generate and persist a non-mutating, development-only VIF plan."""

        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return self._vif_resolution_plan_locked(request)

    def _vif_resolution_plan_locked(
        self,
        request: EDAVifResolutionPlanRequest,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        scoped_store = DATASTORE.current()
        base = EDAWorkspaceRequest(
            project_id=request.project_id,
            target=request.target,
            event_value=request.event_value,
            problem_type=request.problem_type,
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
            dataset_version=request.dataset_version,
        )
        df, target, _y, problem, event, authorization = self._dataset(base)
        identity = assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
            legacy_dataset_version=request.dataset_version,
            require_expected=True,
        )
        authorized = [
            str(feature)
            for feature in authorization.get("authorized_predictors", [])
            if str(feature) in df.columns
        ]
        protected = sorted(set(request.protected_predictors))
        unauthorized_protected = [feature for feature in protected if feature not in authorized]
        if unauthorized_protected:
            raise ValueError(
                "Protected predictors must belong to the exact authorized predictor set: "
                + ", ".join(unauthorized_protected)
            )
        allowed_actions = list(dict.fromkeys(request.allowed_actions))
        if not allowed_actions:
            raise ValueError("Select at least one permitted VIF resolution action.")

        # A Dataset Library frame does not acquire authoritative partition
        # semantics merely because it contains a column named ``atlas_split``.
        # Balance & Split owns the exact development partition in X_train /
        # y_train and binds it to an exact-identity split_record.  Reading the
        # active full frame here previously let all 6,275 HELOC rows influence
        # a plan even though 1,255 of them were already sealed as final holdout.
        development, development_target, resolved_scope = resolve_development_partition(
            store=scoped_store,
            identity={
                "project_id": identity["project_id"],
                "dataset_id": identity["dataset_id"],
                "dataset_version_id": identity["dataset_version_id"],
            },
            target=target,
            authorized_predictors=authorized,
            predictor_manifest_id=str(authorization.get("manifest_version") or ""),
        )
        analysis_df = development.copy(deep=True)
        analysis_df[target] = development_target
        development_scope = "exact_materialized_development_partition_only"
        target_informed_evidence = "exact_development_partition_only"
        split_field = "governed_split_record"
        split_id = resolved_scope["split_id"]
        final_holdout_rows_excluded = int(resolved_scope["rows_excluded"])
        exact_development_partition = True

        contract = self._governed_contract(
            request=base,
            df=df,
            target=target,
            event=event,
            authorization=authorization,
        )

        numeric_df = self._governed_ordinary_numeric_frame(
            development,
            contract,
            authorized,
        )
        vif_frame, vif_scope = self._prepare_vif_frame(numeric_df)
        if vif_frame.shape[1] < 2:
            raise ValueError("At least two authorized numeric predictors are required for a VIF resolution plan.")

        target_series = analysis_df[target]
        profiles: dict[str, dict[str, Any]] = {}
        event_indicator = (
            target_series.astype(str).eq(str(event)).astype(float)
            if problem == "classification" and event is not None
            else pd.to_numeric(target_series, errors="coerce")
        )
        for feature in vif_frame.columns:
            artifact = contract["predictor_artifacts"][str(feature)]
            counts = (
                (artifact.get("value_classification") or {}).get(
                    "development_counts"
                )
                or {}
            )
            ordinary = numeric_df[str(feature)]
            signal = (
                ordinary.corr(event_indicator)
                if exact_development_partition
                else None
            )
            population = max(len(development), 1)
            missingness = int(counts.get("true_null") or 0) / population
            parse_failure = int(counts.get("parse_failure") or 0) / population
            special_burden = (
                int(counts.get("bureau_special_value") or 0) / population
            )
            profiles[str(feature)] = {
                "development_signal": abs(float(signal)) if pd.notna(signal) else None,
                "signal_metric": (
                    "absolute_point_biserial_correlation"
                    if problem == "classification"
                    else "absolute_development_correlation"
                )
                if exact_development_partition
                else "disabled_without_exact_development_partition",
                "signal_scope": development_scope,
                "missingness": missingness,
                "parse_failure_burden": parse_failure,
                "special_value_burden": special_burden,
                "predictor_artifact_id": artifact["artifact_id"],
                "special_value_policy_id": contract["special_value_policy_id"],
                "interpretability": 1.0,
                "production_availability": 1.0,
                "data_quality": max(
                    0.0,
                    1.0 - missingness - parse_failure - special_burden,
                ),
            }

        analysis = build_vif_resolution_plan(
            frame=vif_frame,
            vif_calculator=self._vif,
            profiles=profiles,
            model_family=request.intended_model_family,
            target_threshold=float(request.target_vif_threshold),
            objective=request.resolution_objective,
            protected_predictors=protected,
            allowed_actions=allowed_actions,
            correlation_threshold=float(request.correlation_threshold),
            preference_weights=request.preference_weights.model_dump(),
            maximum_removals=int(request.maximum_removals),
        )
        analysis["analysis_scope"].update(
            {
                "target_informed_evidence": target_informed_evidence,
                "development_population": development_scope,
                "development_rows": int(len(analysis_df)),
                "sealed_final_holdout_rows_excluded": final_holdout_rows_excluded,
                "split_field_used": split_field,
                "split_id": split_id or None,
                "exact_development_partition_resolved": exact_development_partition,
                "vif_scope": vif_scope,
                "governed_relationship_artifact_id": contract[
                    "relationship_artifact"
                ]["artifact_id"],
                "current_vif_artifact_basis": "governed_development_ordinary_numeric_complete_case",
            }
        )
        plan_basis = {
            "project_id": request.project_id,
            "dataset_id": identity["dataset_id"],
            "dataset_version_id": identity["dataset_version_id"],
            "inputs": request.model_dump(mode="json"),
            "current": analysis["current"],
            "proposed": analysis["proposed"],
        }
        digest = plan_hash(plan_basis)
        record = save_generated_plan(
            {
                "ok": True,
                "plan_id": f"vif-plan-{digest[:16]}",
                "plan_hash": digest,
                "project_id": request.project_id,
                "dataset_id": identity["dataset_id"],
                "dataset_version_id": identity["dataset_version_id"],
                "dataset_version": identity["dataset_version_id"],
                "target": target,
                "predictor_authorization": authorization,
                "inputs": request.model_dump(mode="json"),
                **analysis,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return record

    def vif_resolution_decision(
        self,
        request: EDAVifResolutionDecisionRequest,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        """Record plan governance without changing data or the feature manifest."""

        identity = assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
            legacy_dataset_version=request.dataset_version,
            require_expected=True,
        )
        plan = get_plan(
            request.project_id,
            identity["dataset_id"],
            identity["dataset_version_id"],
            request.plan_id,
        )
        if plan is None:
            raise ValueError("The exact VIF resolution plan was not found.")
        if request.action == "send_to_feature_engineering" and plan.get("status") not in {
            "accepted",
            "partially_accepted",
            "sent_to_feature_engineering",
        }:
            raise ValueError("Accept all or selected cluster recommendations before sending them to Feature Engineering.")
        cluster_ids = set(request.selected_cluster_ids)
        if request.action == "accept_selected" and not cluster_ids:
            raise ValueError("Select at least one cluster recommendation to accept.")
        known_clusters = {str(cluster.get("cluster_id")) for cluster in plan.get("clusters", [])}
        unknown = sorted(cluster_ids - known_clusters)
        if unknown:
            raise ValueError("Unknown VIF cluster selection: " + ", ".join(unknown))

        accepted = request.action in {
            "accept_complete",
            "accept_selected",
            "send_to_feature_engineering",
        }
        recommendations: list[dict[str, Any]] = []
        decision_cluster_ids = set(cluster_ids)
        if accepted:
            if request.action == "accept_complete":
                selected = known_clusters
            elif request.action == "accept_selected":
                selected = cluster_ids
            else:
                selected: set[str] = set()
                for disposition in plan.get("decision_history", []):
                    if disposition.get("action") == "accept_complete":
                        selected.update(known_clusters)
                    elif disposition.get("action") == "accept_selected":
                        selected.update(
                            str(value)
                            for value in disposition.get("selected_cluster_ids", [])
                            if str(value) in known_clusters
                        )
                if not selected:
                    raise ValueError(
                        "No accepted VIF cluster recommendations are available to send."
                    )
                decision_cluster_ids = set(selected)
            for cluster in plan.get("clusters", []):
                cluster_id = str(cluster.get("cluster_id"))
                if cluster_id not in selected:
                    continue
                tie = cluster.get("tie_case")
                action = str(cluster.get("recommended_action") or "defer")
                if tie:
                    action = "defer"
                recommendations.append(
                    {
                        "recommendation_id": f"{request.plan_id}:{cluster_id}",
                        "source_plan_id": request.plan_id,
                        "cluster_id": cluster_id,
                        "action": action,
                        "features": list(cluster.get("features") or []),
                        "proposed_exclusions": list(cluster.get("proposed_exclusions") or []),
                        "protected_features": list(cluster.get("protected_features") or []),
                        "tie_case": tie,
                        "rationale": str(cluster.get("rationale") or ""),
                        "status": "draft_recommendation",
                        "governed_feature_set_changed": False,
                        "dataset_mutated": False,
                    }
                )
        updated = record_plan_decision(
            project_id=request.project_id,
            dataset_id=identity["dataset_id"],
            dataset_version_id=identity["dataset_version_id"],
            plan_id=request.plan_id,
            action=request.action,
            selected_cluster_ids=list(decision_cluster_ids),
            rationale=request.rationale,
            modifications=request.modifications,
            recommendations=recommendations,
            actor_id=actor_id,
        )
        evidence = None
        if accepted:
            evidence = upsert_evidence(
                {
                    "lineage_contract": "canonical_dataset_version",
                    "project_id": request.project_id,
                    "dataset_id": identity["dataset_id"],
                    "dataset_version_id": identity["dataset_version_id"],
                    "projectId": request.project_id,
                    "datasetIds": [identity["dataset_id"]],
                    "evidenceType": "vif",
                    "title": "Governed VIF Resolution Plan",
                    "summary": (
                        f"VIF plan {request.plan_id} recorded {len(recommendations)} draft "
                        "Feature Engineering recommendation(s). No predictor or dataset was changed."
                    ),
                    "sourcePage": "Exploratory Data Analysis",
                    "sourceRoute": "/step02?tab=relationships",
                    "artifactType": "vif_resolution_plan",
                    "artifactId": request.plan_id,
                    "status": "ready",
                    "importance": "high",
                    "supportsSections": ["feature_engineering", "correlation_vif"],
                    "createdBy": actor_id,
                    "governance": {
                        "recommendations_only": True,
                        "governed_feature_set_changed": False,
                        "dataset_mutated": False,
                        "development_population_only": True,
                        "final_holdout_accessed": False,
                    },
                }
            )
        queue = get_feature_recommendations(
            request.project_id,
            identity["dataset_id"],
            identity["dataset_version_id"],
            request.plan_id,
        )
        return {
            "ok": True,
            "project_id": request.project_id,
            "dataset_id": identity["dataset_id"],
            "dataset_version_id": identity["dataset_version_id"],
            "dataset_version": identity["dataset_version_id"],
            "plan_id": request.plan_id,
            "status": updated.get("status"),
            "decision": updated.get("decision_history", [])[-1],
            "feature_recommendations": queue,
            "evidence": evidence,
            "governed_feature_set_changed": False,
            "dataset_mutated": False,
        }

    def vif_feature_recommendations(
        self,
        *,
        project_id: str,
        expected_dataset_id: str,
        expected_dataset_version_id: str,
    ) -> dict[str, Any]:
        identity = assert_expected_active_identity(
            project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
            require_expected=True,
        )
        records = list_feature_recommendations(
            project_id,
            identity["dataset_id"],
            identity["dataset_version_id"],
        )
        recommendations = [
            recommendation
            for record in records
            for recommendation in record.get("recommendations", [])
        ]
        return {
            "ok": True,
            "project_id": project_id,
            "dataset_id": identity["dataset_id"],
            "dataset_version_id": identity["dataset_version_id"],
            "dataset_version": identity["dataset_version_id"],
            "recommendation_contract": "draft_feature_engineering_recommendations",
            "records": records,
            "recommendations": recommendations,
            "count": len(recommendations),
            "governed_feature_set_changed": False,
            "dataset_mutated": False,
        }

    def relationship_sample(
        self,
        request: EDARelationshipSampleRequest,
    ) -> dict[str, Any]:
        """Return one bounded deterministic sample for 2D, density, and 3D.

        The response deliberately contains canonical plot dimensions and a
        derived target group only. Raw target values and browser-provided field
        names never bypass the server-authored predictor authorization.
        """

        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return self._relationship_sample_locked(request)

    def _relationship_sample_locked(
        self,
        request: EDARelationshipSampleRequest,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        base = EDAWorkspaceRequest(
            project_id=request.project_id,
            target=request.target,
            event_value=request.event_value,
            problem_type=request.problem_type,
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
            dataset_version=request.dataset_version,
        )
        full_df, target, full_y, problem, event, authorization = self._dataset(base)
        contract = self._governed_contract(
            request=base,
            df=full_df,
            target=target,
            event=event,
            authorization=authorization,
        )
        development, development_target, _development_scope = resolve_development_partition(
            store=DATASTORE.current(),
            identity={
                "project_id": contract["project_id"],
                "dataset_id": contract["dataset_id"],
                "dataset_version_id": contract["dataset_version_id"],
            },
            target=target,
            authorized_predictors=authorization["authorized_predictors"],
            predictor_manifest_id=contract["predictor_manifest_id"],
        )
        # All target-colored relationship points and pair metrics are derived
        # from development only. Meaning-bearing special codes are excluded
        # from ordinary numeric axes using the same predictor artifacts as the
        # rest of EDA.
        df = development.copy(deep=True)
        for feature, artifact in contract["predictor_artifacts"].items():
            if feature not in df.columns or not artifact.get("is_numeric"):
                continue
            codes = {
                float(group["code"])
                for group in (artifact.get("special_values") or {}).get("groups") or []
            }
            if codes:
                numeric = pd.to_numeric(df[feature], errors="coerce")
                df.loc[numeric.isin(codes), feature] = np.nan
        df[target] = development_target
        y = development_target
        dataset_version = str(DATASTORE.meta.get("dataset_version_id") or "unresolved")
        manifest_id = str(authorization["manifest_version"])
        if request.dataset_version and str(request.dataset_version) != dataset_version:
            raise ValueError(
                "The requested dataset version does not match the active "
                "server-governed dataset."
            )
        if (
            request.predictor_manifest_id
            and str(request.predictor_manifest_id) != manifest_id
        ):
            raise ValueError(
                "The requested predictor manifest does not match the active "
                "server-governed predictor authorization."
            )

        authorized = set(str(value) for value in authorization["authorized_predictors"])
        excluded_by_feature = {
            str(row.get("feature")): str(row.get("reason") or "Excluded by server authorization")
            for row in authorization.get("excluded", [])
            if isinstance(row, dict) and row.get("feature") is not None
        }
        requested_fields: list[tuple[str, str | None, bool]] = [
            ("x", request.x_feature, True),
            ("y", request.y_feature, True),
            ("z", request.z_feature, True),
            ("point_size", request.point_size_feature, True),
            ("segment", request.segment_feature, False),
            ("selection", request.selection_feature, True),
        ]
        rejected: list[dict[str, str]] = []

        def reject(field: str, role: str, reason: str) -> None:
            row = {"field": field, "role": role, "reason": reason}
            if row not in rejected:
                rejected.append(row)

        normalized: dict[str, str | None] = {}
        for role, raw_field, must_be_numeric in requested_fields:
            field = str(raw_field or "").strip()
            normalized[role] = field or None
            if role in {"x", "y"} and not field:
                reject(field or "(missing)", role, "A numeric axis is required")
                continue
            if not field:
                continue
            if field not in authorized or field not in df.columns:
                reject(
                    field,
                    role,
                    excluded_by_feature.get(
                        field,
                        "Not present in the active server-authorized predictor manifest",
                    ),
                )
                continue
            numeric, is_numeric = _numeric_series(df[field])
            if must_be_numeric and (
                not is_numeric or int(numeric.notna().sum()) < 3
            ):
                reject(field, role, "This role requires a numeric predictor")
            if role == "segment":
                distinct = int(df[field].nunique(dropna=True))
                if distinct < 2 or distinct > 100:
                    reject(
                        field,
                        role,
                        "An approved segment must contain between 2 and 100 groups",
                    )

        axes = [
            value
            for value in (normalized["x"], normalized["y"], normalized["z"])
            if value
        ]
        seen_axes: set[str] = set()
        for role in ("x", "y", "z"):
            field = normalized[role]
            if not field:
                continue
            if field in seen_axes:
                reject(field, role, "Relationship axes must use distinct predictors")
            seen_axes.add(field)
        if rejected:
            raise RelationshipSampleValidationError(rejected)

        source = (
            DATASTORE.meta.get("source")
            if isinstance(DATASTORE.meta.get("source"), dict)
            else {}
        )
        # Sampling and caching are keyed by the governed development artifact,
        # not a fingerprint that includes the sealed holdout target.  A
        # holdout-only change therefore cannot perturb a target-colored point.
        fingerprint = contract["relationship_artifact"]["artifact_hash"]
        cache_payload = {
            "section": "relationship-sample",
            "project_id": request.project_id,
            "workspace_instance": id(DATASTORE.get_base_df()),
            "data_revision": int(getattr(DATASTORE, "data_revision", 0)),
            "workspace_fingerprint": fingerprint,
            "dataset_version": dataset_version,
            "manifest_id": manifest_id,
            "split_id": contract["split_id"],
            "governed_relationship_artifact_id": contract[
                "relationship_artifact"
            ]["artifact_id"],
            "target": target,
            "event_value": request.event_value,
            "problem_type": request.problem_type,
            "x": normalized["x"],
            "y": normalized["y"],
            "z": normalized["z"],
            "point_size": normalized["point_size"],
            "segment": normalized["segment"],
            "selection": normalized["selection"],
            "sample_limit": int(request.sample_limit),
        }
        cache_key = hashlib.sha256(
            json.dumps(cache_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if cache_key in self._cache:
            cached = self._cache.pop(cache_key)
            self._cache[cache_key] = cached
            return {**cached, "cache_status": "hit"}

        frame = pd.DataFrame(index=df.index)
        for role in ("x", "y", "z", "point_size", "selection"):
            field = normalized[role]
            if field:
                frame[f"__{role}__"] = pd.to_numeric(
                    df[field], errors="coerce"
                ).replace([np.inf, -np.inf], np.nan)
        if normalized["segment"]:
            frame["__segment__"] = df[normalized["segment"]].astype("object")
        frame["__target__"] = y
        frame["__ordinal__"] = np.arange(len(frame), dtype=np.int64)

        if problem == "classification" and event is not None:
            frame["__target_group__"] = np.where(
                frame["__target__"].isna(),
                "missing",
                np.where(
                    frame["__target__"].astype(str) == str(event),
                    "event",
                    "non_event",
                ),
            )
            target_encoding = {
                "kind": "binary_event",
                "target": target,
                "groups": ["event", "non_event", "missing"],
            }
        elif problem == "regression":
            target_numeric = pd.to_numeric(frame["__target__"], errors="coerce")
            frame["__target_group__"] = "missing"
            present = target_numeric.notna()
            if int(present.sum()):
                band_count = min(5, int(present.sum()))
                try:
                    bands = pd.qcut(
                        target_numeric[present].rank(method="first"),
                        q=band_count,
                        labels=False,
                        duplicates="drop",
                    )
                    frame.loc[present, "__target_group__"] = [
                        f"Band {int(value) + 1}" for value in bands
                    ]
                except ValueError:
                    frame.loc[present, "__target_group__"] = "Target available"
            target_encoding = {
                "kind": "regression_bands",
                "target": target,
                "groups": sorted(
                    str(value) for value in frame["__target_group__"].unique()
                ),
            }
        else:
            frame["__target_group__"] = np.where(
                frame["__target__"].isna(), "missing", "target available"
            )
            target_encoding = {
                "kind": "target_availability",
                "target": target,
                "groups": ["target available", "missing"],
            }

        required_axis_columns = [
            f"__{role}__"
            for role in ("x", "y", "z")
            if normalized[role]
        ]
        eligible = frame.dropna(subset=required_axis_columns).copy()
        eligible_rows = int(len(eligible))

        pair_metrics: list[dict[str, Any]] = []
        for left_index, left in enumerate(axes):
            for right in axes[left_index + 1 :]:
                pairs = pd.DataFrame(
                    {
                        "left": pd.to_numeric(df[left], errors="coerce"),
                        "right": pd.to_numeric(df[right], errors="coerce"),
                    }
                ).replace([np.inf, -np.inf], np.nan).dropna()
                pair_metrics.append(
                    {
                        "a": left,
                        "b": right,
                        "correlation": (
                            _finite(pairs["left"].corr(pairs["right"]))
                            if len(pairs) >= 3
                            else None
                        ),
                        "n": int(len(pairs)),
                    }
                )

        seed_material = json.dumps(cache_payload, sort_keys=True, default=str)
        seed_id = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16]
        eligible["__sample_score__"] = [
            hashlib.sha256(
                f"{seed_id}:sample:{int(ordinal)}".encode("utf-8")
            ).hexdigest()
            for ordinal in eligible["__ordinal__"]
        ]
        sample_limit = min(int(request.sample_limit), eligible_rows)
        sampled_groups: list[pd.DataFrame] = []
        if sample_limit and eligible_rows > sample_limit:
            group_counts = eligible["__target_group__"].value_counts().sort_index()
            quotas: dict[str, int] = {}
            fractions: list[tuple[float, str]] = []
            for group, count in group_counts.items():
                exact = sample_limit * int(count) / eligible_rows
                quota = min(int(count), int(math.floor(exact)))
                quotas[str(group)] = quota
                fractions.append((exact - quota, str(group)))
            remaining = sample_limit - sum(quotas.values())
            for _fraction, group in sorted(
                fractions, key=lambda item: (-item[0], item[1])
            ):
                if remaining <= 0:
                    break
                capacity = int(group_counts.loc[group]) - quotas[group]
                if capacity > 0:
                    quotas[group] += 1
                    remaining -= 1
            for group, quota in quotas.items():
                if quota <= 0:
                    continue
                sampled_groups.append(
                    eligible[
                        eligible["__target_group__"].astype(str) == group
                    ]
                    .sort_values("__sample_score__", kind="stable")
                    .head(quota)
                )
            rendered = pd.concat(sampled_groups, axis=0)
        else:
            rendered = eligible
        rendered = rendered.sort_values("__sample_score__", kind="stable").head(
            sample_limit
        )

        points: list[dict[str, Any]] = []
        for row in rendered.to_dict(orient="records"):
            point: dict[str, Any] = {
                "id": hashlib.sha256(
                    f"{seed_id}:point:{int(row['__ordinal__'])}".encode("utf-8")
                ).hexdigest()[:16],
                "x": _finite(row.get("__x__")),
                "y": _finite(row.get("__y__")),
                "z": _finite(row.get("__z__")),
                "size": _finite(row.get("__point_size__")),
                "target_group": str(row.get("__target_group__") or "missing"),
                "segment_group": (
                    "Missing"
                    if normalized["segment"]
                    and pd.isna(row.get("__segment__"))
                    else (
                        str(row.get("__segment__"))
                        if normalized["segment"]
                        else None
                    )
                ),
                "selection_value": _finite(row.get("__selection__")),
            }
            points.append(point)

        analysis_scope = {
            "contractVersion": contract["contract_version"],
            "mode": "governed_version",
            "label": "Development Population",
            "projectId": contract["project_id"],
            "datasetId": contract["dataset_id"],
            "datasetVersionId": contract["dataset_version_id"],
            "target": contract["target"],
            "populationRows": contract["rows_used"],
            "fullGovernedPopulationRows": contract["population_rows"],
            "rowsExcluded": contract["rows_excluded"],
            "analysisPopulationId": contract["analysis_population_id"],
            "splitId": contract["split_id"],
            "exact": True,
            "sampled": eligible_rows > int(request.sample_limit),
            "artifactId": contract["artifact_id"],
            "artifactHash": contract["artifact_hash"],
            "finalHoldoutAccessed": False,
            "finalHoldoutUsedForSelection": False,
        }
        result = {
            "ok": True,
            "scope": "rendered_sample",
            "analysis_scope": analysis_scope,
            "scope_identity": f"governed-eda:{contract['artifact_hash']}",
            "project_id": request.project_id,
            "dataset_id": DATASTORE.meta.get("dataset_id"),
            "dataset_version_id": DATASTORE.meta.get("dataset_version_id"),
            "dataset_version": dataset_version,
            "predictor_manifest_id": manifest_id,
            "population_rows": int(len(df)),
            "full_governed_population_rows": contract["population_rows"],
            "eligible_rows": eligible_rows,
            "requested_rows": int(request.sample_limit),
            "returned_rows": int(len(points)),
            "sampled": eligible_rows > int(request.sample_limit),
            "sampling": {
                "method": "deterministic_proportional_stratified",
                "seed_id": seed_id,
                "missing_rows_excluded": int(len(df) - eligible_rows),
                "maximum_rows": 5000,
            },
            "axes": {
                "x": normalized["x"],
                "y": normalized["y"],
                "z": normalized["z"],
            },
            "encodings": {
                "point_size": normalized["point_size"],
                "segment": normalized["segment"],
                "selection_feature": normalized["selection"],
            },
            "pair_metrics": pair_metrics,
            "target_encoding": target_encoding,
            "points": points,
            "governance": {
                "authorized_fields": sorted(authorized),
                "target_source_excluded": authorization["target_source_excluded"],
                "analysis_population": "development_population",
                "special_value_representation": "excluded_from_ordinary_numeric_axes",
                "final_holdout_accessed": False,
                "final_holdout_used_for_selection": False,
            },
            "generated_at": _now(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "cache_status": "miss",
        }
        self._cache[cache_key] = result
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)
        return result

    def _full_population_assessment(self, target, problem, profile) -> dict[str, Any] | None:
        """Class balance, imbalance tier, and event-rate interval over the full
        backend population.

        This exists for the case where the project has no registered Dataset
        Library version, so `/api/analytics/target-assessment` has no immutable
        (dataset, version) to aggregate. The backend still holds the complete
        population here, so the Target tab must show exact figures rather than
        "Not available" -- and it must show the SAME figures, which is why this
        calls the shared `assess_class_balance` / `wilson_score_interval`
        functions instead of recomputing anything locally.
        """
        if problem != "classification":
            return None
        events = int(profile.get("event_count") or 0)
        non_events = int(profile.get("non_event_count") or 0)
        total = events + non_events
        if total <= 0:
            return None
        return {
            "supported": True,
            "source": "eda_full_population",
            "classBalance": {
                "target": str(target),
                "eventValue": None if profile.get("positive_class") is None else str(profile.get("positive_class")),
                "nonEventValue": None if profile.get("negative_class") is None else str(profile.get("negative_class")),
                "eventCount": events,
                "nonEventCount": non_events,
                "eventRate": events / total,
                "nonEventRate": non_events / total,
                "eventToNonEventRatio": (events / non_events) if non_events else None,
                "imbalanceRatio": (non_events / events) if events else None,
                "missingTargetCount": int(profile.get("missing_count") or 0),
                "totalModelingPopulation": total,
                "classCount": int(profile.get("class_count") or 0),
                "resolution": "exact",
            },
            "imbalance": assess_class_balance(events, non_events),
            "confidenceInterval": wilson_score_interval(events, total, 0.95),
        }

    def _governed_time_fields(self, df) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for column in df.columns:
            accepted = governed_time_field(str(column), df[column])
            if accepted:
                fields.append({
                    "field": str(column),
                    "minimum": accepted.get("min"),
                    "maximum": accepted.get("max"),
                    "basis": "datetime dtype" if pd.api.types.is_datetime64_any_dtype(df[column]) else "date-named text parsed at 80 percent or higher",
                })
        return fields

    def _time_stability(self, rows: list[dict[str, Any]], df, date_field: str | None) -> dict[str, Any] | None:
        """Material prevalence movement across observed periods.

        'Material' is defined conservatively: the widest period rate must be at
        least twice the narrowest AND differ by at least half a percentage point
        of the pooled rate, so ordinary rare-event noise across small monthly
        cells is not reported as a shift.
        """
        if not rows or not date_field:
            return None
        rates = [row["event_rate"] for row in rows if row.get("event_rate") is not None]
        if len(rates) < 2:
            return None
        pooled_events = sum(row["events"] for row in rows)
        pooled_count = sum(row["count"] for row in rows)
        pooled_rate = pooled_events / pooled_count if pooled_count else None
        lowest, highest = min(rates), max(rates)
        material = bool(
            pooled_rate
            and lowest > 0
            and (highest / lowest) >= 2.0
            and (highest - lowest) >= max(0.5 * pooled_rate, 0.0005)
        )
        return {
            "period_count": len(rows),
            "pooled_event_rate": pooled_rate,
            "lowest_period_event_rate": lowest,
            "highest_period_event_rate": highest,
            "material_shift": material,
            "missing_time_values": int(df[date_field].isna().sum()) if date_field in df.columns else 0,
            "rule": "A material shift requires the highest period rate to be at least twice the lowest and to differ by at least half the pooled rate.",
        }

    def _target_identity(self, df, target, y, problem, event, profile) -> dict[str, Any]:
        return {
            "target": str(target),
            "data_type": str(y.dtype),
            "problem_type": problem,
            "positive_value": _json_value(event) if problem == "classification" else None,
            "negative_value": profile.get("negative_class") if problem == "classification" else None,
            "missing_target_count": int(y.isna().sum()),
            "population_row_count": int(len(df)),
            "modeling_population_row_count": int(y.notna().sum()),
            "distinct_value_count": int(y.dropna().nunique()),
        }

    def _target_quality(
        self,
        df,
        target,
        y,
        problem,
        event,
        profile,
        *,
        include_leakage: bool = True,
    ) -> dict[str, Any]:
        """Part I: focused target measurability review.

        Reuses the same conservative name families and the same duplicate
        detection as the rest of ATLAS; it does not introduce a second leakage
        engine. Every automated conclusion stops at 'Review recommended' --
        'Likely leakage' requires a structural rule (perfect separation or a
        near-perfect correlation), and 'Confirmed leakage' is only ever set by a
        reviewer.
        """
        valid = y.dropna()
        missing_count = int(y.isna().sum())

        invalid_values: list[dict[str, Any]] = []
        unexpected_values: list[str] = []
        if problem == "classification":
            governed = {str(event), str(profile.get("negative_class"))} if event is not None else set()
            counts = valid.astype(str).value_counts()
            if governed and len(counts) > 2:
                unexpected_values = [str(index) for index in counts.index if str(index) not in governed][:20]
            # A blank-but-not-null target value is neither a class nor a missing
            # value; it is an invalid record that would silently join a class.
            blanks = int((valid.astype(str).str.strip() == "").sum())
            if blanks:
                invalid_values.append({"reason": "Blank (whitespace-only) target value", "count": blanks})
        else:
            numeric = pd.to_numeric(valid, errors="coerce")
            unparsed = int(numeric.isna().sum())
            if unparsed:
                invalid_values.append({"reason": "Target value could not be parsed as a number", "count": unparsed})
            non_finite = int(np.isinf(numeric.dropna().to_numpy(dtype=float)).sum()) if len(numeric.dropna()) else 0
            if non_finite:
                invalid_values.append({"reason": "Non-finite target value", "count": non_finite})

        duplicate_rows = int(df.duplicated().sum())
        # Duplicate records that carry a target are the ones that actually bias a
        # rate: a duplicated row with a missing target contributes to neither
        # numerator nor denominator.
        duplicate_mask = df.duplicated(keep=False) & y.notna()
        duplicate_target_rows = int(df[duplicate_mask].duplicated().sum())

        candidates = (
            self._leakage_candidates(df, target, y, problem, event)
            if include_leakage
            else []
        )

        return {
            "missing_target_count": missing_count,
            "missing_target_rate": missing_count / max(len(y), 1),
            "invalid_target_values": invalid_values,
            "unexpected_target_values": unexpected_values,
            "target_cardinality": int(valid.nunique()),
            "duplicate_rows": duplicate_rows,
            "duplicate_target_bearing_rows": duplicate_target_rows,
            "target_derived_candidates": [item for item in candidates if item["family"] == "target_derived"],
            "post_outcome_candidates": [item for item in candidates if item["family"] == "post_outcome"],
            "perfect_relationship_candidates": [item for item in candidates if item["family"] == "perfect_relationship"],
            "leakage_states": list(LEAKAGE_STATES),
            "assessment_rule": (
                "Name-based matches are reported as 'Review recommended' only. 'Likely leakage' requires a structural "
                "rule: a low-cardinality field that perfectly separates the target, or a numeric field correlated with "
                "the target at 0.999 or above. High IV, high correlation, and differing event rates alone are never "
                "sufficient. 'Confirmed leakage' is set by a reviewer, never by ATLAS."
            ),
        }

    def _leakage_candidates(self, df, target, y, problem, event) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        numeric_target = pd.to_numeric(y, errors="coerce") if problem == "regression" else (y.astype(str) == str(event)).astype(float)
        row_count = int(len(df))

        for column in df.columns:
            if str(column) == str(target):
                continue
            name = str(column)
            series = df[column]

            if _TARGET_DERIVED_NAME.search(name):
                candidates.append({
                    "feature": name, "family": "target_derived", "state": "review_recommended",
                    "reason": "The field name suggests it may be derived from the target or from a model output.",
                })
            if _POST_OUTCOME_NAME.search(name):
                candidates.append({
                    "feature": name, "family": "post_outcome", "state": "review_recommended",
                    "reason": "The field name suggests information recorded after the outcome was known.",
                })

            if row_count < MIN_SEPARATION_ROWS:
                continue
            distinct = int(series.nunique(dropna=True))
            if 2 <= distinct <= MAX_SEPARATION_CARDINALITY and problem == "classification":
                frame = pd.DataFrame({"value": series.astype(str), "target": y.astype(str)}).dropna()
                if not frame.empty and int(frame.groupby("value")["target"].nunique().max()) == 1:
                    candidates.append({
                        "feature": name, "family": "perfect_relationship", "state": "likely_leakage",
                        "reason": f"Every one of the {distinct} distinct values maps to exactly one target class. A predictor cannot separate an outcome perfectly unless it encodes it.",
                    })
                    continue
            numeric, is_numeric = _numeric_series(series)
            if is_numeric:
                pairs = pd.DataFrame({"x": numeric, "y": numeric_target}).dropna()
                if len(pairs) >= 3:
                    correlation = _finite(pairs["x"].corr(pairs["y"]))
                    if correlation is not None and abs(correlation) >= PERFECT_CORRELATION_THRESHOLD:
                        candidates.append({
                            "feature": name, "family": "perfect_relationship", "state": "likely_leakage",
                            "reason": f"Correlation with the target is {correlation:.4f}, which is not attainable for a legitimate predictor.",
                        })
        return candidates[:100]

    def _group_target(self, df, target, event, field, as_date: bool) -> list[dict[str, Any]]:
        if not field:
            return []
        frame = df[[field, target]].copy()
        if as_date:
            parsed = pd.to_datetime(frame[field], errors="coerce")
            if parsed.notna().mean() < 0.8:
                return []
            frame["group"] = parsed.dt.to_period("M").astype(str)
        else:
            frame["group"] = frame[field].astype("object").where(frame[field].notna(), "__MISSING__").astype(str)
            keep = set(frame["group"].value_counts().head(50).index)
            frame["group"] = frame["group"].where(frame["group"].isin(keep), "__OTHER__")
        frame = frame.dropna(subset=[target])
        frame["event"] = frame[target].astype(str) == str(event)
        grouped = frame.groupby("group", dropna=False)["event"].agg(["size", "sum"])
        return [{"group": str(index), "count": int(row["size"]), "events": int(row["sum"]), "event_rate": float(row["sum"] / row["size"])} for index, row in grouped.iterrows()]

    def _predictors(self, df, target, y, problem, event, request) -> dict[str, Any]:
        started = time.perf_counter()
        shape_limit = int(request.predictor_visual_shape_limit)
        requested = [column for column in request.selected_features if column in df.columns and column != target]
        columns = requested or [str(column) for column in df.columns if column != target]
        numeric_profiles: list[dict[str, Any]] = []
        categorical_profiles: list[dict[str, Any]] = []
        missing_profiles: list[dict[str, Any]] = []
        for column in columns:
            series = df[column]
            numeric, is_numeric = _numeric_series(series)
            missing_count = int(series.isna().sum())
            missing_rate = missing_count / max(len(series), 1)
            present_event_rate = _event_rate(y[series.notna()], event) if problem == "classification" else None
            missing_event_rate = _event_rate(y[series.isna()], event) if problem == "classification" else None
            special_mask, bureau_special = _bureau_special_profile(
                column,
                series,
                numeric,
                y,
                event if problem == "classification" else None,
            )
            missing_profiles.append({
                "feature": column,
                "missing_count": missing_count,
                "missing_rate": missing_rate,
                "present_event_rate": present_event_rate,
                "missing_event_rate": missing_event_rate,
                "informative_missingness": bool(present_event_rate is not None and missing_event_rate is not None and abs(present_event_rate - missing_event_rate) >= 0.02),
                "missing_semantics": "null_only",
                "bureau_special_value_count": bureau_special["count"],
                "bureau_special_value_prevalence": bureau_special["prevalence"],
                "bureau_special_values_are_missing": False,
            })
            if is_numeric:
                clean = numeric.dropna()
                histogram = _histogram_bins(numeric, bins=request.histogram_bins)
                quantiles = _series_quantiles(clean)
                q1, q3 = quantiles["q1"], quantiles["q3"]
                iqr = (q3 - q1) if q1 is not None and q3 is not None else None
                outlier_rate = float(((clean < q1 - 1.5 * iqr) | (clean > q3 + 1.5 * iqr)).mean()) if iqr is not None and len(clean) else None
                association = None
                iv = None
                if problem == "classification":
                    try:
                        iv, _ = information_value(series, y, event)
                    except ValueError:
                        iv = None
                else:
                    pairs = pd.DataFrame({"x": numeric, "y": pd.to_numeric(y, errors="coerce")}).dropna()
                    association = _finite(pairs["x"].corr(pairs["y"])) if len(pairs) >= 3 else None
                event_bins = _quantile_event_table(series, y, event) if problem == "classification" else []
                if bureau_special["count"]:
                    regular_numeric = numeric[numeric.notna() & ~special_mask]
                    regular_quantiles = _series_quantiles(regular_numeric)
                    regular_q1, regular_q3 = (
                        regular_quantiles["q1"],
                        regular_quantiles["q3"],
                    )
                    regular_iqr = (
                        regular_q3 - regular_q1
                        if regular_q1 is not None and regular_q3 is not None
                        else None
                    )
                    ordinary_outlier_mask = (
                        (regular_numeric < regular_q1 - 1.5 * regular_iqr)
                        | (regular_numeric > regular_q3 + 1.5 * regular_iqr)
                        if regular_iqr is not None
                        else pd.Series(False, index=regular_numeric.index)
                    )
                    ordinary_outlier_count = int(ordinary_outlier_mask.sum())
                    ordinary_outlier_rate = (
                        float(ordinary_outlier_mask.mean())
                        if regular_iqr is not None and len(regular_numeric)
                        else None
                    )
                    visual_event_bins = (
                        _quantile_event_table(
                            series.mask(special_mask),
                            y,
                            event,
                            bins=shape_limit,
                        )
                        if problem == "classification"
                        else []
                    )
                else:
                    regular_numeric = clean
                    ordinary_outlier_count = (
                        int(
                            (
                                (clean < q1 - 1.5 * iqr)
                                | (clean > q3 + 1.5 * iqr)
                            ).sum()
                        )
                        if iqr is not None
                        else 0
                    )
                    ordinary_outlier_rate = outlier_rate
                    visual_event_bins = event_bins[:shape_limit]
                event_rate_shape = _predictor_event_shape(
                    kind="quantile",
                    source_rows=visual_event_bins,
                    population_rows=len(df),
                    limit=shape_limit,
                )
                numeric_profiles.append({
                    "feature": column,
                    "count": int(len(clean)),
                    "missing_count": missing_count,
                    "missing_rate": missing_rate,
                    "mean": _finite(clean.mean()),
                    "standard_deviation": _finite(clean.std()),
                    "minimum": _finite(clean.min()),
                    **quantiles,
                    "maximum": _finite(clean.max()),
                    "skewness": _finite(clean.skew()),
                    "kurtosis": _finite(clean.kurt()),
                    "distinct_count": int(series.nunique(dropna=True)),
                    "zero_rate": float((clean == 0).mean()) if len(clean) else None,
                    "negative_rate": float((clean < 0).mean()) if len(clean) else None,
                    "outlier_rate": outlier_rate,
                    "outlier_rate_semantics": (
                        "legacy_raw_numeric_rate_may_include_bureau_special_values"
                    ),
                    "ordinary_outlier_count": ordinary_outlier_count,
                    "ordinary_outlier_rate": ordinary_outlier_rate,
                    "ordinary_outlier_denominator": int(len(regular_numeric)),
                    "ordinary_outlier_excludes_nulls": True,
                    "ordinary_outlier_excludes_bureau_special_values": True,
                    "correlation_with_target": association,
                    "iv": iv,
                    "event_rate_by_quantile": event_bins,
                    "event_rate_shape": event_rate_shape,
                    "histogram": histogram,
                    "histogram_bin_count": len(histogram),
                    "monotonicity": _monotonicity(event_bins) if event_bins else None,
                    "regular_monotonicity": (
                        _monotonicity(visual_event_bins)
                        if visual_event_bins
                        else None
                    ),
                    "present_event_rate": present_event_rate,
                    "missing_event_rate": missing_event_rate,
                    "bureau_special": bureau_special,
                })
            else:
                values = series.astype("object").where(series.notna(), "__MISSING__").astype(str)
                counts = values.value_counts()
                top_levels = []
                for level, count in counts.head(20).items():
                    mask = values == level
                    top_levels.append({
                        "level": str(level),
                        "count": int(count),
                        "rate": float(count / len(values)),
                        "event_rate": _event_rate(y[mask], event) if problem == "classification" else None,
                    })
                special_value_labels = {
                    str(item["value"])
                    for item in bureau_special["values"]
                }
                special_value_labels.update(
                    f"{float(item['value']):g}"
                    for item in bureau_special["values"]
                )
                event_rate_shape = _predictor_event_shape(
                    kind="top_levels",
                    source_rows=top_levels,
                    population_rows=len(df),
                    limit=shape_limit,
                    special_value_labels=special_value_labels,
                )
                iv = None
                if problem == "classification":
                    try:
                        iv, _ = information_value(series, y, event)
                    except ValueError:
                        iv = None
                cardinality = int(series.nunique(dropna=True))
                rare_levels = int((counts < max(5, int(len(values) * 0.001))).sum())
                stripped_unique = int(series.dropna().astype(str).str.strip().str.lower().nunique())
                categorical_profiles.append({
                    "feature": column,
                    "count": int(series.notna().sum()),
                    "missing_count": missing_count,
                    "missing_rate": missing_rate,
                    "cardinality": cardinality,
                    "rare_level_count": rare_levels,
                    "top_levels": top_levels,
                    "iv": iv,
                    "high_cardinality": bool(cardinality > 50 or cardinality / max(len(values), 1) > 0.2),
                    "sparse_levels": bool(rare_levels > 0),
                    "inconsistent_labels": bool(stripped_unique < cardinality),
                    "suggested_grouping": "Review rare levels for grouping" if rare_levels else "No grouping indicated",
                    "present_event_rate": present_event_rate,
                    "missing_event_rate": missing_event_rate,
                    "event_rate_shape": event_rate_shape,
                    "bureau_special": bureau_special,
                })
        numeric_profiles.sort(key=lambda row: abs(float(row.get("iv") or row.get("correlation_with_target") or 0)), reverse=True)
        categorical_profiles.sort(key=lambda row: abs(float(row.get("iv") or 0)), reverse=True)
        missing_profiles.sort(key=lambda row: row["missing_rate"], reverse=True)
        visual_profiles = [
            {
                "feature": row["feature"],
                "kind": "numeric",
                "scope": "full_dataset_aggregates",
                "population_rows": int(len(df)),
                "metrics": {
                    "iv": _finite(row.get("iv")),
                    "missing_rate": _finite(row.get("missing_rate")),
                    "outlier_count": int(
                        row.get("ordinary_outlier_count") or 0
                    ),
                    "outlier_rate": _finite(row.get("ordinary_outlier_rate")),
                    "distinct_count": int(row.get("distinct_count") or 0),
                    "skewness": _finite(row.get("skewness")),
                    "monotonicity": row.get("regular_monotonicity"),
                    "vif": None,
                    "vif_status": "pending_relationship_review",
                    "special_prevalence": _finite(
                        (row.get("bureau_special") or {}).get("prevalence")
                    ),
                },
                "ordinary_outlier": {
                    "count": int(row.get("ordinary_outlier_count") or 0),
                    "rate": _finite(row.get("ordinary_outlier_rate")),
                    "denominator": int(
                        row.get("ordinary_outlier_denominator") or 0
                    ),
                    "excludes_nulls": True,
                    "excludes_bureau_special_values": True,
                    "semantics": "regular_numeric_iqr_only",
                },
                "missing": {
                    "count": int(row.get("missing_count") or 0),
                    "rate": _finite(row.get("missing_rate")),
                    "event_rate": _finite(row.get("missing_event_rate")),
                    "semantics": "null_only",
                },
                "bureau_special": row.get("bureau_special"),
                "event_rate_shape": row.get("event_rate_shape"),
            }
            for row in numeric_profiles
        ]
        visual_profiles.extend(
            {
                "feature": row["feature"],
                "kind": "categorical",
                "scope": "full_dataset_aggregates",
                "population_rows": int(len(df)),
                "metrics": {
                    "iv": _finite(row.get("iv")),
                    "missing_rate": _finite(row.get("missing_rate")),
                    "outlier_count": None,
                    "outlier_rate": None,
                    "distinct_count": int(row.get("cardinality") or 0),
                    "skewness": None,
                    "monotonicity": None,
                    "vif": None,
                    "vif_status": "not_applicable_categorical",
                    "special_prevalence": _finite(
                        (row.get("bureau_special") or {}).get("prevalence")
                    ),
                },
                "missing": {
                    "count": int(row.get("missing_count") or 0),
                    "rate": _finite(row.get("missing_rate")),
                    "event_rate": _finite(row.get("missing_event_rate")),
                    "semantics": "null_only",
                },
                "bureau_special": row.get("bureau_special"),
                "event_rate_shape": row.get("event_rate_shape"),
            }
            for row in categorical_profiles
        )
        return {
            "numeric": numeric_profiles,
            "categorical": categorical_profiles,
            "missingness": missing_profiles,
            "profiled_features": len(columns),
            "predictor_visual_profiles": visual_profiles,
            "predictor_visual_contract": {
                "version": PREDICTOR_VISUAL_CONTRACT_VERSION,
                "request_mode": "single_batched_workspace_request",
                "scope": "full_dataset_aggregates",
                "profile_count": len(visual_profiles),
                "event_rate_shape_limit": shape_limit,
                "raw_observations_included": False,
                "server_authorized_predictors_only": True,
                "target_excluded": True,
                "target_source_exclusions_disclosed_at_response_root": True,
                "non_overlapping_quality_buckets": [
                    "null_missing",
                    "bureau_special_value",
                    "ordinary_outlier",
                ],
                "additional_vif_computation": False,
                "vif_status": "pending_relationship_review",
                "documentation_identity_excludes": [
                    "generated_at",
                    "duration_ms",
                    "cache_status",
                    "predictor_visual_contract.profile_duration_ms",
                ],
                "profile_duration_ms": int(
                    (time.perf_counter() - started) * 1000
                ),
            },
        }

    def _distribution(self, df, target, y, problem, event, request) -> dict[str, Any]:
        """Exact server-side distribution and optional brushed-range summary."""

        feature = str(request.feature or "").strip()
        if not feature:
            raise ValueError("Select an authorized numeric predictor for distribution analysis.")
        if feature == target or feature not in df.columns:
            raise ValueError(f"Predictor '{feature}' is not authorized for EDA distribution analysis.")

        numeric = pd.to_numeric(df[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
        finite_mask = numeric.notna()
        values = numeric[finite_mask]
        if values.empty:
            raise ValueError(f"Authorized predictor '{feature}' has no finite numeric values.")

        requested_bins = min(60, max(5, int(request.histogram_bins)))
        counts, edges = np.histogram(values.to_numpy(dtype=float), bins=requested_bins)
        event_mask = (y.notna() & (y.astype(str) == str(event))) if problem == "classification" and event is not None else pd.Series(False, index=df.index)
        non_event_mask = (y.notna() & ~event_mask) if problem == "classification" and event is not None else pd.Series(False, index=df.index)
        event_counts = np.histogram(numeric[finite_mask & event_mask].to_numpy(dtype=float), bins=edges)[0]
        non_event_counts = np.histogram(numeric[finite_mask & non_event_mask].to_numpy(dtype=float), bins=edges)[0]
        valid_count = int(len(values))

        histogram: list[dict[str, Any]] = []
        for index, count in enumerate(counts):
            lower = float(edges[index])
            upper = float(edges[index + 1])
            width = upper - lower
            events = int(event_counts[index])
            target_rows = events + int(non_event_counts[index])
            histogram.append({
                "key": f"{index}:{lower:.12g}:{upper:.12g}",
                "bin": index + 1,
                "lower": _finite(lower),
                "upper": _finite(upper),
                "count": int(count),
                "share": float(count / max(len(df), 1)),
                "valid_share": float(count / max(valid_count, 1)),
                "density": float(count / max(valid_count * width, 1e-12)),
                "event_count": events if problem == "classification" else None,
                "non_event_count": int(non_event_counts[index]) if problem == "classification" else None,
                "event_rate": (events / target_rows) if problem == "classification" and target_rows else None,
            })

        missing_mask = ~finite_mask
        missing_count = int(missing_mask.sum())
        missing_events = int(event_mask[missing_mask].sum()) if problem == "classification" else 0
        missing_target_rows = int(y[missing_mask].notna().sum()) if problem == "classification" else 0
        missing_bucket = {
            "label": "Missing / non-finite",
            "count": missing_count,
            "share": missing_count / max(len(df), 1),
            "event_count": missing_events if problem == "classification" else None,
            "non_event_count": (missing_target_rows - missing_events) if problem == "classification" else None,
            "event_rate": (missing_events / missing_target_rows) if problem == "classification" and missing_target_rows else None,
        }

        requested_min = request.selection_min
        requested_max = request.selection_max
        if requested_min is None and requested_max is None:
            lower_selection = float(values.min())
            upper_selection = float(values.max())
            selection_active = False
        else:
            lower_selection = float(requested_min if requested_min is not None else values.min())
            upper_selection = float(requested_max if request.selection_max is not None else values.max())
            if lower_selection > upper_selection:
                lower_selection, upper_selection = upper_selection, lower_selection
            selection_active = True
        selected_mask = finite_mask & numeric.between(lower_selection, upper_selection, inclusive="both")
        selected = numeric[selected_mask]
        selected_count = int(selected_mask.sum())
        selected_quantiles = selected.quantile([0.25, 0.5, 0.75]) if selected_count else pd.Series(dtype=float)
        selected_target_rate = _event_rate(y[selected_mask], event) if problem == "classification" else None
        selected_subset = {
            "active": selection_active,
            "minimum": _finite(lower_selection),
            "maximum": _finite(upper_selection),
            "row_count": selected_count,
            "population_share": selected_count / max(len(df), 1),
            "valid_share": selected_count / max(valid_count, 1),
            "mean": _finite(selected.mean()) if selected_count else None,
            "median": _finite(selected.median()) if selected_count else None,
            "standard_deviation": _finite(selected.std()) if selected_count > 1 else None,
            "q1": _finite(selected_quantiles.loc[0.25]) if selected_count else None,
            "q3": _finite(selected_quantiles.loc[0.75]) if selected_count else None,
            "minimum_value": _finite(selected.min()) if selected_count else None,
            "maximum_value": _finite(selected.max()) if selected_count else None,
            "event_count": int(event_mask[selected_mask].sum()) if problem == "classification" else None,
            "target_rate": selected_target_rate,
            "lower_percentile": float((values < lower_selection).mean()),
            "upper_percentile": float((values <= upper_selection).mean()),
        }

        quantiles = values.quantile([0.25, 0.5, 0.75])
        q1 = float(quantiles.loc[0.25])
        median = float(quantiles.loc[0.5])
        q3 = float(quantiles.loc[0.75])
        iqr = q3 - q1
        outlier_lower = q1 - 1.5 * iqr
        outlier_upper = q3 + 1.5 * iqr

        iv_rows: list[dict[str, Any]] = []
        iv_total: float | None = None
        if problem == "classification" and event is not None:
            source_rows = [
                {
                    "label": f"{row['lower']:.4g} – {row['upper']:.4g}",
                    "count": int(row["count"]),
                    "event_count": int(row["event_count"] or 0),
                    "non_event_count": int(row["non_event_count"] or 0),
                    "lower": row["lower"],
                    "upper": row["upper"],
                    "missing": False,
                }
                for row in histogram
            ]
            if missing_count:
                source_rows.append({
                    "label": "Missing / non-finite",
                    "count": missing_count,
                    "event_count": int(missing_bucket["event_count"] or 0),
                    "non_event_count": int(missing_bucket["non_event_count"] or 0),
                    "lower": None,
                    "upper": None,
                    "missing": True,
                })
            bucket_count = max(len(source_rows), 1)
            smoothing = 0.5
            event_total = sum(row["event_count"] for row in source_rows)
            non_event_total = sum(row["non_event_count"] for row in source_rows)
            event_denominator = event_total + smoothing * bucket_count
            non_event_denominator = non_event_total + smoothing * bucket_count
            iv_total = 0.0
            for row in source_rows:
                event_distribution = (row["event_count"] + smoothing) / max(event_denominator, smoothing)
                non_event_distribution = (row["non_event_count"] + smoothing) / max(non_event_denominator, smoothing)
                woe = math.log(event_distribution / non_event_distribution)
                contribution = (event_distribution - non_event_distribution) * woe
                iv_total += contribution
                iv_rows.append({
                    **row,
                    "event_distribution": event_distribution,
                    "non_event_distribution": non_event_distribution,
                    "woe": woe,
                    "iv_contribution": contribution,
                    "event_rate": row["event_count"] / max(row["event_count"] + row["non_event_count"], 1),
                })

        return {
            "feature": feature,
            "target_event_value": _json_value(event),
            "engine": "server_numpy_full_population",
            "resolution": "exact",
            "bins": histogram,
            "histogram": histogram,
            "missing_bucket": missing_bucket,
            "selected_subset": selected_subset,
            "selected_range": selected_subset,
            "statistics": {
                "count": valid_count,
                "missing_count": missing_count,
                "missing_rate": missing_count / max(len(df), 1),
                "mean": _finite(values.mean()),
                "standard_deviation": _finite(values.std()),
                "minimum": _finite(values.min()),
                "q1": q1,
                "median": median,
                "q3": q3,
                "maximum": _finite(values.max()),
                "outlier_lower": _finite(outlier_lower),
                "outlier_upper": _finite(outlier_upper),
                "outlier_count": int(((values < outlier_lower) | (values > outlier_upper)).sum()),
            },
            "markers": {
                "mean": _finite(values.mean()),
                "median": median,
                "q1": q1,
                "q3": q3,
                "outlier_lower": _finite(outlier_lower),
                "outlier_upper": _finite(outlier_upper),
            },
            "iv": _finite(iv_total),
            "iv_by_bin": iv_rows,
            "requested_bins": requested_bins,
            "returned_bins": len(histogram),
        }

    def _relationships(self, df, target, y, problem, event, request) -> dict[str, Any]:
        candidate_columns = request.selected_features or [str(column) for column in df.columns if column != target]
        numeric_data: dict[str, pd.Series] = {}
        for column in candidate_columns:
            if column not in df.columns or column == target:
                continue
            numeric, is_numeric = _numeric_series(df[column])
            if is_numeric and numeric.notna().sum() >= 3:
                numeric_data[column] = numeric
        numeric_df = pd.DataFrame(numeric_data)
        correlation = numeric_df.corr() if numeric_df.shape[1] >= 2 else pd.DataFrame()
        correlation_n_matrix = (
            [
                [
                    int((numeric_df[left].notna() & numeric_df[right].notna()).sum())
                    for right in correlation.columns
                ]
                for left in correlation.columns
            ]
            if not correlation.empty
            else []
        )
        strong_pairs: list[dict[str, Any]] = []
        if not correlation.empty:
            for left_index, left in enumerate(correlation.columns):
                for right in correlation.columns[left_index + 1:]:
                    value = _finite(correlation.loc[left, right])
                    if value is not None and abs(value) >= 0.7:
                        strong_pairs.append({"feature_a": str(left), "feature_b": str(right), "correlation": value})
            strong_pairs.sort(key=lambda row: abs(row["correlation"]), reverse=True)
        vif_frame, vif_scope = self._prepare_vif_frame(numeric_df)
        vif_rows = self._vif(vif_frame)
        for row in vif_rows:
            feature = str(row["feature"])
            row["top_relationships"] = [
                {"feature": str(partner), "correlation": _finite(correlation.loc[feature, partner])}
                for partner in correlation.columns
                if partner != feature and _finite(correlation.loc[feature, partner]) is not None
            ]
            row["top_relationships"].sort(key=lambda item: abs(float(item["correlation"] or 0)), reverse=True)
            row["top_relationships"] = row["top_relationships"][:5]

        target_association: list[dict[str, Any]] = []
        for column, numeric in numeric_data.items():
            if problem == "classification":
                try:
                    value, _ = information_value(df[column], y, event)
                except ValueError:
                    value = None
                event_rows = _quantile_event_table(df[column], y, event)
                target_association.append({
                    "feature": column,
                    "iv": _finite(value),
                    "correlation_with_target": None,
                    "monotonicity": _monotonicity(event_rows) if event_rows else None,
                })
            else:
                target_pairs = pd.DataFrame({"x": numeric, "y": pd.to_numeric(y, errors="coerce")}).dropna()
                target_association.append({
                    "feature": column,
                    "iv": None,
                    "correlation_with_target": _finite(target_pairs["x"].corr(target_pairs["y"])) if len(target_pairs) >= 3 else None,
                    "monotonicity": None,
                })
        association_key = "iv" if problem == "classification" else "correlation_with_target"
        target_association.sort(key=lambda row: abs(float(row.get(association_key) or 0)), reverse=True)
        all_requested_pairwise = [
            str(column) for column in request.pairwise_features
        ]
        requested_pairwise = all_requested_pairwise[:6]
        rejected_pairwise = [
            {
                "field": column,
                "role": "pairwise",
                "reason": "Not an authorized numeric predictor",
            }
            for column in all_requested_pairwise
            if column not in numeric_df.columns
        ]
        rejected_pairwise.extend(
            {
                "field": column,
                "role": "pairwise",
                "reason": "The bounded pairwise view accepts at most six predictors",
            }
            for column in all_requested_pairwise[6:]
            if column in numeric_df.columns
        )
        if rejected_pairwise:
            raise RelationshipSampleValidationError(rejected_pairwise)
        pairwise = requested_pairwise
        rendered = pd.DataFrame()
        if pairwise:
            sample_frame = pd.concat([numeric_df[pairwise], y.rename("__target__")], axis=1).dropna(subset=pairwise)
            if problem == "classification" and event is not None and "__target__" in sample_frame.columns:
                events = sample_frame[sample_frame["__target__"].astype(str) == str(event)]
                non_events = sample_frame[sample_frame["__target__"].astype(str) != str(event)]
                event_limit = min(len(events), max(25, request.rendered_sample_limit // 3))
                non_event_limit = max(0, request.rendered_sample_limit - event_limit)
                rendered = pd.concat([events.head(event_limit), non_events.head(non_event_limit)], axis=0).head(request.rendered_sample_limit)
            else:
                rendered = sample_frame.head(request.rendered_sample_limit)
            rendered["__event__"] = rendered["__target__"].astype(str) == str(event) if problem == "classification" and event is not None else False
            # The browser only needs the derived event flag for color encoding.
            # Never serialize the raw governed target into a bounded plot sample.
            rendered = rendered.drop(columns=["__target__"], errors="ignore")
        return {
            "correlation_columns": [str(column) for column in correlation.columns],
            "correlation_matrix": [[_finite(value) for value in row] for row in correlation.to_numpy()] if not correlation.empty else [],
            "correlation_n_matrix": correlation_n_matrix,
            "strong_pairs": strong_pairs[:100],
            "vif": vif_rows,
            "vif_scope": vif_scope,
            "target_association": target_association,
            "pairwise_features": pairwise,
            "pairwise_sample": [{str(key): _json_value(value) for key, value in row.items()} for row in rendered.to_dict(orient="records")],
            "pairwise_scope": "rendered_sample" if pairwise else "unavailable",
            "pairwise_rows": int(len(rendered)),
            "pairwise_event_rows": int(rendered["__event__"].sum()) if "__event__" in rendered.columns else 0,
            "pairwise_limit": 6,
        }

    def _prepare_vif_frame(
        self,
        numeric_df: pd.DataFrame,
        required_feature: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Create the exact governed complete-case cohort used everywhere."""

        clean = numeric_df.replace([np.inf, -np.inf], np.nan)
        variances = clean.var(skipna=True).replace(0, np.nan).dropna().sort_values(ascending=False)
        selected = [
            str(column)
            for column in variances.index
            if column in clean.columns
        ]
        work = clean.loc[:, selected].dropna() if selected else pd.DataFrame(index=clean.index)
        complete_case_rows = int(len(work))
        # Correlation/Relationships, temporary simulation, and Auto-VIF all use
        # this exact cohort. No sampling or predictor cap may create divergent
        # VIF values for the same governed identity.
        sampled = False
        maximum_rows = max(20_000, complete_case_rows)
        predictor_cap = len(selected)
        scope = {
            "scope": "governed_exact_development_complete_case",
            "population_rows": int(len(numeric_df)),
            "complete_case_rows": complete_case_rows,
            "rows_used": int(len(work)),
            "sampled": sampled,
            "maximum_rows": maximum_rows,
            "source_predictors": int(numeric_df.shape[1]),
            "predictors_used": [str(column) for column in work.columns],
            "predictor_cap": predictor_cap,
            "required_feature": required_feature,
        }
        return work, scope

    @staticmethod
    def _governed_ordinary_numeric_frame(
        development: pd.DataFrame,
        contract: dict[str, Any],
        features: list[str],
    ) -> pd.DataFrame:
        """Apply the contract's special/null policy before correlation or VIF."""

        numeric: dict[str, pd.Series] = {}
        artifacts = contract.get("predictor_artifacts") or {}
        for feature in features:
            artifact = artifacts.get(str(feature))
            if (
                not artifact
                or not artifact.get("is_numeric")
                or feature not in development.columns
            ):
                continue
            values = pd.to_numeric(
                development[feature], errors="coerce"
            ).replace([np.inf, -np.inf], np.nan)
            special_codes = {
                float(group["code"])
                for group in (artifact.get("special_values") or {}).get("groups")
                or []
            }
            if special_codes:
                values = values.mask(values.isin(special_codes))
            if int(values.notna().sum()) >= 3:
                numeric[str(feature)] = values
        return pd.DataFrame(numeric, index=development.index)

    def _vif(self, work: pd.DataFrame) -> list[dict[str, Any]]:
        if work.shape[1] < 2 or len(work) < 5:
            return []
        values = (work - work.mean()) / work.std(ddof=0).replace(0, 1)
        rows: list[dict[str, Any]] = []
        for column in values.columns:
            y = values[column].to_numpy()
            X = values.drop(columns=[column]).to_numpy()
            X = np.column_stack([np.ones(len(X)), X])
            try:
                fitted = X @ np.linalg.lstsq(X, y, rcond=None)[0]
                denominator = float(((y - y.mean()) ** 2).sum())
                r_squared = 1 - float(((y - fitted) ** 2).sum()) / denominator if denominator > 0 else 1
                vif = 1 / max(1 - r_squared, 1e-9)
            except np.linalg.LinAlgError:
                vif = float("inf")
            rows.append({
                "feature": str(column),
                "vif": _finite(vif),
                "is_infinite": not math.isfinite(vif),
                "status": "high" if vif >= 10 else "review" if vif >= 5 else "acceptable",
            })
        return sorted(
            rows,
            key=lambda row: (
                1 if row.get("is_infinite") else 0,
                float(row["vif"] or 0),
            ),
            reverse=True,
        )

    def _stability(self, df, target, y, problem, event, request) -> dict[str, Any]:
        date_field = request.date_field if request.date_field in df.columns else None
        segment_field = request.segment_field if request.segment_field in df.columns else None
        time_rows = self._group_target(df, target, event, date_field, True) if problem == "classification" and date_field else []
        segment_rows = self._group_target(df, target, event, segment_field, False) if problem == "classification" and segment_field else []
        if segment_field and segment_rows:
            total = sum(row["count"] for row in segment_rows)
            for row in segment_rows:
                row["population_rate"] = row["count"] / max(total, 1)
                row["small_sample"] = row["count"] < 30 or row["events"] < 5
        return {
            "date_field": date_field,
            "segment_field": segment_field,
            "time_profile": time_rows,
            "segment_profile": segment_rows,
            "time_scope": "development_population" if time_rows else "unavailable",
            "segment_scope": "development_population" if segment_rows else "unavailable",
            "final_holdout_accessed": False,
            "out_of_time_suggestion": self._oot_suggestion(time_rows),
        }

    def _oot_suggestion(self, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(rows) < 6:
            return None
        cutoff = max(1, int(len(rows) * 0.8))
        return {
            "reference_periods": [row["group"] for row in rows[:cutoff]],
            "comparison_periods": [row["group"] for row in rows[cutoff:]],
            "rationale": "The latest 20 percent of observed periods can be reserved as an out-of-time comparison after reviewer confirmation.",
        }

    def _findings(self, df, target, y, problem, event, request) -> dict[str, Any]:
        overview = self._overview(df, target, y, problem, event, request)
        target_profile = overview["target_profile"]
        findings: list[dict[str, Any]] = []
        if problem == "classification" and target_profile.get("rare_event"):
            findings.append({"category": "Rare event", "severity": "warning", "finding": "The observed event rate is below 1 percent.", "recommended_action": "Use stratified validation and ranking, lift, calibration, and threshold metrics instead of accuracy alone."})
        if overview["data_integrity"]["duplicate_rows"]:
            findings.append({"category": "Data integrity", "severity": "warning", "finding": f"{overview['data_integrity']['duplicate_rows']:,} duplicate rows were detected.", "recommended_action": "Confirm whether duplicate records represent repeated observations or ingestion duplication."})
        if overview["data_integrity"]["leakage_candidates"]:
            findings.append({"category": "Leakage", "severity": "warning", "finding": f"{len(overview['data_integrity']['leakage_candidates'])} fields have names associated with targets, outcomes, or split metadata.", "recommended_action": "Review the evidence before excluding any field from the governed predictor set."})
        if overview["headline"]["missing_cells"]:
            findings.append({"category": "Missingness", "severity": "review", "finding": f"{overview['headline']['missing_cells']:,} missing cells are present.", "recommended_action": "Review informative missingness and select treatment on the Missing Values step."})
        if not findings:
            findings.append({"category": "Readiness", "severity": "info", "finding": "No headline target, duplicate, leakage-name, or missingness condition requires immediate escalation.", "recommended_action": "Review predictor, relationship, and stability tabs before completing EDA."})
        return {
            "findings": findings,
            "carry_forward": {
                "outliers": [item for item in findings if item["category"] in {"Data integrity"}],
                "missing_values": [item for item in findings if item["category"] == "Missingness"],
                "feature_engineering": [item for item in findings if item["category"] == "Leakage"],
                "balance_split": [item for item in findings if item["category"] == "Rare event"],
            },
        }


eda_workspace_service = EDAWorkspaceService()
