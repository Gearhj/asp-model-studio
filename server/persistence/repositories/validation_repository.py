from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class ValidationRepository(BaseRepository):
    def list_cases(
        self,
        *,
        status: str | None = None,
        assigned_validator_user_id: str | None = None,
        project_id: str | None = None,
        limit: int = 250,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM validation_cases WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if assigned_validator_user_id:
            query += " AND assigned_validator_user_id = ?"
            params.append(assigned_validator_user_id)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return self._many(query, params)

    def get_case(self, validation_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM validation_cases WHERE validation_id = ?", (validation_id,))

    def get_case_by_project(self, project_id: str) -> Dict[str, Any] | None:
        return self._one(
            "SELECT * FROM validation_cases WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        )

    def upsert_case(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO validation_cases (
              validation_id, project_id, asset_type, validation_template_id, status,
              business_status_label, risk_tier, assigned_validator_user_id,
              assigned_validator_name, submitted_by, submitted_at, review_started_at,
              review_completed_at, final_disposition, final_score, next_review_date,
              summary, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(validation_id) DO UPDATE SET
              asset_type = excluded.asset_type,
              validation_template_id = excluded.validation_template_id,
              status = excluded.status,
              business_status_label = excluded.business_status_label,
              risk_tier = excluded.risk_tier,
              assigned_validator_user_id = excluded.assigned_validator_user_id,
              assigned_validator_name = excluded.assigned_validator_name,
              submitted_by = COALESCE(validation_cases.submitted_by, excluded.submitted_by),
              submitted_at = COALESCE(validation_cases.submitted_at, excluded.submitted_at),
              review_started_at = COALESCE(excluded.review_started_at, validation_cases.review_started_at),
              review_completed_at = COALESCE(excluded.review_completed_at, validation_cases.review_completed_at),
              final_disposition = excluded.final_disposition,
              final_score = excluded.final_score,
              next_review_date = excluded.next_review_date,
              summary = excluded.summary,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["validation_id"],
                record["project_id"],
                record.get("asset_type") or "custom_workflow",
                record.get("validation_template_id") or "generic",
                record.get("status") or "not_submitted",
                record.get("business_status_label") or "Not submitted",
                record.get("risk_tier"),
                record.get("assigned_validator_user_id"),
                record.get("assigned_validator_name"),
                record.get("submitted_by"),
                record.get("submitted_at"),
                record.get("review_started_at"),
                record.get("review_completed_at"),
                record.get("final_disposition"),
                record.get("final_score"),
                record.get("next_review_date"),
                record.get("summary"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_case(record["validation_id"]) or {}

    def list_checklist(self, validation_id: str) -> List[Dict[str, Any]]:
        return self._many(
            "SELECT * FROM validation_checklist_items WHERE validation_id = ? ORDER BY sort_order, category, item_label",
            (validation_id,),
        )

    def upsert_checklist_item(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO validation_checklist_items (
              checklist_item_id, validation_id, project_id, template_id, category, item_key,
              item_label, item_description, status, result, evidence_reference,
              reviewer_notes, sort_order, updated_by, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(validation_id, item_key) DO UPDATE SET
              status = excluded.status,
              result = excluded.result,
              evidence_reference = excluded.evidence_reference,
              reviewer_notes = excluded.reviewer_notes,
              updated_by = excluded.updated_by,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["checklist_item_id"],
                record["validation_id"],
                record["project_id"],
                record.get("template_id") or "generic",
                record.get("category") or "General",
                record["item_key"],
                record.get("item_label") or record["item_key"],
                record.get("item_description"),
                record.get("status") or "not_reviewed",
                record.get("result"),
                record.get("evidence_reference"),
                record.get("reviewer_notes"),
                int(record.get("sort_order") or 0),
                record.get("updated_by"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one(
            "SELECT * FROM validation_checklist_items WHERE validation_id = ? AND item_key = ?",
            (record["validation_id"], record["item_key"]),
        ) or {}

    def list_findings(self, validation_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM validation_findings WHERE validation_id = ? ORDER BY updated_at DESC", (validation_id,))

    def upsert_finding(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO validation_findings (
              finding_id, validation_id, project_id, category, severity, status, title,
              description, evidence_reference, remediation_owner, remediation_due_date,
              validator_notes, management_response_required, created_by, created_at,
              updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(finding_id) DO UPDATE SET
              category = excluded.category,
              severity = excluded.severity,
              status = excluded.status,
              title = excluded.title,
              description = excluded.description,
              evidence_reference = excluded.evidence_reference,
              remediation_owner = excluded.remediation_owner,
              remediation_due_date = excluded.remediation_due_date,
              validator_notes = excluded.validator_notes,
              management_response_required = excluded.management_response_required,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["finding_id"],
                record["validation_id"],
                record["project_id"],
                record.get("category") or "General",
                record.get("severity") or "Medium",
                record.get("status") or "open",
                record.get("title") or "Validation finding",
                record.get("description"),
                record.get("evidence_reference"),
                record.get("remediation_owner"),
                record.get("remediation_due_date"),
                record.get("validator_notes"),
                1 if record.get("management_response_required") else 0,
                record.get("created_by"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM validation_findings WHERE finding_id = ?", (record["finding_id"],)) or {}

    def list_challenges(self, validation_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM validation_challenges WHERE validation_id = ? ORDER BY updated_at DESC", (validation_id,))

    def upsert_challenge(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO validation_challenges (
              challenge_id, validation_id, project_id, challenge_type, status, title,
              challenge_question, validator_position, severity, due_date, created_by,
              created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(challenge_id) DO UPDATE SET
              challenge_type = excluded.challenge_type,
              status = excluded.status,
              title = excluded.title,
              challenge_question = excluded.challenge_question,
              validator_position = excluded.validator_position,
              severity = excluded.severity,
              due_date = excluded.due_date,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["challenge_id"],
                record["validation_id"],
                record["project_id"],
                record.get("challenge_type") or "methodology",
                record.get("status") or "open",
                record.get("title") or "Validator challenge",
                record.get("challenge_question"),
                record.get("validator_position"),
                record.get("severity") or "Medium",
                record.get("due_date"),
                record.get("created_by"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM validation_challenges WHERE challenge_id = ?", (record["challenge_id"],)) or {}

    def list_responses(self, validation_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM validation_responses WHERE validation_id = ? ORDER BY created_at DESC", (validation_id,))

    def upsert_response(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO validation_responses (
              response_id, challenge_id, validation_id, project_id, response_text,
              response_type, status, responder_user_id, responder_name,
              evidence_reference, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(response_id) DO UPDATE SET
              response_text = excluded.response_text,
              response_type = excluded.response_type,
              status = excluded.status,
              evidence_reference = excluded.evidence_reference,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["response_id"],
                record["challenge_id"],
                record["validation_id"],
                record["project_id"],
                record.get("response_text") or "",
                record.get("response_type") or "owner_response",
                record.get("status") or "submitted",
                record.get("responder_user_id"),
                record.get("responder_name"),
                record.get("evidence_reference"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM validation_responses WHERE response_id = ?", (record["response_id"],)) or {}

    def list_approvals(self, validation_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM validation_approvals WHERE validation_id = ? ORDER BY created_at DESC", (validation_id,))

    def upsert_approval(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO validation_approvals (
              approval_id, validation_id, project_id, approver_user_id, approver_name,
              approver_role, decision, decision_rationale, conditions_json,
              approved_at, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(approval_id) DO UPDATE SET
              decision = excluded.decision,
              decision_rationale = excluded.decision_rationale,
              conditions_json = excluded.conditions_json,
              approved_at = excluded.approved_at,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["approval_id"],
                record["validation_id"],
                record["project_id"],
                record.get("approver_user_id"),
                record.get("approver_name"),
                record.get("approver_role"),
                record.get("decision") or "approved",
                record.get("decision_rationale"),
                json_dumps(record.get("conditions_json"), []),
                record.get("approved_at"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM validation_approvals WHERE approval_id = ?", (record["approval_id"],)) or {}

    def list_events(self, validation_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM validation_case_events WHERE validation_id = ? ORDER BY created_at DESC", (validation_id,))

    def create_event(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO validation_case_events (
              event_id, validation_id, project_id, event_type, title, summary,
              user_id, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["event_id"],
                record["validation_id"],
                record["project_id"],
                record["event_type"],
                record.get("title") or record["event_type"].replace(".", " ").title(),
                record.get("summary"),
                record.get("user_id"),
                record.get("created_at") or now_iso(),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM validation_case_events WHERE event_id = ?", (record["event_id"],)) or {}
