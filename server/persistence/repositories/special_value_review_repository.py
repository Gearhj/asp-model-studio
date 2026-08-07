from __future__ import annotations

import hashlib
import math
import sqlite3
import uuid
from typing import Any, Dict, Mapping

from ..db import decode_row, json_dumps, now_iso
from .base_repository import BaseRepository


class SpecialValueReviewConflictError(RuntimeError):
    """The caller attempted to update a stale durable review revision."""

    def __init__(self, message: str, *, current: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.current = dict(current or {})


class SpecialValueReviewStateError(RuntimeError):
    """The exact durable review is missing or internally contradictory."""


def _review_id(project_id: str, dataset_id: str, dataset_version_id: str) -> str:
    digest = hashlib.sha256(
        f"{project_id}\x1f{dataset_id}\x1f{dataset_version_id}".encode("utf-8")
    ).hexdigest()
    return f"special-review-{digest[:24]}"


def _canonical_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return f"bool:{str(value).lower()}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"number:{format(float(value), '.15g')}"
    return "text:" + str(value)


def _valid_persisted_replacement(
    value: Any,
    *,
    variable_row: Mapping[str, Any] | None = None,
) -> bool:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    row = variable_row if isinstance(variable_row, Mapping) else {}
    datatype = str(row.get("datatype") or "").strip().casefold()
    numeric_datatype = any(
        token in datatype
        for token in ("int", "float", "double", "decimal", "number")
    )
    native_value = value
    if numeric_datatype:
        if isinstance(native_value, str):
            try:
                native_value = float(native_value.strip())
            except ValueError:
                return False
        if not isinstance(native_value, (int, float)) or not math.isfinite(
            float(native_value)
        ):
            return False
        if "int" in datatype and not float(native_value).is_integer():
            return False
    elif isinstance(native_value, float) and not math.isfinite(native_value):
        return False
    detected_values = {
        _canonical_scalar(item.get("value"))
        for item in row.get("special_values", []) or []
        if isinstance(item, Mapping) and item.get("value") is not None
    }
    return _canonical_scalar(native_value) not in detected_values


def _assert_confirmed_replacements(
    decisions: Any,
    detection: Mapping[str, Any] | None = None,
) -> None:
    variable_rows = {
        str(row.get("variable") or "").strip(): row
        for row in (detection or {}).get("variables", []) or []
        if isinstance(row, Mapping)
    }
    for decision in decisions or []:
        if not isinstance(decision, Mapping):
            raise SpecialValueReviewStateError(
                "Confirmed special-value decisions must be structured records."
            )
        variable = str(decision.get("variable") or "").strip() or "The variable"
        variable_row = variable_rows.get(variable)
        if (
            str(decision.get("policy") or "")
            == "documented_domain_mapping"
            and not _valid_persisted_replacement(
                decision.get("replacement_value"),
                variable_row=variable_row,
            )
        ):
            raise SpecialValueReviewStateError(
                f"{variable} requires a valid governed replacement value before confirmation."
            )
        for override in decision.get("overrides") or []:
            if not isinstance(override, Mapping):
                raise SpecialValueReviewStateError(
                    f"{variable} contains an invalid special-value override."
                )
            if (
                str(override.get("policy") or "")
                == "documented_domain_mapping"
                and not _valid_persisted_replacement(
                    override.get("replacement_value"),
                    variable_row=variable_row,
                )
            ):
                raise SpecialValueReviewStateError(
                    f"{variable} contains an imputation override without a valid governed replacement value."
                )


def _detection_lineage_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    detection = record.get("detection")
    detection = detection if isinstance(detection, Mapping) else {}
    return {
        "analysis_partition_id": detection.get("analysis_partition_id"),
        "analysis_partition_revision": detection.get(
            "analysis_partition_revision"
        ),
        "development_partition_id": detection.get(
            "development_partition_id"
        ),
        "analysis_partition_assignment_hash": detection.get(
            "analysis_partition_assignment_hash"
        ),
        "analysis_partition_artifact_hash": detection.get(
            "analysis_partition_artifact_hash"
        ),
        "development_target_checksum": detection.get(
            "development_target_checksum"
        ),
        "source_checksum": detection.get("source_checksum"),
        "structural_scope": detection.get("structural_scope"),
        "target_analysis_scope": detection.get("target_analysis_scope"),
    }


def _event(
    connection: sqlite3.Connection,
    row: Mapping[str, Any],
    *,
    event_type: str,
    actor_user_id: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO special_value_review_events (
          special_value_review_event_id, special_value_review_id, project_id,
          dataset_id, dataset_version_id, revision, event_type,
          actor_user_id, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"special-review-event-{uuid.uuid4().hex}",
            str(row["special_value_review_id"]),
            str(row["project_id"]),
            str(row["dataset_id"]),
            str(row["dataset_version_id"]),
            int(row["revision"]),
            event_type,
            actor_user_id,
            now_iso(),
            json_dumps(dict(payload or {}), {}),
        ),
    )


class SpecialValueReviewRepository(BaseRepository):
    """Exact project/dataset/version authority for Data Acquisition review."""

    def get_exact(
        self, project_id: str, dataset_id: str, dataset_version_id: str
    ) -> Dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM special_value_reviews
            WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
            """,
            (project_id, dataset_id, dataset_version_id),
        )

    def sync_detection(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        project_id = str(record.get("project_id") or "").strip()
        dataset_id = str(record.get("dataset_id") or "").strip()
        version_id = str(record.get("dataset_version_id") or "").strip()
        fingerprint = str(record.get("detection_fingerprint") or "").strip()
        actor = str(record.get("actor_user_id") or "atlas-user").strip()
        if not all((project_id, dataset_id, version_id, fingerprint)):
            raise SpecialValueReviewStateError(
                "Exact identity and detection_fingerprint are required."
            )
        activation_revision = int(record.get("activation_revision") or 0)
        if activation_revision < 1:
            raise SpecialValueReviewStateError(
                "A positive activation_revision is required."
            )

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM special_value_reviews
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                """,
                (project_id, dataset_id, version_id),
            ).fetchone()
            timestamp = now_iso()
            if existing is None:
                review_id = _review_id(project_id, dataset_id, version_id)
                connection.execute(
                    """
                    INSERT INTO special_value_reviews (
                      special_value_review_id, project_id, dataset_id,
                      dataset_version_id, activation_revision,
                      predictor_authorization_id, target_contract_id,
                      detection_fingerprint, detection_json, decisions_json,
                      reviewer_rationale, status, detected_count,
                      reviewed_count, open_count, blocks_confirmation,
                      blocks_continuation, revision, created_by, updated_by,
                      confirmed_by, created_at, updated_at, confirmed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '', ?, ?, 0, ?, ?, ?, 1, ?, ?, NULL, ?, ?, NULL)
                    """,
                    (
                        review_id,
                        project_id,
                        dataset_id,
                        version_id,
                        activation_revision,
                        str(record.get("predictor_authorization_id") or ""),
                        str(record.get("target_contract_id") or ""),
                        fingerprint,
                        json_dumps(record.get("detection"), {}),
                        str(record.get("status") or "not_started"),
                        int(record.get("detected_count") or 0),
                        int(record.get("open_count") or 0),
                        int(bool(record.get("blocks_confirmation"))),
                        int(bool(record.get("blocks_continuation"))),
                        actor,
                        actor,
                        timestamp,
                        timestamp,
                    ),
                )
                inserted = connection.execute(
                    "SELECT * FROM special_value_reviews WHERE special_value_review_id = ?",
                    (review_id,),
                ).fetchone()
                _event(
                    connection,
                    inserted,
                    event_type="detection_initialized",
                    actor_user_id=actor,
                    payload={
                        "detection_fingerprint": fingerprint,
                        "activation_revision": activation_revision,
                        "predictor_authorization_id": str(
                            record.get("predictor_authorization_id") or ""
                        ),
                        "target_contract_id": str(
                            record.get("target_contract_id") or ""
                        ),
                        **_detection_lineage_payload(record),
                    },
                )
                connection.commit()
                return decode_row(inserted) or {}

            decoded = decode_row(existing) or {}
            same_detection = str(existing["detection_fingerprint"]) == fingerprint
            same_activation = int(existing["activation_revision"]) == activation_revision
            same_lineage = (
                str(existing["predictor_authorization_id"])
                == str(record.get("predictor_authorization_id") or "")
                and str(existing["target_contract_id"])
                == str(record.get("target_contract_id") or "")
            )
            if same_detection and same_activation and same_lineage:
                connection.commit()
                return decoded

            next_revision = int(existing["revision"]) + 1
            # A changed analytical snapshot or upstream lineage invalidates the
            # old decisions. Exact reactivation of the same version preserves
            # them while recording the new activation revision.
            invalidate = not same_detection or not same_lineage
            if invalidate:
                status = str(record.get("status") or "not_started")
                detected = int(record.get("detected_count") or 0)
                reviewed = 0
                open_count = int(record.get("open_count") or 0)
                blocks_confirmation = int(bool(record.get("blocks_confirmation")))
                blocks_continuation = int(bool(record.get("blocks_continuation")))
                decisions_json = "[]"
                rationale = ""
                confirmed_by = None
                confirmed_at = None
            else:
                status = str(existing["status"])
                detected = int(existing["detected_count"])
                reviewed = int(existing["reviewed_count"])
                open_count = int(existing["open_count"])
                blocks_confirmation = int(existing["blocks_confirmation"])
                blocks_continuation = int(existing["blocks_continuation"])
                decisions_json = str(existing["decisions_json"])
                rationale = str(existing["reviewer_rationale"] or "")
                confirmed_by = existing["confirmed_by"]
                confirmed_at = existing["confirmed_at"]
            connection.execute(
                """
                UPDATE special_value_reviews
                SET activation_revision = ?, predictor_authorization_id = ?,
                    target_contract_id = ?, detection_fingerprint = ?,
                    detection_json = ?, decisions_json = ?,
                    reviewer_rationale = ?, status = ?, detected_count = ?,
                    reviewed_count = ?, open_count = ?,
                    blocks_confirmation = ?, blocks_continuation = ?,
                    revision = ?, updated_by = ?, updated_at = ?,
                    confirmed_by = ?, confirmed_at = ?
                WHERE special_value_review_id = ? AND revision = ?
                """,
                (
                    activation_revision,
                    str(record.get("predictor_authorization_id") or ""),
                    str(record.get("target_contract_id") or ""),
                    fingerprint,
                    json_dumps(record.get("detection"), {}),
                    decisions_json,
                    rationale,
                    status,
                    detected,
                    reviewed,
                    open_count,
                    blocks_confirmation,
                    blocks_continuation,
                    next_revision,
                    actor,
                    timestamp,
                    confirmed_by,
                    confirmed_at,
                    str(existing["special_value_review_id"]),
                    int(existing["revision"]),
                ),
            )
            updated = connection.execute(
                "SELECT * FROM special_value_reviews WHERE special_value_review_id = ?",
                (str(existing["special_value_review_id"]),),
            ).fetchone()
            _event(
                connection,
                updated,
                event_type="detection_refreshed",
                actor_user_id=actor,
                payload={
                    "detection_fingerprint": fingerprint,
                    "previous_detection_fingerprint": str(
                        existing["detection_fingerprint"]
                    ),
                    "decisions_invalidated": invalidate,
                    "previous_activation_revision": int(
                        existing["activation_revision"]
                    ),
                    "activation_revision": activation_revision,
                    "previous_predictor_authorization_id": str(
                        existing["predictor_authorization_id"]
                    ),
                    "predictor_authorization_id": str(
                        record.get("predictor_authorization_id") or ""
                    ),
                    "previous_target_contract_id": str(
                        existing["target_contract_id"]
                    ),
                    "target_contract_id": str(
                        record.get("target_contract_id") or ""
                    ),
                    **_detection_lineage_payload(record),
                },
            )
            connection.commit()
            return decode_row(updated) or {}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_review(
        self,
        record: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> Dict[str, Any]:
        project_id = str(record.get("project_id") or "").strip()
        dataset_id = str(record.get("dataset_id") or "").strip()
        version_id = str(record.get("dataset_version_id") or "").strip()
        actor = str(record.get("actor_user_id") or "atlas-user").strip()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT * FROM special_value_reviews
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                """,
                (project_id, dataset_id, version_id),
            ).fetchone()
            if current is None:
                raise SpecialValueReviewStateError(
                    "The exact special-value detection has not been initialized."
                )
            if int(current["revision"]) != int(expected_revision):
                raise SpecialValueReviewConflictError(
                    "The special-value review was updated by another request.",
                    current=decode_row(current),
                )
            supplied_fingerprint = str(record.get("detection_fingerprint") or "")
            if supplied_fingerprint != str(current["detection_fingerprint"]):
                raise SpecialValueReviewConflictError(
                    "The supplied detection fingerprint is stale.",
                    current=decode_row(current),
                )
            next_revision = int(current["revision"]) + 1
            timestamp = now_iso()
            status = str(record.get("status") or "in_review")
            confirmed = status == "confirmed"
            decisions = list(record.get("decisions") or [])
            if confirmed:
                current_record = decode_row(current) or {}
                detection = current_record.get("detection_json")
                _assert_confirmed_replacements(
                    decisions,
                    detection if isinstance(detection, Mapping) else {},
                )
            cursor = connection.execute(
                """
                UPDATE special_value_reviews
                SET decisions_json = ?, reviewer_rationale = ?, status = ?,
                    detected_count = ?, reviewed_count = ?, open_count = ?,
                    blocks_confirmation = ?, blocks_continuation = ?,
                    revision = ?, updated_by = ?, updated_at = ?,
                    confirmed_by = ?, confirmed_at = ?
                WHERE special_value_review_id = ? AND revision = ?
                """,
                (
                    json_dumps(decisions, []),
                    str(record.get("reviewer_rationale") or ""),
                    status,
                    int(record.get("detected_count") or 0),
                    int(record.get("reviewed_count") or 0),
                    int(record.get("open_count") or 0),
                    int(bool(record.get("blocks_confirmation"))),
                    int(bool(record.get("blocks_continuation"))),
                    next_revision,
                    actor,
                    timestamp,
                    actor if confirmed else None,
                    timestamp if confirmed else None,
                    str(current["special_value_review_id"]),
                    int(expected_revision),
                ),
            )
            if cursor.rowcount != 1:
                latest = connection.execute(
                    "SELECT * FROM special_value_reviews WHERE special_value_review_id = ?",
                    (str(current["special_value_review_id"]),),
                ).fetchone()
                raise SpecialValueReviewConflictError(
                    "The special-value review changed concurrently.",
                    current=decode_row(latest),
                )
            updated = connection.execute(
                "SELECT * FROM special_value_reviews WHERE special_value_review_id = ?",
                (str(current["special_value_review_id"]),),
            ).fetchone()
            _event(
                connection,
                updated,
                event_type="confirmed" if confirmed else "draft_saved",
                actor_user_id=actor,
                payload={
                    "status": status,
                    "detection_fingerprint": supplied_fingerprint,
                    "detected_count": int(record.get("detected_count") or 0),
                    "reviewed_count": int(record.get("reviewed_count") or 0),
                    "open_count": int(record.get("open_count") or 0),
                    "blocks_confirmation": bool(
                        record.get("blocks_confirmation")
                    ),
                    "blocks_continuation": bool(
                        record.get("blocks_continuation")
                    ),
                    "decisions": list(record.get("decisions") or []),
                    "reviewer_rationale": str(
                        record.get("reviewer_rationale") or ""
                    ),
                },
            )
            connection.commit()
            return decode_row(updated) or {}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def events(
        self, project_id: str, dataset_id: str, dataset_version_id: str
    ) -> list[Dict[str, Any]]:
        return self._many(
            """
            SELECT * FROM special_value_review_events
            WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
            ORDER BY revision ASC, created_at ASC
            """,
            (project_id, dataset_id, dataset_version_id),
        )
