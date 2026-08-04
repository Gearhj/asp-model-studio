from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from ..analysis_partition.service import analysis_partition_service
from ..analysis_partition.types import AnalysisPartitionError
from ..core.dataset_store import DATASTORE
from ..datasets.dataset_identity import (
    assert_expected_active_identity,
    resolve_registered_version,
)
from ..persistence.service import get_persistence_service
from ..security.security_store import active_user
from .candidate_contract import canonical_contract_hash
from .trainer import MODEL_CATALOG
from .training_job_types import TrainingJobRequest


LARGE_RUN_FIT_THRESHOLD = max(
    1, int(os.getenv("ATLAS_LARGE_TRAINING_FIT_THRESHOLD", "160"))
)

TRAINING_TARGET_AUTHORITY_UNAVAILABLE = "training_target_authority_unavailable"
TRAINING_TARGET_SEMANTICS_CONTRADICTORY = (
    "training_target_semantics_contradictory"
)


class TrainingTargetSemanticsError(ValueError):
    """Structured fail-closed target-authority failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        identifiers: dict[str, Any] | None = None,
        mismatches: dict[str, Any] | None = None,
        authority: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.authority = dict(authority or {})
        self.detail = {
            "ok": False,
            "code": str(code),
            "message": str(message),
            "recovery": (
                "Refresh Model Training from the exact approved Validation "
                "Design. Changing target semantics requires an explicit "
                "Analysis Partition reset in Data Acquisition."
            ),
            "identifiers": dict(identifiers or {}),
            "mismatches": dict(mismatches or {}),
        }


def _contract_value_equal(left: Any, right: Any) -> bool:
    """Compare exact governed JSON scalars without truthiness coercion."""

    return canonical_contract_hash({"value": left}) == canonical_contract_hash(
        {"value": right}
    )


def _resolve_durable_training_partition(
    *,
    active_identity: dict[str, Any],
    cached_partition: dict[str, Any],
    identifiers: dict[str, Any],
    target: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Resolve one exact, documented partition before training semantics pass.

    Browser/checkpoint metadata is an optimistic copy, never documentation
    authority.  This read verifies the exact current repository row and its
    evidence/MDD sidecars for native-v2 and integrity-gated legacy-v1 records.
    It inspects partition metadata only; no development or holdout rows are
    materialized here.
    """

    expected_identity = {
        field: str(active_identity.get(field) or "")
        for field in ("project_id", "dataset_id", "dataset_version_id")
    }
    scoped_identifiers = {**identifiers, **expected_identity}
    try:
        durable_partition = analysis_partition_service.current(
            expected_identity["project_id"],
            expected_identity["dataset_id"],
            expected_identity["dataset_version_id"],
            target=target,
            target_contract_id=str(
                identifiers.get("target_contract_id") or ""
            ),
            predictor_authorization_id=str(
                cached_partition.get("predictor_authorization_id") or ""
            )
            or None,
            require_documentation_ready=True,
        )
        durable_authority = (
            analysis_partition_service.target_authority_compatibility(
                durable_partition
            )
        )
        durable_safe = analysis_partition_service.safe_record(
            durable_partition
        )
    except AnalysisPartitionError as exc:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            (
                "The exact durable Analysis Partition and its documentation "
                "could not be verified for training."
            ),
            identifiers=scoped_identifiers,
            mismatches={
                "durable_analysis_partition": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
        ) from exc
    except Exception as exc:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            "The durable Analysis Partition repository could not be read safely for training.",
            identifiers=scoped_identifiers,
            mismatches={
                "durable_analysis_partition": {
                    "code": "analysis_partition_repository_unavailable",
                    "error_type": type(exc).__name__,
                }
            },
        ) from exc

    mismatches: dict[str, Any] = {}

    def compare(name: str, recorded: Any, authoritative: Any) -> None:
        if not _contract_value_equal(recorded, authoritative):
            mismatches[name] = {
                "recorded": recorded,
                "authoritative": authoritative,
            }

    for field, expected in expected_identity.items():
        compare(
            f"durable_analysis_partition.{field}",
            durable_partition.get(field),
            expected,
        )
    for field, expected in (
        ("analysis_partition_id", identifiers.get("analysis_partition_id")),
        ("revision", identifiers.get("analysis_partition_revision")),
        ("target_column", target),
        ("target_contract_id", identifiers.get("target_contract_id")),
    ):
        compare(
            f"durable_analysis_partition.{field}",
            durable_partition.get(field),
            expected,
        )

    cached_to_durable = (
        ("analysis_partition_id", "analysis_partition_id"),
        ("revision", "revision"),
        ("project_id", "project_id"),
        ("dataset_id", "dataset_id"),
        ("dataset_version_id", "dataset_version_id"),
        ("target", "target"),
        ("target_contract_id", "target_contract_id"),
        ("predictor_authorization_id", "predictor_authorization_id"),
        ("development_partition_id", "development_partition_id"),
        ("sealed_holdout_partition_id", "sealed_holdout_partition_id"),
        ("assignment_hash", "assignment_hash"),
        ("artifact_hash", "artifact_hash"),
    )
    for cached_field, durable_field in cached_to_durable:
        recorded = cached_partition.get(cached_field)
        if recorded is None or (
            isinstance(recorded, str) and not recorded.strip()
        ):
            continue
        compare(
            f"cached_analysis_partition.{cached_field}",
            recorded,
            durable_safe.get(durable_field),
        )

    if mismatches:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            (
                "The cached Analysis Partition identity does not match the "
                "exact documented current partition."
            ),
            identifiers=scoped_identifiers,
            mismatches=mismatches,
        )
    return durable_partition, durable_safe, durable_authority


def _verified_legacy_partition_authority(
    *,
    split_record: dict[str, Any],
    validation_design: dict[str, Any],
    target_definition: dict[str, Any],
    analysis_partition: dict[str, Any],
    active_identity: dict[str, Any],
    identifiers: dict[str, Any],
    target: str,
    problem_type: str,
    event_value: Any,
    non_event_value: Any,
    durable_partition: dict[str, Any],
    durable_authority: dict[str, Any],
) -> dict[str, Any]:
    """Re-verify a v1 partition from its exact durable repository record."""

    expected_identity = {
        field: str(active_identity.get(field) or "")
        for field in ("project_id", "dataset_id", "dataset_version_id")
    }
    scoped_identifiers = {**identifiers, **expected_identity}
    mismatches: dict[str, Any] = {}

    def compare(
        name: str,
        recorded: Any,
        authoritative: Any,
        *,
        required: bool = True,
    ) -> None:
        if required and (
            recorded is None
            or (isinstance(recorded, str) and not recorded.strip())
        ):
            mismatches[name] = {
                "recorded": recorded,
                "authoritative": authoritative,
            }
        elif not _contract_value_equal(recorded, authoritative):
            mismatches[name] = {
                "recorded": recorded,
                "authoritative": authoritative,
            }

    for field, expected in expected_identity.items():
        if not expected:
            mismatches[f"active_identity.{field}"] = {
                "recorded": expected,
                "authoritative": "exact active identity required",
            }
            continue
        compare(f"split_record.{field}", split_record.get(field), expected)
        compare(
            f"validation_design.{field}",
            validation_design.get(field),
            expected,
        )
        compare(
            f"analysis_partition.{field}",
            analysis_partition.get(field),
            expected,
        )

    required_legacy_markers = {
        "authority_source": "verified_legacy_analysis_partition",
        "compatibility_status": "verified_legacy_v1",
        "lineage_contract": "analysis_partition_v1",
    }
    for field, expected in required_legacy_markers.items():
        compare(
            f"validation_design.target_definition.{field}",
            target_definition.get(field),
            expected,
        )
    split_target_authority = (
        split_record.get("target_authority")
        if isinstance(split_record.get("target_authority"), dict)
        else {}
    )
    split_marker_names = {
        "source": "verified_legacy_analysis_partition",
        "compatibility_status": "verified_legacy_v1",
        "lineage_contract": "analysis_partition_v1",
        "target_membership_fingerprint_status": "legacy_not_recorded",
    }
    for field, expected in split_marker_names.items():
        compare(
            f"split_record.target_authority.{field}",
            split_target_authority.get(field),
            expected,
        )

    partition_id = identifiers.get("analysis_partition_id")
    partition_revision = identifiers.get("analysis_partition_revision")
    development_partition_id = analysis_partition.get(
        "development_partition_id"
    )
    sealed_holdout_partition_id = analysis_partition.get(
        "sealed_holdout_partition_id"
    )
    for record_name, record in (
        ("split_record", split_record),
        ("validation_design", validation_design),
    ):
        compare(
            f"{record_name}.development_partition_id",
            record.get("development_partition_id"),
            development_partition_id,
        )
        compare(
            f"{record_name}.sealed_holdout_partition_id",
            record.get("sealed_holdout_partition_id"),
            sealed_holdout_partition_id,
        )
    for record_name, record in (
        ("split_record", split_record),
        ("validation_design", validation_design),
    ):
        for field in ("training_population_id", "selection_partition_id"):
            compare(
                f"{record_name}.{field}",
                record.get(field),
                development_partition_id,
            )
        for field in (
            "holdout_population_id",
            "final_holdout_partition_id",
        ):
            compare(
                f"{record_name}.{field}",
                record.get(field),
                sealed_holdout_partition_id,
            )

    if mismatches:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            (
                "The approved Validation Design does not preserve the exact "
                "verified legacy Analysis Partition lineage."
            ),
            identifiers=scoped_identifiers,
            mismatches=mismatches,
        )

    durable_comparisons = (
        ("project_id", expected_identity["project_id"]),
        ("dataset_id", expected_identity["dataset_id"]),
        ("dataset_version_id", expected_identity["dataset_version_id"]),
        ("analysis_partition_id", partition_id),
        ("revision", partition_revision),
        ("target_column", target),
        ("target_contract_id", identifiers["target_contract_id"]),
        ("positive_value_json", event_value),
        ("negative_value_json", non_event_value),
        ("development_partition_id", development_partition_id),
        ("sealed_holdout_partition_id", sealed_holdout_partition_id),
        ("assignment_hash", analysis_partition.get("assignment_hash")),
        ("artifact_hash", analysis_partition.get("artifact_hash")),
    )
    for field, expected in durable_comparisons:
        compare(
            f"durable_analysis_partition.{field}",
            durable_partition.get(field),
            expected,
        )
    authority_comparisons = (
        ("target_contract_id", identifiers["target_contract_id"]),
        ("target", target),
        ("problem_type", problem_type),
        ("event_value", event_value),
        ("non_event_value", non_event_value),
        ("source", "verified_legacy_analysis_partition"),
        ("compatibility_status", "verified_legacy_v1"),
        ("lineage_contract", "analysis_partition_v1"),
        ("target_membership_fingerprint_status", "legacy_not_recorded"),
    )
    for field, expected in authority_comparisons:
        compare(
            f"durable_target_authority.{field}",
            durable_authority.get(field),
            expected,
        )
    if mismatches:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            (
                "The approved Validation Design target semantics do not "
                "match the exact integrity-verified legacy partition."
            ),
            identifiers=scoped_identifiers,
            mismatches=mismatches,
        )

    return {
        "partition_authority_source": durable_authority["source"],
        "compatibility_status": durable_authority["compatibility_status"],
        "lineage_contract": durable_authority["lineage_contract"],
        "target_membership_fingerprint_status": durable_authority[
            "target_membership_fingerprint_status"
        ],
        "project_id": expected_identity["project_id"],
        "dataset_id": expected_identity["dataset_id"],
        "dataset_version_id": expected_identity["dataset_version_id"],
        "development_partition_id": str(development_partition_id),
        "sealed_holdout_partition_id": str(sealed_holdout_partition_id),
        "assignment_hash": str(durable_partition["assignment_hash"]),
        "artifact_hash": str(durable_partition["artifact_hash"]),
    }


def _verify_legacy_development_arrays(
    *,
    store: Any,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    active_identity: dict[str, Any],
    analysis_partition: dict[str, Any],
    target_authority: dict[str, Any],
) -> None:
    """Bind legacy training arrays to durable development membership only."""

    identifiers = {
        "project_id": str(active_identity.get("project_id") or ""),
        "dataset_id": str(active_identity.get("dataset_id") or ""),
        "dataset_version_id": str(
            active_identity.get("dataset_version_id") or ""
        ),
        "analysis_partition_id": str(
            target_authority.get("analysis_partition_id") or ""
        ),
        "analysis_partition_revision": int(
            target_authority.get("analysis_partition_revision") or 0
        ),
    }
    try:
        durable = analysis_partition_service.current(
            identifiers["project_id"],
            identifiers["dataset_id"],
            identifiers["dataset_version_id"],
            target=str(target_authority.get("target") or ""),
            target_contract_id=str(
                target_authority.get("source_target_contract_id") or ""
            ),
            predictor_authorization_id=str(
                analysis_partition.get("predictor_authorization_id") or ""
            ),
            require_documentation_ready=True,
        )
        compatibility = (
            analysis_partition_service.target_authority_compatibility(durable)
        )
        if compatibility.get("compatibility_status") != "verified_legacy_v1":
            raise AnalysisPartitionError(
                "analysis_partition_target_authority_unverified",
                "The training array verifier expected an integrity-verified legacy Analysis Partition.",
                identifiers=identifiers,
            )
        expected_X, expected_y = (
            analysis_partition_service.materialize_training_development(
                store,
                durable,
                list(X_train.columns),
            )
        )
    except AnalysisPartitionError as exc:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            "The verified legacy training population could not be bound to its exact durable development membership.",
            identifiers=identifiers,
            mismatches={
                "durable_development_membership": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
        ) from exc
    except Exception as exc:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            "The verified legacy training population could not be checked safely.",
            identifiers=identifiers,
            mismatches={
                "durable_development_membership": {
                    "code": "development_membership_verification_failed",
                    "error_type": type(exc).__name__,
                }
            },
        ) from exc

    mismatches: dict[str, Any] = {}
    if (
        str(durable.get("analysis_partition_id") or "")
        != identifiers["analysis_partition_id"]
        or int(durable.get("revision") or 0)
        != identifiers["analysis_partition_revision"]
        or str(durable.get("assignment_hash") or "")
        != str(target_authority.get("assignment_hash") or "")
        or str(durable.get("artifact_hash") or "")
        != str(target_authority.get("artifact_hash") or "")
    ):
        mismatches["durable_partition_identity"] = {
            "recorded": "changed",
            "authoritative": "exact preflight target authority",
        }
    if list(X_train.columns) != list(expected_X.columns):
        mismatches["development_feature_columns"] = {
            "recorded_count": int(len(X_train.columns)),
            "authoritative_count": int(len(expected_X.columns)),
        }
    if len(X_train) != len(expected_X) or len(y_train) != len(expected_y):
        mismatches["development_row_count"] = {
            "recorded_features": int(len(X_train)),
            "recorded_target": int(len(y_train)),
            "authoritative": int(len(expected_y)),
        }
    if not X_train.index.equals(expected_X.index) or not y_train.index.equals(
        expected_y.index
    ):
        mismatches["development_row_order"] = {
            "recorded": "different",
            "authoritative": "durable development positions",
        }
    if not X_train.equals(expected_X):
        mismatches["development_feature_values"] = {
            "recorded": "different",
            "authoritative": "exact processed development rows",
        }
    if not y_train.equals(expected_y):
        mismatches["development_target_values"] = {
            "recorded": "different",
            "authoritative": "exact development target rows",
        }
    if mismatches:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            "The in-memory training arrays do not match the exact durable legacy development membership.",
            identifiers=identifiers,
            mismatches=mismatches,
        )


def _governed_training_target_semantics(
    *,
    split_record: dict[str, Any],
    active_target: str,
    analysis_partition: dict[str, Any] | None = None,
    active_identity: dict[str, Any] | None = None,
    request: TrainingJobRequest | None = None,
) -> dict[str, Any]:
    """Resolve training semantics only from an approved sealed authority.

    The approved Validation Design is the immediate training authority.  Its
    target definition must be a native projection of the exact sealed Analysis
    Partition and must agree with the split record.  Request fields are only
    optimistic expectations; they can never define or invert the target.
    """

    validation_design = (
        split_record.get("validation_design")
        if isinstance(split_record.get("validation_design"), dict)
        else {}
    )
    target_definition = (
        validation_design.get("target_definition")
        if isinstance(validation_design.get("target_definition"), dict)
        else {}
    )
    identifiers = {
        "analysis_partition_id": validation_design.get(
            "analysis_partition_id"
        )
        or split_record.get("analysis_partition_id"),
        "analysis_partition_revision": validation_design.get(
            "analysis_partition_revision"
        )
        or split_record.get("analysis_partition_revision"),
        "validation_design_id": validation_design.get(
            "validation_design_id"
        ),
        "validation_design_version": validation_design.get("design_version"),
        "target_contract_id": target_definition.get("target_contract_id")
        or validation_design.get("target_contract_id")
        or split_record.get("target_contract_id"),
    }
    required = {
        "validation_design_id": identifiers["validation_design_id"],
        "validation_design_version": identifiers["validation_design_version"],
        "analysis_partition_id": identifiers["analysis_partition_id"],
        "analysis_partition_revision": identifiers[
            "analysis_partition_revision"
        ],
        "target_contract_id": identifiers["target_contract_id"],
        "target": target_definition.get("target"),
        "problem_type": target_definition.get("problem_type"),
        "authority_source": target_definition.get("authority_source"),
    }
    missing = [
        key
        for key, value in required.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing or validation_design.get("status") != "approved":
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            (
                "The approved Validation Design does not contain a complete "
                "sealed Analysis Partition target authority."
            ),
            identifiers=identifiers,
            mismatches={"missing_or_invalid_fields": missing},
        )

    target = str(target_definition.get("target") or "")
    problem_type = str(target_definition.get("problem_type") or "").lower()
    event_value = target_definition.get("positive_value")
    non_event_value = target_definition.get("negative_value")
    authority_source = str(target_definition.get("authority_source") or "")
    is_native_authority = authority_source == "sealed_analysis_partition"
    is_verified_legacy_authority = (
        authority_source == "verified_legacy_analysis_partition"
    )
    authority_invalid = (
        not (is_native_authority or is_verified_legacy_authority)
        or problem_type not in {"classification", "regression"}
        or target != str(active_target or "")
        or (
            problem_type == "classification"
            and (
                event_value is None
                or non_event_value is None
                or _contract_value_equal(event_value, non_event_value)
            )
        )
        or (
            problem_type == "regression"
            and (event_value is not None or non_event_value is not None)
        )
    )
    cached_partition = (
        analysis_partition if isinstance(analysis_partition, dict) else {}
    )
    durable_partition: dict[str, Any] = {}
    durable_authority: dict[str, Any] = {}
    partition = cached_partition
    if not authority_invalid:
        (
            durable_partition,
            partition,
            durable_authority,
        ) = _resolve_durable_training_partition(
            active_identity=(
                active_identity if isinstance(active_identity, dict) else {}
            ),
            cached_partition=cached_partition,
            identifiers=identifiers,
            target=target,
        )
    internal_mismatches: dict[str, Any] = {}
    comparison_fields = (
        ("target", target),
        ("target_contract_id", identifiers["target_contract_id"]),
        ("problem_type", problem_type),
        ("event_value", event_value),
        ("non_event_value", non_event_value),
        ("analysis_partition_id", identifiers["analysis_partition_id"]),
        (
            "analysis_partition_revision",
            identifiers["analysis_partition_revision"],
        ),
    )
    for field, sealed_value in comparison_fields:
        split_value = split_record.get(field)
        if field == "target_contract_id":
            design_value = validation_design.get(field)
        elif field == "event_value":
            design_value = validation_design.get("event_value")
        elif field == "non_event_value":
            design_value = validation_design.get("non_event_value")
        else:
            design_value = validation_design.get(field)
        for record_name, value in (
            ("split_record", split_value),
            ("validation_design", design_value),
        ):
            if value is None and field not in {
                "event_value",
                "non_event_value",
            }:
                internal_mismatches[f"{record_name}.{field}"] = {
                    "recorded": value,
                    "sealed": sealed_value,
                }
            elif not _contract_value_equal(value, sealed_value):
                internal_mismatches[f"{record_name}.{field}"] = {
                    "recorded": value,
                    "sealed": sealed_value,
                }

    if not partition:
        internal_mismatches["analysis_partition"] = {
            "recorded": "missing",
            "sealed": "exact current Analysis Partition required",
        }
    else:
        partition_fields = (
            ("analysis_partition_id", identifiers["analysis_partition_id"]),
            ("revision", identifiers["analysis_partition_revision"]),
            ("target_contract_id", identifiers["target_contract_id"]),
            ("target", target),
            ("positive_value", event_value),
            ("negative_value", non_event_value),
        )
        if is_native_authority:
            partition_fields = (
                *partition_fields,
                ("problem_type", problem_type),
            )
        for field, sealed_value in partition_fields:
            value = partition.get(field)
            if not _contract_value_equal(value, sealed_value):
                internal_mismatches[f"analysis_partition.{field}"] = {
                    "recorded": value,
                    "sealed": sealed_value,
                }
        if (
            is_native_authority
            and partition.get("problem_type_status") != "verified"
        ):
            internal_mismatches["analysis_partition.problem_type_status"] = {
                "recorded": partition.get("problem_type_status"),
                "sealed": "verified",
            }
        if partition.get("status") not in {None, "current"}:
            internal_mismatches["analysis_partition.status"] = {
                "recorded": partition.get("status"),
                "sealed": "current",
            }
        documentation_ready = (
            str(partition.get("evidence_status") or "").lower()
            == "recorded"
            and bool(str(partition.get("evidence_ref") or "").strip())
            and str(partition.get("mdd_status") or "").lower()
            == "recorded"
            and bool(str(partition.get("mdd_ref") or "").strip())
        )
        if not documentation_ready:
            internal_mismatches[
                "analysis_partition.documentation_readiness"
            ] = {
                "recorded": "pending_or_unverified",
                "sealed": "evidence_and_mdd_recorded",
            }

    if durable_authority:
        expected_source = (
            "verified_legacy_analysis_partition"
            if is_verified_legacy_authority
            else "sealed_analysis_partition"
        )
        for field, expected in (
            ("target_contract_id", identifiers["target_contract_id"]),
            ("target", target),
            ("problem_type", problem_type),
            ("event_value", event_value),
            ("non_event_value", non_event_value),
            ("source", expected_source),
        ):
            value = durable_authority.get(field)
            if not _contract_value_equal(value, expected):
                internal_mismatches[
                    f"durable_target_authority.{field}"
                ] = {
                    "recorded": value,
                    "sealed": expected,
                }

    legacy_provenance: dict[str, Any] = {}
    if (
        is_verified_legacy_authority
        and not authority_invalid
        and not internal_mismatches
    ):
        legacy_provenance = _verified_legacy_partition_authority(
            split_record=split_record,
            validation_design=validation_design,
            target_definition=target_definition,
            analysis_partition=partition,
            active_identity=(
                active_identity if isinstance(active_identity, dict) else {}
            ),
            identifiers=identifiers,
            target=target,
            problem_type=problem_type,
            event_value=event_value,
            non_event_value=non_event_value,
            durable_partition=durable_partition,
            durable_authority=durable_authority,
        )

    if authority_invalid or internal_mismatches:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_AUTHORITY_UNAVAILABLE,
            (
                "The Validation Design target semantics do not verify against "
                "the exact sealed Analysis Partition contract."
            ),
            identifiers=identifiers,
            mismatches=internal_mismatches,
        )

    authority = {
        "target": target,
        "source_target_contract_id": str(identifiers["target_contract_id"]),
        "problem_type": problem_type,
        "event_value": event_value,
        "non_event_value": non_event_value,
        "authority_source": (
            "approved_validation_design_bound_to_"
            + (
                "verified_legacy_analysis_partition"
                if is_verified_legacy_authority
                else "sealed_analysis_partition"
            )
        ),
        "analysis_partition_id": str(identifiers["analysis_partition_id"]),
        "analysis_partition_revision": int(
            identifiers["analysis_partition_revision"]
        ),
        "validation_design_id": str(identifiers["validation_design_id"]),
        "validation_design_version": str(
            identifiers["validation_design_version"]
        ),
        **legacy_provenance,
    }
    authority["target_authority_hash"] = canonical_contract_hash(authority)

    client_mismatches: dict[str, Any] = {}
    if request is not None:
        supplied = request.model_fields_set
        if "target" in supplied and request.target and request.target != target:
            client_mismatches["target"] = {
                "requested": request.target,
                "authoritative": target,
            }
        if (
            "problem_type" in supplied
            and request.problem_type
            and request.problem_type != problem_type
        ):
            client_mismatches["problem_type"] = {
                "requested": request.problem_type,
                "authoritative": problem_type,
            }
        if "event_value" in supplied and not _contract_value_equal(
            request.event_value, event_value
        ):
            client_mismatches["event_value"] = {
                "requested": request.event_value,
                "authoritative": event_value,
            }
        if "non_event_value" in supplied and not _contract_value_equal(
            request.non_event_value, non_event_value
        ):
            client_mismatches["non_event_value"] = {
                "requested": request.non_event_value,
                "authoritative": non_event_value,
            }
    if client_mismatches:
        raise TrainingTargetSemanticsError(
            TRAINING_TARGET_SEMANTICS_CONTRADICTORY,
            (
                "Training target claims conflict with the exact approved "
                "Validation Design and sealed Analysis Partition."
            ),
            identifiers=identifiers,
            mismatches=client_mismatches,
            authority=authority,
        )
    return authority


def _package_for_algorithm(key: str, model: Any) -> str:
    if key.startswith("xgb"):
        return "xgboost"
    if key.startswith("lgbm"):
        return "lightgbm"
    if key.startswith("catboost"):
        return "catboost"
    if key in {"ebm", "ebm_reg"}:
        return "interpret"
    if key in {"deep_ffn", "cnn", "lstm"}:
        return "torch"
    if key == "tf_dnn":
        return "tensorflow"
    module_root = str(type(model).__module__ or "").split(".", 1)[0]
    return "scikit-learn" if module_root == "sklearn" else module_root


def _model_runtime_status(key: str) -> dict[str, Any]:
    spec = MODEL_CATALOG.get(key)
    if not spec:
        return {
            "available": False,
            "reason": "Model name is not recognized by the training backend.",
            "label": key,
            "algorithm_class": "unavailable",
            "algorithm_version": "unavailable",
        }
    try:
        model = spec.get("factory", lambda: None)()
    except Exception as exc:
        return {
            "available": False,
            "reason": (
                "Model dependency could not initialize "
                f"({type(exc).__name__})."
            ),
            "label": spec.get("label", key),
            "algorithm_class": "unavailable",
            "algorithm_version": "unavailable",
        }
    if model is None:
        return {
            "available": False,
            "reason": (
                f"{spec.get('label', key)} is unavailable in the current "
                "Python environment."
            ),
            "label": spec.get("label", key),
            "algorithm_class": "unavailable",
            "algorithm_version": "unavailable",
        }
    package = _package_for_algorithm(key, model)
    try:
        version = importlib_metadata.version(package) if package else "local"
    except importlib_metadata.PackageNotFoundError:
        version = "local"
    return {
        "available": True,
        "reason": "Available",
        "label": spec.get("label", key),
        "algorithm_class": (
            f"{type(model).__module__}.{type(model).__qualname__}"
        ),
        "algorithm_version": version,
    }


def _distribution(
    series: pd.Series,
    event_value: Any | None,
    non_event_value: Any | None = None,
) -> dict[str, Any]:
    values = series.dropna()
    counts = values.value_counts()
    result: dict[str, Any] = {
        "rows": int(len(series)),
        "valid_rows": int(len(values)),
        "class_count": int(len(counts)),
        "classes": {str(key): int(value) for key, value in counts.items()},
        "events": None,
        "non_events": None,
        "event_rate": None,
        "event_value": event_value,
        "non_event_value": non_event_value,
        "event_mapping_status": "not_applicable",
        "non_event_mapping_status": "not_applicable",
    }
    if len(counts) != 2:
        return result
    labels = list(counts.index)
    resolved = next((label for label in labels if str(label) == str(event_value)), None)
    if resolved is None:
        result["event_mapping_status"] = "authoritative_event_not_found"
        return result
    resolved_non_event = next(
        (label for label in labels if str(label) == str(non_event_value)), None
    )
    if (
        resolved_non_event is None
        or _contract_value_equal(resolved, resolved_non_event)
    ):
        result["event_mapping_status"] = "authoritative_event_resolved"
        result["non_event_mapping_status"] = (
            "authoritative_non_event_not_found"
        )
        return result
    events = int(counts[resolved])
    result.update({
        "event_value": resolved.item() if hasattr(resolved, "item") else resolved,
        "non_event_value": (
            resolved_non_event.item()
            if hasattr(resolved_non_event, "item")
            else resolved_non_event
        ),
        "events": events,
        "non_events": int(len(values) - events),
        "event_rate": float(events / len(values)) if len(values) else None,
        "event_mapping_status": "authoritative_event_resolved",
        "non_event_mapping_status": "authoritative_non_event_resolved",
    })
    return result


def _model_available(key: str) -> tuple[bool, str]:
    status = _model_runtime_status(key)
    return bool(status["available"]), str(status["reason"])


def _finite_issues(frame: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    all_missing: list[str] = []
    infinite: list[str] = []
    high_cardinality: list[str] = []
    for column in frame.columns:
        series = frame[column]
        if series.dropna().empty:
            all_missing.append(str(column))
        if pd.api.types.is_numeric_dtype(series):
            numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
            if np.isinf(numeric).any():
                infinite.append(str(column))
        elif int(series.nunique(dropna=True)) > 200:
            high_cardinality.append(str(column))
    return all_missing, infinite, high_cardinality


def _identity_error(
    record: dict[str, Any],
    identity: dict[str, Any],
    label: str,
) -> str:
    if not record:
        return (
            f"The {label} is missing. Recreate it for the exact active "
            "Dataset Library version."
        )
    expected = {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": str(identity["dataset_version_id"]),
    }
    missing = [
        key
        for key in expected
        if not str(record.get(key) or "").strip()
    ]
    mismatched = [
        key
        for key, value in expected.items()
        if str(record.get(key) or "").strip()
        and str(record.get(key)) != value
    ]
    legacy = str(record.get("dataset_version") or "").strip()
    if legacy and legacy != expected["dataset_version_id"]:
        mismatched.append("dataset_version")
    if not missing and not mismatched:
        return ""
    return (
        f"The {label} is not bound to the exact active Dataset Library "
        "version. Recreate it before training."
    )


def _external_reference_error(reference: Any, role: str) -> str:
    """Require a persisted TEST/OOT pin to remain exact, readable, and allowed."""
    if reference in (None, {}):
        return ""
    if not isinstance(reference, dict):
        return f"The pinned {role} dataset reference is malformed."
    dataset_id = str(reference.get("dataset_id") or "").strip()
    dataset_version_id = str(reference.get("dataset_version_id") or "").strip()
    if not dataset_id or not dataset_version_id:
        return (
            f"The pinned {role} dataset reference does not contain an exact "
            "dataset_id and dataset_version_id."
        )
    for alias in ("version_id", "dataset_version"):
        compatibility_value = str(reference.get(alias) or "").strip()
        if compatibility_value and compatibility_value != dataset_version_id:
            return (
                f"The pinned {role} dataset reference contains conflicting "
                "version identifiers."
            )
    authenticated_user = active_user()
    if not authenticated_user:
        return (
            f"The pinned {role} dataset version cannot be revalidated because "
            "the authenticated user context is unavailable."
        )
    try:
        resolved = resolve_registered_version(
            dataset_id,
            dataset_version_id,
            user=authenticated_user,
        )
    except HTTPException as exc:
        return (
            f"The pinned {role} dataset version is stale, unavailable, or no "
            f"longer authorized: {exc.detail}"
        )
    if (
        str(resolved.get("dataset_id") or "") != dataset_id
        or str(resolved.get("dataset_version_id") or "") != dataset_version_id
    ):
        return f"The pinned {role} dataset version no longer resolves exactly."
    return ""


def training_preflight(request: TrainingJobRequest) -> dict[str, Any]:
    started = time.perf_counter()
    blocking: list[str] = []
    warnings: list[str] = []
    identity: dict[str, Any] = {}
    try:
        identity = assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=request.dataset_id,
            expected_dataset_version_id=request.dataset_version_id,
            legacy_dataset_version=request.dataset_version,
            require_expected=True,
        )
    except HTTPException as exc:
        blocking.append(str(exc.detail))

    scoped_store = DATASTORE.current()
    # Candidate-selection preflight deliberately reads only the development
    # population. Final-holdout readiness comes from the sealed split contract,
    # never from inspecting final-holdout feature or target arrays.
    X_train = scoped_store.X_train
    y_train = scoped_store.y_train
    split_record = DATASTORE.meta.get("split_record") if isinstance(DATASTORE.meta.get("split_record"), dict) else {}
    manifest = DATASTORE.meta.get("feature_manifest") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else {}
    split_status = str(DATASTORE.meta.get("split_status") or "not_created")
    dataset_id = str(identity.get("dataset_id") or "")
    dataset_version_id = str(identity.get("dataset_version_id") or "")
    # Compatibility alias is always derived from the canonical version ID.
    dataset_version = dataset_version_id
    manifest_version = str(
        manifest.get("manifest_hash") or manifest.get("manifest_version") or ""
    )
    split_id = str(split_record.get("split_id") or "")
    training_population_id = str(split_record.get("training_population_id") or "")
    selection_partition_id = str(
        split_record.get("selection_partition_id") or training_population_id
    )
    final_holdout_partition_id = str(
        split_record.get("final_holdout_partition_id")
        or split_record.get("holdout_population_id")
        or ""
    )
    fold_definition_id = str(split_record.get("fold_definition_id") or "")
    final_holdout_status = str(
        split_record.get("final_holdout_status") or "legacy_unresolved"
    )
    holdout_isolation_status = str(
        split_record.get("holdout_isolation_status") or "legacy_unresolved"
    )
    validation_design = (
        split_record.get("validation_design")
        if isinstance(split_record.get("validation_design"), dict)
        else {}
    )
    validation_design_id = str(
        validation_design.get("validation_design_id") or ""
    )
    validation_design_version = str(
        validation_design.get("design_version") or ""
    )
    durable_holdout_exposure: dict[str, Any] | None = None
    durable_holdout_exposure_check = "not_checked"
    durable_partition_identity = {
        "project_id": str(identity.get("project_id") or request.project_id or ""),
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "validation_design_id": validation_design_id,
        "validation_design_version_id": validation_design_version,
        "split_id": split_id,
        "final_holdout_partition_id": final_holdout_partition_id,
    }
    if all(durable_partition_identity.values()):
        try:
            durable_holdout_exposure = (
                get_persistence_service()
                .holdout_governance.get_holdout_exposure_for_partition(
                    **durable_partition_identity
                )
            )
        except Exception as exc:
            durable_holdout_exposure_check = "verification_failed"
            blocking.append(
                "ATLAS could not verify the durable final-holdout exposure "
                "state, so candidate training is blocked: "
                f"{type(exc).__name__}."
            )
        else:
            durable_holdout_exposure_check = "verified"
            if durable_holdout_exposure is not None:
                exposure_status = str(
                    durable_holdout_exposure.get("final_holdout_status")
                    or "unknown"
                )
                blocking.append(
                    "The exact final-holdout partition already has a durable "
                    f"exposure record ({exposure_status}). It cannot be reused "
                    "for candidate ranking, feature selection, calibration, or "
                    "threshold tuning. Create and approve a new Validation Design."
                )
    cv_design = (
        split_record.get("cv_design")
        if isinstance(split_record.get("cv_design"), dict)
        else {}
    )
    cv_execution_splits = (
        split_record.get("cv_execution_splits")
        if isinstance(split_record.get("cv_execution_splits"), list)
        else []
    )
    target = str(DATASTORE.target or "")
    analysis_partition = (
        scoped_store.meta.get("analysis_partition")
        if isinstance(scoped_store.meta.get("analysis_partition"), dict)
        else {}
    )
    target_authority_errors: list[dict[str, Any]] = []
    try:
        target_semantics_authority = _governed_training_target_semantics(
            split_record=split_record,
            active_target=target,
            analysis_partition=analysis_partition,
            active_identity=identity,
            request=request,
        )
    except TrainingTargetSemanticsError as exc:
        target_semantics_authority = dict(exc.authority)
        target_authority_errors.append(dict(exc.detail))
        blocking.append(str(exc.detail["message"]))
    if (
        target_semantics_authority.get("compatibility_status")
        == "verified_legacy_v1"
        and X_train is not None
        and y_train is not None
    ):
        try:
            _verify_legacy_development_arrays(
                store=scoped_store,
                X_train=X_train,
                y_train=y_train,
                active_identity=identity,
                analysis_partition=analysis_partition,
                target_authority=target_semantics_authority,
            )
        except TrainingTargetSemanticsError as exc:
            target_authority_errors.append(dict(exc.detail))
            blocking.append(str(exc.detail["message"]))

    external_reference_errors = [
        error
        for reference, role in (
            (split_record.get("test_reference"), "TEST"),
            (split_record.get("oot_reference"), "OOT"),
        )
        if (
            error := _external_reference_error(
                reference,
                role,
            )
        )
    ]
    if external_reference_errors:
        split_status = "stale"
        blocking.extend(
            error + " Return to Balance & Split and rebuild Validation Design."
            for error in external_reference_errors
        )

    if split_status != "current" or X_train is None or y_train is None:
        blocking.append("A current governed validation split is required. Return to Balance & Split and create the split explicitly.")
    if not training_population_id or not selection_partition_id:
        blocking.append(
            "The governed training population identity is missing. Return to Balance & Split."
        )
    if (
        not final_holdout_partition_id
        or final_holdout_status != "sealed"
        or holdout_isolation_status != "verified"
    ):
        blocking.append(
            "The final holdout is not sealed under an exact partition identity. Return to Balance & Split."
        )
    if identity:
        for record, label in (
            (manifest, "feature manifest"),
            (split_record, "validation split"),
            (validation_design, "Validation Design"),
        ):
            error = _identity_error(record, identity, label)
            if error:
                blocking.append(error)
        development_dataset = (
            validation_design.get("development_dataset")
            if isinstance(
                validation_design.get("development_dataset"), dict
            )
            else {}
        )
        development_version = str(
            development_dataset.get("dataset_version_id")
            or development_dataset.get("version_id")
            or ""
        )
        if (
            str(development_dataset.get("dataset_id") or "")
            != str(identity["dataset_id"])
            or development_version != str(identity["dataset_version_id"])
        ):
            blocking.append(
                "The Validation Design development population is not pinned "
                "to the exact active Dataset Library version."
            )
    if not manifest_version:
        blocking.append(
            "A versioned feature manifest is required before training."
        )
    if not split_id:
        blocking.append(
            "A versioned validation split is required before training."
        )
    if not validation_design_id or not validation_design_version:
        blocking.append(
            "An approved, versioned Validation Design is required before training."
        )
    split_manifest_version = str(
        split_record.get("feature_manifest_version") or ""
    )
    if not split_manifest_version or split_manifest_version != manifest_version:
        blocking.append(
            "The validation split is not bound to the current feature manifest. "
            "Return to Balance & Split."
        )
    design_manifest_version = str(
        validation_design.get("feature_manifest_hash") or ""
    )
    if (
        not design_manifest_version
        or design_manifest_version != manifest_version
    ):
        blocking.append(
            "The Validation Design is not bound to the current feature manifest. "
            "Return to Balance & Split."
        )
    if request.feature_manifest_version and request.feature_manifest_version != manifest_version:
        blocking.append("Feature manifest version mismatch. Refresh Model Training after saving Final Predictor Review.")
    if request.split_id and request.split_id != split_id:
        blocking.append("Split ID mismatch. The approved validation split changed.")
    if validation_design and validation_design.get("status") != "approved":
        blocking.append(
            "The Validation Design is not approved. Return to Balance & Split."
        )
    completion_gates = split_record.get("completion_gates") or {}
    failed_validation_gates = [
        str(name) for name, passed in completion_gates.items() if passed is not True
    ]
    if validation_design and failed_validation_gates:
        blocking.append(
            "Validation Design completion gates are no longer satisfied: "
            + ", ".join(failed_validation_gates)
        )
    if request.validation_design_id and request.validation_design_id != validation_design_id:
        blocking.append(
            "Validation Design ID mismatch. Refresh Model Training from the approved handoff."
        )
    if (
        request.validation_design_version
        and request.validation_design_version != validation_design_version
    ):
        blocking.append(
            "Validation Design version mismatch. The approved validation contract changed."
        )
    if not target:
        blocking.append("No active target is defined.")

    manifest_selected = [
        str(row.get("feature_name"))
        for row in manifest.get("features", [])
        if isinstance(row, dict) and row.get("selected") and row.get("eligibility_status") == "eligible"
    ]
    engineered = [
        str(row.get("feature_name"))
        for row in manifest.get("features", [])
        if isinstance(row, dict) and row.get("selected") and row.get("eligibility_status") == "eligible" and row.get("origin") != "original"
    ]
    if validation_design and engineered and (
        manifest.get("validation_status") != "passed"
        or manifest.get("materialization_status") != "current"
        or manifest.get("materialized_manifest_hash") != manifest_version
        or manifest.get("confirmation_status") != "confirmed"
        or manifest.get("confirmed_manifest_hash") != manifest_version
    ):
        blocking.append(
            "The engineered feature contract is not validated, materialized, "
            "and confirmed current. Return to Feature Engineering."
        )
    originals = [name for name in manifest_selected if name not in engineered]
    trained_columns = [str(column) for column in X_train.columns] if X_train is not None else []
    missing_features = [name for name in manifest_selected if name not in trained_columns]
    unexpected_features = [name for name in trained_columns if manifest_selected and name not in manifest_selected]
    if not manifest_selected:
        blocking.append("The feature manifest has no selected predictors.")
    if missing_features:
        blocking.append("Selected features are missing from the training split: " + ", ".join(missing_features))
    if unexpected_features:
        blocking.append("The training split contains predictors outside the approved manifest: " + ", ".join(unexpected_features))
    if X_train is not None and X_train.shape[1] == 0:
        blocking.append("The training feature matrix is empty.")

    authoritative_event_value = target_semantics_authority.get("event_value")
    authoritative_non_event_value = target_semantics_authority.get(
        "non_event_value"
    )
    problem_type = str(
        target_semantics_authority.get("problem_type") or ""
    )
    train_distribution = (
        _distribution(
            y_train,
            authoritative_event_value,
            authoritative_non_event_value,
        )
        if y_train is not None and problem_type == "classification"
        else _distribution(y_train, None)
        if y_train is not None
        else {}
    )
    governed_distributions = (
        split_record.get("distributions")
        if isinstance(split_record.get("distributions"), dict)
        else {}
    )
    # Presentation-only final-holdout aggregates were captured at split time.
    # They are not recomputed or inspected during candidate selection.
    test_distribution = (
        governed_distributions.get("holdout_untouched")
        if isinstance(governed_distributions.get("holdout_untouched"), dict)
        else {}
    )
    if y_train is not None and y_train.isna().any():
        blocking.append("The training target contains missing values.")
    if problem_type == "classification":
        if train_distribution.get("class_count") != 2:
            blocking.append("The training target does not contain exactly two classes.")
        if (
            train_distribution.get("event_mapping_status")
            != "authoritative_event_resolved"
        ):
            blocking.append(
                "The authoritative positive class is not present in the "
                "development target."
            )
        elif (
            train_distribution.get("non_event_mapping_status")
            != "authoritative_non_event_resolved"
        ):
            blocking.append(
                "The authoritative negative class is not present in the "
                "development target."
            )
        elif not train_distribution.get("events"):
            blocking.append("The training split contains no positive-class events.")
        event_rate = train_distribution.get("event_rate")
        if isinstance(event_rate, float) and event_rate < 0.01:
            warnings.append("Rare-event target detected. Use PR-AUC, recall, lift, and calibration evidence rather than accuracy alone.")

    all_missing: list[str] = []
    infinite: list[str] = []
    high_cardinality: list[str] = []
    if X_train is not None:
        all_missing, infinite, high_cardinality = _finite_issues(X_train)
    if all_missing:
        blocking.append("All-missing training predictors cannot be fitted: " + ", ".join(all_missing))
    if infinite:
        blocking.append("Infinite numeric values must be treated before training: " + ", ".join(infinite))
    if high_cardinality:
        warnings.append("High-cardinality categorical predictors may expand memory use: " + ", ".join(high_cardinality[:8]))
    missing_value_columns = [str(column) for column in X_train.columns if X_train[column].isna().any()] if X_train is not None else []
    if missing_value_columns:
        warnings.append(f"Training-only imputation will be fitted for {len(missing_value_columns)} predictor(s) with missing values.")

    min_class_count = 0
    if y_train is not None and problem_type == "classification" and len(y_train.value_counts()) >= 2:
        min_class_count = int(y_train.value_counts().min())
    design_fold_method = str(cv_design.get("method") or "none")
    design_folds = int(cv_design.get("fold_count") or 0)
    cv_owned_by_design = bool(
        validation_design and design_fold_method != "none" and design_folds >= 2
    )
    execution_fold_count = (
        len(cv_execution_splits)
        if cv_owned_by_design and cv_execution_splits
        else design_folds
        if cv_owned_by_design
        else 0
    )
    if cv_owned_by_design and request.k_folds != design_folds:
        blocking.append(
            f"Cross-validation is locked by Validation Design at {design_folds} folds; "
            f"the training request attempted {request.k_folds}."
        )
    if not cv_owned_by_design:
        blocking.append(
            "Candidate selection requires an approved governed cross-validation design in Balance & Split."
        )
    if cv_owned_by_design and not fold_definition_id:
        blocking.append(
            "The approved Validation Design lacks an exact fold_definition_id. Return to Balance & Split and rebuild it."
        )
    if request.grid_search and validation_design and not cv_owned_by_design:
        blocking.append(
            "Hyperparameter search requires an approved cross-validation design in Balance & Split."
        )
    if cv_owned_by_design and not cv_execution_splits:
        blocking.append(
            "The approved Validation Design does not contain executable fold "
            "bindings. Return to Balance & Split and rebuild the design."
        )
    if (
        cv_owned_by_design
        and design_fold_method == "nested_cv"
        and request.grid_search
    ):
        blocking.append(
            "Nested-CV outer-loop execution is not available in the current "
            "trainer. Select a non-nested governed fold architecture or disable "
            "hyperparameter search."
        )
    invalid_execution_folds: list[int] = []
    if cv_owned_by_design and X_train is not None:
        for index, fold in enumerate(cv_execution_splits, start=1):
            if not isinstance(fold, dict):
                invalid_execution_folds.append(index)
                continue
            train_positions = fold.get("train_positions")
            validation_positions = fold.get("validation_positions")
            if (
                not isinstance(train_positions, list)
                or not isinstance(validation_positions, list)
                or not train_positions
                or not validation_positions
                or min([*train_positions, *validation_positions]) < 0
                or max([*train_positions, *validation_positions])
                >= len(X_train)
                or set(train_positions).intersection(validation_positions)
            ):
                invalid_execution_folds.append(index)
                continue
            if problem_type == "classification":
                training_target = y_train.iloc[train_positions]
                validation_target = y_train.iloc[validation_positions]
                if (
                    int(training_target.nunique(dropna=True)) != 2
                    or int(validation_target.nunique(dropna=True)) != 2
                ):
                    invalid_execution_folds.append(index)
        if invalid_execution_folds:
            blocking.append(
                "Executable Validation Design folds are invalid or lack both "
                "target classes: "
                + ", ".join(str(value) for value in invalid_execution_folds)
                + ". Return to Balance & Split."
            )
    requested_folds = design_folds if cv_owned_by_design else request.k_folds
    effective_folds = (
        execution_fold_count
        if cv_owned_by_design and execution_fold_count
        else min(max(2, requested_folds), max(2, min_class_count))
        if problem_type == "classification"
        else min(
            max(2, requested_folds),
            max(2, len(y_train) if y_train is not None else 2),
        )
    )
    cv_compatible = problem_type == "regression" or min_class_count >= 2
    if request.grid_search and not cv_compatible:
        blocking.append("Grid search requires at least two observations in every target class.")
    if (
        problem_type == "classification"
        and cv_owned_by_design
        and min_class_count < requested_folds
    ):
        blocking.append(
            f"The approved {requested_folds}-fold design is not event-count compatible "
            f"with the current training population; return to Balance & Split."
        )
    elif request.grid_search and effective_folds < requested_folds:
        blocking.append(
            f"The requested {requested_folds}-fold search is not event-count compatible "
            f"with the current training population; return to Balance & Split."
        )

    library_status: dict[str, Any] = {}
    compatibility: dict[str, Any] = {}
    calibration_compatibility: dict[str, Any] = {}
    for key, spec in MODEL_CATALOG.items():
        runtime_status = _model_runtime_status(key)
        available = bool(runtime_status["available"])
        reason = str(runtime_status["reason"])
        library_status[key] = runtime_status
    selected_algorithm_ids = list(dict.fromkeys(str(key) for key in request.models))
    if not selected_algorithm_ids:
        blocking.append("Select at least one compatible model before validation.")
    for key in selected_algorithm_ids:
        spec = MODEL_CATALOG.get(key)
        available = bool(library_status.get(key, {}).get("available"))
        task_match = bool(spec and (spec.get("task") == problem_type or (spec.get("kind") == "anomaly" and problem_type == "classification")))
        compatible = available and task_match
        reason = library_status.get(key, {}).get("reason") if not available else "Compatible" if task_match else f"Model does not support {problem_type}."
        compatibility[key] = {"compatible": compatible, "reason": reason}
        if not compatible:
            blocking.append(f"{spec.get('label', key) if spec else key}: {reason}")
        calibration_allowed = bool(problem_type == "classification" and spec and spec.get("kind") != "anomaly" and min_class_count >= 2)
        calibration_reason = "Compatible" if calibration_allowed else "Calibration requires binary classification with at least two observations per class and a supervised probability model."
        calibration_compatibility[key] = {"compatible": calibration_allowed, "reason": calibration_reason}
    selected_algorithm_versions = {
        key: str(
            library_status.get(key, {}).get("algorithm_version")
            or "unavailable"
        )
        for key in selected_algorithm_ids
    }
    stale_runtime_versions = [
        key
        for key, expected in request.selected_algorithm_versions.items()
        if key in selected_algorithm_versions
        and str(expected or "") != selected_algorithm_versions[key]
    ]
    if stale_runtime_versions:
        blocking.append(
            "The selected algorithm runtime changed after preflight: "
            + ", ".join(stale_runtime_versions)
            + ". Run preflight again."
        )
    if request.calibrate:
        incompatible_calibration = [key for key in request.models if not calibration_compatibility.get(key, {}).get("compatible")]
        if incompatible_calibration:
            blocking.append(
                "Calibration is incompatible with selected models: "
                + ", ".join(incompatible_calibration)
                + ". Disable calibration or change the portfolio."
            )

    rows = int(len(X_train)) if X_train is not None else 0
    columns = int(X_train.shape[1]) if X_train is not None else 0
    estimated_bytes = rows * max(columns, 1) * 8 * 4
    estimated_memory_mb = round(estimated_bytes / (1024 * 1024), 1)
    cpu_cap = max(1, min(4, os.cpu_count() or 1))
    memory_cap = 1 if estimated_memory_mb > 2_000 else 2 if estimated_memory_mb > 750 else cpu_cap
    recommended_parallel = max(1, min(len(selected_algorithm_ids) or 1, cpu_cap, memory_cap))
    balancing_policy = (
        split_record.get("balancing_policy")
        if isinstance(split_record.get("balancing_policy"), dict)
        else {}
    )
    selection_resampling_status = str(
        balancing_policy.get("selection_resampling_status") or "not_applied"
    )
    if selection_resampling_status != "not_applied":
        blocking.append(
            "Candidate-selection folds must not inherit population-level label resampling. Rebuild Validation Design without resampling."
        )
    preprocessing_values = {
        str(value)
        for value in (
            validation_design.get("fold_local_preprocessing"),
            cv_design.get("fold_local_preprocessing"),
            balancing_policy.get("fold_local_preprocessing"),
        )
        if str(value or "").strip()
    }
    if len(preprocessing_values) > 1:
        blocking.append(
            "The approved Validation Design contains contradictory fold-local preprocessing policies."
        )
    fold_local_preprocessing = next(
        iter(preprocessing_values), "fit_transform_per_fold"
    )
    if fold_local_preprocessing not in {
        "fit_transform_per_fold",
        "model_native_per_fold",
    }:
        blocking.append(
            "The approved fold-local preprocessing policy is not executable."
        )
    balancing_method = str(balancing_policy.get("method") or "none")
    if balancing_method not in {"none", "undersample", "oversample", "smote"}:
        blocking.append("The approved balancing method is not executable.")
    fold_local_resampling_status = str(
        balancing_policy.get("fold_local_resampling_status")
        or ("not_requested" if balancing_method == "none" else "")
    )
    if (
        balancing_method != "none"
        and fold_local_resampling_status != "planned_fold_local_training_only"
    ):
        blocking.append(
            "The approved balancing method is not bound to fold-local training rows. Rebuild Validation Design."
        )
    class_weight_policy = str(
        balancing_policy.get("class_weight_policy") or "none"
    )
    if class_weight_policy not in {"none", "balanced"}:
        blocking.append(
            "Custom class weights require explicit governed weights and are not executable by the approved design."
        )
    if problem_type != "classification" and (
        balancing_method != "none" or class_weight_policy != "none"
    ):
        blocking.append(
            "Balancing and class weights are available only for classification Validation Designs."
        )
    try:
        policy_minority_share = float(
            balancing_policy.get("minority_share", 0.5)
        )
    except (TypeError, ValueError):
        policy_minority_share = -1.0
    if not 0.05 <= policy_minority_share <= 0.5:
        blocking.append(
            "The approved balancing minority share must be between 0.05 and 0.5."
        )
    validation_execution_policy = {
        "source": "approved_validation_design",
        "fold_local_preprocessing": fold_local_preprocessing,
        "balancing_method": balancing_method,
        "minority_share": policy_minority_share,
        "class_weight_policy": class_weight_policy,
        "random_seed": int(
            cv_design.get("random_seed")
            or (split_record.get("fold_architecture") or {}).get(
                "random_seed"
            )
            or (split_record.get("config") or {}).get("random_seed")
            or 42
        ),
        "fold_local_resampling_status": fold_local_resampling_status,
        "selection_resampling_status": selection_resampling_status,
        "fit_scope": "development_fold_training_rows_only",
        "validation_rows_resampled": False,
        "final_holdout_access": "none",
    }
    if request.use_pca:
        blocking.append(
            "PCA is not implemented by the governed training pipeline and cannot be enabled."
        )
    if str(request.grid_search_level).lower() not in {
        "quick",
        "balanced",
        "thorough",
    }:
        blocking.append(
            "Grid-search level must be quick, balanced, or thorough."
        )

    tuning_candidates = (
        {"quick": 4, "balanced": 8, "thorough": 12}.get(
            str(request.grid_search_level).lower(), 4
        )
        if request.grid_search
        else 1
    )
    estimated_fits = (
        len(selected_algorithm_ids)
        * max(1, effective_folds)
        * tuning_candidates
    )
    calibration_supported_algorithm_ids = [
        key
        for key in selected_algorithm_ids
        if calibration_compatibility.get(key, {}).get("compatible")
    ]
    calibration_fits = (
        len(calibration_supported_algorithm_ids) * max(1, effective_folds)
        if request.calibrate
        else 0
    )
    estimated_fits += calibration_fits
    large_run_required = estimated_fits >= LARGE_RUN_FIT_THRESHOLD
    large_run_acknowledged = bool(request.large_job_confirmed)

    ready = not blocking
    unique_blocking = list(dict.fromkeys(blocking))
    unique_warnings = list(dict.fromkeys(warnings))

    def readiness_check(
        check_id: str,
        passed: bool,
        reason: str,
        *,
        warning: bool = False,
    ) -> dict[str, Any]:
        return {
            "check_id": check_id,
            "state": "warning" if passed and warning else "passed" if passed else "failed",
            "passed": bool(passed),
            "reason": reason,
        }

    identity_ready = bool(identity and dataset_id and dataset_version_id)
    feature_ready = bool(
        manifest_version
        and manifest_selected
        and not missing_features
        and not unexpected_features
    )
    validation_ready = bool(
        split_status == "current"
        and split_id
        and validation_design_id
        and validation_design_version
        and validation_design.get("status") == "approved"
        and cv_owned_by_design
        and cv_execution_splits
        and not invalid_execution_folds
    )
    target_ready = bool(
        target and y_train is not None and target_semantics_authority
    )
    dependency_ready = bool(
        selected_algorithm_ids
        and all(
            compatibility.get(key, {}).get("compatible")
            for key in selected_algorithm_ids
        )
    )
    final_holdout_sealed = bool(
        final_holdout_partition_id
        and final_holdout_status == "sealed"
        and holdout_isolation_status == "verified"
        and durable_holdout_exposure is None
        and durable_holdout_exposure_check != "verification_failed"
    )
    checks = [
        readiness_check(
            "canonical_identity",
            identity_ready,
            "Exact canonical Dataset Library identity verified."
            if identity_ready
            else "The exact project, dataset, and dataset-version identity is unavailable or stale.",
        ),
        readiness_check(
            "target_contract",
            target_ready,
            f"Target {target} is available in the development population."
            if target_ready
            else "The governed target contract is missing.",
        ),
        readiness_check(
            "feature_contract",
            feature_ready,
            f"Feature manifest {manifest_version} provides {len(manifest_selected)} selected predictors."
            if feature_ready
            else "The feature manifest is missing, stale, or inconsistent with the development matrix.",
        ),
        readiness_check(
            "validation_design",
            validation_ready,
            f"Validation Design {validation_design_id} and split {split_id} are current."
            if validation_ready
            else "An approved current Validation Design with executable folds is required.",
        ),
        readiness_check(
            "dependencies",
            dependency_ready,
            "Every selected algorithm dependency and task contract is compatible."
            if dependency_ready
            else "One or more selected algorithms are unavailable or incompatible.",
        ),
        readiness_check(
            "data_type_compatibility",
            not all_missing and not infinite,
            "Development predictors contain no all-missing or infinite columns."
            if not all_missing and not infinite
            else "Development predictors contain unsupported all-missing or infinite values.",
        ),
        readiness_check(
            "encoding_requirements",
            True,
            "Categorical encoding is fitted inside governed development folds."
            + (
                f" {len(high_cardinality)} high-cardinality column(s) require review."
                if high_cardinality
                else ""
            ),
            warning=bool(high_cardinality),
        ),
        readiness_check(
            "scaling_requirements",
            True,
            "Algorithm-specific scaling is fitted inside governed development folds.",
        ),
        readiness_check(
            "calibration_compatibility",
            not request.calibrate
            or all(
                calibration_compatibility.get(key, {}).get("compatible")
                for key in selected_algorithm_ids
            ),
            "Calibration is disabled or compatible with every selected model."
            if not request.calibrate
            or all(
                calibration_compatibility.get(key, {}).get("compatible")
                for key in selected_algorithm_ids
            )
            else "Calibration is unsupported for at least one selected model.",
        ),
        readiness_check(
            "event_count_compatibility",
            cv_compatible
            and (
                problem_type != "classification"
                or min_class_count >= requested_folds
            ),
            "Development-population event counts support the approved folds."
            if cv_compatible
            and (
                problem_type != "classification"
                or min_class_count >= requested_folds
            )
            else "Development-population event counts do not support the approved folds.",
        ),
        readiness_check(
            "cv_compatibility",
            validation_ready,
            "Candidate selection is restricted to exact governed development folds."
            if validation_ready
            else "Executable governed cross-validation folds are unavailable.",
        ),
        readiness_check(
            "memory_and_workers",
            True,
            (
                f"Estimated memory is {estimated_memory_mb} MB; "
                f"{recommended_parallel} worker(s) will be honored."
            ),
            warning=request.max_parallel > max(1, recommended_parallel),
        ),
        readiness_check(
            "final_holdout_sealed",
            final_holdout_sealed,
            "The final holdout remains sealed; preflight read development data only."
            if final_holdout_sealed
            else "The exact final holdout is not sealed and verified for isolation.",
        ),
        readiness_check(
            "selection_resampling",
            selection_resampling_status == "not_applied",
            "No population-level label resampling contaminates candidate selection."
            if selection_resampling_status == "not_applied"
            else "Candidate-selection folds contain prohibited population-level resampling.",
        ),
    ]
    # If a specialized check has not represented a newly added fail-closed
    # condition, the contract-consistency check still makes the single result
    # internally non-contradictory and exposes every authoritative reason.
    checks.append(
        readiness_check(
            "contract_consistency",
            ready,
            "Every governed preflight condition passed."
            if ready
            else " | ".join(unique_blocking),
        )
    )

    manifest_id = str(
        manifest.get("manifest_id")
        or manifest.get("manifest_version")
        or manifest_version
    )
    target_contract = {
        "target": target_semantics_authority.get("target") or target,
        "problem_type": problem_type,
        "event_value": authoritative_event_value,
        "non_event_value": authoritative_non_event_value,
        "source_target_contract_id": target_semantics_authority.get(
            "source_target_contract_id"
        ),
        "authority_source": target_semantics_authority.get(
            "authority_source"
        ),
        "analysis_partition_id": target_semantics_authority.get(
            "analysis_partition_id"
        ),
        "analysis_partition_revision": target_semantics_authority.get(
            "analysis_partition_revision"
        ),
        "validation_design_id": target_semantics_authority.get(
            "validation_design_id"
        ),
        "validation_design_version": target_semantics_authority.get(
            "validation_design_version"
        ),
        "target_authority_hash": target_semantics_authority.get(
            "target_authority_hash"
        ),
        "development_rows": rows,
        "development_events": train_distribution.get("events"),
        "status": (
            "current"
            if target_ready and bool(target_semantics_authority)
            else "missing"
        ),
    }
    portfolio = (
        scoped_store.meta.get("training_model_portfolio")
        if isinstance(
            scoped_store.meta.get("training_model_portfolio"), dict
        )
        else {}
    )
    selection_revision = int(portfolio.get("selection_revision") or 0)
    state_payload = {
        "project_id": request.project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "data_revision": int(scoped_store.data_revision),
        "feature_manifest_id": manifest_id,
        "feature_manifest_version": manifest_version,
        "validation_design_id": validation_design_id,
        "validation_design_version": validation_design_version,
        "split_id": split_id,
        "target_contract": target_contract,
        "target_semantics_authority": target_semantics_authority,
        "selected_algorithm_ids": selected_algorithm_ids,
        "selected_algorithm_versions": selected_algorithm_versions,
        "k_folds": request.k_folds,
        "grid_search": request.grid_search,
        "grid_search_level": request.grid_search_level,
        "calibrate": request.calibrate,
        "use_pca": request.use_pca,
        "max_parallel": request.max_parallel,
        "candidate_strategy": request.candidate_strategy,
        "primary_metric": request.primary_metric,
        "final_holdout_partition_id": final_holdout_partition_id,
        "final_holdout_status": final_holdout_status,
        "holdout_isolation_status": holdout_isolation_status,
        "validation_execution_policy": validation_execution_policy,
    }
    state_hash = canonical_contract_hash(state_payload)
    preflight_id = f"training-preflight-{state_hash[:20]}"
    created_at = datetime.now(timezone.utc).isoformat()
    result = {
        "ok": True,
        "ready": ready,
        "readiness_status": "ready" if ready else "blocked",
        "blocking_errors": unique_blocking,
        "blocking_details": target_authority_errors,
        "warnings": unique_warnings,
        "checks": checks,
        "preflight_id": preflight_id,
        "state_hash": state_hash,
        "revision": int(scoped_store.data_revision) * 1_000_000
        + selection_revision,
        "canonical_data_revision": int(scoped_store.data_revision),
        "selection_revision": selection_revision,
        "created_at": created_at,
        "stale": False,
        "stale_reason": None,
        "project_id": request.project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "dataset_version": dataset_version,
        "target": target_semantics_authority.get("target") or target,
        "target_contract": target_contract,
        "target_semantics_authority": target_semantics_authority,
        "target_authority_hash": target_semantics_authority.get(
            "target_authority_hash"
        ),
        "event_value": authoritative_event_value,
        "non_event_value": authoritative_non_event_value,
        "problem_type": problem_type,
        "train_rows": rows,
        "test_rows": int(test_distribution.get("rows") or split_record.get("n_test") or 0),
        "train_events": train_distribution.get("events"),
        "test_events": test_distribution.get("events"),
        "train_event_rate": train_distribution.get("event_rate"),
        "test_event_rate": test_distribution.get("event_rate"),
        "selected_features": manifest_selected,
        "selected_original_features": originals,
        "engineered_features": engineered,
        "missing_features": missing_features,
        "unexpected_features": unexpected_features,
        "feature_manifest_version": manifest_version,
        "feature_manifest_id": manifest_id,
        "split_id": split_id,
        "training_population_id": training_population_id,
        "selection_partition_id": selection_partition_id,
        "holdout_population_id": final_holdout_partition_id,
        "final_holdout_partition_id": final_holdout_partition_id,
        "fold_definition_id": fold_definition_id,
        "final_holdout_status": final_holdout_status,
        "holdout_isolation_status": holdout_isolation_status,
        "durable_holdout_exposure_check": durable_holdout_exposure_check,
        "durable_holdout_exposure_status": (
            durable_holdout_exposure.get("final_holdout_status")
            if durable_holdout_exposure is not None
            else None
        ),
        "selection_resampling_status": selection_resampling_status,
        "validation_execution_policy": validation_execution_policy,
        "split_status": split_status,
        "validation_design": validation_design,
        "validation_design_id": validation_design_id,
        "validation_design_version": validation_design_version,
        "cv_design": cv_design,
        "fold_architecture": split_record.get("fold_architecture") or {},
        "evaluation_population_role": split_record.get(
            "evaluation_population_role"
        ),
        "completion_gates": split_record.get("completion_gates") or {},
        "validation_risks": split_record.get("validation_risks") or [],
        "test_reference": split_record.get("test_reference"),
        "oot_reference": split_record.get("oot_reference"),
        "split_configuration": split_record.get("config") or {},
        "balancing_configuration": balancing_policy
        or {
            "method": (split_record.get("config") or {}).get(
                "balance_method", "none"
            )
        },
        "optional_library_status": library_status,
        "selected_algorithm_ids": selected_algorithm_ids,
        "selected_algorithm_versions": selected_algorithm_versions,
        "selected_algorithm_details": {
            key: {
                **library_status.get(key, {}),
                "compatible": bool(
                    compatibility.get(key, {}).get("compatible")
                ),
                "compatibility_reason": compatibility.get(key, {}).get(
                    "reason"
                ),
                "champion_eligible": bool(
                    MODEL_CATALOG.get(key, {}).get(
                        "champion_eligible",
                        MODEL_CATALOG.get(key, {}).get("kind") != "anomaly",
                    )
                ),
                "candidate_role": (
                    "diagnostic_only"
                    if MODEL_CATALOG.get(key, {}).get("kind") == "anomaly"
                    else "supervised_candidate"
                ),
            }
            for key in selected_algorithm_ids
        },
        "dependency_status": {
            "state": "ready" if dependency_ready else "blocked",
            "algorithms": {
                key: {
                    "available": bool(
                        library_status.get(key, {}).get("available")
                    ),
                    "compatible": bool(
                        compatibility.get(key, {}).get("compatible")
                    ),
                    "reason": compatibility.get(key, {}).get("reason"),
                }
                for key in selected_algorithm_ids
            },
        },
        "model_compatibility": compatibility,
        "calibration_compatibility": calibration_compatibility,
        "data_type_compatibility": {
            "compatible": not all_missing and not infinite,
            "all_missing_columns": all_missing,
            "infinite_columns": infinite,
            "high_cardinality_columns": high_cardinality,
        },
        "encoding_requirements": {
            "fit_scope": "development_fold_only",
            "required_columns": [
                str(column)
                for column in (
                    X_train.columns if X_train is not None else []
                )
                if not pd.api.types.is_numeric_dtype(X_train[column])
            ],
        },
        "scaling_requirements": {
            "fit_scope": "development_fold_only",
            "policy": "algorithm_specific_pipeline",
        },
        "event_count_compatibility": {
            "compatible": cv_compatible
            and (
                problem_type != "classification"
                or min_class_count >= requested_folds
            ),
            "minimum_class_count": min_class_count
            if problem_type == "classification"
            else None,
            "required_folds": requested_folds,
        },
        "cross_validation_compatibility": {
            "compatible": cv_compatible,
            "owned_by_validation_design": cv_owned_by_design,
            "method": design_fold_method,
            "requested_folds": requested_folds,
            "effective_folds": effective_folds,
            "execution_fold_count": execution_fold_count,
            "exact_fold_bindings": bool(cv_execution_splits),
            "minimum_class_count": min_class_count if problem_type == "classification" else None,
            "read_only": bool(validation_design),
        },
        "missing_value_columns": missing_value_columns,
        "infinite_value_columns": infinite,
        "estimated_memory_mb": estimated_memory_mb,
        "memory_estimate": {
            "estimated_mb": estimated_memory_mb,
            "basis": "development_population_only",
        },
        "recommended_parallelism": recommended_parallel,
        "worker_limit": recommended_parallel,
        "base_fit_count": estimated_fits - calibration_fits,
        "calibration_fit_count": calibration_fits,
        "calibration_supported_algorithm_ids": (
            calibration_supported_algorithm_ids if request.calibrate else []
        ),
        "estimated_fits": estimated_fits,
        "estimated_runtime_seconds": round(
            estimated_fits
            * max(rows, 1)
            * max(columns, 1)
            / 5_000_000,
            1,
        ),
        "large_run_status": (
            "acknowledged"
            if large_run_required and large_run_acknowledged
            else "acknowledgement_required"
            if large_run_required and ready
            else "not_large"
            if not large_run_required
            else "validation_blocked"
        ),
        "large_run": {
            "required": large_run_required,
            "threshold_fits": LARGE_RUN_FIT_THRESHOLD,
            "estimated_fits": estimated_fits,
            "acknowledged": large_run_acknowledged,
            "acknowledgement_required": bool(
                ready and large_run_required and not large_run_acknowledged
            ),
        },
        "final_holdout_sealed": final_holdout_sealed,
        "final_holdout_access": "contract_metadata_only",
        "selection_evidence_source": "development_population_cross_validation",
        "backend_status": "ready" if ready else "blocked",
        "worker_status": "ready" if dependency_ready else "blocked",
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return result
