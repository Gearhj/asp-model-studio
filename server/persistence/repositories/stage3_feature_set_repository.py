from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from ..db import Database, decode_row, json_dumps, now_iso
from .base_repository import BaseRepository


NO_CURRENT_FEATURE_SET = "NO_CURRENT_FEATURE_SET"


class Stage3FeatureSetPersistenceError(RuntimeError):
    """An immutable Stage 3 feature-set operation is stale or contradictory."""


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json_dumps(dict(value), {}).encode("utf-8")).hexdigest()


def _policy_ref(row: Mapping[str, Any], prefix: str) -> dict[str, Any] | None:
    policy_id = row.get(f"adopted_{prefix}_policy_id")
    if not policy_id:
        return None
    return {
        "policyId": policy_id,
        "policyVersion": int(row.get(f"adopted_{prefix}_policy_version") or 0),
        "checksum": row.get(f"adopted_{prefix}_policy_checksum"),
        "status": "ADOPTED",
    }


def _public_feature_set(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "featureSetId": row.get("feature_set_id"),
        "projectId": row.get("project_id"),
        "featureSetKey": row.get("feature_set_key"),
        "name": row.get("feature_set_name"),
        "version": int(row.get("feature_set_version") or 0),
        "status": row.get("feature_set_status"),
        "priorFeatureSetId": row.get("prior_feature_set_id"),
        "registeredFromFeatureSetId": row.get("registered_from_feature_set_id"),
        "retiredFeatureSetId": row.get("retired_feature_set_id"),
        "authority": {
            "registrationId": row.get("registration_id"),
            "datasetVersionId": row.get("dataset_version_id"),
            "activationRevision": int(row.get("activation_revision") or 0),
            "sourceDatasetId": row.get("source_dataset_id"),
            "sourceManifestSha": row.get("source_manifest_sha"),
            "goldManifestSha": row.get("gold_manifest_sha"),
            "contextualManifestSha": row.get("contextual_manifest_sha"),
            "reviewDigest": row.get("authority_review_digest"),
        },
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
        "orderedFeatures": list(row.get("ordered_features_json") or []),
        "familyMemberships": list(row.get("family_memberships_json") or []),
        "transformationContracts": dict(row.get("transformation_contracts_json") or {}),
        "interactionContracts": list(row.get("interaction_contracts_json") or []),
        "unavailableExclusions": list(row.get("unavailable_exclusions_json") or []),
        "treatmentPolicies": {
            "outlier": _policy_ref(row, "outlier"),
            "missing": _policy_ref(row, "missing"),
        },
        "description": row.get("description") or "",
        "notes": row.get("notes") or "",
        "checksum": row.get("content_sha256"),
        "createdByUserId": row.get("created_by_user_id"),
        "createdAt": row.get("created_at"),
        "immutable": True,
        "modelActivity": {
            "fits": 0,
            "scores": 0,
            "registrations": 0,
            "promotions": 0,
        },
    }


class Stage3FeatureSetRepository(BaseRepository):
    """Append-only Stage 3 feature-set definitions and lifecycle events."""

    def _event(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
        *,
        event_type: str,
        actor_user_id: str,
        prior_feature_set_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO stage3_feature_set_events (
              feature_set_event_id, feature_set_id, project_id,
              feature_set_key, feature_set_version, event_type,
              actor_user_id, prior_feature_set_id,
              authority_review_digest, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"stage3-feature-set-event-{uuid.uuid4().hex}",
                row["feature_set_id"],
                row["project_id"],
                row["feature_set_key"],
                int(row["feature_set_version"]),
                event_type,
                actor_user_id,
                prior_feature_set_id,
                row["authority_review_digest"],
                now_iso(),
                json_dumps(dict(payload or {}), {}),
            ),
        )

    @staticmethod
    def _current_for_key(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        consumed_drafts = {
            str(row["registered_from_feature_set_id"])
            for row in rows
            if row.get("registered_from_feature_set_id")
        }
        draft = next(
            (
                dict(row)
                for row in rows
                if row.get("feature_set_status") == "DRAFT"
                and str(row.get("feature_set_id")) not in consumed_drafts
            ),
            None,
        )
        terminal = next(
            (
                dict(row)
                for row in rows
                if row.get("feature_set_status") in {"REGISTERED", "RETIRED"}
            ),
            None,
        )
        registered = terminal if terminal and terminal.get("feature_set_status") == "REGISTERED" else None
        return draft, registered

    def list_versions(self, project_id: str, authority_review_digest: str) -> list[dict[str, Any]]:
        rows = self._many(
            """
            SELECT * FROM stage3_feature_set_versions
            WHERE project_id = ? AND authority_review_digest = ?
            ORDER BY feature_set_version DESC, created_at DESC, feature_set_id DESC
            """,
            (project_id, authority_review_digest),
        )
        return [_public_feature_set(row) or {} for row in rows]

    def feature_set_state(self, project_id: str, authority_review_digest: str) -> dict[str, Any]:
        raw_rows = self._many(
            """
            SELECT * FROM stage3_feature_set_versions
            WHERE project_id = ? AND authority_review_digest = ?
            ORDER BY feature_set_version DESC, created_at DESC, feature_set_id DESC
            """,
            (project_id, authority_review_digest),
        )
        by_key: dict[str, list[dict[str, Any]]] = {}
        for row in raw_rows:
            by_key.setdefault(str(row["feature_set_key"]), []).append(row)
        drafts: list[dict[str, Any]] = []
        registered_sets: list[dict[str, Any]] = []
        for rows in by_key.values():
            draft, registered = self._current_for_key(rows)
            if draft:
                drafts.append(draft)
            if registered:
                registered_sets.append(registered)
        drafts.sort(key=lambda item: (int(item["feature_set_version"]), str(item["created_at"])), reverse=True)
        registered_sets.sort(key=lambda item: (int(item["feature_set_version"]), str(item["created_at"])), reverse=True)
        current_registered_ids = {
            str(item["feature_set_id"]) for item in registered_sets
        }
        consumed_draft_ids = {
            str(row["registered_from_feature_set_id"])
            for row in raw_rows
            if row.get("registered_from_feature_set_id")
        }
        history: list[dict[str, Any]] = []
        for row in raw_rows:
            public = _public_feature_set(row) or {}
            row_id = str(row.get("feature_set_id"))
            if public.get("status") == "REGISTERED" and row_id not in current_registered_ids:
                public["status"] = "SUPERSEDED"
            elif public.get("status") == "DRAFT" and row_id in consumed_draft_ids:
                public["status"] = "REGISTERED_SOURCE_DRAFT"
            history.append(public)
        selected = (drafts or registered_sets or raw_rows[:1])
        expected = str(selected[0]["content_sha256"]) if selected else NO_CURRENT_FEATURE_SET
        return {
            "draft": _public_feature_set(drafts[0]) if drafts else None,
            "registered": _public_feature_set(registered_sets[0]) if registered_sets else None,
            "drafts": [_public_feature_set(row) for row in drafts],
            "registeredSets": [_public_feature_set(row) for row in registered_sets],
            "history": history,
            "expectedChecksumByKey": {
                key: self._expected_for_rows(rows) for key, rows in by_key.items()
            },
            "expectedChecksum": expected,
        }

    def _rows_for_key(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        feature_set_key: str,
        authority_review_digest: str,
    ) -> list[dict[str, Any]]:
        return [
            decode_row(row) or {}
            for row in connection.execute(
                """
                SELECT * FROM stage3_feature_set_versions
                WHERE project_id = ? AND feature_set_key = ?
                  AND authority_review_digest = ?
                ORDER BY feature_set_version DESC, created_at DESC, feature_set_id DESC
                """,
                (project_id, feature_set_key, authority_review_digest),
            ).fetchall()
        ]

    @staticmethod
    def _expected_for_rows(rows: Sequence[Mapping[str, Any]]) -> str:
        draft, registered = Stage3FeatureSetRepository._current_for_key(rows)
        selected = draft or registered or (dict(rows[0]) if rows else None)
        return str(selected["content_sha256"]) if selected else NO_CURRENT_FEATURE_SET

    @staticmethod
    def _assert_checksum(expected_checksum: str, actual_checksum: str) -> None:
        if not expected_checksum:
            raise Stage3FeatureSetPersistenceError(
                "The current feature-set checksum is required for concurrent-save protection."
            )
        if expected_checksum != actual_checksum:
            raise Stage3FeatureSetPersistenceError(
                "The feature-set state changed after it was loaded; refresh before saving."
            )

    @staticmethod
    def _insert(
        connection: sqlite3.Connection,
        *,
        feature_set_id: str,
        feature_set_key: str,
        feature_set_name: str,
        version: int,
        status: str,
        prior_feature_set_id: str | None,
        registered_from_feature_set_id: str | None,
        retired_feature_set_id: str | None,
        authority: Mapping[str, Any],
        ordered_features: Sequence[str],
        family_memberships: Sequence[str],
        transformation_contracts: Mapping[str, Any],
        interaction_contracts: Sequence[Mapping[str, Any]],
        unavailable_exclusions: Sequence[Mapping[str, Any]],
        treatment_policies: Mapping[str, Mapping[str, Any] | None],
        description: str,
        notes: str,
        checksum: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        outlier = treatment_policies.get("outlier") or {}
        missing = treatment_policies.get("missing") or {}
        connection.execute(
            """
            INSERT INTO stage3_feature_set_versions (
              feature_set_id, project_id, feature_set_key, feature_set_name,
              feature_set_version, feature_set_status, prior_feature_set_id,
              registered_from_feature_set_id, retired_feature_set_id,
              registration_id, dataset_version_id, activation_revision,
              source_dataset_id, source_manifest_sha, gold_manifest_sha,
              contextual_manifest_sha, authority_review_digest,
              development_start_date, development_end_date, development_rows,
              final_oot_start_date, final_oot_end_date, final_oot_rows,
              ordered_features_json, family_memberships_json,
              transformation_contracts_json, interaction_contracts_json,
              unavailable_exclusions_json,
              adopted_outlier_policy_id, adopted_outlier_policy_version,
              adopted_outlier_policy_checksum, adopted_missing_policy_id,
              adopted_missing_policy_version, adopted_missing_policy_checksum,
              description, notes, content_sha256, created_by_user_id, created_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                feature_set_id,
                authority["projectId"],
                feature_set_key,
                feature_set_name,
                version,
                status,
                prior_feature_set_id,
                registered_from_feature_set_id,
                retired_feature_set_id,
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
                json_dumps(list(ordered_features), []),
                json_dumps(list(family_memberships), []),
                json_dumps(dict(transformation_contracts), {}),
                json_dumps(list(interaction_contracts), []),
                json_dumps(list(unavailable_exclusions), []),
                outlier.get("policyId"),
                outlier.get("policyVersion"),
                outlier.get("checksum"),
                missing.get("policyId"),
                missing.get("policyVersion"),
                missing.get("checksum"),
                description,
                notes,
                checksum,
                actor_user_id,
                now_iso(),
            ),
        )
        return decode_row(
            connection.execute(
                "SELECT * FROM stage3_feature_set_versions WHERE feature_set_id = ?",
                (feature_set_id,),
            ).fetchone()
        ) or {}

    def save_draft(
        self,
        *,
        authority: Mapping[str, Any],
        feature_set_key: str,
        feature_set_name: str,
        ordered_features: Sequence[str],
        family_memberships: Sequence[str],
        transformation_contracts: Mapping[str, Any],
        interaction_contracts: Sequence[Mapping[str, Any]],
        unavailable_exclusions: Sequence[Mapping[str, Any]],
        treatment_policies: Mapping[str, Mapping[str, Any] | None],
        description: str,
        notes: str,
        expected_checksum: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        identity = {
            "projectId": authority["projectId"],
            "featureSetKey": feature_set_key,
            "name": feature_set_name,
            "authorityReviewDigest": authority["reviewDigest"],
            "orderedFeatures": list(ordered_features),
            "familyMemberships": list(family_memberships),
            "transformationContracts": dict(transformation_contracts),
            "interactionContracts": list(interaction_contracts),
            "unavailableExclusions": list(unavailable_exclusions),
            "treatmentPolicies": dict(treatment_policies),
            "description": description,
            "notes": notes,
        }
        checksum = _sha256(identity)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = self._rows_for_key(
                connection,
                str(authority["projectId"]),
                feature_set_key,
                str(authority["reviewDigest"]),
            )
            actual = self._expected_for_rows(rows)
            self._assert_checksum(expected_checksum, actual)
            current_draft, _ = self._current_for_key(rows)
            if current_draft and current_draft.get("content_sha256") == checksum:
                connection.commit()
                return _public_feature_set(current_draft) or {}
            version = int(rows[0]["feature_set_version"] if rows else 0) + 1
            feature_set_id = f"stage3-feature-set-{uuid.uuid4().hex}"
            inserted = self._insert(
                connection,
                feature_set_id=feature_set_id,
                feature_set_key=feature_set_key,
                feature_set_name=feature_set_name,
                version=version,
                status="DRAFT",
                prior_feature_set_id=str(rows[0]["feature_set_id"]) if rows else None,
                registered_from_feature_set_id=None,
                retired_feature_set_id=None,
                authority=authority,
                ordered_features=ordered_features,
                family_memberships=family_memberships,
                transformation_contracts=transformation_contracts,
                interaction_contracts=interaction_contracts,
                unavailable_exclusions=unavailable_exclusions,
                treatment_policies=treatment_policies,
                description=description,
                notes=notes,
                checksum=checksum,
                actor_user_id=actor_user_id,
            )
            self._event(
                connection,
                inserted,
                event_type="DRAFT_REVISED" if rows else "DRAFT_CREATED",
                actor_user_id=actor_user_id,
                prior_feature_set_id=inserted.get("prior_feature_set_id"),
                payload={"checksum": checksum, "featureCount": len(ordered_features)},
            )
            connection.commit()
            return _public_feature_set(inserted) or {}
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def register(
        self,
        *,
        project_id: str,
        authority_review_digest: str,
        draft_feature_set_id: str,
        expected_checksum: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            source_row = connection.execute(
                """
                SELECT * FROM stage3_feature_set_versions
                WHERE feature_set_id = ? AND project_id = ?
                  AND authority_review_digest = ?
                """,
                (draft_feature_set_id, project_id, authority_review_digest),
            ).fetchone()
            if source_row is None:
                raise Stage3FeatureSetPersistenceError(
                    "The exact authority-bound draft feature set does not exist."
                )
            source = decode_row(source_row) or {}
            if source.get("feature_set_status") != "DRAFT":
                raise Stage3FeatureSetPersistenceError(
                    "Only an immutable DRAFT feature set may be registered."
                )
            self._assert_checksum(expected_checksum, str(source["content_sha256"]))
            existing = connection.execute(
                """
                SELECT * FROM stage3_feature_set_versions
                WHERE registered_from_feature_set_id = ?
                  AND feature_set_status = 'REGISTERED'
                """,
                (draft_feature_set_id,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return _public_feature_set(decode_row(existing)) or {}
            rows = self._rows_for_key(
                connection, project_id, str(source["feature_set_key"]), authority_review_digest
            )
            current_draft, current_registered = self._current_for_key(rows)
            if not current_draft or current_draft.get("feature_set_id") != draft_feature_set_id:
                raise Stage3FeatureSetPersistenceError(
                    "A newer immutable draft exists; refresh before registration."
                )
            version = int(rows[0]["feature_set_version"] if rows else 0) + 1
            feature_set_id = f"stage3-feature-set-{uuid.uuid4().hex}"
            authority = {
                "projectId": source["project_id"],
                "registrationId": source["registration_id"],
                "datasetVersionId": source["dataset_version_id"],
                "activationRevision": source["activation_revision"],
                "sourceDatasetId": source["source_dataset_id"],
                "sourceManifestSha": source["source_manifest_sha"],
                "goldManifestSha": source["gold_manifest_sha"],
                "contextualManifestSha": source["contextual_manifest_sha"],
                "reviewDigest": source["authority_review_digest"],
                "development": {
                    "startDate": source["development_start_date"],
                    "endDate": source["development_end_date"],
                    "rows": source["development_rows"],
                },
                "finalOot": {
                    "startDate": source["final_oot_start_date"],
                    "endDate": source["final_oot_end_date"],
                    "rows": source["final_oot_rows"],
                },
            }
            treatments = {
                "outlier": _policy_ref(source, "outlier"),
                "missing": _policy_ref(source, "missing"),
            }
            inserted = self._insert(
                connection,
                feature_set_id=feature_set_id,
                feature_set_key=str(source["feature_set_key"]),
                feature_set_name=str(source["feature_set_name"]),
                version=version,
                status="REGISTERED",
                prior_feature_set_id=str(rows[0]["feature_set_id"]) if rows else None,
                registered_from_feature_set_id=draft_feature_set_id,
                retired_feature_set_id=None,
                authority=authority,
                ordered_features=source["ordered_features_json"],
                family_memberships=source["family_memberships_json"],
                transformation_contracts=source["transformation_contracts_json"],
                interaction_contracts=source["interaction_contracts_json"],
                unavailable_exclusions=source["unavailable_exclusions_json"],
                treatment_policies=treatments,
                description=str(source.get("description") or ""),
                notes=str(source.get("notes") or ""),
                checksum=str(source["content_sha256"]),
                actor_user_id=actor_user_id,
            )
            if current_registered:
                self._event(
                    connection,
                    inserted,
                    event_type="FEATURE_SET_SUPERSEDED",
                    actor_user_id=actor_user_id,
                    prior_feature_set_id=str(current_registered["feature_set_id"]),
                    payload={"supersededFeatureSetId": current_registered["feature_set_id"]},
                )
            self._event(
                connection,
                inserted,
                event_type="FEATURE_SET_REGISTERED",
                actor_user_id=actor_user_id,
                prior_feature_set_id=draft_feature_set_id,
                payload={"registeredFromFeatureSetId": draft_feature_set_id},
            )
            connection.commit()
            return _public_feature_set(inserted) or {}
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def retire(
        self,
        *,
        project_id: str,
        authority_review_digest: str,
        registered_feature_set_id: str,
        expected_checksum: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            source_row = connection.execute(
                """
                SELECT * FROM stage3_feature_set_versions
                WHERE feature_set_id = ? AND project_id = ?
                  AND authority_review_digest = ?
                """,
                (registered_feature_set_id, project_id, authority_review_digest),
            ).fetchone()
            if source_row is None:
                existing = connection.execute(
                    "SELECT * FROM stage3_feature_set_versions WHERE retired_feature_set_id = ?",
                    (registered_feature_set_id,),
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    return _public_feature_set(decode_row(existing)) or {}
                raise Stage3FeatureSetPersistenceError(
                    "The exact registered feature set does not exist."
                )
            source = decode_row(source_row) or {}
            if source.get("feature_set_status") != "REGISTERED":
                raise Stage3FeatureSetPersistenceError(
                    "Only the current REGISTERED feature set may be retired."
                )
            self._assert_checksum(expected_checksum, str(source["content_sha256"]))
            existing = connection.execute(
                "SELECT * FROM stage3_feature_set_versions WHERE retired_feature_set_id = ?",
                (registered_feature_set_id,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return _public_feature_set(decode_row(existing)) or {}
            rows = self._rows_for_key(
                connection, project_id, str(source["feature_set_key"]), authority_review_digest
            )
            _, current_registered = self._current_for_key(rows)
            if not current_registered or current_registered.get("feature_set_id") != registered_feature_set_id:
                raise Stage3FeatureSetPersistenceError(
                    "The requested feature set is no longer current and cannot be retired."
                )
            version = int(rows[0]["feature_set_version"] if rows else 0) + 1
            authority = {
                "projectId": source["project_id"],
                "registrationId": source["registration_id"],
                "datasetVersionId": source["dataset_version_id"],
                "activationRevision": source["activation_revision"],
                "sourceDatasetId": source["source_dataset_id"],
                "sourceManifestSha": source["source_manifest_sha"],
                "goldManifestSha": source["gold_manifest_sha"],
                "contextualManifestSha": source["contextual_manifest_sha"],
                "reviewDigest": source["authority_review_digest"],
                "development": {
                    "startDate": source["development_start_date"],
                    "endDate": source["development_end_date"],
                    "rows": source["development_rows"],
                },
                "finalOot": {
                    "startDate": source["final_oot_start_date"],
                    "endDate": source["final_oot_end_date"],
                    "rows": source["final_oot_rows"],
                },
            }
            treatments = {
                "outlier": _policy_ref(source, "outlier"),
                "missing": _policy_ref(source, "missing"),
            }
            feature_set_id = f"stage3-feature-set-{uuid.uuid4().hex}"
            inserted = self._insert(
                connection,
                feature_set_id=feature_set_id,
                feature_set_key=str(source["feature_set_key"]),
                feature_set_name=str(source["feature_set_name"]),
                version=version,
                status="RETIRED",
                prior_feature_set_id=registered_feature_set_id,
                registered_from_feature_set_id=None,
                retired_feature_set_id=registered_feature_set_id,
                authority=authority,
                ordered_features=source["ordered_features_json"],
                family_memberships=source["family_memberships_json"],
                transformation_contracts=source["transformation_contracts_json"],
                interaction_contracts=source["interaction_contracts_json"],
                unavailable_exclusions=source["unavailable_exclusions_json"],
                treatment_policies=treatments,
                description=str(source.get("description") or ""),
                notes=str(source.get("notes") or ""),
                checksum=str(source["content_sha256"]),
                actor_user_id=actor_user_id,
            )
            self._event(
                connection,
                inserted,
                event_type="FEATURE_SET_RETIRED",
                actor_user_id=actor_user_id,
                prior_feature_set_id=registered_feature_set_id,
                payload={"retiredFeatureSetId": registered_feature_set_id},
            )
            connection.commit()
            return _public_feature_set(inserted) or {}
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()


__all__ = [
    "NO_CURRENT_FEATURE_SET",
    "Stage3FeatureSetPersistenceError",
    "Stage3FeatureSetRepository",
]
