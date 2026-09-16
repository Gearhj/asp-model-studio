"""Metadata-first inventory of existing V18 totals evidence; no simulation/outcomes."""
from __future__ import annotations
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_starter_duration_quarantine import LEDGER, final_oot_eligible_key_mask
from server.sports_current_statcast import mlb_v18_daily_slate as daily

OUT = ROOT / "outputs/mlb-v18-totals-distribution-v1/inventory"

def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

def read(path):
    return json.loads(Path(path).read_bytes())

def main():
    begun = datetime.now(timezone.utc).isoformat()
    current_root = ROOT / "outputs/mlb-v18-current-state-pipeline-v1"
    manifest_paths = sorted((current_root / "objects/sha256").glob("*/manifest.json"))
    slates, published = [], {}
    for pointer_path in sorted((current_root / "slates").glob("*/latest.json")):
        pointer = read(pointer_path)
        receipt_path = current_root / pointer["relativePath"] / "slate-result.json"
        receipt = read(receipt_path)
        rows = receipt.get("games", [])
        slates.append({"slateDate": receipt["slateDate"], "locatorAtInventory": reference(pointer_path),
            "receipt": reference(receipt_path), "receiptGeneratedAtUtc": receipt["generatedAt"],
            "publishedDistinctGames": len({r["gameId"] for r in rows if r.get("status") == "PUBLISHED"}),
            "gamesDiscovered": receipt.get("gamesDiscovered"), "handoffForecasts": receipt.get("handoffForecasts"),
            "missingForecastDispositions": [r for r in rows if r.get("status") != "PUBLISHED"]})
        for row in rows:
            if row.get("status") == "PUBLISHED":
                published[row["objectSha256"]] = reference(receipt_path)
    rows = []
    denied = []
    for mp in manifest_paths:
        m = read(mp)
        if not all(final_oot_eligible_key_mask([m["gameId"]])):
            denied.append({"manifest": reference(mp), "reason": "PERMANENT_WHOLE_GAME_QUARANTINE"})
            continue
        # Pregame evidence provides the source key and date before numerical payload access.
        evidence_path = mp.parent / "pregame-evidence.json"
        evidence = read(evidence_path)
        game = evidence["game"]
        if not all(final_oot_eligible_key_mask([game["game_id"], str(game["source_game_id"])])):
            denied.append({"manifest": reference(mp), "reason": "PERMANENT_WHOLE_GAME_QUARANTINE"})
            continue
        if str(game["starts_at"])[:10] <= "2026-08-27":
            denied.append({"manifest": reference(mp), "reason": "SEALED_OOT_OR_PRIOR_SCOPE"})
            continue
        daily._verify_existing_object(current_root, {"relativePath": mp.parent.relative_to(current_root).as_posix(), "objectSha256": m["objectSha256"]})
        fp, ep = mp.parent / "forecast.json", mp.parent / "execution-inputs.json"
        f, e = read(fp), read(ep)
        if f["gameId"] != game["game_id"] or str(f["sourceGameId"]) != str(game["source_game_id"]):
            raise ValueError("V18_FORECAST_EVIDENCE_IDENTITY_MISMATCH")
        p = e.get("population", {})
        r = {"objectSha256": m["objectSha256"], "baselineForecastId": "mlb-v18-daily-" + m["objectSha256"],
            "gameId": f["gameId"], "sourceGameId": str(f["sourceGameId"]), "gameDate": str(f["scheduledStart"])[:10],
            "away": f["teams"]["AWAY"]["abbreviation"], "home": f["teams"]["HOME"]["abbreviation"],
            "forecast": reference(fp), "manifest": reference(mp), "executionInputs": reference(ep),
            "pregameEvidence": reference(evidence_path), "schemaVersion": f["schemaVersion"],
            "sourceCutoff": f.get("sourceCutoff"), "originalCapturedAt": f["capturedAt"],
            "originalForecastCreatedAt": f.get("forecastCreatedAt"), "scheduledStart": f["scheduledStart"],
            "simulationCount": f["simulation"]["count"], "simulationSeed": f["simulation"]["seed"],
            "pairedPopulationAvailable": all(k in p for k in ("homeRuns", "awayRuns")),
            "pairedPopulationFields": {k: "population." + k for k in ("homeRuns", "awayRuns")},
            "pairedPopulationLengths": {k: len(p[k]) if k in p else None for k in ("homeRuns", "awayRuns")},
            "existingCompleteTotalPmfAvailable": bool(f.get("distributions", {}).get("totalRuns")),
            "existingPmfField": "distributions.totalRuns", "probabilityUnits": "FRACTION_0_TO_1",
            "allOriginalDrawsRequired": True, "inningCountersRequired": False,
            "currentPublishedSlateContainsObject": m["objectSha256"] in published,
            "currentPublishedSlateReceipt": published.get(m["objectSha256"]),
            "metadataQuarantineEligible": True, "parentAuthority": f["parentAuthority"]}
        rows.append(r)
    latest_by_game = {}
    for r in sorted(rows, key=lambda r: (r["originalForecastCreatedAt"] or r["originalCapturedAt"], r["objectSha256"])):
        latest_by_game[r["gameId"]] = r["objectSha256"]
    for r in rows:
        r["latestAvailableVersionForGame"] = latest_by_game[r["gameId"]] == r["objectSha256"]
        r["versionCountForGame"] = sum(v["gameId"] == r["gameId"] for v in rows)
    legacy = []
    legacy_root = ROOT / "outputs/mlb-v18-daily-slate"
    for mp in sorted((legacy_root / "objects/sha256").glob("*/manifest.json")):
        m = read(mp)
        if not all(final_oot_eligible_key_mask([m["gameId"]])):
            continue
        evidence = read(mp.parent / "pregame-evidence.json")
        g = evidence["game"]
        if not all(final_oot_eligible_key_mask([str(g["source_game_id"])])) or str(g["starts_at"])[:10] <= "2026-08-27":
            continue
        f, e = read(mp.parent / "forecast.json"), read(mp.parent / "execution-inputs.json")
        legacy.append({"manifest": reference(mp), "forecast": reference(mp.parent / "forecast.json"),
            "gameId": f["gameId"], "sourceGameId": str(f["sourceGameId"]), "originalCapturedAt": f["capturedAt"],
            "scheduledStart": f["scheduledStart"], "simulationCount": f["simulation"]["count"],
            "completeTotalPmfRetained": bool(f.get("distributions", {}).get("totalRuns")),
            "pairedPopulationRetained": all(k in e.get("population", {}) for k in ("homeRuns", "awayRuns")),
            "forecastCreatedAtRetained": bool(f.get("forecastCreatedAt")),
            "status": "LEGACY_PRIOR_ENGINE_PAYLOAD_NOT_CURRENT_SOURCE_PIPELINE",
            "limitation": "Published complete total PMF exists; original paired population and separate forecast-created clock not retained in this object. Preserve historical lineage."})
    result = {"schemaVersion": "MLB_V18_TOTALS_EXISTING_SUPPORT_INVENTORY_V1", "begunAtUtc": begun,
        "completedAtUtc": datetime.now(timezone.utc).isoformat(), "quarantine": reference(LEDGER),
        "outcomesRead": False, "simulationsRun": 0, "providerRequests": 0,
        "scope": "Snapshot of every immutable ordinary current-source V18 object; all versions listed, latest version marked. Legacy pre-current-source daily objects listed separately.",
        "summary": {"ordinaryObjectCount": len(rows), "ordinaryDistinctGames": len(latest_by_game),
            "dateObjectCounts": dict(sorted(Counter(r["gameDate"] for r in rows).items())),
            "dateDistinctGameCounts": {d: len({r["gameId"] for r in rows if r["gameDate"] == d}) for d in sorted({r["gameDate"] for r in rows})},
            "completePmfObjects": sum(r["existingCompleteTotalPmfAvailable"] for r in rows),
            "pairedPopulationObjects": sum(r["pairedPopulationAvailable"] for r in rows),
            "deniedObjects": len(denied), "legacyDailyObjects": len(legacy)},
        "ordinaryForecasts": sorted(rows, key=lambda r: (r["gameDate"], r["sourceGameId"], r["originalForecastCreatedAt"])),
        "latestSlates": slates, "excludedBeforeNumericalAccess": denied, "legacyDailyForecasts": legacy}
    raw = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = OUT / "objects/sha256" / digest / "coverage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("IMMUTABLE_INVENTORY_CONFLICT")
    if not path.exists():
        path.write_bytes(raw)
    (OUT / "current.json").write_bytes((json.dumps(reference(path), sort_keys=True) + "\n").encode())
    print(json.dumps({"inventory": reference(path), "summary": result["summary"]}, indent=2))

if __name__ == "__main__":
    main()
