"""Advance source-backed V18 current state and publish eligible frozen-model games.

No providers are called here. Supply an immutable acquisition attempt from the
separate bounded/free acquisition command. AISP capture is a read-only transaction.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import traceback
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.inventory_mlb_current_slate import capture_current_slate
from server.sports_current_statcast.mlb_v18_current_slate import load_contract, reference, verify_accepted_reload, write_object
from server.sports_current_statcast.mlb_v18_current_sources import load_current_source_bundle
from server.sports_current_statcast.mlb_v18_current_features import compose_current_game, reconcile_field_contract, feature_family
from server.sports_current_statcast.mlb_v18_current_publication import OUTPUT, CurrentV18Engine, publish_slate, _source_identity
from server.sports_current_statcast.mlb_v18_daily_slate import json_safe, sha_json


def adapt_source_bundle(bundle, snapshot):
    """Join schedule-only identities to safe completed-game observations exactly."""
    game_day = datetime.fromisoformat(str(snapshot["game"]["starts_at"])).date()
    completed = {str(g["canonicalGameId"]): g for g in bundle["games"]}
    projected = bundle["schedule_identity_rows"]
    schedule = []
    for identity in projected:
        actual = completed.get(str(identity["canonicalGameId"]))
        if actual:
            schedule.append({**identity, **actual, "identityOnly": False})
        else:
            schedule.append({**identity, "identityOnly": True})
    authority = dict(bundle.get("schedule_identity_authority") or {})
    authority.update(completeFrom=authority.get("startDate", "2026-08-28"),
        completeThrough=(game_day-timedelta(days=1)).isoformat(),
        allSeasonScheduleComplete=bool(projected) and authority.get("startDate", "9999") <= "2026-03-25"
            and authority.get("throughDate", "") >= game_day.isoformat(),
        seasonStartDate="2026-03-25" if projected and authority.get("startDate") == "2026-03-25" else None)
    roster = {"AWAY": [], "HOME": []}
    sides = {s["team"]["uuid"]: s["side"] for s in snapshot["sides"]}
    for r in snapshot.get("currentRoster", []):
        if r.get("team_id") not in sides:
            continue
        roster[sides[r["team_id"]]].append({**r, "mlbamId": str(r.get("mlbam_id") or ""),
            "canonicalPlayerId": bundle["mlbam_to_canonical"].get(str(r.get("mlbam_id"))),
            "throws": r.get("throws"), "teamId": r["team_id"],
            "rosterStatus": "ACTIVE" if r.get("active_roster") is True and r.get("availability_status") == "ACTIVE" else r.get("availability_status"),
            "role": "PITCHER" if r.get("position") in {"P", "SP", "RP"} else r.get("position"),
            "sourceIdentity": r.get("source"), "sourceMode": r.get("source_mode"),
            "observedAt": r.get("observed_at"), "availableAsOf": r.get("available_as_of"),
            "ingestedAt": r.get("ingested_at"), "effectiveAt": r.get("effective_at"),
            "sha256": r.get("payload_checksum"), "observationId": r.get("observation_id")})
    return {**bundle, "schedule_games": schedule, "schedule_authority": authority, "currentRoster": roster}


def current_participant_ids(collection, resolved_ids):
    """Resolve source identifiers before projecting historical windows, no guesses."""
    identifiers = set()
    for snapshot in collection["snapshots"]:
        for side in snapshot["sides"]:
            identifiers.add(str(side.get("starter", {}).get("mlbamId") or ""))
            identifiers.update(str(row.get("mlbam") or "") for row in side.get("lineup", []))
        # Match the composer's eligible active pitching pool. Inactive roster
        # members and unmapped nonparticipants cannot block a valid current game.
        for row in snapshot.get("currentRoster", []):
            mlbam = str(row.get("mlbam_id", row.get("mlbamId")) or "")
            if (row.get("active_roster") is True and row.get("availability_status") == "ACTIVE"
                    and row.get("position") in {"P", "SP", "RP"} and row.get("throws") in {"L", "R"}
                    and mlbam in resolved_ids):
                identifiers.add(mlbam)
    return sorted(identifiers - {""})


def run(args):
    # Optional event-aware dispatcher restricts expensive composition to due games.
    # Each invocation still captures live evidence after source assembly.
    def capture_live():
        return capture_current_slate(output_root=args.output_root/"inventory",
            slate_date=getattr(args, "slate_date", None), game_ids=getattr(args, "game_ids", None))
    if args.source_attempt is None:
        candidates = list((OUTPUT/"sources/objects/sha256").glob("*.acquisition-attempt.json"))
        if not candidates:
            raise ValueError("No immutable current-source attempt exists; run the bounded source acquisition command first")
        args.source_attempt = max(candidates, key=lambda p: json.loads(p.read_text(encoding="utf-8"))["completedAt"])
    # Safe Development-only reload equality precedes source construction/inference.
    contract = load_contract()
    reload_receipt = verify_accepted_reload(contract)
    reload_ref, _ = write_object(args.output_root, "accepted-reload.json", reload_receipt)
    bundle = load_current_source_bundle(args.source_attempt, as_of_utc=datetime.now(timezone.utc))
    if args.inventory:
        path = args.inventory.resolve()
        capture = reference(path)
        if path.name != "current-slate-input-inventory.json" or capture["sha256"] != path.parent.name:
            raise ValueError("Expected content-addressed captured inventory")
        inventory = json.loads(path.read_text(encoding="utf-8"))
        snapshot_path = path.with_name("current-game-pregame-snapshots.json")
        snapshot_collection = json.loads(snapshot_path.read_text(encoding="utf-8"))
    else:
        inventory, capture = capture_live()
        snapshot_collection = json.loads(Path(capture["snapshotsPath"]).read_text(encoding="utf-8"))
    # Existing safe source history plus the separately authorized NEW operational
    # captures, never an evaluation artifact. Participant filtering is computational
    # projection only; the complete-history/window authority must still be proved.
    from server.sports_current_statcast.mlb_v18_current_sources import extend_history_for_current_players
    base_bundle = bundle
    selected_ids = current_participant_ids(snapshot_collection, base_bundle["mlbam_to_canonical"])
    bundle = extend_history_for_current_players(base_bundle, selected_ids, as_of_utc=datetime.now(timezone.utc))
    if not args.inventory:
        # Source assembly may take time. Freeze a new live pregame cutoff AFTER it,
        # rather than backdating newly assembled evidence to the participant query.
        inventory, capture = capture_live()
        snapshot_collection = json.loads(Path(capture["snapshotsPath"]).read_text(encoding="utf-8"))
        new_ids = set(current_participant_ids(snapshot_collection, base_bundle["mlbam_to_canonical"])) - set(selected_ids)
        if new_ids:
            selected_ids = sorted(set(selected_ids) | new_ids)
            bundle = extend_history_for_current_players(base_bundle, selected_ids, as_of_utc=datetime.now(timezone.utc))
            inventory, capture = capture_live()
            snapshot_collection = json.loads(Path(capture["snapshotsPath"]).read_text(encoding="utf-8"))
            if set(current_participant_ids(snapshot_collection, base_bundle["mlbam_to_canonical"])) - set(selected_ids):
                raise ValueError("CURRENT_PARTICIPANTS_CHANGED_DURING_BOUNDED_SOURCE_ASSEMBLY")
    from server.sports_current_statcast.mlb_v18_current_identity import load_current_identity_evidence
    bundle["currentPlayerIdentityEvidence"] = load_current_identity_evidence(as_of_utc=snapshot_collection["capturedAt"])
    contract["_crosswalk"] = bundle["mlbam_to_canonical"]
    contract["_annualPriors"] = bundle["annual_priors"]
    contract["_annualAuthority"] = bundle["annual_authority"]
    compositions, composition_reuse = [], []
    for snapshot in snapshot_collection["snapshots"]:
        if getattr(args, "require_fresh_participants", False):
            from server.sports_current_statcast.mlb_v18_unattended import participant_readiness
            reasons = participant_readiness(snapshot)
            if reasons:
                compositions.append({"rows": [], "fieldReports": [], "providerInputs": {}, "canSimulate": False,
                    "blockers": [{"reason": reason} for reason in reasons], "coverage": {"rawInputCount": 246},
                    "event": {"canonicalGameId": snapshot["game"]["game_id"]}})
                composition_reuse.append({"gameId": snapshot["game"]["game_id"], "status": "SOURCE_FRESHNESS_HOLD"})
                continue
        mapping = {}
        for item in snapshot.get("teamIdentityCrosswalk", []):
            key, value = str(item["mlbam_id"]), item["abbreviation"]
            if key in mapping and mapping[key] != value:
                raise ValueError("Ambiguous canonical team identity")
            mapping[key] = value
        contract["_teamCrosswalk"] = mapping
        cache_identity = sha_json(_source_identity({"snapshot": snapshot,
            "history": bundle["authority"], "annual": bundle["annual_authority"],
            "schedule": bundle["schedule_identity_authority"],
            "identityAuthority": bundle["player_identity_authority"],
            "currentPlayerIdentityEvidence": [r for r in bundle["currentPlayerIdentityEvidence"]
                if str(r["mlbamId"]) in current_participant_ids({"snapshots": [snapshot]}, bundle["mlbam_to_canonical"])],
            "featureImplementation": reference(ROOT/"server/sports_current_statcast/mlb_v18_current_features.py"),
            "adapterImplementation": reference(Path(__file__)),
            "rawFeatureOrder": contract["rawFeatureColumns"]}))
        cache_path = args.output_root / "composition-keys" / f"{cache_identity}.json"
        if cache_path.exists():
            pointer = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = reference(pointer["path"])
            if cached != pointer:
                raise ValueError("Immutable composition cache checksum differs")
            composition = json.loads(Path(pointer["path"]).read_text(encoding="utf-8"))
            reused_composition = True
        else:
            composition = json_safe(compose_current_game(snapshot, adapt_source_bundle(bundle, snapshot), contract))
            pointer, _ = write_object(args.output_root, "game-composition.json", composition)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("x", encoding="utf-8") as stream:
                json.dump(pointer, stream, sort_keys=True, separators=(",", ":"))
            reused_composition = False
        composition["venueTimezone"] = composition.get("event", {}).get("venueTimezone")
        composition["sourceCutoff"] = {"playerHistoryCompleteThrough": bundle["authority"].get("completeThrough"),
            "annualSeasonPolicy": "LATEST_ELIGIBLE_PRIOR_SEASON", "evidenceAvailableAt": bundle["authority"].get("availableAsOf"),
            "snapshotCapturedAt": snapshot["capturedAt"]}
        compositions.append(json_safe(composition))
        composition_reuse.append({"gameId": snapshot["game"]["game_id"], "reused": reused_composition,
            "composition": pointer, "cacheKey": cache_identity})
        print(json.dumps({"event": "CURRENT_GAME_COMPOSED", "gameId": snapshot["game"]["game_id"],
            "unchangedGameCompositionReused": reused_composition,
            "coverage": composition["coverage"], "blockers": composition["blockers"]}, default=str), flush=True)
    source_summary = {"schemaVersion": "MLB_V18_CURRENT_SOURCE_SUMMARY_V1",
        "paRows": len(bundle["pa_history"]), "pitchRows": len(bundle["pitches"]), "completedGames": len(bundle["games"]),
        "scheduleIdentityRows": len(bundle["schedule_identity_rows"]), "annualPriorRows": len(bundle["annual_priors"]),
        "historyAuthority": {k:v for k,v in bundle["authority"].items() if not k.startswith("_")},
        "annualAuthority": bundle["annual_authority"],
        "currentPlayerIdentityEvidence": bundle["currentPlayerIdentityEvidence"],
        "acquisitionAttempt": reference(args.source_attempt)}
    source_ref, _ = write_object(args.output_root, "source-summary.json", json_safe(source_summary))
    engine = CurrentV18Engine()
    model_ref, _ = write_object(args.output_root, "v18-model-registration.json", engine.model_identity)
    # Complete one-row-per-source-field accounting; later games retain their own
    # per-row statuses, never borrow another game's player values or lineup.
    reports = [r for c in compositions for r in c.get("fieldReports", [])]
    best = max(reports, key=lambda r:r["rawSupportedCount"], default=None)
    availability = {}
    for name in contract["rawFeatureColumns"]:
        f = next((f for f in best["fields"] if f["field"] == name), None) if best else None
        category = f["category"] if f else 5
        availability[name] = {"category": category,
            "evidence": {"sourceSummary": source_ref, "currentCapture": capture,
                "representativeRow": best.get("canonicalPaId") if best else None,
                "provenance": f.get("provenance") if f else None},
            "status": f["status"] if f else "NO_CONFIRMED_CURRENT_MATCHUP_AVAILABLE",
            "repair": "NONE_ALREADY_SOURCE_BACKED" if f and f["supported"] else
                "Supply exact timestamped complete history/state or unresolved source field; unknown is not no-history. See per-game dependency receipt."}
    metadata_path = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/4171306af87bee46e74d2b5141189a5916382967322592243bf71e9eed9cf684.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    specification = json.loads((ROOT / "server/sports_current_statcast/mlb_feature_treatment_spec_v1.json").read_text(encoding="utf-8"))
    specs = specification.get("features", [])
    if isinstance(specs, dict):
        specs = [{"feature_name":k, **v} for k,v in specs.items()]
    field_contract = reconcile_field_contract(contract["rawFeatureColumns"], metadata,
        availability=availability, field_specifications=specs)
    field_ref, _ = write_object(args.output_root, "raw246-field-contract.json", json_safe(field_contract))
    # Match the verified Windows inference context; this is not a model refit or
    # a hyperparameter change. Keep native inference bounded to four workers.
    with threadpool_limits(limits=4):
        result = publish_slate(snapshot_collection, compositions, output_root=args.output_root)
    result.update(sourceSummary=source_ref, acceptedReload=reload_ref, modelRegistration=model_ref,
        normalizedSourceCache=bundle.get("cache"), gameCompositionReuse=composition_reuse,
        fieldContract=field_ref, rawFieldCategoryCounts=field_contract["categoryCounts"],
        rawSourceFamilyCounts=field_contract["sourceFamilyCounts"], currentCapture=capture,
        actualAispModelIdentities=sorted({(r["model_name"], r["model_version"]) for g in inventory["games"]
            for r in g.get("existingForecastMetadata", [])}))
    result["completeRunReceipt"], _ = write_object(args.output_root, "complete-run.json", json_safe(result))
    print(json.dumps(json_safe(result), indent=2), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-attempt", type=Path, help="Exact attempt; omitted selects latest local immutable attempt, including failures")
    parser.add_argument("--inventory", type=Path, help="Explicit immutable replay for diagnostics; late publication still forbidden")
    parser.add_argument("--output-root", type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        failure = {"schemaVersion": "MLB_V18_CURRENT_STATE_LAUNCH_FAILURE_V1",
            "failedAt": datetime.now(timezone.utc).isoformat(), "errorType": type(exc).__name__,
            "error": str(exc), "traceback": traceback.format_exc(),
            "sourceAttempt": str(args.source_attempt), "retryAutomatic": False,
            "aispWrites": 0, "fits": 0, "finalOotPayloadReads": 0}
        receipt, _ = write_object(args.output_root, "launch-failure.json", failure)
        print(json.dumps({"failureReceipt": receipt}), flush=True)
        raise
