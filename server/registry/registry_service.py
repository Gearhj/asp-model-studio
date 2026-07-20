from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ..persistence.db import now_iso
from ..persistence.service import PersistenceService, get_persistence_service
from .schemas import RegistryAction, RegistryAsset, TRANSPORTATION_REQUIRED_EVIDENCE
from ..validation.schemas import OPEN_FINDING_STATUSES, label_status


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_STATUS_CONTRACT_PATH = REPOSITORY_ROOT / "shared" / "evidence_status_contract.json"
SUCCESS_STATUSES = {"complete", "completed", "success", "succeeded", "ready", "approved", "passed"}
FAILURE_STATUSES = {"failed", "failure", "error", "rejected", "blocked"}
TERMINAL_LIFECYCLES = {"Rejected", "Retired"}


def _load_evidence_contract() -> Dict[str, Dict[str, Any]]:
    with EVIDENCE_STATUS_CONTRACT_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


EVIDENCE_STATUS_CONTRACT = _load_evidence_contract()
EVIDENCE_WEIGHTS = {
    status: float(definition["weight"])
    for status, definition in EVIDENCE_STATUS_CONTRACT.items()
}
EVIDENCE_ALIASES = {
    str(alias).strip().lower(): status
    for status, definition in EVIDENCE_STATUS_CONTRACT.items()
    for alias in definition.get("aliases", [])
}


def _mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> List[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _status_key(value: Any) -> str:
    return _text(value).replace("-", "_").replace(" ", "_").lower()


def _parse_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _latest_timestamp(values: Iterable[Any]) -> str | None:
    candidates = [(_parse_datetime(value), _text(value)) for value in values]
    valid = [(parsed, original) for parsed, original in candidates if parsed is not None]
    return max(valid, key=lambda pair: pair[0])[1] if valid else None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _title_status(value: Any, fallback: str) -> str:
    text = _text(value)
    if not text:
        return fallback
    return text.replace("_", " ").replace("-", " ").title()


def normalize_evidence_status(value: Any) -> str:
    return EVIDENCE_ALIASES.get(_status_key(value), "generated")


def summarize_evidence(
    records: Sequence[Mapping[str, Any]],
    required_types: Sequence[str] = (),
) -> Dict[str, Any]:
    by_type: Dict[str, Mapping[str, Any]] = {}
    for index, record in enumerate(records):
        artifact_type = _text(record.get("artifact_type"), f"artifact-{index}")
        current = by_type.get(artifact_type)
        next_status = normalize_evidence_status(record.get("status"))
        if current is None or EVIDENCE_WEIGHTS[next_status] > EVIDENCE_WEIGHTS[normalize_evidence_status(current.get("status"))]:
            by_type[artifact_type] = record

    normalized = list(by_type.values())
    statuses = [normalize_evidence_status(record.get("status")) for record in normalized]
    required_count = max(1, len(required_types) or len(normalized))
    generated_count = sum(status == "generated" for status in statuses)
    captured_count = sum(status in {"captured", "ready", "approved"} for status in statuses)
    ready_count = sum(status in {"ready", "approved"} for status in statuses)
    approved_count = sum(status == "approved" for status in statuses)
    stale_count = sum(status == "stale" for status in statuses)
    rejected_count = sum(status == "rejected" for status in statuses)
    weighted_total = sum(EVIDENCE_WEIGHTS[status] for status in statuses)
    coverage_score = min(100, round((weighted_total / required_count) * 100))
    package_ready = len(normalized) >= required_count and ready_count >= required_count and stale_count == 0 and rejected_count == 0
    package_approved = len(normalized) >= required_count and approved_count >= required_count
    available_ready_types = {
        artifact_type
        for artifact_type, record in by_type.items()
        if normalize_evidence_status(record.get("status")) in {"ready", "approved"}
    }
    missing_required_types = sorted(set(required_types) - available_ready_types)

    if package_approved:
        status_label = "Evidence package approved"
        display_status = "Approved"
    elif package_ready:
        status_label = "Evidence package ready"
        display_status = "Ready"
    elif rejected_count:
        status_label = f"{rejected_count} evidence artifact{'s' if rejected_count != 1 else ''} rejected"
        display_status = "Rejected"
    elif stale_count:
        status_label = f"{stale_count} evidence artifact{'s' if stale_count != 1 else ''} stale"
        display_status = "Stale"
    elif ready_count or captured_count or generated_count:
        status_label = f"{ready_count} of {required_count} evidence artifacts ready"
        display_status = "Incomplete"
    else:
        status_label = "No governed evidence recorded"
        display_status = "Missing"

    return {
        "total_count": len(normalized),
        "required_count": required_count,
        "generated_count": generated_count,
        "captured_count": captured_count,
        "ready_count": ready_count,
        "approved_count": approved_count,
        "stale_count": stale_count,
        "rejected_count": rejected_count,
        "coverage_score": coverage_score,
        "package_ready": package_ready,
        "package_approved": package_approved,
        "status_label": status_label,
        "display_status": display_status,
        "missing_required_types": missing_required_types,
        "status_contract": "shared/evidence_status_contract.json",
    }


class RegistryService:
    def __init__(self, persistence: PersistenceService, *, stale_days: int = 90) -> None:
        self.persistence = persistence
        self.stale_days = max(1, int(stale_days))

    def _asset_type(self, project: Mapping[str, Any]) -> str:
        project_type = _status_key(project.get("project_type"))
        workflow_type = _status_key(project.get("workflow_type"))
        template_id = _status_key(project.get("template_id"))
        combined = " ".join((project_type, workflow_type, template_id))
        if "credit_risk" in combined or "creditrisk" in combined:
            return "credit_risk_model"
        if "optimization" in combined:
            return "optimization_study"
        if "time_series_forecasting" in combined or "time_series" in combined or "forecasting" in combined:
            return "forecasting_study"
        if "llm_generative_ai" in combined or "generative_ai" in combined or "llm" in combined:
            return "llm_workflow"
        if "ab_testing" in combined or "a_b_testing" in combined:
            return "ab_test"
        if "experimental_design" in combined or project_type == "experiment":
            return "experiment"
        if any(token in combined for token in ("decision_strategy", "reinforcement_learning", "decision_intelligence")):
            return "decision_strategy"
        if any(token in combined for token in ("predictive", "classification", "regression")):
            return "predictive_model"
        return "custom_workflow"

    def _required_evidence_types(self, project: Mapping[str, Any]) -> Sequence[str]:
        if self._asset_type(project) == "optimization_study" and _status_key(project.get("template_id")) == "transportation_logistics":
            return TRANSPORTATION_REQUIRED_EVIDENCE
        return ()

    @staticmethod
    def _workflow_summary(workflow: Mapping[str, Any] | None, project_metadata: Mapping[str, Any]) -> Dict[str, Any]:
        workflow = workflow or {}
        completed_steps = {_text(step) for step in _sequence(workflow.get("completed_steps_json")) if _text(step)}
        status_payload = _mapping(workflow.get("workflow_status_json"))
        step_statuses = _mapping(status_payload.get("steps"))
        expected_steps = len(step_statuses)
        complete_from_status = {
            step_id for step_id, status in step_statuses.items()
            if _status_key(status) in {"complete", "completed", "skipped"}
        }
        completed_steps.update(complete_from_status)
        optimization_state = _mapping(project_metadata.get("optimizationState"))
        explicit_complete = bool(
            status_payload.get("status") == "complete"
            or optimization_state.get("studyCompleted") is True
            or (expected_steps > 0 and len(completed_steps) >= expected_steps)
        )
        if expected_steps == 0:
            expected_steps = len(completed_steps)
        if explicit_complete:
            completion_percent = 100
        elif expected_steps:
            completion_percent = min(99, round((len(completed_steps) / expected_steps) * 100))
        else:
            completion_percent = 0
        return {
            "current_step_id": workflow.get("current_step_id"),
            "completed_step_count": len(completed_steps),
            "expected_step_count": expected_steps,
            "completion_percent": completion_percent,
            "complete": explicit_complete,
            "updated_at": workflow.get("updated_at"),
        }

    @staticmethod
    def _documentation_summary(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        latest = records[0] if records else {}
        score = _number(latest.get("readiness_score"))
        section_count = int(_number(latest.get("section_count")) or 0)
        completed_count = int(_number(latest.get("completed_section_count")) or 0)
        if score is None and section_count:
            score = round((completed_count / section_count) * 100)
        score = min(100, max(0, round(score or 0)))
        raw_status = _status_key(latest.get("status"))
        if raw_status in {"complete", "completed", "approved"} or score >= 100:
            display_status = "Complete"
        elif raw_status in {"ready", "ready_for_review"} or score >= 80:
            display_status = "Ready"
        elif records:
            display_status = "Incomplete"
        else:
            display_status = "Not started"
        return {
            "readiness_score": score,
            "display_status": display_status,
            "package_id": latest.get("package_id"),
            "package_type": latest.get("package_type"),
            "package_status": latest.get("status"),
            "section_count": section_count,
            "completed_section_count": completed_count,
            "updated_at": latest.get("updated_at"),
        }

    @staticmethod
    def _validation_summary(
        runs: Sequence[Mapping[str, Any]],
        project_metadata: Mapping[str, Any],
        validation_case: Mapping[str, Any] | None = None,
        validation_findings: Sequence[Mapping[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        if validation_case:
            status = _status_key(validation_case.get("status"))
            open_findings = [
                finding for finding in (validation_findings or [])
                if _status_key(finding.get("status")) in OPEN_FINDING_STATUSES
            ]
            display_status = label_status(status)
            return {
                "display_status": display_status,
                "score": _number(validation_case.get("final_score")),
                "run_id": validation_case.get("validation_id"),
                "gate_status": validation_case.get("final_disposition") or validation_case.get("status"),
                "completed_at": validation_case.get("review_completed_at"),
                "case_status": status,
                "validation_id": validation_case.get("validation_id"),
                "open_finding_count": len(open_findings),
                "finding_count": len(validation_findings or []),
                "next_review_date": validation_case.get("next_review_date"),
            }
        validation_run = next((run for run in runs if "validation" in _status_key(run.get("run_type"))), None)
        optimization_validation = _mapping(_mapping(project_metadata.get("optimizationState")).get("validation"))
        if validation_run:
            metrics = _mapping(validation_run.get("metrics_json"))
            raw_status = _status_key(validation_run.get("status"))
            score = _number(metrics.get("validation_score"))
            if score is None:
                score = _number(metrics.get("score"))
            gate = _status_key(metrics.get("gate_status") or metrics.get("status"))
            if raw_status in FAILURE_STATUSES or gate in FAILURE_STATUSES:
                display_status = "Failed"
            elif raw_status in SUCCESS_STATUSES and (score is not None or gate in {"open", "approved", "passed", "complete"}):
                display_status = "Complete"
            elif raw_status in {"running", "in_progress", "queued", "created"}:
                display_status = "In progress"
            else:
                display_status = "Pending"
            return {
                "display_status": display_status,
                "score": score,
                "run_id": validation_run.get("run_id"),
                "gate_status": metrics.get("gate_status") or metrics.get("status"),
                "completed_at": validation_run.get("completed_at"),
            }
        if optimization_validation:
            score = _number(optimization_validation.get("score"))
            status = _status_key(optimization_validation.get("status"))
            return {
                "display_status": "Complete" if status in SUCCESS_STATUSES or score is not None else "Pending",
                "score": score,
                "run_id": None,
                "gate_status": optimization_validation.get("status"),
                "completed_at": None,
            }
        return {"display_status": "Not submitted", "score": None, "run_id": None, "gate_status": None, "completed_at": None, "case_status": "not_submitted", "open_finding_count": 0, "finding_count": 0, "next_review_date": None}

    @staticmethod
    def _recommendation_summary(decisions: Sequence[Mapping[str, Any]], project_metadata: Mapping[str, Any]) -> Dict[str, Any]:
        optimization_state = _mapping(project_metadata.get("optimizationState"))
        explicit_status = _text(optimization_state.get("recommendationStatus"))
        explicit_owner = _text(optimization_state.get("recommendationOwner"))
        candidate = next(
            (
                decision for decision in decisions
                if "recommendation" in _status_key(decision.get("decision_type"))
                or "recommendation" in _status_key(decision.get("title"))
            ),
            None,
        )
        status = explicit_status or _text((candidate or {}).get("status"), "Draft")
        owner = explicit_owner or _text((candidate or {}).get("owner"))
        return {
            "display_status": _title_status(status, "Draft"),
            "owner": owner,
            "summary": _text(optimization_state.get("recommendation")) or _text((candidate or {}).get("summary")),
            "decision_id": (candidate or {}).get("decision_id"),
            "updated_at": (candidate or {}).get("updated_at"),
        }

    @staticmethod
    def _implementation_summary(
        evidence: Sequence[Mapping[str, Any]],
        runs: Sequence[Mapping[str, Any]],
        audit: Sequence[Mapping[str, Any]],
        project_metadata: Mapping[str, Any],
    ) -> Dict[str, Any]:
        optimization_state = _mapping(project_metadata.get("optimizationState"))
        implementation_artifact = next(
            (record for record in evidence if "implementation_plan" in _status_key(record.get("artifact_type"))),
            None,
        )
        monitoring_artifact = next(
            (record for record in evidence if "monitoring_plan" in _status_key(record.get("artifact_type"))),
            None,
        )
        in_production = bool(
            project_metadata.get("inProduction")
            or project_metadata.get("implementedAt")
            or optimization_state.get("inProduction")
            or optimization_state.get("implementedAt")
        )
        actual_monitoring = in_production or any("monitor" in _status_key(run.get("run_type")) for run in runs) or any(
            _status_key(event.get("action_type")).startswith("monitoring_")
            and "plan" not in _status_key(event.get("action_type"))
            for event in audit
        )
        implementation_ready = bool(
            implementation_artifact
            and normalize_evidence_status(implementation_artifact.get("status")) in {"ready", "approved"}
        )
        monitoring_plan_ready = bool(
            monitoring_artifact
            and normalize_evidence_status(monitoring_artifact.get("status")) in {"ready", "approved"}
        )
        implementation_status = "Implemented" if in_production else "Plan complete" if implementation_ready else "Not started"
        monitoring_status = "Active" if actual_monitoring else "Plan complete" if monitoring_plan_ready else "Not started"
        return {
            "implementation_status": implementation_status,
            "implementation_owner": _text(optimization_state.get("implementationOwner") or project_metadata.get("implementationOwner")),
            "implementation_artifact_id": (implementation_artifact or {}).get("evidence_id"),
            "monitoring_status": monitoring_status,
            "monitoring_artifact_id": (monitoring_artifact or {}).get("evidence_id"),
            "in_production": in_production,
            "actual_monitoring": actual_monitoring,
        }

    @staticmethod
    def _derive_lifecycle(
        project: Mapping[str, Any],
        workflow: Mapping[str, Any],
        evidence: Mapping[str, Any],
        validation: Mapping[str, Any],
        recommendation: Mapping[str, Any],
        implementation: Mapping[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        project_status = _status_key(project.get("status"))
        recommendation_status = _status_key(recommendation.get("display_status"))
        reasons = [
            f"Workflow completion is {workflow.get('completion_percent', 0)}%.",
            f"Evidence status is {evidence.get('display_status', 'Missing')} at {evidence.get('coverage_score', 0)}% readiness.",
            f"Validation status is {validation.get('display_status', 'Pending')}.",
            f"Recommendation status is {recommendation.get('display_status', 'Draft')}.",
            f"Implementation status is {implementation.get('implementation_status', 'Not started')}.",
            f"Monitoring status is {implementation.get('monitoring_status', 'Not started')}.",
        ]
        validation_case_status = _status_key(validation.get("case_status"))
        if project_status == "retired":
            lifecycle, rule = "Retired", "Project status is retired."
        elif validation_case_status == "rejected":
            lifecycle, rule = "Rejected", "Independent validation rejected the asset."
        elif validation_case_status == "returned":
            lifecycle, rule = "Returned", "Independent validation returned the asset to the owner."
        elif validation_case_status == "remediation":
            lifecycle, rule = "Returned", "Independent validation findings require remediation."
        elif validation_case_status == "in_review":
            lifecycle, rule = "Validation", "Independent validation review is in progress."
        elif validation_case_status == "submitted":
            lifecycle, rule = "Ready for Review", "The asset was submitted to independent validation."
        elif recommendation_status == "rejected" or project_status == "rejected":
            lifecycle, rule = "Rejected", "Recommendation or project status is rejected."
        elif recommendation_status == "returned" or project_status == "returned":
            lifecycle, rule = "Returned", "Recommendation or project status is returned."
        elif implementation.get("actual_monitoring"):
            lifecycle, rule = "Monitoring", "Persisted production or monitoring activity exists."
        elif implementation.get("implementation_status") == "Implemented":
            lifecycle, rule = "Implemented", "The project is marked implemented or in production."
        elif implementation.get("implementation_status") == "Plan complete":
            lifecycle, rule = "Implementation Planned", "A completed implementation plan is persisted."
        elif recommendation_status == "approved":
            lifecycle, rule = "Approved", "The persisted recommendation is approved."
        elif validation_case_status == "approved_with_conditions":
            lifecycle, rule = "Approved with Conditions", "Independent validation approved the asset with conditions."
        elif validation_case_status == "approved":
            lifecycle, rule = "Approved", "Independent validation approved the asset."
        elif recommendation_status == "recommended":
            lifecycle, rule = "Recommended", "Validation is complete and the persisted recommendation is Recommended."
        elif validation.get("display_status") == "In progress":
            lifecycle, rule = "Validation", "A persisted validation run is in progress."
        elif workflow.get("complete") and evidence.get("display_status") in {"Ready", "Approved"}:
            lifecycle, rule = "Ready for Review", "Workflow and evidence are ready while final governance disposition is pending."
        elif workflow.get("completion_percent", 0) > 0:
            lifecycle, rule = "Development", "The persisted workflow has recorded progress."
        else:
            lifecycle, rule = "Draft", "No material workflow progress is persisted."
        return lifecycle, {"matched_rule": rule, "reasons": reasons}

    @staticmethod
    def _latest_run(runs: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        return runs[0] if runs else {}

    def _project_records(self, project_id: str) -> Dict[str, Any]:
        validation_case = self.persistence.validation.get_case_by_project(project_id)
        return {
            "workflow": self.persistence.projects.get_workflow_state(project_id),
            "evidence": self.persistence.evidence.list_for_project(project_id),
            "runs": self.persistence.runs.list_for_project(project_id),
            "documentation": self.persistence.documentation.list_for_project(project_id),
            "exports": self.persistence.exports.list_for_project(project_id),
            "decisions": self.persistence.decisions.list_for_project(project_id),
            "audit": self.persistence.audit.list(project_id=project_id, limit=1000),
            "validation_case": validation_case,
            "validation_events": self.persistence.validation.list_events(validation_case["validation_id"]) if validation_case else [],
        }

    def _build_asset(
        self,
        project: Mapping[str, Any],
        users_by_id: Mapping[str, Mapping[str, Any]],
        records: Mapping[str, Any] | None = None,
    ) -> tuple[RegistryAsset, Dict[str, Any]]:
        project_id = _text(project.get("project_id"))
        records = records or self._project_records(project_id)
        metadata = _mapping(project.get("metadata_json"))
        optimization_state = _mapping(metadata.get("optimizationState"))
        workflow = self._workflow_summary(records.get("workflow"), metadata)
        evidence = summarize_evidence(records.get("evidence") or [], self._required_evidence_types(project))
        documentation = self._documentation_summary(records.get("documentation") or [])
        validation_case = records.get("validation_case")
        validation_findings = self.persistence.validation.list_findings(validation_case["validation_id"]) if validation_case else []
        validation = self._validation_summary(records.get("runs") or [], metadata, validation_case, validation_findings)
        recommendation = self._recommendation_summary(records.get("decisions") or [], metadata)
        implementation = self._implementation_summary(
            records.get("evidence") or [], records.get("runs") or [], records.get("audit") or [], metadata
        )
        monitoring_plan = self.persistence.monitoring.get_plan_by_project(project_id) if hasattr(self.persistence, "monitoring") else None
        monitoring_runs = self.persistence.monitoring.list_runs(project_id=project_id, limit=1) if hasattr(self.persistence, "monitoring") else []
        monitoring_alerts = self.persistence.monitoring.list_alerts(project_id=project_id, limit=500) if hasattr(self.persistence, "monitoring") else []
        open_monitoring_alerts = [
            alert for alert in monitoring_alerts
            if alert.get("status") not in {"resolved", "closed", "accepted_risk"}
        ]
        last_monitoring_run = monitoring_runs[0] if monitoring_runs else {}
        if monitoring_plan:
            if monitoring_plan.get("plan_status") == "active":
                implementation["monitoring_status"] = "Active"
            elif implementation.get("monitoring_status") == "Not started":
                implementation["monitoring_status"] = "Plan complete"
        lifecycle, derivation = self._derive_lifecycle(project, workflow, evidence, validation, recommendation, implementation)
        owner_user_id = project.get("owner_user_id") or project.get("created_by")
        owner = users_by_id.get(_text(owner_user_id), {})
        latest_run = self._latest_run(records.get("runs") or [])
        latest_export = (records.get("exports") or [{}])[0] if records.get("exports") else {}
        last_activity_at = _latest_timestamp(
            [
                project.get("updated_at"),
                workflow.get("updated_at"),
                *[item.get("created_at") for item in records.get("evidence") or []],
                *[item.get("completed_at") or item.get("started_at") for item in records.get("runs") or []],
                *[item.get("updated_at") for item in records.get("documentation") or []],
                *[item.get("created_at") for item in records.get("exports") or []],
                *[item.get("updated_at") for item in records.get("decisions") or []],
                *[item.get("created_at") for item in records.get("audit") or []],
                monitoring_plan.get("updated_at") if monitoring_plan else None,
                last_monitoring_run.get("completed_at") or last_monitoring_run.get("executed_at"),
                *[item.get("updated_at") or item.get("created_at") for item in monitoring_alerts],
            ]
        )
        tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
        tags = sorted({
            *[_text(tag) for tag in tags if _text(tag)],
            _text(project.get("project_type")),
            _text(project.get("workflow_type")),
            _text(project.get("template_id")),
        } - {""})
        failed_run_count = sum(_status_key(run.get("status")) in FAILURE_STATUSES for run in records.get("runs") or [])
        open_validation_finding_count = int(validation.get("open_finding_count") or 0)
        open_finding_count = failed_run_count + evidence["stale_count"] + evidence["rejected_count"] + open_validation_finding_count
        asset: RegistryAsset = {
            "registry_id": f"registry:{project_id}",
            "project_id": project_id,
            "name": _text(project.get("project_name"), "Untitled ATLAS Project"),
            "asset_type": self._asset_type(project),
            "workflow_type": _text(project.get("workflow_type"), "custom"),
            "template_id": project.get("template_id"),
            "owner_user_id": owner_user_id,
            "owner_display_name": _text(owner.get("display_name"), _text(owner_user_id, "Unassigned")),
            "lifecycle_status": lifecycle,
            "risk_tier": _text(
                metadata.get("riskTier")
                or _mapping(metadata.get("projectContext")).get("riskLevel")
                or optimization_state.get("riskTier"),
                "Not classified",
            ),
            "business_purpose": _text(
                metadata.get("businessPurpose")
                or metadata.get("businessObjective")
                or _mapping(metadata.get("projectContext")).get("businessObjective")
                or optimization_state.get("businessObjective"),
                "Not documented",
            ),
            "intended_use": _text(
                metadata.get("intendedUse")
                or metadata.get("intendedModelUse")
                or _mapping(metadata.get("projectContext")).get("intendedModelUse")
                or optimization_state.get("decisionTitle")
                or optimization_state.get("objectiveName"),
                "Not documented",
            ),
            "current_step_id": workflow.get("current_step_id"),
            "workflow_completion_percent": workflow["completion_percent"],
            "evidence_readiness_percent": evidence["coverage_score"],
            "evidence_status": evidence["display_status"],
            "documentation_readiness_percent": documentation["readiness_score"],
            "documentation_status": documentation["display_status"],
            "validation_status": validation["display_status"],
            "validation_score": validation["score"],
            "recommendation_status": recommendation["display_status"],
            "implementation_status": implementation["implementation_status"],
            "monitoring_status": implementation["monitoring_status"],
            "monitoring_open_alert_count": len(open_monitoring_alerts),
            "last_monitoring_run_at": last_monitoring_run.get("completed_at") or last_monitoring_run.get("executed_at"),
            "next_monitoring_due_at": monitoring_plan.get("next_monitoring_date") if monitoring_plan else None,
            "latest_run_status": _title_status(latest_run.get("status"), "No runs"),
            "latest_run_type": latest_run.get("run_type"),
            "latest_run_at": latest_run.get("completed_at") or latest_run.get("started_at"),
            "latest_export_at": latest_export.get("created_at"),
            "last_activity_at": last_activity_at,
            "created_at": project.get("created_at"),
            "updated_at": project.get("updated_at"),
            "next_review_date": validation.get("next_review_date") or metadata.get("nextReviewDate") or optimization_state.get("nextReviewDate"),
            "open_action_count": 0,
            "open_finding_count": open_finding_count,
            "tags": tags,
            "summary_json": {
                "record_counts": {
                    "evidence": len(records.get("evidence") or []),
                    "runs": len(records.get("runs") or []),
                    "documentation_packages": len(records.get("documentation") or []),
                    "exports": len(records.get("exports") or []),
                    "decisions": len(records.get("decisions") or []),
                    "audit_events": len(records.get("audit") or []),
                    "validation_findings": len(validation_findings),
                    "validation_events": len(records.get("validation_events") or []),
                },
                "workflow": workflow,
                "evidence": evidence,
                "documentation": documentation,
                "validation": validation,
                "recommendation": recommendation,
                "implementation": implementation,
                "lifecycle_derivation": derivation,
            },
        }
        actions = self._derive_actions(asset, records)
        asset["open_action_count"] = len(actions)
        return asset, {**records, "actions": actions, "validation_findings": validation_findings}

    def _derive_actions(self, asset: RegistryAsset, records: Mapping[str, Any]) -> List[RegistryAction]:
        actions: List[RegistryAction] = []

        def add(
            action_type: str,
            severity: str,
            title: str,
            description: str,
            recommended_next_step: str,
            source: str,
        ) -> None:
            actions.append(
                {
                    "action_id": f"registry:{asset['project_id']}:{action_type}",
                    "project_id": asset["project_id"],
                    "project_name": asset["name"],
                    "severity": severity,
                    "action_type": action_type,
                    "title": title,
                    "description": description,
                    "owner": asset["owner_display_name"],
                    "recommended_next_step": recommended_next_step,
                    "created_at": asset.get("last_activity_at"),
                    "source": source,
                }
            )

        if asset["workflow_completion_percent"] < 100:
            add(
                "incomplete_workflow",
                "Medium",
                "Workflow is incomplete",
                f"Persisted workflow completion is {asset['workflow_completion_percent']}%.",
                "Open the project and complete the next required workflow step.",
                "workflow_state",
            )
        if asset["evidence_status"] not in {"Ready", "Approved"}:
            add(
                "missing_evidence",
                "High" if asset["workflow_completion_percent"] >= 100 else "Medium",
                "Evidence package is not ready",
                f"Evidence readiness is {asset['evidence_readiness_percent']}% with status {asset['evidence_status']}.",
                "Open Evidence Center and capture or resolve the outstanding governed artifacts.",
                "evidence_artifacts",
            )
        if asset["documentation_status"] not in {"Ready", "Complete"}:
            add(
                "missing_documentation",
                "High" if asset["workflow_completion_percent"] >= 100 else "Medium",
                "Documentation package is incomplete",
                f"Documentation readiness is {asset['documentation_readiness_percent']}%.",
                "Open Model Documentation Studio and complete the required sections.",
                "documentation_packages",
            )
        validation_record = records.get("validation_case")
        if asset["workflow_completion_percent"] >= 100 and not validation_record and asset["validation_status"] != "Complete":
            add(
                "validation_needed",
                "High",
                "Validation is required",
                "No independent validation case has been submitted.",
                "Submit this asset to the Validation and Challenge Center.",
                "validation_cases",
            )
        if validation_record and _status_key(validation_record.get("status")) in {"submitted", "in_review", "returned", "remediation"}:
            add(
                "validation_case_open",
                "High" if _status_key(validation_record.get("status")) in {"returned", "remediation"} else "Medium",
                "Independent validation case is open",
                f"Validation status is {asset['validation_status']}.",
                "Resolve review questions, findings, and required responses.",
                "validation_cases",
            )
        validation_findings = records.get("validation_findings") or []
        open_validation_findings = [finding for finding in validation_findings if _status_key(finding.get("status")) in OPEN_FINDING_STATUSES]
        if open_validation_findings:
            add(
                "validation_findings_open",
                "High",
                "Validation findings are open",
                f"{len(open_validation_findings)} validation finding{'s' if len(open_validation_findings) != 1 else ''} require closure.",
                "Open the validation case and resolve findings before approval.",
                "validation_findings",
            )
        if _status_key(asset["validation_status"]) in {"approved", "approved_with_conditions"} and asset["recommendation_status"] in {"Draft", "Pending", "Not Started"}:
            add(
                "recommendation_draft",
                "Medium",
                "Recommendation remains draft",
                "Validation is complete but no final recommendation is persisted.",
                "Record the accountable recommendation and governance rationale.",
                "decision_journal",
            )
        implementation = _mapping(_mapping(asset.get("summary_json")).get("implementation"))
        if asset["recommendation_status"] in {"Recommended", "Approved"} and not _text(implementation.get("implementation_owner")):
            add(
                "implementation_owner_missing",
                "High",
                "Implementation owner is missing",
                "The recommendation is actionable but no accountable implementation owner is persisted.",
                "Assign an implementation owner and target date.",
                "projects.metadata_json",
            )
        if asset["implementation_status"] in {"Plan complete", "Implemented"} and asset["monitoring_status"] == "Not started":
            add(
                "monitoring_plan_missing",
                "High",
                "Monitoring plan is missing",
                "Implementation planning is complete without a persisted monitoring plan.",
                "Define monitoring metrics, thresholds, cadence, ownership, and escalation triggers.",
                "evidence_artifacts",
            )
        if asset["workflow_completion_percent"] >= 100 and not records.get("exports"):
            add(
                "export_package_missing",
                "Low",
                "Governed export package is missing",
                "The workflow is complete but no export artifact is persisted.",
                "Generate the governed report, data output, and reproducibility exports.",
                "export_artifacts",
            )
        failed_runs = [run for run in records.get("runs") or [] if _status_key(run.get("status")) in FAILURE_STATUSES]
        if failed_runs:
            add(
                "failed_run",
                "High",
                "A persisted run failed",
                f"{len(failed_runs)} failed run record{'s' if len(failed_runs) != 1 else ''} require review.",
                "Open the project run history, resolve the error, and rerun the governed process.",
                "run_records",
            )
        last_activity = _parse_datetime(asset.get("last_activity_at"))
        if last_activity and datetime.now(timezone.utc) - last_activity > timedelta(days=self.stale_days):
            add(
                "project_stale",
                "Low",
                "Project activity is stale",
                f"No persisted activity has been recorded for more than {self.stale_days} days.",
                "Confirm ownership, current disposition, and the next review date.",
                "audit_log",
            )
        severity_order = {"High": 0, "Medium": 1, "Low": 2}
        return sorted(actions, key=lambda action: (severity_order.get(action["severity"], 9), action["title"]))

    def list_assets(
        self,
        *,
        asset_type: str | None = None,
        workflow_type: str | None = None,
        lifecycle_status: str | None = None,
        owner_user_id: str | None = None,
        evidence_status: str | None = None,
        documentation_status: str | None = None,
        validation_status: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        users = self.persistence.users.list()
        users_by_id = {_text(user.get("user_id")): user for user in users}
        items = [self._build_asset(project, users_by_id)[0] for project in self.persistence.projects.list()]
        filters = {
            "asset_type": asset_type,
            "workflow_type": workflow_type,
            "lifecycle_status": lifecycle_status,
            "owner_user_id": owner_user_id,
            "evidence_status": evidence_status,
            "documentation_status": documentation_status,
            "validation_status": validation_status,
        }
        for field, expected in filters.items():
            if expected:
                items = [item for item in items if _status_key(item.get(field)) == _status_key(expected)]
        if search:
            needle = search.strip().lower()
            items = [
                item for item in items
                if needle in " ".join(
                    _text(item.get(field)).lower()
                    for field in ("name", "project_id", "asset_type", "workflow_type", "template_id", "owner_display_name", "business_purpose", "intended_use")
                )
                or any(needle in tag.lower() for tag in item.get("tags", []))
            ]
        items.sort(key=lambda item: _parse_datetime(item.get("last_activity_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        total = len(items)
        start = max(0, int(offset))
        page_size = max(1, min(int(limit), 500))
        return {"items": items[start:start + page_size], "total": total, "limit": page_size, "offset": start}

    def get_asset(self, project_id: str) -> Dict[str, Any] | None:
        project = self.persistence.projects.get(project_id)
        if not project:
            return None
        users = self.persistence.users.list()
        users_by_id = {_text(user.get("user_id")): user for user in users}
        asset, records = self._build_asset(project, users_by_id)
        return {
            "asset": asset,
            "evidence_summary": _mapping(asset["summary_json"]).get("evidence"),
            "documentation_summary": _mapping(asset["summary_json"]).get("documentation"),
            "latest_runs": [self._run_summary(run) for run in (records.get("runs") or [])[:12]],
            "exports": [self._export_summary(item) for item in records.get("exports") or []],
            "decisions": [self._decision_summary(item) for item in (records.get("decisions") or [])[:25]],
            "audit_trail": [self._audit_summary(item, users_by_id) for item in (records.get("audit") or [])[:50]],
            "lifecycle_timeline": self._timeline(project, records, users_by_id),
            "open_actions": records.get("actions") or [],
            "lifecycle_derivation": _mapping(asset["summary_json"]).get("lifecycle_derivation"),
        }

    @staticmethod
    def _run_summary(run: Mapping[str, Any]) -> Dict[str, Any]:
        metrics = _mapping(run.get("metrics_json"))
        preferred = (
            "total_cost", "demand_fulfilled", "total_demand", "unmet_demand", "active_routes",
            "scenario_count", "validation_score", "auc", "roc_auc", "pr_auc", "accuracy",
            "rmse", "mae", "r_squared", "solver_status", "gate_status",
        )
        metrics_summary = {key: metrics[key] for key in preferred if key in metrics}
        if not metrics_summary:
            metrics_summary = dict(list(metrics.items())[:8])
        return {
            "run_id": run.get("run_id"),
            "run_type": run.get("run_type"),
            "status": run.get("status"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "created_by": run.get("created_by"),
            "metrics": metrics_summary,
            "has_error": bool(_mapping(run.get("error_json"))),
        }

    @staticmethod
    def _export_summary(item: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "export_id": item.get("export_id"),
            "export_type": item.get("export_type"),
            "file_name": item.get("file_name"),
            "file_path": item.get("file_path"),
            "storage_mode": item.get("storage_mode"),
            "created_by": item.get("created_by"),
            "created_at": item.get("created_at"),
            "artifact_hash": item.get("artifact_hash"),
        }

    @staticmethod
    def _decision_summary(item: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "decision_id": item.get("decision_id"),
            "decision_type": item.get("decision_type"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "status": item.get("status"),
            "owner": item.get("owner"),
            "created_by": item.get("created_by"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "detail": {
                key: value for key, value in _mapping(item.get("payload_json")).items()
                if key in {"workflowStep", "newValue", "previousValue", "userReason", "followStatus", "systemRecommendation"}
            },
        }

    @staticmethod
    def _audit_summary(item: Mapping[str, Any], users_by_id: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
        user_id = _text(item.get("user_id"))
        return {
            "audit_id": item.get("audit_id"),
            "project_id": item.get("project_id"),
            "user_id": item.get("user_id"),
            "user_display_name": _text(users_by_id.get(user_id, {}).get("display_name"), user_id or "System"),
            "action_type": item.get("action_type"),
            "entity_type": item.get("entity_type"),
            "entity_id": item.get("entity_id"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "created_at": item.get("created_at"),
        }

    def _timeline(
        self,
        project: Mapping[str, Any],
        records: Mapping[str, Any],
        users_by_id: Mapping[str, Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []

        def add(event_type: str, title: str, occurred_at: Any, *, summary: str = "", status: Any = None, user_id: Any = None, source_id: Any = None) -> None:
            if not _text(occurred_at):
                return
            events.append({
                "event_type": event_type,
                "title": title,
                "summary": summary,
                "status": status,
                "occurred_at": occurred_at,
                "user_id": user_id,
                "user_display_name": _text(users_by_id.get(_text(user_id), {}).get("display_name"), _text(user_id, "System")),
                "source_id": source_id,
            })

        add("project_created", "Project created", project.get("created_at"), summary=_text(project.get("project_name")), user_id=project.get("created_by"), source_id=project.get("project_id"))
        workflow = records.get("workflow") or {}
        add("workflow_progress", "Workflow state updated", workflow.get("updated_at"), summary=f"Current step: {_text(workflow.get('current_step_id'), 'Not recorded')}", status="complete" if _mapping(_mapping(workflow.get("workflow_status_json")).get("steps")) else "recorded", user_id=workflow.get("completed_by"), source_id=workflow.get("project_id"))
        for run in records.get("runs") or []:
            add("run", _title_status(run.get("run_type"), "Analytical run"), run.get("completed_at") or run.get("started_at"), summary="Persisted analytical execution record.", status=run.get("status"), user_id=run.get("created_by"), source_id=run.get("run_id"))
        for evidence in records.get("evidence") or []:
            add("evidence", _text(evidence.get("title"), "Evidence artifact"), evidence.get("approved_at") or evidence.get("captured_at") or evidence.get("created_at"), summary=_text(evidence.get("summary"), _title_status(evidence.get("artifact_type"), "Governed evidence")), status=evidence.get("status"), user_id=evidence.get("created_by"), source_id=evidence.get("evidence_id"))
        for package in records.get("documentation") or []:
            add("documentation", "Documentation package updated", package.get("updated_at"), summary=f"{package.get('completed_section_count') or 0} of {package.get('section_count') or 0} sections complete.", status=package.get("status"), user_id=package.get("created_by"), source_id=package.get("package_id"))
        for export in records.get("exports") or []:
            add("export", f"Export generated: {_text(export.get('file_name'), 'ATLAS export')}", export.get("created_at"), summary=_title_status(export.get("export_type"), "Governed export"), status="complete", user_id=export.get("created_by"), source_id=export.get("export_id"))
        for decision in records.get("decisions") or []:
            add("decision", _text(decision.get("title"), "Decision recorded"), decision.get("updated_at") or decision.get("created_at"), summary=_text(decision.get("summary"), _text(_mapping(decision.get("payload_json")).get("newValue"))), status=decision.get("status"), user_id=decision.get("created_by"), source_id=decision.get("decision_id"))
        validation_case = records.get("validation_case") or {}
        add("validation_case", "Validation case updated", validation_case.get("updated_at"), summary=_text(validation_case.get("summary"), label_status(validation_case.get("status"))), status=validation_case.get("business_status_label") or validation_case.get("status"), user_id=validation_case.get("submitted_by"), source_id=validation_case.get("validation_id"))
        for event in records.get("validation_events") or []:
            add("validation_event", _text(event.get("title"), "Validation event"), event.get("created_at"), summary=_text(event.get("summary")), status=_title_status(event.get("event_type"), "Validation"), user_id=event.get("user_id"), source_id=event.get("event_id"))
        for audit in records.get("audit") or []:
            add("audit", _text(audit.get("title"), _title_status(audit.get("action_type"), "Audit event")), audit.get("created_at"), summary=_text(audit.get("summary")), status="recorded", user_id=audit.get("user_id"), source_id=audit.get("audit_id"))
        events.sort(key=lambda item: _parse_datetime(item.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return events[:100]

    def list_actions(self, *, severity: str | None = None, project_id: str | None = None, limit: int = 250) -> Dict[str, Any]:
        assets = self.list_assets(limit=500)["items"]
        actions: List[RegistryAction] = []
        for asset in assets:
            if project_id and asset["project_id"] != project_id:
                continue
            detail = self.get_asset(asset["project_id"])
            actions.extend((detail or {}).get("open_actions") or [])
        if severity:
            actions = [action for action in actions if _status_key(action["severity"]) == _status_key(severity)]
        severity_order = {"High": 0, "Medium": 1, "Low": 2}
        actions.sort(key=lambda action: (severity_order.get(action["severity"], 9), action["project_name"], action["title"]))
        page_size = max(1, min(int(limit), 500))
        return {"items": actions[:page_size], "total": len(actions)}

    def list_activity(self, *, project_id: str | None = None, limit: int = 100) -> Dict[str, Any]:
        users = self.persistence.users.list()
        users_by_id = {_text(user.get("user_id")): user for user in users}
        projects = [self.persistence.projects.get(project_id)] if project_id else self.persistence.projects.list()
        events: List[Dict[str, Any]] = []
        for project in projects:
            if not project:
                continue
            records = self._project_records(_text(project.get("project_id")))
            events.extend(
                {
                    **event,
                    "project_id": project.get("project_id"),
                    "project_name": project.get("project_name"),
                }
                for event in self._timeline(project, records, users_by_id)
            )
        events.sort(key=lambda item: _parse_datetime(item.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        page_size = max(1, min(int(limit), 500))
        return {"items": events[:page_size], "total": len(events)}

    def owner_summaries(self) -> Dict[str, Any]:
        users = self.persistence.users.list()
        assets = self.list_assets(limit=500)["items"]
        actions = self.list_actions(limit=500)["items"]
        audit = self.persistence.audit.list(limit=1000)
        summaries: List[Dict[str, Any]] = []
        for user in users:
            user_id = _text(user.get("user_id"))
            owned_assets = [asset for asset in assets if asset.get("owner_user_id") == user_id]
            active_assets = [asset for asset in owned_assets if asset.get("lifecycle_status") not in TERMINAL_LIFECYCLES]
            project_ids = {asset["project_id"] for asset in owned_assets}
            project_records = [self._project_records(project_id) for project_id in project_ids]
            evidence_count = sum(
                1 for records in project_records for record in records["evidence"]
                if record.get("created_by") == user_id or records.get("workflow", {}).get("completed_by") == user_id
            )
            validation_count = sum(
                1 for records in project_records for run in records["runs"]
                if "validation" in _status_key(run.get("run_type"))
            )
            export_count = sum(len(records["exports"]) for records in project_records)
            user_audit = [event for event in audit if event.get("user_id") == user_id]
            last_active_at = _latest_timestamp([
                user.get("last_active_at"),
                *[asset.get("last_activity_at") for asset in owned_assets],
                *[event.get("created_at") for event in user_audit],
            ])
            summaries.append({
                "user_id": user_id,
                "display_name": _text(user.get("display_name"), user_id),
                "role": user.get("role"),
                "status": user.get("status"),
                "active_assets": len(active_assets),
                "ready_for_review": sum(asset.get("lifecycle_status") == "Ready for Review" for asset in owned_assets),
                "open_actions": sum(action["project_id"] in project_ids for action in actions),
                "evidence_artifacts": evidence_count,
                "validation_records": validation_count,
                "exports_generated": export_count,
                "recent_activity_count": len(user_audit),
                "last_active_at": last_active_at,
            })
        summaries.sort(key=lambda item: (item["active_assets"], item["recent_activity_count"], item["display_name"]), reverse=True)
        return {"items": summaries, "total": len(summaries)}

    def summary(self) -> Dict[str, Any]:
        assets = self.list_assets(limit=500)["items"]
        actions = self.list_actions(limit=500)["items"]
        owners = self.owner_summaries()["items"]
        activity = self.list_activity(limit=500)["items"]
        now = datetime.now(timezone.utc)
        recent_activity = [
            item for item in activity
            if (_parse_datetime(item.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= now - timedelta(days=30)
        ]
        lifecycle_counts = Counter(asset["lifecycle_status"] for asset in assets)
        type_counts = Counter(asset["asset_type"] for asset in assets)
        stale_count = sum(
            bool(_parse_datetime(asset.get("last_activity_at")))
            and now - (_parse_datetime(asset.get("last_activity_at")) or now) > timedelta(days=self.stale_days)
            for asset in assets
        )
        return {
            "generated_at": now_iso(),
            "total_assets": len(assets),
            "active_assets": sum(asset["lifecycle_status"] not in TERMINAL_LIFECYCLES for asset in assets),
            "draft_assets": lifecycle_counts["Draft"],
            "ready_for_review": lifecycle_counts["Ready for Review"],
            "in_validation": lifecycle_counts["Validation"],
            "recommended": lifecycle_counts["Recommended"],
            "approved": lifecycle_counts["Approved"],
            "implementation_planned": lifecycle_counts["Implementation Planned"],
            "monitoring": lifecycle_counts["Monitoring"],
            "evidence_ready_count": sum(asset["evidence_status"] in {"Ready", "Approved"} for asset in assets),
            "evidence_incomplete_count": sum(asset["evidence_status"] not in {"Ready", "Approved"} for asset in assets),
            "documentation_ready_count": sum(asset["documentation_status"] in {"Ready", "Complete"} for asset in assets),
            "documentation_incomplete_count": sum(asset["documentation_status"] not in {"Ready", "Complete"} for asset in assets),
            "validation_complete_count": sum(asset["validation_status"] == "Complete" for asset in assets),
            "validation_pending_count": sum(asset["validation_status"] != "Complete" for asset in assets),
            "open_action_count": len(actions),
            "recent_activity_count": len(recent_activity),
            "assets_by_type": dict(sorted(type_counts.items())),
            "assets_by_status": dict(sorted(lifecycle_counts.items())),
            "assets_by_owner": {
                owner["display_name"]: owner["active_assets"]
                for owner in owners if owner["active_assets"]
            },
            "stale_assets_count": stale_count,
        }


_registry_service: RegistryService | None = None


def get_registry_service() -> RegistryService:
    global _registry_service
    persistence = get_persistence_service()
    if _registry_service is None or _registry_service.persistence.database.path != persistence.database.path:
        _registry_service = RegistryService(persistence)
    return _registry_service
