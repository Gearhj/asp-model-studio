from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping

import pandas as pd

from ..core.dataset_store import DATASTORE


BUREAU_SPECIAL_VALUES = (-9.0, -8.0, -7.0)
_SPLIT_FIELD = re.compile(
    r"(^|_)(split|fold|partition|sample_role|dataset_role)($|_)",
    re.IGNORECASE,
)
_SYSTEM_FIELD = re.compile(
    r"(^|_)(row_id|record_id|load_id|batch_id|ingestion_id)($|_)",
    re.IGNORECASE,
)


class PredictorAuthorizationIntegrityError(ValueError):
    """The durable Data Acquisition authorization failed exact verification."""


def _stable_contract_id(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:20]}"


def verify_durable_predictor_authorization(
    record: Mapping[str, Any] | None,
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
) -> dict[str, Any]:
    """Verify the exact production Data Acquisition authorization checksum.

    The repository query supplies exact identity scoping, but callers must
    still prove that the stored row, embedded manifest, target contract,
    authorization identifier, and artifact-hash suffix agree. This function
    intentionally has no first/latest/legacy fallback.
    """

    if not isinstance(record, Mapping):
        raise PredictorAuthorizationIntegrityError(
            "The exact predictor authorization record is unavailable."
        )
    manifest = record.get("manifest_json")
    if not isinstance(manifest, dict):
        raise PredictorAuthorizationIntegrityError(
            "The predictor authorization manifest is unavailable."
        )
    expected_identity = {
        "project_id": str(project_id).strip(),
        "dataset_id": str(dataset_id).strip(),
        "dataset_version_id": str(dataset_version_id).strip(),
    }
    for field, expected in expected_identity.items():
        if str(record.get(field) or "").strip() != expected:
            raise PredictorAuthorizationIntegrityError(
                "The predictor authorization row has a stale identity binding."
            )
        if str(manifest.get(field) or "").strip() != expected:
            raise PredictorAuthorizationIntegrityError(
                "The predictor authorization manifest has a stale identity binding."
            )
    if str(record.get("status") or "").casefold() != "current":
        raise PredictorAuthorizationIntegrityError(
            "The predictor authorization is not current."
        )

    target = str(manifest.get("target") or "").strip()
    if not target or str(record.get("target_column") or "").strip() != target:
        raise PredictorAuthorizationIntegrityError(
            "The predictor authorization target binding is stale."
        )
    target_payload = {
        **expected_identity,
        "target": target,
        "positive_value": manifest.get("positive_value"),
        "negative_value": manifest.get("negative_value"),
    }
    expected_target_contract_id = _stable_contract_id(
        "target-contract", target_payload
    )
    if any(
        str(value or "").strip() != expected_target_contract_id
        for value in (
            record.get("target_contract_id"),
            manifest.get("target_contract_id"),
        )
    ):
        raise PredictorAuthorizationIntegrityError(
            "The predictor authorization target-contract checksum is stale."
        )

    manifest_base = {
        **target_payload,
        "target_contract_id": expected_target_contract_id,
        "authorized_predictors": sorted(
            str(value)
            for value in manifest.get("authorized_predictors", [])
        ),
        "excluded_predictors": dict(
            manifest.get("excluded_predictors") or {}
        ),
        "selected_predictors": sorted(
            str(value) for value in manifest.get("selected_predictors", [])
        ),
        "target_source_excluded": sorted(
            str(value)
            for value in manifest.get("target_source_excluded", [])
        ),
        "target_source_detection_scope": str(
            manifest.get("target_source_detection_scope") or ""
        ),
        "source": str(manifest.get("source") or ""),
    }
    # New manifests bind the durable deterministic-source evidence into the
    # authorization checksum. Preserve verification compatibility for earlier
    # manifests that predate the evidence field.
    if "target_source_fields" in manifest:
        manifest_base["target_source_fields"] = list(
            manifest.get("target_source_fields") or []
        )
    expected_authorization_id = _stable_contract_id(
        "predictor-auth", manifest_base
    )
    identifiers = (
        record.get("predictor_authorization_id"),
        manifest.get("predictor_authorization_id"),
        manifest.get("manifest_version"),
    )
    if any(
        str(value or "").strip() != expected_authorization_id
        for value in identifiers
    ):
        raise PredictorAuthorizationIntegrityError(
            "The predictor authorization content checksum is stale."
        )
    evidence_ref = str(manifest.get("target_source_evidence_ref") or "").strip()
    if evidence_ref and evidence_ref != expected_authorization_id:
        raise PredictorAuthorizationIntegrityError(
            "The predictor authorization target-source evidence reference is stale."
        )
    expected_artifact_hash = expected_authorization_id.removeprefix(
        "predictor-auth-"
    )
    if any(
        str(value or "").strip() != expected_artifact_hash
        for value in (
            record.get("artifact_hash"),
            manifest.get("artifact_hash"),
        )
    ):
        raise PredictorAuthorizationIntegrityError(
            "The predictor authorization artifact hash is stale."
        )
    return manifest


def _string_set(values: Any) -> set[str]:
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def _evidence_scalar(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def explicit_predictor_exclusions(
    *, include_prior_authorization: bool = True
) -> set[str]:
    """Return predictor exclusions already established by upstream governance."""

    exclusions: set[str] = set()
    for key in (
        "target_source_excluded",
        "target_source_exclusions",
        "prohibited_columns",
        "system_columns",
        "split_columns",
    ):
        exclusions.update(_string_set(DATASTORE.meta.get(key)))

    authorization = DATASTORE.meta.get("predictor_authorization")
    if include_prior_authorization and isinstance(authorization, dict):
        exclusions.update(_string_set(authorization.get("target_source_excluded")))
        exclusions.update(_string_set(authorization.get("excluded_predictors")))
    return exclusions


def detect_deterministic_target_sources(
    frame: pd.DataFrame,
    target: str | None,
    candidates: Iterable[str] | None = None,
) -> set[str]:
    """Detect low-cardinality columns that deterministically reveal the target.

    This is the pandas-side equivalent of the governed EDA authorization check.
    It deliberately relies on the observed mapping rather than a dataset-specific
    column name.  A candidate is excluded when every populated source value maps
    to exactly one populated target value.
    """

    if not target or target not in frame.columns:
        return set()
    target_values = frame[target]
    if int(target_values.dropna().nunique()) < 2:
        return set()

    names = list(candidates) if candidates is not None else [str(column) for column in frame.columns]
    found: set[str] = set()
    for name in names:
        if name == target or name not in frame.columns:
            continue
        source = frame[name]
        distinct = int(source.dropna().nunique())
        if distinct < 2 or distinct > 50:
            continue
        paired = pd.DataFrame({"source": source, "target": target_values}).dropna()
        if paired.empty or len(paired) / max(len(frame), 1) < 0.8:
            continue
        mapping_width = paired.groupby("source", dropna=True)["target"].nunique(dropna=True)
        if not mapping_width.empty and int(mapping_width.max()) == 1:
            found.add(name)
    return found


def deterministic_target_source_fields(
    frame: pd.DataFrame,
    target: str | None,
    fields: Iterable[str],
    *,
    detection_scope: str,
) -> list[dict[str, Any]]:
    """Build durable, reviewable evidence for deterministic target sources."""

    if not target or target not in frame.columns:
        return []
    records: list[dict[str, Any]] = []
    for field in sorted({str(value) for value in fields}):
        if field not in frame.columns or field == target:
            continue
        paired = pd.DataFrame(
            {"source": frame[field], "target": frame[target]}
        ).dropna()
        grouped = (
            paired.groupby(["source", "target"], dropna=False)
            .size()
            .reset_index(name="rowCount")
        )
        mapping = []
        for row in grouped.itertuples(index=False):
            source_value = _evidence_scalar(row.source)
            target_value = _evidence_scalar(row.target)
            mapping.append(
                {
                    "sourceValue": source_value,
                    "targetValue": target_value,
                    "rowCount": int(row.rowCount),
                }
            )
        records.append(
            {
                "field": field,
                "target": str(target),
                "relationship": "deterministic_target_source",
                "detection_scope": detection_scope,
                "registered_rows": int(len(frame)),
                "compared_rows": int(len(paired)),
                "coverage_rate": float(len(paired) / max(len(frame), 1)),
                "source_distinct_count": int(paired["source"].nunique()),
                "target_distinct_count": int(paired["target"].nunique()),
                "mapping": mapping,
            }
        )
    return records


def governed_predictor_authorization(
    frame: pd.DataFrame,
    target: str | None = None,
    selected_columns: Iterable[str] | None = None,
    *,
    detect_target_sources: bool = True,
    include_prior_authorization: bool = True,
) -> dict[str, Any]:
    """Resolve the one authoritative predictor set used by preparation stages.

    Target-source discovery is permitted while Data Acquisition still owns the
    unpartitioned registered population. The resulting evidence is persisted in
    the immutable authorization manifest; downstream EDA consumes that lineage
    and never re-discovers against a sealed holdout target.
    """

    resolved_target = str(target or DATASTORE.target or "") or None
    selected = [
        str(name)
        for name in (
            list(selected_columns)
            if selected_columns is not None
            else DATASTORE.get_selected_columns()
        )
        if str(name) in frame.columns and str(name) != resolved_target
    ]
    selected_set = set(selected)
    candidate_names = selected or [
        str(column)
        for column in frame.columns
        if str(column) != resolved_target
    ]

    explicit = explicit_predictor_exclusions(
        include_prior_authorization=include_prior_authorization
    )
    deterministic = (
        detect_deterministic_target_sources(
            frame,
            resolved_target,
            [
                str(column)
                for column in frame.columns
                if str(column) != resolved_target
            ],
        )
        if detect_target_sources
        else set()
    )
    detection_scope = (
        "registered_population_pre_partition"
        if detect_target_sources
        else "not_performed"
    )
    target_source_fields = deterministic_target_source_fields(
        frame,
        resolved_target,
        deterministic,
        detection_scope=detection_scope,
    )
    excluded: dict[str, str] = {}
    # Record authoritative safety exclusions for the complete source schema,
    # not only the currently selected subset. Feature Engineering rewrites the
    # downstream selected-column list to include engineered outputs; an
    # unselected deterministic target source must retain its specific exclusion
    # reason instead of being downgraded to the generic "not selected" reason.
    for column in frame.columns:
        name = str(column)
        if name == resolved_target:
            continue
        if name in deterministic:
            excluded[name] = "Deterministic source of the modeling target"
        elif name in explicit:
            excluded[name] = "Excluded by the governed predictor authorization contract"
        elif _SPLIT_FIELD.search(name):
            excluded[name] = "Split or fold metadata cannot be used as a predictor"
        elif _SYSTEM_FIELD.search(name):
            excluded[name] = "System metadata cannot be used as a predictor"

    # When an upstream selection exists, every unselected source column remains
    # visible to authorization reporting but cannot silently re-enter a builder.
    if selected:
        for column in frame.columns:
            name = str(column)
            if name == resolved_target or name in selected_set or name in excluded:
                continue
            excluded[name] = "Not selected in the governed predictor manifest"

    authorized = [name for name in candidate_names if name not in excluded]
    return {
        "target": resolved_target,
        "authorized_predictors": authorized,
        "excluded_predictors": excluded,
        "target_source_excluded": sorted(deterministic),
        "target_source_fields": target_source_fields,
        "selected_predictors": selected,
        "target_source_detection_scope": detection_scope,
    }


def bureau_special_mask(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.isin(BUREAU_SPECIAL_VALUES)


def bureau_special_summary(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce")
    mask = bureau_special_mask(numeric)
    counts = {
        str(int(special)): int((numeric == special).sum())
        for special in BUREAU_SPECIAL_VALUES
        if int((numeric == special).sum()) > 0
    }
    count = int(mask.sum())
    return {
        "special_value_count": count,
        "special_value_rate": count / max(int(numeric.notna().sum()), 1),
        "special_values": counts,
    }
