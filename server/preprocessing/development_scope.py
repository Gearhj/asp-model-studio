from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import pandas as pd

from ..analysis_partition.service import analysis_partition_service
from ..analysis_partition.types import (
    ANALYSIS_PARTITION_STALE,
    DATASET_IDENTITY_UNAVAILABLE,
    PREDICTOR_AUTHORIZATION_REQUIRED,
    TARGET_CONTRACT_STALE,
    AnalysisPartitionError,
)
from ..persistence import service as persistence_service_module
from .predictor_authorization import (
    PredictorAuthorizationIntegrityError,
    verify_durable_predictor_authorization,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _same_scalar(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return str(left) == str(right)


def _identifiers(
    identity: Mapping[str, Any],
    partition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = partition or {}
    return {
        "project_id": _text(identity.get("project_id")),
        "dataset_id": _text(identity.get("dataset_id")),
        "dataset_version_id": _text(identity.get("dataset_version_id")),
        "analysis_partition_id": _text(source.get("analysis_partition_id")),
        "analysis_partition_revision": int(source.get("revision") or 0),
    }


@dataclass(frozen=True)
class DevelopmentAnalysisScope:
    """Verified target authority and development-only analytical population.

    ``development_features`` and ``development_target`` are materialized by
    durable positional assignments.  Holdout positions are intentionally not
    retained on the public object and are never selected by this module.
    """

    identity: dict[str, Any]
    partition: dict[str, Any]
    target_authority: dict[str, Any]
    predictor_authorization: dict[str, Any]
    development_features: pd.DataFrame
    development_target: pd.Series
    _development_positions: tuple[int, ...]
    _source_index: pd.Index
    _source_checksum: str
    _actor: str
    _actor_source: str
    _resolved_at: str

    @property
    def target(self) -> str:
        return _text(self.target_authority.get("target"))

    @property
    def problem_type(self) -> str:
        return _text(self.target_authority.get("problem_type"))

    @property
    def event_value(self) -> Any:
        return self.target_authority.get("event_value")

    @property
    def non_event_value(self) -> Any:
        return self.target_authority.get("non_event_value")

    @property
    def authorized_predictors(self) -> list[str]:
        return [
            _text(value)
            for value in self.predictor_authorization.get(
                "authorized_predictors", []
            )
            if _text(value)
        ]

    def materialize_aligned_features(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Select development predictors from one row-aligned structural frame.

        This is used after an unsupervised full-population transform (for
        example, outlier capping).  Only development positions are selected;
        the sealed holdout is neither selected nor inspected.  Index equality
        is checked before positional selection so duplicate labels are safe.
        """

        if frame is None or frame.empty:
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_STALE,
                "The preprocessing frame required for development analysis is unavailable.",
                recovery="Restore the exact registered dataset version and its current preparation state.",
                identifiers=_identifiers(self.identity, self.partition),
            )
        if int(len(frame)) != int(self.partition.get("population_count") or 0):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_STALE,
                "The preprocessing frame row count no longer matches the sealed Analysis Partition.",
                recovery="Restore the exact row-aligned preprocessing frame; do not infer or redraw membership.",
                identifiers=_identifiers(self.identity, self.partition),
            )
        if not frame.index.equals(self._source_index):
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_STALE,
                "The preprocessing frame row order no longer matches the sealed Analysis Partition.",
                recovery="Restore the exact row order; do not use index labels to reconstruct membership.",
                identifiers=_identifiers(self.identity, self.partition),
            )
        missing = [
            feature
            for feature in self.authorized_predictors
            if feature not in frame.columns
        ]
        if missing:
            raise AnalysisPartitionError(
                PREDICTOR_AUTHORIZATION_REQUIRED,
                "Authorized predictors are absent from the current preprocessing frame.",
                recovery="Restore the exact predictor-authorized preparation state.",
                identifiers={
                    **_identifiers(self.identity, self.partition),
                    "missing_predictors": missing,
                },
            )
        return (
            frame.iloc[list(self._development_positions)]
            .loc[:, self.authorized_predictors]
            .copy()
        )

    def metadata(self) -> dict[str, Any]:
        population_id = _text(
            self.partition.get("development_partition_id")
        )
        partition_id = _text(self.partition.get("analysis_partition_id"))
        partition_revision = int(self.partition.get("revision") or 0)
        population_count = int(len(self.development_target))
        return {
            "scope": "development_population",
            "analysis_scope": "development_population",
            "analytical_scope": "development_population",
            "target_directed_scope": "development_population",
            "structural_scope": "full_governed_population_predictors_only",
            "source_population": "sealed_analysis_partition_development",
            "scope_resolution": "durable_current_exact",
            "row_selection_method": "verified_positional_assignment",
            "project_id": _text(self.identity.get("project_id")),
            "dataset_id": _text(self.identity.get("dataset_id")),
            "dataset_version_id": _text(
                self.identity.get("dataset_version_id")
            ),
            "target": self.target,
            "target_contract_id": _text(
                self.partition.get("target_contract_id")
            ),
            "predictor_authorization_id": _text(
                self.partition.get("predictor_authorization_id")
            ),
            "analysis_partition_id": _text(
                self.partition.get("analysis_partition_id")
            ),
            "analysis_partition_revision": int(
                self.partition.get("revision") or 0
            ),
            "development_partition_id": _text(
                self.partition.get("development_partition_id")
            ),
            "sealed_holdout_partition_id": _text(
                self.partition.get("sealed_holdout_partition_id")
            ),
            "full_governed_population_rows": int(
                self.partition.get("population_count") or 0
            ),
            "development_rows": int(
                self.partition.get("development_count") or 0
            ),
            "sealed_holdout_rows": int(
                self.partition.get("holdout_count") or 0
            ),
            "final_holdout_status": _text(
                self.partition.get("final_holdout_status")
            )
            or "sealed",
            "holdout_isolation_status": _text(
                self.partition.get("holdout_isolation_status")
            ),
            "final_holdout_accessed": False,
            "final_holdout_used_for_selection": False,
            "raw_dataset_target_fallback_used": False,
            "browser_target_semantics_used": False,
            # Canonical audit keys consumed by every target-directed response
            # and persisted preparation artifact. Compatibility aliases above
            # remain during the frontend migration.
            "population_id": population_id,
            "population_count": population_count,
            "partition_id": partition_id,
            "partition_revision": partition_revision,
            "holdout_excluded": True,
            "source_checksum": self._source_checksum,
            "actor": self._actor,
            "actor_source": self._actor_source,
            "timestamp": self._resolved_at,
        }


def resolve_development_analysis_scope(
    store: Any,
    identity: Mapping[str, Any],
    *,
    requested_target: Any = None,
    requested_event_value: Any = None,
    requested_problem_type: Any = None,
    expected_analysis_partition_id: Any = None,
    expected_analysis_partition_revision: Any = None,
    require_documentation_ready: bool = True,
    actor: Any = None,
    timestamp: Any = None,
) -> DevelopmentAnalysisScope:
    """Resolve one exact target-aware analytical scope or fail closed.

    The server derives target/class semantics from the exact durable predictor
    authorization and sealed Analysis Partition.  Request values are checked
    only for contradiction; they never become analytical authority.
    """

    project_id = _text(identity.get("project_id"))
    dataset_id = _text(identity.get("dataset_id"))
    dataset_version_id = _text(identity.get("dataset_version_id"))
    if not project_id or not dataset_id or not dataset_version_id:
        raise AnalysisPartitionError(
            DATASET_IDENTITY_UNAVAILABLE,
            "Exact project, dataset, and dataset-version identity is required for target-directed preprocessing.",
            recovery="Activate the exact registered Dataset Library version before continuing.",
            identifiers=_identifiers(identity),
        )

    store_meta = getattr(store, "meta", {})
    store_meta = store_meta if isinstance(store_meta, Mapping) else {}
    identity_checksum = _text(identity.get("dataset_content_hash"))
    store_checksum = _text(store_meta.get("dataset_content_hash"))
    if identity_checksum and store_checksum and identity_checksum != store_checksum:
        raise AnalysisPartitionError(
            DATASET_IDENTITY_UNAVAILABLE,
            "The active dataset content checksum contradicts the requested exact identity.",
            recovery="Reload the exact registered Dataset Library version before continuing.",
            identifiers=_identifiers(identity),
        )
    source_checksum = identity_checksum or store_checksum
    if not source_checksum:
        raise AnalysisPartitionError(
            DATASET_IDENTITY_UNAVAILABLE,
            "The exact registered dataset content checksum is required for target-directed preprocessing.",
            recovery="Reopen the exact registered Dataset Library version so its checksum can be verified.",
            identifiers=_identifiers(identity),
        )

    record = (
        persistence_service_module.get_persistence_service()
        .predictor_authorizations.get_current_exact(
            project_id,
            dataset_id,
            dataset_version_id,
        )
    )
    if not isinstance(record, Mapping):
        raise AnalysisPartitionError(
            PREDICTOR_AUTHORIZATION_REQUIRED,
            "The exact current Data Acquisition predictor authorization is required for target-directed preprocessing.",
            recovery="Return to Data Acquisition and confirm the target and predictor authorization for this exact version.",
            identifiers=_identifiers(identity),
        )
    try:
        authorization = verify_durable_predictor_authorization(
            record,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
    except PredictorAuthorizationIntegrityError as exc:
        raise AnalysisPartitionError(
            PREDICTOR_AUTHORIZATION_REQUIRED,
            "The exact current predictor authorization failed integrity verification.",
            recovery="Return to Data Acquisition and reconfirm the target and predictor authorization.",
            identifiers=_identifiers(identity),
        ) from exc

    target = _text(authorization.get("target"))
    target_contract_id = _text(authorization.get("target_contract_id"))
    authorization_id = _text(authorization.get("predictor_authorization_id"))
    if not target or not target_contract_id or not authorization_id:
        raise AnalysisPartitionError(
            PREDICTOR_AUTHORIZATION_REQUIRED,
            "The exact predictor authorization has incomplete target lineage.",
            recovery="Return to Data Acquisition and reconfirm the governed target contract.",
            identifiers=_identifiers(identity),
        )
    requested_actor = _text(actor)
    resolved_actor = requested_actor or _text(authorization.get("created_by"))
    actor_source = "authenticated_request" if requested_actor else "predictor_authorization_creator"
    if not resolved_actor:
        raise AnalysisPartitionError(
            PREDICTOR_AUTHORIZATION_REQUIRED,
            "An auditable actor is required for target-directed preprocessing.",
            recovery="Retry from an authenticated project-scoped workflow session.",
            identifiers=_identifiers(identity),
        )
    resolved_at = _text(timestamp) or datetime.now(timezone.utc).isoformat()

    partition = analysis_partition_service.current(
        project_id,
        dataset_id,
        dataset_version_id,
        target=target,
        target_contract_id=target_contract_id,
        predictor_authorization_id=authorization_id,
        require_documentation_ready=require_documentation_ready,
    )
    partition_id = _text(partition.get("analysis_partition_id"))
    partition_revision = int(partition.get("revision") or 0)
    if not partition_id or partition_revision <= 0:
        raise AnalysisPartitionError(
            ANALYSIS_PARTITION_STALE,
            "The current Analysis Partition does not have a positive exact revision.",
            recovery="Return to Data Acquisition and explicitly confirm the Analysis Partition.",
            identifiers=_identifiers(identity, partition),
        )
    if not _text(partition.get("development_partition_id")):
        raise AnalysisPartitionError(
            ANALYSIS_PARTITION_STALE,
            "The current Analysis Partition has no exact development population ID.",
            recovery="Return to Data Acquisition and explicitly confirm the Analysis Partition.",
            identifiers=_identifiers(identity, partition),
        )

    expected_partition_id = _text(expected_analysis_partition_id)
    expected_revision = (
        int(expected_analysis_partition_revision)
        if expected_analysis_partition_revision not in (None, "")
        else None
    )
    if bool(expected_partition_id) != bool(expected_revision is not None):
        raise AnalysisPartitionError(
            ANALYSIS_PARTITION_STALE,
            "Analysis Partition ID and revision must be supplied together.",
            recovery="Reload the exact current preprocessing workspace before retrying.",
            identifiers=_identifiers(identity, partition),
        )
    if expected_partition_id and (
        expected_partition_id != partition_id
        or expected_revision != partition_revision
    ):
        raise AnalysisPartitionError(
            ANALYSIS_PARTITION_STALE,
            "The requested Analysis Partition ID or revision is stale.",
            recovery="Reload the exact current Analysis Partition before retrying.",
            identifiers=_identifiers(identity, partition),
        )

    authority = analysis_partition_service.target_authority_compatibility(
        partition
    )
    governed_problem = _text(authority.get("problem_type")).casefold()
    supplied_target = _text(requested_target)
    supplied_problem = _text(requested_problem_type).casefold()
    if supplied_target and supplied_target != target:
        raise AnalysisPartitionError(
            TARGET_CONTRACT_STALE,
            "The requested target contradicts the sealed Analysis Partition.",
            recovery="Reload the exact governed target contract before retrying.",
            identifiers=_identifiers(identity, partition),
        )
    if supplied_problem and supplied_problem != governed_problem:
        raise AnalysisPartitionError(
            TARGET_CONTRACT_STALE,
            "The requested problem type contradicts the sealed Analysis Partition.",
            recovery="Reload the exact governed target contract before retrying.",
            identifiers=_identifiers(identity, partition),
        )
    if requested_event_value not in (None, "") and not _same_scalar(
        requested_event_value,
        authority.get("event_value"),
    ):
        raise AnalysisPartitionError(
            TARGET_CONTRACT_STALE,
            "The requested event value contradicts the sealed Analysis Partition.",
            recovery="Reload the exact governed class mapping before retrying.",
            identifiers=_identifiers(identity, partition),
        )

    predictors = [
        _text(value)
        for value in authorization.get("authorized_predictors", [])
        if _text(value)
    ]
    development_features, development_target = (
        analysis_partition_service.materialize_development(
            store,
            partition,
            authorized_predictors=predictors,
        )
    )
    assignments = partition.get("row_assignments_json")
    development_positions = tuple(
        int(value)
        for value in (
            assignments.get("development_positions", [])
            if isinstance(assignments, Mapping)
            else []
        )
    )
    raw = getattr(store, "raw_df", None)
    if raw is None or raw.empty:
        raise AnalysisPartitionError(
            DATASET_IDENTITY_UNAVAILABLE,
            "The exact registered source frame is unavailable.",
            recovery="Reopen the exact registered Dataset Library version.",
            identifiers=_identifiers(identity, partition),
        )

    return DevelopmentAnalysisScope(
        identity=dict(identity),
        partition=dict(partition),
        target_authority=dict(authority),
        predictor_authorization=dict(authorization),
        development_features=development_features,
        development_target=development_target,
        _development_positions=development_positions,
        _source_index=raw.index.copy(),
        _source_checksum=source_checksum,
        _actor=resolved_actor,
        _actor_source=actor_source,
        _resolved_at=resolved_at,
    )


def scope_http_exception(exc: AnalysisPartitionError) -> Exception:
    """Convert a governed scope failure into the standard FastAPI envelope."""

    from fastapi import HTTPException

    return HTTPException(status_code=exc.status_code, detail=exc.as_detail())
