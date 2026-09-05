from __future__ import annotations

import sqlite3

from typing import Any, Dict, List

from ..db import decode_row, json_dumps, json_loads, now_iso
from .base_repository import BaseRepository


class ProjectRepository(BaseRepository):
    def list(self) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM projects ORDER BY updated_at DESC, project_name")

    def get(self, project_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM projects WHERE project_id = ?", (project_id,))

    def delete(self, project_id: str) -> bool:
        """Delete a project and its project-scoped records through database cascades."""
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
            return cursor.rowcount > 0

    def create(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Create without upsert: a racing request cannot replace an owner.

        Identity conflicts fail atomically before any existing project changes.
        """
        from fastapi import HTTPException
        import sqlite3

        timestamp = record.get("updated_at") or now_iso()
        try:
            self._write(
                """INSERT INTO projects (
                    project_id, project_name, project_type, workflow_type, template_id,
                    status, owner_user_id, created_at, updated_at, metadata_json, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record["project_id"], record.get("project_name") or "Untitled ATLAS Project",
                 record.get("project_type") or "predictive-modeling",
                 record.get("workflow_type") or record.get("project_type") or "predictive-modeling",
                 record.get("template_id"), record.get("status") or "active", record["owner_user_id"],
                 record.get("created_at") or timestamp, timestamp, json_dumps(record.get("metadata_json"), {}),
                 record["created_by"], record["updated_by"]),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Project creation requires a new project identity.") from exc
        return self.get(record["project_id"]) or {}

    def update_locked(self, record: Dict[str, Any], *, connection: sqlite3.Connection) -> Dict[str, Any]:
        """Update only a row authorized under the caller's BEGIN IMMEDIATE lock.

        This method neither starts nor commits a transaction. It cannot create
        a missing row or transfer owner/creator identity, and a lost identity
        guard fails before the surrounding transaction can commit its audit.
        """
        from fastapi import HTTPException

        if not connection.in_transaction:
            raise RuntimeError("Project update requires the authorization write transaction.")
        cursor = connection.execute(
            """UPDATE projects SET
                project_name = ?, project_type = ?, workflow_type = ?, template_id = ?,
                status = ?, updated_at = ?, metadata_json = ?, updated_by = ?
               WHERE project_id = ? AND owner_user_id IS ? AND created_by IS ?""",
            (record.get("project_name") or "Untitled ATLAS Project",
             record.get("project_type") or "predictive-modeling",
             record.get("workflow_type") or record.get("project_type") or "predictive-modeling",
             record.get("template_id"), record.get("status") or "active",
             record.get("updated_at") or now_iso(), json_dumps(record.get("metadata_json"), {}),
             record["updated_by"], record["project_id"], record.get("owner_user_id"), record.get("created_by")),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action on this project.")
        return decode_row(connection.execute(
            "SELECT * FROM projects WHERE project_id = ?", (record["project_id"],),
        ).fetchone()) or {}

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        created_at = record.get("created_at") or timestamp
        self._write(
            """
            INSERT INTO projects (
              project_id, project_name, project_type, workflow_type, template_id,
              status, owner_user_id, created_at, updated_at, metadata_json, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
              project_name = excluded.project_name,
              project_type = excluded.project_type,
              workflow_type = excluded.workflow_type,
              template_id = excluded.template_id,
              status = excluded.status,
              owner_user_id = COALESCE(excluded.owner_user_id, projects.owner_user_id),
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json,
              created_by = COALESCE(projects.created_by, excluded.created_by),
              updated_by = excluded.updated_by
            """,
            (
                record["project_id"],
                record.get("project_name") or "Untitled ATLAS Project",
                record.get("project_type") or "predictive-modeling",
                record.get("workflow_type") or record.get("project_type") or "predictive-modeling",
                record.get("template_id"),
                record.get("status") or "active",
                record.get("owner_user_id"),
                created_at,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
                record.get("created_by") or record.get("owner_user_id"),
                record.get("updated_by") or record.get("owner_user_id"),
            ),
        )
        return self.get(record["project_id"]) or {}

    def upsert_preserving_metadata_keys(
        self,
        record: Dict[str, Any],
        *,
        reserved_metadata_keys: set[str],
    ) -> Dict[str, Any]:
        """Upsert a project without racing server-owned metadata authority.

        Generic project PUTs are assembled from a previously read project
        snapshot.  A dedicated authority writer can commit after that read but
        before the generic upsert.  Acquire the write lock first, reread the
        current metadata inside the transaction, and preserve each reserved
        key from that locked row so the stale snapshot cannot erase it.
        """

        timestamp = record.get("updated_at") or now_iso()
        created_at = record.get("created_at") or timestamp
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current_row = connection.execute(
                "SELECT metadata_json FROM projects WHERE project_id = ?",
                (record["project_id"],),
            ).fetchone()
            current_metadata = (
                json_loads(current_row["metadata_json"], {})
                if current_row is not None
                else {}
            )
            if not isinstance(current_metadata, dict):
                current_metadata = {}
            incoming_metadata = record.get("metadata_json")
            incoming_metadata = (
                dict(incoming_metadata)
                if isinstance(incoming_metadata, dict)
                else {}
            )
            for key in reserved_metadata_keys:
                incoming_metadata.pop(key, None)
                if key in current_metadata:
                    incoming_metadata[key] = current_metadata[key]

            connection.execute(
                """
                INSERT INTO projects (
                  project_id, project_name, project_type, workflow_type,
                  template_id, status, owner_user_id, created_at, updated_at,
                  metadata_json, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                  project_name = excluded.project_name,
                  project_type = excluded.project_type,
                  workflow_type = excluded.workflow_type,
                  template_id = excluded.template_id,
                  status = excluded.status,
                  owner_user_id = COALESCE(excluded.owner_user_id, projects.owner_user_id),
                  updated_at = excluded.updated_at,
                  metadata_json = excluded.metadata_json,
                  created_by = COALESCE(projects.created_by, excluded.created_by),
                  updated_by = excluded.updated_by
                """,
                (
                    record["project_id"],
                    record.get("project_name") or "Untitled ATLAS Project",
                    record.get("project_type") or "predictive-modeling",
                    record.get("workflow_type")
                    or record.get("project_type")
                    or "predictive-modeling",
                    record.get("template_id"),
                    record.get("status") or "active",
                    record.get("owner_user_id"),
                    created_at,
                    timestamp,
                    json_dumps(incoming_metadata, {}),
                    record.get("created_by") or record.get("owner_user_id"),
                    record.get("updated_by") or record.get("owner_user_id"),
                ),
            )
            saved = decode_row(
                connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?",
                    (record["project_id"],),
                ).fetchone()
            ) or {}
            connection.commit()
            return saved
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def ensure(self, project_id: str, defaults: Dict[str, Any] | None = None) -> Dict[str, Any]:
        existing = self.get(project_id)
        if existing:
            return existing
        values = defaults or {}
        return self.upsert(
            {
                "project_id": project_id,
                "project_name": values.get("project_name") or "Recovered ATLAS Project",
                "project_type": values.get("project_type") or "predictive-modeling",
                "workflow_type": values.get("workflow_type") or values.get("project_type") or "predictive-modeling",
                "status": values.get("status") or "active",
                "owner_user_id": values.get("owner_user_id"),
                "created_by": values.get("created_by") or values.get("owner_user_id"),
                "updated_by": values.get("updated_by") or values.get("owner_user_id"),
                "metadata_json": {"recoveredFromCompatibilityStore": True, **(values.get("metadata_json") or {})},
            }
        )

    def get_workflow_state(self, project_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM workflow_state WHERE project_id = ?", (project_id,))

    def upsert_workflow_state(self, project_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        self.ensure(project_id)
        self._write(
            """
            INSERT INTO workflow_state (
              project_id, current_step_id, completed_steps_json, workflow_status_json,
              step_evidence_status_json, updated_at, completed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
              current_step_id = excluded.current_step_id,
              completed_steps_json = excluded.completed_steps_json,
              workflow_status_json = excluded.workflow_status_json,
              step_evidence_status_json = excluded.step_evidence_status_json,
              updated_at = excluded.updated_at,
              completed_by = excluded.completed_by
            """,
            (
                project_id,
                record.get("current_step_id"),
                json_dumps(record.get("completed_steps_json"), []),
                json_dumps(record.get("workflow_status_json"), {}),
                json_dumps(record.get("step_evidence_status_json"), {}),
                record.get("updated_at") or now_iso(),
                record.get("completed_by"),
            ),
        )
        return self.get_workflow_state(project_id) or {}

    def upsert_workflow_history(
        self,
        project_id: str,
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist browser-reported history without accepting lineage authority.

        Effective completion and canonical dataset identity are calculated by
        backend activation/artifact reconciliation.  A browser save may append
        historical completion, but it cannot replace those server-owned fields.
        ``BEGIN IMMEDIATE`` also prevents a racing browser save from clobbering
        an activation transaction that just reconciled the workflow.
        """
        self.ensure(project_id)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = decode_row(
                connection.execute(
                    "SELECT * FROM workflow_state WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
            ) or {}
            previous_completed = [
                str(step)
                for step in (previous.get("completed_steps_json") or [])
                if str(step)
            ]
            incoming_completed = [
                str(step)
                for step in (record.get("completed_steps_json") or [])
                if str(step)
            ]
            historical_completed = list(
                dict.fromkeys([*previous_completed, *incoming_completed])
            )

            previous_status = dict(previous.get("workflow_status_json") or {})
            incoming_status = dict(record.get("workflow_status_json") or {})
            server_fields = {
                "datasetIdentity",
                "hasDataset",
                "historicalCompletedSteps",
                "effectiveCompletedSteps",
                "effectiveCurrentStepId",
                "effectiveSteps",
                "identityValidity",
                # Overall completion is server authority.  A browser may
                # append historical step observations, but it cannot promote
                # the project by posting ``status = complete``.
                "status",
                "steps",
            }
            workflow_status = {
                **previous_status,
                **{
                    key: value
                    for key, value in incoming_status.items()
                    if key not in server_fields
                },
            }
            workflow_status["historicalCompletedSteps"] = historical_completed
            # Browser status labels are presentation history, not durable
            # completion evidence. Derive this audit map only from the append-
            # only completed-step list so an omitted step cannot be smuggled in
            # as `workflowStatus.steps.stepXX = complete`.
            workflow_status["steps"] = {
                step: "complete" for step in historical_completed
            }

            # A legacy workflow row has no server-derived effective view.  Fail
            # closed until an explicit durable activation reconciles it.
            if not isinstance(previous_status.get("identityValidity"), dict):
                independent = [
                    step for step in historical_completed if step == "step00"
                ]
                effective_steps = {
                    step: {
                        "effectiveStatus": (
                            "complete" if step in independent else "pending"
                        ),
                        "lineageStatus": (
                            "current" if step in independent else "missing"
                        ),
                        "reason": (
                            "Identity-independent project context remains current."
                            if step in independent
                            else "No exact durable active Dataset Library version has reconciled this workflow."
                        ),
                        "artifactIds": [],
                    }
                    for step in historical_completed
                }
                workflow_status.update(
                    {
                        "datasetIdentity": None,
                        "hasDataset": False,
                        "effectiveCompletedSteps": independent,
                        "effectiveCurrentStepId": "step01",
                        "effectiveSteps": effective_steps,
                        "identityValidity": {
                            "status": "missing",
                            "reason": (
                                "No exact durable active Dataset Library version "
                                "has reconciled this workflow."
                            ),
                            "historicalCompletionPreserved": True,
                        },
                    }
                )
            else:
                for key in server_fields - {"historicalCompletedSteps", "steps"}:
                    if key in previous_status:
                        workflow_status[key] = previous_status[key]

            timestamp = record.get("updated_at") or now_iso()
            connection.execute(
                """
                INSERT INTO workflow_state (
                  project_id, current_step_id, completed_steps_json,
                  workflow_status_json, step_evidence_status_json, updated_at,
                  completed_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                  current_step_id = excluded.current_step_id,
                  completed_steps_json = excluded.completed_steps_json,
                  workflow_status_json = excluded.workflow_status_json,
                  step_evidence_status_json = excluded.step_evidence_status_json,
                  updated_at = excluded.updated_at,
                  completed_by = excluded.completed_by
                """,
                (
                    project_id,
                    record.get("current_step_id"),
                    json_dumps(historical_completed, []),
                    json_dumps(workflow_status, {}),
                    json_dumps(
                        record.get("step_evidence_status_json")
                        or previous.get("step_evidence_status_json"),
                        {},
                    ),
                    timestamp,
                    record.get("completed_by"),
                ),
            )
            saved = decode_row(
                connection.execute(
                    "SELECT * FROM workflow_state WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
            ) or {}
            connection.commit()
            return saved
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
