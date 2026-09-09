"""Read-only, authenticated discovery of completed NFL research evidence.

The API accepts opaque artifact IDs, never arbitrary file paths. Downloads
revalidate the exact bytes referenced by a completed local publication.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..security.security_store import require_user
from ..sharing.sharing_service import SharingService

router = APIRouter()
ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "sports-project-nfl-overnight-model-lab-v1"
LOCAL_OUTPUTS = (
    ROOT / "outputs/nfl-overnight-model-laboratory-v1",
    ROOT / "outputs/nfl-semantic-lab-v1",
    ROOT / "outputs/nfl-labs-simulation-v1",
    ROOT / "outputs/nfl-research-benchmarks-v1",
    ROOT / "outputs/mlb-v18-cold-start-reconciliation-v1",
)
ALLOWED_ROOTS = (*LOCAL_OUTPUTS,
    Path(r"C:\Users\james\asp-data-staging\nfl\overnight-model-laboratory-v1"),
    Path(r"C:\Users\james\asp-data-staging\nfl\semantic-lab-v1"),
    Path(r"C:\Users\james\asp-model-exchange\contracts"),
    Path(r"C:\Users\james\asp-model-exchange\nfl-labs-simulation-supplements"),
    ROOT / "server/sports_nfl_m1")
ALLOWED_ROOTS = (*ALLOWED_ROOTS, ROOT / "outputs/nfl-semantic-session-v1")


def _permission(user: dict[str, Any], permission: str = "view"):
    if not SharingService().check_permission(user, "project", PROJECT_ID, permission)["allowed"]:
        raise HTTPException(status_code=403, detail="NFL laboratory project access is required.")


def _checked(path: str | Path, sha: str | None = None) -> tuple[Path, bytes, str]:
    resolved = Path(path).resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in ALLOWED_ROOTS):
        raise ValueError("Artifact is outside the published laboratory roots.")
    if not resolved.is_file() or resolved.suffix not in {".json", ".jsonl", ".md", ".png", ".csv", ".xlsx", ".joblib", ".parquet"}:
        raise ValueError("Published artifact is absent or unsupported.")
    raw = resolved.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if sha and actual != sha:
        raise ValueError("Published artifact checksum mismatch.")
    return resolved, raw, actual


def laboratory_catalog() -> tuple[dict[str, Any], dict[str, tuple[Path, str]]]:
    artifacts: list[dict[str, Any]] = []
    allowed: dict[str, tuple[Path, str]] = {}
    warnings: list[str] = []
    groups = []

    def artifact(path: str | Path, label: str, category: str, sha: str | None = None):
        try:
            resolved, raw, digest = _checked(path, sha)
            identifier = hashlib.sha256((str(resolved) + digest).encode()).hexdigest()[:32]
            if identifier not in allowed:
                allowed[identifier] = (resolved, digest)
                artifacts.append({"id": identifier, "label": label, "category": category, "sha256": digest,
                                  "bytes": len(raw), "filename": resolved.name,
                                  "href": f"/sports/nfl/laboratory/artifacts/{identifier}"})
            return json.loads(raw) if resolved.suffix == ".json" else None
        except (OSError, ValueError) as exc:
            warnings.append(f"{label}: {exc}")
            return None

    matrix_path = ROOT / "server/sports_nfl_m1/nfl_overnight_matrix_v1.json"
    matrix = artifact(matrix_path, "Frozen original 22-pipeline matrix", "Original laboratory") or {}
    for filename, label in (("NFL_TARGET_CONTRACT_V1.json", "Exact NFL training targets and derived quantities"),
                            ("NFL_Feature_Treatment_Specification.xlsx", "Editable all-feature treatment workbook")):
        path = ROOT / "outputs/nfl-semantic-session-v1" / filename
        if path.is_file():
            artifact(path, label, "Semantic target and feature contracts")
    enhanced_policy_sha = "ad3f1e57106f58b76b835cb7cd3912c26d357e05fd85f9495dbccd9367edd6d6"
    enhanced_policy = LOCAL_OUTPUTS[1] / "policy-supplements/sha256" / enhanced_policy_sha / "feature-treatment-policy.json"
    if enhanced_policy.is_file():
        artifact(enhanced_policy, "All-feature semantic policy with exact definitions and dispositions", "Semantic target and feature contracts", enhanced_policy_sha)

    session_pointer = ROOT / "outputs/nfl-semantic-session-v1/CURRENT.json"
    if session_pointer.is_file():
        session = json.loads(session_pointer.read_text(encoding="utf-8"))
        delivery = artifact(session["manifestPath"], "Complete session delivery manifest", "Session delivery", session["manifestSha256"])
        if delivery and delivery.get("contract") == "NFL_SEMANTIC_SESSION_DELIVERY_V1" and delivery.get("status") == "RESEARCH_SHADOW":
            artifact(session["reportPath"], "Session results and exact consumer instructions", "Session delivery", session["reportSha256"])
            for ref in delivery.get("files", []):
                artifact(ref["path"], Path(ref["path"]).name, "Session delivery", ref["sha256"])
    old_pointer = LOCAL_OUTPUTS[0] / "CURRENT.json"
    if old_pointer.is_file():
        pointer = json.loads(old_pointer.read_text(encoding="utf-8"))
        handoff = artifact(pointer["handoffPath"], "Original laboratory handoff", "Original laboratory", pointer["handoffSha256"])
        if handoff:
            groups.append({"id": "original", "label": "Original laboratory — 22 screening + 2 tuning", "status": "SAVED_DEVELOPMENT_RESULTS",
                           "rows": handoff["leaderboard"], "pairedComparison": handoff["pairedUncertaintyVersusM1"],
                           "note": "Exploratory Development evidence. M1 recipe is fold-refitted, not the operational artifact trained through 2025. Raw score distributions and calibrated probabilities remain distinct."})
            artifact(handoff["reportPath"], "Original laboratory report", "Original laboratory", handoff["reportSha256"])
            for key in ("fittedDevelopmentArtifact", "fittedCalibrationArtifact"):
                ref = handoff.get(key, {})
                if ref.get("path"):
                    artifact(ref["path"], key, "Original laboratory", ref.get("sha256"))
            # Individual result and chart references must match analysis bytes;
            # do not trust a mutable external path merely because it exists.
            analysis_path = Path(handoff["externalManifestPath"]).parent / "analysis/result.json"
            analysis = artifact(analysis_path, "Original analysis and per-fold evidence", "Original laboratory", handoff["analysisSha256"])
            if analysis:
                for chart in analysis.get("charts", []):
                    artifact(chart["path"], Path(chart["path"]).stem.replace("_", " "), "Original charts", chart["sha256"])
                artifact(analysis["treatmentFeatureManifestPath"], "Original fitted treatment manifest", "Original laboratory", analysis["treatmentFeatureManifestSha256"])
                for pipeline in analysis.get("pipelines", []):
                    if pipeline.get("oofPredictionsPath"):
                        artifact(pipeline["oofPredictionsPath"], pipeline["pipelineId"] + " OOF predictions", "Original predictions", pipeline.get("oofPredictionsSha256"))

    # New result publishers own these independent discovery pointers. Missing
    # or incomplete publications remain missing; no completed state is inferred.
    for folder, category in zip(LOCAL_OUTPUTS[1:], ("Semantic laboratory", "Football simulations", "Benchmark scoreboard", "MLB reconciliation")):
        pointer_path = folder / ("current.json" if category == "Benchmark scoreboard" else "CURRENT.json")
        if not pointer_path.is_file():
            continue
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if pointer.get("status") not in {"COMPLETE", "COMPLETED", "RESEARCH_SHADOW", "READY"} and pointer.get("completed") is not True:
            warnings.append(category + ": publication is not complete.")
            continue
        path = pointer.get("resultPath") or pointer.get("path") or pointer.get("handoffPath") or pointer.get("manifestPath")
        sha = pointer.get("resultSha256") or pointer.get("sha256") or pointer.get("handoffSha256") or pointer.get("manifestSha256")
        if not path or not sha:
            warnings.append(category + ": completed discovery needs an exact path and checksum.")
            continue
        document = artifact(path, category + " results", category, sha)
        if not document:
            continue
        if pointer.get("driveHandoffPath") and pointer.get("driveHandoffSha256"):
            drive_handoff = artifact(pointer["driveHandoffPath"], "Independent drive-engine handoff — not M1", "Independent drive research", pointer["driveHandoffSha256"])
            if drive_handoff:
                fit_ref = drive_handoff.get("fitReceipt", {})
                if fit_ref.get("path") and fit_ref.get("sha256"):
                    artifact(fit_ref["path"], "Drive fitted model and observed-state validation receipt", "Independent drive research", fit_ref["sha256"])
                for drive_ref in drive_handoff.get("artifacts", []):
                    child = drive_ref.get("artifact", {})
                    if child.get("path") and child.get("sha256"):
                        drive_body = artifact(child["path"], f"{drive_ref.get('eventId', 'NFL game')} independent drive population", "Independent drive research", child["sha256"])
                        if drive_body:
                            for item in artifacts:
                                if item["sha256"] == child["sha256"]:
                                    item["label"] += " · " + drive_body.get("scenario", {}).get("scenarioId", "BASE")
        for key in ("reportPath", "workbookPath", "policyPath", "targetContractPath", "matrixPath"):
            value = document.get(key) or pointer.get(key)
            if value:
                artifact(value, key.replace("Path", ""), category, document.get(key.replace("Path", "Sha256")) or pointer.get(key.replace("Path", "Sha256")))
        for ref in [*document.get("artifacts", []), *document.get("fittedArtifacts", [])]:
            if isinstance(ref, dict) and ref.get("path") and ref.get("sha256"):
                label = ref.get("label") or " ".join(value for value in (ref.get("pipelineId"), Path(ref["path"]).name) if value)
                artifact(ref["path"], label, category, ref["sha256"])
            elif isinstance(ref, dict) and isinstance(ref.get("artifact"), dict):
                for kind in ("artifact", "manifest"):
                    child = ref.get(kind, {})
                    if child.get("path") and child.get("sha256"):
                        artifact(child["path"], f"{ref.get('eventId', 'simulation')} {kind}", category, child["sha256"])
        if category == "Semantic laboratory":
            run_root = Path(path).resolve().parent
            artifact(folder / "candidate-matrix.json", "Predeclared semantic candidate and tuning matrix", "Semantic target and feature contracts", document["matrixSha256"])
            # Serve only files present in the checksum-bound completed result
            # inventory. Partial runs and guessed filenames are not discovered.
            for ref in document.get("inventory", []):
                relative = Path(ref["path"])
                candidate = (run_root / relative).resolve()
                if not candidate.is_relative_to(run_root):
                    warnings.append("Semantic inventory path is outside its completed run.")
                    continue
                if candidate.suffix not in {".json", ".jsonl", ".parquet"}:
                    continue
                if candidate.name == "pregame_feature_states.parquet":
                    continue
                label = str(relative).replace("\\", " / ").replace("_", " ")
                artifact(candidate, label, "Semantic fold predictions and receipts", ref["sha256"])
            rows = []
            reporting = None
            reporting_pointer = folder / "reporting/CURRENT.json"
            if reporting_pointer.is_file():
                reporting_ref = json.loads(reporting_pointer.read_text(encoding="utf-8"))
                if reporting_ref.get("status") != "COMPLETED" or reporting_ref.get("parentResultSha256") != sha:
                    warnings.append("Semantic reporting supplement is incomplete or references a different result.")
                else:
                    reporting = artifact(reporting_ref["supplementPath"], "Semantic reporting supplement — true expanded counts and subgroup comparisons", "Semantic reporting", reporting_ref["supplementSha256"])
                    if reporting:
                        for ref in reporting.get("artifacts", []):
                            artifact(ref["path"], ref["label"], "Semantic reporting", ref["sha256"])
            for row in document.get("leaderboard", document.get("results", [])):
                metrics = row.get("metrics", {})
                raw = metrics.get("raw", metrics)
                calibrated = metrics.get("calibrated", {})
                subgroups = {name: {**group.get("raw", {}), "calibratedLogLoss": group.get("calibrated", {}).get("multiclassLogLoss")}
                             for name, group in row.get("subgroups", {}).items() if isinstance(group, dict)}
                rows.append({**row, **raw, "calibratedLogLoss": calibrated.get("multiclassLogLoss"),
                             "treatment": row.get("design"), "subgroups": subgroups})
            groups.append({"id": "semantic", "label": category, "status": document.get("status", "COMPLETE"),
                           "rows": rows,
                           "note": document.get("interpretation", "Research only; compare exactly matched Development cohorts."),
                           "pairedComparison": {"fullSeason": document.get("pairedAgainstM1", document.get("pairedComparisons", document.get("pairedComparison"))),
                                                "subgroups": reporting.get("subgroupPairedAgainstM1") if reporting else None}})

    return {"schemaVersion": "NFL_LABORATORY_UI_V1", "projectId": PROJECT_ID,
            "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False,
            "retainedModel": "NFL_M1_XGBOOST", "groups": groups, "artifacts": artifacts,
            "treatments": {**matrix.get("treatments", {}),
                "C1": "Semantic team offense / defense / pace priors, previous-season information, offseason regression and reliability blending. No generic cold-start median.",
                "C2": "C1 plus a lagged passing-personnel mixture from prior-date usage and player history. This is not an assertion of the target game's known starting quarterback; current starter, injury and depth-chart evidence remain unsupported.",
                "C3": "C2 plus bounded fold-local peer pooling where pregame evidence supports it; not future-performance clustering."},
            "featureVariants": matrix.get("featureVariants", {}), "warnings": warnings}, allowed


@router.get("/sports/nfl/laboratory")
def read_laboratory(user: dict[str, Any] = Depends(require_user)):
    _permission(user)
    catalog, _ = laboratory_catalog()
    return catalog


@router.get("/sports/nfl/laboratory/artifacts/{artifact_id}")
def read_artifact(artifact_id: str, user: dict[str, Any] = Depends(require_user)):
    _permission(user)
    _, allowed = laboratory_catalog()
    if artifact_id not in allowed:
        raise HTTPException(status_code=404, detail="Artifact is not in a completed NFL laboratory publication.")
    path, sha = allowed[artifact_id]
    if path.suffix in {".joblib", ".parquet", ".xlsx", ".csv"}:
        _permission(user, "export")
    try:
        _checked(path, sha)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name, content_disposition_type="inline" if path.suffix in {".png", ".json", ".md"} else "attachment",
                        headers={"X-Artifact-SHA256": sha, "Cache-Control": "private, no-store"})
