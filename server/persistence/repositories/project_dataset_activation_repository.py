from __future__ import annotations

import json
import sqlite3
import uuid
from threading import Lock, RLock
from typing import Any, Dict, List

from ..db import decode_row, json_dumps, now_iso
from .base_repository import BaseRepository


class ProjectDatasetActivationConflictError(RuntimeError):
    """A compare-and-set activation request raced with another revision."""


class ProjectDatasetActivationStateError(RuntimeError):
    """The durable link/selection state is missing or contradictory."""


_IDENTITY_INDEPENDENT_STEPS = {"step00"}
_CANONICAL_LINEAGE_CONTRACT = "canonical_dataset_version"
_CURRENT_EVIDENCE_STATUSES = {"captured", "ready", "approved"}
_STANDARD_WORKFLOW_ORDER = [
    "step00",
    "step01",
    "step02",
    "step03",
    "step04",
    "step05",
    "step06",
    "step07",
    "step08",
    "step09",
    "step10",
    "step11",
    "step12",
    "step13",
]
_EVIDENCE_TYPE_STEPS = {
    "eda": "step02",
    "outliers": "step03",
    "missing_values": "step04",
    "feature_engineering": "step05",
    "model_training": "step07",
    "evaluation": "step08",
    "model_selection": "step09",
}


_PROJECT_ACTIVATION_LOCKS_GUARD = Lock()
_PROJECT_ACTIVATION_LOCKS: Dict[str, Any] = {}


def project_dataset_activation_lock(project_id: Any) -> Any:
    """Return the process-local serialization lock for one project.

    SQLite serializes the durable rows, while this lock extends that same
    ordering through DATASTORE publication.  Dataset identity readers and
    activation endpoints therefore cannot interleave a durable revision
    change with publication of an older immutable artifact.
    """

    key = str(project_id or "").strip()
    if not key:
        raise ProjectDatasetActivationStateError(
            "A project_id is required for dataset activation serialization."
        )
    with _PROJECT_ACTIVATION_LOCKS_GUARD:
        lock = _PROJECT_ACTIVATION_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _PROJECT_ACTIVATION_LOCKS[key] = lock
        return lock


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed if str(item)] if isinstance(parsed, list) else []


def _link_authorization_metadata(
    metadata: Dict[str, Any] | None,
    existing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Keep authorization separate while refreshing a labeled UI projection."""

    incoming = dict(metadata or {})
    prior = dict(existing or {})
    last_validated_version = _text(
        incoming.get("requestedDatasetVersionId")
        or incoming.get("datasetVersionId")
        or incoming.get("versionId")
        or prior.get("lastValidatedVersionId")
        or prior.get("requestedDatasetVersionId")
        or prior.get("datasetVersionId")
        or prior.get("versionId")
    )
    merged = dict(existing or {})
    merged.update(metadata or {})
    version_keys = {
        "requesteddatasetversionid",
        "datasetversionid",
        "versionid",
        "activeversionid",
        "lastvalidatedversionid",
    }
    sanitized = {
        str(key): value
        for key, value in merged.items()
        if str(key).replace("_", "").casefold() not in version_keys
    }
    if last_validated_version:
        sanitized["lastValidatedVersionId"] = last_validated_version
    return sanitized


def _text(value: Any) -> str:
    return str(value or "").strip()


def _evidence_step(record: Dict[str, Any], payload: Dict[str, Any]) -> str:
    explicit = _text(record.get("step_id"))
    if explicit:
        return explicit
    source = _text(record.get("source_ref")).split("?", 1)[0].rstrip("/")
    if source.startswith("/step"):
        return source.removeprefix("/")
    artifact_type = _text(record.get("artifact_type")).casefold()
    if artifact_type == "governance":
        tags = {
            _text(tag).casefold()
            for tag in payload.get("tags", [])
            if _text(tag)
        } if isinstance(payload.get("tags"), list) else set()
        if tags & {"feature_gate", "validation_design"}:
            return "step06"
    return _EVIDENCE_TYPE_STEPS.get(artifact_type, "")


def _exact_evidence_payload(
    payload: Dict[str, Any],
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
) -> bool:
    lineage = payload.get("lineage")
    if not isinstance(lineage, dict):
        return False
    expected = {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
    }
    return bool(
        _text(payload.get("lineage_contract")) == _CANONICAL_LINEAGE_CONTRACT
        and _text(lineage.get("lineage_contract")) == _CANONICAL_LINEAGE_CONTRACT
        and all(_text(payload.get(key)) == value for key, value in expected.items())
        and all(_text(lineage.get(key)) == value for key, value in expected.items())
    )


def _hashes_match_feature_evidence(payload: Dict[str, Any]) -> bool:
    lineage = payload.get("lineage") if isinstance(payload.get("lineage"), dict) else {}
    artifact = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    manifest_hash = _text(lineage.get("manifestVersion"))
    materialization_hash = _text(lineage.get("materializationHash"))
    return bool(
        manifest_hash
        and materialization_hash
        and _text(artifact.get("manifestHash")) == manifest_hash
        and _text(artifact.get("confirmedManifestHash")) == manifest_hash
        and _text(artifact.get("materializationHash")) == materialization_hash
    )


def _hashes_match_split_evidence(payload: Dict[str, Any]) -> bool:
    lineage = payload.get("lineage") if isinstance(payload.get("lineage"), dict) else {}
    artifact = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    manifest_hash = _text(lineage.get("manifestVersion"))
    split_id = _text(lineage.get("splitId"))
    design_id = _text(lineage.get("validationDesignId"))
    design_version = _text(lineage.get("validationDesignVersion"))
    artifact_design = (
        artifact.get("validation_design")
        if isinstance(artifact.get("validation_design"), dict)
        else {}
    )
    return bool(
        manifest_hash
        and split_id
        and design_id
        and design_version
        and _text(artifact.get("status")).casefold() == "current"
        and _text(artifact.get("feature_manifest_version")) == manifest_hash
        and _text(artifact.get("split_id")) == split_id
        and _text(artifact.get("validation_design_id")) == design_id
        and _text(artifact.get("validation_design_version")) == design_version
        and _text(artifact_design.get("status")).casefold() == "approved"
    )


def _matches_promoted_model_completion(
    payload: Dict[str, Any],
    *,
    step_id: str,
    version: Dict[str, Any],
) -> bool:
    """Validate a late-stage completion against the exact current champion.

    Canonical dataset identity alone is insufficient after promotion.  Every
    completion grant must repeat the immutable registry lineage in both the
    canonical lineage block and the step-specific payload so a browser cannot
    unlock one model's workflow with another model's evidence.
    """

    lineage = payload.get("lineage") if isinstance(payload.get("lineage"), dict) else {}
    artifact = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    expected = {
        "modelId": _text(version.get("model_id")),
        "modelVersionId": _text(version.get("model_version_id")),
        "candidateId": _text(version.get("candidate_id")),
        "trainingRunId": _text(version.get("training_run_id")),
        "featureManifestVersion": _text(version.get("feature_manifest_version")),
        "validationDesignId": _text(version.get("validation_design_id")),
        "splitId": _text(version.get("split_id")),
        "artifactChecksum": _text(version.get("checksum")),
        "artifactVerificationStatus": "verified",
        "target": _text(version.get("target_name")),
    }
    if not all(expected.values()):
        return False
    if (
        _text(lineage.get("workflowStep")) != step_id
        or _text(artifact.get("stepId")) != step_id
        or _text(artifact.get("workflowCompletionContract"))
        != "predictive_workflow_completion_v1"
    ):
        return False
    if any(
        _text(container.get(key)) != value
        for container in (lineage, artifact)
        for key, value in expected.items()
    ):
        return False

    if step_id == "step10":
        partitions = artifact.get("scoredPartitions")
        return bool(
            isinstance(partitions, list)
            and partitions
            and all(_text(partition).casefold() in {"train", "test", "oot"} for partition in partitions)
            and int(artifact.get("scoredOutputCount") or 0) == len(partitions)
        )
    if step_id == "step11":
        return bool(
            int(artifact.get("requiredSections") or 0) > 0
            and _text(artifact.get("documentTitle"))
            and _text(artifact.get("documentMode"))
            and _text(artifact.get("generatedAt"))
        )
    if step_id == "step12":
        return all(
            key in artifact
            for key in (
                "implementationOwner",
                "implementationTargetDate",
                "implementationEnvironment",
                "implementationNotesPresent",
            )
        )
    if step_id == "step13":
        metrics = artifact.get("monitoringMetrics")
        return bool(
            _text(artifact.get("monitoringCadence"))
            and isinstance(metrics, list)
            and any(_text(metric) for metric in metrics)
            and "monitoringNotesPresent" in artifact
            and "escalationCount" in artifact
        )
    return False


class ProjectDatasetActivationRepository(BaseRepository):
    """Durable authority for project links and exact modeling activation.

    Every multi-record mutation starts with ``BEGIN IMMEDIATE``.  SQLite thus
    serializes competing activations before either request reads the current
    revision, and a failure rolls back the link, selection, event, and workflow
    reconciliation together.
    """

    def get_link(self, project_id: str, dataset_id: str) -> Dict[str, Any] | None:
        return self._one(
            "SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
            (project_id, dataset_id),
        )

    def list_links(self, project_id: str, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
        if include_inactive:
            return self._many(
                "SELECT * FROM project_dataset_links WHERE project_id = ? ORDER BY updated_at DESC, dataset_id",
                (project_id,),
            )
        return self._many(
            """
            SELECT * FROM project_dataset_links
            WHERE project_id = ? AND link_status = 'active'
            ORDER BY updated_at DESC, dataset_id
            """,
            (project_id,),
        )

    def get_active_selection(self, project_id: str) -> Dict[str, Any] | None:
        return self._one(
            "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
            (project_id,),
        )

    def get_project_state(self, project_id: str) -> Dict[str, Any]:
        """Return links and active selection from one consistent read snapshot."""
        connection = self.database.connect()
        try:
            connection.execute("BEGIN")
            links = [
                decode_row(row) or {}
                for row in connection.execute(
                    """
                    SELECT * FROM project_dataset_links
                    WHERE project_id = ? AND link_status = 'active'
                    ORDER BY updated_at DESC, dataset_id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            active = decode_row(
                connection.execute(
                    "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
            )
            connection.commit()
            return {"links": links, "active_selection": active}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reconcile_workflow_after_history_update(
        self,
        *,
        project_id: str,
    ) -> Dict[str, Any]:
        """Recompute effective progress after append-only workflow history changes.

        A browser workflow save records only historical observations.  Effective
        completion must be recalculated from the exact durable active selection
        and current canonical evidence; otherwise a project activated before a
        later step was completed remains permanently pinned to the older
        effective resume point.  This method deliberately has no browser,
        first-version, or latest-version fallback.
        """

        project_key = _text(project_id)
        if not project_key:
            raise ProjectDatasetActivationStateError(
                "A project_id is required for workflow reconciliation."
            )

        project_lock = project_dataset_activation_lock(project_key)
        project_lock.acquire()
        connection = None
        try:
            connection = self.database.connect()
            self._begin_immediate(connection)
            active = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_key,),
            )
            dataset_id = _text((active or {}).get("dataset_id"))
            dataset_version_id = _text(
                (active or {}).get("dataset_version_id")
            )
            activation_revision = int(
                (active or {}).get("activation_revision") or 0
            )
            activated_at = _text((active or {}).get("activated_at"))
            activation_status = _text(
                (active or {}).get("activation_status")
            ).casefold()

            link = None
            if dataset_id:
                link = self._row(
                    connection,
                    """
                    SELECT * FROM project_dataset_links
                    WHERE project_id = ? AND dataset_id = ?
                    """,
                    (project_key, dataset_id),
                )

            exact_active_identity = bool(
                active
                and activation_status == "active"
                and dataset_id
                and dataset_version_id
                and activation_revision >= 1
                and activated_at
                and link
                and _text(link.get("link_status")).casefold() == "active"
            )
            if exact_active_identity:
                self._reconcile_workflow_identity(
                    connection,
                    project_id=project_key,
                    dataset_id=dataset_id,
                    dataset_version_id=dataset_version_id,
                    activation_revision=activation_revision,
                    activated_at=activated_at,
                    preserve_effective=True,
                )
            else:
                contradictory = bool(
                    active
                    and (
                        activation_status == "contradictory"
                        or (
                            activation_status == "active"
                            and not exact_active_identity
                        )
                    )
                )
                self._reconcile_workflow_unavailable(
                    connection,
                    project_id=project_key,
                    reason=(
                        "The durable active dataset selection is contradictory or its exact project link is unavailable."
                        if contradictory
                        else "No exact durable active Dataset Library version is available for this project."
                    ),
                    validity_status=("contradictory" if contradictory else "missing"),
                )

            workflow = self._row(
                connection,
                "SELECT * FROM workflow_state WHERE project_id = ?",
                (project_key,),
            ) or {}
            connection.commit()
            return workflow
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
            project_lock.release()

    @staticmethod
    def _begin_immediate(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _row(connection: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> Dict[str, Any] | None:
        return decode_row(connection.execute(query, params).fetchone())

    @staticmethod
    def _write_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str | None,
        activation_revision: int | None,
        event_type: str,
        event_status: str,
        actor_user_id: str,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        created_at = now_iso()
        event_id = f"dataset-activation-{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO project_dataset_activation_events (
              activation_event_id, project_id, dataset_id, dataset_version_id,
              activation_revision, event_type, event_status, actor_user_id,
              created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                project_id,
                dataset_id,
                dataset_version_id,
                activation_revision,
                event_type,
                event_status,
                actor_user_id,
                created_at,
                json_dumps(metadata, {}),
            ),
        )
        return {
            "activation_event_id": event_id,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "activation_revision": activation_revision,
            "event_type": event_type,
            "event_status": event_status,
            "actor_user_id": actor_user_id,
            "created_at": created_at,
            "metadata_json": metadata or {},
        }

    @staticmethod
    def _matching_evidence(
        connection: sqlite3.Connection,
        *,
        step_id: str,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> List[tuple[Dict[str, Any], Dict[str, Any]]]:
        matches: List[tuple[Dict[str, Any], Dict[str, Any]]] = []
        rows = connection.execute(
            """
            SELECT * FROM evidence_artifacts
            WHERE project_id = ?
            ORDER BY created_at DESC, evidence_id DESC
            """,
            (project_id,),
        ).fetchall()
        for row in rows:
            record = dict(row)
            payload = _json_object(record.get("payload_json"))
            if (
                _evidence_step(record, payload) == step_id
                and _text(record.get("status")).casefold()
                in _CURRENT_EVIDENCE_STATUSES
                and _exact_evidence_payload(
                    payload,
                    project_id=project_id,
                    dataset_id=dataset_id,
                    dataset_version_id=dataset_version_id,
                )
            ):
                matches.append((record, payload))
        return matches

    @classmethod
    def _step_lineage_validation(
        cls,
        connection: sqlite3.Connection,
        *,
        step_id: str,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> tuple[bool, str, List[str]]:
        """Validate one historical completion from durable server records.

        A historical browser completion is never evidence by itself.  Simple
        preparation steps require server-authorized canonical evidence.  Steps
        that create a manifest, split, candidate, Evaluation package, or final
        model additionally require their contract identifiers, hashes, and
        integrity states to agree with the exact active version.
        """
        if step_id in _IDENTITY_INDEPENDENT_STEPS:
            return True, "Identity-independent project context remains current.", []
        if step_id == "step01":
            return (
                True,
                "The durable project link and exact active version revalidate Data Acquisition.",
                [],
            )

        evidence = cls._matching_evidence(
            connection,
            step_id=step_id,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
        evidence_ids = [_text(record.get("evidence_id")) for record, _ in evidence]

        if step_id in {"step01b", "step02", "step03", "step04"}:
            return (
                bool(evidence),
                (
                    "A current canonical evidence record matches the exact active version."
                    if evidence
                    else "No current canonical evidence record matches the exact active version."
                ),
                evidence_ids,
            )

        if step_id == "step05":
            valid = [
                (record, payload)
                for record, payload in evidence
                if _hashes_match_feature_evidence(payload)
            ]
            return (
                bool(valid),
                (
                    "The confirmed feature-manifest and materialization hashes match."
                    if valid
                    else "No exact feature evidence has matching confirmed-manifest and materialization hashes."
                ),
                [_text(record.get("evidence_id")) for record, _ in valid],
            )

        if step_id == "step06":
            valid = [
                (record, payload)
                for record, payload in evidence
                if _hashes_match_split_evidence(payload)
            ]
            return (
                bool(valid),
                (
                    "The approved Validation Design, split, and feature-manifest hashes match."
                    if valid
                    else "No exact split evidence has a current approved design and matching contract identifiers."
                ),
                [_text(record.get("evidence_id")) for record, _ in valid],
            )

        if step_id == "step07":
            for record, payload in evidence:
                lineage = payload.get("lineage") if isinstance(payload.get("lineage"), dict) else {}
                decision_id = _text(lineage.get("modelDecisionId"))
                job_id = _text(lineage.get("jobId"))
                manifest_hash = _text(lineage.get("manifestVersion"))
                split_id = _text(lineage.get("splitId"))
                design_id = _text(lineage.get("validationDesignId"))
                design_version = _text(lineage.get("validationDesignVersion"))
                if not all((decision_id, job_id, manifest_hash, split_id, design_id, design_version)):
                    continue
                decision = connection.execute(
                    """
                    SELECT * FROM candidate_selection_decisions
                    WHERE candidate_decision_id = ? AND project_id = ?
                      AND dataset_id = ? AND dataset_version_id = ?
                      AND NOT EXISTS (
                        SELECT 1
                        FROM analysis_partition_derivative_invalidations di
                        WHERE di.artifact_type = 'candidate_decision'
                          AND di.artifact_id = candidate_selection_decisions.candidate_decision_id
                          AND di.invalidation_status = 'invalidated'
                      )
                    """,
                    (decision_id, project_id, dataset_id, dataset_version_id),
                ).fetchone()
                if decision is None:
                    continue
                contract = dict(decision)
                if all(
                    (
                        _text(contract.get("decision_status")) == "locked",
                        _text(contract.get("selection_integrity_status")) == "verified",
                        _text(contract.get("holdout_isolation_status")) == "verified",
                        _text(contract.get("selection_metric_source")) != "final_holdout",
                        _text(contract.get("training_job_id")) == job_id,
                        _text(contract.get("feature_manifest_hash")) == manifest_hash,
                        _text(contract.get("split_id")) == split_id,
                        _text(contract.get("validation_design_id")) == design_id,
                        _text(contract.get("validation_design_version_id")) == design_version,
                        bool(_text(contract.get("decision_contract_hash"))),
                        bool(_text(contract.get("ranking_snapshot_hash"))),
                        bool(_text(contract.get("selected_candidate_contract_hash"))),
                    )
                ):
                    return (
                        True,
                        "The exact locked candidate has verified non-holdout selection lineage.",
                        [_text(record.get("evidence_id"))],
                    )
            return (
                False,
                "No exact training evidence resolves to a verified locked candidate contract.",
                [],
            )

        if step_id == "step08":
            package = connection.execute(
                """
                SELECT * FROM evaluation_packages
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                  AND package_status = 'complete'
                  AND selection_integrity_status = 'verified'
                  AND holdout_isolation_status = 'verified'
                  AND package_integrity_status = 'verified'
                  AND final_holdout_status = 'evaluated'
                  AND recommendations_derived_from_final_holdout = 0
                  AND NOT EXISTS (
                    SELECT 1
                    FROM analysis_partition_derivative_invalidations di
                    WHERE di.artifact_type = 'evaluation_package'
                      AND di.artifact_id = evaluation_packages.evaluation_package_id
                      AND di.invalidation_status = 'invalidated'
                  )
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (project_id, dataset_id, dataset_version_id),
            ).fetchone()
            valid = bool(
                package
                and _text(package["evaluation_package_contract_hash"])
                and _text(package["content_hash"])
                and _text(package["feature_manifest_hash"])
                and _text(package["split_id"])
            )
            return (
                valid,
                (
                    "A verified Evaluation package matches the exact active lineage."
                    if valid
                    else "No verified Evaluation package matches the exact active lineage."
                ),
                [_text(package["evaluation_package_id"])] if valid and package else [],
            )

        if step_id == "step09":
            version = connection.execute(
                """
                SELECT * FROM model_versions
                WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
                  AND publication_status = 'finalized'
                  AND lineage_status = 'verified'
                  AND promotion_readiness_status = 'verified'
                  AND evaluation_package_integrity_status = 'verified'
                ORDER BY finalized_at DESC, created_at DESC
                LIMIT 1
                """,
                (project_id, dataset_id, dataset_version_id),
            ).fetchone()
            valid = bool(
                version
                and _text(version["artifact_reference"])
                and _text(version["checksum"])
                and _text(version["artifact_verified_at"])
                and _text(version["candidate_contract_hash"])
                and _text(version["evaluation_package_contract_hash"])
            )
            return (
                valid,
                (
                    "A finalized checksum-verified model version matches the exact active lineage."
                    if valid
                    else "No finalized checksum-verified model version matches the exact active lineage."
                ),
                [_text(version["model_version_id"])] if valid and version else [],
            )

        if step_id in {"step10", "step11", "step12", "step13"}:
            version_row = connection.execute(
                """
                SELECT mv.*
                FROM model_versions mv
                JOIN models m
                  ON m.model_id = mv.model_id
                 AND m.project_id = mv.project_id
                 AND m.current_version_id = mv.model_version_id
                WHERE mv.project_id = ?
                  AND mv.dataset_id = ?
                  AND mv.dataset_version_id = ?
                  AND mv.publication_status = 'finalized'
                  AND mv.lineage_status = 'verified'
                  AND mv.promotion_readiness_status = 'verified'
                  AND mv.evaluation_package_integrity_status = 'verified'
                  AND mv.artifact_verified_at IS NOT NULL
                  AND mv.checksum IS NOT NULL
                  AND mv.checksum <> ''
                  AND COALESCE(m.archived, 0) = 0
                ORDER BY mv.finalized_at DESC, mv.created_at DESC
                LIMIT 1
                """,
                (project_id, dataset_id, dataset_version_id),
            ).fetchone()
            version = dict(version_row) if version_row is not None else None
            if version is None:
                return (
                    False,
                    "No current checksum-verified promoted model matches the exact active lineage.",
                    [],
                )

            valid = [
                (record, payload)
                for record, payload in evidence
                if _matches_promoted_model_completion(
                    payload,
                    step_id=step_id,
                    version=version,
                )
            ]
            if step_id == "step10" and valid:
                scoring_run = connection.execute(
                    """
                    SELECT scoring_run_id
                    FROM scoring_runs
                    WHERE project_id = ?
                      AND dataset_id = ?
                      AND dataset_version_id = ?
                      AND model_version_id = ?
                      AND target = ?
                      AND status = 'completed'
                      AND archived_at IS NULL
                      AND checksum IS NOT NULL
                      AND checksum <> ''
                      AND LOWER(partition) IN ('train', 'test', 'oot')
                    ORDER BY completed_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (
                        project_id,
                        dataset_id,
                        dataset_version_id,
                        _text(version.get("model_version_id")),
                        _text(version.get("target_name")),
                    ),
                ).fetchone()
                if scoring_run is None:
                    valid = []

            return (
                bool(valid),
                (
                    "The exact current promoted model and step-specific durable artifact are verified."
                    if valid
                    else (
                        "No completed checksum-backed exact scoring run and completion artifact match the promoted model."
                        if step_id == "step10"
                        else "No step-specific completion artifact matches the exact promoted model lineage."
                    )
                ),
                [_text(record.get("evidence_id")) for record, _ in valid],
            )

        # Later workflow steps require their own exact canonical artifact.  The
        # absence of one remains stale; a historical UI status cannot restore it.
        return (
            bool(evidence),
            (
                "A current canonical evidence record matches the exact active version."
                if evidence
                else "No current canonical artifact matches the exact active version."
            ),
            evidence_ids,
        )

    @classmethod
    def _reconcile_workflow_identity(
        cls,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        activation_revision: int,
        activated_at: str,
        preserve_effective: bool,
    ) -> Dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM workflow_state WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            # Activation is authoritative identity state even when this project
            # has never saved browser workflow history.  Create a fail-closed
            # row without inventing a completed step; Data Acquisition remains
            # the resume route until the user records its completion.
            timestamp = now_iso()
            connection.execute(
                """
                INSERT INTO workflow_state (
                  project_id, current_step_id, completed_steps_json,
                  workflow_status_json, step_evidence_status_json, updated_at
                ) VALUES (?, 'step01', '[]', '{}', '{}', ?)
                """,
                (project_id, timestamp),
            )
            row = connection.execute(
                "SELECT * FROM workflow_state WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        record = dict(row)
        historical = _json_list(record.get("completed_steps_json"))
        workflow_status = _json_object(record.get("workflow_status_json"))
        effective_completed: List[str] = []
        effective_steps: Dict[str, Any] = {}
        for step in historical:
            valid, reason, artifact_ids = cls._step_lineage_validation(
                connection,
                step_id=step,
                project_id=project_id,
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
            )
            if valid:
                effective_completed.append(step)
            effective_steps[step] = {
                "effectiveStatus": "complete" if valid else "pending",
                "lineageStatus": "current" if valid else "stale",
                "reason": reason,
                "artifactIds": artifact_ids,
            }

        previous_current = _text(
            workflow_status.get("effectiveCurrentStepId")
            or record.get("current_step_id")
        )
        effective_current = next(
            (
                step
                for step in _STANDARD_WORKFLOW_ORDER
                if step in historical and step not in effective_completed
            ),
            "",
        )
        if not effective_current and previous_current and previous_current not in effective_completed:
            effective_current = previous_current
        if not effective_current:
            effective_current = next(
                (step for step in _STANDARD_WORKFLOW_ORDER if step not in effective_completed),
                "step13",
            )
        canonical = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            # The activation revision is part of the authoritative modeling
            # identity.  Open Project must be able to compare the exact
            # backend-reconciled revision with ``identityValidity`` after a
            # fresh browser session; omitting it makes otherwise-current
            # projects fail closed to Data Acquisition.
            "activation_revision": activation_revision,
        }
        workflow_status.update(
            {
                "hasDataset": True,
                "datasetIdentity": canonical,
                "historicalCompletedSteps": historical,
                "effectiveCompletedSteps": effective_completed,
                "effectiveCurrentStepId": effective_current,
                "effectiveSteps": effective_steps,
                # `steps` is historical server-owned audit state. Browser
                # workflowStatus.steps is never copied into effective state.
                "steps": {step: "complete" for step in historical},
                "identityValidity": {
                    "status": "current",
                    "projectId": project_id,
                    "datasetId": dataset_id,
                    "datasetVersionId": dataset_version_id,
                    "activationRevision": activation_revision,
                    "activatedAt": activated_at,
                    "revalidationRequired": len(effective_completed) < len(historical),
                    "revalidatedAt": now_iso(),
                    "historicalCompletionPreserved": True,
                },
            }
        )
        connection.execute(
            """
            UPDATE workflow_state
            SET workflow_status_json = ?, updated_at = ?
            WHERE project_id = ?
            """,
            (json_dumps(workflow_status, {}), now_iso(), project_id),
        )
        return {
            "historicalCompletedSteps": historical,
            "effectiveCompletedSteps": effective_completed,
            "effectiveCurrentStepId": effective_current,
            "workflowStatus": workflow_status,
        }

    @staticmethod
    def _reconcile_workflow_unavailable(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        reason: str,
        validity_status: str = "missing",
    ) -> Dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM workflow_state WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        historical = _json_list(record.get("completed_steps_json"))
        workflow_status = _json_object(record.get("workflow_status_json"))
        effective_completed = [
            step for step in historical if step in _IDENTITY_INDEPENDENT_STEPS
        ]
        effective_steps = {
            step: {
                "effectiveStatus": (
                    "complete" if step in effective_completed else "pending"
                ),
                "lineageStatus": (
                    "current" if step in effective_completed else validity_status
                ),
                "reason": (
                    "Identity-independent project context remains current."
                    if step in effective_completed
                    else reason
                ),
                "artifactIds": [],
            }
            for step in historical
        }
        workflow_status.update(
            {
                "hasDataset": False,
                "historicalCompletedSteps": historical,
                "effectiveCompletedSteps": effective_completed,
                "effectiveCurrentStepId": "step01",
                "effectiveSteps": effective_steps,
                "steps": {step: "complete" for step in historical},
                "identityValidity": {
                    "status": validity_status,
                    "reason": reason,
                    "historicalCompletionPreserved": True,
                },
            }
        )
        connection.execute(
            """
            UPDATE workflow_state
            SET workflow_status_json = ?, updated_at = ?
            WHERE project_id = ?
            """,
            (json_dumps(workflow_status, {}), now_iso(), project_id),
        )
        return {
            "historicalCompletedSteps": historical,
            "effectiveCompletedSteps": effective_completed,
            "effectiveCurrentStepId": "step01",
            "workflowStatus": workflow_status,
        }

    def authorize_link(
        self,
        *,
        project_id: str,
        dataset_id: str,
        actor_user_id: str,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if not project_id or not dataset_id or not actor_user_id:
            raise ProjectDatasetActivationStateError(
                "project_id, dataset_id, and an authenticated actor are required."
            )
        project_lock = project_dataset_activation_lock(project_id)
        project_lock.acquire()
        connection = None
        try:
            connection = self.database.connect()
            self._begin_immediate(connection)
            if connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone() is None:
                raise ProjectDatasetActivationStateError("The authorized project does not exist.")
            timestamp = now_iso()
            existing = self._row(
                connection,
                "SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
                (project_id, dataset_id),
            )
            changed = existing is None or existing.get("link_status") != "active"
            existing_metadata = _json_object((existing or {}).get("metadata_json"))
            link_metadata = _link_authorization_metadata(metadata, existing_metadata)
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO project_dataset_links (
                      project_id, dataset_id, link_status, linked_by, linked_at,
                      updated_at, metadata_json
                    ) VALUES (?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        dataset_id,
                        actor_user_id,
                        timestamp,
                        timestamp,
                        json_dumps(link_metadata, {}),
                    ),
                )
            elif changed:
                connection.execute(
                    """
                    UPDATE project_dataset_links
                    SET link_status = 'active', linked_by = ?, updated_at = ?, metadata_json = ?
                    WHERE project_id = ? AND dataset_id = ?
                    """,
                    (
                        actor_user_id,
                        timestamp,
                        json_dumps(link_metadata, {}),
                        project_id,
                        dataset_id,
                    ),
                )
            elif existing_metadata != link_metadata:
                connection.execute(
                    """
                    UPDATE project_dataset_links
                    SET updated_at = ?, metadata_json = ?
                    WHERE project_id = ? AND dataset_id = ?
                    """,
                    (
                        timestamp,
                        json_dumps(link_metadata, {}),
                        project_id,
                        dataset_id,
                    ),
                )
            if changed:
                self._write_event(
                    connection,
                    project_id=project_id,
                    dataset_id=dataset_id,
                    dataset_version_id=None,
                    activation_revision=None,
                    event_type="project_dataset_linked",
                    event_status="complete",
                    actor_user_id=actor_user_id,
                    metadata=metadata,
                )
            link = self._row(
                connection,
                "SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
                (project_id, dataset_id),
            ) or {}
            connection.commit()
            return {"link": link, "changed": changed}
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
            project_lock.release()

    def activate_exact(
        self,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        actor_user_id: str,
        expected_activation_revision: int | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if not all((project_id, dataset_id, dataset_version_id, actor_user_id)):
            raise ProjectDatasetActivationStateError(
                "An exact project, dataset, version, and authenticated actor are required."
            )
        project_lock = project_dataset_activation_lock(project_id)
        project_lock.acquire()
        connection = None
        try:
            connection = self.database.connect()
            self._begin_immediate(connection)
            if connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone() is None:
                raise ProjectDatasetActivationStateError("The authorized project does not exist.")

            current = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            )
            current_revision = int((current or {}).get("activation_revision") or 0)
            if (
                expected_activation_revision is not None
                and expected_activation_revision != current_revision
            ):
                raise ProjectDatasetActivationConflictError(
                    "The active dataset selection changed before this activation completed."
                )
            same_active = bool(
                current
                and current.get("activation_status") == "active"
                and current.get("dataset_id") == dataset_id
                and current.get("dataset_version_id") == dataset_version_id
            )
            timestamp = now_iso()
            existing_link = self._row(
                connection,
                "SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
                (project_id, dataset_id),
            )
            link_changed = existing_link is None or existing_link.get("link_status") != "active"
            existing_link_metadata = _json_object(
                (existing_link or {}).get("metadata_json")
            )
            link_metadata = _link_authorization_metadata(
                metadata,
                existing_link_metadata,
            )
            if existing_link is None:
                connection.execute(
                    """
                    INSERT INTO project_dataset_links (
                      project_id, dataset_id, link_status, linked_by, linked_at,
                      updated_at, metadata_json
                    ) VALUES (?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        dataset_id,
                        actor_user_id,
                        timestamp,
                        timestamp,
                        json_dumps(link_metadata, {}),
                    ),
                )
            elif link_changed:
                connection.execute(
                    """
                    UPDATE project_dataset_links
                    SET link_status = 'active', linked_by = ?, updated_at = ?, metadata_json = ?
                    WHERE project_id = ? AND dataset_id = ?
                    """,
                    (
                        actor_user_id,
                        timestamp,
                        json_dumps(link_metadata, {}),
                        project_id,
                        dataset_id,
                    ),
                )
            elif existing_link_metadata != link_metadata:
                connection.execute(
                    """
                    UPDATE project_dataset_links
                    SET updated_at = ?, metadata_json = ?
                    WHERE project_id = ? AND dataset_id = ?
                    """,
                    (
                        timestamp,
                        json_dumps(link_metadata, {}),
                        project_id,
                        dataset_id,
                    ),
                )

            changed = not same_active or link_changed
            activation_revision = current_revision if same_active and not link_changed else current_revision + 1
            activated_at = str((current or {}).get("activated_at") or timestamp) if same_active and not link_changed else timestamp
            if current is None:
                connection.execute(
                    """
                    INSERT INTO active_modeling_dataset_versions (
                      project_id, dataset_id, dataset_version_id,
                      activation_revision, activation_status, activated_by,
                      activated_at, updated_at, metadata_json
                    ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        dataset_id,
                        dataset_version_id,
                        activation_revision,
                        actor_user_id,
                        activated_at,
                        timestamp,
                        json_dumps(metadata, {}),
                    ),
                )
            elif changed:
                connection.execute(
                    """
                    UPDATE active_modeling_dataset_versions
                    SET dataset_id = ?, dataset_version_id = ?, activation_revision = ?,
                        activation_status = 'active', activated_by = ?, activated_at = ?,
                        updated_at = ?, metadata_json = ?
                    WHERE project_id = ?
                    """,
                    (
                        dataset_id,
                        dataset_version_id,
                        activation_revision,
                        actor_user_id,
                        activated_at,
                        timestamp,
                        json_dumps(metadata, current.get("metadata_json") or {}),
                        project_id,
                    ),
                )

            event = None
            if changed:
                event = self._write_event(
                    connection,
                    project_id=project_id,
                    dataset_id=dataset_id,
                    dataset_version_id=dataset_version_id,
                    activation_revision=activation_revision,
                    event_type="modeling_dataset_activated",
                    event_status="complete",
                    actor_user_id=actor_user_id,
                    metadata={
                        **(metadata or {}),
                        "previousDatasetId": (current or {}).get("dataset_id"),
                        "previousDatasetVersionId": (current or {}).get("dataset_version_id"),
                        "previousActivationRevision": current_revision,
                    },
                )
            workflow = self._reconcile_workflow_identity(
                connection,
                project_id=project_id,
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
                activation_revision=activation_revision,
                activated_at=activated_at,
                preserve_effective=not changed,
            )
            link = self._row(
                connection,
                "SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
                (project_id, dataset_id),
            ) or {}
            active = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            ) or {}
            connection.commit()
            return {
                "link": link,
                "active_selection": active,
                "activation_event": event,
                "workflow_effective_state": workflow,
                "changed": changed,
            }
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
            project_lock.release()

    def unlink_dataset(
        self,
        *,
        project_id: str,
        dataset_id: str,
        actor_user_id: str,
        reason: str = "The project-dataset authorization was removed.",
    ) -> Dict[str, Any]:
        project_lock = project_dataset_activation_lock(project_id)
        project_lock.acquire()
        connection = None
        try:
            connection = self.database.connect()
            self._begin_immediate(connection)
            link = self._row(
                connection,
                "SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
                (project_id, dataset_id),
            )
            if link is None:
                connection.commit()
                return {"removed": 0, "active_selection": self.get_active_selection(project_id)}
            timestamp = now_iso()
            connection.execute(
                """
                UPDATE project_dataset_links
                SET link_status = 'unlinked', updated_at = ?
                WHERE project_id = ? AND dataset_id = ?
                """,
                (timestamp, project_id, dataset_id),
            )
            active = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            )
            revision = int((active or {}).get("activation_revision") or 0)
            removed_active_selection = bool(
                active
                and active.get("dataset_id") == dataset_id
                and active.get("activation_status") == "active"
            )
            if removed_active_selection:
                revision += 1
                connection.execute(
                    """
                    UPDATE active_modeling_dataset_versions
                    SET activation_status = 'inactive', activation_revision = ?, updated_at = ?
                    WHERE project_id = ?
                    """,
                    (revision, timestamp, project_id),
                )
                self._reconcile_workflow_unavailable(
                    connection,
                    project_id=project_id,
                    reason=reason,
                )
            self._write_event(
                connection,
                project_id=project_id,
                dataset_id=dataset_id,
                dataset_version_id=(
                    (active or {}).get("dataset_version_id")
                    if removed_active_selection
                    else None
                ),
                activation_revision=(revision if removed_active_selection else None),
                event_type="project_dataset_unlinked",
                event_status="complete",
                actor_user_id=actor_user_id,
                metadata={"reason": reason},
            )
            updated_active = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            )
            connection.commit()
            return {"removed": 1, "active_selection": updated_active}
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
            project_lock.release()

    def record_contradiction(
        self,
        *,
        project_id: str,
        actor_user_id: str,
        reason: str,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Fail a durable selection closed while preserving its exact identity.

        A contradiction is diagnostic state, not a request to guess a replacement
        dataset or version.  Keep the selected identifiers and revision intact so
        an operator can inspect the failed contract, and append an audit event in
        the same immediate transaction.
        """
        if not project_id or not actor_user_id or not str(reason or "").strip():
            raise ProjectDatasetActivationStateError(
                "project_id, an authenticated actor, and a contradiction reason are required."
            )
        project_lock = project_dataset_activation_lock(project_id)
        project_lock.acquire()
        try:
            return self._record_contradiction_transaction(
                project_id=project_id,
                actor_user_id=actor_user_id,
                reason=reason,
                metadata=metadata,
            )
        finally:
            project_lock.release()

    def record_contradiction_if_current(
        self,
        *,
        project_id: str,
        actor_user_id: str,
        reason: str,
        expected_dataset_id: str,
        expected_dataset_version_id: str,
        expected_activation_revision: int,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Mark only the exact still-current active revision contradictory.

        Identity readers use this compare-and-set diagnostic path after an
        optimistic durable read.  It deliberately does not acquire the
        process-local activation lock: a caller may already own the runtime
        store lock while an activation owns the project lock and is waiting to
        publish its cache.  ``BEGIN IMMEDIATE`` plus the exact revision/triple
        comparison keeps the mutation atomic without recreating that lock
        inversion.  All activation operations remain serialized by the
        project lock.
        """
        if not project_id or not actor_user_id or not str(reason or "").strip():
            raise ProjectDatasetActivationStateError(
                "project_id, an authenticated actor, and a contradiction reason are required."
            )
        if (
            not str(expected_dataset_id or "").strip()
            or not str(expected_dataset_version_id or "").strip()
            or not isinstance(expected_activation_revision, int)
            or expected_activation_revision < 1
        ):
            raise ProjectDatasetActivationStateError(
                "An exact active dataset triple and positive activation revision are required."
            )
        return self._record_contradiction_transaction(
            project_id=project_id,
            actor_user_id=actor_user_id,
            reason=reason,
            metadata=metadata,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
            expected_activation_revision=expected_activation_revision,
        )

    def _record_contradiction_transaction(
        self,
        *,
        project_id: str,
        actor_user_id: str,
        reason: str,
        metadata: Dict[str, Any] | None = None,
        expected_dataset_id: str | None = None,
        expected_dataset_version_id: str | None = None,
        expected_activation_revision: int | None = None,
    ) -> Dict[str, Any]:
        connection = None
        try:
            connection = self.database.connect()
            self._begin_immediate(connection)
            current = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            )
            if current is None:
                raise ProjectDatasetActivationStateError(
                    "No durable active dataset selection exists to mark contradictory."
                )
            if expected_activation_revision is not None and not (
                str(current.get("activation_status") or "").casefold() == "active"
                and str(current.get("dataset_id") or "") == expected_dataset_id
                and str(current.get("dataset_version_id") or "")
                == expected_dataset_version_id
                and int(current.get("activation_revision") or 0)
                == expected_activation_revision
            ):
                raise ProjectDatasetActivationConflictError(
                    "The active dataset selection changed before the contradiction diagnostic completed."
                )
            timestamp = now_iso()
            current_metadata = dict(current.get("metadata_json") or {})
            normalized_reason = str(reason).strip()
            changed = not (
                str(current.get("activation_status") or "").casefold()
                == "contradictory"
                and str(current_metadata.get("contradictionReason") or "")
                == normalized_reason
            )
            event = None
            if changed:
                current_metadata.update(metadata or {})
                current_metadata["contradictionReason"] = normalized_reason
                current_metadata["contradictionRecordedAt"] = timestamp
                connection.execute(
                    """
                    UPDATE active_modeling_dataset_versions
                    SET activation_status = 'contradictory', updated_at = ?, metadata_json = ?
                    WHERE project_id = ?
                    """,
                    (timestamp, json_dumps(current_metadata, {}), project_id),
                )
                event = self._write_event(
                    connection,
                    project_id=project_id,
                    dataset_id=str(current.get("dataset_id") or ""),
                    dataset_version_id=str(current.get("dataset_version_id") or ""),
                    activation_revision=int(current.get("activation_revision") or 0),
                    event_type="modeling_dataset_contradiction_detected",
                    event_status="diagnostic",
                    actor_user_id=actor_user_id,
                    metadata={"reason": normalized_reason, **(metadata or {})},
                )
            workflow = self._reconcile_workflow_unavailable(
                connection,
                project_id=project_id,
                reason=normalized_reason,
                validity_status="contradictory",
            )
            updated = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            ) or {}
            connection.commit()
            return {
                "active_selection": updated,
                "activation_event": event,
                "workflow_effective_state": workflow,
                "changed": changed,
            }
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    def deactivate_project(
        self,
        *,
        project_id: str,
        actor_user_id: str,
        reason: str = "The project was deleted.",
    ) -> Dict[str, Any]:
        project_lock = project_dataset_activation_lock(project_id)
        project_lock.acquire()
        connection = None
        try:
            connection = self.database.connect()
            self._begin_immediate(connection)
            active = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            )
            active_links = [
                decode_row(row) or {}
                for row in connection.execute(
                    """
                    SELECT * FROM project_dataset_links
                    WHERE project_id = ? AND link_status = 'active'
                    ORDER BY dataset_id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            timestamp = now_iso()
            selection_changed = bool(
                active
                and str(active.get("activation_status") or "").casefold()
                != "inactive"
            )
            changed = selection_changed or bool(active_links)
            event = None
            next_revision = int((active or {}).get("activation_revision") or 0)
            if selection_changed and active:
                next_revision = int(active.get("activation_revision") or 0) + 1
                connection.execute(
                    """
                    UPDATE active_modeling_dataset_versions
                    SET activation_status = 'inactive', activation_revision = ?, updated_at = ?
                    WHERE project_id = ?
                    """,
                    (next_revision, timestamp, project_id),
                )
            if active_links:
                connection.execute(
                    """
                    UPDATE project_dataset_links
                    SET link_status = 'unlinked', updated_at = ?
                    WHERE project_id = ? AND link_status = 'active'
                    """,
                    (timestamp, project_id),
                )
            if changed:
                self._reconcile_workflow_unavailable(
                    connection,
                    project_id=project_id,
                    reason=reason,
                )
            if changed and (active or active_links):
                event_dataset_id = str(
                    (active or {}).get("dataset_id")
                    or active_links[0].get("dataset_id")
                    or ""
                )
                event = self._write_event(
                    connection,
                    project_id=project_id,
                    dataset_id=event_dataset_id,
                    dataset_version_id=(active or {}).get("dataset_version_id"),
                    activation_revision=next_revision or None,
                    event_type="project_dataset_deactivated",
                    event_status="complete",
                    actor_user_id=actor_user_id,
                    metadata={"reason": reason},
                )
            updated = self._row(
                connection,
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (project_id,),
            )
            connection.commit()
            return {
                "active_selection": updated,
                "activation_event": event,
                "changed": changed,
            }
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
            project_lock.release()
