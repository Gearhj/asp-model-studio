from __future__ import annotations

from typing import Any, Dict, Literal

from pydantic import BaseModel, Field


ValidationStatus = Literal[
    "not_submitted",
    "submitted",
    "in_review",
    "returned",
    "remediation",
    "approved",
    "approved_with_conditions",
    "rejected",
    "withdrawn",
]

STATUS_LABELS: Dict[str, str] = {
    "not_submitted": "Not submitted",
    "submitted": "Submitted for independent validation",
    "in_review": "Independent validation in progress",
    "returned": "Returned to owner",
    "remediation": "Remediation required",
    "approved": "Approved by validation",
    "approved_with_conditions": "Approved with conditions",
    "rejected": "Rejected by validation",
    "withdrawn": "Withdrawn",
}

OPEN_FINDING_STATUSES = {"open", "in_remediation", "returned"}


def label_status(status: str | None) -> str:
    return STATUS_LABELS.get(str(status or "not_submitted"), str(status or "not_submitted").replace("_", " ").title())


class SubmitValidationRequest(BaseModel):
    assigned_validator_user_id: str | None = None
    assigned_validator_name: str | None = None
    risk_tier: str | None = None
    summary: str | None = None
    next_review_date: str | None = None


class CaseUpdateRequest(BaseModel):
    status: str | None = None
    assigned_validator_user_id: str | None = None
    assigned_validator_name: str | None = None
    risk_tier: str | None = None
    summary: str | None = None
    final_score: float | None = None
    final_disposition: str | None = None
    next_review_date: str | None = None
    metadata_json: Dict[str, Any] | None = None


class ChecklistUpdateRequest(BaseModel):
    status: str = "not_reviewed"
    result: str | None = None
    evidence_reference: str | None = None
    reviewer_notes: str | None = None


class FindingRequest(BaseModel):
    category: str = "General"
    severity: str = "Medium"
    status: str = "open"
    title: str = Field(default="Validation finding", min_length=1)
    description: str | None = None
    evidence_reference: str | None = None
    remediation_owner: str | None = None
    remediation_due_date: str | None = None
    validator_notes: str | None = None
    management_response_required: bool = False
    metadata_json: Dict[str, Any] | None = None


class ChallengeRequest(BaseModel):
    challenge_type: str = "methodology"
    status: str = "open"
    title: str = Field(default="Validator challenge", min_length=1)
    challenge_question: str | None = None
    validator_position: str | None = None
    severity: str = "Medium"
    due_date: str | None = None
    metadata_json: Dict[str, Any] | None = None


class ResponseRequest(BaseModel):
    response_text: str = Field(min_length=1)
    response_type: str = "owner_response"
    status: str = "submitted"
    evidence_reference: str | None = None
    metadata_json: Dict[str, Any] | None = None


class ApprovalRequest(BaseModel):
    decision: str = "approved"
    decision_rationale: str | None = None
    conditions_json: list[Dict[str, Any]] | None = None
    next_review_date: str | None = None
    final_score: float | None = None
    metadata_json: Dict[str, Any] | None = None
