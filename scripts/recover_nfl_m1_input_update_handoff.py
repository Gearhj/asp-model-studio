"""Complete the failed handoff step using published NFL forecasts, without republishing."""
from __future__ import annotations
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nfl_m1.current_shadow import publish_current_slate_handoff
from server.sports_nfl_m1.rolling_publication import publish_rolling_handoff
from server.sports_nfl_m1.prospective_shadow import (
    _load_targets, _select_slate_targets, _started_events_in_current_rolling_week,
    load_foundation_runtime,
)
from server.sports_gold.nfl_shadow_exchange import verify_sports_forecast_bundle

OUT = ROOT / "outputs/nfl-m1-current-season-update-v1"
STAGING = Path("C:/Users/james/asp-data-staging/nfl")
EXCHANGE = Path("C:/Users/james/asp-model-exchange")
REVISION = "08c1582c8b371ae9ae55e6c369b53975039e8487"
CUTOFF = "2026-09-13T19:15:52.815675Z"


def read(path):
    return json.loads(Path(path).read_bytes())


def ref(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}


def main():
    destination = OUT / "publication-recovery-execution.json"
    if destination.exists():
        print(json.dumps({"status": "ALREADY_RETAINED", "receipt": ref(destination)}))
        return
    before, after = read(OUT / "inputs-before.json"), read(OUT / "inputs-after.json")
    prior = before["pointers"]["prospective"]["value"]
    index_path = STAGING / "m1-prospective-shadow-v1/prospective-index.json"
    raw_index = index_path.read_bytes(); index = json.loads(raw_index)
    locator_path = EXCHANGE / "aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json"
    raw_locator = locator_path.read_bytes()
    recovered_at = datetime.now(timezone.utc).isoformat()
    source = load_foundation_runtime()
    assert source.paths.foundation_manifest_sha256 == after["pointers"]["foundation"]["value"]["currentManifestSha256"]
    cutoff = datetime.fromisoformat(CUTOFF.replace("Z", "+00:00"))
    targets, _, _ = _load_targets(source, as_of=cutoff)
    targets = _select_slate_targets(targets, slate_date=None, next_slate_only=False, rolling_window_days=7, as_of=cutoff)
    assert {t["canonical_game_id"] for t in targets} == {r["canonicalGameId"] for r in before["targets"]}
    new_entries = [(game, entry) for game, snapshots in index["events"].items() for entry in snapshots["CURRENT"]
                   if entry.get("producerRevision") == REVISION and entry["forecastCutoffUtc"] == CUTOFF]
    assert len(new_entries) == 1 and new_entries[0][0] == "2026_02_PIT_NE"
    new_ids = {entry["forecastId"] for _, entry in new_entries}
    before_vectors = {t["canonicalGameId"]: t["features"] for t in before["targets"]}
    after_vectors = {t["canonicalGameId"]: t["features"] for t in after["targets"]}
    reused = []
    for target in targets:
        game = str(target["canonical_game_id"])
        if game == new_entries[0][0]:
            assert before_vectors[game] != after_vectors[game]
            continue
        assert index["events"][game]["CURRENT"] == prior["events"][game]["CURRENT"]
        assert before_vectors[game] == after_vectors[game]
        reused.append(game)
    bundles = [b for b in index["bundles"] if set(b["forecastIds"]) == new_ids]
    assert len(bundles) == 1
    for bundle in bundles:
        verify_sports_forecast_bundle(EXCHANGE, bundle["bundleSha256"])
    for game, snapshots in prior["events"].items():
        for snapshot, entries in snapshots.items():
            assert index["events"][game][snapshot][:len(entries)] == entries
    old_sources = sorted({str(e["sourceFoundationManifestSha256"]) for target in targets
                         for e in prior["events"][target["canonical_game_id"]]["CURRENT"] if e.get("sourceFoundationManifestSha256")})
    fixture_path = STAGING / "m1-prospective-shadow-v1/activation-fixtures/sha256" / index["reloadFixtureSha256"] / "fixture.json"
    activation = {
        "status": "ACTIVE", "selectionMode": "ROLLING_WINDOW", "rollingWindowDays": 7,
        "selectedSlateDates": sorted({str(t["game_date"]) for t in targets}), "games": len(targets),
        "forecastsCreated": 1, "unchangedEvidenceForecastsReused": len(reused),
        "forecastInferenceRows": 1, "bundles": bundles, "bundleCount": len(bundles),
        "forecastCutoffUtc": CUTOFF, "completedAtUtc": index["updatedAtUtc"],
        "sourceEvidenceAsOfUtc": source.schedule_as_of_utc,
        "sourceFoundationManifestSha256": source.paths.foundation_manifest_sha256,
        "sourceFoundationChangedSincePreviousSnapshot": True,
        "priorSourceFoundationManifestSha256s": old_sources,
        "modelManifestSha256": index["modelManifestSha256"], "modelBinarySha256": index["modelBinarySha256"],
        "featureContractSha256": index["featureContractSha256"], "producerRevision": REVISION,
        "residualAuthoritySha256": "34b95d42f55d5be424752b73b4450d8b8d17a9a3e434659ac0b0cc9a185984be",
        "modelsFit": 0, "modelsPromoted": 0,
        "completed2026GameIdsEligibleByFoundationCutoff": sorted({r["canonical_game_id"] for r in after["completed2026TeamFacts"]}),
        "eventPlan": [{"eventId": str(t["canonical_game_id"]), "scheduledStartUtc": t["scheduled_start_utc"].isoformat().replace("+00:00", "Z"),
                       "action": "PUBLISH_CHANGED_ELIGIBLE_INPUTS" if t["canonical_game_id"] == new_entries[0][0] else "REUSE_UNCHANGED_FORECAST"} for t in targets],
        "alreadyStartedEvents": _started_events_in_current_rolling_week(source, targets, as_of=cutoff),
        "exchangeLocatorPath": str(locator_path), "reloadFixtureSha256": index["reloadFixtureSha256"],
        "reloadFixtureReproduced": True,
        "historicalParity": {"originalReturnPayloadRetained": False, "requiredPublisherGatePassedBeforeIndexCommit": True,
                             "basis": "PINNED_PRODUCER_CONTROL_FLOW_AND_COMPLETED_INDEX_WRITE"},
        "recovery": {
            "contract": "NFL_M1_PUBLISHED_RUN_RECEIPT_RECOVERY_V1", "recoveredAtUtc": recovered_at,
            "method": "IMMUTABLE_NEW_BUNDLE_AND_VECTOR_PLUS_PRESERVED_INDEX_ENTRIES_AND_PINNED_PRODUCER_CONTROL_FLOW",
            "originalApiReturnRetained": False, "forecastReruns": 0,
            "originalWrapperFailure": "Forecast publication completed; current-slate handoff incorrectly included already-started games from full retained slate",
            "originalStdout": ref(OUT / "rolling-publication-execution.json"),
            "indexAtRecovery": ref(index_path), "indexPhysicalLastWriteUtc": datetime.fromtimestamp(index_path.stat().st_mtime, timezone.utc).isoformat(),
            "clockQualification": "Index updatedAtUtc is the original numerical publication run clock, preceding current-authority locator composition; physical index write and recovery clocks are separate",
            "reloadFixture": ref(fixture_path),
        },
    }
    # A new handoff is a newly checked derivative; original forecast clocks stay
    # in the immutable children, while freshness here uses this real check time.
    refresh = {**activation, "completedAtUtc": recovered_at}
    handoffs = [publish_current_slate_handoff(date.fromisoformat(s), output_root=OUT / "publication/slates",
                refresh_evidence=refresh) for s in activation["selectedSlateDates"]]
    handoff = publish_rolling_handoff(refresh, handoffs, output_root=OUT / "publication")
    assert handoff["eventCount"] == handoff["forecastCount"] == len(targets)
    assert index_path.read_bytes() == raw_index and locator_path.read_bytes() == raw_locator
    result = {"activation": activation, "handoff": handoff,
              "handoffRecovery": {"completedAtUtc": datetime.now(timezone.utc).isoformat(),
                                  "forecastsRegenerated": 0, "forecastIndexAndExchangeLocatorUnchanged": True}}
    destination.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE", "receipt": ref(destination), "handoffPath": handoff["handoffPath"],
                      "handoffSha256": handoff["handoffSha256"], "forecastCount": handoff["forecastCount"]}))


if __name__ == "__main__":
    main()
