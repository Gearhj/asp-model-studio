from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from ..db import Database, decode_row, json_dumps, now_iso
from .base_repository import BaseRepository


NO_CURRENT_SPLIT_CONTRACT = "NO_CURRENT_SPLIT_CONTRACT"


class Stage3SplitContractPersistenceError(RuntimeError):
    """An immutable split contract is missing, stale, or contradictory."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json_dumps(dict(value), {}).encode("utf-8")).hexdigest()


def _authority_identity(authority: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "projectId": authority.get("projectId"),
        "registrationId": authority.get("registrationId"),
        "datasetVersionId": authority.get("datasetVersionId"),
        "activationRevision": int(authority.get("activationRevision") or 0),
        "sourceDatasetId": authority.get("sourceDatasetId"),
        "sourceManifestSha": authority.get("sourceManifestSha"),
        "goldManifestSha": authority.get("goldManifestSha"),
        "contextualManifestSha": authority.get("contextualManifestSha"),
        "reviewDigest": authority.get("reviewDigest"),
        "development": {
            "startDate": (authority.get("development") or {}).get("startDate"),
            "endDate": (authority.get("development") or {}).get("endDate"),
            "rows": int((authority.get("development") or {}).get("rows") or 0),
        },
        "finalOot": {
            "startDate": (authority.get("finalOot") or {}).get("startDate"),
            "endDate": (authority.get("finalOot") or {}).get("endDate"),
            "rows": int((authority.get("finalOot") or {}).get("rows") or 0),
            "locked": True,
        },
    }


def _identity_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "authority": {
            "projectId": row.get("project_id"),
            "registrationId": row.get("registration_id"),
            "datasetVersionId": row.get("dataset_version_id"),
            "activationRevision": int(row.get("activation_revision") or 0),
            "sourceDatasetId": row.get("source_dataset_id"),
            "sourceManifestSha": row.get("source_manifest_sha"),
            "goldManifestSha": row.get("gold_manifest_sha"),
            "contextualManifestSha": row.get("contextual_manifest_sha"),
            "reviewDigest": row.get("authority_review_digest"),
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
        },
        "contract": row.get("contract_json") or {},
        "selectedFeatureSetIds": list(row.get("selected_feature_set_ids_json") or []),
        "notes": row.get("notes") or "",
    }


def _contract_feature_bindings(
    contract: Mapping[str, Any], selected_ids: Sequence[str]
) -> list[tuple[str, str, int]]:
    registered = {
        str(item.get("featureSetId")): str(item.get("checksum"))
        for item in (contract.get("selectedFeatureSets") or [])
        if isinstance(item, Mapping)
        and str(item.get("featureSetId") or "")
        and len(str(item.get("checksum") or "")) == 64
    }
    return [
        (feature_set_id, registered[feature_set_id], ordinal)
        for ordinal, feature_set_id in enumerate(selected_ids)
        if feature_set_id in registered
    ]


def _public_contract(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    expected = _sha256(_identity_from_row(row))
    if expected != row.get("content_sha256"):
        raise Stage3SplitContractPersistenceError(
            "SPLIT_CONTRACT_CHECKSUM_MISMATCH",
            "The stored immutable split contract does not match its checksum.",
        )
    return {
        "contractId": row.get("split_contract_id"),
        "projectId": row.get("project_id"),
        "contractVersion": int(row.get("contract_version") or 0),
        "status": row.get("contract_status"),
        "priorContractId": row.get("prior_contract_id"),
        "registeredFromContractId": row.get("registered_from_contract_id"),
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
        "splitMode": row.get("split_mode"),
        "foldCount": int(row.get("fold_count") or 0),
        "contract": row.get("contract_json") or {},
        "selectedFeatureSetIds": list(row.get("selected_feature_set_ids_json") or []),
        "notes": row.get("notes") or "",
        "checksum": row.get("content_sha256"),
        "createdByUserId": row.get("created_by_user_id"),
        "createdAt": row.get("created_at"),
        "immutable": True,
    }


class Stage3SplitContractRepository(BaseRepository):
    """Append-only Split & Balance drafts, registrations, and audit events."""

    @staticmethod
    def _rows(
        connection: sqlite3.Connection,
        project_id: str,
        authority_review_digest: str,
    ) -> list[dict[str, Any]]:
        return [
            decode_row(row) or {}
            for row in connection.execute(
                """
                SELECT * FROM stage3_split_contract_versions
                WHERE project_id = ? AND authority_review_digest = ?
                ORDER BY contract_version DESC, created_at DESC
                """,
                (project_id, authority_review_digest),
            ).fetchall()
        ]

    @staticmethod
    def _surface(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        current_registered = next(
            (row for row in rows if row.get("contract_status") == "REGISTERED"),
            None,
        )
        registered_version = (
            int(current_registered.get("contract_version") or 0)
            if current_registered
            else 0
        )
        draft = next(
            (
                row
                for row in rows
                if row.get("contract_status") == "DRAFT"
                and int(row.get("contract_version") or 0) > registered_version
            ),
            None,
        )
        return draft or current_registered

    def _event(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
        *,
        event_type: str,
        actor_user_id: str,
        prior_contract_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO stage3_split_contract_events (
              split_contract_event_id, split_contract_id, project_id,
              contract_version, event_type, actor_user_id, prior_contract_id,
              authority_review_digest, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"stage3-split-event-{uuid.uuid4().hex}",
                row["split_contract_id"],
                row["project_id"],
                int(row["contract_version"]),
                event_type,
                actor_user_id,
                prior_contract_id,
                row["authority_review_digest"],
                now_iso(),
                json_dumps(dict(payload or {}), {}),
            ),
        )

    def list_versions(
        self, project_id: str, authority_review_digest: str
    ) -> list[dict[str, Any]]:
        rows = self._many(
            """
            SELECT * FROM stage3_split_contract_versions
            WHERE project_id = ? AND authority_review_digest = ?
            ORDER BY contract_version DESC, created_at DESC
            """,
            (project_id, authority_review_digest),
        )
        return [_public_contract(row) or {} for row in rows]

    def get(self, contract_id: str) -> dict[str, Any] | None:
        return _public_contract(
            self._one(
                "SELECT * FROM stage3_split_contract_versions WHERE split_contract_id = ?",
                (contract_id,),
            )
        )

    def contract_state(
        self, project_id: str, authority_review_digest: str
    ) -> dict[str, Any]:
        versions = self.list_versions(project_id, authority_review_digest)
        registered_draft_ids = {
            str(row["registeredFromContractId"])
            for row in versions
            if row["status"] == "REGISTERED" and row.get("registeredFromContractId")
        }
        current_registered = next(
            (row for row in versions if row["status"] == "REGISTERED"), None
        )
        current_registered_id = (
            current_registered.get("contractId") if current_registered else None
        )
        current_registered_version = (
            int(current_registered.get("contractVersion") or 0)
            if current_registered
            else 0
        )
        latest_draft = next(
            (
                row
                for row in versions
                if row["status"] == "DRAFT"
                and int(row.get("contractVersion") or 0)
                > current_registered_version
            ),
            None,
        )
        history: list[dict[str, Any]] = []
        for row in versions:
            public = dict(row)
            if (
                public["status"] == "REGISTERED"
                and public["contractId"] != current_registered_id
            ):
                public["status"] = "SUPERSEDED"
            elif (
                public["status"] == "DRAFT"
                and public["contractId"] in registered_draft_ids
            ):
                public["status"] = "REGISTERED_SOURCE_DRAFT"
            elif (
                public["status"] == "DRAFT"
                and current_registered
                and int(public.get("contractVersion") or 0)
                < current_registered_version
            ):
                public["status"] = "SUPERSEDED_DRAFT"
            history.append(public)
        surface = latest_draft or current_registered
        return {
            "latestDraft": latest_draft,
            "currentRegistered": current_registered,
            "history": history,
            "expectedChecksum": (
                surface.get("checksum") if surface else NO_CURRENT_SPLIT_CONTRACT
            ),
        }

    def save_draft(
        self,
        *,
        authority: Mapping[str, Any],
        split_mode: str,
        contract: Mapping[str, Any],
        selected_feature_set_ids: Sequence[str],
        notes: str,
        expected_checksum: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        if split_mode not in {"AUTOMATIC", "MANUAL"}:
            raise Stage3SplitContractPersistenceError(
                "SPLIT_MODE_INVALID", "Split mode must be AUTOMATIC or MANUAL."
            )
        if not expected_checksum:
            raise Stage3SplitContractPersistenceError(
                "SPLIT_EXPECTED_CHECKSUM_REQUIRED",
                "Concurrent-save protection requires expectedChecksum.",
            )
        selected_ids = list(dict.fromkeys(str(value) for value in selected_feature_set_ids))
        identity = {
            "authority": _authority_identity(authority),
            "contract": dict(contract),
            "selectedFeatureSetIds": selected_ids,
            "notes": notes,
        }
        checksum = _sha256(identity)
        feature_bindings = _contract_feature_bindings(contract, selected_ids)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = self._rows(
                connection,
                str(authority["projectId"]),
                str(authority["reviewDigest"]),
            )
            surface = self._surface(rows)
            actual_checksum = (
                str(surface.get("content_sha256"))
                if surface
                else NO_CURRENT_SPLIT_CONTRACT
            )
            if expected_checksum != actual_checksum:
                raise Stage3SplitContractPersistenceError(
                    "SPLIT_CONCURRENT_SAVE_CONFLICT",
                    "The split contract changed after this editor loaded; reload before saving.",
                )
            if (
                surface
                and surface.get("contract_status") == "DRAFT"
                and surface.get("content_sha256") == checksum
            ):
                connection.commit()
                return _public_contract(surface) or {}
            version = max(
                (int(row.get("contract_version") or 0) for row in rows), default=0
            ) + 1
            contract_id = f"stage3-split-contract-{uuid.uuid4().hex}"
            timestamp = now_iso()
            connection.execute(
                """
                INSERT INTO stage3_split_contract_versions (
                  split_contract_id, project_id, contract_version,
                  contract_status, prior_contract_id, registered_from_contract_id,
                  registration_id, dataset_version_id, activation_revision,
                  source_dataset_id, source_manifest_sha, gold_manifest_sha,
                  contextual_manifest_sha, authority_review_digest,
                  development_start_date, development_end_date, development_rows,
                  final_oot_start_date, final_oot_end_date, final_oot_rows,
                  split_mode, fold_count, contract_json,
                  selected_feature_set_ids_json, notes, content_sha256,
                  created_by_user_id, created_at
                ) VALUES (
                  ?, ?, ?, 'DRAFT', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    contract_id,
                    authority["projectId"],
                    version,
                    surface.get("split_contract_id") if surface else None,
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
                    split_mode,
                    int(contract.get("foldCount") or 0),
                    json_dumps(dict(contract), {}),
                    json_dumps(selected_ids, []),
                    notes,
                    checksum,
                    actor_user_id,
                    timestamp,
                ),
            )
            try:
                connection.executemany(
                    """
                    INSERT INTO stage3_split_contract_feature_sets (
                      split_contract_id, feature_set_id,
                      feature_set_checksum, ordinal
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [
                        (contract_id, feature_set_id, feature_checksum, ordinal)
                        for feature_set_id, feature_checksum, ordinal in feature_bindings
                    ],
                )
            except sqlite3.IntegrityError as exc:
                raise Stage3SplitContractPersistenceError(
                    "SPLIT_FEATURE_SET_AUTHORITY_BLOCKED",
                    "A selected feature set no longer matches its immutable registered checksum.",
                ) from exc
            inserted = decode_row(
                connection.execute(
                    "SELECT * FROM stage3_split_contract_versions WHERE split_contract_id = ?",
                    (contract_id,),
                ).fetchone()
            ) or {}
            self._event(
                connection,
                inserted,
                event_type="DRAFT_UPDATED" if surface else "DRAFT_CREATED",
                actor_user_id=actor_user_id,
                prior_contract_id=inserted.get("prior_contract_id"),
                payload={"checksum": checksum},
            )
            connection.commit()
            return _public_contract(inserted) or {}
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
        draft_contract_id: str,
        expected_checksum: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        if not expected_checksum:
            raise Stage3SplitContractPersistenceError(
                "SPLIT_EXPECTED_CHECKSUM_REQUIRED",
                "Registration requires the exact immutable draft checksum.",
            )
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM stage3_split_contract_versions
                WHERE project_id = ? AND authority_review_digest = ?
                  AND contract_status = 'REGISTERED'
                  AND registered_from_contract_id = ?
                """,
                (project_id, authority_review_digest, draft_contract_id),
            ).fetchone()
            if existing is not None:
                decoded = decode_row(existing) or {}
                if decoded.get("content_sha256") != expected_checksum:
                    raise Stage3SplitContractPersistenceError(
                        "SPLIT_CONTRACT_CHECKSUM_MISMATCH",
                        "The registered split contract checksum differs from the request.",
                    )
                connection.commit()
                return _public_contract(decoded) or {}
            rows = self._rows(connection, project_id, authority_review_digest)
            source = next(
                (
                    row
                    for row in rows
                    if row.get("split_contract_id") == draft_contract_id
                ),
                None,
            )
            if source is None or source.get("contract_status") != "DRAFT":
                raise Stage3SplitContractPersistenceError(
                    "SPLIT_DRAFT_REQUIRED",
                    "Only an exact immutable DRAFT split contract may be registered.",
                )
            if source.get("content_sha256") != expected_checksum:
                raise Stage3SplitContractPersistenceError(
                    "SPLIT_CONTRACT_CHECKSUM_MISMATCH",
                    "The requested draft checksum does not match its immutable content.",
                )
            source_bindings = connection.execute(
                """
                SELECT feature_set_id, feature_set_checksum, ordinal
                FROM stage3_split_contract_feature_sets
                WHERE split_contract_id = ?
                ORDER BY ordinal ASC
                """,
                (draft_contract_id,),
            ).fetchall()
            expected_bindings = _contract_feature_bindings(
                source.get("contract_json") or {},
                source.get("selected_feature_set_ids_json") or [],
            )
            actual_bindings = [
                (
                    str(row["feature_set_id"]),
                    str(row["feature_set_checksum"]),
                    int(row["ordinal"]),
                )
                for row in source_bindings
            ]
            if actual_bindings != expected_bindings or len(actual_bindings) != len(
                source.get("selected_feature_set_ids_json") or []
            ):
                raise Stage3SplitContractPersistenceError(
                    "SPLIT_FEATURE_SET_AUTHORITY_BLOCKED",
                    "Registration requires an exact immutable feature-set ID/checksum binding for every selected set.",
                )
            surface = self._surface(rows)
            if not surface or surface.get("split_contract_id") != draft_contract_id:
                raise Stage3SplitContractPersistenceError(
                    "SPLIT_CONCURRENT_SAVE_CONFLICT",
                    "A newer split contract exists; reload before registration.",
                )
            prior_registered = next(
                (row for row in rows if row.get("contract_status") == "REGISTERED"),
                None,
            )
            version = max(
                (int(row.get("contract_version") or 0) for row in rows), default=0
            ) + 1
            contract_id = f"stage3-split-contract-{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO stage3_split_contract_versions (
                  split_contract_id, project_id, contract_version,
                  contract_status, prior_contract_id, registered_from_contract_id,
                  registration_id, dataset_version_id, activation_revision,
                  source_dataset_id, source_manifest_sha, gold_manifest_sha,
                  contextual_manifest_sha, authority_review_digest,
                  development_start_date, development_end_date, development_rows,
                  final_oot_start_date, final_oot_end_date, final_oot_rows,
                  split_mode, fold_count, contract_json,
                  selected_feature_set_ids_json, notes, content_sha256,
                  created_by_user_id, created_at
                ) VALUES (
                  ?, ?, ?, 'REGISTERED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    contract_id,
                    project_id,
                    version,
                    source["split_contract_id"],
                    source["split_contract_id"],
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
                    source["split_mode"],
                    int(source["fold_count"]),
                    json_dumps(source["contract_json"], {}),
                    json_dumps(source["selected_feature_set_ids_json"], []),
                    source["notes"],
                    source["content_sha256"],
                    actor_user_id,
                    now_iso(),
                ),
            )
            connection.executemany(
                """
                INSERT INTO stage3_split_contract_feature_sets (
                  split_contract_id, feature_set_id,
                  feature_set_checksum, ordinal
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (contract_id, feature_set_id, feature_checksum, ordinal)
                    for feature_set_id, feature_checksum, ordinal in actual_bindings
                ],
            )
            inserted = decode_row(
                connection.execute(
                    "SELECT * FROM stage3_split_contract_versions WHERE split_contract_id = ?",
                    (contract_id,),
                ).fetchone()
            ) or {}
            if prior_registered is not None:
                self._event(
                    connection,
                    inserted,
                    event_type="CONTRACT_SUPERSEDED",
                    actor_user_id=actor_user_id,
                    prior_contract_id=str(prior_registered["split_contract_id"]),
                    payload={
                        "supersededContractId": prior_registered[
                            "split_contract_id"
                        ]
                    },
                )
            self._event(
                connection,
                inserted,
                event_type="CONTRACT_REGISTERED",
                actor_user_id=actor_user_id,
                prior_contract_id=draft_contract_id,
                payload={"registeredFromContractId": draft_contract_id},
            )
            connection.commit()
            return _public_contract(inserted) or {}
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()


__all__ = [
    "NO_CURRENT_SPLIT_CONTRACT",
    "Stage3SplitContractPersistenceError",
    "Stage3SplitContractRepository",
]
