"""Publish a no-fit interpretability supplement for the completed NFL lab."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.audit_assurance.canonical import canonical_json_bytes
from server.persistence.db import Database, now_iso
from server.persistence.service import PersistenceService
from server.sports_nfl_m1.lab_registration import DEFAULT_DATABASE_PATH, PROJECT_ID
from server.sports_nfl_m1.overnight_lab import (
    DEFAULT_OUTPUT_ROOT,
    LabConfig,
    _atomic_json,
    _interpretability_artifact,
    _load_development,
    _plain_json,
)


def main() -> int:
    current = json.loads((DEFAULT_OUTPUT_ROOT / "current.json").read_text(encoding="utf-8"))
    handoff = json.loads(Path(current["handoffPath"]).read_text(encoding="utf-8"))
    external_manifest = json.loads(Path(handoff["externalManifestPath"]).read_text(encoding="utf-8"))
    analysis = json.loads(Path(external_manifest["analysisPath"]).read_text(encoding="utf-8"))
    _, development, _ = _load_development(LabConfig())
    run_root = Path(external_manifest["analysisPath"]).parent.parent
    importance = _interpretability_artifact(
        analysis["fittedDevelopmentArtifact"], development, run_root, seed=1_651_001
    )
    supplement = {
        "contract": "ASP_NFL_OVERNIGHT_INTERPRETABILITY_SUPPLEMENT_V1",
        "parentManifestSha256": current["manifestSha256"],
        "parentHandoffSha256": current["handoffSha256"],
        "pipelineId": analysis["developmentSelectedPipeline"],
        "interpretability": importance,
        "finalOotAccessed": False,
        "modelFitOccurred": False,
        "modelArtifactChanged": False,
        "status": "RESEARCH_SHADOW",
        "promotionStatus": "NOT_PROMOTED",
        "wageringAuthority": False,
        "createdAt": now_iso(),
    }
    payload = canonical_json_bytes(_plain_json(supplement))
    digest = hashlib.sha256(payload).hexdigest()
    destination = DEFAULT_OUTPUT_ROOT / "interpretability" / "sha256" / digest / "supplement.json"
    written = _atomic_json(destination, supplement)
    if written != digest:
        raise RuntimeError("interpretability supplement identity mismatch")
    _atomic_json(DEFAULT_OUTPUT_ROOT / "interpretability" / "current.json", {
        "contract": "ASP_NFL_OVERNIGHT_INTERPRETABILITY_CURRENT_V1",
        "supplementPath": str(destination.resolve()), "supplementSha256": digest,
        "parentManifestSha256": current["manifestSha256"],
    })
    service = PersistenceService(Database(DEFAULT_DATABASE_PATH.resolve()))
    evidence_id = f"nfl-lab-interpretability-{digest[:20]}"
    service.evidence.upsert({
        "evidence_id": evidence_id, "project_id": PROJECT_ID,
        "workflow_type": "nfl-forecasting", "step_id": "nfl-10",
        "artifact_type": "research_interpretability", "status": "complete_descriptive_only",
        "title": "Finalist descriptive permutation importance",
        "summary": "2024 refit-training-sample interpretation; not validation evidence and no model fit occurred.",
        "source_ref": str(destination.resolve()), "artifact_hash": digest,
        "created_by": "user_20e0f4e20ec9434c",
        "payload_json": {"parentManifestSha256": current["manifestSha256"],
                         "finalOotAccessed": False, "modelFitOccurred": False},
    })
    print(json.dumps({
        "supplementPath": str(destination.resolve()), "supplementSha256": digest,
        "parentManifestSha256": current["manifestSha256"], "modelFitOccurred": False,
        "finalOotAccessed": False, "evidenceId": evidence_id,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
