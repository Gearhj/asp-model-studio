"""Phase 7D.4 (B9 / Gate 9) — backend↔frontend response-contract test.

Proves: (1) each of the four scientific cockpit reads declares its strict versioned V2 Pydantic response model
on the route; (2) the SHARED representative JSON fixture (also compiled against the TypeScript types in
src/sports/cockpit/__contract__/cockpitV2Contract.ts) validates against every DTO and its key set is EXACTLY the
DTO field set; (3) a renamed / missing / misnested / unexpected critical field fails construction; and (4)
cockpitSteps2.tsx no longer reads any legacy field path. 2025 never appears in any contract shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.sports_cockpit import router as R
from server.sports_cockpit.cockpit_dtos import (
    ActiveCandidateResponseV2, FeatureFamilyComparisonResponseV2, ModelCalibrationResponseV2,
    ModelEvaluationResponseV2, ModelRegistryEvidenceResponseV2,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((REPO / "src/sports/cockpit/__contract__/cockpit_v2_contract.json").read_text(encoding="utf-8"))

_SHAPES = {
    "activeCandidate": ActiveCandidateResponseV2,
    "evaluation": ModelEvaluationResponseV2,
    "calibration": ModelCalibrationResponseV2,
    "registryEvidence": ModelRegistryEvidenceResponseV2,
    "comparison": FeatureFamilyComparisonResponseV2,
}


# --------------------------------------------------------------- (1) routes declare the strict V2 response models
def _route(path: str):
    for r in R.router.routes:
        if getattr(r, "path", None) == path:
            return r
    raise AssertionError(f"route not found: {path}")


@pytest.mark.parametrize("path,model", [
    ("/cockpit/gen3/active-candidate/{project_id}", ActiveCandidateResponseV2),
    ("/cockpit/gen3/evaluation/{project_id}", ModelEvaluationResponseV2),
    ("/cockpit/gen3/calibration/{project_id}", ModelCalibrationResponseV2),
    ("/cockpit/gen3/registry-evidence/{project_id}", ModelRegistryEvidenceResponseV2),
    ("/cockpit/gen3/feature-family-ablation", FeatureFamilyComparisonResponseV2),
])
def test_route_declares_strict_v2_response_model(path, model):
    assert _route(path).response_model is model


# --------------------------------------------------------------- (2) fixture validates + key set == DTO field set
@pytest.mark.parametrize("key,model", list(_SHAPES.items()))
def test_shared_fixture_validates_and_key_set_matches(key, model):
    payload = FIXTURE[key]
    model.model_validate(payload)                     # representative payload validates
    assert set(payload) == set(model.model_fields)    # exactly the DTO field set (no missing / extra)
    # No 2025 SEASON/metric/score value anywhere; the only permitted 2025 mention is the honest human-readable
    # seal label (e.g. "2025 sealed — never scored"), which carries no 2025 data.
    scrubbed = {k: v for k, v in payload.items() if k != "validationLabel"}
    assert "2025" not in json.dumps(scrubbed)


# --------------------------------------------------------------- (3) drift fails closed
def test_missing_critical_field_fails():
    bad = {k: v for k, v in FIXTURE["evaluation"].items() if k != "runReceiptSha256"}
    with pytest.raises(ValidationError):
        ModelEvaluationResponseV2.model_validate(bad)


def test_unexpected_field_fails():
    bad = {**FIXTURE["activeCandidate"], "surprise": True}
    with pytest.raises(ValidationError):
        ActiveCandidateResponseV2.model_validate(bad)


def test_renamed_field_fails():
    bad = {k: v for k, v in FIXTURE["registryEvidence"].items() if k != "bundleManifestSha256"}
    bad["bundleSha"] = FIXTURE["registryEvidence"]["bundleManifestSha256"]   # renamed critical field
    with pytest.raises(ValidationError):
        ModelRegistryEvidenceResponseV2.model_validate(bad)


def test_misnested_field_fails():
    ev = dict(FIXTURE["evaluation"])
    ev.pop("metrics")
    ev["logLoss"] = 1.48        # misnested: aggregate metric hoisted to the top level
    with pytest.raises(ValidationError):
        ModelEvaluationResponseV2.model_validate(ev)


def test_prohibited_extra_in_nested_metrics_fails():
    ev = json.loads(json.dumps(FIXTURE["evaluation"]))
    ev["metrics"]["balancedAccuracy"] = 0.5   # not a governed aggregate metric -> nested extra rejected
    with pytest.raises(ValidationError):
        ModelEvaluationResponseV2.model_validate(ev)


# --------------------------------------------------------------- (4) frontend reads no legacy field paths
def test_cockpit_steps2_uses_no_legacy_field_paths():
    src = (REPO / "src/sports/cockpit/cockpitSteps2.tsx").read_text(encoding="utf-8")
    forbidden = [
        ".evidenceBundleSha256",       # V1 field name (now bundleManifestSha256)
        ".resultFingerprint",          # never present in the V2 responses
        ".diagnosticsSha256",          # not in the evaluation V2 shape
        "cand.run?",                   # active-candidate nested run.* (now flat)
        "d.diagnostics.classOrder",    # classOrder now lives on d.confusion
        "m.classwiseBrier",            # per-class block is now d.perClass.classwiseBrier
        "m.perClass[",                 # per-class block is now d.perClass.perClass
        "m.balancedAccuracy",          # not in the governed aggregate metrics
    ]
    hits = [tok for tok in forbidden if tok in src]
    assert hits == [], f"cockpitSteps2.tsx still reads legacy field path(s): {hits}"
