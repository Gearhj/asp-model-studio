"""Verify Claude's existing exchange objects without rebuilding its exporter."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_v18_exchange import _child, _read
from server.sports_current_statcast.mlb_v18_current_publication import reference
from server.sports_datasets.consumer import canonical_json_bytes

EXCHANGE = Path(r"C:\Users\james\asp-model-exchange\mlb-v18-simulator-evidence-v1")
OUT = ROOT / "outputs/mlb-v18-transition-shrinkage-v1"
REPORTED = "6d7b90edc538a6240d5a24a8b2d40edf8d5874d5a65b2c6fc027343bae3ddb43"


def verified_ref(root: Path, item: dict) -> dict:
    path = _child(root, item["relativePath"])
    actual = reference(path)
    if any(actual[key] != item[key] for key in ("sha256", "bytes")):
        raise ValueError("AISP_EVIDENCE_OBJECT_CHECKSUM_MISMATCH")
    return actual


def consume() -> dict:
    pointer_ref = reference(EXCHANGE / "current.json")
    pointer = _read(pointer_ref)
    handoff_ref = verified_ref(EXCHANGE, pointer["handoff"])
    handoff = _read(handoff_ref)
    old_path = _child(EXCHANGE, f"objects/sha256/{REPORTED}/simulator-evidence-handoff.json")
    old_ref = reference(old_path)
    if old_ref["sha256"] != REPORTED:
        raise ValueError("REPORTED_HANDOFF_CHECKSUM_MISMATCH")
    old = _read(old_ref)
    files = {}
    for name, item in pointer["files"].items():
        ref = verified_ref(EXCHANGE, item)
        if any(ref[k] != handoff["files"][name][k] for k in ("sha256", "bytes")):
            raise ValueError("AISP_POINTER_HANDOFF_OBJECT_MISMATCH")
        files[name] = ref
    previous_files = {}
    for name, item in old["files"].items():
        previous_files[name] = verified_ref(EXCHANGE, {
            **item, "relativePath": f"objects/sha256/{item['sha256']}/{name}"})
    protected = handoff["protectedPopulations"]
    if set(protected["quarantinedGamePks"]) != {"823343", "824235", "822693"}:
        raise ValueError("AISP_EVIDENCE_QUARANTINE_DIFFERS")
    if protected["sealedFinalOutOfTimeWindow"] != ["2026-08-14", "2026-08-27"]:
        raise ValueError("AISP_EVIDENCE_SEALED_WINDOW_DIFFERS")
    if handoff["scopes"]["developmentHistory"]["use"] != "LABEL_ONLY_AUTHORIZED_HISTORICAL_EVALUATION":
        raise ValueError("AISP_APPEARANCE_AUTHORITY_DIFFERS")
    # Hashing opaque JSONL bytes above verifies transport; appearance outcomes
    # are not decoded or admitted as pregame covariates by this consumer.
    receipt = {
        "schemaVersion": "MLB_V18_SIMULATOR_EVIDENCE_CONSUMPTION_V1",
        "verifiedAtUtc": datetime.now(timezone.utc).isoformat(),
        "pointer": pointer_ref, "reportedHandoff": old_ref, "currentHandoff": handoff_ref,
        "reportedAsOfUtc": old["asOfUtc"], "currentAsOfUtc": handoff["asOfUtc"],
        "resolution": "CURRENT_IS_NEWER_VERIFIED_SUCCESSOR" if old_ref != handoff_ref else "REPORTED_IS_CURRENT",
        "files": files, "reportedFiles": previous_files,
        "appearanceLabels": handoff["scopes"]["developmentHistory"],
        "appearanceOutcomesDecoded": 0, "appearancePregameFeatureUse": "NONE",
        "inputCutoffRule": "Each covariate must be available by the frozen forecast source cutoff; a later decision deadline is insufficient.",
        "omissions": handoff["omissions"]["consequences"],
        "protectedPopulations": protected,
        "producerExporterRebuilt": False, "providerCalls": 0,
        "researchShadowOnly": True, "candidateAuthority": False,
    }
    raw = canonical_json_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    path = OUT / f"evidence-consumption/sha256/{digest}/receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    result = reference(path)
    (OUT / "evidence-consumption-current.json").write_bytes(canonical_json_bytes(result))
    return result


if __name__ == "__main__":
    print(json.dumps(consume(), indent=2))
