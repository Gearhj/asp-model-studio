from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

from ..evidence.evidence_store import upsert_evidence
from ..evidence.financial_services_taxonomy import CREDIT_RISK_DOCUMENTATION_MAPPING


CREDIT_RISK_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "credit_risk"
PROFILES_ROOT = CREDIT_RISK_ROOT / "profiles"
REGISTRY_PATH = CREDIT_RISK_ROOT / "credit_risk_profiles.json"

READINESS_SECTIONS = [
    "Target Definition",
    "Population Definition",
    "Variable Mapping",
    "WOE / IV",
    "Manual Binning",
    "Reject Inference",
    "PDO Scaling",
    "Adverse Action",
    "Fair Lending",
    "Cutoff Strategy",
    "Risk-Based Pricing",
    "PSI",
    "Champion / Challenger",
    "Monitoring",
    "Documentation",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_store() -> None:
    PROFILES_ROOT.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_PATH.exists():
        write_json(REGISTRY_PATH, {"profiles": []})


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def profile_id_for(profile: Dict[str, Any]) -> str:
    basis = f"{profile.get('projectId','')}|{profile.get('datasetId','')}|{profile.get('productType','')}|{profile.get('modelPurpose','')}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", str(profile.get("projectName") or profile.get("projectId") or "credit-risk").lower()).strip("-")[:40]
    return f"cr-{slug or 'profile'}-{digest}"


def profile_path(profile_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", profile_id)
    return PROFILES_ROOT / f"{safe}.json"


def compact_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "profileId": profile.get("profileId"),
        "projectId": profile.get("projectId"),
        "projectName": profile.get("projectName"),
        "datasetId": profile.get("datasetId"),
        "datasetVersionId": profile.get("datasetVersionId"),
        "productType": profile.get("productType"),
        "modelPurpose": profile.get("modelPurpose"),
        "targetEvent": profile.get("targetEvent"),
        "targetWindow": profile.get("targetWindow"),
        "ttcPitAssumption": profile.get("ttcPitAssumption"),
        "readinessScore": profile.get("readinessScore"),
        "updatedAt": profile.get("updatedAt"),
        "createdAt": profile.get("createdAt"),
    }


def load_registry() -> List[Dict[str, Any]]:
    ensure_store()
    payload = read_json(REGISTRY_PATH, {"profiles": []})
    return payload.get("profiles", []) if isinstance(payload, dict) else []


def save_registry(rows: List[Dict[str, Any]]) -> None:
    write_json(REGISTRY_PATH, {"profiles": sorted(rows, key=lambda row: str(row.get("updatedAt") or ""), reverse=True)})


def list_profiles() -> List[Dict[str, Any]]:
    return load_registry()


def get_profile(profile_id: str) -> Dict[str, Any] | None:
    item = read_json(profile_path(profile_id), None)
    return item if isinstance(item, dict) else None


def get_project_profile(project_id: str) -> Dict[str, Any] | None:
    match = next((row for row in load_registry() if row.get("projectId") == project_id), None)
    return get_profile(str(match.get("profileId"))) if match else None


def save_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_store()
    timestamp = now_iso()
    existing = get_profile(str(payload.get("profileId") or "")) if payload.get("profileId") else None
    profile = {**(existing or {}), **payload}
    profile["profileId"] = profile.get("profileId") or profile_id_for(profile)
    profile["createdAt"] = profile.get("createdAt") or timestamp
    profile["updatedAt"] = timestamp
    preview = scorecard_preview(profile.get("scorecardScaling") or {})
    profile.setdefault("scorecardScaling", {})
    profile["scorecardScaling"].update({k: v for k, v in preview.items() if v is not None})
    readiness = compute_readiness(profile)
    profile["readiness"] = {item["section"]: item["status"] for item in readiness["items"]}
    profile["readinessScore"] = readiness["score"]
    write_json(profile_path(profile["profileId"]), profile)
    registry = [row for row in load_registry() if row.get("profileId") != profile["profileId"]]
    registry.append(compact_profile(profile))
    save_registry(registry)
    return profile


def compute_readiness(profile: Dict[str, Any]) -> Dict[str, Any]:
    feature_review = profile.get("featureReview") if isinstance(profile.get("featureReview"), dict) else {}
    explainability = profile.get("explainability") if isinstance(profile.get("explainability"), dict) else {}
    strategy = profile.get("decisionStrategy") if isinstance(profile.get("decisionStrategy"), dict) else {}
    monitoring = profile.get("monitoring") if isinstance(profile.get("monitoring"), dict) else {}
    scaling = profile.get("scorecardScaling") if isinstance(profile.get("scorecardScaling"), dict) else {}
    checks = {
        "Target Definition": bool(profile.get("targetEvent") and profile.get("targetWindow")),
        "Population Definition": bool(profile.get("observationWindow") or profile.get("exclusionRules")),
        "Variable Mapping": bool(profile.get("variableMappings")),
        "WOE / IV": bool(feature_review.get("woeIv")),
        "Manual Binning": bool(feature_review.get("manualBinning")),
        "Reject Inference": bool(feature_review.get("rejectInference")),
        "PDO Scaling": bool(scaling.get("pdo") and scaling.get("baseScore") and scaling.get("baseOdds")),
        "Adverse Action": bool(explainability.get("adverseActionStatus") or explainability.get("reasonCodeLogic")),
        "Fair Lending": bool(explainability.get("fairLendingStatus")),
        "Cutoff Strategy": bool(strategy.get("cutoffs")),
        "Risk-Based Pricing": bool(strategy.get("riskBasedPricing")),
        "PSI": bool(monitoring.get("psiThresholds")),
        "Champion / Challenger": bool(monitoring.get("challengerChampion")),
        "Monitoring": bool(monitoring.get("monitoringCadence") or monitoring.get("redevelopmentTrigger")),
        "Documentation": bool(profile.get("readiness", {}).get("Documentation") == "Ready"),
    }
    items = [{"section": section, "status": "Ready" if checks.get(section) else "Missing"} for section in READINESS_SECTIONS]
    score = round(sum(1 for item in items if item["status"] == "Ready") / len(items) * 100)
    return {"score": score, "items": items}


def scorecard_preview(scaling: Dict[str, Any]) -> Dict[str, float | None]:
    try:
        pdo = float(scaling.get("pdo"))
        base_score = float(scaling.get("baseScore"))
        odds = parse_base_odds(str(scaling.get("baseOdds") or ""))
        if pdo <= 0 or odds <= 0:
            return {"factor": None, "offset": None}
        factor = pdo / math.log(2)
        offset = base_score - factor * math.log(odds)
        return {"factor": round(factor, 4), "offset": round(offset, 4)}
    except Exception:
        return {"factor": None, "offset": None}


def parse_base_odds(value: str) -> float:
    match = re.search(r"([0-9.]+)\s*:?\s*1?", value)
    return float(match.group(1)) if match else float(value)


def create_credit_risk_evidence(profile: Dict[str, Any], technique: str, label: str, supports_sections: List[str] | None = None) -> Dict[str, Any]:
    sections = supports_sections or CREDIT_RISK_DOCUMENTATION_MAPPING.get(technique, [])
    evidence_type = "vif" if technique in {"iv"} else "model_diagnostics" if technique in {"psi", "cutoff_optimization"} else "governance"
    item = {
        "projectId": profile.get("projectId", ""),
        "projectName": profile.get("projectName", ""),
        "evidenceType": evidence_type,
        "title": label,
        "summary": f"{label} captured from Credit Risk Studio for {profile.get('productType') or 'credit risk'} {profile.get('modelPurpose') or 'model'} governance.",
        "sourcePage": "Credit Risk Studio",
        "sourceRoute": "/credit-risk-studio",
        "artifactType": "credit_risk_profile",
        "artifactId": profile.get("profileId") or "",
        "datasetIds": [profile.get("datasetId")] if profile.get("datasetId") else [],
        "supportsSections": sections,
        "tags": ["credit_risk", technique, "underwriting", "governance"],
        "financialDomain": "credit_risk",
        "financialTechnique": technique,
        "creditRiskContext": {
            "productType": profile.get("productType"),
            "modelPurpose": profile.get("modelPurpose"),
            "targetEvent": profile.get("targetEvent"),
            "targetWindow": profile.get("targetWindow"),
            "ttcPitAssumption": profile.get("ttcPitAssumption"),
        },
        "regulatoryRelevance": {
            "fair_lending": technique in {"fair_lending", "adverse_action", "manual_binning", "monotonic_constraints"},
            "model_risk": True,
            "adverse_action": technique == "adverse_action",
        },
        "lineage": {"profileId": profile.get("profileId"), "source": "Credit Risk Studio"},
        "payload": {"technique": technique, "profileSummary": compact_profile(profile)},
        "governance": {"note": "Credit Risk Studio stores compact evidence metadata and profile references only."},
        "status": "ready",
        "importance": "high",
    }
    return upsert_evidence(item)


def export_profile_excel(profile: Dict[str, Any]) -> bytes:
    try:
        from openpyxl import Workbook
    except Exception:
        return json.dumps(profile, indent=2, default=str).encode("utf-8")
    wb = Workbook()
    ws = wb.active
    ws.title = "Credit Risk Profile"
    rows = [
        ("Project", profile.get("projectName")),
        ("Product Type", profile.get("productType")),
        ("Model Purpose", profile.get("modelPurpose")),
        ("Target Event", profile.get("targetEvent")),
        ("Target Window", profile.get("targetWindow")),
        ("Readiness Score", profile.get("readinessScore")),
    ]
    for row in rows:
        ws.append(row)
    ws2 = wb.create_sheet("Readiness")
    ws2.append(["Section", "Status"])
    readiness = compute_readiness(profile)
    for item in readiness["items"]:
        ws2.append([item["section"], item["status"]])
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()
