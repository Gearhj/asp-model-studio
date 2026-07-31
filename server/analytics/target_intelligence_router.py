"""EDA Target Intelligence -- HTTP routes.

Kept separate from `analytics_queries_router` (the generic analytical query
plane) because these endpoints answer one specific governed question -- "is this
target correctly defined, sufficiently populated, stable, measurable, and
appropriate for modeling" -- and carry their own persistence (target findings)
and their own governance gate (governed evidence).

Governance rule enforced here, once, on the server: an analysis is governed only
when the server itself resolves an authorized project, an authorized dataset, an
exact registered version, and an immutable artifact. No field of the request can
assert that. See server/analytics/analysis_scope.py.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.modeling_scope import authorize_modeling_scope
from ..datasets.dataset_identity import (
    assert_expected_active_identity,
    require_exact_project_link,
)
from ..datasets.dataset_registry import require_dataset
from ..evidence.evidence_identity import authorize_and_normalize_evidence
from ..evidence.evidence_store import upsert_evidence
from ..evidence.evidence_types import CANONICAL_DATASET_LINEAGE_CONTRACT
from ..persistence.db import PersistenceUnavailableError, now_iso
from ..persistence.service import get_persistence_service
from ..security.security_store import audit_event, require_user, user_can_access_project
from .analysis_scope import (
    DRAFT_EXPORT_MARKERS,
    GOVERNED_VERSION,
    WORKSPACE_DRAFT,
    is_governed,
    require_evidence_eligible,
    scope_identity,
)
from .target_distribution_service import _duckdb, _quote_identifier, _resolve_version_artifact, _scan_expression
from .target_intelligence_service import (
    DEFAULT_BANDS,
    DEFAULT_TOP_CATEGORIES,
    ENGINE_VERSION,
    compute_target_assessment,
    compute_target_by_predictor,
)


router = APIRouter(dependencies=[Depends(require_user)])

# Evidence must summarize an analysis, never carry the population. These caps
# are enforced server-side so a client cannot widen them.
MAX_EVIDENCE_ROWS = 60
MAX_EVIDENCE_BYTES = 96 * 1024


def _check_project_access(user: Dict[str, Any], project_id: str) -> None:
    if not project_id:
        raise HTTPException(status_code=400, detail="A projectId is required.")
    if not user_can_access_project(project_id):
        audit_event(
            "access.denied", "project", project_id, "denied",
            user_id=str(user.get("userId") or ""),
            reason="Target Intelligence denied for project ACL",
        )
        raise HTTPException(status_code=403, detail="You do not have access to target analysis for this project.")


def _user_scope(user: Dict[str, Any]) -> str:
    return str(user.get("userId") or "anonymous")


def _service():
    try:
        return get_persistence_service()
    except PersistenceUnavailableError as exc:  # pragma: no cover - deployment dependent
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_dataset_linked_to_project(project_id: str, dataset_id: str, version_id: str) -> None:
    """Blocks pairing a project the caller owns with another project's dataset version.

    `require_dataset` already enforces the dataset ACL, but a user who can read
    two projects could otherwise attach dataset D from project A as governed
    provenance for project B. Governed evidence must name a version that is
    actually linked to the project it documents.
    """
    require_exact_project_link(project_id, dataset_id, version_id)


def _require_active_version(
    user: Dict[str, Any],
    project_id: str,
    dataset_id: str,
    version_id: Optional[str],
) -> Dict[str, Any]:
    # Bind the request to the project-scoped modeling store before consulting
    # DATASTORE. Project ACL checks alone do not establish the scoped store.
    authorize_modeling_scope(user, project_id, "view")
    return assert_expected_active_identity(
        project_id,
        expected_dataset_id=dataset_id,
        expected_dataset_version_id=version_id,
        require_expected=True,
        user=user,
    )


def _assert_target_exists_in_version(dataset_id: str, version_id: Optional[str], target: str) -> Dict[str, Any]:
    """Confirms the target column genuinely exists in the resolved artifact.

    Uses a zero-row projection, so it reads the artifact's schema rather than its
    population -- the check costs no scan.
    """
    artifact = _resolve_version_artifact(dataset_id, version_id)
    scan = _scan_expression(artifact)
    connection = _duckdb().connect()
    try:
        connection.execute(f"SELECT {_quote_identifier(target)} FROM {scan} LIMIT 0")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=422,
            detail=f"Target '{target}' does not exist in dataset version {artifact.get('versionId')}.",
        ) from exc
    finally:
        connection.close()
    return artifact


# ---------------------------------------------------------------------------
# Parts D / E / F -- class balance, rare-event assessment, event-rate interval
# ---------------------------------------------------------------------------


class TargetAssessmentRequest(BaseModel):
    projectId: str
    datasetId: str
    versionId: str | None = None
    target: str
    eventValue: Any = None
    nonEventValue: Any = None
    confidenceLevel: float = 0.95
    forceExact: bool = False


@router.post("/analytics/target-assessment")
def target_assessment(payload: TargetAssessmentRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Exact class balance, event-prevalence and class-imbalance assessment, and a
    Wilson score interval, with a server-derived governed analysis scope."""
    _check_project_access(user, payload.projectId)
    identity = _require_active_version(
        user,
        payload.projectId,
        payload.datasetId,
        payload.versionId,
    )
    return compute_target_assessment(
        user_scope=_user_scope(user),
        project_id=identity["project_id"],
        dataset_id=identity["dataset_id"],
        version_id=identity["dataset_version_id"],
        target=payload.target,
        event_value=payload.eventValue,
        non_event_value=payload.nonEventValue,
        confidence_level=payload.confidenceLevel,
        force_exact=payload.forceExact,
    )


# ---------------------------------------------------------------------------
# Part G -- target by predictor (on demand only)
# ---------------------------------------------------------------------------


class TargetByPredictorRequest(BaseModel):
    projectId: str
    datasetId: str
    versionId: str | None = None
    target: str
    predictor: str
    analysisType: str = "numeric_quantile"
    eventValue: Any = None
    bands: int = DEFAULT_BANDS
    topCategories: int = DEFAULT_TOP_CATEGORIES
    includeMissing: bool = True


@router.post("/analytics/target-by-predictor")
def target_by_predictor(payload: TargetByPredictorRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Bounded grouped event rate for one predictor. Explicitly invoked -- this
    is never issued when the Target tab mounts."""
    _check_project_access(user, payload.projectId)
    identity = _require_active_version(
        user,
        payload.projectId,
        payload.datasetId,
        payload.versionId,
    )
    return compute_target_by_predictor(
        user_scope=_user_scope(user),
        project_id=identity["project_id"],
        dataset_id=identity["dataset_id"],
        version_id=identity["dataset_version_id"],
        target=payload.target,
        predictor=payload.predictor,
        analysis_type=payload.analysisType,
        event_value=payload.eventValue,
        bands=payload.bands,
        top_categories=payload.topCategories,
        include_missing=payload.includeMissing,
    )


# ---------------------------------------------------------------------------
# Part C -- governed Target Intelligence evidence
# ---------------------------------------------------------------------------


class TargetEvidenceRequest(BaseModel):
    """Only ANALYTICAL SELECTION comes from the client.

    Deliberately absent: scope mode, evidence eligibility, class counts, event
    rate, imbalance, interval, checksum, population rows. Every one of those is
    derived on the server, so a crafted request cannot assert governance or
    substitute figures. Fields a client sends that are not on this model are
    rejected by pydantic rather than carried through.
    """

    model_config = {"extra": "forbid"}

    projectId: str
    datasetId: str
    versionId: str | None = None
    target: str
    eventValue: Any = None
    nonEventValue: Any = None
    # Analytical selection to reproduce alongside the class assessment.
    predictor: str | None = None
    predictorAnalysisType: str | None = None
    predictorBands: int = DEFAULT_BANDS
    predictorTopCategories: int = DEFAULT_TOP_CATEGORIES
    predictorIncludeMissing: bool = True
    timeField: str | None = None
    segmentField: str | None = None
    chartSpecification: Dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=300)
    notes: str = Field(default="", max_length=8000)


def _bounded(payload: Dict[str, Any], *, label: str) -> Dict[str, Any]:
    rows = payload.get("rows")
    if isinstance(rows, list) and len(rows) > MAX_EVIDENCE_ROWS:
        raise HTTPException(
            status_code=422,
            detail=f"{label} exceeds the {MAX_EVIDENCE_ROWS} bounded result-row limit.",
        )
    encoded = json.dumps(payload, default=str)
    if len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"{label} exceeds the {MAX_EVIDENCE_BYTES // 1024} KB bounded-summary limit.",
        )
    return payload


@router.post("/analytics/target-evidence")
def save_target_evidence(payload: TargetEvidenceRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Creates a governed Target Intelligence evidence artifact.

    Every governance fact is resolved here, in this order, before anything is
    written:

      1. project authorization
      2. dataset authorization (`require_dataset`)
      3. the dataset is actually linked to this project
      4. the registered version and its immutable artifact resolve
      5. the target exists in THAT version
      6. the analysis is recomputed server-side (cached, so this is a cache read)
      7. the resolved scope is governed

    A workspace draft analysis therefore cannot become governed evidence, no
    matter what the request claims -- there is no request field that can assert
    it, and the figures written are the server's, not the client's.
    """
    _check_project_access(user, payload.projectId)
    if not payload.datasetId or not payload.versionId:
        raise HTTPException(
            status_code=409,
            detail=(
                "Governed evidence requires a registered dataset version. This analysis is a Workspace Draft "
                "Analysis; register or link an immutable Dataset Library version and rerun the analysis first."
            ),
        )

    dataset = require_dataset(payload.datasetId)
    active = _require_active_version(
        user,
        payload.projectId,
        payload.datasetId,
        payload.versionId,
    )
    dataset_id = active["dataset_id"]
    version_id = active["dataset_version_id"]
    artifact = _assert_target_exists_in_version(dataset_id, version_id, payload.target)
    if str(artifact.get("versionId")) != str(payload.versionId):
        raise HTTPException(
            status_code=422,
            detail="The requested dataset version could not be resolved exactly; governed evidence was not created.",
        )

    assessment = compute_target_assessment(
        user_scope=_user_scope(user), project_id=payload.projectId, dataset_id=dataset_id,
        version_id=version_id, target=payload.target,
        event_value=payload.eventValue, non_event_value=payload.nonEventValue,
    )
    scope = require_evidence_eligible(assessment.get("analysisScope"))

    predictor_analysis = None
    if payload.predictor:
        predictor_analysis = compute_target_by_predictor(
            user_scope=_user_scope(user), project_id=payload.projectId, dataset_id=dataset_id,
            version_id=version_id, target=payload.target, predictor=payload.predictor,
            analysis_type=payload.predictorAnalysisType or "numeric_quantile",
            event_value=payload.eventValue, bands=payload.predictorBands,
            top_categories=payload.predictorTopCategories, include_missing=payload.predictorIncludeMissing,
        )

    balance = assessment.get("classBalance") or {}
    imbalance = assessment.get("imbalance") or {}
    interval = assessment.get("confidenceInterval") or {}

    predictor_rows = (predictor_analysis or {}).get("rows") or []
    truncated = len(predictor_rows) > MAX_EVIDENCE_ROWS
    bounded_predictor = (
        {
            "predictor": predictor_analysis["predictor"],
            "analysisType": predictor_analysis["analysisType"],
            "rows": [
                {
                    "group": row.get("category") or row.get("label"),
                    "population": row.get("population"),
                    "eventCount": row.get("eventCount"),
                    "eventRate": row.get("eventRate"),
                    "smallGroup": row.get("smallGroup"),
                }
                for row in predictor_rows[:MAX_EVIDENCE_ROWS]
            ],
            "missingGroup": predictor_analysis.get("missingGroup"),
            "otherGroup": predictor_analysis.get("otherGroup"),
            "summary": predictor_analysis.get("summary"),
            "truncatedRows": truncated,
        }
        if predictor_analysis
        else None
    )

    evidence_payload = _bounded(
        {
            "analysisScope": scope,
            "datasetIdentity": {
                "datasetId": dataset_id,
                "datasetName": dataset.get("name"),
                "datasetVersionId": artifact.get("versionId"),
                "artifactChecksum": artifact.get("checksum"),
                "immutableVersion": True,
                "populationRows": balance.get("totalModelingPopulation"),
            },
            "targetDefinition": {
                "target": payload.target,
                "positiveValue": balance.get("eventValue"),
                "negativeValue": balance.get("nonEventValue"),
                "eventValueResolution": balance.get("eventValueResolution"),
            },
            "classCounts": {
                "eventCount": balance.get("eventCount"),
                "nonEventCount": balance.get("nonEventCount"),
                "missingTargetCount": balance.get("missingTargetCount"),
                "totalModelingPopulation": balance.get("totalModelingPopulation"),
            },
            "eventRate": balance.get("eventRate"),
            "eventPrevalence": imbalance.get("eventPrevalence"),
            "classImbalance": imbalance.get("classImbalance"),
            "ratios": {
                "nonEventsPerEvent": imbalance.get("nonEventsPerEvent"),
                "eventsPerNonEvent": imbalance.get("eventsPerNonEvent"),
                "majorityToMinorityRatio": imbalance.get("majorityToMinorityRatio"),
                "orientation": imbalance.get("ratioOrientation"),
            },
            "confidenceInterval": interval,
            "resolution": {
                "exact": scope.get("exact"),
                "sampled": scope.get("sampled"),
                "state": balance.get("resolution"),
            },
            "selectedPredictorAnalysis": bounded_predictor,
            "timeAndSegmentSelection": {"timeField": payload.timeField, "segmentField": payload.segmentField},
            "chartSpecification": payload.chartSpecification,
            "analysisSpecification": {
                "engineVersion": ENGINE_VERSION,
                "scopeContractVersion": scope.get("contractVersion"),
                "sourceOperation": "POST /api/analytics/target-evidence",
                "analysisSource": scope.get("analysisSource"),
            },
            "boundedResultDisclosure": (
                f"Aggregate rows only, capped at {MAX_EVIDENCE_ROWS} rows and "
                f"{MAX_EVIDENCE_BYTES // 1024} KB. No population data is stored."
            ),
            "truncationDisclosure": (
                f"The predictor analysis returned {len(predictor_rows)} groups; only the first "
                f"{MAX_EVIDENCE_ROWS} are recorded."
            )
            if truncated
            else None,
            "notes": payload.notes,
            "capturedBy": _user_scope(user),
            "capturedAt": now_iso(),
        },
        label="The Target Intelligence evidence payload",
    )

    title = (payload.title or f"Target Intelligence -- {payload.target} @ {artifact.get('versionId')}").strip()
    # A fresh id per save: governed evidence is an immutable record, so a repeat
    # save creates a NEW artifact that references the prior one rather than
    # silently overwriting it.
    evidence_id = f"ev-target-intel-{uuid.uuid4().hex[:20]}"
    evidence_record = authorize_and_normalize_evidence({
        "evidenceId": evidence_id,
        "lineage_contract": CANONICAL_DATASET_LINEAGE_CONTRACT,
        "project_id": payload.projectId,
        "dataset_id": dataset_id,
        "dataset_version_id": version_id,
        "projectId": payload.projectId,
        "evidenceType": "eda",
        "title": title,
        "summary": (
            f"{balance.get('eventCount'):,} events in {balance.get('totalModelingPopulation'):,} rows "
            f"({(balance.get('eventRate') or 0) * 100:.4f}%); {imbalance.get('label')}; "
            f"version {artifact.get('versionId')}."
        ),
        "sourcePage": "Exploratory Data Analysis -- Target Intelligence",
        "sourceRoute": "/step02",
        "artifactType": "target_intelligence",
        "artifactId": f"{dataset_id}:{artifact.get('versionId')}:{payload.target}",
        "datasetIds": [dataset_id],
        "modelIds": [], "documentIds": [], "notebookIds": [],
        "supportsSections": ["Exploratory Data Analysis", "Data Quality", "Model Development"],
        "tags": ["predictive_modeling", "eda", "target_intelligence", "governed_version"],
        "status": "needs_review",
        "importance": "high",
        "workflowStep": "Exploratory Data Analysis",
        "createdBy": _user_scope(user),
        "lineage": {
            "lineage_contract": CANONICAL_DATASET_LINEAGE_CONTRACT,
            "project_id": payload.projectId,
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "projectId": payload.projectId,
            "datasetId": dataset_id,
            "datasetVersion": version_id,
            "datasetVersionId": version_id,
            "artifactChecksum": artifact.get("checksum"),
            "target": payload.target,
            "scopeMode": scope.get("mode"),
            "immutableVersion": True,
            "exact": scope.get("exact"),
            "mddEligible": scope.get("mddEligible"),
        },
        "payload": evidence_payload,
        "governance": {
            "scopeMode": scope.get("mode"),
            "evidenceEligible": True,
            "mddEligible": scope.get("mddEligible"),
            "scopeIdentity": scope_identity(scope),
            "resolvedBy": "server",
        },
    }, user)
    record = upsert_evidence(evidence_record)
    audit_event(
        "eda.target_evidence.created", "project", payload.projectId, "success",
        user_id=_user_scope(user),
        metadata={
            "evidenceId": record.get("evidenceId"), "datasetId": dataset_id,
            "versionId": artifact.get("versionId"), "target": payload.target,
        },
    )
    return {
        "ok": True,
        "evidenceId": record.get("evidenceId"),
        "analysisScope": scope,
        "mddEligible": scope.get("mddEligible"),
        "createdAt": record.get("createdAt"),
    }


# ---------------------------------------------------------------------------
# Part H -- bounded summary export, scope-labelled
# ---------------------------------------------------------------------------


class TargetSummaryExportRequest(BaseModel):
    model_config = {"extra": "forbid"}

    projectId: str
    datasetId: str | None = None
    versionId: str | None = None
    target: str
    eventValue: Any = None
    nonEventValue: Any = None


@router.post("/analytics/target-summary-export")
def target_summary_export(payload: TargetSummaryExportRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Bounded analytical summary for download.

    A draft summary may be exported -- but it is stamped, at the top of the
    document, with markers that make it impossible to mistake for an approved
    governed artifact.
    """
    _check_project_access(user, payload.projectId)
    if bool(payload.datasetId) != bool(payload.versionId):
        raise HTTPException(
            status_code=422,
            detail="datasetId and versionId must be supplied together for an exact governed export.",
        )
    governed = bool(payload.datasetId and payload.versionId)
    if not governed:
        return {
            "ok": True,
            "scopeMode": WORKSPACE_DRAFT,
            "markers": DRAFT_EXPORT_MARKERS,
            "governed": False,
            "datasetId": None,
            "datasetVersionId": None,
            "target": payload.target,
            "evidenceEligible": False,
            "mddEligible": False,
            "generatedAt": now_iso(),
            "disclosure": (
                "Workspace Draft. This summary is not governed evidence, is not pinned to an immutable dataset "
                "version, and is not Model Development Document eligible."
            ),
        }

    active = _require_active_version(
        user,
        payload.projectId,
        str(payload.datasetId),
        payload.versionId,
    )
    assessment = compute_target_assessment(
        user_scope=_user_scope(user), project_id=payload.projectId, dataset_id=active["dataset_id"],
        version_id=active["dataset_version_id"], target=payload.target,
        event_value=payload.eventValue, non_event_value=payload.nonEventValue,
    )
    scope = assessment.get("analysisScope") or {}
    return {
        "ok": True,
        "scopeMode": scope.get("mode"),
        "markers": [],
        "governed": is_governed(scope),
        "datasetId": scope.get("datasetId"),
        "datasetVersionId": scope.get("datasetVersionId"),
        "artifactChecksum": scope.get("artifactChecksum"),
        "target": payload.target,
        "exact": scope.get("exact"),
        "sampled": scope.get("sampled"),
        "evidenceEligible": scope.get("evidenceEligible"),
        "mddEligible": scope.get("mddEligible"),
        "generatedAt": now_iso(),
        "classBalance": assessment.get("classBalance"),
        "imbalance": assessment.get("imbalance"),
        "confidenceInterval": assessment.get("confidenceInterval"),
        "disclosure": scope.get("disclosure"),
    }


# ---------------------------------------------------------------------------
# Part D -- durable, scope-aware target findings
# ---------------------------------------------------------------------------


class TargetFindingRequest(BaseModel):
    projectId: str
    # Scope is DERIVED: supplying a dataset + version produces a governed
    # finding only after the server resolves them; otherwise the finding is a
    # draft pinned to the workspace fingerprint the client observed.
    datasetId: str = ""
    versionId: str = ""
    workspaceFingerprint: str = ""
    target: str = ""
    analysisType: str = "target_intelligence"
    title: str = Field(min_length=1, max_length=300)
    detail: str = Field(default="", max_length=8000)
    severity: str = "review"
    status: str = "open"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TargetFindingUpdateRequest(BaseModel):
    projectId: str
    title: str | None = Field(default=None, max_length=300)
    detail: str | None = Field(default=None, max_length=8000)
    severity: str | None = None
    status: str | None = None
    metadata: Dict[str, Any] | None = None


class TargetFindingPromoteRequest(BaseModel):
    projectId: str
    datasetId: str
    versionId: str


ALLOWED_SEVERITIES = {"info", "review", "warning", "blocker"}
ALLOWED_STATUSES = {"open", "reviewed", "resolved"}

SCOPE_LABELS = {
    GOVERNED_VERSION: "Governed Finding",
    WORKSPACE_DRAFT: "Draft Finding",
    "legacy_unscoped": "Legacy Finding (scope unknown)",
}


def _api_finding(record: Dict[str, Any]) -> Dict[str, Any]:
    scope_mode = str(record.get("scope_mode") or "legacy_unscoped")
    return {
        "targetFindingId": record.get("target_finding_id"),
        "projectId": record.get("project_id"),
        "scopeMode": scope_mode,
        "scopeLabel": SCOPE_LABELS.get(scope_mode, "Legacy Finding (scope unknown)"),
        "governed": scope_mode == GOVERNED_VERSION,
        # Governed identity is only reported for a governed finding; a draft
        # finding reports null rather than an empty string that could be read as
        # "some version".
        "datasetId": (record.get("dataset_id") or None) if scope_mode == GOVERNED_VERSION else None,
        "versionId": (record.get("dataset_version_id") or None) if scope_mode == GOVERNED_VERSION else None,
        "artifactChecksum": (record.get("artifact_checksum") or None) if scope_mode == GOVERNED_VERSION else None,
        "workspaceFingerprint": record.get("workspace_fingerprint") or None,
        "target": record.get("target"),
        "analysisType": record.get("analysis_type"),
        "title": record.get("title"),
        "detail": record.get("detail"),
        "severity": record.get("severity"),
        "status": record.get("status"),
        "createdByUserId": record.get("created_by_user_id"),
        "createdAt": record.get("created_at"),
        "updatedAt": record.get("updated_at"),
        "promotedFromFindingId": record.get("promoted_from_finding_id"),
        "promotedAt": record.get("promoted_at"),
        "metadata": record.get("metadata_json") or {},
    }


def _bounded_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    if not metadata:
        return {}
    return _bounded(metadata, label="A target finding payload")


def _resolve_finding_scope(payload: TargetFindingRequest, user: Dict[str, Any]) -> Dict[str, Any]:
    """Derives the finding's scope from server state.

    A caller that supplies a dataset and version gets a GOVERNED finding only if
    the dataset authorizes, is linked to the project, and the version and its
    artifact resolve. Anything else is a draft pinned to the workspace
    fingerprint -- never a governed row with blank identity.
    """
    if bool(payload.datasetId) != bool(payload.versionId):
        raise HTTPException(
            status_code=422,
            detail="datasetId and versionId must be supplied together for an exact governed finding.",
        )
    if payload.datasetId and payload.versionId:
        require_dataset(payload.datasetId)
        active = _require_active_version(
            user,
            payload.projectId,
            payload.datasetId,
            payload.versionId,
        )
        artifact = _assert_target_exists_in_version(active["dataset_id"], active["dataset_version_id"], payload.target) if payload.target else _resolve_version_artifact(active["dataset_id"], active["dataset_version_id"])
        if str(artifact.get("versionId")) != str(payload.versionId):
            raise HTTPException(status_code=422, detail="The requested dataset version could not be resolved exactly.")
        return {
            "scope_mode": GOVERNED_VERSION,
            "dataset_id": active["dataset_id"],
            "dataset_version_id": str(artifact.get("versionId")),
            "artifact_checksum": str(artifact.get("checksum") or ""),
            "workspace_fingerprint": "",
        }
    return {
        "scope_mode": WORKSPACE_DRAFT,
        "dataset_id": "",
        "dataset_version_id": "",
        "artifact_checksum": "",
        "workspace_fingerprint": payload.workspaceFingerprint or "",
    }


@router.get("/analytics/target-findings")
def list_target_findings(
    projectId: str = Query(...),
    scopeMode: Optional[str] = Query(default=None),
    datasetId: Optional[str] = Query(default=None),
    versionId: Optional[str] = Query(default=None),
    workspaceFingerprint: Optional[str] = Query(default=None),
    target: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Scope-aware listing.

    A governed query returns only findings pinned to that exact version; a draft
    query returns only findings pinned to that exact workspace fingerprint.
    Legacy rows are returned separately and labeled, never mixed in as governed.
    """
    _check_project_access(user, projectId)
    service = _service()
    records: List[Dict[str, Any]] = service.target_findings.list(
        project_id=projectId, scope_mode=scopeMode, dataset_id=datasetId, version_id=versionId,
        workspace_fingerprint=workspaceFingerprint, target=target, include_legacy=scopeMode is None,
    )
    legacy = service.target_findings.list_legacy(project_id=projectId, target=target) if scopeMode else []
    return {
        "ok": True,
        "scopeMode": scopeMode,
        "findings": [_api_finding(record) for record in records],
        "legacyFindings": [_api_finding(record) for record in legacy],
        "count": len(records),
    }


@router.post("/analytics/target-findings")
def create_target_finding(payload: TargetFindingRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _check_project_access(user, payload.projectId)
    if payload.severity not in ALLOWED_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"Unsupported severity. Use one of: {', '.join(sorted(ALLOWED_SEVERITIES))}.")
    if payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported status. Use one of: {', '.join(sorted(ALLOWED_STATUSES))}.")

    scope = _resolve_finding_scope(payload, user)
    service = _service()
    service.ensure_project(payload.projectId, user)
    timestamp = now_iso()
    record = service.target_findings.upsert({
        "target_finding_id": f"tfind_{uuid.uuid4().hex}",
        "project_id": payload.projectId,
        "target": payload.target,
        "analysis_type": payload.analysisType,
        "title": payload.title.strip(),
        "detail": payload.detail.strip(),
        "severity": payload.severity,
        "status": payload.status,
        "created_by_user_id": _user_scope(user),
        "created_at": timestamp,
        "updated_at": timestamp,
        "metadata_json": _bounded_metadata(payload.metadata),
        **scope,
    })
    audit_event(
        "eda.target_finding.created", "project", payload.projectId, "success",
        user_id=_user_scope(user),
        metadata={"target": payload.target, "scopeMode": scope["scope_mode"], "versionId": scope["dataset_version_id"]},
    )
    return {"ok": True, "finding": _api_finding(record)}


@router.put("/analytics/target-findings/{finding_id}")
def update_target_finding(
    finding_id: str,
    payload: TargetFindingUpdateRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _check_project_access(user, payload.projectId)
    service = _service()
    existing = service.target_findings.get(finding_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Target finding not found.")
    if str(existing.get("project_id")) != payload.projectId:
        raise HTTPException(status_code=403, detail="This finding belongs to a different project.")
    if str(existing.get("scope_mode")) == GOVERNED_VERSION:
        _require_active_version(
            user,
            payload.projectId,
            str(existing.get("dataset_id") or ""),
            str(existing.get("dataset_version_id") or ""),
        )
    if payload.severity is not None and payload.severity not in ALLOWED_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"Unsupported severity. Use one of: {', '.join(sorted(ALLOWED_SEVERITIES))}.")
    if payload.status is not None and payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported status. Use one of: {', '.join(sorted(ALLOWED_STATUSES))}.")

    record = service.target_findings.upsert({
        **existing,
        "title": (payload.title if payload.title is not None else existing.get("title")),
        "detail": (payload.detail if payload.detail is not None else existing.get("detail")),
        "severity": (payload.severity or existing.get("severity")),
        "status": (payload.status or existing.get("status")),
        "metadata_json": _bounded_metadata(
            payload.metadata if payload.metadata is not None else (existing.get("metadata_json") or {})
        ),
        "updated_at": now_iso(),
    })
    return {"ok": True, "finding": _api_finding(record)}


@router.post("/analytics/target-findings/{finding_id}/promote")
def promote_target_finding(
    finding_id: str,
    payload: TargetFindingPromoteRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Controlled carry-forward: COPY a draft finding onto a governed version.

    Explicitly a copy, never a mutation. The draft record is left exactly as it
    was, the new governed record starts at status `open`, and the source id and
    promotion timestamp are recorded. Nothing is auto-reviewed or auto-resolved,
    and no promotion happens automatically on registration.
    """
    _check_project_access(user, payload.projectId)
    service = _service()
    existing = service.target_findings.get(finding_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Target finding not found.")
    if str(existing.get("project_id")) != payload.projectId:
        raise HTTPException(status_code=403, detail="This finding belongs to a different project.")
    if str(existing.get("scope_mode")) == GOVERNED_VERSION:
        raise HTTPException(status_code=409, detail="This finding is already a governed finding.")

    require_dataset(payload.datasetId)
    active = _require_active_version(
        user,
        payload.projectId,
        payload.datasetId,
        payload.versionId,
    )
    target = str(existing.get("target") or "")
    artifact = (
        _assert_target_exists_in_version(active["dataset_id"], active["dataset_version_id"], target)
        if target
        else _resolve_version_artifact(active["dataset_id"], active["dataset_version_id"])
    )

    timestamp = now_iso()
    record = service.target_findings.upsert({
        "target_finding_id": f"tfind_{uuid.uuid4().hex}",
        "project_id": payload.projectId,
        "dataset_id": active["dataset_id"],
        "dataset_version_id": str(artifact.get("versionId")),
        "artifact_checksum": str(artifact.get("checksum") or ""),
        "workspace_fingerprint": "",
        "scope_mode": GOVERNED_VERSION,
        "target": target,
        "analysis_type": existing.get("analysis_type") or "target_intelligence",
        "title": existing.get("title"),
        "detail": existing.get("detail"),
        "severity": existing.get("severity") or "review",
        # Always starts open. A carried-forward observation has not been reviewed
        # against the registered version yet.
        "status": "open",
        "created_by_user_id": _user_scope(user),
        "created_at": timestamp,
        "updated_at": timestamp,
        "metadata_json": existing.get("metadata_json") or {},
        "promoted_from_finding_id": finding_id,
        "promoted_at": timestamp,
    })
    audit_event(
        "eda.target_finding.promoted", "project", payload.projectId, "success",
        user_id=_user_scope(user),
        metadata={"sourceFindingId": finding_id, "versionId": artifact.get("versionId")},
    )
    return {"ok": True, "finding": _api_finding(record), "sourceFindingId": finding_id}


@router.delete("/analytics/target-findings/{finding_id}")
def delete_target_finding(
    finding_id: str,
    projectId: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _check_project_access(user, projectId)
    service = _service()
    existing = service.target_findings.get(finding_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Target finding not found.")
    if str(existing.get("project_id")) != projectId:
        raise HTTPException(status_code=403, detail="This finding belongs to a different project.")
    service.target_findings.delete(finding_id)
    return {"ok": True, "targetFindingId": finding_id}
