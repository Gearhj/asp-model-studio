from __future__ import annotations

import uuid
from collections import Counter
from typing import Any, Dict, List, Mapping

from fastapi import HTTPException

from ..persistence.db import json_loads, now_iso
from ..persistence.service import get_persistence_service
from ..registry.registry_service import get_registry_service
from .schemas import OPEN_FINDING_STATUSES, label_status
from .validation_templates import checklist_items, template_for_project


VALIDATOR_ROLES = {"admin", "validator", "model_manager", "manager"}
OWNER_ROLES = {"admin", "data_scientist", "model_owner", "model_manager", "manager", "validator"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _user_id(user: Mapping[str, Any]) -> str | None:
    return user.get("userId") or user.get("user_id")


def _user_name(user: Mapping[str, Any]) -> str:
    return str(user.get("displayName") or user.get("display_name") or _user_id(user) or "ATLAS user")


def _role(user: Mapping[str, Any]) -> str:
    return str(user.get("role") or "")


def _require_role(user: Mapping[str, Any], roles: set[str], action: str) -> None:
    if _role(user) not in roles:
        raise HTTPException(status_code=403, detail=f"{action} requires one of these roles: {', '.join(sorted(roles))}.")


def _metadata(record: Mapping[str, Any] | None) -> Dict[str, Any]:
    if not record:
        return {}
    return json_loads(record.get("metadata_json"), {})


class ValidationService:
    def __init__(self, persistence: Any | None = None) -> None:
        self.persistence = persistence or get_persistence_service()
        self.validation = self.persistence.validation
        self.registry_service: Any | None = None

    def _registry_detail(self, project_id: str) -> Dict[str, Any] | None:
        registry = self.registry_service or get_registry_service()
        return registry.get_asset(project_id)

    def _project(self, project_id: str) -> Dict[str, Any]:
        project = self.persistence.projects.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project was not found in the ATLAS persistence database.")
        return project

    def _audit(self, case: Mapping[str, Any], user: Mapping[str, Any], action_type: str, title: str, summary: str | None = None) -> None:
        self.persistence.audit.create(
            {
                "audit_id": _id("audit"),
                "project_id": case["project_id"],
                "user_id": _user_id(user),
                "action_type": action_type,
                "entity_type": "validation_case",
                "entity_id": case["validation_id"],
                "title": title,
                "summary": summary,
                "created_at": now_iso(),
                "metadata_json": {"validation_id": case["validation_id"], "status": case.get("status")},
            }
        )

    def _event(self, case: Mapping[str, Any], user: Mapping[str, Any], event_type: str, title: str, summary: str | None = None, metadata: Mapping[str, Any] | None = None) -> None:
        self.validation.create_event(
            {
                "event_id": _id("vce"),
                "validation_id": case["validation_id"],
                "project_id": case["project_id"],
                "event_type": event_type,
                "title": title,
                "summary": summary,
                "user_id": _user_id(user),
                "created_at": now_iso(),
                "metadata_json": dict(metadata or {}),
            }
        )

    def _decision(self, case: Mapping[str, Any], user: Mapping[str, Any], decision_type: str, title: str, summary: str | None = None, status: str = "recorded") -> None:
        self.persistence.decisions.upsert(
            {
                "decision_id": f"validation:{case['validation_id']}:{decision_type}",
                "project_id": case["project_id"],
                "decision_type": f"validation_{decision_type}",
                "title": title,
                "summary": summary,
                "status": status,
                "owner": case.get("assigned_validator_name"),
                "created_by": _user_id(user),
                "created_at": case.get("created_at") or now_iso(),
                "updated_at": now_iso(),
                "payload_json": {"validation_id": case["validation_id"], "validation_status": case.get("status")},
            }
        )

    def _seed_checklist(self, case: Mapping[str, Any], project: Mapping[str, Any], user: Mapping[str, Any]) -> None:
        template = template_for_project(dict(project))
        existing = self.validation.list_checklist(str(case["validation_id"]))
        if existing:
            return
        for item in checklist_items(template):
            self.validation.upsert_checklist_item(
                {
                    "checklist_item_id": _id("vci"),
                    "validation_id": case["validation_id"],
                    "project_id": case["project_id"],
                    **item,
                    "status": "not_reviewed",
                    "updated_by": _user_id(user),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
            )

    def create_or_submit_case(self, project_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        _require_role(user, OWNER_ROLES, "Submitting validation")
        project = self._project(project_id)
        existing = self.validation.get_case_by_project(project_id)
        template = template_for_project(project)
        status = "submitted"
        timestamp = now_iso()
        case = self.validation.upsert_case(
            {
                **(existing or {}),
                "validation_id": (existing or {}).get("validation_id") or _id("val"),
                "project_id": project_id,
                "asset_type": project.get("project_type") or project.get("workflow_type") or "custom_workflow",
                "validation_template_id": template["template_id"],
                "status": status,
                "business_status_label": label_status(status),
                "risk_tier": payload.get("risk_tier") or (existing or {}).get("risk_tier"),
                "assigned_validator_user_id": payload.get("assigned_validator_user_id") or (existing or {}).get("assigned_validator_user_id"),
                "assigned_validator_name": payload.get("assigned_validator_name") or (existing or {}).get("assigned_validator_name"),
                "submitted_by": (existing or {}).get("submitted_by") or _user_id(user),
                "submitted_at": (existing or {}).get("submitted_at") or timestamp,
                "summary": payload.get("summary") or (existing or {}).get("summary") or "Submitted for independent validation.",
                "next_review_date": payload.get("next_review_date") or (existing or {}).get("next_review_date"),
                "metadata_json": {**_metadata(existing), "submitted_from": "validation_center"},
                "created_at": (existing or {}).get("created_at") or timestamp,
                "updated_at": timestamp,
            }
        )
        self._seed_checklist(case, project, user)
        self._event(case, user, "validation.submitted", "Validation submitted", "Project entered the independent validation queue.")
        self._audit(case, user, "validation.submitted", "Validation submitted", "Project entered the independent validation queue.")
        self._decision(case, user, "submitted", "Validation submitted", "Independent validation was requested.", "submitted")
        return self.case_detail(str(case["validation_id"]))

    def start_review(self, validation_id: str, user: Mapping[str, Any]) -> Dict[str, Any]:
        _require_role(user, VALIDATOR_ROLES, "Starting validation review")
        case = self._case(validation_id)
        updated = self.validation.upsert_case(
            {
                **case,
                "status": "in_review",
                "business_status_label": label_status("in_review"),
                "review_started_at": case.get("review_started_at") or now_iso(),
                "updated_at": now_iso(),
            }
        )
        self._event(updated, user, "validation.review_started", "Independent review started")
        self._audit(updated, user, "validation.review_started", "Independent review started")
        self._decision(updated, user, "review_started", "Independent review started", "Validator started case review.", "in_review")
        return self.case_detail(validation_id)

    def update_case(self, validation_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        _require_role(user, VALIDATOR_ROLES, "Updating validation case")
        case = self._case(validation_id)
        status = str(payload.get("status") or case.get("status") or "submitted")
        updated = self.validation.upsert_case(
            {
                **case,
                **{key: value for key, value in payload.items() if value is not None},
                "status": status,
                "business_status_label": label_status(status),
                "updated_at": now_iso(),
                "metadata_json": {**_metadata(case), **dict(payload.get("metadata_json") or {})},
            }
        )
        self._event(updated, user, "validation.case_updated", "Validation case updated", f"Status is {label_status(status)}.")
        self._audit(updated, user, "validation.case_updated", "Validation case updated", f"Status is {label_status(status)}.")
        return self.case_detail(validation_id)

    def _case(self, validation_id: str) -> Dict[str, Any]:
        case = self.validation.get_case(validation_id)
        if not case:
            raise HTTPException(status_code=404, detail="Validation case was not found.")
        return case

    def project_lookup(self, project_id: str) -> Dict[str, Any]:
        project = self._project(project_id)
        case = self.validation.get_case_by_project(project_id)
        registry = self._registry_detail(project_id)
        return {"project": project, "case": case, "registry": registry, "eligible": True}

    def queue(self, filters: Mapping[str, Any]) -> Dict[str, Any]:
        cases = self.validation.list_cases(
            status=filters.get("status"),
            assigned_validator_user_id=filters.get("assigned_validator_user_id"),
            project_id=filters.get("project_id"),
            limit=int(filters.get("limit") or 250),
        )
        enriched = []
        for case in cases:
            project = self.persistence.projects.get(case["project_id"]) or {}
            registry = self._registry_detail(case["project_id"]) or {}
            findings = self.validation.list_findings(case["validation_id"])
            open_findings = [item for item in findings if str(item.get("status")) in OPEN_FINDING_STATUSES]
            enriched.append(
                {
                    **case,
                    "project_name": project.get("project_name") or case["project_id"],
                    "workflow_type": project.get("workflow_type"),
                    "asset": (registry.get("asset") or {}),
                    "open_finding_count": len(open_findings),
                    "finding_count": len(findings),
                }
            )
        return {"items": enriched, "total": len(enriched)}

    def case_detail(self, validation_id: str) -> Dict[str, Any]:
        case = self._case(validation_id)
        project = self.persistence.projects.get(case["project_id"]) or {}
        registry = self._registry_detail(case["project_id"])
        checklist = self.validation.list_checklist(validation_id)
        findings = self.validation.list_findings(validation_id)
        challenges = self.validation.list_challenges(validation_id)
        responses = self.validation.list_responses(validation_id)
        responses_by_challenge: Dict[str, List[Dict[str, Any]]] = {}
        for response in responses:
            responses_by_challenge.setdefault(response["challenge_id"], []).append(response)
        challenge_items = [{**challenge, "responses": responses_by_challenge.get(challenge["challenge_id"], [])} for challenge in challenges]
        approvals = self.validation.list_approvals(validation_id)
        events = self.validation.list_events(validation_id)
        status_counts = Counter(item.get("status") for item in checklist)
        open_findings = [item for item in findings if str(item.get("status")) in OPEN_FINDING_STATUSES]
        return {
            "case": case,
            "project": project,
            "registry": registry,
            "checklist": checklist,
            "findings": findings,
            "challenges": challenge_items,
            "responses": responses,
            "approvals": approvals,
            "events": events,
            "summary": {
                "checklist_total": len(checklist),
                "checklist_passed": status_counts.get("passed", 0),
                "checklist_failed": status_counts.get("failed", 0),
                "open_finding_count": len(open_findings),
                "challenge_count": len(challenges),
                "approval_count": len(approvals),
            },
        }

    def update_checklist(self, validation_id: str, item_key: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        _require_role(user, VALIDATOR_ROLES, "Updating validation checklist")
        case = self._case(validation_id)
        existing = next((item for item in self.validation.list_checklist(validation_id) if item["item_key"] == item_key), None)
        if not existing:
            raise HTTPException(status_code=404, detail="Checklist item was not found.")
        self.validation.upsert_checklist_item({**existing, **dict(payload), "updated_by": _user_id(user), "updated_at": now_iso()})
        self._event(case, user, "validation.checklist_updated", "Checklist item updated", existing.get("item_label"))
        self._audit(case, user, "validation.checklist_updated", "Checklist item updated", existing.get("item_label"))
        return self.case_detail(validation_id)

    def upsert_finding(self, validation_id: str, payload: Mapping[str, Any], user: Mapping[str, Any], finding_id: str | None = None) -> Dict[str, Any]:
        _require_role(user, VALIDATOR_ROLES, "Managing validation findings")
        case = self._case(validation_id)
        existing = self._find_by_id(self.validation.list_findings(validation_id), "finding_id", finding_id) if finding_id else {}
        finding = self.validation.upsert_finding(
            {
                **existing,
                **dict(payload),
                "finding_id": finding_id or _id("vf"),
                "validation_id": validation_id,
                "project_id": case["project_id"],
                "created_by": existing.get("created_by") or _user_id(user),
                "created_at": existing.get("created_at") or now_iso(),
                "updated_at": now_iso(),
            }
        )
        self._event(case, user, "validation.finding_saved", "Validation finding saved", finding.get("title"))
        self._audit(case, user, "validation.finding_saved", "Validation finding saved", finding.get("title"))
        return self.case_detail(validation_id)

    def upsert_challenge(self, validation_id: str, payload: Mapping[str, Any], user: Mapping[str, Any], challenge_id: str | None = None) -> Dict[str, Any]:
        _require_role(user, VALIDATOR_ROLES, "Managing validation challenges")
        case = self._case(validation_id)
        existing = self._find_by_id(self.validation.list_challenges(validation_id), "challenge_id", challenge_id) if challenge_id else {}
        challenge = self.validation.upsert_challenge(
            {
                **existing,
                **dict(payload),
                "challenge_id": challenge_id or _id("vc"),
                "validation_id": validation_id,
                "project_id": case["project_id"],
                "created_by": existing.get("created_by") or _user_id(user),
                "created_at": existing.get("created_at") or now_iso(),
                "updated_at": now_iso(),
            }
        )
        self._event(case, user, "validation.challenge_saved", "Validator challenge saved", challenge.get("title"))
        self._audit(case, user, "validation.challenge_saved", "Validator challenge saved", challenge.get("title"))
        return self.case_detail(validation_id)

    def add_response(self, validation_id: str, challenge_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        _require_role(user, OWNER_ROLES, "Responding to validation challenge")
        case = self._case(validation_id)
        if not self._find_by_id(self.validation.list_challenges(validation_id), "challenge_id", challenge_id):
            raise HTTPException(status_code=404, detail="Validation challenge was not found.")
        self.validation.upsert_response(
            {
                **dict(payload),
                "response_id": _id("vr"),
                "challenge_id": challenge_id,
                "validation_id": validation_id,
                "project_id": case["project_id"],
                "responder_user_id": _user_id(user),
                "responder_name": _user_name(user),
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
        self._event(case, user, "validation.response_submitted", "Challenge response submitted")
        self._audit(case, user, "validation.response_submitted", "Challenge response submitted")
        return self.case_detail(validation_id)

    def approve(self, validation_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        _require_role(user, VALIDATOR_ROLES, "Approving validation case")
        case = self._case(validation_id)
        # FND-005 (segregation of duties): the identity of record for "who
        # submitted this case" is validation_cases.submitted_by, set once in
        # create_or_submit_case() and never overwritten thereafter. The
        # project owner is a separate identity (projects.owner_user_id), but
        # the required rule only restricts the owner "if they are also the
        # submitter" -- i.e. exactly the case already covered by comparing
        # the approver against submitted_by. No separate owner lookup or
        # ownership field is needed. This check applies uniformly regardless
        # of role (including admin/validator/manager): there is no existing
        # policy that lets any role bypass being a different person from the
        # submitter, so none is introduced here -- only role-based access to
        # approve() at all is unchanged, per existing policy.
        approver_id = _user_id(user)
        submitter_id = case.get("submitted_by")
        if approver_id and submitter_id and approver_id == submitter_id:
            self._event(
                case,
                user,
                "validation.self_approval_denied",
                "Self-approval denied",
                "Approval was attempted by the same person who submitted this validation case.",
            )
            self._audit(
                case,
                user,
                "validation.self_approval_denied",
                "Self-approval denied",
                "Approval was attempted by the same person who submitted this validation case.",
            )
            raise HTTPException(
                status_code=403,
                detail="This validation case must be approved by another qualified validator.",
            )
        decision = str(payload.get("decision") or "approved")
        status = "approved_with_conditions" if decision == "approved_with_conditions" else "approved" if decision == "approved" else "rejected"
        timestamp = now_iso()
        self.validation.upsert_approval(
            {
                **dict(payload),
                "approval_id": _id("va"),
                "validation_id": validation_id,
                "project_id": case["project_id"],
                "approver_user_id": _user_id(user),
                "approver_name": _user_name(user),
                "approver_role": _role(user),
                "approved_at": timestamp,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
        updated = self.validation.upsert_case(
            {
                **case,
                "status": status,
                "business_status_label": label_status(status),
                "final_disposition": decision,
                "final_score": payload.get("final_score") if payload.get("final_score") is not None else case.get("final_score"),
                "next_review_date": payload.get("next_review_date") or case.get("next_review_date"),
                "review_completed_at": timestamp,
                "updated_at": timestamp,
            }
        )
        self._event(updated, user, "validation.approval_recorded", "Validation disposition recorded", label_status(status))
        self._audit(updated, user, "validation.approval_recorded", "Validation disposition recorded", label_status(status))
        self._decision(updated, user, "approval", "Validation disposition recorded", payload.get("decision_rationale"), status)
        return self.case_detail(validation_id)

    @staticmethod
    def _find_by_id(items: List[Dict[str, Any]], key: str, value: str | None) -> Dict[str, Any]:
        if not value:
            return {}
        return next((item for item in items if item.get(key) == value), {})

    def summary(self) -> Dict[str, Any]:
        cases = self.validation.list_cases(limit=500)
        status_counts = Counter(case.get("status") for case in cases)
        open_findings = 0
        for case in cases:
            open_findings += sum(1 for item in self.validation.list_findings(case["validation_id"]) if str(item.get("status")) in OPEN_FINDING_STATUSES)
        return {
            "total_cases": len(cases),
            "submitted": status_counts.get("submitted", 0),
            "in_review": status_counts.get("in_review", 0),
            "returned": status_counts.get("returned", 0),
            "approved": status_counts.get("approved", 0) + status_counts.get("approved_with_conditions", 0),
            "rejected": status_counts.get("rejected", 0),
            "open_findings": open_findings,
            "cases_by_status": dict(status_counts),
        }


_validation_service: ValidationService | None = None


def get_validation_service() -> ValidationService:
    global _validation_service
    if _validation_service is None:
        _validation_service = ValidationService()
    return _validation_service
