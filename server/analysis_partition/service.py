from __future__ import annotations

import hashlib
import json
import math
import threading
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from ..persistence.repositories.analysis_partition_repository import (
    AnalysisPartitionConflictError,
    AnalysisPartitionRepository,
    AnalysisPartitionStateError,
)
from ..persistence.service import get_persistence_service
from .types import (
    ANALYSIS_PARTITION_CONTRADICTORY,
    ANALYSIS_PARTITION_DOCUMENTATION_PENDING,
    ANALYSIS_PARTITION_INTEGRITY_FAILED,
    ANALYSIS_PARTITION_REQUIRED,
    ANALYSIS_PARTITION_RESET_INVALIDATION_FAILED,
    ANALYSIS_PARTITION_PREVIEW_STALE,
    ANALYSIS_PARTITION_STALE,
    ANALYSIS_PARTITION_SUFFICIENCY_FAILED,
    ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED,
    DATASET_IDENTITY_UNAVAILABLE,
    PREDICTOR_AUTHORIZATION_REQUIRED,
    TARGET_CONTRACT_STALE,
    AnalysisPartitionConfirmRequest,
    AnalysisPartitionError,
    AnalysisPartitionPreviewRequest,
    AnalysisPartitionResetPreviewRequest,
)


_RESET_IMPACTS = [
    "Target-directed EDA evidence and EDA confirmation become stale.",
    "IV, WoE, monotonicity, VIF, and Auto-VIF evidence becomes stale.",
    "Accepted EDA findings and carry-forward decisions become stale.",
    "Outlier and missing-value treatment evidence derived from EDA becomes stale.",
    "Feature recommendations, feature manifests, and materializations become stale.",
    "Validation Designs and derived split artifacts must be recreated from the new partition.",
    "Training jobs, training runs, and candidate contracts become stale.",
    "Candidate decisions and Evaluation packages become stale.",
    "Interpretation evidence and promoted model versions become stale.",
    "Scoring runs derived from affected model versions become stale.",
    "Analysis Partition-owned MDD sections are superseded and downstream MDD sections become stale.",
    "The prior sealed holdout remains immutable for audit, but is superseded by new membership.",
]

_STALE_ARTIFACTS = [
    "eda",
    "iv_woe",
    "monotonicity",
    "vif_auto_vif",
    "eda_findings",
    "outlier_treatments",
    "missing_value_treatments",
    "feature_engineering",
    "validation_design",
    "training_candidates",
    "training_jobs",
    "training_runs",
    "candidate_contracts",
    "candidate_decisions",
    "evaluation",
    "interpretation",
    "model_promotion",
    "model_versions",
    "scoring_runs",
    "mdd_sections",
]

_SUFFICIENCY_POLICY_ID = "atlas.analysis_partition.supervised_default"
_SUFFICIENCY_POLICY_VERSION = "1.0"
_PARTITION_METHOD = "deterministic_random"
_CLASSIFICATION_MIN_CLASS_HARD = 2
_CLASSIFICATION_MIN_HOLDOUT_CLASS_RECOMMENDED = 30
_REGRESSION_MIN_HOLDOUT_HARD = 10
_REGRESSION_MIN_HOLDOUT_RECOMMENDED = 30


def _text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _bind_reset_preview_fingerprint(
    preview: Mapping[str, Any],
    current: Mapping[str, Any],
) -> Dict[str, Any]:
    """Bind one alternate design to the exact sealed authority it may replace."""

    candidate_fingerprint = _text(preview.get("preview_fingerprint"))
    current_partition_id = _text(current.get("analysis_partition_id"))
    current_revision = int(current.get("revision") or 0)
    bound_fingerprint = _stable_hash(
        {
            "contract": "analysis_partition_reset_preview_v1",
            "candidate_preview_fingerprint": candidate_fingerprint,
            "expected_current_partition_id": current_partition_id,
            "expected_current_revision": current_revision,
        }
    )
    return {
        **dict(preview),
        "candidate_preview_fingerprint": candidate_fingerprint,
        "preview_fingerprint": bound_fingerprint,
        "reset_preview": True,
        "expected_current_partition_id": current_partition_id,
        "expected_current_revision": current_revision,
    }


def _canonical_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float) and math.isnan(value):
        return "__missing__"
    if pd.isna(value):
        return "__missing__"
    return _stable_json(value)


def _actor_id(
    user: Mapping[str, Any] | str | None,
    *,
    allow_system: bool = False,
) -> str:
    if isinstance(user, str):
        actor = user.strip()
    else:
        actor = _text((user or {}).get("userId") or (user or {}).get("user_id"))
    if not actor and allow_system:
        return "atlas-system"
    if not actor:
        raise AnalysisPartitionError(
            ANALYSIS_PARTITION_REQUIRED,
            "An authenticated actor is required to confirm or reset an Analysis Partition.",
            recovery="Sign in and confirm the Analysis Partition again.",
            status_code=401,
        )
    return actor


def _record_identifiers(record: Mapping[str, Any] | None) -> Dict[str, Any]:
    source = record or {}
    return {
        key: source.get(key)
        for key in (
            "analysis_partition_id",
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "target_contract_id",
            "target_column",
            "predictor_authorization_id",
            "revision",
        )
        if source.get(key) not in (None, "")
    }


def _request_matches_record_contract(
    payload: Mapping[str, Any], record: Mapping[str, Any]
) -> bool:
    """Compare only non-secret, non-membership inputs to a sealed record.

    This intentionally does not inspect target values or regenerate a split.
    The preview fingerprint proves the target-aware preview; these comparisons
    prevent a caller from replaying that fingerprint alongside different
    visible configuration fields.
    """

    text_pairs = (
        ("project_id", "project_id"),
        ("dataset_id", "dataset_id"),
        ("dataset_version_id", "dataset_version_id"),
        ("target_contract_id", "target_contract_id"),
        ("target", "target_column"),
        ("predictor_authorization_id", "predictor_authorization_id"),
        ("problem_type", "problem_type"),
        ("partition_method", "partition_method"),
        ("stratification_policy", "stratification_policy"),
    )
    if any(
        _text(payload.get(request_key)) != _text(record.get(record_key))
        for request_key, record_key in text_pairs
    ):
        return False
    requested_field = (
        _text(payload.get("stratification_field"))
        if _text(payload.get("stratification_policy")) == "target"
        else ""
    )
    if requested_field != _text(record.get("stratification_field")):
        return False
    try:
        numeric_matches = (
            math.isclose(
                float(payload.get("development_share")),
                float(record.get("development_share")),
                abs_tol=1e-9,
            )
            and math.isclose(
                float(payload.get("holdout_share")),
                float(record.get("holdout_share")),
                abs_tol=1e-9,
            )
            and int(payload.get("random_seed")) == int(record.get("random_seed"))
        )
    except (TypeError, ValueError):
        return False
    return bool(
        numeric_matches
        and _canonical_scalar(payload.get("positive_value"))
        == _canonical_scalar(record.get("positive_value_json"))
        and _canonical_scalar(payload.get("negative_value"))
        == _canonical_scalar(record.get("negative_value_json"))
    )


def _assignment_payload(record: Mapping[str, Any]) -> Dict[str, Any]:
    assignments = record.get("row_assignments_json")
    if not isinstance(assignments, dict):
        assignments = {}
    return {
        "project_id": record.get("project_id"),
        "dataset_id": record.get("dataset_id"),
        "dataset_version_id": record.get("dataset_version_id"),
        "target_contract_id": record.get("target_contract_id"),
        "population_count": int(record.get("population_count") or 0),
        "development_positions": [
            int(item) for item in assignments.get("development_positions", [])
        ],
        "holdout_positions": [
            int(item) for item in assignments.get("holdout_positions", [])
        ],
        "development_target_fingerprint": assignments.get(
            "development_target_fingerprint"
        ),
        "holdout_target_fingerprint": assignments.get(
            "holdout_target_fingerprint"
        ),
    }


def _artifact_payload(
    record: Mapping[str, Any], *, legacy_rationale_binding: bool = False
) -> Dict[str, Any]:
    preview_fingerprint = _text(record.get("preview_fingerprint"))
    payload = {
        "lineage_contract": (
            "analysis_partition_v2" if preview_fingerprint else "analysis_partition_v1"
        ),
        "project_id": record.get("project_id"),
        "dataset_id": record.get("dataset_id"),
        "dataset_version_id": record.get("dataset_version_id"),
        "target_contract_id": record.get("target_contract_id"),
        "target_column": record.get("target_column"),
        "positive_value": record.get("positive_value_json"),
        "negative_value": record.get("negative_value_json"),
        # Predictor authorization is recorded as creation lineage, but it is
        # deliberately not part of membership identity. Predictor-only changes
        # must preserve the exact sealed row partition.
        "development_share": float(record.get("development_share") or 0.0),
        "holdout_share": float(record.get("holdout_share") or 0.0),
        "random_seed": int(record.get("random_seed") or 0),
        "stratification_policy": record.get("stratification_policy"),
        "stratification_field": record.get("stratification_field"),
        "population_count": int(record.get("population_count") or 0),
        "development_count": int(record.get("development_count") or 0),
        "holdout_count": int(record.get("holdout_count") or 0),
        "event_counts": record.get("event_counts_json"),
        "assignment_hash": record.get("assignment_hash"),
        "population_fingerprint": record.get("population_fingerprint"),
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
    }
    if preview_fingerprint:
        payload.update(
            {
                "problem_type": record.get("problem_type"),
                "partition_method": record.get("partition_method"),
                "preview_fingerprint": preview_fingerprint,
                "sufficiency": record.get("sufficiency_json"),
            }
        )
        # Membership identity and analyst documentation are deliberately
        # separate.  A wording-only rationale edit must not imply different
        # row membership.  Integrity validation retains a read-only fallback
        # for rows written by the short-lived v2 implementation that did bind
        # rationale into the artifact hash.
        if legacy_rationale_binding:
            payload["selection_rationale"] = record.get("selection_rationale")
    return payload


def _structural_fingerprint(frame: pd.DataFrame) -> str:
    """Hash population size and row order without reading any row values."""

    try:
        index_series = frame.index.to_series(index=frame.index)
        hashed = pd.util.hash_pandas_object(index_series, index=True)
        payload = hashed.to_numpy(dtype=np.uint64, copy=False).tobytes()
    except (TypeError, ValueError):
        fallback = [_json_default(index) for index in frame.index.tolist()]
        payload = _stable_json(fallback).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(str(len(frame)).encode("ascii"))
    digest.update(b"\0")
    digest.update(payload)
    return digest.hexdigest()


def _target_membership_fingerprint(
    frame: pd.DataFrame,
    target: str,
    positions: Sequence[int],
) -> str:
    """Hash target/index for only the explicitly supplied partition rows."""

    subset = frame.iloc[list(positions)].loc[:, [target]]
    try:
        hashed = pd.util.hash_pandas_object(subset, index=True)
        payload = hashed.to_numpy(dtype=np.uint64, copy=False).tobytes()
    except (TypeError, ValueError):
        fallback = [
            {"index": _json_default(index), "target": _canonical_scalar(value)}
            for index, value in subset[target].items()
        ]
        payload = _stable_json(fallback).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(str(len(positions)).encode("ascii"))
    digest.update(b"\0")
    digest.update(target.encode("utf-8"))
    digest.update(b"\0")
    digest.update(payload)
    return digest.hexdigest()


def _target_population_fingerprint(frame: pd.DataFrame, target: str) -> str:
    return _target_membership_fingerprint(
        frame, target, list(range(int(len(frame))))
    )


def _numeric_summary(series: pd.Series) -> Dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    values = values.where(np.isfinite(values), np.nan).dropna()
    if values.empty:
        return {
            "count": 0,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "standard_deviation": None,
            "quantiles": {},
        }
    quantiles = values.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    return {
        "count": int(len(values)),
        "minimum": float(values.min()),
        "maximum": float(values.max()),
        "mean": float(values.mean()),
        "standard_deviation": float(values.std(ddof=0)),
        "quantiles": {
            "p01": float(quantiles.loc[0.01]),
            "p05": float(quantiles.loc[0.05]),
            "p25": float(quantiles.loc[0.25]),
            "p50": float(quantiles.loc[0.5]),
            "p75": float(quantiles.loc[0.75]),
            "p95": float(quantiles.loc[0.95]),
            "p99": float(quantiles.loc[0.99]),
        },
    }


def _counts(
    target: pd.Series,
    positions: Sequence[int],
    positive_value: Any,
    negative_value: Any,
) -> Dict[str, int]:
    positive = _canonical_scalar(positive_value)
    negative = _canonical_scalar(negative_value)
    result = {"event": 0, "non_event": 0, "other": 0, "missing": 0}
    values = target.iloc[list(positions)]
    for value in values.tolist():
        canonical = _canonical_scalar(value)
        if canonical == "__missing__":
            result["missing"] += 1
        elif canonical == positive:
            result["event"] += 1
        elif canonical == negative:
            result["non_event"] += 1
        else:
            result["other"] += 1
    return result


def _store_meta(store: Any) -> Dict[str, Any]:
    meta = getattr(store, "meta", None)
    return meta if isinstance(meta, dict) else {}


def _authorization_contract(store: Any) -> Dict[str, Any]:
    meta = _store_meta(store)
    for key in ("predictor_authorization", "predictor_authorization_manifest"):
        candidate = meta.get(key)
        if isinstance(candidate, dict):
            return dict(candidate)
    flat_id = _text(meta.get("predictor_authorization_id"))
    return {"predictor_authorization_id": flat_id} if flat_id else {}


def _authorization_id(contract: Mapping[str, Any]) -> str:
    return _text(
        contract.get("predictor_authorization_id")
        or contract.get("authorization_id")
        or contract.get("manifest_id")
        or contract.get("manifest_version")
    )


def _base_frame(store: Any, *, raw_only: bool = False) -> pd.DataFrame:
    frame = getattr(store, "raw_df", None) if raw_only else None
    if frame is None and not raw_only:
        getter = getattr(store, "get_base_df", None)
        frame = getter() if callable(getter) else getattr(store, "processed_df", None)
        if frame is None:
            frame = getattr(store, "raw_df", None)
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise AnalysisPartitionError(
            DATASET_IDENTITY_UNAVAILABLE,
            "The exact registered dataset version is not loaded in the governed project workspace.",
            recovery="Reopen the exact registered Dataset Library version, then return to Data Acquisition.",
        )
    return frame


def _authorized_predictors(store: Any, requested: Iterable[str] | None) -> List[str]:
    if requested is None:
        getter = getattr(store, "get_selected_columns", None)
        requested = getter() if callable(getter) else []
    result: List[str] = []
    seen: set[str] = set()
    target = _text(getattr(store, "target", ""))
    for value in requested or []:
        name = _text(value)
        if name and name != target and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _external_invalidation_inventory(context: Any) -> List[Dict[str, Any]]:
    if context is None:
        return []
    value = (
        context.get("inventory")
        if isinstance(context, Mapping)
        else getattr(context, "inventory", None)
    )
    return [dict(item) for item in value or [] if isinstance(item, Mapping)]


def _compensate_external_invalidation(context: Any) -> None:
    if context is None:
        return
    callback = (
        context.get("compensate")
        if isinstance(context, Mapping)
        else getattr(context, "compensate", None)
    )
    if callable(callback):
        callback()


class AnalysisPartitionService:
    _project_locks_guard = threading.Lock()
    _project_locks: Dict[str, threading.RLock] = {}

    def __init__(
        self,
        repository: AnalysisPartitionRepository | None = None,
    ) -> None:
        self._repository = repository

    @property
    def repository(self) -> AnalysisPartitionRepository:
        if self._repository is not None:
            return self._repository
        return get_persistence_service().analysis_partitions

    @classmethod
    def _project_lock(cls, project_id: str) -> threading.RLock:
        key = _text(project_id)
        with cls._project_locks_guard:
            return cls._project_locks.setdefault(key, threading.RLock())

    @staticmethod
    def impact_for_reset(record: Mapping[str, Any] | None = None) -> List[str]:
        return list(_RESET_IMPACTS)

    @staticmethod
    def safe_record(record: Mapping[str, Any]) -> Dict[str, Any]:
        event_counts = record.get("event_counts_json")
        if not isinstance(event_counts, dict):
            event_counts = {}
        # Once membership is sealed, operational responses may report the
        # development-population distribution, but must not publish target
        # aggregates for the final holdout (or the full population, from
        # which holdout aggregates can be derived).  The complete decision
        # evidence remains durable in the creation preview/evidence/MDD.
        public_event_counts = {
            "development": dict(event_counts.get("development") or {})
        }
        sufficiency = record.get("sufficiency_json")
        if not isinstance(sufficiency, dict):
            sufficiency = {}
        public_sufficiency = {
            key: sufficiency.get(key)
            for key in (
                "policy_id",
                "policy_version",
                "overall_status",
            )
            if sufficiency.get(key) is not None
        }
        preview_fingerprint = _text(record.get("preview_fingerprint"))
        verified_problem_type = (
            _text(record.get("problem_type")) or None
            if preview_fingerprint
            else None
        )
        lineage_contract = (
            "analysis_partition_v2"
            if preview_fingerprint
            else "analysis_partition_v1"
        )
        return {
            "analysis_partition_id": record.get("analysis_partition_id"),
            "project_id": record.get("project_id"),
            "dataset_id": record.get("dataset_id"),
            "dataset_version_id": record.get("dataset_version_id"),
            "target_contract_id": record.get("target_contract_id"),
            "target": record.get("target_column"),
            "positive_value": record.get("positive_value_json"),
            "negative_value": record.get("negative_value_json"),
            "predictor_authorization_id": record.get(
                "predictor_authorization_id"
            ),
            "current_predictor_authorization_id": record.get(
                "current_predictor_authorization_id"
            )
            or record.get("predictor_authorization_id"),
            "predictor_authorization_lineage_status": record.get(
                "predictor_authorization_lineage_status"
            )
            or "current",
            "problem_type": verified_problem_type,
            "problem_type_status": (
                "verified" if verified_problem_type else "legacy_unverified"
            ),
            "lineage_contract": lineage_contract,
            "compatibility_status": (
                "native_v2_strict"
                if preview_fingerprint
                else "legacy_v1_integrity_verification_required"
            ),
            "partition_method": record.get("partition_method")
            or _PARTITION_METHOD,
            "selection_rationale": record.get("selection_rationale") or "",
            "preview_fingerprint": preview_fingerprint,
            "sufficiency": public_sufficiency,
            "development_partition_id": record.get("development_partition_id"),
            "sealed_holdout_partition_id": record.get(
                "sealed_holdout_partition_id"
            ),
            "development_share": record.get("development_share"),
            "holdout_share": record.get("holdout_share"),
            "random_seed": record.get("random_seed"),
            "stratification_policy": record.get("stratification_policy"),
            "stratification_field": record.get("stratification_field"),
            "population_count": record.get("population_count"),
            "development_count": record.get("development_count"),
            "holdout_count": record.get("holdout_count"),
            "event_counts": public_event_counts,
            "status": record.get("status"),
            "revision": record.get("revision"),
            "artifact_hash": record.get("artifact_hash"),
            "assignment_hash": record.get("assignment_hash"),
            "holdout_status": record.get("final_holdout_status") or "sealed",
            "final_holdout_status": record.get("final_holdout_status") or "sealed",
            "holdout_isolation_status": record.get("holdout_isolation_status"),
            "created_by": record.get("created_by"),
            "created_at": record.get("created_at"),
            "sealed_at": record.get("sealed_at"),
            "updated_at": record.get("updated_at"),
            "stale_reason": record.get("stale_reason"),
            "evidence_status": record.get("evidence_status") or "pending",
            "evidence_ref": record.get("evidence_ref"),
            "mdd_status": record.get("mdd_status") or "pending",
            "mdd_ref": record.get("mdd_ref"),
        }

    @classmethod
    def publish_safe(cls, store: Any, record: Mapping[str, Any]) -> Dict[str, Any]:
        safe = cls.safe_record(record)
        meta = _store_meta(store)
        meta["analysis_partition"] = safe
        meta["analysis_partition_id"] = safe.get("analysis_partition_id")
        meta["analysis_partition_status"] = safe.get("status")
        return safe

    @staticmethod
    def _validate_integrity(record: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            population_count = int(record.get("population_count") or 0)
            development_count = int(record.get("development_count") or 0)
            holdout_count = int(record.get("holdout_count") or 0)
            assignments = record.get("row_assignments_json")
            if not isinstance(assignments, dict):
                raise ValueError("row assignments are missing")
            development = [
                int(item) for item in assignments.get("development_positions", [])
            ]
            holdout = [
                int(item) for item in assignments.get("holdout_positions", [])
            ]
            if population_count <= 0 or development_count <= 0 or holdout_count <= 0:
                raise ValueError("partition counts must be positive")
            if development_count != len(development) or holdout_count != len(holdout):
                raise ValueError("stored counts do not match row assignments")
            if development_count + holdout_count != population_count:
                raise ValueError("development and holdout do not cover the population")
            if len(set(development)) != len(development) or len(set(holdout)) != len(holdout):
                raise ValueError("row assignments contain duplicates")
            if set(development).intersection(holdout):
                raise ValueError("development and holdout assignments overlap")
            if set(development).union(holdout) != set(range(population_count)):
                raise ValueError("row assignments are not an exact population partition")
            if not _text(record.get("population_fingerprint")):
                raise ValueError("population fingerprint is missing")
            expected_assignment_hash = _stable_hash(_assignment_payload(record))
            if expected_assignment_hash != _text(record.get("assignment_hash")):
                raise ValueError("assignment checksum does not match")
            expected_artifact_hash = _stable_hash(_artifact_payload(record))
            if expected_artifact_hash != _text(record.get("artifact_hash")):
                legacy_artifact_hash = _stable_hash(
                    _artifact_payload(record, legacy_rationale_binding=True)
                )
                if legacy_artifact_hash != _text(record.get("artifact_hash")):
                    raise ValueError("artifact checksum does not match")
            if _text(record.get("final_holdout_status")) != "sealed":
                raise ValueError("final holdout is not sealed")
            if _text(record.get("holdout_isolation_status")) != "verified":
                raise ValueError("holdout isolation is not verified")
            return {
                **dict(record),
                "target": record.get("target_column"),
                "positive_value": record.get("positive_value_json"),
                "negative_value": record.get("negative_value_json"),
                "holdout_status": record.get("final_holdout_status"),
                "event_counts": record.get("event_counts_json"),
            }
        except (TypeError, ValueError) as exc:
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_INTEGRITY_FAILED,
                f"The durable Analysis Partition failed checksum validation: {exc}.",
                recovery="Do not use this partition. Review durable integrity evidence and explicitly create a governed replacement.",
                stale_artifacts=_STALE_ARTIFACTS,
                identifiers=_record_identifiers(record),
            ) from exc

    @classmethod
    def target_authority_compatibility(
        cls,
        record: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Resolve target semantics from an integrity-verified sealed record.

        Native v2 rows use their explicitly previewed problem type. Historical
        v1 rows predate that field, so the migration's database default is
        never treated as authority. A v1 classification contract is
        recoverable only from two present, distinct class labels; a v1
        regression contract is recoverable only from two absent labels and an
        explicit ``none`` stratification policy. Every other legacy shape is
        ambiguous and fails closed.
        """

        governed = cls._validate_integrity(record)
        target_contract_id = _text(governed.get("target_contract_id"))
        target = _text(governed.get("target_column"))
        predictor_authorization_id = _text(
            governed.get("predictor_authorization_id")
        )
        identifiers = _record_identifiers(governed)
        if not target_contract_id or not target or not predictor_authorization_id:
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED,
                "The sealed Analysis Partition does not contain complete target and predictor-authority lineage.",
                recovery="Restore the exact governed target and predictor-authorization contracts before continuing.",
                identifiers=identifiers,
            )

        positive_value = governed.get("positive_value_json")
        negative_value = governed.get("negative_value_json")
        preview_fingerprint = _text(governed.get("preview_fingerprint"))
        if preview_fingerprint:
            problem_type = _text(governed.get("problem_type")).lower()
            contract_invalid = (
                problem_type not in {"classification", "regression"}
                or (
                    problem_type == "classification"
                    and (
                        positive_value is None
                        or negative_value is None
                        or _canonical_scalar(positive_value)
                        == _canonical_scalar(negative_value)
                    )
                )
                or (
                    problem_type == "regression"
                    and (
                        positive_value is not None
                        or negative_value is not None
                    )
                )
            )
            if contract_invalid:
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED,
                    "The native sealed Analysis Partition has an incomplete or internally inconsistent target contract.",
                    recovery="Return to Data Acquisition and explicitly reset and confirm the target and Analysis Partition.",
                    identifiers=identifiers,
                )
            return {
                "target_contract_id": target_contract_id,
                "target": target,
                "problem_type": problem_type,
                "event_value": positive_value,
                "non_event_value": negative_value,
                "source": "sealed_analysis_partition",
                "compatibility_status": "native_v2_strict",
                "lineage_contract": "analysis_partition_v2",
                "target_membership_fingerprint_status": "required_and_verified",
            }

        labels_present = positive_value is not None and negative_value is not None
        labels_absent = positive_value is None and negative_value is None
        labels_distinct = labels_present and (
            _canonical_scalar(positive_value)
            != _canonical_scalar(negative_value)
        )
        stratification_policy = _text(
            governed.get("stratification_policy")
        ).lower()
        if labels_distinct:
            problem_type = "classification"
        elif labels_absent and stratification_policy == "none":
            problem_type = "regression"
        else:
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED,
                "The legacy Analysis Partition target mapping is ambiguous and cannot be verified safely.",
                recovery=(
                    "Return to Data Acquisition and explicitly reset and confirm "
                    "a native Analysis Partition. No migration default or partial "
                    "legacy target mapping was used."
                ),
                identifiers={
                    **identifiers,
                    "compatibility_status": "legacy_v1_unverifiable",
                },
            )
        return {
            "target_contract_id": target_contract_id,
            "target": target,
            "problem_type": problem_type,
            "event_value": positive_value,
            "non_event_value": negative_value,
            "source": "verified_legacy_analysis_partition",
            "compatibility_status": "verified_legacy_v1",
            "lineage_contract": "analysis_partition_v1",
            "target_membership_fingerprint_status": "legacy_not_recorded",
        }

    def _build_preview(
        self,
        store: Any,
        request: AnalysisPartitionPreviewRequest | AnalysisPartitionConfirmRequest | Mapping[str, Any],
        *,
        require_explicit_contracts: bool,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        payload = request.model_dump() if hasattr(request, "model_dump") else dict(request)
        meta = _store_meta(store)
        authorization = _authorization_contract(store)
        loaded_authorization_id = _authorization_id(authorization)
        loaded_target_contract_id = _text(
            authorization.get("target_contract_id") or meta.get("target_contract_id")
        )
        requested_authorization_id = _text(payload.get("predictor_authorization_id"))
        requested_target_contract_id = _text(payload.get("target_contract_id"))
        identifiers = {
            "project_id": _text(payload.get("project_id")),
            "dataset_id": _text(payload.get("dataset_id")),
            "dataset_version_id": _text(payload.get("dataset_version_id")),
            "target_contract_id": requested_target_contract_id
            or loaded_target_contract_id,
            "target": _text(payload.get("target")),
            "predictor_authorization_id": requested_authorization_id
            or loaded_authorization_id,
        }
        if not all(identifiers.values()):
            raise AnalysisPartitionError(
                DATASET_IDENTITY_UNAVAILABLE,
                "The exact dataset, target, and current Data Acquisition contracts are required for an Analysis Partition preview.",
                recovery="Save the target and predictor inventory, then preview the partition again.",
                identifiers=identifiers,
            )
        if require_explicit_contracts and (
            not requested_target_contract_id or not requested_authorization_id
        ):
            raise AnalysisPartitionError(
                DATASET_IDENTITY_UNAVAILABLE,
                "Durable confirmation requires explicit target-contract and predictor-authorization IDs.",
                recovery="Save Data Acquisition, then create and seal the exact previewed partition.",
                identifiers=identifiers,
            )
        if requested_authorization_id and requested_authorization_id != loaded_authorization_id:
            raise AnalysisPartitionError(
                PREDICTOR_AUTHORIZATION_REQUIRED,
                "The requested predictor authorization is not the current Data Acquisition authority.",
                recovery="Refresh the predictor inventory and preview the current contract.",
                identifiers={
                    **identifiers,
                    "loaded_predictor_authorization_id": loaded_authorization_id,
                },
            )
        if requested_target_contract_id and requested_target_contract_id != loaded_target_contract_id:
            raise AnalysisPartitionError(
                TARGET_CONTRACT_STALE,
                "The requested target contract is not the current Data Acquisition authority.",
                recovery="Refresh the target setup and preview the current contract.",
                identifiers={
                    **identifiers,
                    "loaded_target_contract_id": loaded_target_contract_id,
                },
            )

        store_identity = {
            "project_id": _text(meta.get("project_id")),
            "dataset_id": _text(meta.get("dataset_id")),
            "dataset_version_id": _text(meta.get("dataset_version_id")),
        }
        for key in ("dataset_id", "dataset_version_id"):
            if not store_identity[key] or store_identity[key] != identifiers[key]:
                raise AnalysisPartitionError(
                    DATASET_IDENTITY_UNAVAILABLE,
                    "The loaded project workspace is not bound to the requested exact Dataset Library version.",
                    recovery="Activate and reopen the exact registered dataset version.",
                    identifiers={
                        **identifiers,
                        **{f"loaded_{name}": value for name, value in store_identity.items()},
                    },
                )
        if store_identity["project_id"] and store_identity["project_id"] != identifiers["project_id"]:
            raise AnalysisPartitionError(
                DATASET_IDENTITY_UNAVAILABLE,
                "The loaded dataset belongs to a different project scope.",
                recovery="Reopen the intended project before previewing its partition.",
                identifiers={
                    **identifiers,
                    "loaded_project_id": store_identity["project_id"],
                },
            )
        target = _text(getattr(store, "target", ""))
        if target != identifiers["target"]:
            raise AnalysisPartitionError(
                TARGET_CONTRACT_STALE,
                "The loaded target does not match the requested target contract.",
                recovery="Save the target setup in Data Acquisition.",
                identifiers={**identifiers, "loaded_target": target},
            )
        frame = _base_frame(store, raw_only=True)
        if target not in frame.columns:
            raise AnalysisPartitionError(
                TARGET_CONTRACT_STALE,
                "The target field is not present in the exact registered dataset version.",
                recovery="Correct the Data Acquisition target selection.",
                identifiers=identifiers,
            )

        development_share = float(payload.get("development_share", 0.8))
        holdout_share = float(payload.get("holdout_share", 0.2))
        supported = ((0.7, 0.3), (0.8, 0.2), (0.9, 0.1))
        if not any(
            math.isclose(development_share, left, abs_tol=1e-9)
            and math.isclose(holdout_share, right, abs_tol=1e-9)
            for left, right in supported
        ):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_CONTRADICTORY,
                "Analysis Partition ratio must be exactly 70/30, 80/20, or 90/10.",
                recovery="Choose one of the three governed standard ratios.",
                identifiers=identifiers,
            )
        method = _text(payload.get("partition_method") or _PARTITION_METHOD)
        if method != _PARTITION_METHOD:
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_CONTRADICTORY,
                "The requested Analysis Partition method is not supported.",
                recovery="Use deterministic_random.",
                identifiers=identifiers,
            )
        problem_type = _text(payload.get("problem_type") or "classification").lower()
        if problem_type not in {"classification", "regression"}:
            raise AnalysisPartitionError(
                TARGET_CONTRACT_STALE,
                "Analysis Partition preview supports classification or regression targets.",
                recovery="Correct the project problem type.",
                identifiers=identifiers,
            )

        population_count = int(len(frame))
        positions = np.arange(population_count, dtype=np.int64)
        policy = _text(payload.get("stratification_policy") or "target")
        stratification_field = (
            _text(payload.get("stratification_field")) or target
            if policy == "target"
            else ""
        )
        blockers: List[str] = []
        warnings: List[str] = []
        checks: List[Dict[str, Any]] = []

        authorized_names = [
            _text(value)
            for value in authorization.get("authorized_predictors", [])
            if _text(value)
        ]
        missing_authorized = sorted(
            {name for name in authorized_names if name not in frame.columns}
        )
        if missing_authorized:
            raise AnalysisPartitionError(
                PREDICTOR_AUTHORIZATION_REQUIRED,
                "The durable predictor authorization references fields that are absent from the exact registered dataset version.",
                recovery="Reconfirm Data Acquisition against the exact active Dataset Library version.",
                identifiers={
                    **identifiers,
                    "missing_authorized_predictors": missing_authorized,
                },
            )
        repeated_group_fields = [
            name
            for name in authorized_names
            if (
                "group" in name.lower()
                or name.lower().endswith("_id")
                or name.lower()
                in {"customerid", "accountid", "subjectid", "entityid"}
            )
            and 1 < int(frame[name].nunique(dropna=True)) < population_count
        ]
        if repeated_group_fields:
            warnings.append(
                "Repeated observation groups were detected in "
                + ", ".join(sorted(repeated_group_fields))
                + "; standard row-random assignment may place one group in both populations."
            )

        def add_check(
            check_id: str,
            *,
            minimum_count: int | float | None,
            actual_count: int | float | bool | None,
            status: str,
            rationale: str,
        ) -> None:
            checks.append(
                {
                    "check_id": check_id,
                    "minimum_count": minimum_count,
                    "actual_count": actual_count,
                    "status": status,
                    "rationale": rationale,
                }
            )

        positive_value = payload.get("positive_value")
        negative_value = payload.get("negative_value")
        if problem_type == "classification" and (
            positive_value is None
            or negative_value is None
            or _canonical_scalar(positive_value) == _canonical_scalar(negative_value)
        ):
            blockers.append("Classification requires distinct governed event and non-event values.")

        stratify_values: Sequence[Any] | None = None
        stratification_valid = True
        target_counts = _counts(
            frame[target], list(range(population_count)), positive_value, negative_value
        )
        if problem_type == "classification":
            mapping_valid = (
                target_counts["event"] > 0
                and target_counts["non_event"] > 0
                and target_counts["other"] == 0
                and target_counts["missing"] == 0
            )
            if not mapping_valid:
                blockers.append(
                    "The governed binary target mapping does not cover every eligible row."
                )
            if policy == "target":
                if stratification_field != target:
                    stratification_valid = False
                    blockers.append("Stratification may use only the governed target field.")
                frequencies = pd.Series(
                    [_canonical_scalar(value) for value in frame[target].tolist()]
                ).value_counts(dropna=False)
                if len(frequencies) != 2 or int(frequencies.min()) < 2:
                    stratification_valid = False
                    blockers.append(
                        "Target stratification requires two mapped classes with at least two rows each."
                    )
                if stratification_valid:
                    stratify_values = [
                        _canonical_scalar(value) for value in frame[target].tolist()
                    ]
            elif policy != "none":
                stratification_valid = False
                blockers.append("The stratification policy is not supported.")
        else:
            mapping_valid = True
            if policy != "none":
                stratification_valid = False
                blockers.append(
                    "Regression Analysis Partitions must use unstratified deterministic assignment."
                )

        split_error = ""
        try:
            development_positions, holdout_positions = train_test_split(
                positions,
                test_size=holdout_share,
                random_state=int(payload.get("random_seed", 42)),
                shuffle=True,
                stratify=stratify_values if stratification_valid else None,
            )
        except ValueError as exc:
            split_error = str(exc)
            blockers.append(f"The requested deterministic partition is infeasible: {exc}")
            rng = np.random.default_rng(int(payload.get("random_seed", 42)))
            shuffled = rng.permutation(positions)
            holdout_count = max(1, int(math.ceil(population_count * holdout_share)))
            holdout_positions = shuffled[:holdout_count]
            development_positions = shuffled[holdout_count:]
        development = sorted(int(item) for item in development_positions.tolist())
        holdout = sorted(int(item) for item in holdout_positions.tolist())
        assignments = {
            "development_positions": development,
            "holdout_positions": holdout,
            "development_target_fingerprint": _target_membership_fingerprint(
                frame, target, development
            ),
            "holdout_target_fingerprint": _target_membership_fingerprint(
                frame, target, holdout
            ),
        }
        event_counts = {
            "population": target_counts,
            "development": _counts(
                frame[target], development, positive_value, negative_value
            ),
            "holdout": _counts(frame[target], holdout, positive_value, negative_value),
        }
        add_check(
            "target_mapping_current",
            minimum_count=None,
            actual_count=mapping_valid,
            status="passed" if mapping_valid else "blocked",
            rationale="The current target contract covers the exact eligible population."
            if mapping_valid
            else "Unmapped, missing, or contradictory target values are present.",
        )
        add_check(
            "stratification_valid",
            minimum_count=None,
            actual_count=stratification_valid,
            status="passed" if stratification_valid else "blocked",
            rationale="The selected stratification policy is feasible."
            if stratification_valid
            else "The selected stratification policy is not feasible for this target.",
        )

        preview: Dict[str, Any] = {
            **identifiers,
            "problem_type": problem_type,
            "development_share": development_share,
            "holdout_share": holdout_share,
            "ratio_label": f"{int(round(development_share * 100))}/{int(round(holdout_share * 100))}",
            "random_seed": int(payload.get("random_seed", 42)),
            "stratification_policy": policy,
            "stratification_field": stratification_field if policy == "target" else None,
            "partition_method": method,
            "total_eligible_rows": population_count,
            "development_rows": len(development),
            "holdout_rows": len(holdout),
            "split_error": split_error or None,
        }

        if problem_type == "classification":
            development_counts = event_counts["development"]
            holdout_counts = event_counts["holdout"]
            for scope, counts_for_scope in (
                ("development", development_counts),
                ("holdout", holdout_counts),
            ):
                for kind in ("event", "non_event"):
                    actual = int(counts_for_scope[kind])
                    status = (
                        "passed"
                        if actual >= _CLASSIFICATION_MIN_CLASS_HARD
                        else "blocked"
                    )
                    if status == "blocked":
                        blockers.append(
                            f"{scope.title()} requires at least {_CLASSIFICATION_MIN_CLASS_HARD} {kind.replace('_', '-')} rows."
                        )
                    add_check(
                        f"{scope}_{kind}_count",
                        minimum_count=_CLASSIFICATION_MIN_CLASS_HARD,
                        actual_count=actual,
                        status=status,
                        rationale=(
                            "Both target classes must remain estimable in each governed population."
                        ),
                    )
            minimum_holdout_class = min(
                int(holdout_counts["event"]), int(holdout_counts["non_event"])
            )
            if minimum_holdout_class < _CLASSIFICATION_MIN_HOLDOUT_CLASS_RECOMMENDED:
                warnings.append(
                    "The final holdout has fewer than 30 rows in its smaller target class; final performance estimates may be imprecise."
                )
                advisory_status = "warning"
            else:
                advisory_status = "passed"
            add_check(
                "recommended_holdout_class_count",
                minimum_count=_CLASSIFICATION_MIN_HOLDOUT_CLASS_RECOMMENDED,
                actual_count=minimum_holdout_class,
                status=advisory_status,
                rationale="The default advisory threshold supports more stable class-specific final metrics.",
            )
            development_total = max(1, len(development))
            holdout_total = max(1, len(holdout))
            population_total = max(1, population_count)
            development_event_rate = development_counts["event"] / development_total
            holdout_event_rate = holdout_counts["event"] / holdout_total
            population_event_rate = target_counts["event"] / population_total
            preview.update(
                {
                    "development_event_count": int(development_counts["event"]),
                    "development_non_event_count": int(
                        development_counts["non_event"]
                    ),
                    "holdout_event_count": int(holdout_counts["event"]),
                    "holdout_non_event_count": int(holdout_counts["non_event"]),
                    "development_event_rate": float(development_event_rate),
                    "holdout_event_rate": float(holdout_event_rate),
                    "full_population_event_rate": float(population_event_rate),
                    "absolute_event_rate_difference": float(
                        abs(development_event_rate - holdout_event_rate)
                    ),
                    "minimum_event_count_status": (
                        "passed"
                        if min(
                            development_counts["event"], holdout_counts["event"]
                        )
                        >= _CLASSIFICATION_MIN_CLASS_HARD
                        else "blocked"
                    ),
                    "minimum_non_event_count_status": (
                        "passed"
                        if min(
                            development_counts["non_event"],
                            holdout_counts["non_event"],
                        )
                        >= _CLASSIFICATION_MIN_CLASS_HARD
                        else "blocked"
                    ),
                    "class_counts": event_counts,
                }
            )
        else:
            numeric = pd.to_numeric(frame[target], errors="coerce").astype(float)
            finite_mask = pd.Series(
                np.isfinite(numeric.to_numpy(dtype=float, copy=False)),
                index=numeric.index,
            )
            invalid_mask = numeric.isna() | ~finite_mask
            invalid_count = int(invalid_mask.sum())
            numeric = numeric.where(~invalid_mask, np.nan)
            if invalid_count:
                blockers.append(
                    f"Regression target contains {invalid_count} missing, non-numeric, or non-finite values."
                )
            full_summary = _numeric_summary(numeric)
            development_summary = _numeric_summary(numeric.iloc[development])
            holdout_summary = _numeric_summary(numeric.iloc[holdout])
            holdout_valid_rows = int(holdout_summary["count"])
            row_status = (
                "blocked"
                if holdout_valid_rows < _REGRESSION_MIN_HOLDOUT_HARD
                else "warning"
                if holdout_valid_rows < _REGRESSION_MIN_HOLDOUT_RECOMMENDED
                else "passed"
            )
            if row_status == "blocked":
                blockers.append(
                    f"Regression final holdout requires at least {_REGRESSION_MIN_HOLDOUT_HARD} valid target rows."
                )
            elif row_status == "warning":
                warnings.append(
                    "The regression final holdout has fewer than 30 valid target rows; error estimates may be imprecise."
                )
            add_check(
                "regression_holdout_rows",
                minimum_count=_REGRESSION_MIN_HOLDOUT_HARD,
                actual_count=holdout_valid_rows,
                status=row_status,
                rationale="The final evaluation population needs enough valid outcomes for stable error estimates.",
            )
            valid_values = numeric.dropna().astype(float)
            target_range_valid = bool(
                len(valid_values) >= 2 and float(valid_values.min()) < float(valid_values.max())
            )
            if not target_range_valid:
                blockers.append("Regression target has no usable range.")
            add_check(
                "regression_target_range",
                minimum_count=None,
                actual_count=target_range_valid,
                status="passed" if target_range_valid else "blocked",
                rationale="Regression validation requires a non-constant numeric target.",
            )
            band_count = 0
            represented_bands = 0
            band_coverage_rate = 0.0
            low_extreme = False
            high_extreme = False
            if target_range_valid:
                edges = np.unique(
                    valid_values.quantile([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]).to_numpy()
                )
                if len(edges) >= 2:
                    full_bands = pd.cut(
                        numeric,
                        bins=edges,
                        include_lowest=True,
                        duplicates="drop",
                    )
                    categories = list(full_bands.cat.categories)
                    holdout_bands = full_bands.iloc[holdout].dropna()
                    represented = set(holdout_bands.tolist())
                    band_count = len(categories)
                    represented_bands = len(represented)
                    band_coverage_rate = (
                        represented_bands / band_count if band_count else 0.0
                    )
                low_threshold = float(valid_values.quantile(0.05))
                high_threshold = float(valid_values.quantile(0.95))
                holdout_numeric = numeric.iloc[holdout].dropna().astype(float)
                low_extreme = bool((holdout_numeric <= low_threshold).any())
                high_extreme = bool((holdout_numeric >= high_threshold).any())
                if band_coverage_rate < 0.8:
                    warnings.append(
                        "The simulated holdout does not represent at least 80% of target quantile bands."
                    )
                if not (low_extreme and high_extreme):
                    warnings.append(
                        "The simulated holdout does not represent both target extremes."
                    )
            add_check(
                "regression_target_band_coverage",
                minimum_count=0.8,
                actual_count=band_coverage_rate,
                status="passed" if band_coverage_rate >= 0.8 else "warning",
                rationale="Quantile-band coverage checks representation across the target range.",
            )
            add_check(
                "regression_extreme_value_coverage",
                minimum_count=2,
                actual_count=int(low_extreme) + int(high_extreme),
                status="passed" if low_extreme and high_extreme else "warning",
                rationale="Both low and high target extremes should be represented in final evaluation.",
            )
            preview.update(
                {
                    "target_minimum": full_summary["minimum"],
                    "target_maximum": full_summary["maximum"],
                    "target_mean": full_summary["mean"],
                    "target_standard_deviation": full_summary[
                        "standard_deviation"
                    ],
                    "target_quantiles": full_summary["quantiles"],
                    "full_target_summary": full_summary,
                    "development_target_summary": development_summary,
                    "holdout_target_summary": holdout_summary,
                    "invalid_target_value_count": invalid_count,
                    "target_band_coverage": {
                        "total_bands": band_count,
                        "represented_bands": represented_bands,
                        "coverage_rate": float(band_coverage_rate),
                    },
                    "extreme_value_coverage": {
                        "low_extreme_represented": low_extreme,
                        "high_extreme_represented": high_extreme,
                        "status": "passed"
                        if low_extreme and high_extreme
                        else "warning",
                    },
                }
            )

        blockers = list(dict.fromkeys(blockers))
        warnings = list(dict.fromkeys(warnings))
        recommended_ratio = math.isclose(holdout_share, 0.2, abs_tol=1e-9)
        if blockers:
            recommendation_status = "blocked"
        elif warnings:
            recommendation_status = "acceptable_with_warning"
        elif recommended_ratio:
            recommendation_status = "recommended"
        else:
            recommendation_status = "acceptable"
        rationale_required = not recommended_ratio or bool(warnings)
        sufficiency = {
            "policy_id": _SUFFICIENCY_POLICY_ID,
            "policy_version": _SUFFICIENCY_POLICY_VERSION,
            "overall_status": recommendation_status,
            "checks": checks,
            "rationale": (
                "The split satisfies all blocking checks."
                if not blockers
                else "One or more governed sufficiency checks block sealing."
            ),
        }
        preview.update(
            {
                "recommended": recommendation_status == "recommended",
                "recommended_status": recommendation_status,
                "recommendation_status": recommendation_status,
                "rationale_required": rationale_required,
                "recommendation_rationale": (
                    "80/20 is the recommended general-purpose balance."
                    if recommended_ratio
                    else "This standard ratio is acceptable when its tradeoff is documented."
                ),
                "warnings": warnings,
                "blockers": blockers,
                "sufficiency": sufficiency,
                "sufficiency_policy_id": _SUFFICIENCY_POLICY_ID,
                "sufficiency_policy_version": _SUFFICIENCY_POLICY_VERSION,
            }
        )
        preview_fingerprint = _stable_hash(
            {
                "contract": "analysis_partition_preview_v1",
                "identity": {
                    key: identifiers[key]
                    for key in (
                        "project_id",
                        "dataset_id",
                        "dataset_version_id",
                        "target_contract_id",
                        "target",
                    )
                },
                "problem_type": problem_type,
                "positive_value": _canonical_scalar(positive_value),
                "negative_value": _canonical_scalar(negative_value),
                "development_share": development_share,
                "holdout_share": holdout_share,
                "random_seed": int(payload.get("random_seed", 42)),
                "stratification_policy": policy,
                "stratification_field": stratification_field,
                "partition_method": method,
                "population_fingerprint": _structural_fingerprint(frame),
                "target_population_fingerprint": _target_population_fingerprint(
                    frame, target
                ),
                "assignment": assignments,
                "sufficiency": sufficiency,
                "recommendation_status": recommendation_status,
                "warnings": warnings,
                "blockers": blockers,
            }
        )
        preview["preview_fingerprint"] = preview_fingerprint
        record: Dict[str, Any] = {
            "project_id": identifiers["project_id"],
            "dataset_id": identifiers["dataset_id"],
            "dataset_version_id": identifiers["dataset_version_id"],
            "target_contract_id": identifiers["target_contract_id"],
            "target_column": target,
            "positive_value_json": positive_value,
            "negative_value_json": negative_value,
            "predictor_authorization_id": identifiers[
                "predictor_authorization_id"
            ],
            "problem_type": problem_type,
            "partition_method": method,
            "selection_rationale": "",
            "preview_fingerprint": preview_fingerprint,
            "sufficiency_json": sufficiency,
            "development_share": development_share,
            "holdout_share": holdout_share,
            "random_seed": int(payload.get("random_seed", 42)),
            "stratification_policy": policy,
            "stratification_field": stratification_field,
            "population_count": population_count,
            "development_count": len(development),
            "holdout_count": len(holdout),
            "event_counts_json": event_counts,
            "row_assignments_json": assignments,
            "population_fingerprint": _structural_fingerprint(frame),
            "final_holdout_status": "sealed",
            "holdout_isolation_status": "verified",
            "evidence_status": "pending",
            "mdd_status": "pending",
        }
        record["assignment_hash"] = _stable_hash(_assignment_payload(record))
        return preview, record

    def preview(
        self,
        store: Any,
        request: AnalysisPartitionPreviewRequest | Mapping[str, Any],
        *,
        enforce_sealed_holdout: bool = False,
    ) -> Dict[str, Any]:
        payload = request.model_dump() if hasattr(request, "model_dump") else dict(request)
        project_id = _text(payload.get("project_id"))
        if enforce_sealed_holdout:
            current = self.repository.get_current(project_id)
            if current is not None:
                governed = self._validate_integrity(current)
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_CONTRADICTORY,
                    "A sealed Analysis Partition is already current. Alternate target-aware previews are disabled.",
                    recovery="Review the safe current summary or begin an explicit reset preflight against its exact ID and revision.",
                    impacts=self.impact_for_reset(governed),
                    identifiers=_record_identifiers(governed),
                )
        preview, _record = self._build_preview(
            store, payload, require_explicit_contracts=False
        )
        return {
            "ok": True,
            "code": (
                "analysis_partition_preview_blocked"
                if preview["recommendation_status"] == "blocked"
                else "analysis_partition_preview_ready"
            ),
            "readiness": "preview",
            "preview": preview,
        }

    def _exact_current_for_reset(
        self,
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Resolve and concurrency-check the one sealed partition being replaced."""

        project_id = _text(payload.get("project_id"))
        current = self.current(
            project_id,
            _text(payload.get("dataset_id")),
            _text(payload.get("dataset_version_id")),
            target=_text(payload.get("target")),
            target_contract_id=_text(payload.get("target_contract_id")),
            predictor_authorization_id=_text(
                payload.get("predictor_authorization_id")
            ),
        )
        expected_id = _text(payload.get("expected_current_partition_id"))
        try:
            expected_revision = int(payload.get("expected_current_revision") or 0)
        except (TypeError, ValueError):
            expected_revision = 0
        if (
            expected_id != _text(current.get("analysis_partition_id"))
            or expected_revision != int(current.get("revision") or 0)
        ):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_CONTRADICTORY,
                "The current Analysis Partition changed after reset preflight. No alternate preview was calculated.",
                recovery="Refresh the reset impact and retry against the exact current ID and revision.",
                impacts=self.impact_for_reset(current),
                identifiers=_record_identifiers(current),
            )
        return current

    def reset_preview(
        self,
        store: Any,
        request: AnalysisPartitionResetPreviewRequest | Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Preview an alternate design without changing the current sealed partition."""

        payload = request.model_dump() if hasattr(request, "model_dump") else dict(request)
        project_id = _text(payload.get("project_id"))
        with self._project_lock(project_id):
            current = self._exact_current_for_reset(payload)
            preview, _record = self._build_preview(
                store,
                payload,
                require_explicit_contracts=True,
            )
            bound_preview = _bind_reset_preview_fingerprint(preview, current)

            # Detect a concurrent replacement from another process after the
            # deterministic calculation but before returning its fingerprint.
            latest = self.repository.get_current(project_id)
            if (
                latest is None
                or _text(latest.get("analysis_partition_id"))
                != _text(current.get("analysis_partition_id"))
                or int(latest.get("revision") or 0)
                != int(current.get("revision") or 0)
                or _text(latest.get("status")) != "current"
            ):
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_CONTRADICTORY,
                    "The current Analysis Partition changed while the reset preview was calculated.",
                    recovery="Refresh the reset impact and retry against the newly current partition ID and revision.",
                    impacts=self.impact_for_reset(latest or current),
                    identifiers=_record_identifiers(latest or current),
                )
            self._validate_integrity(latest)
            return {
                "ok": True,
                "code": (
                    "analysis_partition_reset_preview_blocked"
                    if bound_preview["recommendation_status"] == "blocked"
                    else "analysis_partition_reset_preview_ready"
                ),
                "readiness": "preview",
                "preview": bound_preview,
            }

    def current(
        self,
        project_id: str,
        expected_dataset_id: str,
        expected_dataset_version_id: str,
        target: str | None = None,
        target_contract_id: str | None = None,
        predictor_authorization_id: str | None = None,
        require_documentation_ready: bool = False,
    ) -> Dict[str, Any]:
        project = _text(project_id)
        dataset = _text(expected_dataset_id)
        version = _text(expected_dataset_version_id)
        if not project or not dataset or not version:
            raise AnalysisPartitionError(
                DATASET_IDENTITY_UNAVAILABLE,
                "Exact project_id, dataset_id, and dataset_version_id are required to resolve an Analysis Partition.",
                recovery="Activate one exact registered Dataset Library version before continuing.",
                identifiers={
                    "project_id": project,
                    "dataset_id": dataset,
                    "dataset_version_id": version,
                },
            )

        record = self.repository.get_current(project)
        if record is None:
            known_exact = [
                item
                for item in self.repository.history(project)
                if _text(item.get("dataset_id")) == dataset
                and _text(item.get("dataset_version_id")) == version
            ]
            if known_exact:
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_STALE,
                    "The exact dataset version has Analysis Partition history, but no partition is current.",
                    recovery="Return to Data Acquisition and explicitly confirm a current partition; historical membership will not be selected as a fallback.",
                    impacts=self.impact_for_reset(),
                    stale_artifacts=_STALE_ARTIFACTS,
                    identifiers={
                        "project_id": project,
                        "dataset_id": dataset,
                        "dataset_version_id": version,
                        "historical_partitions": [
                            {
                                "analysis_partition_id": item.get(
                                    "analysis_partition_id"
                                ),
                                "revision": item.get("revision"),
                                "status": item.get("status"),
                            }
                            for item in known_exact
                        ],
                    },
                )
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_REQUIRED,
                "Target-directed EDA requires an explicitly confirmed Analysis Partition.",
                recovery="Return to Data Acquisition, review the development/final-holdout design, and confirm it.",
                identifiers={
                    "project_id": project,
                    "dataset_id": dataset,
                    "dataset_version_id": version,
                },
            )
        if (
            _text(record.get("dataset_id")) != dataset
            or _text(record.get("dataset_version_id")) != version
        ):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_STALE,
                "The current Analysis Partition belongs to a different exact Dataset Library version.",
                recovery="Return to Data Acquisition and confirm a new Analysis Partition for the exact active version.",
                impacts=self.impact_for_reset(record),
                stale_artifacts=_STALE_ARTIFACTS,
                identifiers=_record_identifiers(record),
            )
        expected_target = _text(target)
        if expected_target and _text(record.get("target_column")) != expected_target:
            raise AnalysisPartitionError(
                TARGET_CONTRACT_STALE,
                "The Analysis Partition target does not match the current Data Acquisition target contract.",
                recovery="Confirm the target mapping, then explicitly reset the Analysis Partition.",
                impacts=self.impact_for_reset(record),
                stale_artifacts=_STALE_ARTIFACTS,
                identifiers=_record_identifiers(record),
            )
        expected_target_contract = _text(target_contract_id)
        if expected_target_contract and _text(record.get("target_contract_id")) != expected_target_contract:
            raise AnalysisPartitionError(
                TARGET_CONTRACT_STALE,
                "The Analysis Partition is bound to a superseded target definition.",
                recovery="Confirm the current target mapping and explicitly reset the Analysis Partition.",
                impacts=self.impact_for_reset(record),
                stale_artifacts=_STALE_ARTIFACTS,
                identifiers=_record_identifiers(record),
            )
        if _text(record.get("status")) != "current":
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_STALE,
                "The Analysis Partition is not current.",
                recovery="Return to Data Acquisition and explicitly confirm a current partition.",
                stale_artifacts=_STALE_ARTIFACTS,
                identifiers=_record_identifiers(record),
            )
        governed = self._validate_integrity(record)
        expected_authorization = _text(predictor_authorization_id)
        creation_authorization = _text(record.get("predictor_authorization_id"))
        governed["current_predictor_authorization_id"] = (
            expected_authorization or creation_authorization
        )
        governed["predictor_authorization_lineage_status"] = (
            "changed_partition_preserved"
            if expected_authorization
            and creation_authorization
            and expected_authorization != creation_authorization
            else "current"
        )
        if require_documentation_ready:
            documentation = self.repository.documentation_readiness(governed)
            if not documentation.get("ready"):
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_DOCUMENTATION_PENDING,
                    "The sealed Analysis Partition is durable, but its exact evidence and MDD read-back are not both complete.",
                    recovery="Use Complete Partition Documentation for this exact design. The durable partition will be reused and only its missing sidecars will be completed idempotently.",
                    identifiers={
                        **_record_identifiers(governed),
                        "durable_partition_created": True,
                        "evidence_ready": bool(
                            documentation.get("evidence_ready")
                        ),
                        "mdd_ready": bool(documentation.get("mdd_ready")),
                    },
                )
        return governed

    def confirm(
        self,
        store: Any,
        request: AnalysisPartitionConfirmRequest | Mapping[str, Any],
        user: Mapping[str, Any] | str | None,
        *,
        before_reset_persist: Callable[[], Any] | None = None,
        require_preview_contract: bool = False,
    ) -> Dict[str, Any]:
        """Recalculate, validate, and durably seal one exact previewed design."""

        payload = (
            request.model_dump()
            if isinstance(request, AnalysisPartitionConfirmRequest)
            else dict(request)
        )
        actor = _actor_id(user)
        project_id = _text(payload.get("project_id"))
        with self._project_lock(project_id):
            supplied_fingerprint = _text(payload.get("preview_fingerprint"))
            reset_existing = bool(payload.get("reset_existing"))
            if require_preview_contract and not supplied_fingerprint:
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_PREVIEW_STALE,
                    "A backend-authoritative preview fingerprint is required before an Analysis Partition can be confirmed.",
                    recovery="Generate a fresh preview and confirm that exact design.",
                    identifiers={
                        "project_id": project_id,
                        "dataset_id": payload.get("dataset_id"),
                        "dataset_version_id": payload.get("dataset_version_id"),
                    },
                    status_code=422,
                )
            current = self.repository.get_current(project_id)
            reset_current: Dict[str, Any] | None = None
            if reset_existing:
                # Resolve the exact current authority before calculating any
                # alternate target-aware membership.  This keeps stale reset
                # requests fail-closed and avoids even a read-only calculation
                # against an authority the caller did not explicitly name.
                reset_current = self._exact_current_for_reset(payload)
            if require_preview_contract and current is not None and not reset_existing:
                governed_current = self.current(
                    project_id,
                    _text(payload.get("dataset_id")),
                    _text(payload.get("dataset_version_id")),
                    target=_text(payload.get("target")),
                    target_contract_id=_text(payload.get("target_contract_id")),
                    predictor_authorization_id=_text(
                        payload.get("predictor_authorization_id")
                    ),
                )
                if (
                    supplied_fingerprint
                    == _text(governed_current.get("preview_fingerprint"))
                    and _request_matches_record_contract(payload, governed_current)
                ):
                    safe = self.publish_safe(store, governed_current)
                    sufficiency = governed_current.get("sufficiency_json")
                    if not isinstance(sufficiency, dict):
                        sufficiency = {}
                    return {
                        "ok": True,
                        "code": "analysis_partition_reused",
                        "readiness": "current",
                        "analysis_partition": safe,
                        "preview": {
                            "preview_fingerprint": supplied_fingerprint,
                            "recommendation_status": sufficiency.get(
                                "overall_status"
                            ),
                            "current_partition": True,
                        },
                        "reused": True,
                        "reset_impacts": [],
                    }
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_CONTRADICTORY,
                    "The requested design contradicts the current sealed Analysis Partition. No alternate target-aware split was calculated.",
                    recovery="Use the safe current summary or begin an explicit reset preflight against the exact current ID and revision.",
                    impacts=self.impact_for_reset(governed_current),
                    identifiers=_record_identifiers(governed_current),
                )

            preview, record = self._build_preview(
                store, payload, require_explicit_contracts=True
            )
            candidate_fingerprint = _text(preview.get("preview_fingerprint"))
            recalculated_fingerprint = candidate_fingerprint
            accepted_fingerprints = {candidate_fingerprint}
            if reset_existing:
                if reset_current is None:  # pragma: no cover - defensive invariant
                    raise AnalysisPartitionError(
                        ANALYSIS_PARTITION_CONTRADICTORY,
                        "The requested reset has no exact current Analysis Partition authority.",
                        recovery="Refresh Data Acquisition and begin a new reset preflight.",
                        impacts=self.impact_for_reset(),
                    )
                preview = _bind_reset_preview_fingerprint(preview, reset_current)
                recalculated_fingerprint = _text(preview.get("preview_fingerprint"))
                accepted_fingerprints = {recalculated_fingerprint}
                if not require_preview_contract:
                    # Preserve compatibility for trusted service callers while
                    # HTTP confirmation requires the concurrency-bound reset
                    # preview token returned by /reset-preview.
                    accepted_fingerprints.add(candidate_fingerprint)
            if supplied_fingerprint and supplied_fingerprint not in accepted_fingerprints:
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_PREVIEW_STALE,
                    "The Analysis Partition preview is stale and no partition was created.",
                    recovery="Refresh the backend-authoritative preview and confirm the exact current fingerprint.",
                    identifiers={
                        "project_id": project_id,
                        "dataset_id": payload.get("dataset_id"),
                        "dataset_version_id": payload.get("dataset_version_id"),
                        "supplied_preview_fingerprint": supplied_fingerprint,
                        "current_preview_fingerprint": recalculated_fingerprint,
                        "candidate_preview_fingerprint": candidate_fingerprint,
                    },
                )
            if preview.get("recommendation_status") == "blocked":
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_SUFFICIENCY_FAILED,
                    "The requested Analysis Partition failed governed split-sufficiency checks.",
                    recovery="Review the preview blockers and select a sufficient standard ratio or correct the target contract.",
                    impacts=list(preview.get("blockers") or []),
                    identifiers={
                        "project_id": project_id,
                        "dataset_id": payload.get("dataset_id"),
                        "dataset_version_id": payload.get("dataset_version_id"),
                        "preview_fingerprint": recalculated_fingerprint,
                    },
                )
            rationale = _text(payload.get("selection_rationale"))
            if bool(preview.get("rationale_required")) and len(rationale) < 10 and (
                require_preview_contract or supplied_fingerprint
            ):
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_SUFFICIENCY_FAILED,
                    "This acceptable but nonrecommended partition choice requires a short analyst rationale.",
                    recovery="Record the reason this split is appropriate for the governed project.",
                    identifiers={
                        "project_id": project_id,
                        "preview_fingerprint": recalculated_fingerprint,
                        "recommendation_status": preview.get(
                            "recommendation_status"
                        ),
                    },
                )

            record["selection_rationale"] = rationale
            record["artifact_hash"] = _stable_hash(_artifact_payload(record))
            current_before_reset: Dict[str, Any] | None = None
            external_invalidation: Any = None
            if reset_existing:
                if not bool(payload.get("acknowledge_invalidation")):
                    raise AnalysisPartitionError(
                        ANALYSIS_PARTITION_CONTRADICTORY,
                        "Reset requires explicit acknowledgement of downstream invalidation.",
                        recovery="Review and acknowledge every reset impact before creating replacement membership.",
                        impacts=self.impact_for_reset(),
                    )
                if not _text(payload.get("reset_reason")):
                    raise AnalysisPartitionError(
                        ANALYSIS_PARTITION_CONTRADICTORY,
                        "Reset requires an analyst rationale.",
                        recovery="Record why new row membership is required.",
                        impacts=self.impact_for_reset(),
                    )
                current_before_reset = self.repository.get_current(project_id)
                if current_before_reset is None:
                    raise AnalysisPartitionError(
                        ANALYSIS_PARTITION_CONTRADICTORY,
                        "The requested reset has no current Analysis Partition to replace.",
                        recovery="Refresh Data Acquisition and create a partition without reset mode.",
                        impacts=self.impact_for_reset(),
                    )
                expected_id = _text(payload.get("expected_current_partition_id"))
                expected_revision = payload.get("expected_current_revision")
                if (
                    expected_id
                    != _text(current_before_reset.get("analysis_partition_id"))
                    or int(expected_revision or 0)
                    != int(current_before_reset.get("revision") or 0)
                ):
                    raise AnalysisPartitionError(
                        ANALYSIS_PARTITION_CONTRADICTORY,
                        "The current Analysis Partition changed after reset preflight. No replacement was created.",
                        recovery="Refresh the reset impact and retry against the exact current ID and revision.",
                        impacts=self.impact_for_reset(current_before_reset),
                        identifiers=_record_identifiers(current_before_reset),
                    )
                if before_reset_persist is not None:
                    try:
                        external_invalidation = before_reset_persist()
                    except AnalysisPartitionError:
                        raise
                    except Exception as exc:
                        raise AnalysisPartitionError(
                            ANALYSIS_PARTITION_RESET_INVALIDATION_FAILED,
                            "The existing Analysis Partition remains current because downstream invalidation did not complete.",
                            recovery="Resolve the invalidation failure, refresh reset impact, and retry.",
                            impacts=self.impact_for_reset(current_before_reset),
                            identifiers=_record_identifiers(current_before_reset),
                        ) from exc
            try:
                try:
                    persisted = self.repository.create_or_reuse(
                        record,
                        actor_user_id=actor,
                        reset_existing=reset_existing,
                        reset_reason=_text(payload.get("reset_reason")),
                        impacts=self.impact_for_reset(),
                        expected_current_partition_id=(
                            _text(payload.get("expected_current_partition_id"))
                            if reset_existing
                            else None
                        ),
                        expected_current_revision=(
                            int(payload.get("expected_current_revision"))
                            if reset_existing
                            and payload.get("expected_current_revision") is not None
                            else None
                        ),
                        external_invalidation_inventory=(
                            _external_invalidation_inventory(external_invalidation)
                            if reset_existing
                            else None
                        ),
                    )
                except AnalysisPartitionConflictError as exc:
                    raise AnalysisPartitionError(
                        ANALYSIS_PARTITION_CONTRADICTORY,
                        str(exc),
                        recovery="Refresh the exact current partition before attempting a governed reset.",
                        impacts=exc.impacts or self.impact_for_reset(exc.current),
                        identifiers=_record_identifiers(exc.current),
                    ) from exc
                except AnalysisPartitionStateError as exc:
                    raise AnalysisPartitionError(
                        ANALYSIS_PARTITION_INTEGRITY_FAILED,
                        str(exc),
                        recovery="Do not continue into target-directed EDA until durable partition integrity is restored.",
                    ) from exc
            except Exception:
                if reset_existing:
                    try:
                        _compensate_external_invalidation(external_invalidation)
                    except Exception as compensation_exc:
                        raise AnalysisPartitionError(
                            ANALYSIS_PARTITION_RESET_INVALIDATION_FAILED,
                            "Analysis Partition reset failed and external derivative compensation could not be verified.",
                            recovery="Keep the workflow closed and reconcile the exact reset inventory before retrying.",
                            impacts=self.impact_for_reset(current_before_reset),
                            identifiers={
                                **_record_identifiers(current_before_reset),
                                "compensation_failed": True,
                            },
                        ) from compensation_exc
                raise
            governed = self._validate_integrity(persisted)
            creation_authorization = _text(
                persisted.get("predictor_authorization_id")
            )
            current_authorization = _text(payload.get("predictor_authorization_id"))
            governed["current_predictor_authorization_id"] = current_authorization
            governed["predictor_authorization_lineage_status"] = (
                "changed_partition_preserved"
                if creation_authorization
                and creation_authorization != current_authorization
                else "current"
            )
            safe = self.publish_safe(store, governed)
            reused = bool(persisted.get("reused"))
            return {
                "ok": True,
                "code": (
                    "analysis_partition_reused"
                    if reused
                    else "analysis_partition_confirmed"
                ),
                "readiness": "current",
                "analysis_partition": safe,
                "preview": preview,
                "reused": reused,
                "reset_impacts": self.impact_for_reset()
                if reset_existing
                else [],
                "reset_invalidation": (
                    persisted.get("reset_invalidation")
                    if reset_existing
                    else None
                ),
            }

    def _validate_frame_structure(
        self,
        store: Any,
        record: Mapping[str, Any],
        *,
        raw_only: bool = False,
    ) -> Tuple[pd.DataFrame, str]:
        governed = self._validate_integrity(record)
        frame = _base_frame(store, raw_only=raw_only)
        target = _text(governed.get("target_column"))
        if target not in frame.columns:
            raise AnalysisPartitionError(
                TARGET_CONTRACT_STALE,
                "The governed target is absent from the current modeling frame.",
                recovery="Restore the exact target contract before using the Analysis Partition.",
                identifiers=_record_identifiers(governed),
            )
        if int(len(frame)) != int(governed.get("population_count") or 0):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_INTEGRITY_FAILED,
                "The current modeling frame row count no longer matches the sealed Analysis Partition.",
                recovery="Do not redraw or infer membership. Restore the exact registered version or explicitly reset the Analysis Partition.",
                stale_artifacts=_STALE_ARTIFACTS,
                identifiers=_record_identifiers(governed),
            )
        actual = _structural_fingerprint(frame)
        if actual != _text(governed.get("population_fingerprint")):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_INTEGRITY_FAILED,
                "The current modeling frame no longer has the exact sealed row order.",
                recovery="Do not redraw or infer membership. Restore the exact registered version or explicitly reset the Analysis Partition.",
                stale_artifacts=_STALE_ARTIFACTS,
                identifiers=_record_identifiers(governed),
            )
        return frame, target

    def materialize_development(
        self,
        store: Any,
        record: Mapping[str, Any],
        authorized_predictors: Iterable[str] | None = None,
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Materialize development rows only; holdout positions are not read."""

        compatibility = self.target_authority_compatibility(record)
        # EDA is governed by the exact Data Acquisition predictor inventory,
        # not later treatment/materialization state.
        frame, target = self._validate_frame_structure(
            store, record, raw_only=True
        )
        predictors = _authorized_predictors(store, authorized_predictors)
        missing = [name for name in predictors if name not in frame.columns]
        if missing:
            raise AnalysisPartitionError(
                PREDICTOR_AUTHORIZATION_REQUIRED,
                "Authorized predictors are absent from the current modeling frame.",
                recovery="Refresh the Data Acquisition predictor-authorization manifest.",
                identifiers={
                    **_record_identifiers(record),
                    "missing_predictors": missing,
                },
            )
        assignments = record.get("row_assignments_json")
        development = [
            int(item)
            for item in (
                assignments.get("development_positions", [])
                if isinstance(assignments, dict)
                else []
            )
        ]
        expected_development_fingerprint = (
            assignments.get("development_target_fingerprint")
            if isinstance(assignments, dict)
            else ""
        )
        expected_development_fingerprint = _text(
            expected_development_fingerprint
        )
        native_v2 = compatibility["lineage_contract"] == "analysis_partition_v2"
        fingerprint_mismatch = False
        if expected_development_fingerprint:
            fingerprint_mismatch = (
                _target_membership_fingerprint(frame, target, development)
                != expected_development_fingerprint
            )
        elif native_v2:
            fingerprint_mismatch = True
        if fingerprint_mismatch:
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_INTEGRITY_FAILED,
                "Development-population target membership failed checksum validation.",
                recovery="Restore the exact development population; the sealed holdout was not inspected.",
                stale_artifacts=["eda_target_directed_artifacts"],
                identifiers=_record_identifiers(record),
            )
        X_dev = frame.iloc[development].loc[:, predictors].copy()
        y_dev = frame.iloc[development].loc[:, target].copy()
        y_dev.name = target
        X_dev.attrs["analysis_partition_compatibility"] = dict(compatibility)
        y_dev.attrs["analysis_partition_compatibility"] = dict(compatibility)
        return X_dev, y_dev

    def materialize_training_development(
        self,
        store: Any,
        record: Mapping[str, Any],
        selected_features: Iterable[str],
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Materialize processed development rows without opening holdout rows.

        Training uses the post-Feature-Engineering frame, unlike EDA's raw
        predictor frame. This verifier selects only durable development
        positions. It may validate structural population identity and the v2
        development-target checksum, but it never indexes holdout feature or
        target values.
        """

        compatibility = self.target_authority_compatibility(record)
        frame, target = self._validate_frame_structure(
            store, record, raw_only=False
        )
        features = _authorized_predictors(store, selected_features)
        missing = [name for name in features if name not in frame.columns]
        if missing:
            raise AnalysisPartitionError(
                PREDICTOR_AUTHORIZATION_REQUIRED,
                "Training features are absent from the exact processed development population.",
                recovery="Rebuild Feature Engineering and Validation Design from the exact current Analysis Partition.",
                identifiers={
                    **_record_identifiers(record),
                    "missing_features": missing,
                },
            )
        assignments = record.get("row_assignments_json")
        development = [
            int(item)
            for item in (
                assignments.get("development_positions", [])
                if isinstance(assignments, dict)
                else []
            )
        ]
        expected_fingerprint = _text(
            assignments.get("development_target_fingerprint")
            if isinstance(assignments, dict)
            else ""
        )
        native_v2 = compatibility["lineage_contract"] == "analysis_partition_v2"
        if (
            native_v2
            and not expected_fingerprint
        ) or (
            expected_fingerprint
            and _target_membership_fingerprint(frame, target, development)
            != expected_fingerprint
        ):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_INTEGRITY_FAILED,
                "Training development-target membership failed checksum validation.",
                recovery="Rebuild Validation Design from the exact current Analysis Partition.",
                stale_artifacts=["validation_design", "training_preflight"],
                identifiers=_record_identifiers(record),
            )
        X_development = frame.iloc[development].loc[:, features].copy()
        y_development = frame.iloc[development].loc[:, target].copy()
        y_development.name = target
        X_development.attrs["analysis_partition_compatibility"] = dict(
            compatibility
        )
        y_development.attrs["analysis_partition_compatibility"] = dict(
            compatibility
        )
        return X_development, y_development

    def materialize_validation(
        self,
        store: Any,
        record: Mapping[str, Any],
        authorized_predictors: Iterable[str] | None = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """Materialize exact membership for Validation Design, never redraw it."""

        compatibility = self.target_authority_compatibility(record)
        frame, target = self._validate_frame_structure(store, record)
        predictors = _authorized_predictors(store, authorized_predictors)
        missing = [name for name in predictors if name not in frame.columns]
        if missing:
            raise AnalysisPartitionError(
                PREDICTOR_AUTHORIZATION_REQUIRED,
                "Authorized predictors are absent from the current modeling frame.",
                recovery="Refresh the governed feature/predictor authorization before creating Validation Design.",
                identifiers={
                    **_record_identifiers(record),
                    "missing_predictors": missing,
                },
            )
        assignments = record.get("row_assignments_json")
        if not isinstance(assignments, dict):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_INTEGRITY_FAILED,
                "Durable Analysis Partition row assignments are unavailable.",
                recovery="Do not redraw membership. Restore the durable partition artifact.",
                identifiers=_record_identifiers(record),
            )
        development = [int(item) for item in assignments["development_positions"]]
        holdout = [int(item) for item in assignments["holdout_positions"]]
        native_v2 = compatibility["lineage_contract"] == "analysis_partition_v2"
        development_target_fingerprint = _text(
            assignments.get("development_target_fingerprint")
        )
        if (
            not development_target_fingerprint
            and native_v2
        ) or (
            development_target_fingerprint
            and _target_membership_fingerprint(frame, target, development)
            != development_target_fingerprint
        ):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_INTEGRITY_FAILED,
                "Development-population target membership failed checksum validation.",
                recovery="Restore the exact registered dataset version before creating Validation Design.",
                identifiers=_record_identifiers(record),
            )
        holdout_target_fingerprint = _text(
            assignments.get("holdout_target_fingerprint")
        )
        if (
            not holdout_target_fingerprint
            and native_v2
        ) or (
            holdout_target_fingerprint
            and _target_membership_fingerprint(frame, target, holdout)
            != holdout_target_fingerprint
        ):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_INTEGRITY_FAILED,
                "Sealed final-holdout target membership failed checksum validation.",
                recovery="Restore the exact registered dataset version; do not redraw holdout membership.",
                identifiers=_record_identifiers(record),
            )
        X_dev = frame.iloc[development].loc[:, predictors].copy()
        X_holdout = frame.iloc[holdout].loc[:, predictors].copy()
        y_dev = frame.iloc[development].loc[:, target].copy()
        y_holdout = frame.iloc[holdout].loc[:, target].copy()
        y_dev.name = target
        y_holdout.name = target
        for materialized in (X_dev, X_holdout, y_dev, y_holdout):
            materialized.attrs["analysis_partition_compatibility"] = dict(
                compatibility
            )
        return X_dev, X_holdout, y_dev, y_holdout

    def invalidate(
        self,
        project_id: str,
        reason: str,
        user: Mapping[str, Any] | str | None = None,
        *,
        expected_dataset_id: str | None = None,
        expected_dataset_version_id: str | None = None,
        target: str | None = None,
        store: Any | None = None,
        expected_current_partition_id: str | None = None,
        expected_current_revision: int | None = None,
        before_invalidation_persist: Callable[[], Any] | None = None,
    ) -> Dict[str, Any]:
        actor = _actor_id(user, allow_system=True)
        current_before = self.repository.get_current(_text(project_id))
        external_invalidation: Any = None
        if current_before is not None and before_invalidation_persist is not None:
            try:
                external_invalidation = before_invalidation_persist()
            except AnalysisPartitionError:
                raise
            except Exception as exc:
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_RESET_INVALIDATION_FAILED,
                    "Analysis Partition invalidation stopped because derivative invalidation did not complete.",
                    recovery="The partition remains current. Resolve the derivative invalidation failure and retry.",
                    impacts=self.impact_for_reset(current_before),
                    identifiers=_record_identifiers(current_before),
                ) from exc
        try:
            try:
                stale = self.repository.invalidate_current(
                    _text(project_id),
                    reason=_text(reason),
                    actor_user_id=actor,
                    expected_dataset_id=_text(expected_dataset_id) or None,
                    expected_dataset_version_id=_text(expected_dataset_version_id) or None,
                    expected_target=_text(target) or None,
                    expected_current_partition_id=(
                        _text(expected_current_partition_id) or None
                    ),
                    expected_current_revision=expected_current_revision,
                    external_invalidation_inventory=(
                        _external_invalidation_inventory(external_invalidation)
                    ),
                )
            except AnalysisPartitionConflictError as exc:
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_STALE,
                    str(exc),
                    recovery="Resolve the exact project/dataset/target identity before invalidating Analysis Partition state.",
                    identifiers=_record_identifiers(exc.current),
                ) from exc
        except Exception:
            try:
                _compensate_external_invalidation(external_invalidation)
            except Exception as compensation_exc:
                raise AnalysisPartitionError(
                    ANALYSIS_PARTITION_RESET_INVALIDATION_FAILED,
                    "Analysis Partition invalidation failed and external derivative compensation could not be verified.",
                    recovery="Keep the workflow closed and reconcile the exact invalidation inventory before retrying.",
                    impacts=self.impact_for_reset(current_before),
                    identifiers={
                        **_record_identifiers(current_before),
                        "compensation_failed": True,
                    },
                ) from compensation_exc
            raise
        if stale is None:
            return {
                "ok": True,
                "code": "analysis_partition_not_present",
                "readiness": "required",
                "analysis_partition": None,
            }
        safe = self.safe_record(stale)
        if store is not None:
            self.publish_safe(store, stale)
        return {
            "ok": True,
            "code": "analysis_partition_invalidated",
            "readiness": "stale",
            "analysis_partition": safe,
            "stale_artifacts": list(_STALE_ARTIFACTS),
            "reset_invalidation": stale.get("reset_invalidation"),
        }


analysis_partition_service = AnalysisPartitionService()
