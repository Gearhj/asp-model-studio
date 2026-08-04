"""Analysis Scope -- the server-derived governance contract for EDA analysis.

Why this exists
---------------
Target Intelligence supports two analytical paths. One scans an immutable
registered Dataset Library version; the other aggregates the complete in-memory
workspace population. Both can be exact and both can cover the full population,
so the results LOOK identical -- and until this module existed, an unregistered
upload silently produced results that were presented, exported, and saved to
evidence exactly like version-pinned ones.

That is the defect this module closes. "Exact" is not "governed". "Full
population" is not "governed". "Persistent" is not "MDD eligible". Only an
analysis pinned to a resolved, authorized, immutable artifact is governed, and
only the SERVER may decide that.

Design rules enforced here
--------------------------
1. Scope mode is derived from authoritative server state -- a resolved artifact
   or a loaded workspace frame. It is never read from the request.
2. `evidenceEligible` and `mddEligible` are outputs of this module, never inputs.
   A client that posts `evidenceEligible: true` is ignored.
3. Resolving scope must not cost a second population scan. The governed path is
   built from the artifact record the caller already resolved; the workspace
   fingerprint hashes bounded head/tail slices, never the whole frame.
4. Scope identity participates in cache keys and stale-response rejection, so a
   draft result can never land in a governed panel (or vice versa).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

CONTRACT_VERSION = "analysis-scope/1"

GOVERNED_VERSION = "governed_version"
WORKSPACE_DRAFT = "workspace_draft"
# Only used when NO complete backend population exists -- a bounded browser
# preview. Never governed, never decision-ready, never evidence eligible.
PREVIEW_ONLY = "preview_only"

# Stable, machine-readable reason for a legacy Dataset Version that was
# registered before full artifacts were stored. The version keeps its metadata
# and lineage untouched; it simply cannot support governed full-population
# profiling, and its 5,000-row data_sample.csv is never substituted for it.
FULL_ARTIFACT_MISSING = "full_artifact_missing"

# Rows hashed from each end of the workspace frame to fingerprint its content.
# Bounded on purpose: fingerprinting must never become a second full scan.
FINGERPRINT_EDGE_ROWS = 50

GOVERNED_DISCLOSURE = (
    "Governed Dataset Version. This analysis is pinned to an immutable, registered dataset version "
    "and is eligible to be saved as governed evidence."
)

WORKSPACE_DISCLOSURE = (
    "Workspace Draft Analysis. This analysis uses the current full backend workspace population. "
    "It may be exact, but it is not tied to an immutable dataset version, so it is not eligible for "
    "governed evidence or Model Development Document use. Changing or replacing the workspace dataset "
    "invalidates it. Register or link a Dataset Library version to produce governed evidence."
)

SAMPLED_MDD_DISCLOSURE = (
    "This governed analysis was estimated from a stratified sample rather than an exact full-population "
    "scan, so it is recorded as evidence but is not Model Development Document eligible."
)

# Short banner labels, shared by the API and the UI so the two cannot drift.
SCOPE_LABELS = {
    GOVERNED_VERSION: "Governed Dataset Version",
    WORKSPACE_DRAFT: "Workspace Draft Analysis",
    PREVIEW_ONLY: "Browser Preview Only",
}

PREVIEW_DISCLOSURE = (
    "Browser Preview Only. These statistics describe a bounded preview, not the modeling population. "
    "They are for inspection only: they do not drive readiness, Information Value, automatic predictor "
    "exclusion, or evidence."
)

LEGACY_ARTIFACT_DISCLOSURE = (
    "Legacy Dataset Version: Full Artifact Unavailable. This version was registered before ATLAS stored a "
    "complete data artifact, so it cannot support governed full-population profiling. Select a complete "
    "governed version, or re-register the original source as a new immutable version."
)

DRAFT_EXPORT_MARKERS = [
    "Workspace Draft",
    "Not Governed Evidence",
    "Not Version-Pinned",
    "Not MDD Eligible",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def workspace_fingerprint(df: Any, target: Optional[str], source: Optional[Dict[str, Any]] = None) -> str:
    """Durable identity for one loaded workspace dataset.

    Combines predictor shape, predictor column names, the target *name*, and the
    declared source with a content hash of bounded predictor-only head/tail
    slices.  Target values are intentionally excluded: the workspace fingerprint
    is structural identity, while target-directed cache identity is supplied by
    the exact materialized development target.  A sealed-holdout target change
    therefore cannot invalidate or influence structural EDA.

    Deliberately NOT a whole-frame hash: `pd.util.hash_pandas_object` over a
    170,884 x 31 frame is a second full pass, and scope resolution must be free.
    """
    try:
        import pandas as pd  # noqa: PLC0415

        target_name = str(target or "")
        structural_df = df.drop(columns=[target_name], errors="ignore")
        identity: Dict[str, Any] = {
            "columns": [str(column) for column in structural_df.columns],
            "shape": [int(structural_df.shape[0]), int(structural_df.shape[1])],
            # Preserve target schema identity without hashing any target value.
            "target": target_name,
            "sourceKind": str((source or {}).get("kind") or ""),
            "sourceFilename": str((source or {}).get("filename") or ""),
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8"))
        edge = min(FINGERPRINT_EDGE_ROWS, int(structural_df.shape[0]))
        if edge:
            for slice_frame in (
                structural_df.head(edge),
                structural_df.tail(edge),
            ):
                digest.update(pd.util.hash_pandas_object(slice_frame, index=False).values.tobytes())
        return f"wsfp_{digest.hexdigest()[:32]}"
    except Exception:  # noqa: BLE001 - a fingerprint must never break an analysis
        return "wsfp_unavailable"


def governed_scope(
    *,
    project_id: str,
    dataset_id: str,
    dataset_name: str,
    version_id: str,
    artifact_checksum: Optional[str],
    target: str,
    population_rows: int,
    exact: bool,
    analysis_source: str,
    immutable: bool = True,
) -> Dict[str, Any]:
    """Scope for an analysis pinned to a resolved immutable artifact.

    Callers must only reach this AFTER project authorization, dataset
    authorization, version resolution, and artifact resolution have all
    succeeded -- this function records that outcome, it does not perform it.
    """
    sampled = not exact
    return {
        "contractVersion": CONTRACT_VERSION,
        "mode": GOVERNED_VERSION,
        "label": SCOPE_LABELS[GOVERNED_VERSION],
        "projectId": project_id,
        "datasetId": dataset_id,
        "datasetVersionId": version_id,
        "workspaceDatasetId": None,
        "datasetName": dataset_name,
        "datasetFingerprint": None,
        "artifactChecksum": artifact_checksum,
        "target": target,
        "populationRows": int(population_rows or 0),
        "exact": bool(exact),
        "sampled": bool(sampled),
        "immutableVersion": bool(immutable),
        "analysisSource": analysis_source,
        # A governed analysis is evidence eligible. MDD eligibility additionally
        # requires exact counts: a stratified estimate is a legitimate governed
        # record but is not a figure to quote in a Model Development Document.
        "evidenceEligible": True,
        "mddEligible": bool(exact),
        "disclosure": GOVERNED_DISCLOSURE if exact else f"{GOVERNED_DISCLOSURE} {SAMPLED_MDD_DISCLOSURE}",
        "resolvedAt": _now(),
    }


def workspace_scope(
    *,
    project_id: str,
    target: str,
    population_rows: int,
    fingerprint: str,
    dataset_name: str = "Workspace dataset",
    analysis_source: str,
    exact: bool = True,
    linked_dataset_id: Optional[str] = None,
    linked_version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Scope for an analysis over the in-memory workspace population.

    `linked*` values are provenance HINTS only -- they record that the workspace
    frame was loaded from a Library version so the UI can offer a one-click
    governed rerun. They are never promoted into `datasetVersionId`, because the
    in-memory frame can have been mutated since it was loaded and is therefore
    not the immutable artifact.
    """
    return {
        "contractVersion": CONTRACT_VERSION,
        "mode": WORKSPACE_DRAFT,
        "label": SCOPE_LABELS[WORKSPACE_DRAFT],
        "projectId": project_id,
        # Never invented. A draft analysis has no governed dataset identity.
        "datasetId": None,
        "datasetVersionId": None,
        "workspaceDatasetId": fingerprint,
        "datasetName": dataset_name,
        "datasetFingerprint": fingerprint,
        "artifactChecksum": None,
        "target": target,
        "populationRows": int(population_rows or 0),
        "exact": bool(exact),
        "sampled": not bool(exact),
        "immutableVersion": False,
        "analysisSource": analysis_source,
        "evidenceEligible": False,
        "mddEligible": False,
        "disclosure": WORKSPACE_DISCLOSURE,
        "resolvedAt": _now(),
        "suggestedGovernedSource": (
            {"datasetId": linked_dataset_id, "versionId": linked_version_id}
            if linked_dataset_id and linked_version_id
            else None
        ),
    }


def preview_scope(
    *,
    project_id: str,
    target: str,
    profiled_rows: int,
    population_rows: int,
    fingerprint: str,
    dataset_name: str = "Browser preview",
    analysis_source: str,
) -> Dict[str, Any]:
    """Scope for a bounded browser preview.

    Only produced when NO complete backend population exists. It is never
    governed and never decision-ready -- it exists so the UI can say honestly
    "this is a preview" instead of a caller silently presenting preview numbers
    as population numbers, which is exactly the defect this phase closes.
    """
    return {
        "contractVersion": CONTRACT_VERSION,
        "mode": PREVIEW_ONLY,
        "label": SCOPE_LABELS[PREVIEW_ONLY],
        "projectId": project_id,
        "datasetId": None,
        "datasetVersionId": None,
        "workspaceDatasetId": fingerprint,
        "datasetName": dataset_name,
        "datasetFingerprint": fingerprint,
        "artifactChecksum": None,
        "target": target,
        "populationRows": int(population_rows or 0),
        "profiledRows": int(profiled_rows or 0),
        "exact": False,
        "sampled": True,
        "immutableVersion": False,
        "analysisSource": analysis_source,
        "evidenceEligible": False,
        "mddEligible": False,
        "decisionReady": False,
        "disclosure": PREVIEW_DISCLOSURE,
        "resolvedAt": _now(),
    }


def scope_identity(scope: Dict[str, Any]) -> str:
    """Stable identity string for cache keys and stale-response rejection.

    Two results are interchangeable only when this matches. It therefore
    includes the mode, so a draft result can never satisfy a governed request.
    """
    if not scope:
        return "scope:none"
    return "|".join([
        "scope",
        str(scope.get("mode") or ""),
        str(scope.get("projectId") or ""),
        str(scope.get("datasetId") or ""),
        str(scope.get("datasetVersionId") or ""),
        str(scope.get("datasetFingerprint") or ""),
        str(scope.get("artifactChecksum") or ""),
        str(scope.get("target") or ""),
    ])


def is_governed(scope: Optional[Dict[str, Any]]) -> bool:
    return bool(scope) and scope.get("mode") == GOVERNED_VERSION


def require_evidence_eligible(scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Gate for anything that produces governed evidence.

    Raises 409 for an otherwise valid workspace analysis -- the request is
    well-formed and the analysis is real, it is simply not governed yet, and the
    caller has a clear remedy (register or link a version).
    """
    if not scope:
        raise HTTPException(
            status_code=409,
            detail="Analytical scope could not be resolved, so governed evidence cannot be created.",
        )
    if not is_governed(scope):
        raise HTTPException(
            status_code=409,
            detail=(
                "This is a Workspace Draft Analysis and is not eligible to be saved as governed evidence. "
                "Register or link an immutable Dataset Library version and rerun the analysis against that "
                "version first."
            ),
        )
    if not scope.get("evidenceEligible"):
        raise HTTPException(
            status_code=409,
            detail="The resolved analytical scope is not eligible for governed evidence.",
        )
    return scope
