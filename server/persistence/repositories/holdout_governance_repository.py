from __future__ import annotations

import sqlite3
from hashlib import sha256
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Dict

from ..db import decode_row, json_dumps, now_iso
from .base_repository import BaseRepository


class HoldoutGovernanceConflictError(RuntimeError):
    """An immutable governance identity or contract conflicted."""


class HoldoutGovernanceNotFoundError(RuntimeError):
    """A required durable governance record was not found."""


class HoldoutGovernanceStateError(RuntimeError):
    """A requested final-holdout lifecycle transition is not allowed."""


_SELECTION_INTEGRITY_STATUSES = {
    "legacy_unresolved",
    "verified",
    "invalid_final_holdout_ranking",
    "invalid_selection_provenance",
    "invalid_holdout_isolation",
}
_TERMINAL_SELECTION_INTEGRITY_STATUSES = _SELECTION_INTEGRITY_STATUSES - {"legacy_unresolved"}
_HOLDOUT_ISOLATION_STATUSES = {"legacy_unresolved", "verified", "invalid"}

_DECISION_COLUMNS = (
    "candidate_decision_id",
    "decision_status",
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "feature_manifest_id",
    "feature_manifest_hash",
    "treatment_manifest_id",
    "treatment_manifest_hash",
    "materialization_id",
    "validation_design_id",
    "validation_design_version_id",
    "split_id",
    "final_holdout_partition_id",
    "training_job_id",
    "training_run_id",
    "candidate_id",
    "selected_candidate_contract_hash",
    "selection_metric_name",
    "selection_metric_value",
    "selection_metric_source",
    "selection_metric_created_at",
    "selection_partition_id",
    "fold_definition_id",
    "fold_count",
    "fold_values_json",
    "selection_metric_mean",
    "selection_metric_std",
    "out_of_fold_prediction_artifact_id",
    "threshold_source",
    "locked_threshold",
    "threshold_locked_at",
    "threshold_policy_hash",
    "calibration_source",
    "ranking_snapshot_json",
    "ranking_snapshot_hash",
    "selection_rationale",
    "selection_locked_at",
    "actor",
    "selection_integrity_status",
    "selection_integrity_reason",
    "holdout_isolation_status",
    "holdout_isolation_reason",
    "integrity_classified_at",
    "integrity_classified_by",
    "decision_contract_hash",
    "created_at",
)

_EXPOSURE_COLUMNS = (
    "holdout_exposure_id",
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "validation_design_id",
    "validation_design_version_id",
    "split_id",
    "final_holdout_partition_id",
    "candidate_decision_id",
    "candidate_id",
    "feature_manifest_id",
    "feature_manifest_hash",
    "treatment_manifest_id",
    "treatment_manifest_hash",
    "materialization_id",
    "final_holdout_status",
    "selection_locked_at",
    "sealed_at",
    "first_opened_at",
    "opened_by",
    "evaluated_at",
    "evaluation_package_id",
    "invalidated_at",
    "invalidated_by",
    "invalidation_reason",
    "exposure_contract_hash",
    "created_at",
    "updated_at",
)

_PACKAGE_COLUMNS = (
    "evaluation_package_id",
    "package_status",
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "feature_manifest_id",
    "feature_manifest_hash",
    "treatment_manifest_id",
    "treatment_manifest_hash",
    "materialization_id",
    "validation_design_id",
    "validation_design_version_id",
    "split_id",
    "training_job_id",
    "training_run_id",
    "candidate_id",
    "selected_candidate_contract_hash",
    "candidate_decision_id",
    "holdout_exposure_id",
    "final_holdout_partition_id",
    "selection_metric_name",
    "selection_metric_value",
    "selection_metric_source",
    "selection_metric_created_at",
    "out_of_fold_prediction_artifact_id",
    "locked_threshold",
    "threshold_source",
    "threshold_policy_hash",
    "selection_integrity_status",
    "selection_evidence_json",
    "final_holdout_evidence_json",
    "metric_definitions_json",
    "threshold_policy_json",
    "isolation_evidence_json",
    "canonical_lineage_json",
    "holdout_isolation_status",
    "final_holdout_status",
    "threshold_locked_at",
    "holdout_exposed_at",
    "recommendations_derived_from_final_holdout",
    "package_integrity_status",
    "evaluation_package_contract_hash",
    "content_hash",
    "package_payload_json",
    "created_by",
    "created_at",
)


def _require(record: Mapping[str, Any], *fields: str) -> None:
    missing = [field for field in fields if record.get(field) is None or record.get(field) == ""]
    if missing:
        raise ValueError(f"Missing required holdout-governance fields: {', '.join(missing)}")


def _safe_object(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_array(value: Any) -> list[Any]:
    return (
        list(value)
        if isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        else []
    )


def _json_object(value: Any) -> str:
    return json_dumps(_safe_object(value), {})


def _json_array(value: Any) -> str:
    return json_dumps(_safe_array(value), [])


def _normalize_row(row: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if row is None:
        return None
    normalized = dict(row)
    for field in ("fold_values_json", "ranking_snapshot_json"):
        if field in normalized and not isinstance(normalized.get(field), list):
            normalized[field] = []
    for field in (
        "selection_evidence_json",
        "final_holdout_evidence_json",
        "metric_definitions_json",
        "threshold_policy_json",
        "isolation_evidence_json",
        "canonical_lineage_json",
        "package_payload_json",
    ):
        if field in normalized and not isinstance(normalized.get(field), dict):
            normalized[field] = {}
    if "recommendations_derived_from_final_holdout" in normalized:
        normalized["recommendations_derived_from_final_holdout"] = bool(
            normalized["recommendations_derived_from_final_holdout"]
        )
    return normalized


def _insert_sql(table: str, columns: tuple[str, ...]) -> str:
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _utc_instant(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} requires a timezone-aware UTC timestamp.")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} requires an explicit UTC offset.")
    return parsed.astimezone(timezone.utc)


class HoldoutGovernanceRepository(BaseRepository):
    """Durable, fail-closed selection and final-holdout governance records."""

    def get_selection_decision(self, candidate_decision_id: str) -> Dict[str, Any] | None:
        return _normalize_row(
            self._one(
                "SELECT * FROM candidate_selection_decisions WHERE candidate_decision_id = ?",
                (candidate_decision_id,),
            )
        )

    def get_selection_decision_exact(
        self,
        *,
        candidate_decision_id: str,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        validation_design_id: str,
        validation_design_version_id: str,
        split_id: str,
        training_run_id: str,
        candidate_id: str,
    ) -> Dict[str, Any] | None:
        return _normalize_row(
            self._one(
                """
                SELECT * FROM candidate_selection_decisions
                WHERE candidate_decision_id = ?
                  AND project_id = ?
                  AND dataset_id = ?
                  AND dataset_version_id = ?
                  AND validation_design_id = ?
                  AND validation_design_version_id = ?
                  AND split_id = ?
                  AND training_run_id = ?
                  AND candidate_id = ?
                """,
                (
                    candidate_decision_id,
                    project_id,
                    dataset_id,
                    dataset_version_id,
                    validation_design_id,
                    validation_design_version_id,
                    split_id,
                    training_run_id,
                    candidate_id,
                ),
            )
        )

    def insert_selection_decision_if_absent(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        _require(
            record,
            "candidate_decision_id",
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "feature_manifest_id",
            "validation_design_id",
            "validation_design_version_id",
            "split_id",
            "final_holdout_partition_id",
            "training_job_id",
            "training_run_id",
            "candidate_id",
            "selected_candidate_contract_hash",
            "selection_metric_name",
            "selection_metric_value",
            "selection_metric_source",
            "selection_metric_created_at",
            "selection_partition_id",
            "threshold_source",
            "threshold_locked_at",
            "threshold_policy_hash",
            "calibration_source",
            "ranking_snapshot_hash",
            "decision_contract_hash",
        )
        decision_status = str(record.get("decision_status") or "locked")
        if decision_status not in {"locked", "legacy_proposal"}:
            raise ValueError("candidate decision status must be locked or legacy_proposal")
        if decision_status == "locked":
            _require(record, "selection_locked_at", "actor")
        threshold_source = str(record.get("threshold_source") or "")
        locked_threshold = record.get("locked_threshold")
        if threshold_source != "not_applicable":
            if (
                isinstance(locked_threshold, bool)
                or not isinstance(locked_threshold, (int, float))
            ):
                raise ValueError(
                    "A classification selection decision requires a numeric locked threshold."
                )
        threshold_payload = {
            "locked_threshold": locked_threshold,
            "threshold_source": threshold_source,
            "threshold_locked_at": record.get("threshold_locked_at"),
            "selection_threshold_tuned": False,
        }
        if _canonical_hash(threshold_payload) != str(
            record.get("threshold_policy_hash") or ""
        ):
            raise ValueError("The candidate threshold policy hash is not canonical.")
        ranking_snapshot = _safe_array(record.get("ranking_snapshot_json"))
        if _canonical_hash(ranking_snapshot) != str(
            record.get("ranking_snapshot_hash") or ""
        ):
            raise ValueError(
                "The candidate ranking snapshot hash does not match its canonical payload."
            )
        selected_snapshot = next(
            (
                row
                for row in ranking_snapshot
                if isinstance(row, dict)
                and str(row.get("candidate_id") or "")
                == str(record.get("candidate_id") or "")
            ),
            None,
        )
        if (
            selected_snapshot is None
            or str(selected_snapshot.get("candidate_contract_hash") or "")
            != str(record.get("selected_candidate_contract_hash") or "")
        ):
            raise ValueError(
                "The selected candidate contract hash is absent from the exact ranking snapshot."
            )

        integrity_status = str(record.get("selection_integrity_status") or "legacy_unresolved")
        isolation_status = str(record.get("holdout_isolation_status") or "legacy_unresolved")
        if integrity_status not in _SELECTION_INTEGRITY_STATUSES:
            raise ValueError(f"Unsupported selection integrity status: {integrity_status}")
        if isolation_status not in _HOLDOUT_ISOLATION_STATUSES:
            raise ValueError(f"Unsupported holdout isolation status: {isolation_status}")
        if str(record["selection_metric_source"]) == "final_holdout" and integrity_status != "invalid_final_holdout_ranking":
            raise ValueError("A final-holdout selection source must be explicitly classified as invalid_final_holdout_ranking")
        if integrity_status == "verified" and isolation_status != "verified":
            raise ValueError("Verified selection integrity requires verified holdout isolation")
        if integrity_status == "legacy_unresolved" and isolation_status != "legacy_unresolved":
            raise ValueError("Legacy-unresolved selection integrity requires legacy-unresolved holdout isolation")
        if integrity_status in _TERMINAL_SELECTION_INTEGRITY_STATUSES:
            _require(record, "selection_integrity_reason", "holdout_isolation_reason")
            if not (record.get("integrity_classified_by") or record.get("actor")):
                raise ValueError("A terminal selection-integrity classification requires an actor")

        timestamp = str(record.get("created_at") or now_iso())
        payload: Dict[str, Any] = {
            **record,
            "decision_status": decision_status,
            "fold_values_json": _json_array(record.get("fold_values_json")),
            "ranking_snapshot_json": _json_array(ranking_snapshot),
            "selection_integrity_status": integrity_status,
            "holdout_isolation_status": isolation_status,
            "created_at": timestamp,
        }
        if integrity_status in _TERMINAL_SELECTION_INTEGRITY_STATUSES:
            payload["integrity_classified_at"] = record.get("integrity_classified_at") or timestamp
            payload["integrity_classified_by"] = record.get("integrity_classified_by") or record.get("actor")

        try:
            with self.database.transaction() as connection:
                connection.execute(
                    _insert_sql("candidate_selection_decisions", _DECISION_COLUMNS),
                    tuple(payload.get(column) for column in _DECISION_COLUMNS),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.get_selection_decision(str(record["candidate_decision_id"]))
            if (
                existing
                and existing.get("decision_contract_hash") == record.get("decision_contract_hash")
                and existing.get("project_id") == record.get("project_id")
                and existing.get("training_run_id") == record.get("training_run_id")
                and existing.get("candidate_id") == record.get("candidate_id")
            ):
                return existing
            raise HoldoutGovernanceConflictError(
                "Candidate selection decision conflicts with an existing immutable lock."
            ) from exc
        return self.get_selection_decision(str(record["candidate_decision_id"])) or {}

    def insert_selection_decision_if_unexposed(
        self,
        record: Mapping[str, Any],
        *,
        final_holdout_partition_id: str,
    ) -> Dict[str, Any]:
        """Insert an immutable decision only while its exact holdout is unexposed.

        ``BEGIN IMMEDIATE`` serializes this check with exposure creation. An
        idempotent replay of the same already-persisted decision remains
        readable even after exposure; a different decision cannot be locked.
        """
        if not final_holdout_partition_id:
            raise ValueError(
                "An exact final_holdout_partition_id is required to lock a decision."
            )
        candidate_decision_id = str(record.get("candidate_decision_id") or "")
        with self.database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = decode_row(
                connection.execute(
                    "SELECT * FROM candidate_selection_decisions WHERE candidate_decision_id = ?",
                    (candidate_decision_id,),
                ).fetchone()
            )
            if existing is not None:
                normalized = _normalize_row(existing) or {}
                if (
                    normalized.get("decision_contract_hash")
                    == record.get("decision_contract_hash")
                    and normalized.get("project_id") == record.get("project_id")
                    and normalized.get("training_run_id")
                    == record.get("training_run_id")
                    and normalized.get("candidate_id")
                    == record.get("candidate_id")
                ):
                    return normalized
                raise HoldoutGovernanceConflictError(
                    "Candidate selection decision conflicts with an existing immutable lock."
                )
            exposure = decode_row(
                connection.execute(
                    """
                    SELECT * FROM holdout_exposures
                    WHERE project_id = ?
                      AND dataset_id = ?
                      AND dataset_version_id = ?
                      AND validation_design_id = ?
                      AND validation_design_version_id = ?
                      AND split_id = ?
                      AND final_holdout_partition_id = ?
                    """,
                    (
                        record.get("project_id"),
                        record.get("dataset_id"),
                        record.get("dataset_version_id"),
                        record.get("validation_design_id"),
                        record.get("validation_design_version_id"),
                        record.get("split_id"),
                        final_holdout_partition_id,
                    ),
                ).fetchone()
            )
            if exposure is not None:
                raise HoldoutGovernanceStateError(
                    "The exact final-holdout partition already has a durable "
                    "exposure record; a new verified candidate decision cannot be locked."
                )

            # Apply the same value-level validation as the public insert path
            # before performing the write in this transaction.
            _require(
                record,
                "candidate_decision_id",
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "feature_manifest_id",
                "validation_design_id",
                "validation_design_version_id",
                "split_id",
                "final_holdout_partition_id",
                "training_job_id",
                "training_run_id",
                "candidate_id",
                "selected_candidate_contract_hash",
                "selection_metric_name",
                "selection_metric_value",
                "selection_metric_source",
                "selection_metric_created_at",
                "selection_partition_id",
                "threshold_source",
                "threshold_locked_at",
                "threshold_policy_hash",
                "calibration_source",
                "ranking_snapshot_hash",
                "decision_contract_hash",
            )
            if str(record.get("decision_status") or "locked") != "locked":
                raise ValueError("Only a locked candidate decision may use the unexposed insert path.")
            _require(record, "selection_locked_at", "actor")
            threshold_source = str(record.get("threshold_source") or "")
            locked_threshold = record.get("locked_threshold")
            if threshold_source != "not_applicable" and (
                isinstance(locked_threshold, bool)
                or not isinstance(locked_threshold, (int, float))
            ):
                raise ValueError(
                    "A classification selection decision requires a numeric locked threshold."
                )
            threshold_payload = {
                "locked_threshold": locked_threshold,
                "threshold_source": threshold_source,
                "threshold_locked_at": record.get("threshold_locked_at"),
                "selection_threshold_tuned": False,
            }
            if _canonical_hash(threshold_payload) != str(
                record.get("threshold_policy_hash") or ""
            ):
                raise ValueError("The candidate threshold policy hash is not canonical.")
            ranking_snapshot = _safe_array(record.get("ranking_snapshot_json"))
            if _canonical_hash(ranking_snapshot) != str(
                record.get("ranking_snapshot_hash") or ""
            ):
                raise ValueError(
                    "The candidate ranking snapshot hash does not match its canonical payload."
                )
            selected_snapshot = next(
                (
                    row
                    for row in ranking_snapshot
                    if isinstance(row, dict)
                    and str(row.get("candidate_id") or "")
                    == str(record.get("candidate_id") or "")
                ),
                None,
            )
            if (
                selected_snapshot is None
                or str(selected_snapshot.get("candidate_contract_hash") or "")
                != str(record.get("selected_candidate_contract_hash") or "")
            ):
                raise ValueError(
                    "The selected candidate contract hash is absent from the exact ranking snapshot."
                )
            integrity_status = str(
                record.get("selection_integrity_status") or "legacy_unresolved"
            )
            isolation_status = str(
                record.get("holdout_isolation_status") or "legacy_unresolved"
            )
            if integrity_status != "verified" or isolation_status != "verified":
                raise ValueError(
                    "Only verified selection and holdout-isolation evidence may be locked."
                )
            payload: Dict[str, Any] = {
                **record,
                "decision_status": "locked",
                "fold_values_json": _json_array(record.get("fold_values_json")),
                "ranking_snapshot_json": _json_array(ranking_snapshot),
                "selection_integrity_status": integrity_status,
                "holdout_isolation_status": isolation_status,
                "created_at": str(record.get("created_at") or now_iso()),
            }
            connection.execute(
                _insert_sql("candidate_selection_decisions", _DECISION_COLUMNS),
                tuple(payload.get(column) for column in _DECISION_COLUMNS),
            )
            inserted = decode_row(
                connection.execute(
                    "SELECT * FROM candidate_selection_decisions WHERE candidate_decision_id = ?",
                    (candidate_decision_id,),
                ).fetchone()
            )
        return _normalize_row(inserted) or {}

    def classify_selection_integrity(
        self,
        candidate_decision_id: str,
        *,
        selection_integrity_status: str,
        holdout_isolation_status: str,
        reason: str,
        classified_by: str,
        classified_at: str | None = None,
    ) -> Dict[str, Any]:
        if selection_integrity_status not in _TERMINAL_SELECTION_INTEGRITY_STATUSES:
            raise ValueError("Selection integrity classification must be a terminal explicit status.")
        if holdout_isolation_status not in {"verified", "invalid"}:
            raise ValueError("Holdout isolation classification must be verified or invalid.")
        if not reason or not classified_by:
            raise ValueError("Integrity classification requires a reason and actor.")
        if selection_integrity_status == "verified" and holdout_isolation_status != "verified":
            raise ValueError("Verified selection integrity requires verified holdout isolation.")

        timestamp = classified_at or now_iso()
        with self.database.transaction() as connection:
            row = decode_row(
                connection.execute(
                    "SELECT * FROM candidate_selection_decisions WHERE candidate_decision_id = ?",
                    (candidate_decision_id,),
                ).fetchone()
            )
            if row is None:
                raise HoldoutGovernanceNotFoundError(
                    f"Candidate selection decision {candidate_decision_id} was not found."
                )
            current_integrity = str(row.get("selection_integrity_status") or "legacy_unresolved")
            current_isolation = str(row.get("holdout_isolation_status") or "legacy_unresolved")
            if current_integrity == selection_integrity_status and current_isolation == holdout_isolation_status:
                return _normalize_row(row) or {}
            if current_integrity != "legacy_unresolved" or current_isolation != "legacy_unresolved":
                raise HoldoutGovernanceConflictError(
                    "A terminal selection-integrity classification cannot be replaced."
                )
            connection.execute(
                """
                UPDATE candidate_selection_decisions
                SET selection_integrity_status = ?,
                    selection_integrity_reason = ?,
                    holdout_isolation_status = ?,
                    holdout_isolation_reason = ?,
                    integrity_classified_at = ?,
                    integrity_classified_by = ?
                WHERE candidate_decision_id = ?
                """,
                (
                    selection_integrity_status,
                    reason,
                    holdout_isolation_status,
                    reason,
                    timestamp,
                    classified_by,
                    candidate_decision_id,
                ),
            )
        return self.get_selection_decision(candidate_decision_id) or {}

    def get_holdout_exposure(self, holdout_exposure_id: str) -> Dict[str, Any] | None:
        return _normalize_row(
            self._one(
                "SELECT * FROM holdout_exposures WHERE holdout_exposure_id = ?",
                (holdout_exposure_id,),
            )
        )

    def get_holdout_exposure_exact(
        self,
        *,
        holdout_exposure_id: str,
        project_id: str,
        dataset_version_id: str,
        split_id: str,
        final_holdout_partition_id: str,
        candidate_decision_id: str,
        candidate_id: str,
    ) -> Dict[str, Any] | None:
        return _normalize_row(
            self._one(
                """
                SELECT * FROM holdout_exposures
                WHERE holdout_exposure_id = ?
                  AND project_id = ?
                  AND dataset_version_id = ?
                  AND split_id = ?
                  AND final_holdout_partition_id = ?
                  AND candidate_decision_id = ?
                  AND candidate_id = ?
                """,
                (
                    holdout_exposure_id,
                    project_id,
                    dataset_version_id,
                    split_id,
                    final_holdout_partition_id,
                    candidate_decision_id,
                    candidate_id,
                ),
            )
        )

    def get_holdout_exposure_for_partition(
        self,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        validation_design_id: str,
        validation_design_version_id: str,
        split_id: str,
        final_holdout_partition_id: str,
    ) -> Dict[str, Any] | None:
        """Return the one durable exposure bound to an exact holdout partition.

        The database enforces one exposure per project/version/split/partition.
        Requiring the complete Validation Design identity here prevents callers
        from substituting a latest or partial-match exposure.
        """
        return _normalize_row(
            self._one(
                """
                SELECT * FROM holdout_exposures
                WHERE project_id = ?
                  AND dataset_id = ?
                  AND dataset_version_id = ?
                  AND validation_design_id = ?
                  AND validation_design_version_id = ?
                  AND split_id = ?
                  AND final_holdout_partition_id = ?
                """,
                (
                    project_id,
                    dataset_id,
                    dataset_version_id,
                    validation_design_id,
                    validation_design_version_id,
                    split_id,
                    final_holdout_partition_id,
                ),
            )
        )

    def invalidate_holdout_exposure_for_partition(
        self,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        validation_design_id: str,
        validation_design_version_id: str,
        split_id: str,
        final_holdout_partition_id: str,
        reason: str,
        invalidated_by: str,
        invalidated_at: str | None = None,
    ) -> Dict[str, Any] | None:
        """Atomically invalidate the exposure for one exact governed partition."""
        identity = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "validation_design_id": validation_design_id,
            "validation_design_version_id": validation_design_version_id,
            "split_id": split_id,
            "final_holdout_partition_id": final_holdout_partition_id,
        }
        _require(identity, *identity.keys())
        if not reason or not invalidated_by:
            raise ValueError("Invalidating a final holdout requires a reason and actor.")
        timestamp = invalidated_at or now_iso()
        with self.database.transaction() as connection:
            row = decode_row(
                connection.execute(
                    """
                    SELECT * FROM holdout_exposures
                    WHERE project_id = ?
                      AND dataset_id = ?
                      AND dataset_version_id = ?
                      AND validation_design_id = ?
                      AND validation_design_version_id = ?
                      AND split_id = ?
                      AND final_holdout_partition_id = ?
                    """,
                    tuple(identity.values()),
                ).fetchone()
            )
            if row is None:
                return None
            if row.get("final_holdout_status") == "invalidated":
                return _normalize_row(row)
            cursor = connection.execute(
                """
                UPDATE holdout_exposures
                SET final_holdout_status = 'invalidated',
                    invalidated_at = ?,
                    invalidated_by = ?,
                    invalidation_reason = ?,
                    updated_at = ?
                WHERE project_id = ?
                  AND dataset_id = ?
                  AND dataset_version_id = ?
                  AND validation_design_id = ?
                  AND validation_design_version_id = ?
                  AND split_id = ?
                  AND final_holdout_partition_id = ?
                  AND final_holdout_status IN ('sealed', 'opened', 'evaluated')
                """,
                (
                    timestamp,
                    invalidated_by,
                    reason,
                    timestamp,
                    *identity.values(),
                ),
            )
            if cursor.rowcount != 1:
                raise HoldoutGovernanceConflictError(
                    "The exact final-holdout exposure changed during invalidation."
                )
        return self.get_holdout_exposure_for_partition(**identity)

    def seal_holdout_exposure_if_absent(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        _require(
            record,
            "holdout_exposure_id",
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "validation_design_id",
            "validation_design_version_id",
            "split_id",
            "final_holdout_partition_id",
            "candidate_decision_id",
            "candidate_id",
            "feature_manifest_id",
            "feature_manifest_hash",
            "treatment_manifest_id",
            "treatment_manifest_hash",
            "materialization_id",
            "exposure_contract_hash",
        )
        if str(record.get("final_holdout_status") or "sealed") != "sealed":
            raise ValueError("A new final-holdout exposure must begin sealed.")
        decision = self.get_selection_decision(str(record["candidate_decision_id"]))
        if decision is None:
            raise HoldoutGovernanceNotFoundError("The candidate decision must exist before the holdout is sealed.")
        if (
            decision.get("decision_status") != "locked"
            or decision.get("selection_integrity_status") != "verified"
            or decision.get("holdout_isolation_status") != "verified"
        ):
            raise HoldoutGovernanceStateError(
                "The final holdout may be sealed only for an exact locked, verified candidate decision."
            )
        for field in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "validation_design_id",
            "validation_design_version_id",
            "split_id",
            "final_holdout_partition_id",
            "candidate_id",
            "feature_manifest_id",
            "feature_manifest_hash",
            "treatment_manifest_id",
            "treatment_manifest_hash",
            "materialization_id",
        ):
            if decision.get(field) != record.get(field):
                raise HoldoutGovernanceConflictError(
                    f"Holdout exposure {field} does not match the locked candidate decision."
                )
        if record.get("selection_locked_at") not in (None, decision.get("selection_locked_at")):
            raise HoldoutGovernanceConflictError(
                "Holdout exposure selection lock time does not match the candidate decision."
            )

        timestamp = str(record.get("created_at") or now_iso())
        payload: Dict[str, Any] = {
            **record,
            "final_holdout_status": "sealed",
            "selection_locked_at": decision.get("selection_locked_at"),
            "sealed_at": record.get("sealed_at") or timestamp,
            "created_at": timestamp,
            "updated_at": record.get("updated_at") or timestamp,
        }
        try:
            with self.database.transaction() as connection:
                # Serialize the durable exposure boundary with the atomic
                # decision-lock path.  Whichever transaction acquires the
                # write reservation first establishes the authoritative
                # ordering; a later decision lock will observe this row and
                # fail closed.
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    _insert_sql("holdout_exposures", _EXPOSURE_COLUMNS),
                    tuple(payload.get(column) for column in _EXPOSURE_COLUMNS),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.get_holdout_exposure(str(record["holdout_exposure_id"]))
            if (
                existing
                and existing.get("exposure_contract_hash") == record.get("exposure_contract_hash")
                and existing.get("candidate_decision_id") == record.get("candidate_decision_id")
            ):
                return existing
            raise HoldoutGovernanceConflictError(
                "Final-holdout exposure conflicts with an existing governed partition."
            ) from exc
        return self.get_holdout_exposure(str(record["holdout_exposure_id"])) or {}

    def mark_holdout_opened(
        self,
        holdout_exposure_id: str,
        *,
        opened_by: str,
        opened_at: str | None = None,
    ) -> Dict[str, Any]:
        if not opened_by:
            raise ValueError("Opening the final holdout requires an actor.")
        timestamp = opened_at or now_iso()
        with self.database.transaction() as connection:
            row = decode_row(
                connection.execute(
                    "SELECT * FROM holdout_exposures WHERE holdout_exposure_id = ?",
                    (holdout_exposure_id,),
                ).fetchone()
            )
            if row is None:
                raise HoldoutGovernanceNotFoundError(f"Holdout exposure {holdout_exposure_id} was not found.")
            status = str(row.get("final_holdout_status"))
            if status in {"opened", "evaluated"}:
                return _normalize_row(row) or {}
            if status != "sealed":
                raise HoldoutGovernanceStateError(f"A {status} holdout exposure cannot be opened.")
            connection.execute(
                """
                UPDATE holdout_exposures
                SET final_holdout_status = 'opened',
                    first_opened_at = ?,
                    opened_by = ?,
                    updated_at = ?
                WHERE holdout_exposure_id = ? AND final_holdout_status = 'sealed'
                """,
                (timestamp, opened_by, timestamp, holdout_exposure_id),
            )
        return self.get_holdout_exposure(holdout_exposure_id) or {}

    def mark_holdout_evaluated(
        self,
        holdout_exposure_id: str,
        *,
        evaluation_package_id: str,
        evaluated_at: str | None = None,
    ) -> Dict[str, Any]:
        if not evaluation_package_id:
            raise ValueError("Completing final-holdout evaluation requires an evaluation package.")
        timestamp = evaluated_at or now_iso()
        with self.database.transaction() as connection:
            row = decode_row(
                connection.execute(
                    "SELECT * FROM holdout_exposures WHERE holdout_exposure_id = ?",
                    (holdout_exposure_id,),
                ).fetchone()
            )
            if row is None:
                raise HoldoutGovernanceNotFoundError(f"Holdout exposure {holdout_exposure_id} was not found.")
            status = str(row.get("final_holdout_status"))
            if status == "evaluated":
                if row.get("evaluation_package_id") != evaluation_package_id:
                    raise HoldoutGovernanceConflictError(
                        "The evaluated holdout is already bound to another immutable package."
                    )
                return _normalize_row(row) or {}
            if status != "opened":
                raise HoldoutGovernanceStateError(f"A {status} holdout exposure cannot be marked evaluated.")
            package = decode_row(
                connection.execute(
                    "SELECT * FROM evaluation_packages WHERE evaluation_package_id = ?",
                    (evaluation_package_id,),
                ).fetchone()
            )
            if package is None:
                raise HoldoutGovernanceNotFoundError(
                    "The immutable evaluation package must be persisted before the holdout is marked evaluated."
                )
            if (
                package.get("holdout_exposure_id") != holdout_exposure_id
                or package.get("candidate_decision_id") != row.get("candidate_decision_id")
                or package.get("candidate_id") != row.get("candidate_id")
            ):
                raise HoldoutGovernanceConflictError(
                    "Evaluation package identity does not match the opened holdout exposure."
                )
            connection.execute(
                """
                UPDATE holdout_exposures
                SET final_holdout_status = 'evaluated',
                    evaluated_at = ?,
                    evaluation_package_id = ?,
                    updated_at = ?
                WHERE holdout_exposure_id = ? AND final_holdout_status = 'opened'
                """,
                (timestamp, evaluation_package_id, timestamp, holdout_exposure_id),
            )
        return self.get_holdout_exposure(holdout_exposure_id) or {}

    def invalidate_holdout_exposure(
        self,
        holdout_exposure_id: str,
        *,
        reason: str,
        invalidated_by: str,
        invalidated_at: str | None = None,
    ) -> Dict[str, Any]:
        if not reason or not invalidated_by:
            raise ValueError("Invalidating a final holdout requires a reason and actor.")
        timestamp = invalidated_at or now_iso()
        with self.database.transaction() as connection:
            row = decode_row(
                connection.execute(
                    "SELECT * FROM holdout_exposures WHERE holdout_exposure_id = ?",
                    (holdout_exposure_id,),
                ).fetchone()
            )
            if row is None:
                raise HoldoutGovernanceNotFoundError(f"Holdout exposure {holdout_exposure_id} was not found.")
            if row.get("final_holdout_status") == "invalidated":
                return _normalize_row(row) or {}
            connection.execute(
                """
                UPDATE holdout_exposures
                SET final_holdout_status = 'invalidated',
                    invalidated_at = ?,
                    invalidated_by = ?,
                    invalidation_reason = ?,
                    updated_at = ?
                WHERE holdout_exposure_id = ?
                  AND final_holdout_status IN ('sealed', 'opened', 'evaluated')
                """,
                (timestamp, invalidated_by, reason, timestamp, holdout_exposure_id),
            )
        return self.get_holdout_exposure(holdout_exposure_id) or {}

    def get_evaluation_package(self, evaluation_package_id: str) -> Dict[str, Any] | None:
        return _normalize_row(
            self._one(
                "SELECT * FROM evaluation_packages WHERE evaluation_package_id = ?",
                (evaluation_package_id,),
            )
        )

    def get_evaluation_package_exact(
        self,
        *,
        evaluation_package_id: str,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        training_run_id: str,
        candidate_id: str,
        candidate_decision_id: str,
        holdout_exposure_id: str,
    ) -> Dict[str, Any] | None:
        package = _normalize_row(
            self._one(
                """
                SELECT * FROM evaluation_packages
                WHERE evaluation_package_id = ?
                  AND project_id = ?
                  AND dataset_id = ?
                  AND dataset_version_id = ?
                  AND training_run_id = ?
                  AND candidate_id = ?
                  AND candidate_decision_id = ?
                  AND holdout_exposure_id = ?
                """,
                (
                    evaluation_package_id,
                    project_id,
                    dataset_id,
                    dataset_version_id,
                    training_run_id,
                    candidate_id,
                    candidate_decision_id,
                    holdout_exposure_id,
                ),
            )
        )
        if package is None:
            return None
        exposure = self.get_holdout_exposure(str(holdout_exposure_id))
        if (
            exposure is None
            or exposure.get("final_holdout_status") != "evaluated"
            or exposure.get("evaluation_package_id") != evaluation_package_id
        ):
            return None
        payload = package.get("package_payload_json")
        if (
            not isinstance(payload, dict)
            or not payload
            or _canonical_hash(payload) != str(package.get("content_hash") or "")
        ):
            return None
        expected_contract_hash = _canonical_hash(
            {
                "evaluation_package_id": evaluation_package_id,
                "completion_content_hash": payload.get(
                    "completion_content_hash"
                ),
                "holdout_prediction_digest": payload.get(
                    "holdout_prediction_digest"
                ),
                "candidate_decision_id": candidate_decision_id,
                "holdout_exposure_id": holdout_exposure_id,
                "content_hash": package.get("content_hash"),
            }
        )
        if expected_contract_hash != str(
            package.get("evaluation_package_contract_hash") or ""
        ):
            return None
        return package

    def insert_evaluation_package_if_absent(
        self,
        record: Mapping[str, Any],
        *,
        _connection: sqlite3.Connection | None = None,
    ) -> Dict[str, Any]:
        _require(
            record,
            "evaluation_package_id",
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "feature_manifest_id",
            "validation_design_id",
            "validation_design_version_id",
            "split_id",
            "training_job_id",
            "training_run_id",
            "candidate_id",
            "selected_candidate_contract_hash",
            "candidate_decision_id",
            "holdout_exposure_id",
            "final_holdout_partition_id",
            "selection_metric_name",
            "selection_metric_value",
            "selection_metric_source",
            "selection_metric_created_at",
            "out_of_fold_prediction_artifact_id",
            "threshold_source",
            "threshold_policy_hash",
            "evaluation_package_contract_hash",
            "content_hash",
        )
        package_status = str(record.get("package_status") or "complete")
        selection_integrity_status = str(record.get("selection_integrity_status") or "legacy_unresolved")
        isolation_status = str(record.get("holdout_isolation_status") or "legacy_unresolved")
        package_integrity_status = str(record.get("package_integrity_status") or "legacy_unresolved")
        final_holdout_status = str(record.get("final_holdout_status") or "evaluated")
        recommendations_from_holdout = bool(record.get("recommendations_derived_from_final_holdout"))
        if selection_integrity_status not in _SELECTION_INTEGRITY_STATUSES:
            raise ValueError(f"Unsupported selection integrity status: {selection_integrity_status}")
        if isolation_status not in _HOLDOUT_ISOLATION_STATUSES:
            raise ValueError(f"Unsupported holdout isolation status: {isolation_status}")
        if str(record["selection_metric_source"]) == "final_holdout" and selection_integrity_status != "invalid_final_holdout_ranking":
            raise ValueError("A final-holdout selection source must be explicitly classified as invalid_final_holdout_ranking")
        if package_status == "complete":
            _require(
                record,
                "threshold_locked_at",
                "holdout_exposed_at",
                "created_by",
            )
            if (
                selection_integrity_status != "verified"
                or isolation_status != "verified"
                or package_integrity_status != "verified"
                or final_holdout_status != "evaluated"
                or recommendations_from_holdout
            ):
                raise ValueError(
                    "A complete package requires verified selection/isolation/package integrity, "
                    "an evaluated holdout, and no holdout-derived recommendations."
                )

        decision = self.get_selection_decision(str(record["candidate_decision_id"]))
        exposure = self.get_holdout_exposure(str(record["holdout_exposure_id"]))
        if decision is None or exposure is None:
            raise HoldoutGovernanceNotFoundError(
                "The exact candidate decision and opened holdout exposure must exist before package persistence."
            )
        for field in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "feature_manifest_id",
            "feature_manifest_hash",
            "treatment_manifest_id",
            "treatment_manifest_hash",
            "materialization_id",
            "validation_design_id",
            "validation_design_version_id",
            "split_id",
            "training_job_id",
            "training_run_id",
            "candidate_id",
            "selected_candidate_contract_hash",
        ):
            if decision.get(field) != record.get(field):
                raise HoldoutGovernanceConflictError(
                    f"Evaluation package {field} does not match the immutable candidate decision."
                )
        threshold_policy = _safe_object(record.get("threshold_policy_json"))
        if package_status == "complete" and (
            threshold_policy.get("locked_threshold")
            != decision.get("locked_threshold")
            or threshold_policy.get("threshold_source")
            != decision.get("threshold_source")
            or threshold_policy.get("threshold_locked_at")
            != decision.get("threshold_locked_at")
            or threshold_policy.get("threshold_policy_hash")
            != decision.get("threshold_policy_hash")
            or record.get("threshold_locked_at")
            != decision.get("threshold_locked_at")
        ):
            raise HoldoutGovernanceConflictError(
                "The Evaluation package threshold does not exactly match the "
                "durable pre-exposure candidate threshold lock."
            )
        for field in (
            "selection_metric_name",
            "selection_metric_value",
            "selection_metric_source",
            "selection_metric_created_at",
            "out_of_fold_prediction_artifact_id",
            "locked_threshold",
            "threshold_source",
            "threshold_policy_hash",
            "selection_integrity_status",
            "holdout_isolation_status",
        ):
            if decision.get(field) != record.get(field):
                raise HoldoutGovernanceConflictError(
                    f"Evaluation package {field} does not match the immutable candidate decision."
                )
        selection_evidence = _safe_object(record.get("selection_evidence_json"))
        if package_status == "complete" and (
            selection_evidence.get("out_of_fold_prediction_artifact_id")
            != decision.get("out_of_fold_prediction_artifact_id")
            or selection_evidence.get("selection_metric_created_at")
            != decision.get("selection_metric_created_at")
        ):
            raise HoldoutGovernanceConflictError(
                "The Evaluation package selection evidence does not match the "
                "durable OOF artifact and metric timestamp."
            )
        if (
            exposure.get("candidate_decision_id") != record.get("candidate_decision_id")
            or exposure.get("candidate_id") != record.get("candidate_id")
            or exposure.get("final_holdout_partition_id") != record.get("final_holdout_partition_id")
        ):
            raise HoldoutGovernanceConflictError(
                "Evaluation package identity does not match the final-holdout exposure."
            )
        if exposure.get("final_holdout_status") not in {"opened", "evaluated"}:
            raise HoldoutGovernanceStateError(
                "The final holdout must be opened by the governed Evaluation boundary before package persistence."
            )
        if package_status == "complete" and decision.get("decision_status") != "locked":
            raise HoldoutGovernanceStateError(
                "A complete evaluation package requires an exact locked candidate decision."
            )
        if record.get("holdout_exposed_at") != exposure.get("first_opened_at"):
            raise HoldoutGovernanceConflictError(
                "Evaluation package holdout exposure time does not match the durable first-opened time."
            )
        if package_status == "complete":
            threshold_locked_at = _utc_instant(
                record.get("threshold_locked_at"),
                "threshold_locked_at",
            )
            first_opened_at = _utc_instant(
                exposure.get("first_opened_at"),
                "first_opened_at",
            )
            if threshold_locked_at >= first_opened_at:
                raise HoldoutGovernanceStateError(
                    "The evaluation threshold must be locked before final-holdout exposure."
                )

        package_payload = _safe_object(record.get("package_payload_json"))
        if package_status == "complete" and not package_payload:
            raise ValueError(
                "A complete Evaluation package requires a nonempty immutable payload."
            )
        content_hash = _canonical_hash(package_payload)
        if content_hash != str(record.get("content_hash") or ""):
            raise HoldoutGovernanceConflictError(
                "The Evaluation package content hash does not match its canonical payload."
            )
        expected_package_contract_hash = _canonical_hash(
            {
                "evaluation_package_id": record.get("evaluation_package_id"),
                "completion_content_hash": package_payload.get(
                    "completion_content_hash"
                ),
                "holdout_prediction_digest": package_payload.get(
                    "holdout_prediction_digest"
                ),
                "candidate_decision_id": record.get(
                    "candidate_decision_id"
                ),
                "holdout_exposure_id": record.get("holdout_exposure_id"),
                "content_hash": content_hash,
            }
        )
        if expected_package_contract_hash != str(
            record.get("evaluation_package_contract_hash") or ""
        ):
            raise HoldoutGovernanceConflictError(
                "The Evaluation package contract hash is not canonical."
            )

        payload: Dict[str, Any] = {
            **record,
            "package_status": package_status,
            "selection_integrity_status": selection_integrity_status,
            "selection_evidence_json": _json_object(selection_evidence),
            "final_holdout_evidence_json": _json_object(record.get("final_holdout_evidence_json")),
            "metric_definitions_json": _json_object(record.get("metric_definitions_json")),
            "threshold_policy_json": _json_object(threshold_policy),
            "isolation_evidence_json": _json_object(record.get("isolation_evidence_json")),
            "canonical_lineage_json": _json_object(record.get("canonical_lineage_json")),
            "package_payload_json": _json_object(package_payload),
            "holdout_isolation_status": isolation_status,
            "final_holdout_status": final_holdout_status,
            "recommendations_derived_from_final_holdout": int(recommendations_from_holdout),
            "package_integrity_status": package_integrity_status,
            "created_at": record.get("created_at") or now_iso(),
        }
        if _connection is not None:
            try:
                _connection.execute(
                    _insert_sql("evaluation_packages", _PACKAGE_COLUMNS),
                    tuple(payload.get(column) for column in _PACKAGE_COLUMNS),
                )
            except sqlite3.IntegrityError as exc:
                existing = _normalize_row(
                    decode_row(
                        _connection.execute(
                            "SELECT * FROM evaluation_packages WHERE evaluation_package_id = ?",
                            (record["evaluation_package_id"],),
                        ).fetchone()
                    )
                )
                if (
                    existing
                    and existing.get("evaluation_package_contract_hash")
                    == record.get("evaluation_package_contract_hash")
                    and existing.get("content_hash") == record.get("content_hash")
                    and existing.get("candidate_decision_id")
                    == record.get("candidate_decision_id")
                ):
                    return existing
                raise HoldoutGovernanceConflictError(
                    "Evaluation package conflicts with an existing immutable package."
                ) from exc
            inserted = decode_row(
                _connection.execute(
                    "SELECT * FROM evaluation_packages WHERE evaluation_package_id = ?",
                    (record["evaluation_package_id"],),
                ).fetchone()
            )
            return _normalize_row(inserted) or {}

        try:
            with self.database.transaction() as connection:
                connection.execute(
                    _insert_sql("evaluation_packages", _PACKAGE_COLUMNS),
                    tuple(payload.get(column) for column in _PACKAGE_COLUMNS),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.get_evaluation_package(str(record["evaluation_package_id"]))
            if (
                existing
                and existing.get("evaluation_package_contract_hash") == record.get("evaluation_package_contract_hash")
                and existing.get("content_hash") == record.get("content_hash")
                and existing.get("candidate_decision_id") == record.get("candidate_decision_id")
            ):
                return existing
            raise HoldoutGovernanceConflictError(
                "Evaluation package conflicts with an existing immutable package."
            ) from exc
        return self.get_evaluation_package(str(record["evaluation_package_id"])) or {}

    def complete_evaluation_package(
        self,
        record: Mapping[str, Any],
        *,
        exposure_id: str,
        evaluated_at: str | None = None,
    ) -> Dict[str, Any]:
        """Atomically persist a complete package and transition its exposure.

        Any validation, insert, or lifecycle failure rolls back both changes,
        preventing a durable package-only or evaluated-exposure-only state.
        """
        if str(record.get("holdout_exposure_id") or "") != str(
            exposure_id or ""
        ):
            raise HoldoutGovernanceConflictError(
                "The Evaluation package does not match the requested holdout exposure."
            )
        timestamp = evaluated_at or now_iso()
        with self.database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exposure = decode_row(
                connection.execute(
                    "SELECT * FROM holdout_exposures WHERE holdout_exposure_id = ?",
                    (exposure_id,),
                ).fetchone()
            )
            if exposure is None:
                raise HoldoutGovernanceNotFoundError(
                    f"Holdout exposure {exposure_id} was not found."
                )
            status = str(exposure.get("final_holdout_status") or "")
            package_id = str(record.get("evaluation_package_id") or "")
            if status == "evaluated":
                if exposure.get("evaluation_package_id") != package_id:
                    raise HoldoutGovernanceConflictError(
                        "The evaluated holdout is already bound to another immutable package."
                    )
            elif status != "opened":
                raise HoldoutGovernanceStateError(
                    f"A {status} holdout exposure cannot complete Evaluation."
                )

            package = self.insert_evaluation_package_if_absent(
                record,
                _connection=connection,
            )
            if status == "opened":
                cursor = connection.execute(
                    """
                    UPDATE holdout_exposures
                    SET final_holdout_status = 'evaluated',
                        evaluated_at = ?,
                        evaluation_package_id = ?,
                        updated_at = ?
                    WHERE holdout_exposure_id = ?
                      AND final_holdout_status = 'opened'
                    """,
                    (timestamp, package_id, timestamp, exposure_id),
                )
                if cursor.rowcount != 1:
                    raise HoldoutGovernanceConflictError(
                        "The holdout exposure changed while Evaluation was completing."
                    )
            completed_exposure = decode_row(
                connection.execute(
                    "SELECT * FROM holdout_exposures WHERE holdout_exposure_id = ?",
                    (exposure_id,),
                ).fetchone()
            )
            if (
                completed_exposure is None
                or completed_exposure.get("final_holdout_status") != "evaluated"
                or completed_exposure.get("evaluation_package_id") != package_id
            ):
                raise HoldoutGovernanceStateError(
                    "Evaluation did not reach an atomic durable terminal state."
                )
        return package
