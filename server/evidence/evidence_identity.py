"""Fail-closed canonical identity checks for governed evidence persistence."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import ValidationError

from ..core.modeling_scope import authorize_modeling_scope
from ..datasets.dataset_identity import assert_expected_active_identity
from ..security.security_store import audit_event
from .evidence_types import (
    CANONICAL_DATASET_LINEAGE_CONTRACT,
    CanonicalEvidenceLineage,
)


CANONICAL_PREPARATION_EVIDENCE_TYPES = {
    "eda",
    "outliers",
    "missing_values",
    "feature_engineering",
    "model_training",
}
CANONICAL_SPLIT_TAGS = {"feature_gate", "validation_design"}
CANONICAL_DATASET_PREPROCESSING_TAGS = {"bureau_review"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lineage(payload: Dict[str, Any]) -> Dict[str, Any]:
    value = payload.get("lineage")
    return value if isinstance(value, dict) else {}


def is_dataset_catalog_evidence(payload: Dict[str, Any]) -> bool:
    """Return whether an item represents an auto-captured Dataset Library row."""
    evidence_type = _clean(
        payload.get("evidenceType") or payload.get("evidence_type")
    ).casefold()
    artifact_type = _clean(
        payload.get("artifactType") or payload.get("artifact_type")
    ).casefold()
    source_page = _clean(
        payload.get("sourcePage") or payload.get("source_page")
    ).casefold()
    source_route = _clean(
        payload.get("sourceRoute") or payload.get("source_route")
    ).casefold()
    return bool(
        evidence_type == "dataset"
        and artifact_type == "dataset"
        and (
            source_page == "dataset library"
            or source_route.startswith("/datasets/")
        )
    )


def has_complete_canonical_dataset_lineage(payload: Dict[str, Any]) -> bool:
    """Check persisted canonical fields without resolving or migrating them.

    This is intentionally a structural read-time check. Legacy Dataset Library
    captures that predate immutable version lineage stay on disk but are
    quarantined from evidence reads until they are captured again from an exact
    project-to-version link.
    """
    project_id = _clean(payload.get("project_id"))
    dataset_id = _clean(payload.get("dataset_id"))
    dataset_version_id = _clean(payload.get("dataset_version_id"))
    if (
        not project_id
        or not dataset_id
        or not dataset_version_id
        or _clean(payload.get("lineage_contract"))
        != CANONICAL_DATASET_LINEAGE_CONTRACT
    ):
        return False

    compatibility_project_id = _clean(payload.get("projectId"))
    if compatibility_project_id and compatibility_project_id != project_id:
        return False
    dataset_ids = payload.get("datasetIds")
    if dataset_ids is not None:
        if not isinstance(dataset_ids, list):
            return False
        if [_clean(value) for value in dataset_ids] != [dataset_id]:
            return False
    return True


def assert_evidence_lineage_immutable(
    existing: Dict[str, Any],
    candidate: Dict[str, Any],
) -> None:
    """Prevent an existing evidence ID from changing dataset identity.

    Canonical evidence is an immutable statement about one project, dataset,
    and registered dataset version. Metadata may be edited, but changing,
    adding, or removing that triple requires a newly captured evidence item
    with a new ID. This also prevents an alias-only legacy record from being
    silently upgraded in place.
    """

    if not existing:
        return
    existing_is_canonical = has_complete_canonical_dataset_lineage(existing)
    candidate_is_canonical = has_complete_canonical_dataset_lineage(candidate)
    if not existing_is_canonical and not candidate_is_canonical:
        return

    canonical_keys = ("project_id", "dataset_id", "dataset_version_id")
    same_identity = bool(
        existing_is_canonical
        and candidate_is_canonical
        and all(
            _clean(existing.get(key)) == _clean(candidate.get(key))
            for key in canonical_keys
        )
    )
    if not same_identity:
        raise HTTPException(
            status_code=409,
            detail=(
                "Canonical evidence dataset lineage is immutable for an "
                "existing evidence ID. Capture a new evidence item for the "
                "new project, dataset, or dataset version."
            ),
        )


def requires_canonical_dataset_lineage(payload: Dict[str, Any]) -> bool:
    """Identify Phase 2A evidence even if a crafted request omits the marker."""
    evidence_type = _clean(payload.get("evidenceType") or payload.get("evidence_type"))
    source_page = _clean(payload.get("sourcePage") or payload.get("source_page"))
    source_route = _clean(payload.get("sourceRoute") or payload.get("source_route"))
    tags = payload.get("tags")
    tag_set = {
        _clean(tag)
        for tag in (tags if isinstance(tags, list) else [])
        if _clean(tag)
    }
    lineage = _lineage(payload)
    return bool(
        _clean(payload.get("lineage_contract"))
        or any(
            _clean(payload.get(key))
            for key in ("project_id", "dataset_id", "dataset_version_id")
        )
        or any(
            _clean(lineage.get(key))
            for key in ("project_id", "dataset_id", "dataset_version_id")
        )
        or evidence_type in CANONICAL_PREPARATION_EVIDENCE_TYPES
        or (
            evidence_type == "governance"
            and bool(tag_set & CANONICAL_SPLIT_TAGS)
        )
        or (
            evidence_type == "dataset"
            and (
                is_dataset_catalog_evidence(payload)
                or bool(tag_set & CANONICAL_DATASET_PREPROCESSING_TAGS)
                or source_route == "/step01"
                or source_route.startswith("/step01?")
                or (
                    source_page.casefold() == "data acquisition"
                    and "predictive_modeling" in tag_set
                )
            )
        )
    )


def _reject_contradiction(label: str) -> None:
    raise HTTPException(
        status_code=409,
        detail=(
            f"Evidence {label} contradicts the exact canonical Dataset Library "
            "identity. Reload the project before capturing evidence."
        ),
    )


def _canonical_claim(payload: Dict[str, Any]) -> CanonicalEvidenceLineage:
    try:
        return CanonicalEvidenceLineage(
            project_id=payload.get("project_id"),
            dataset_id=payload.get("dataset_id"),
            dataset_version_id=payload.get("dataset_version_id"),
            lineage_contract=payload.get("lineage_contract"),
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Phase 2A preparation and training evidence requires exact "
                "project_id, dataset_id, and dataset_version_id fields from the "
                "active immutable Dataset Library version."
            ),
        ) from exc


def _assert_compatibility_claims(
    payload: Dict[str, Any],
    canonical: CanonicalEvidenceLineage,
    *,
    path_project_id: Optional[str],
) -> None:
    lineage = _lineage(payload)
    comparisons = (
        ("path project_id", path_project_id, canonical.project_id),
        ("projectId", payload.get("projectId"), canonical.project_id),
        ("dataset_version", payload.get("dataset_version"), canonical.dataset_version_id),
        ("lineage.project_id", lineage.get("project_id"), canonical.project_id),
        ("lineage.dataset_id", lineage.get("dataset_id"), canonical.dataset_id),
        (
            "lineage.dataset_version_id",
            lineage.get("dataset_version_id"),
            canonical.dataset_version_id,
        ),
        ("lineage.projectId", lineage.get("projectId"), canonical.project_id),
        ("lineage.datasetId", lineage.get("datasetId"), canonical.dataset_id),
        (
            "lineage.datasetVersion",
            lineage.get("datasetVersion"),
            canonical.dataset_version_id,
        ),
        (
            "lineage.lineage_contract",
            lineage.get("lineage_contract"),
            CANONICAL_DATASET_LINEAGE_CONTRACT,
        ),
    )
    for label, supplied, expected in comparisons:
        if _clean(supplied) and _clean(supplied) != expected:
            _reject_contradiction(label)

    dataset_ids = payload.get("datasetIds")
    if dataset_ids is not None:
        supplied_ids = (
            [_clean(value) for value in dataset_ids]
            if isinstance(dataset_ids, list)
            else [_clean(dataset_ids)]
        )
        if supplied_ids != [canonical.dataset_id]:
            _reject_contradiction("datasetIds")


def authorize_and_normalize_evidence(
    payload: Dict[str, Any],
    user: Dict[str, Any],
    *,
    path_project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Authorize a project and validate canonical lineage before any write.

    Existing non-modeling evidence remains compatible with ``projectId``.
    Phase 2A evidence, or any evidence that claims canonical lineage, must use
    the snake-case canonical fields. Legacy aliases are comparison-only inputs
    and are regenerated from the verified identity.
    """
    requires_canonical = requires_canonical_dataset_lineage(payload)
    claimed_project_id = _clean(payload.get("project_id"))
    compatibility_project_id = _clean(payload.get("projectId"))
    route_project_id = _clean(path_project_id)
    project_id = (
        claimed_project_id
        or route_project_id
        or compatibility_project_id
    )
    if not project_id:
        raise HTTPException(
            status_code=400,
            detail="A project_id is required before evidence can be persisted.",
        )
    if route_project_id and route_project_id != project_id:
        _reject_contradiction("project_id")
    if not requires_canonical and compatibility_project_id and claimed_project_id:
        if compatibility_project_id != claimed_project_id:
            _reject_contradiction("projectId")

    # This checks existence plus edit authorization and selects the exact
    # project-scoped DATASTORE used by active_dataset_identity.
    authorize_modeling_scope(user, project_id, "edit")

    if not requires_canonical:
        return {**payload, "projectId": project_id}

    canonical = _canonical_claim(payload)
    _assert_compatibility_claims(
        payload,
        canonical,
        path_project_id=path_project_id,
    )
    active = assert_expected_active_identity(
        canonical.project_id,
        expected_dataset_id=canonical.dataset_id,
        expected_dataset_version_id=canonical.dataset_version_id,
        legacy_dataset_version=payload.get("dataset_version"),
        user=user,
    )
    lineage = {
        **_lineage(payload),
        "project_id": active["project_id"],
        "dataset_id": active["dataset_id"],
        "dataset_version_id": active["dataset_version_id"],
        "lineage_contract": CANONICAL_DATASET_LINEAGE_CONTRACT,
        # Compatibility aliases are outputs derived from canonical authority.
        "projectId": active["project_id"],
        "datasetId": active["dataset_id"],
        "datasetVersion": active["dataset_version_id"],
    }
    normalized = {
        **payload,
        "lineage_contract": CANONICAL_DATASET_LINEAGE_CONTRACT,
        "project_id": active["project_id"],
        "dataset_id": active["dataset_id"],
        "dataset_version_id": active["dataset_version_id"],
        "projectId": active["project_id"],
        "datasetIds": [active["dataset_id"]],
        "lineage": lineage,
    }
    audit_event(
        "evidence.dataset_identity.validated",
        "dataset_version",
        active["dataset_version_id"],
        "success",
        user_id=user.get("userId"),
        metadata={
            "projectId": active["project_id"],
            "datasetId": active["dataset_id"],
            "evidenceType": normalized.get("evidenceType"),
        },
    )
    return normalized
