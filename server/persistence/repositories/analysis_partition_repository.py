from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Dict, Iterable, List, Mapping

from ..db import decode_row, json_dumps, now_iso
from .base_repository import BaseRepository


class AnalysisPartitionConflictError(RuntimeError):
    """A new partition conflicts with the project's current authority."""

    def __init__(
        self,
        message: str,
        *,
        current: Mapping[str, Any] | None = None,
        impacts: List[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.current = dict(current or {})
        self.impacts = list(impacts or [])


class AnalysisPartitionStateError(RuntimeError):
    """The durable Analysis Partition lifecycle is internally inconsistent."""


_INSERT_COLUMNS = (
    "analysis_partition_id",
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "target_contract_id",
    "target_column",
    "positive_value_json",
    "negative_value_json",
    "predictor_authorization_id",
    "problem_type",
    "partition_method",
    "selection_rationale",
    "preview_fingerprint",
    "sufficiency_json",
    "development_partition_id",
    "sealed_holdout_partition_id",
    "development_share",
    "holdout_share",
    "random_seed",
    "stratification_policy",
    "stratification_field",
    "population_count",
    "development_count",
    "holdout_count",
    "event_counts_json",
    "row_assignments_json",
    "assignment_hash",
    "population_fingerprint",
    "artifact_hash",
    "status",
    "revision",
    "final_holdout_status",
    "holdout_isolation_status",
    "evidence_status",
    "evidence_ref",
    "mdd_status",
    "mdd_ref",
    "created_by",
    "created_at",
    "sealed_at",
    "updated_at",
    "stale_reason",
    "superseded_by_partition_id",
)


def _decoded(row: sqlite3.Row | None) -> Dict[str, Any] | None:
    return decode_row(row)


class AnalysisPartitionRepository(BaseRepository):
    """Durable authority for pre-EDA development/holdout membership.

    A project may have one ``current`` partition.  Contract-identical ordinary
    confirmations reuse that row.  Every explicit reset, including a reset to
    the same deterministic policy, retains the prior row as ``superseded`` and
    inserts a new monotonic revision in the same ``BEGIN IMMEDIATE``
    transaction.
    """

    def get(self, analysis_partition_id: str) -> Dict[str, Any] | None:
        return self._one(
            "SELECT * FROM analysis_partitions WHERE analysis_partition_id = ?",
            (analysis_partition_id,),
        )

    def get_current(self, project_id: str) -> Dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM analysis_partitions
            WHERE project_id = ? AND status = 'current'
            """,
            (project_id,),
        )

    def get_current_exact(
        self,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> Dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM analysis_partitions
            WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
              AND status = 'current'
            """,
            (project_id, dataset_id, dataset_version_id),
        )

    def history(self, project_id: str) -> List[Dict[str, Any]]:
        """Audit-only revision history; never used to resolve current state."""

        return self._many(
            """
            SELECT * FROM analysis_partitions
            WHERE project_id = ?
            ORDER BY revision ASC
            """,
            (project_id,),
        )

    @staticmethod
    def _inventory_item(
        *,
        artifact_type: str,
        artifact_id: Any,
        source_authority: str,
        prior_status: Any = None,
        invalidation_status: str = "invalidated",
        metadata: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return {
            "artifact_type": str(artifact_type),
            "artifact_id": str(artifact_id),
            "source_authority": str(source_authority),
            "prior_status": (
                str(prior_status) if prior_status not in (None, "") else None
            ),
            "invalidation_status": str(invalidation_status),
            "metadata": dict(metadata or {}),
        }

    @staticmethod
    def _dedupe_inventory(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        unique: Dict[tuple[str, str, str], Dict[str, Any]] = {}
        for raw in items:
            item = dict(raw)
            key = (
                str(item.get("artifact_type") or "").strip(),
                str(item.get("artifact_id") or "").strip(),
                str(item.get("source_authority") or "").strip(),
            )
            if not all(key):
                continue
            item["artifact_type"], item["artifact_id"], item["source_authority"] = key
            item["invalidation_status"] = str(
                item.get("invalidation_status") or "invalidated"
            )
            item["metadata"] = (
                dict(item.get("metadata"))
                if isinstance(item.get("metadata"), Mapping)
                else {}
            )
            unique[key] = item
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    @classmethod
    def _inventory_downstream(
        cls,
        connection: sqlite3.Connection,
        current: Mapping[str, Any],
        external_inventory: Iterable[Mapping[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        """Inventory exact current derivatives without reading holdout values.

        Immutable candidate/evaluation records are inventoried into the reset
        overlay rather than rewritten. Mutable authorities are subsequently
        marked stale in the same transaction as the partition transition.
        """

        project_id = str(current.get("project_id") or "")
        dataset_id = str(current.get("dataset_id") or "")
        dataset_version_id = str(current.get("dataset_version_id") or "")
        partition_id = str(current.get("analysis_partition_id") or "")
        holdout_id = str(current.get("sealed_holdout_partition_id") or "")
        items: List[Dict[str, Any]] = [dict(item) for item in external_inventory or []]

        def rows(query: str, params: tuple[Any, ...]) -> List[sqlite3.Row]:
            return list(connection.execute(query, params).fetchall())

        if cls._table_exists(connection, "evidence_artifacts"):
            for row in rows(
                """
                SELECT evidence_id, step_id, artifact_type, status, source_ref,
                       payload_json
                FROM evidence_artifacts
                WHERE project_id = ?
                  AND lower(status) NOT IN ('stale', 'invalidated', 'superseded', 'archived')
                """,
                (project_id,),
            ):
                payload_text = str(row["payload_json"] or "")
                step = str(row["step_id"] or "").strip().lower()
                artifact_type = str(row["artifact_type"] or "").strip().lower()
                source_ref = str(row["source_ref"] or "")
                is_partition_evidence = (
                    source_ref == partition_id
                    or (
                        artifact_type == "analysis_partition"
                        and partition_id in payload_text
                    )
                    or (step == "step01" and partition_id in payload_text)
                )
                is_downstream = (
                    partition_id in payload_text
                    or holdout_id in payload_text
                    or step in {
                        "step02", "step03", "step04", "step05", "step06",
                        "step07", "step08", "step09", "step10", "step11",
                        "step12", "step13", "eda", "outliers", "missing_values",
                        "feature_engineering", "validation_design", "model_training",
                        "evaluation", "interpretation", "scoring",
                    }
                )
                if is_partition_evidence:
                    items.append(
                        cls._inventory_item(
                            artifact_type="analysis_partition_evidence",
                            artifact_id=row["evidence_id"],
                            source_authority="evidence_artifacts",
                            prior_status=row["status"],
                            invalidation_status="preserved_history",
                            metadata={"step_id": step, "artifact_type": artifact_type},
                        )
                    )
                elif is_downstream:
                    items.append(
                        cls._inventory_item(
                            artifact_type="evidence",
                            artifact_id=row["evidence_id"],
                            source_authority="evidence_artifacts",
                            prior_status=row["status"],
                            metadata={"step_id": step, "artifact_type": artifact_type},
                        )
                    )

        if cls._table_exists(connection, "run_records"):
            for row in rows(
                """
                SELECT run_id, run_type, status, parameters_json, artifacts_json
                FROM run_records
                WHERE project_id = ?
                  AND lower(status) NOT IN ('invalidated', 'cancelled', 'canceled')
                """,
                (project_id,),
            ):
                payload = " ".join(
                    str(row[key] or "") for key in ("parameters_json", "artifacts_json")
                )
                run_type = str(row["run_type"] or "").lower()
                if (
                    partition_id in payload
                    or holdout_id in payload
                    or any(
                        marker in run_type
                        for marker in (
                            "train", "candidate", "evaluation", "interpret",
                            "validation", "model", "scor",
                        )
                    )
                ):
                    items.append(
                        cls._inventory_item(
                            artifact_type="run_record",
                            artifact_id=row["run_id"],
                            source_authority="run_records",
                            prior_status=row["status"],
                            metadata={"run_type": row["run_type"]},
                        )
                    )

        if cls._table_exists(connection, "decision_journal"):
            for row in rows(
                """
                SELECT decision_id, decision_type, status, payload_json
                FROM decision_journal
                WHERE project_id = ?
                  AND lower(status) NOT IN ('stale', 'invalidated', 'superseded', 'archived')
                """,
                (project_id,),
            ):
                payload = str(row["payload_json"] or "")
                decision_type = str(row["decision_type"] or "").lower()
                if (
                    partition_id in payload
                    or holdout_id in payload
                    or any(
                        marker in decision_type
                        for marker in (
                            "eda", "feature", "validation", "candidate",
                            "evaluation", "model", "scor",
                        )
                    )
                ):
                    items.append(
                        cls._inventory_item(
                            artifact_type="decision",
                            artifact_id=row["decision_id"],
                            source_authority="decision_journal",
                            prior_status=row["status"],
                            metadata={"decision_type": row["decision_type"]},
                        )
                    )

        if cls._table_exists(connection, "candidate_selection_decisions"):
            for row in rows(
                """
                SELECT candidate_decision_id, decision_status,
                       training_job_id, training_run_id, candidate_id,
                       validation_design_id, split_id
                FROM candidate_selection_decisions
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                  AND final_holdout_partition_id = ?
                  AND NOT EXISTS (
                    SELECT 1
                    FROM analysis_partition_derivative_invalidations di
                    WHERE di.artifact_type = 'candidate_decision'
                      AND di.artifact_id = candidate_selection_decisions.candidate_decision_id
                      AND di.invalidation_status = 'invalidated'
                  )
                """,
                (project_id, dataset_id, dataset_version_id, holdout_id),
            ):
                items.append(
                    cls._inventory_item(
                        artifact_type="candidate_decision",
                        artifact_id=row["candidate_decision_id"],
                        source_authority="candidate_selection_decisions",
                        prior_status=row["decision_status"],
                        metadata={
                            key: row[key]
                            for key in (
                                "training_job_id", "training_run_id", "candidate_id",
                                "validation_design_id", "split_id",
                            )
                        },
                    )
                )

        if cls._table_exists(connection, "holdout_exposures"):
            for row in rows(
                """
                SELECT holdout_exposure_id, final_holdout_status,
                       candidate_decision_id, candidate_id, split_id
                FROM holdout_exposures
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                  AND final_holdout_partition_id = ?
                  AND final_holdout_status <> 'invalidated'
                """,
                (project_id, dataset_id, dataset_version_id, holdout_id),
            ):
                items.append(
                    cls._inventory_item(
                        artifact_type="holdout_exposure",
                        artifact_id=row["holdout_exposure_id"],
                        source_authority="holdout_exposures",
                        prior_status=row["final_holdout_status"],
                        metadata={
                            "candidate_decision_id": row["candidate_decision_id"],
                            "candidate_id": row["candidate_id"],
                            "split_id": row["split_id"],
                        },
                    )
                )

        if cls._table_exists(connection, "evaluation_packages"):
            for row in rows(
                """
                SELECT evaluation_package_id, package_status,
                       candidate_decision_id, candidate_id, training_run_id, split_id
                FROM evaluation_packages
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                  AND final_holdout_partition_id = ?
                  AND NOT EXISTS (
                    SELECT 1
                    FROM analysis_partition_derivative_invalidations di
                    WHERE di.artifact_type = 'evaluation_package'
                      AND di.artifact_id = evaluation_packages.evaluation_package_id
                      AND di.invalidation_status = 'invalidated'
                  )
                """,
                (project_id, dataset_id, dataset_version_id, holdout_id),
            ):
                items.append(
                    cls._inventory_item(
                        artifact_type="evaluation_package",
                        artifact_id=row["evaluation_package_id"],
                        source_authority="evaluation_packages",
                        prior_status=row["package_status"],
                        metadata={
                            key: row[key]
                            for key in (
                                "candidate_decision_id", "candidate_id",
                                "training_run_id", "split_id",
                            )
                        },
                    )
                )

        affected_model_ids: set[str] = set()
        if cls._table_exists(connection, "model_versions"):
            for row in rows(
                """
                SELECT model_version_id, model_id, publication_status,
                       training_run_id, candidate_id, evaluation_package_id
                FROM model_versions
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                  AND final_holdout_partition_id = ?
                  AND archived_at IS NULL
                """,
                (project_id, dataset_id, dataset_version_id, holdout_id),
            ):
                affected_model_ids.add(str(row["model_id"]))
                items.append(
                    cls._inventory_item(
                        artifact_type="model_version",
                        artifact_id=row["model_version_id"],
                        source_authority="model_versions",
                        prior_status=row["publication_status"],
                        metadata={
                            "model_id": row["model_id"],
                            "training_run_id": row["training_run_id"],
                            "candidate_id": row["candidate_id"],
                            "evaluation_package_id": row["evaluation_package_id"],
                        },
                    )
                )
        if affected_model_ids and cls._table_exists(connection, "models"):
            placeholders = ",".join("?" for _ in affected_model_ids)
            for row in rows(
                f"""
                SELECT model_id, current_version_id, status
                FROM models
                WHERE model_id IN ({placeholders}) AND current_version_id IS NOT NULL
                """,
                tuple(sorted(affected_model_ids)),
            ):
                items.append(
                    cls._inventory_item(
                        artifact_type="model_current_binding",
                        artifact_id=row["model_id"],
                        source_authority="models",
                        prior_status=row["status"],
                        metadata={"current_version_id": row["current_version_id"]},
                    )
                )

        if cls._table_exists(connection, "scoring_runs"):
            for row in rows(
                """
                SELECT scoring_run_id, status, model_version_id, partition
                FROM scoring_runs
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                  AND lower(status) NOT IN ('invalidated', 'archived')
                """,
                (project_id, dataset_id, dataset_version_id),
            ):
                items.append(
                    cls._inventory_item(
                        artifact_type="scoring_run",
                        artifact_id=row["scoring_run_id"],
                        source_authority="scoring_runs",
                        prior_status=row["status"],
                        metadata={
                            "model_version_id": row["model_version_id"],
                            "partition": row["partition"],
                        },
                    )
                )

        if cls._table_exists(connection, "mdd_documents"):
            document_ids = [
                str(row["mdd_document_id"])
                for row in rows(
                    "SELECT mdd_document_id FROM mdd_documents WHERE project_id = ?",
                    (project_id,),
                )
            ]
            if document_ids:
                placeholders = ",".join("?" for _ in document_ids)
                for row in rows(
                    f"""
                    SELECT v.mdd_document_version_id, v.status,
                           s.mdd_section_id, s.section_id, s.status AS section_status,
                           s.metadata_json, l.canonical_version_reference
                    FROM mdd_document_versions v
                    JOIN mdd_sections s
                      ON s.mdd_document_version_id = v.mdd_document_version_id
                    LEFT JOIN mdd_evidence_links l
                      ON l.mdd_section_id = s.mdd_section_id
                    WHERE v.mdd_document_id IN ({placeholders})
                      AND lower(s.status) NOT IN ('stale', 'invalidated', 'superseded', 'archived')
                    """,
                    tuple(document_ids),
                ):
                    metadata_text = str(row["metadata_json"] or "")
                    try:
                        metadata = json.loads(metadata_text) if metadata_text else {}
                    except (TypeError, ValueError, json.JSONDecodeError):
                        metadata = {}
                    section_name = str(row["section_id"] or "").lower()
                    is_partition_owned = (
                        section_name in {
                            "analysis_partition",
                            "data.analysis_partition",
                        }
                        or section_name.endswith(".analysis_partition")
                        or str(metadata.get("owner_step") or "").lower() == "step01"
                    )
                    if (
                        is_partition_owned
                        and str(row["canonical_version_reference"] or "")
                        != partition_id
                    ):
                        # A prior partition's MDD remains immutable history; it
                        # is neither current downstream state nor part of this
                        # reset's exact affected inventory.
                        continue
                    items.append(
                        cls._inventory_item(
                            artifact_type=(
                                "analysis_partition_mdd_section"
                                if is_partition_owned
                                else "mdd_section"
                            ),
                            artifact_id=row["mdd_section_id"],
                            source_authority="mdd_sections",
                            prior_status=row["section_status"],
                            invalidation_status=(
                                "preserved_history" if is_partition_owned else "invalidated"
                            ),
                            metadata={
                                "mdd_document_version_id": row["mdd_document_version_id"],
                                "document_version_status": row["status"],
                                "section_id": row["section_id"],
                            },
                        )
                    )

        return cls._dedupe_inventory(items)

    def inventory_downstream(
        self,
        current: Mapping[str, Any],
        external_inventory: Iterable[Mapping[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        with self.database.connection() as connection:
            return self._inventory_downstream(
                connection, current, external_inventory=external_inventory
            )

    @staticmethod
    def build_mdd_content(
        record: Mapping[str, Any],
        evidence_ref: str,
        evidence_payload: Mapping[str, Any] | None,
        *,
        include_target_distribution: bool,
    ) -> Dict[str, Any]:
        """Build the exact partition-owned MDD block without loading a dataset.

        Documentation recovery deliberately uses the target-neutral marker.  An
        original creation block can still be verified from the immutable
        decision evidence already stored beside the partition; no row-level
        holdout target is reopened or recalculated.
        """

        payload = dict(evidence_payload or {})
        preview = (
            dict(payload.get("partition_preview") or {})
            if isinstance(payload.get("partition_preview"), Mapping)
            else {}
        )
        if not include_target_distribution:
            distribution_or_coverage: Any = {
                "status": "retained_in_original_partition_decision_evidence",
                "final_holdout_accessed_during_documentation_retry": False,
            }
        elif str(record.get("problem_type") or "") == "classification":
            # Creation documentation is reproduced only from the durable
            # decision-evidence preview. Recovery never falls back to the
            # partition's stored holdout target aggregates.
            distribution_or_coverage = preview.get("class_counts")
        else:
            distribution_or_coverage = {
                "full_target_summary": preview.get("full_target_summary"),
                "development_target_summary": preview.get(
                    "development_target_summary"
                ),
                "holdout_target_summary": preview.get("holdout_target_summary"),
                "target_band_coverage": preview.get("target_band_coverage"),
                "extreme_value_coverage": preview.get("extreme_value_coverage"),
            }
        return {
            "eligible_population": record.get("population_count"),
            "development_holdout_ratio": {
                "development_share": record.get("development_share"),
                "holdout_share": record.get("holdout_share"),
            },
            "development_count": record.get("development_count"),
            "holdout_count": record.get("holdout_count"),
            "partition_method": record.get("partition_method"),
            "random_seed": record.get("random_seed"),
            "stratification": {
                "policy": record.get("stratification_policy"),
                "field": record.get("stratification_field"),
            },
            "target_distribution_or_coverage": distribution_or_coverage,
            "selection_rationale": record.get("selection_rationale"),
            "analysis_partition_id": record.get("analysis_partition_id"),
            "revision": record.get("revision"),
            "sealed_holdout_status": record.get("final_holdout_status"),
            "actor": record.get("created_by"),
            "timestamp": record.get("created_at"),
            "evidence_references": [evidence_ref] if evidence_ref else [],
        }

    @staticmethod
    def _json_object(value: Any) -> Dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        try:
            decoded = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}

    def documentation_readiness(
        self, record: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Verify both durable documentation references for one exact row."""

        partition_id = str(record.get("analysis_partition_id") or "")
        evidence_ref = str(record.get("evidence_ref") or "")
        mdd_ref = str(record.get("mdd_ref") or "")
        evidence_ready = False
        mdd_ready = False
        mdd_section_ready = False
        mdd_content_ready = False
        mdd_evidence_link_ready = False
        with self.database.connection() as connection:
            evidence_payload: Dict[str, Any] = {}
            if evidence_ref:
                evidence = connection.execute(
                    """
                    SELECT evidence_id, project_id, source_ref, artifact_hash,
                           status, payload_json
                    FROM evidence_artifacts WHERE evidence_id = ?
                    """,
                    (evidence_ref,),
                ).fetchone()
                evidence_payload = self._json_object(
                    evidence["payload_json"] if evidence is not None else None
                )
                evidence_ready = bool(
                    evidence is not None
                    and str(evidence["project_id"] or "")
                    == str(record.get("project_id") or "")
                    and str(evidence["source_ref"] or "") == partition_id
                    and str(evidence["artifact_hash"] or "")
                    == str(record.get("artifact_hash") or "")
                    and str(evidence["status"] or "").lower()
                    in {"approved", "recorded", "current"}
                    and str(evidence_payload.get("analysis_partition_id") or "")
                    == partition_id
                    and int(evidence_payload.get("revision") or 0)
                    == int(record.get("revision") or 0)
                    and str(evidence_payload.get("artifact_hash") or "")
                    == str(record.get("artifact_hash") or "")
                    and str(evidence_payload.get("assignment_hash") or "")
                    == str(record.get("assignment_hash") or "")
                )
            if mdd_ref:
                section = connection.execute(
                    """
                    SELECT s.mdd_section_id, s.mdd_document_version_id,
                           s.section_id, s.section_number, s.title,
                           s.status, s.metadata_json,
                           v.metadata_json AS version_metadata_json,
                           d.project_id
                    FROM mdd_sections s
                    JOIN mdd_document_versions v
                      ON v.mdd_document_version_id = s.mdd_document_version_id
                    JOIN mdd_documents d
                      ON d.mdd_document_id = v.mdd_document_id
                    WHERE s.mdd_section_id = ?
                    """,
                    (mdd_ref,),
                ).fetchone()
                section_metadata = self._json_object(
                    section["metadata_json"] if section is not None else None
                )
                version_metadata = self._json_object(
                    section["version_metadata_json"]
                    if section is not None
                    else None
                )
                mdd_section_ready = bool(
                    section is not None
                    and mdd_ref == f"mdd-section-{partition_id}"
                    and str(section["mdd_document_version_id"] or "")
                    == f"mdd-version-{partition_id}"
                    and str(section["section_id"] or "")
                    == "data.analysis_partition"
                    and str(section["section_number"] or "") == "3.2"
                    and str(section["title"] or "")
                    == "Development and Final Evaluation Populations"
                    and str(section["status"] or "").lower()
                    not in {"stale", "invalidated", "superseded", "archived"}
                    and str(section["project_id"] or "")
                    == str(record.get("project_id") or "")
                    and str(section_metadata.get("owner_step") or "") == "step01"
                    and str(version_metadata.get("analysis_partition_id") or "")
                    == partition_id
                    and str(version_metadata.get("evidence_ref") or "")
                    == evidence_ref
                )

                block = connection.execute(
                    """
                    SELECT block_id, mdd_section_id, block_type, title,
                           content_json, source_type, source_reference_json,
                           generated_indicator, metadata_json
                    FROM mdd_content_blocks
                    WHERE block_id = ? AND mdd_section_id = ?
                    """,
                    (f"mdd-block-{partition_id}", mdd_ref),
                ).fetchone()
                actual_content = self._json_object(
                    block["content_json"] if block is not None else None
                )
                source_reference = self._json_object(
                    block["source_reference_json"] if block is not None else None
                )
                block_metadata = self._json_object(
                    block["metadata_json"] if block is not None else None
                )
                expected_creation_content = self.build_mdd_content(
                    record,
                    evidence_ref,
                    evidence_payload,
                    include_target_distribution=True,
                )
                expected_retry_content = self.build_mdd_content(
                    record,
                    evidence_ref,
                    evidence_payload,
                    include_target_distribution=False,
                )
                mdd_content_ready = bool(
                    block is not None
                    and str(block["block_type"] or "") == "structured_data"
                    and str(block["title"] or "") == "Sealed Analysis Partition"
                    and str(block["source_type"] or "") == "evidence"
                    and str(block["generated_indicator"] or "")
                    == "system_generated"
                    and source_reference
                    == {
                        "analysis_partition_id": partition_id,
                        "evidence_id": evidence_ref,
                    }
                    and str(block_metadata.get("owner_step") or "") == "step01"
                    and json_dumps(actual_content, {})
                    in {
                        json_dumps(expected_creation_content, {}),
                        json_dumps(expected_retry_content, {}),
                    }
                )

                link = connection.execute(
                    """
                    SELECT mdd_evidence_link_id, mdd_section_id,
                           evidence_reference_json,
                           canonical_version_reference, metadata_json
                    FROM mdd_evidence_links
                    WHERE mdd_evidence_link_id = ? AND mdd_section_id = ?
                    """,
                    (f"mdd-evidence-link-{partition_id}", mdd_ref),
                ).fetchone()
                link_reference = self._json_object(
                    link["evidence_reference_json"] if link is not None else None
                )
                link_metadata = self._json_object(
                    link["metadata_json"] if link is not None else None
                )
                mdd_evidence_link_ready = bool(
                    link is not None
                    and str(link["canonical_version_reference"] or "")
                    == partition_id
                    and link_reference == {"evidence_id": evidence_ref}
                    and str(link_metadata.get("owner_step") or "") == "step01"
                    and evidence_ready
                )
                mdd_ready = bool(
                    mdd_section_ready
                    and mdd_content_ready
                    and mdd_evidence_link_ready
                )
        flags_ready = (
            str(record.get("evidence_status") or "").lower() == "recorded"
            and str(record.get("mdd_status") or "").lower() == "recorded"
        )
        return {
            "ready": bool(flags_ready and evidence_ready and mdd_ready),
            "flags_ready": bool(flags_ready),
            "evidence_ready": bool(evidence_ready),
            "mdd_ready": bool(mdd_ready),
            "mdd_section_ready": bool(mdd_section_ready),
            "mdd_content_ready": bool(mdd_content_ready),
            "mdd_evidence_link_ready": bool(mdd_evidence_link_ready),
            "evidence_ref": evidence_ref or None,
            "mdd_ref": mdd_ref or None,
        }

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        record: Mapping[str, Any],
        *,
        event_type: str,
        actor_user_id: str,
        reason: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO analysis_partition_events (
              analysis_partition_event_id, analysis_partition_id, project_id,
              dataset_id, dataset_version_id, revision, event_type,
              event_status, actor_user_id, reason, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"analysis-partition-event-{uuid.uuid4().hex}",
                record["analysis_partition_id"],
                record["project_id"],
                record["dataset_id"],
                record["dataset_version_id"],
                int(record["revision"]),
                event_type,
                "recorded",
                actor_user_id,
                reason or None,
                now_iso(),
                json_dumps(dict(metadata or {}), {}),
            ),
        )

    @staticmethod
    def _insert(connection: sqlite3.Connection, record: Mapping[str, Any]) -> None:
        placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
        columns = ", ".join(_INSERT_COLUMNS)
        connection.execute(
            f"INSERT INTO analysis_partitions ({columns}) VALUES ({placeholders})",
            tuple(record.get(column) for column in _INSERT_COLUMNS),
        )

    @staticmethod
    def _row(
        connection: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...],
    ) -> Dict[str, Any] | None:
        return _decoded(connection.execute(query, params).fetchone())

    @staticmethod
    def _next_revision(connection: sqlite3.Connection, project_id: str) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(revision), 0) AS revision FROM analysis_partitions WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row["revision"] or 0) + 1

    @staticmethod
    def _ids(record: Mapping[str, Any], revision: int) -> Dict[str, str]:
        digest = str(record.get("artifact_hash") or "").strip()
        if len(digest) < 20:
            raise AnalysisPartitionStateError(
                "An Analysis Partition requires a canonical artifact hash before persistence."
            )
        stem = digest[:20]
        return {
            "analysis_partition_id": f"analysis-partition-{stem}-r{revision}",
            "development_partition_id": f"development-{stem}-r{revision}",
            "sealed_holdout_partition_id": f"sealed-holdout-{stem}-r{revision}",
        }

    @classmethod
    def _apply_derivative_invalidations(
        cls,
        connection: sqlite3.Connection,
        inventory: List[Dict[str, Any]],
        *,
        timestamp: str,
        reason: str,
        actor_user_id: str,
    ) -> Dict[str, int]:
        """Mark mutable authorities stale; immutable records use the ledger."""

        by_source: Dict[str, List[str]] = {}
        for item in inventory:
            if item.get("invalidation_status") != "invalidated":
                continue
            by_source.setdefault(str(item["source_authority"]), []).append(
                str(item["artifact_id"])
            )

        counts: Dict[str, int] = {}

        def update_many(source: str, query: str, params_for_id) -> None:
            ids = sorted(set(by_source.get(source, [])))
            changed = 0
            for artifact_id in ids:
                cursor = connection.execute(query, params_for_id(artifact_id))
                changed += max(int(cursor.rowcount or 0), 0)
            counts[source] = changed

        update_many(
            "evidence_artifacts",
            "UPDATE evidence_artifacts SET status = 'stale' WHERE evidence_id = ?",
            lambda artifact_id: (artifact_id,),
        )
        update_many(
            "run_records",
            """
            UPDATE run_records
            SET status = 'invalidated', completed_at = COALESCE(completed_at, ?),
                error_json = ?
            WHERE run_id = ?
            """,
            lambda artifact_id: (
                timestamp,
                json_dumps(
                    {
                        "code": "analysis_partition_reset",
                        "reason": reason,
                        "invalidated_by": actor_user_id,
                    },
                    {},
                ),
                artifact_id,
            ),
        )
        update_many(
            "decision_journal",
            "UPDATE decision_journal SET status = 'stale', updated_at = ? WHERE decision_id = ?",
            lambda artifact_id: (timestamp, artifact_id),
        )
        update_many(
            "holdout_exposures",
            """
            UPDATE holdout_exposures
            SET final_holdout_status = 'invalidated', invalidated_at = ?,
                invalidated_by = ?, invalidation_reason = ?, updated_at = ?
            WHERE holdout_exposure_id = ? AND final_holdout_status <> 'invalidated'
            """,
            lambda artifact_id: (
                timestamp,
                actor_user_id,
                reason,
                timestamp,
                artifact_id,
            ),
        )
        update_many(
            "model_versions",
            """
            UPDATE model_versions
            SET approval_status = 'invalidated', validation_status = 'invalidated',
                documentation_status = 'stale', archived_at = COALESCE(archived_at, ?),
                publication_status = 'invalidated', lineage_status = 'invalidated',
                quarantine_reason = ?, quarantined_at = COALESCE(quarantined_at, ?),
                final_holdout_status = 'invalidated', holdout_isolation_status = 'invalid',
                evaluation_package_integrity_status = 'invalidated',
                promotion_readiness_status = 'invalidated'
            WHERE model_version_id = ?
            """,
            lambda artifact_id: (timestamp, reason, timestamp, artifact_id),
        )
        update_many(
            "models",
            """
            UPDATE models
            SET current_version_id = NULL,
                current_version_generation = current_version_generation + 1,
                updated_at = ?, champion_updated_at = ?, champion_updated_by = ?
            WHERE model_id = ? AND current_version_id IS NOT NULL
            """,
            lambda artifact_id: (
                timestamp,
                timestamp,
                actor_user_id,
                artifact_id,
            ),
        )
        update_many(
            "scoring_runs",
            """
            UPDATE scoring_runs
            SET status = 'invalidated', archived_at = COALESCE(archived_at, ?),
                error_message = ?, updated_at = ?
            WHERE scoring_run_id = ?
            """,
            lambda artifact_id: (timestamp, reason, timestamp, artifact_id),
        )
        update_many(
            "mdd_sections",
            "UPDATE mdd_sections SET status = 'stale' WHERE mdd_section_id = ?",
            lambda artifact_id: (artifact_id,),
        )

        affected_versions = sorted(
            {
                str((item.get("metadata") or {}).get("mdd_document_version_id") or "")
                for item in inventory
                if item.get("source_authority") == "mdd_sections"
                and item.get("invalidation_status") == "invalidated"
            }
            - {""}
        )
        for version_id in affected_versions:
            connection.execute(
                "UPDATE mdd_document_versions SET status = 'stale' WHERE mdd_document_version_id = ?",
                (version_id,),
            )
            connection.execute(
                """
                UPDATE mdd_documents
                SET current_validated_version_id = NULL, updated_at = ?
                WHERE current_validated_version_id = ?
                """,
                (timestamp, version_id),
            )
        counts["mdd_document_versions"] = len(affected_versions)
        return counts

    @classmethod
    def _record_reset_operation(
        cls,
        connection: sqlite3.Connection,
        *,
        current: Mapping[str, Any],
        operation_kind: str,
        replacement: Mapping[str, Any] | None,
        inventory: List[Dict[str, Any]],
        actor_user_id: str,
        reason: str,
        timestamp: str,
    ) -> Dict[str, Any]:
        operation_id = f"analysis-partition-reset-{uuid.uuid4().hex}"
        counts = cls._apply_derivative_invalidations(
            connection,
            inventory,
            timestamp=timestamp,
            reason=reason,
            actor_user_id=actor_user_id,
        )
        receipt = {
            "inventory_count": len(inventory),
            "invalidated_count": sum(
                1
                for item in inventory
                if item.get("invalidation_status") == "invalidated"
            ),
            "preserved_history_count": sum(
                1
                for item in inventory
                if item.get("invalidation_status") == "preserved_history"
            ),
            "native_updates": counts,
            "atomic_sqlite_transaction": True,
            "external_state_compensation_required": any(
                str(item.get("source_authority") or "").startswith(
                    ("runtime", "file:")
                )
                for item in inventory
            ),
        }
        connection.execute(
            """
            INSERT INTO analysis_partition_reset_operations (
              reset_operation_id, project_id, dataset_id, dataset_version_id,
              prior_analysis_partition_id, prior_revision,
              replacement_analysis_partition_id, replacement_revision,
              operation_kind, operation_status, actor_user_id, rationale,
              inventory_json, invalidation_receipt_json, created_at, committed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'committed', ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                current["project_id"],
                current["dataset_id"],
                current["dataset_version_id"],
                current["analysis_partition_id"],
                int(current["revision"]),
                (replacement or {}).get("analysis_partition_id"),
                (replacement or {}).get("revision"),
                operation_kind,
                actor_user_id,
                reason,
                json_dumps(inventory, []),
                json_dumps(receipt, {}),
                timestamp,
                timestamp,
            ),
        )
        for item in inventory:
            connection.execute(
                """
                INSERT INTO analysis_partition_derivative_invalidations (
                  derivative_invalidation_id, reset_operation_id, project_id,
                  dataset_id, dataset_version_id, prior_analysis_partition_id,
                  prior_revision, artifact_type, artifact_id, source_authority,
                  prior_status, invalidation_status, rationale, actor_user_id,
                  invalidated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"analysis-partition-derivative-{uuid.uuid4().hex}",
                    operation_id,
                    current["project_id"],
                    current["dataset_id"],
                    current["dataset_version_id"],
                    current["analysis_partition_id"],
                    int(current["revision"]),
                    item["artifact_type"],
                    item["artifact_id"],
                    item["source_authority"],
                    item.get("prior_status"),
                    item.get("invalidation_status") or "invalidated",
                    reason,
                    actor_user_id,
                    timestamp,
                    json_dumps(item.get("metadata"), {}),
                ),
            )
        recorded = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM analysis_partition_derivative_invalidations
            WHERE reset_operation_id = ?
            """,
            (operation_id,),
        ).fetchone()
        if int(recorded["count"] or 0) != len(inventory):
            raise AnalysisPartitionStateError(
                "The exact derivative invalidation inventory failed durable read-back verification."
            )
        return {
            "reset_operation_id": operation_id,
            "operation_kind": operation_kind,
            "inventory": inventory,
            "receipt": receipt,
        }

    def create_or_reuse(
        self,
        record: Mapping[str, Any],
        *,
        actor_user_id: str,
        reset_existing: bool = False,
        reset_reason: str = "",
        impacts: List[str] | None = None,
        expected_current_partition_id: str | None = None,
        expected_current_revision: int | None = None,
        external_invalidation_inventory: Iterable[Mapping[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        project_id = str(record.get("project_id") or "").strip()
        artifact_hash = str(record.get("artifact_hash") or "").strip()
        if not project_id or not artifact_hash:
            raise ValueError("project_id and artifact_hash are required.")
        if reset_existing and not str(reset_reason or "").strip():
            raise ValueError("An explicit reset reason is required.")

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._row(
                connection,
                "SELECT * FROM analysis_partitions WHERE project_id = ? AND status = 'current'",
                (project_id,),
            )
            expected_current = str(expected_current_partition_id or "").strip()
            expected_revision = int(expected_current_revision or 0)
            if reset_existing:
                if current is None:
                    raise AnalysisPartitionConflictError(
                        "The requested reset has no current Analysis Partition to replace.",
                        impacts=impacts,
                    )
                if (
                    expected_current
                    and str(current.get("analysis_partition_id") or "")
                    != expected_current
                ):
                    raise AnalysisPartitionConflictError(
                        "The current Analysis Partition changed after reset preflight. "
                        "No replacement partition was created.",
                        current=current,
                        impacts=impacts,
                    )
                if expected_revision and int(current.get("revision") or 0) != expected_revision:
                    raise AnalysisPartitionConflictError(
                        "The current Analysis Partition revision changed after reset preflight. "
                        "No replacement partition was created.",
                        current=current,
                        impacts=impacts,
                    )
            if (
                current
                and not reset_existing
                and str(current.get("artifact_hash") or "") == artifact_hash
            ):
                self._event(
                    connection,
                    current,
                    event_type="reused",
                    actor_user_id=actor_user_id,
                    metadata={"idempotent": True},
                )
                connection.commit()
                return {**current, "reused": True}

            if current and not reset_existing:
                raise AnalysisPartitionConflictError(
                    "The requested Analysis Partition contradicts the current sealed partition. "
                    "Review the invalidation impact and explicitly reset it before changing membership.",
                    current=current,
                    impacts=impacts,
                )

            revision = self._next_revision(connection, project_id)
            identifiers = self._ids(record, revision)
            timestamp = now_iso()
            new_record: Dict[str, Any] = {
                **dict(record),
                **identifiers,
                "positive_value_json": json_dumps(record.get("positive_value_json"), None),
                "negative_value_json": json_dumps(record.get("negative_value_json"), None),
                "sufficiency_json": json_dumps(record.get("sufficiency_json"), {}),
                "event_counts_json": json_dumps(record.get("event_counts_json"), {}),
                "row_assignments_json": json_dumps(record.get("row_assignments_json"), {}),
                "status": "current",
                "revision": revision,
                "final_holdout_status": "sealed",
                "holdout_isolation_status": "verified",
                "evidence_status": str(record.get("evidence_status") or "pending"),
                "evidence_ref": record.get("evidence_ref"),
                "mdd_status": str(record.get("mdd_status") or "pending"),
                "mdd_ref": record.get("mdd_ref"),
                "created_by": actor_user_id,
                "created_at": timestamp,
                "sealed_at": timestamp,
                "updated_at": timestamp,
                "stale_reason": None,
                "superseded_by_partition_id": None,
            }

            if current:
                connection.execute(
                    """
                    UPDATE analysis_partitions
                    SET status = 'superseded', stale_reason = ?,
                        superseded_by_partition_id = ?, updated_at = ?
                    WHERE analysis_partition_id = ? AND status = 'current'
                    """,
                    (
                        str(reset_reason).strip(),
                        identifiers["analysis_partition_id"],
                        timestamp,
                        current["analysis_partition_id"],
                    ),
                )
                self._event(
                    connection,
                    current,
                    event_type="superseded",
                    actor_user_id=actor_user_id,
                    reason=str(reset_reason).strip(),
                    metadata={
                        "superseded_by_partition_id": identifiers[
                            "analysis_partition_id"
                        ],
                        "impacts": list(impacts or []),
                    },
                )

            self._insert(connection, new_record)
            inserted = self._row(
                connection,
                "SELECT * FROM analysis_partitions WHERE analysis_partition_id = ?",
                (identifiers["analysis_partition_id"],),
            )
            if inserted is None:
                raise AnalysisPartitionStateError(
                    "The Analysis Partition was not durably readable after insertion."
                )
            reset_transition: Dict[str, Any] | None = None
            if current:
                inventory = self._inventory_downstream(
                    connection,
                    current,
                    external_inventory=external_invalidation_inventory,
                )
                reset_transition = self._record_reset_operation(
                    connection,
                    current=current,
                    operation_kind="reset_replace",
                    replacement=inserted,
                    inventory=inventory,
                    actor_user_id=actor_user_id,
                    reason=str(reset_reason).strip(),
                    timestamp=timestamp,
                )
            self._event(
                connection,
                inserted,
                event_type="confirmed",
                actor_user_id=actor_user_id,
                reason=str(reset_reason or "").strip(),
                metadata={
                    "reset_existing": bool(current),
                    "impacts": list(impacts or []) if current else [],
                },
            )
            connection.commit()
            return {
                **inserted,
                "reused": False,
                "reset_invalidation": reset_transition,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_documentation_status(
        self,
        analysis_partition_id: str,
        *,
        expected_current: Mapping[str, Any],
        evidence_status: str,
        evidence_ref: str,
        mdd_status: str,
        mdd_ref: str,
    ) -> Dict[str, Any]:
        """Attach documentation only while the exact partition remains current.

        The optimistic predicates live in the database write itself so a reset
        committed by another process cannot attach sidecars to a superseded
        row.  Recorded status is monotonic, which also prevents an evidence
        stage in a concurrent retry from downgrading an already completed MDD.
        """

        expected = dict(expected_current or {})
        expected_partition_id = str(
            expected.get("analysis_partition_id") or ""
        ).strip()
        expected_project_id = str(expected.get("project_id") or "").strip()
        expected_dataset_id = str(expected.get("dataset_id") or "").strip()
        expected_version_id = str(
            expected.get("dataset_version_id") or ""
        ).strip()
        expected_assignment_hash = str(
            expected.get("assignment_hash") or ""
        ).strip()
        expected_artifact_hash = str(
            expected.get("artifact_hash") or ""
        ).strip()
        expected_revision = int(expected.get("revision") or 0)
        if (
            not expected_partition_id
            or expected_partition_id != str(analysis_partition_id or "").strip()
            or not expected_project_id
            or not expected_dataset_id
            or not expected_version_id
            or expected_revision <= 0
            or not expected_assignment_hash
            or not expected_artifact_hash
        ):
            raise AnalysisPartitionStateError(
                "Exact current partition identity is required while documentation status is recorded."
            )

        requested_evidence_status = str(evidence_status or "pending").lower()
        requested_mdd_status = str(mdd_status or "pending").lower()
        requested_evidence_ref = str(evidence_ref or "").strip()
        requested_mdd_ref = str(mdd_ref or "").strip()
        if requested_evidence_status == "recorded" and not requested_evidence_ref:
            raise AnalysisPartitionStateError(
                "Recorded Analysis Partition evidence requires an exact reference."
            )
        if requested_mdd_status == "recorded" and not requested_mdd_ref:
            raise AnalysisPartitionStateError(
                "Recorded Analysis Partition MDD requires an exact reference."
            )

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._row(
                connection,
                """
                SELECT * FROM analysis_partitions
                WHERE project_id = ? AND status = 'current'
                """,
                (expected_project_id,),
            )
            exact_current = bool(
                current is not None
                and str(current.get("analysis_partition_id") or "")
                == expected_partition_id
                and str(current.get("dataset_id") or "") == expected_dataset_id
                and str(current.get("dataset_version_id") or "")
                == expected_version_id
                and int(current.get("revision") or 0) == expected_revision
                and str(current.get("assignment_hash") or "")
                == expected_assignment_hash
                and str(current.get("artifact_hash") or "")
                == expected_artifact_hash
            )
            if not exact_current:
                raise AnalysisPartitionConflictError(
                    "The exact Analysis Partition changed before documentation status could be recorded.",
                    current=current,
                )

            effective_evidence_status = requested_evidence_status
            effective_evidence_ref = requested_evidence_ref
            if str(current.get("evidence_status") or "").lower() == "recorded":
                effective_evidence_status = "recorded"
                effective_evidence_ref = str(
                    current.get("evidence_ref") or requested_evidence_ref
                ).strip()
            effective_mdd_status = requested_mdd_status
            effective_mdd_ref = requested_mdd_ref
            if str(current.get("mdd_status") or "").lower() == "recorded":
                effective_mdd_status = "recorded"
                effective_mdd_ref = str(
                    current.get("mdd_ref") or requested_mdd_ref
                ).strip()

            cursor = connection.execute(
                """
                UPDATE analysis_partitions
                SET evidence_status = ?, evidence_ref = ?,
                    mdd_status = ?, mdd_ref = ?, updated_at = ?
                WHERE analysis_partition_id = ?
                  AND project_id = ?
                  AND dataset_id = ?
                  AND dataset_version_id = ?
                  AND status = 'current'
                  AND revision = ?
                  AND assignment_hash = ?
                  AND artifact_hash = ?
                """,
                (
                    effective_evidence_status,
                    effective_evidence_ref or None,
                    effective_mdd_status,
                    effective_mdd_ref or None,
                    now_iso(),
                    analysis_partition_id,
                    expected_project_id,
                    expected_dataset_id,
                    expected_version_id,
                    expected_revision,
                    expected_assignment_hash,
                    expected_artifact_hash,
                ),
            )
            if cursor.rowcount != 1:
                changed = self._row(
                    connection,
                    """
                    SELECT * FROM analysis_partitions
                    WHERE project_id = ? AND status = 'current'
                    """,
                    (expected_project_id,),
                )
                raise AnalysisPartitionConflictError(
                    "The exact Analysis Partition changed while documentation status was recorded.",
                    current=changed,
                )
            updated = self._row(
                connection,
                """
                SELECT * FROM analysis_partitions
                WHERE analysis_partition_id = ?
                  AND project_id = ?
                  AND dataset_id = ?
                  AND dataset_version_id = ?
                  AND status = 'current'
                  AND revision = ?
                  AND assignment_hash = ?
                  AND artifact_hash = ?
                """,
                (
                    analysis_partition_id,
                    expected_project_id,
                    expected_dataset_id,
                    expected_version_id,
                    expected_revision,
                    expected_assignment_hash,
                    expected_artifact_hash,
                ),
            )
            if updated is None:
                changed = self._row(
                    connection,
                    """
                    SELECT * FROM analysis_partitions
                    WHERE project_id = ? AND status = 'current'
                    """,
                    (expected_project_id,),
                )
                raise AnalysisPartitionConflictError(
                    "The documented Analysis Partition lost current authority before durable read-back.",
                    current=changed,
                )
            if (
                str(updated.get("evidence_status") or "").lower()
                != effective_evidence_status
                or str(updated.get("evidence_ref") or "")
                != effective_evidence_ref
                or str(updated.get("mdd_status") or "").lower()
                != effective_mdd_status
                or str(updated.get("mdd_ref") or "") != effective_mdd_ref
            ):
                raise AnalysisPartitionStateError(
                    "The exact documentation status failed durable read-back verification."
                )
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def invalidate_current(
        self,
        project_id: str,
        *,
        reason: str,
        actor_user_id: str,
        expected_dataset_id: str | None = None,
        expected_dataset_version_id: str | None = None,
        expected_target: str | None = None,
        expected_current_partition_id: str | None = None,
        expected_current_revision: int | None = None,
        external_invalidation_inventory: Iterable[Mapping[str, Any]] | None = None,
    ) -> Dict[str, Any] | None:
        """Mark the exact current row stale without deleting its assignment."""

        if not str(reason or "").strip():
            raise ValueError("An Analysis Partition invalidation reason is required.")
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._row(
                connection,
                "SELECT * FROM analysis_partitions WHERE project_id = ? AND status = 'current'",
                (project_id,),
            )
            if current is None:
                connection.commit()
                return None
            if (
                expected_current_partition_id
                and str(current.get("analysis_partition_id") or "")
                != str(expected_current_partition_id)
            ):
                raise AnalysisPartitionConflictError(
                    "The current Analysis Partition changed before invalidation.",
                    current=current,
                )
            if (
                expected_current_revision is not None
                and int(current.get("revision") or 0)
                != int(expected_current_revision)
            ):
                raise AnalysisPartitionConflictError(
                    "The current Analysis Partition revision changed before invalidation.",
                    current=current,
                )
            expected = {
                "dataset_id": str(expected_dataset_id or "").strip(),
                "dataset_version_id": str(expected_dataset_version_id or "").strip(),
                "target_column": str(expected_target or "").strip(),
            }
            mismatches = [
                key
                for key, value in expected.items()
                if value and str(current.get(key) or "") != value
            ]
            if mismatches:
                raise AnalysisPartitionConflictError(
                    "The current Analysis Partition does not match the exact invalidation scope.",
                    current=current,
                )
            timestamp = now_iso()
            cursor = connection.execute(
                """
                UPDATE analysis_partitions
                SET status = 'stale', stale_reason = ?, updated_at = ?
                WHERE analysis_partition_id = ? AND status = 'current'
                """,
                (str(reason).strip(), timestamp, current["analysis_partition_id"]),
            )
            if cursor.rowcount != 1:
                raise AnalysisPartitionStateError(
                    "The Analysis Partition changed while invalidation was being recorded."
                )
            stale = self._row(
                connection,
                "SELECT * FROM analysis_partitions WHERE analysis_partition_id = ?",
                (current["analysis_partition_id"],),
            )
            if stale is None:
                raise AnalysisPartitionStateError(
                    "The invalidated Analysis Partition is not durably readable."
                )
            inventory = self._inventory_downstream(
                connection,
                current,
                external_inventory=external_invalidation_inventory,
            )
            invalidation = self._record_reset_operation(
                connection,
                current=current,
                operation_kind="invalidate_only",
                replacement=None,
                inventory=inventory,
                actor_user_id=actor_user_id,
                reason=str(reason).strip(),
                timestamp=timestamp,
            )
            self._event(
                connection,
                stale,
                event_type="invalidated",
                actor_user_id=actor_user_id,
                reason=str(reason).strip(),
            )
            connection.commit()
            return {**stale, "reset_invalidation": invalidation}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def events(self, analysis_partition_id: str) -> List[Dict[str, Any]]:
        return self._many(
            """
            SELECT * FROM analysis_partition_events
            WHERE analysis_partition_id = ?
            ORDER BY created_at ASC, analysis_partition_event_id ASC
            """,
            (analysis_partition_id,),
        )

    def reset_operations(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many(
            """
            SELECT * FROM analysis_partition_reset_operations
            WHERE project_id = ?
            ORDER BY committed_at ASC, reset_operation_id ASC
            """,
            (project_id,),
        )

    def derivative_invalidations(
        self, reset_operation_id: str
    ) -> List[Dict[str, Any]]:
        return self._many(
            """
            SELECT * FROM analysis_partition_derivative_invalidations
            WHERE reset_operation_id = ?
            ORDER BY artifact_type, artifact_id, source_authority
            """,
            (reset_operation_id,),
        )
