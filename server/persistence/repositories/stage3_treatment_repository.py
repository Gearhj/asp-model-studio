from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Mapping
from typing import Any

from ..db import Database, decode_row, json_dumps, now_iso
from .base_repository import BaseRepository


class Stage3TreatmentPersistenceError(RuntimeError):
    """An immutable Stage 3 treatment record is missing or contradictory."""


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json_dumps(dict(value), {}).encode("utf-8")).hexdigest()


def _public_policy(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "policyId": row.get("treatment_policy_id"),
        "projectId": row.get("project_id"),
        "policyKind": row.get("policy_kind"),
        "policyVersion": int(row.get("policy_version") or 0),
        "status": row.get("policy_status"),
        "priorPolicyId": row.get("prior_policy_id"),
        "adoptedFromPolicyId": row.get("adopted_from_policy_id"),
        "authorityReviewDigest": row.get("authority_review_digest"),
        "registrationId": row.get("registration_id"),
        "datasetVersionId": row.get("dataset_version_id"),
        "activationRevision": int(row.get("activation_revision") or 0),
        "sourceDatasetId": row.get("source_dataset_id"),
        "sourceManifestSha": row.get("source_manifest_sha"),
        "goldManifestSha": row.get("gold_manifest_sha"),
        "contextualManifestSha": row.get("contextual_manifest_sha"),
        "development": {
            "startDate": row.get("development_start_date"),
            "endDate": row.get("development_end_date"),
            "rows": int(row.get("development_rows") or 0),
        },
        "finalOot": {
            "startDate": row.get("final_oot_start_date"),
            "endDate": row.get("final_oot_end_date"),
            "rows": int(row.get("final_oot_rows") or 0),
            "locked": True,
        },
        "globalMethod": row.get("global_method"),
        "policy": row.get("policy_json") or {},
        "fittingRule": row.get("fitting_rule_json") or {},
        "notes": row.get("notes") or "",
        "checksum": row.get("content_sha256"),
        "createdByUserId": row.get("created_by_user_id"),
        "createdAt": row.get("created_at"),
        "immutable": True,
    }


class Stage3TreatmentRepository(BaseRepository):
    """Append-only Stage 3 preprocessing-policy and preview evidence."""

    def _event(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
        *,
        event_type: str,
        actor_user_id: str,
        payload: Mapping[str, Any] | None = None,
        prior_policy_id: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO stage3_treatment_policy_events (
              treatment_policy_event_id, treatment_policy_id, project_id,
              policy_kind, policy_version, event_type, actor_user_id,
              prior_policy_id, authority_review_digest, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"stage3-policy-event-{uuid.uuid4().hex}",
                row["treatment_policy_id"],
                row["project_id"],
                row["policy_kind"],
                int(row["policy_version"]),
                event_type,
                actor_user_id,
                prior_policy_id,
                row["authority_review_digest"],
                now_iso(),
                json_dumps(dict(payload or {}), {}),
            ),
        )

    def list_versions(
        self, project_id: str, policy_kind: str, authority_review_digest: str
    ) -> list[dict[str, Any]]:
        rows = self._many(
            """
            SELECT * FROM stage3_treatment_policy_versions
            WHERE project_id = ? AND policy_kind = ? AND authority_review_digest = ?
            ORDER BY policy_version DESC, created_at DESC
            """,
            (project_id, policy_kind, authority_review_digest),
        )
        return [_public_policy(row) or {} for row in rows]

    def policy_state(
        self, project_id: str, policy_kind: str, authority_review_digest: str
    ) -> dict[str, Any]:
        versions = self.list_versions(project_id, policy_kind, authority_review_digest)
        adopted_draft_ids = {
            str(row["adoptedFromPolicyId"])
            for row in versions
            if row["status"] == "ADOPTED" and row.get("adoptedFromPolicyId")
        }
        return {
            # A draft remains an immutable historical record after adoption,
            # but it is no longer an editable/current draft. Only an
            # unconsumed successor draft should supersede the adopted policy
            # on the editing surface.
            "latestDraft": next(
                (
                    row
                    for row in versions
                    if row["status"] == "DRAFT" and row["policyId"] not in adopted_draft_ids
                ),
                None,
            ),
            "adopted": next((row for row in versions if row["status"] == "ADOPTED"), None),
            "history": versions,
        }

    def save_draft(
        self,
        *,
        authority: Mapping[str, Any],
        policy_kind: str,
        global_method: str,
        policy: Mapping[str, Any],
        fitting_rule: Mapping[str, Any],
        notes: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        if policy_kind not in {"OUTLIER", "IMPUTATION"}:
            raise Stage3TreatmentPersistenceError("Unsupported treatment policy kind.")
        identity = {
            "projectId": str(authority["projectId"]),
            "policyKind": policy_kind,
            "authorityReviewDigest": str(authority["reviewDigest"]),
            "globalMethod": global_method,
            "policy": dict(policy),
            "fittingRule": dict(fitting_rule),
            "notes": notes,
        }
        checksum = _sha256(identity)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT draft.* FROM stage3_treatment_policy_versions AS draft
                WHERE draft.project_id = ? AND draft.policy_kind = ?
                  AND draft.authority_review_digest = ? AND draft.content_sha256 = ?
                  AND draft.policy_status = 'DRAFT'
                  AND draft.policy_version = (
                    SELECT MAX(latest.policy_version)
                    FROM stage3_treatment_policy_versions AS latest
                    WHERE latest.project_id = draft.project_id
                      AND latest.policy_kind = draft.policy_kind
                      AND latest.authority_review_digest = draft.authority_review_digest
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM stage3_treatment_policy_versions AS adopted
                    WHERE adopted.adopted_from_policy_id = draft.treatment_policy_id
                      AND adopted.policy_status = 'ADOPTED'
                  )
                """,
                (
                    authority["projectId"],
                    policy_kind,
                    authority["reviewDigest"],
                    checksum,
                ),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return _public_policy(decode_row(existing)) or {}
            previous = connection.execute(
                """
                SELECT * FROM stage3_treatment_policy_versions
                WHERE project_id = ? AND policy_kind = ? AND authority_review_digest = ?
                ORDER BY policy_version DESC LIMIT 1
                """,
                (authority["projectId"], policy_kind, authority["reviewDigest"]),
            ).fetchone()
            version = int(previous["policy_version"] if previous else 0) + 1
            policy_id = f"stage3-{policy_kind.lower()}-policy-{uuid.uuid4().hex}"
            timestamp = now_iso()
            values = (
                policy_id,
                authority["projectId"],
                policy_kind,
                version,
                "DRAFT",
                previous["treatment_policy_id"] if previous else None,
                None,
                authority["registrationId"],
                authority["datasetVersionId"],
                int(authority["activationRevision"]),
                authority["sourceDatasetId"],
                authority["sourceManifestSha"],
                authority["goldManifestSha"],
                authority["contextualManifestSha"],
                authority["reviewDigest"],
                authority["development"]["startDate"],
                authority["development"]["endDate"],
                int(authority["development"]["rows"]),
                authority["finalOot"]["startDate"],
                authority["finalOot"]["endDate"],
                int(authority["finalOot"]["rows"]),
                global_method,
                json_dumps(dict(policy), {}),
                json_dumps(dict(fitting_rule), {}),
                notes,
                checksum,
                actor_user_id,
                timestamp,
            )
            connection.execute(
                """
                INSERT INTO stage3_treatment_policy_versions (
                  treatment_policy_id, project_id, policy_kind, policy_version,
                  policy_status, prior_policy_id, adopted_from_policy_id,
                  registration_id, dataset_version_id, activation_revision,
                  source_dataset_id, source_manifest_sha, gold_manifest_sha,
                  contextual_manifest_sha, authority_review_digest,
                  development_start_date, development_end_date, development_rows,
                  final_oot_start_date, final_oot_end_date, final_oot_rows,
                  global_method, policy_json, fitting_rule_json, notes,
                  content_sha256, created_by_user_id, created_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?
                )
                """,
                values,
            )
            inserted = decode_row(
                connection.execute(
                    "SELECT * FROM stage3_treatment_policy_versions WHERE treatment_policy_id = ?",
                    (policy_id,),
                ).fetchone()
            ) or {}
            self._event(
                connection,
                inserted,
                event_type="DRAFT_UPDATED" if previous is not None else "DRAFT_CREATED",
                actor_user_id=actor_user_id,
                prior_policy_id=inserted.get("prior_policy_id"),
                payload={"checksum": checksum},
            )
            serialized = json_dumps(dict(policy), {})
            if "EXCLUDE_ROW" in serialized:
                self._event(connection, inserted, event_type="ROW_EXCLUSION_SELECTED", actor_user_id=actor_user_id)
            if policy_kind == "IMPUTATION" and "DROP_VARIABLE" in serialized:
                self._event(connection, inserted, event_type="VARIABLE_DROP_SELECTED", actor_user_id=actor_user_id)
            source_failure_overridden = (
                policy_kind == "IMPUTATION"
                and (
                    str(dict(policy).get("sourceFailureDefault") or "REVIEW_REQUIRED") != "REVIEW_REQUIRED"
                    or any(
                        isinstance(value, Mapping)
                        and value.get("sourceFailureMethod") not in {None, "", "REVIEW_REQUIRED"}
                        for value in dict(policy).get("overrides", {}).values()
                    )
                )
            )
            if source_failure_overridden:
                self._event(connection, inserted, event_type="SOURCE_FAILURE_OVERRIDE_SELECTED", actor_user_id=actor_user_id)
            connection.commit()
            return _public_policy(inserted) or {}
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def adopt(
        self,
        *,
        project_id: str,
        policy_kind: str,
        authority_review_digest: str,
        draft_policy_id: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute(
                """
                SELECT * FROM stage3_treatment_policy_versions
                WHERE treatment_policy_id = ? AND project_id = ? AND policy_kind = ?
                  AND authority_review_digest = ?
                """,
                (draft_policy_id, project_id, policy_kind, authority_review_digest),
            ).fetchone()
            if source is None:
                raise Stage3TreatmentPersistenceError(
                    "The exact authority-bound draft treatment policy does not exist."
                )
            if source["policy_status"] != "DRAFT":
                raise Stage3TreatmentPersistenceError(
                    "Only an exact immutable DRAFT treatment policy may be adopted."
                )
            existing = connection.execute(
                """
                SELECT * FROM stage3_treatment_policy_versions
                WHERE project_id = ? AND policy_kind = ? AND authority_review_digest = ?
                  AND policy_status = 'ADOPTED' AND adopted_from_policy_id = ?
                """,
                (project_id, policy_kind, authority_review_digest, draft_policy_id),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return _public_policy(decode_row(existing)) or {}
            latest = connection.execute(
                """
                SELECT * FROM stage3_treatment_policy_versions
                WHERE project_id = ? AND policy_kind = ? AND authority_review_digest = ?
                ORDER BY policy_version DESC LIMIT 1
                """,
                (project_id, policy_kind, authority_review_digest),
            ).fetchone()
            prior_adopted = connection.execute(
                """
                SELECT * FROM stage3_treatment_policy_versions
                WHERE project_id = ? AND policy_kind = ? AND authority_review_digest = ?
                  AND policy_status = 'ADOPTED'
                ORDER BY policy_version DESC LIMIT 1
                """,
                (project_id, policy_kind, authority_review_digest),
            ).fetchone()
            version = int(latest["policy_version"] if latest else 0) + 1
            policy_id = f"stage3-{policy_kind.lower()}-policy-{uuid.uuid4().hex}"
            values = (
                policy_id,
                project_id,
                policy_kind,
                version,
                "ADOPTED",
                latest["treatment_policy_id"] if latest else None,
                draft_policy_id,
                source["registration_id"],
                source["dataset_version_id"],
                int(source["activation_revision"]),
                source["source_dataset_id"],
                source["source_manifest_sha"],
                source["gold_manifest_sha"],
                source["contextual_manifest_sha"],
                source["authority_review_digest"],
                source["development_start_date"],
                source["development_end_date"],
                int(source["development_rows"]),
                source["final_oot_start_date"],
                source["final_oot_end_date"],
                int(source["final_oot_rows"]),
                source["global_method"],
                source["policy_json"],
                source["fitting_rule_json"],
                source["notes"],
                source["content_sha256"],
                actor_user_id,
                now_iso(),
            )
            connection.execute(
                """
                INSERT INTO stage3_treatment_policy_versions (
                  treatment_policy_id, project_id, policy_kind, policy_version,
                  policy_status, prior_policy_id, adopted_from_policy_id,
                  registration_id, dataset_version_id, activation_revision,
                  source_dataset_id, source_manifest_sha, gold_manifest_sha,
                  contextual_manifest_sha, authority_review_digest,
                  development_start_date, development_end_date, development_rows,
                  final_oot_start_date, final_oot_end_date, final_oot_rows,
                  global_method, policy_json, fitting_rule_json, notes,
                  content_sha256, created_by_user_id, created_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?
                )
                """,
                values,
            )
            inserted = decode_row(
                connection.execute(
                    "SELECT * FROM stage3_treatment_policy_versions WHERE treatment_policy_id = ?",
                    (policy_id,),
                ).fetchone()
            ) or {}
            if prior_adopted is not None:
                self._event(
                    connection,
                    inserted,
                    event_type="POLICY_SUPERSEDED",
                    actor_user_id=actor_user_id,
                    prior_policy_id=prior_adopted["treatment_policy_id"],
                    payload={"supersededPolicyId": prior_adopted["treatment_policy_id"]},
                )
            self._event(
                connection,
                inserted,
                event_type="POLICY_ADOPTED",
                actor_user_id=actor_user_id,
                prior_policy_id=draft_policy_id,
                payload={"adoptedFromPolicyId": draft_policy_id},
            )
            connection.commit()
            return _public_policy(inserted) or {}
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def record_preview_request(
        self,
        *,
        project_id: str,
        variable: str,
        authority_review_digest: str,
        actor_user_id: str,
        specification: Mapping[str, Any],
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO stage3_predicted_imputation_preview_events (
                  predicted_preview_event_id, predicted_preview_id, project_id,
                  variable_name, event_type, actor_user_id,
                  authority_review_digest, created_at, payload_json
                ) VALUES (?, NULL, ?, ?, 'PREDICTED_PREVIEW_REQUESTED', ?, ?, ?, ?)
                """,
                (
                    f"stage3-preview-event-{uuid.uuid4().hex}",
                    project_id,
                    variable,
                    actor_user_id,
                    authority_review_digest,
                    now_iso(),
                    json_dumps(dict(specification), {}),
                ),
            )

    def latest_preview(
        self,
        project_id: str,
        variable: str,
        authority_review_digest: str,
        specification: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        specification_clause = " AND specification_json = ?" if specification is not None else ""
        params: tuple[Any, ...] = (project_id, variable, authority_review_digest)
        if specification is not None:
            params = (*params, json_dumps(dict(specification), {}))
        row = self._one(
            f"""
            SELECT * FROM stage3_predicted_imputation_previews
            WHERE project_id = ? AND variable_name = ?
              AND authority_review_digest = ?
              {specification_clause}
            ORDER BY created_at DESC, predicted_preview_id DESC LIMIT 1
            """,
            params,
        )
        if not row:
            return None
        return {
            "previewId": row["predicted_preview_id"],
            "projectId": row["project_id"],
            "variable": row["variable_name"],
            "authorityReviewDigest": row["authority_review_digest"],
            "specification": row["specification_json"],
            "summary": row["summary_json"],
            "artifactSha256": row["artifact_sha256"],
            "seed": int(row["seed"]),
            "createdAt": row["created_at"],
            "immutable": True,
        }

    def save_preview(
        self,
        *,
        authority: Mapping[str, Any],
        variable: str,
        specification: Mapping[str, Any],
        summary: Mapping[str, Any],
        seed: int,
        actor_user_id: str,
    ) -> dict[str, Any]:
        stable_summary = {
            key: value
            for key, value in dict(summary).items()
            if key not in {"runtimeSeconds", "artifactChecksum"}
        }
        artifact_sha = _sha256(
            {"authority": dict(authority), "variable": variable, "specification": dict(specification), "summary": stable_summary}
        )
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM stage3_predicted_imputation_previews
                WHERE project_id = ? AND variable_name = ?
                  AND authority_review_digest = ? AND artifact_sha256 = ?
                """,
                (authority["projectId"], variable, authority["reviewDigest"], artifact_sha),
            ).fetchone()
            if existing is None:
                preview_id = f"stage3-predicted-preview-{uuid.uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO stage3_predicted_imputation_previews (
                      predicted_preview_id, project_id, variable_name,
                      registration_id, dataset_version_id, authority_review_digest,
                      development_end_date, final_oot_start_date,
                      specification_json, summary_json, artifact_sha256, seed,
                      requested_by_user_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        preview_id,
                        authority["projectId"],
                        variable,
                        authority["registrationId"],
                        authority["datasetVersionId"],
                        authority["reviewDigest"],
                        authority["development"]["endDate"],
                        authority["finalOot"]["startDate"],
                        json_dumps(dict(specification), {}),
                        json_dumps(dict(summary), {}),
                        artifact_sha,
                        int(seed),
                        actor_user_id,
                        now_iso(),
                    ),
                )
                existing = connection.execute(
                    "SELECT * FROM stage3_predicted_imputation_previews WHERE predicted_preview_id = ?",
                    (preview_id,),
                ).fetchone()
            decoded = decode_row(existing) or {}
            connection.execute(
                """
                INSERT INTO stage3_predicted_imputation_preview_events (
                  predicted_preview_event_id, predicted_preview_id, project_id,
                  variable_name, event_type, actor_user_id,
                  authority_review_digest, created_at, payload_json
                ) VALUES (?, ?, ?, ?, 'PREDICTED_PREVIEW_COMPLETED', ?, ?, ?, ?)
                """,
                (
                    f"stage3-preview-event-{uuid.uuid4().hex}",
                    decoded["predicted_preview_id"],
                    authority["projectId"],
                    variable,
                    actor_user_id,
                    authority["reviewDigest"],
                    now_iso(),
                    json_dumps({"artifactSha256": artifact_sha}, {}),
                ),
            )
            connection.commit()
            return {
                "previewId": decoded["predicted_preview_id"],
                "projectId": decoded["project_id"],
                "variable": decoded["variable_name"],
                "authorityReviewDigest": decoded["authority_review_digest"],
                "specification": decoded["specification_json"],
                "summary": decoded["summary_json"],
                "artifactSha256": decoded["artifact_sha256"],
                "seed": int(decoded["seed"]),
                "createdAt": decoded["created_at"],
                "immutable": True,
            }
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()


__all__ = ["Stage3TreatmentPersistenceError", "Stage3TreatmentRepository"]
