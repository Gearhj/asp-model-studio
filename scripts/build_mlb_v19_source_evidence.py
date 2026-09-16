"""Reuse seven already captured safe days; no provider/model/AISP calls."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_v19_source_evidence import (
    VERSION, descriptor, load_daily_capture, store_supplement, supplement, utc, verified_bytes,
)

SOURCES = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/sources/objects/sha256"
DEST = ROOT / "outputs/mlb-v19-current-state-specialists-v1/source-evidence"
AUDIT = ROOT / "outputs/mlb-v18-unattended-v1/evidence/sha256/2bcf37de2fd76316ec850ebec2f06c7383fcd7c5afa275071ea21f8aafc95e29/sept10-operational-evidence.json"


def build():
    started = datetime.now(timezone.utc).isoformat()
    audit_ref = descriptor(AUDIT)
    if audit_ref["sha256"] != AUDIT.parent.name:
        raise ValueError("Original operational audit identity changed")
    audit = json.loads(verified_bytes(audit_ref, AUDIT.parents[2]))
    venue_path = ROOT / "server/sports_current_statcast/mlb_context_authorities_v1.json"
    venue_ref = descriptor(venue_path)
    venues = json.loads(verified_bytes(venue_ref, venue_path.parent))["venues"]
    games = []
    for original in audit["publishedGames"]:
        snapshot_ref = original["actualExecutionFeatureSnapshot"]
        snapshot = json.loads(verified_bytes(snapshot_ref, ROOT / "outputs/mlb-v18-current-state-pipeline-v1"))
        games.append({**original, "targetGameDate": "2026-09-10", "sourceVenueId": snapshot["game"]["source_venue_id"],
            "venueAuthorities": venues, "scheduleVenueAuthority": venue_ref})
    cutoff = min(utc(game["evidenceCutoff"]) for game in games)
    requested = [(date(2026, 9, 10) - timedelta(days=i)).isoformat() for i in range(1, 8)]
    pairs = {}
    # Metadata inspection does not open any raw historical or evaluation file.
    for path in sorted(SOURCES.glob("*.receipt.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("day") not in requested or record.get("family") not in {"STATCAST", "SCHEDULE"}:
            continue
        if max(utc(record[key]) for key in ("observedAt", "availableAsOf", "ingestedAt")) > cutoff:
            continue
        ref = descriptor(path)
        if ref["sha256"] != path.name.split(".")[0]:
            raise ValueError("Capture receipt is not content addressed")
        record["_receipt"] = ref
        key = (record["day"], record["family"])
        if key not in pairs or utc(record["availableAsOf"]) > utc(pairs[key]["availableAsOf"]):
            pairs[key] = record
    missing = [day for day in requested if any((day, family) not in pairs for family in ("SCHEDULE", "STATCAST"))]
    captures = [load_daily_capture(pairs[(day, "SCHEDULE")], pairs[(day, "STATCAST")],
        cutoff=cutoff, source_root=SOURCES) for day in sorted(requested) if day not in missing]
    captured_ref = store_supplement({"schemaVersion": VERSION + "_CAPTURES", "captures": captures,
        "missingDates": missing, "providerCalls": 0, "sealedPayloadReads": 0}, DEST, name="derived-captures.json")
    artifacts = [store_supplement(supplement(game, captures), DEST) for game in games]
    # Reconstruct independently; no numerical tolerances or modification times.
    repeated = [store_supplement(supplement(game, captures), DEST) for game in games]
    if artifacts != repeated:
        raise ValueError("Repeated source derivation did not reproduce exactly")
    source_bytes = sum(ref["bytes"] for capture in captures for ref in capture["rawSources"])
    result = {"schemaVersion": VERSION + "_PACKAGE", "originalOperationalAudit": audit_ref,
        "captureDerivations": captured_ref, "gameSupplements": artifacts,
        "gameCount": len(games), "requestedDays": sorted(requested), "missingDays": missing,
        "completeCapturedDays": sum(capture["complete"] for capture in captures),
        "rawSourceBytesReused": source_bytes, "downloadedBytes": 0, "providerCalls": 0, "costUsd": 0,
        "idempotentExactRerun": True, "sealedPayloadReads": 0,
        "fittedModels": 0, "originalForecastsModified": 0, "historicalDevelopmentTrainingAllowed": False,
        "sourcePurpose": "RESEARCH_FORWARD_ARCHIVE_SCHEMA_WITH_PREGAME_CAPTURED_SEPT10_DEMONSTRATION",
        "derivationCode": [descriptor(Path(__file__)), descriptor(ROOT / "server/sports_current_statcast/mlb_v19_source_evidence.py")]}
    package = store_supplement(result, DEST, name="source-package.json")
    receipt = store_supplement({"schemaVersion": VERSION + "_EXECUTION", "startedAt": started,
        "completedAt": datetime.now(timezone.utc).isoformat(), "package": package,
        "sealedPayloadReads": 0, "providerCalls": 0}, DEST, name="execution-receipt.json")
    return {"package": package, "executionReceipt": receipt, **{key: result[key] for key in
        ("gameCount", "completeCapturedDays", "rawSourceBytesReused", "providerCalls", "costUsd", "idempotentExactRerun")}}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
