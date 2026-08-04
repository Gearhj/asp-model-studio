from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional

from ..db import decode_row, json_dumps, now_iso
from .base_repository import BaseRepository

_MODEL_FILTERABLE = {"project_id", "problem_type", "status", "owner_user_id"}
_VERSION_FILTERABLE = {
    "model_id",
    "algorithm",
    "approval_status",
    "validation_status",
    "training_run_id",
    "publication_status",
    "lineage_status",
    "candidate_id",
    "evaluation_package_id",
    "validation_design_id",
    "split_id",
}


class ModelRegistryConflictError(RuntimeError):
    """A durable registry identity or compare-and-set contract conflicted."""


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _insert_model_row(connection: sqlite3.Connection, record: Dict[str, Any]) -> None:
    timestamp = record.get("created_at") or now_iso()
    connection.execute(
        """
        INSERT INTO models (
          model_id, project_id, name, problem_type, status, owner_user_id,
          created_at, updated_at, current_version_id,
          current_version_generation, champion_updated_at, champion_updated_by,
          archived, archived_at, tags_json, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["model_id"],
            record.get("project_id"),
            record.get("name") or "Untitled Model",
            record.get("problem_type"),
            record.get("status") or "active",
            record.get("owner_user_id"),
            timestamp,
            record.get("updated_at") or timestamp,
            record.get("current_version_id"),
            int(record.get("current_version_generation") or 0),
            record.get("champion_updated_at"),
            record.get("champion_updated_by"),
            int(bool(record.get("archived"))),
            record.get("archived_at"),
            json_dumps(record.get("tags_json"), []),
            record.get("description"),
        ),
    )


def _insert_version_row(connection: sqlite3.Connection, record: Dict[str, Any]) -> None:
    timestamp = record.get("created_at") or now_iso()
    connection.execute(
        """
        INSERT INTO model_versions (
          model_version_id, model_id, version_number, training_run_id, project_id,
          dataset_id, dataset_version_id, feature_manifest_version, algorithm, algorithm_version,
          hyperparameters_json, training_parameters_json, metrics_summary_json,
          evaluation_summary_json, interpretation_summary_json,
          artifact_reference, artifact_format, training_timestamp, checksum,
          artifact_size_bytes, publication_status, artifact_verified_at, finalized_at,
          idempotency_key, publication_fingerprint, lineage_status,
          quarantine_reason, quarantined_at,
          candidate_id, evaluation_package_id,
          candidate_decision_id, candidate_decision_status,
          candidate_decision_contract_hash,
          selection_metric_name, selection_metric_value,
          selection_metric_source, selection_metric_created_at,
          out_of_fold_prediction_artifact_id, selection_integrity_status,
          selection_locked_at, holdout_exposure_id,
          final_holdout_partition_id, final_holdout_status,
          holdout_isolation_status, threshold_locked_at,
          locked_threshold, threshold_source, threshold_policy_hash,
          evaluation_package_contract_hash, evaluation_package_content_hash,
          evaluation_package_integrity_status,
          promotion_readiness_status,
          target_name,
          validation_design_id, split_id, candidate_contract_hash,
          selected_candidate_contract_hash,
          model_contract_json, previous_champion_version_id,
          approval_status, validation_status, documentation_status, lineage_json,
          archived_at, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["model_version_id"],
            record["model_id"],
            int(record["version_number"]),
            record.get("training_run_id"),
            record.get("project_id"),
            record.get("dataset_id"),
            record.get("dataset_version_id"),
            record.get("feature_manifest_version"),
            record.get("algorithm"),
            record.get("algorithm_version"),
            json_dumps(record.get("hyperparameters_json"), {}),
            json_dumps(record.get("training_parameters_json"), {}),
            json_dumps(record.get("metrics_summary_json"), {}),
            json_dumps(record.get("evaluation_summary_json"), {}),
            json_dumps(record.get("interpretation_summary_json"), {}),
            record.get("artifact_reference"),
            record.get("artifact_format"),
            record.get("training_timestamp"),
            record.get("checksum"),
            record.get("artifact_size_bytes"),
            record.get("publication_status") or "legacy_unresolved",
            record.get("artifact_verified_at"),
            record.get("finalized_at"),
            record.get("idempotency_key"),
            record.get("publication_fingerprint"),
            record.get("lineage_status") or "legacy_unresolved",
            record.get("quarantine_reason"),
            record.get("quarantined_at"),
            record.get("candidate_id"),
            record.get("evaluation_package_id"),
            record.get("candidate_decision_id"),
            record.get("candidate_decision_status") or "legacy_unresolved",
            record.get("candidate_decision_contract_hash"),
            record.get("selection_metric_name") or "legacy_unresolved",
            record.get("selection_metric_value"),
            record.get("selection_metric_source") or "legacy_unresolved",
            record.get("selection_metric_created_at"),
            record.get("out_of_fold_prediction_artifact_id"),
            record.get("selection_integrity_status") or "legacy_unresolved",
            record.get("selection_locked_at"),
            record.get("holdout_exposure_id"),
            record.get("final_holdout_partition_id"),
            record.get("final_holdout_status") or "legacy_unresolved",
            record.get("holdout_isolation_status") or "legacy_unresolved",
            record.get("threshold_locked_at"),
            record.get("locked_threshold"),
            record.get("threshold_source"),
            record.get("threshold_policy_hash"),
            record.get("evaluation_package_contract_hash"),
            record.get("evaluation_package_content_hash"),
            record.get("evaluation_package_integrity_status")
            or "legacy_unresolved",
            record.get("promotion_readiness_status") or "legacy_unresolved",
            record.get("target_name"),
            record.get("validation_design_id"),
            record.get("split_id"),
            record.get("candidate_contract_hash"),
            record.get("selected_candidate_contract_hash"),
            json_dumps(record.get("model_contract_json"), {}),
            record.get("previous_champion_version_id"),
            record.get("approval_status") or "unreviewed",
            record.get("validation_status") or "not_validated",
            record.get("documentation_status") or "not_documented",
            json_dumps(record.get("lineage_json"), {}),
            record.get("archived_at"),
            record.get("created_by"),
            timestamp,
        ),
    )


def _assert_durable_promotion_governance(
    connection: sqlite3.Connection,
    record: Dict[str, Any],
) -> None:
    """Recheck promotion gates under the same write lock as publication."""
    lineage = record.get("lineage_json")
    if not isinstance(lineage, dict):
        raise ModelRegistryConflictError(
            "Finalized publication requires exact durable governance lineage."
        )
    for artifact_type, artifact_id in (
        ("candidate_decision", record.get("candidate_decision_id")),
        ("evaluation_package", record.get("evaluation_package_id")),
    ):
        if artifact_id and connection.execute(
            """
            SELECT 1
            FROM analysis_partition_derivative_invalidations
            WHERE artifact_type = ? AND artifact_id = ?
              AND invalidation_status = 'invalidated'
            LIMIT 1
            """,
            (artifact_type, artifact_id),
        ).fetchone():
            raise ModelRegistryConflictError(
                "Model publication references governance evidence invalidated by an Analysis Partition reset."
            )
    decision = decode_row(
        connection.execute(
            """
            SELECT * FROM candidate_selection_decisions
            WHERE candidate_decision_id = ? AND project_id = ?
              AND dataset_id = ? AND dataset_version_id = ?
              AND validation_design_id = ? AND validation_design_version_id = ?
              AND split_id = ? AND training_run_id = ? AND candidate_id = ?
              AND decision_status = 'locked'
              AND selection_integrity_status = 'verified'
              AND holdout_isolation_status = 'verified'
            """,
            (
                record["candidate_decision_id"],
                record["project_id"],
                record["dataset_id"],
                record["dataset_version_id"],
                record["validation_design_id"],
                lineage.get("validationDesignVersion"),
                record["split_id"],
                record["training_run_id"],
                record["candidate_id"],
            ),
        ).fetchone()
    )
    if (
        decision is None
        or decision.get("decision_contract_hash")
        != record.get("candidate_decision_contract_hash")
        or decision.get("selection_metric_name")
        != record.get("selection_metric_name")
        or decision.get("selection_metric_value")
        != record.get("selection_metric_value")
        or decision.get("selection_metric_source")
        != record.get("selection_metric_source")
        or decision.get("selection_metric_created_at")
        != record.get("selection_metric_created_at")
        or decision.get("out_of_fold_prediction_artifact_id")
        != record.get("out_of_fold_prediction_artifact_id")
        or decision.get("selected_candidate_contract_hash")
        != record.get("selected_candidate_contract_hash")
        or decision.get("selection_locked_at")
        != record.get("selection_locked_at")
        or decision.get("locked_threshold") != record.get("locked_threshold")
        or decision.get("threshold_source") != record.get("threshold_source")
        or decision.get("threshold_locked_at")
        != record.get("threshold_locked_at")
        or decision.get("threshold_policy_hash")
        != record.get("threshold_policy_hash")
        or decision.get("final_holdout_partition_id")
        != record.get("final_holdout_partition_id")
    ):
        raise ModelRegistryConflictError(
            "The exact locked candidate decision changed before publication."
        )
    exposure = decode_row(
        connection.execute(
            """
            SELECT * FROM holdout_exposures
            WHERE holdout_exposure_id = ? AND project_id = ?
              AND dataset_id = ? AND dataset_version_id = ?
              AND validation_design_id = ?
              AND validation_design_version_id = ? AND split_id = ?
              AND final_holdout_partition_id = ?
              AND candidate_decision_id = ? AND candidate_id = ?
              AND final_holdout_status = 'evaluated'
              AND evaluation_package_id = ?
              AND invalidated_at IS NULL
              AND invalidated_by IS NULL
              AND invalidation_reason IS NULL
            """,
            (
                record["holdout_exposure_id"],
                record["project_id"],
                record["dataset_id"],
                record["dataset_version_id"],
                record["validation_design_id"],
                lineage.get("validationDesignVersion"),
                record["split_id"],
                record["final_holdout_partition_id"],
                record["candidate_decision_id"],
                record["candidate_id"],
                record["evaluation_package_id"],
            ),
        ).fetchone()
    )
    package = decode_row(
        connection.execute(
            """
            SELECT * FROM evaluation_packages
            WHERE evaluation_package_id = ? AND project_id = ?
              AND dataset_id = ? AND dataset_version_id = ?
              AND training_run_id = ? AND candidate_id = ?
              AND candidate_decision_id = ? AND holdout_exposure_id = ?
              AND package_status = 'complete'
              AND selection_integrity_status = 'verified'
              AND holdout_isolation_status = 'verified'
              AND final_holdout_status = 'evaluated'
              AND package_integrity_status = 'verified'
              AND recommendations_derived_from_final_holdout = 0
            """,
            (
                record["evaluation_package_id"],
                record["project_id"],
                record["dataset_id"],
                record["dataset_version_id"],
                record["training_run_id"],
                record["candidate_id"],
                record["candidate_decision_id"],
                record["holdout_exposure_id"],
            ),
        ).fetchone()
    )
    if (
        exposure is None
        or package is None
        or package.get("selected_candidate_contract_hash")
        != record.get("selected_candidate_contract_hash")
        or package.get("selection_metric_created_at")
        != record.get("selection_metric_created_at")
        or package.get("out_of_fold_prediction_artifact_id")
        != record.get("out_of_fold_prediction_artifact_id")
        or package.get("locked_threshold") != record.get("locked_threshold")
        or package.get("threshold_source") != record.get("threshold_source")
        or package.get("threshold_policy_hash")
        != record.get("threshold_policy_hash")
        or package.get("evaluation_package_contract_hash")
        != record.get("evaluation_package_contract_hash")
        or package.get("content_hash")
        != record.get("evaluation_package_content_hash")
        or package.get("threshold_locked_at")
        != record.get("threshold_locked_at")
        or exposure.get("first_opened_at") is None
        or package.get("holdout_exposed_at") != exposure.get("first_opened_at")
    ):
        raise ModelRegistryConflictError(
            "The exact evaluated holdout package changed before publication."
        )
    package_payload = package.get("package_payload_json")
    threshold_policy = package.get("threshold_policy_json")
    candidate_contract = lineage.get("candidateContract")
    ranking_snapshot = decision.get("ranking_snapshot_json")
    if (
        not isinstance(package_payload, dict)
        or not package_payload
        or _canonical_hash(package_payload) != package.get("content_hash")
        or not isinstance(threshold_policy, dict)
        or not isinstance(candidate_contract, dict)
        or not isinstance(ranking_snapshot, list)
        or _canonical_hash(ranking_snapshot)
        != decision.get("ranking_snapshot_hash")
    ):
        raise ModelRegistryConflictError(
            "The exact promotion governance payload hashes do not verify."
        )
    threshold_tuple = {
        "locked_threshold": decision.get("locked_threshold"),
        "threshold_source": decision.get("threshold_source"),
        "threshold_locked_at": decision.get("threshold_locked_at"),
        "selection_threshold_tuned": False,
    }
    threshold_configuration = candidate_contract.get(
        "threshold_configuration"
    )
    candidate_payload = dict(candidate_contract)
    candidate_payload.pop("contract_hash", None)
    selected_snapshot = next(
        (
            row
            for row in ranking_snapshot
            if isinstance(row, dict)
            and row.get("candidate_id") == record.get("candidate_id")
        ),
        None,
    )
    if (
        not isinstance(threshold_configuration, dict)
        or _canonical_hash(candidate_payload)
        != record.get("selected_candidate_contract_hash")
        or candidate_contract.get("contract_hash")
        != record.get("selected_candidate_contract_hash")
        or not isinstance(selected_snapshot, dict)
        or selected_snapshot.get("candidate_contract_hash")
        != record.get("selected_candidate_contract_hash")
        or threshold_policy != {
            **threshold_tuple,
            "threshold_policy_hash": decision.get("threshold_policy_hash"),
        }
        or _canonical_hash(threshold_tuple)
        != decision.get("threshold_policy_hash")
        or threshold_configuration != {
            **threshold_tuple,
            "threshold_policy_hash": decision.get("threshold_policy_hash"),
        }
    ):
        raise ModelRegistryConflictError(
            "The exact locked threshold policy changed before publication."
        )
    package_contract = {
        "evaluation_package_id": package.get("evaluation_package_id"),
        "completion_content_hash": package_payload.get(
            "completion_content_hash"
        ),
        "holdout_prediction_digest": package_payload.get(
            "holdout_prediction_digest"
        ),
        "candidate_decision_id": package.get("candidate_decision_id"),
        "holdout_exposure_id": package.get("holdout_exposure_id"),
        "content_hash": package.get("content_hash"),
    }
    if _canonical_hash(package_contract) != package.get(
        "evaluation_package_contract_hash"
    ):
        raise ModelRegistryConflictError(
            "The exact Evaluation package contract hash changed before publication."
        )


class ModelRepository(BaseRepository):
    def list(
        self,
        *,
        project_id: Optional[str] = None,
        problem_type: Optional[str] = None,
        status: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        filters = {"project_id": project_id, "problem_type": problem_type, "status": status, "owner_user_id": owner_user_id}
        clauses: List[str] = []
        params: List[Any] = []
        for column, value in filters.items():
            if value is None or column not in _MODEL_FILTERABLE:
                continue
            clauses.append(f"{column} = ?")
            params.append(value)
        if not include_archived:
            clauses.append("archived = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        bounded_limit = max(1, min(int(limit or 200), 1000))
        query = f"SELECT * FROM models {where} ORDER BY created_at DESC LIMIT ?"
        params.append(bounded_limit)
        return self._many(query, tuple(params))

    def get(self, model_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM models WHERE model_id = ?", (model_id,))

    def find_by_name(self, project_id: str, name: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM models WHERE project_id = ? AND name = ? AND archived = 0", (project_id, name))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO models (
              model_id, project_id, name, problem_type, status, owner_user_id,
              created_at, updated_at, current_version_id,
              current_version_generation, champion_updated_at, champion_updated_by,
              archived, archived_at, tags_json, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_id) DO UPDATE SET
              status = excluded.status,
              updated_at = excluded.updated_at,
              current_version_id = excluded.current_version_id,
              current_version_generation = excluded.current_version_generation,
              champion_updated_at = excluded.champion_updated_at,
              champion_updated_by = excluded.champion_updated_by,
              archived = excluded.archived,
              archived_at = excluded.archived_at,
              tags_json = excluded.tags_json,
              description = excluded.description
            """,
            (
                record["model_id"], record.get("project_id"), record.get("name") or "Untitled Model",
                record.get("problem_type"), record.get("status") or "active", record.get("owner_user_id"),
                timestamp, record.get("updated_at") or timestamp, record.get("current_version_id"),
                int(record.get("current_version_generation") or 0),
                record.get("champion_updated_at"), record.get("champion_updated_by"),
                int(bool(record.get("archived"))), record.get("archived_at"),
                json_dumps(record.get("tags_json"), []), record.get("description"),
            ),
        )
        return self.get(record["model_id"]) or {}

    def promote_champion(
        self,
        model_id: str,
        model_version_id: str,
        *,
        actor_user_id: str,
        expected_generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Compare-and-set the champion pointer under an immediate write lock."""
        with self.database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            model = decode_row(
                connection.execute(
                    "SELECT * FROM models WHERE model_id = ?",
                    (model_id,),
                ).fetchone()
            )
            version = decode_row(
                connection.execute(
                    "SELECT * FROM model_versions WHERE model_version_id = ?",
                    (model_version_id,),
                ).fetchone()
            )
            if (
                not model
                or not version
                or version.get("model_id") != model_id
                or version.get("project_id") != model.get("project_id")
            ):
                raise ModelRegistryConflictError(
                    "The requested champion is not a version of this model."
                )
            if (
                model.get("archived")
                or version.get("archived_at")
                or version.get("publication_status") != "finalized"
                or version.get("lineage_status") != "verified"
                or version.get("quarantine_reason")
            ):
                raise ModelRegistryConflictError(
                    "Only a finalized, verified, non-quarantined version may be champion."
                )
            current_generation = int(
                model.get("current_version_generation") or 0
            )
            if (
                expected_generation is not None
                and int(expected_generation) != current_generation
            ):
                raise ModelRegistryConflictError(
                    "The champion pointer changed; reload before promoting."
                )
            if model.get("current_version_id") == model_version_id:
                return model
            timestamp = now_iso()
            cursor = connection.execute(
                """
                UPDATE models
                SET current_version_id = ?,
                    current_version_generation = current_version_generation + 1,
                    champion_updated_at = ?, champion_updated_by = ?, updated_at = ?
                WHERE model_id = ? AND current_version_generation = ? AND archived = 0
                """,
                (
                    model_version_id,
                    timestamp,
                    actor_user_id,
                    timestamp,
                    model_id,
                    current_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise ModelRegistryConflictError(
                    "The champion pointer changed; reload before promoting."
                )
            return decode_row(
                connection.execute(
                    "SELECT * FROM models WHERE model_id = ?",
                    (model_id,),
                ).fetchone()
            ) or {}

    def clear_champion_if_current(
        self,
        model_id: str,
        model_version_id: str,
        *,
        actor_user_id: str,
    ) -> Dict[str, Any] | None:
        with self.database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            model = decode_row(
                connection.execute(
                    "SELECT * FROM models WHERE model_id = ?",
                    (model_id,),
                ).fetchone()
            )
            if not model:
                return None
            if model.get("current_version_id") != model_version_id:
                return model
            timestamp = now_iso()
            generation = int(model.get("current_version_generation") or 0)
            cursor = connection.execute(
                """
                UPDATE models
                SET current_version_id = NULL,
                    current_version_generation = current_version_generation + 1,
                    champion_updated_at = ?, champion_updated_by = ?, updated_at = ?
                WHERE model_id = ? AND current_version_generation = ?
                  AND current_version_id = ?
                """,
                (
                    timestamp,
                    actor_user_id,
                    timestamp,
                    model_id,
                    generation,
                    model_version_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ModelRegistryConflictError(
                    "The champion pointer changed while the version was archived."
                )
            return decode_row(
                connection.execute(
                    "SELECT * FROM models WHERE model_id = ?",
                    (model_id,),
                ).fetchone()
            )

    def archive(
        self,
        model_id: str,
        *,
        actor_user_id: str,
    ) -> Dict[str, Any] | None:
        with self.database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            model = decode_row(
                connection.execute(
                    "SELECT * FROM models WHERE model_id = ?",
                    (model_id,),
                ).fetchone()
            )
            if not model:
                return None
            timestamp = now_iso()
            connection.execute(
                """
                UPDATE models
                SET archived = 1, archived_at = ?, status = 'archived',
                    current_version_id = NULL,
                    current_version_generation = current_version_generation
                      + CASE WHEN current_version_id IS NULL THEN 0 ELSE 1 END,
                    champion_updated_at = ?, champion_updated_by = ?, updated_at = ?
                WHERE model_id = ?
                """,
                (
                    timestamp,
                    timestamp,
                    actor_user_id,
                    timestamp,
                    model_id,
                ),
            )
            return decode_row(
                connection.execute(
                    "SELECT * FROM models WHERE model_id = ?",
                    (model_id,),
                ).fetchone()
            )

    def archive_for_project(self, project_id: str) -> int:
        rows = self.list(project_id=project_id, include_archived=False, limit=1000)
        timestamp = now_iso()
        for row in rows:
            self._write(
                """
                UPDATE models
                SET archived = 1, archived_at = ?, status = 'archived',
                    current_version_id = NULL,
                    current_version_generation = current_version_generation
                      + CASE WHEN current_version_id IS NULL THEN 0 ELSE 1 END,
                    champion_updated_at = ?, champion_updated_by = ?, updated_at = ?
                WHERE model_id = ?
                """,
                (
                    timestamp,
                    timestamp,
                    "project-archive",
                    timestamp,
                    row["model_id"],
                ),
            )
        return len(rows)


class ModelVersionRepository(BaseRepository):
    def list(
        self,
        *,
        model_id: Optional[str] = None,
        algorithm: Optional[str] = None,
        approval_status: Optional[str] = None,
        validation_status: Optional[str] = None,
        training_run_id: Optional[str] = None,
        publication_status: Optional[str] = None,
        lineage_status: Optional[str] = None,
        candidate_id: Optional[str] = None,
        evaluation_package_id: Optional[str] = None,
        validation_design_id: Optional[str] = None,
        split_id: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        filters = {
            "model_id": model_id, "algorithm": algorithm, "approval_status": approval_status,
            "validation_status": validation_status, "training_run_id": training_run_id,
            "publication_status": publication_status, "lineage_status": lineage_status,
            "candidate_id": candidate_id, "evaluation_package_id": evaluation_package_id,
            "validation_design_id": validation_design_id, "split_id": split_id,
        }
        clauses: List[str] = []
        params: List[Any] = []
        for column, value in filters.items():
            if value is None or column not in _VERSION_FILTERABLE:
                continue
            clauses.append(f"{column} = ?")
            params.append(value)
        if not include_archived:
            clauses.append("archived_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        bounded_limit = max(1, min(int(limit or 200), 1000))
        query = f"SELECT * FROM model_versions {where} ORDER BY version_number DESC LIMIT ?"
        params.append(bounded_limit)
        return self._many(query, tuple(params))

    def get(self, model_version_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM model_versions WHERE model_version_id = ?", (model_version_id,))

    def get_many(self, model_version_ids: List[str]) -> List[Dict[str, Any]]:
        if not model_version_ids:
            return []
        placeholders = ",".join("?" for _ in model_version_ids)
        return self._many(f"SELECT * FROM model_versions WHERE model_version_id IN ({placeholders})", tuple(model_version_ids))

    def artifact_version_ids(self) -> set[str]:
        return {
            str(row["model_version_id"])
            for row in self._many(
                "SELECT model_version_id FROM model_versions WHERE artifact_reference IS NOT NULL"
            )
        }

    def find_current_by_exact_context(
        self,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        target_name: str,
    ) -> List[Dict[str, Any]]:
        """Resolve only exact, ready champion pointers; never latest/first."""
        return self._many(
            """
            SELECT mv.*
            FROM models AS m
            JOIN model_versions AS mv
              ON mv.model_version_id = m.current_version_id
             AND mv.model_id = m.model_id
             AND mv.project_id = m.project_id
            WHERE m.project_id = ?
              AND m.archived = 0
              AND mv.project_id = ?
              AND mv.dataset_id = ?
              AND mv.dataset_version_id = ?
              AND mv.target_name = ?
              AND mv.publication_status = 'finalized'
              AND mv.lineage_status = 'verified'
              AND mv.quarantine_reason IS NULL
              AND mv.quarantined_at IS NULL
              AND mv.archived_at IS NULL
            ORDER BY m.model_id ASC
            LIMIT 3
            """,
            (
                project_id,
                project_id,
                dataset_id,
                dataset_version_id,
                target_name,
            ),
        )

    def next_version_number(self, model_id: str) -> int:
        row = self._one("SELECT MAX(version_number) AS max_version FROM model_versions WHERE model_id = ?", (model_id,))
        current = (row or {}).get("max_version")
        return int(current) + 1 if current is not None else 1

    def find_by_idempotency(
        self,
        project_id: str,
        idempotency_key: str,
    ) -> Dict[str, Any] | None:
        if not project_id or not idempotency_key:
            return None
        return self._one(
            """
            SELECT * FROM model_versions
            WHERE project_id = ? AND idempotency_key = ?
            """,
            (project_id, idempotency_key),
        )

    def insert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """INSERT only -- a ModelVersion's content is immutable once created.
        There is deliberately no upsert/update path for the content columns
        here (see archive() below for the one legitimate later mutation)."""
        with self.database.transaction() as connection:
            _insert_version_row(connection, record)
        return self.get(record["model_version_id"]) or {}

    def publish_finalized(
        self,
        model_record: Dict[str, Any],
        version_record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Atomically insert the immutable version and advance its champion.

        Artifact staging/finalization is owned by the registry service. This
        transaction is deliberately the single relational commit point. A
        caller compensates the finalized file if this method raises.
        """
        if (
            version_record.get("publication_status") != "finalized"
            or version_record.get("lineage_status") != "verified"
            or not version_record.get("checksum")
            or not version_record.get("artifact_reference")
            or not version_record.get("artifact_size_bytes")
            or not version_record.get("idempotency_key")
            or not version_record.get("publication_fingerprint")
            or not version_record.get("candidate_id")
            or not version_record.get("evaluation_package_id")
            or not version_record.get("candidate_decision_id")
            or version_record.get("candidate_decision_status") != "locked"
            or not version_record.get("candidate_decision_contract_hash")
            or not version_record.get("selection_metric_name")
            or version_record.get("selection_metric_value") is None
            or version_record.get("selection_metric_source") in {None, "", "final_holdout"}
            or not version_record.get("selection_metric_created_at")
            or not version_record.get("out_of_fold_prediction_artifact_id")
            or version_record.get("selection_integrity_status") != "verified"
            or not version_record.get("selection_locked_at")
            or not version_record.get("holdout_exposure_id")
            or not version_record.get("final_holdout_partition_id")
            or version_record.get("final_holdout_status") != "evaluated"
            or version_record.get("holdout_isolation_status") != "verified"
            or not version_record.get("threshold_locked_at")
            or not version_record.get("threshold_source")
            or (
                version_record.get("threshold_source") != "not_applicable"
                and version_record.get("locked_threshold") is None
            )
            or not version_record.get("threshold_policy_hash")
            or not version_record.get("evaluation_package_contract_hash")
            or not version_record.get("evaluation_package_content_hash")
            or version_record.get("evaluation_package_integrity_status")
            != "verified"
            or version_record.get("promotion_readiness_status") != "verified"
            or not version_record.get("candidate_contract_hash")
            or not version_record.get("selected_candidate_contract_hash")
            or version_record.get("candidate_contract_hash")
            != version_record.get("selected_candidate_contract_hash")
            or not version_record.get("model_contract_json")
        ):
            raise ValueError(
                "A finalized version requires verified lineage, checksum, and idempotency identity."
            )
        with self.database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _assert_durable_promotion_governance(connection, version_record)
            existing_version = decode_row(
                connection.execute(
                    """
                    SELECT * FROM model_versions
                    WHERE project_id = ? AND idempotency_key = ?
                    """,
                    (
                        version_record["project_id"],
                        version_record["idempotency_key"],
                    ),
                ).fetchone()
            )
            if existing_version:
                if (
                    existing_version.get("publication_fingerprint")
                    != version_record.get("publication_fingerprint")
                ):
                    raise ModelRegistryConflictError(
                        "The idempotency key was already used for different model content."
                    )
                existing_model = decode_row(
                    connection.execute(
                        "SELECT * FROM models WHERE model_id = ?",
                        (existing_version["model_id"],),
                    ).fetchone()
                )
                if not existing_model:
                    raise ModelRegistryConflictError(
                        "The idempotent model version has no durable parent model."
                    )
                if existing_model.get("project_id") != existing_version.get(
                    "project_id"
                ):
                    raise ModelRegistryConflictError(
                        "The idempotent model version has no exact project-bound parent."
                    )
                return {
                    "model": existing_model,
                    "model_version": existing_version,
                    "idempotent_replay": True,
                }

            model = decode_row(
                connection.execute(
                    """
                    SELECT * FROM models
                    WHERE project_id = ? AND name = ? AND archived = 0
                    ORDER BY created_at ASC, model_id ASC
                    LIMIT 1
                    """,
                    (model_record["project_id"], model_record["name"]),
                ).fetchone()
            )
            if model is None:
                _insert_model_row(connection, model_record)
                model = decode_row(
                    connection.execute(
                        "SELECT * FROM models WHERE model_id = ?",
                        (model_record["model_id"],),
                    ).fetchone()
                )
            if not model:
                raise RuntimeError("The durable parent model could not be created.")
            if model.get("project_id") != version_record.get("project_id"):
                raise ModelRegistryConflictError(
                    "The parent model belongs to a different project."
                )

            max_row = connection.execute(
                """
                SELECT MAX(version_number) AS max_version
                FROM model_versions WHERE model_id = ?
                """,
                (model["model_id"],),
            ).fetchone()
            version_number = int(max_row["max_version"] or 0) + 1
            durable_version = {
                **version_record,
                "model_id": model["model_id"],
                "version_number": version_number,
                "previous_champion_version_id": model.get("current_version_id"),
            }
            _insert_version_row(connection, durable_version)

            generation = int(model.get("current_version_generation") or 0)
            timestamp = str(version_record.get("finalized_at") or now_iso())
            cursor = connection.execute(
                """
                UPDATE models
                SET current_version_id = ?,
                    current_version_generation = current_version_generation + 1,
                    champion_updated_at = ?, champion_updated_by = ?, updated_at = ?
                WHERE model_id = ? AND current_version_generation = ? AND archived = 0
                """,
                (
                    version_record["model_version_id"],
                    timestamp,
                    version_record.get("created_by"),
                    timestamp,
                    model["model_id"],
                    generation,
                ),
            )
            if cursor.rowcount != 1:
                raise ModelRegistryConflictError(
                    "The champion pointer changed during model publication."
                )
            saved_model = decode_row(
                connection.execute(
                    "SELECT * FROM models WHERE model_id = ?",
                    (model["model_id"],),
                ).fetchone()
            )
            saved_version = decode_row(
                connection.execute(
                    "SELECT * FROM model_versions WHERE model_version_id = ?",
                    (version_record["model_version_id"],),
                ).fetchone()
            )
            if not saved_model or not saved_version:
                raise RuntimeError("The model publication did not finalize atomically.")
            return {
                "model": saved_model,
                "model_version": saved_version,
                "idempotent_replay": False,
            }

    def quarantine(
        self,
        model_version_id: str,
        reason: str,
    ) -> Dict[str, Any] | None:
        timestamp = now_iso()
        with self.database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = decode_row(
                connection.execute(
                    "SELECT * FROM model_versions WHERE model_version_id = ?",
                    (model_version_id,),
                ).fetchone()
            )
            if not row:
                return None
            connection.execute(
                """
                UPDATE model_versions
                SET publication_status = 'quarantined',
                    lineage_status = CASE
                      WHEN lineage_status = 'verified' THEN lineage_status
                      ELSE 'legacy_unresolved'
                    END,
                    quarantine_reason = ?, quarantined_at = COALESCE(quarantined_at, ?)
                WHERE model_version_id = ?
                """,
                (
                    str(reason or "Registry recovery validation failed."),
                    timestamp,
                    model_version_id,
                ),
            )
            connection.execute(
                """
                UPDATE models
                SET current_version_id = NULL,
                    current_version_generation = current_version_generation + 1,
                    champion_updated_at = ?, champion_updated_by = ?, updated_at = ?
                WHERE model_id = ? AND current_version_id = ?
                """,
                (
                    timestamp,
                    "registry-recovery",
                    timestamp,
                    row["model_id"],
                    model_version_id,
                ),
            )
            return decode_row(
                connection.execute(
                    "SELECT * FROM model_versions WHERE model_version_id = ?",
                    (model_version_id,),
                ).fetchone()
            )

    def set_governance_status(
        self, model_version_id: str, *,
        approval_status: Optional[str] = None, validation_status: Optional[str] = None, documentation_status: Optional[str] = None,
    ) -> Dict[str, Any] | None:
        """The one legitimate class of post-creation mutation: workflow status
        transitions (approval/validation/documentation progress), never the
        model's substantive content (metrics/hyperparameters/artifact/checksum)."""
        current = self.get(model_version_id)
        if current is None:
            return None
        self._write(
            "UPDATE model_versions SET approval_status = ?, validation_status = ?, documentation_status = ? WHERE model_version_id = ?",
            (
                approval_status or current.get("approval_status") or "unreviewed",
                validation_status or current.get("validation_status") or "not_validated",
                documentation_status or current.get("documentation_status") or "not_documented",
                model_version_id,
            ),
        )
        return self.get(model_version_id)

    def archive(self, model_version_id: str) -> Dict[str, Any] | None:
        self._write("UPDATE model_versions SET archived_at = ? WHERE model_version_id = ?", (now_iso(), model_version_id))
        return self.get(model_version_id)

    def archive_and_clear_champion(
        self,
        model_version_id: str,
        *,
        actor_user_id: str,
    ) -> Dict[str, Any] | None:
        with self.database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = decode_row(
                connection.execute(
                    "SELECT * FROM model_versions WHERE model_version_id = ?",
                    (model_version_id,),
                ).fetchone()
            )
            if not row:
                return None
            timestamp = now_iso()
            connection.execute(
                """
                UPDATE model_versions
                SET archived_at = COALESCE(archived_at, ?)
                WHERE model_version_id = ?
                """,
                (timestamp, model_version_id),
            )
            connection.execute(
                """
                UPDATE models
                SET current_version_id = NULL,
                    current_version_generation = current_version_generation + 1,
                    champion_updated_at = ?, champion_updated_by = ?, updated_at = ?
                WHERE model_id = ? AND current_version_id = ?
                """,
                (
                    timestamp,
                    actor_user_id,
                    timestamp,
                    row["model_id"],
                    model_version_id,
                ),
            )
            return decode_row(
                connection.execute(
                    "SELECT * FROM model_versions WHERE model_version_id = ?",
                    (model_version_id,),
                ).fetchone()
            )

    def archive_for_project(self, project_id: str) -> int:
        rows = self._many("SELECT model_version_id FROM model_versions WHERE project_id = ? AND archived_at IS NULL", (project_id,))
        timestamp = now_iso()
        for row in rows:
            self._write("UPDATE model_versions SET archived_at = ? WHERE model_version_id = ?", (timestamp, row["model_version_id"]))
        return len(rows)
