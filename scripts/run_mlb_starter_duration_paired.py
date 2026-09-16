"""One bounded research execution; optional authorized cached intake, no fits."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_starter_duration_paired_publication import (
    OUTPUT, FLAGS, declare, read, reference, save, tick, utc, verified, verify_published_pointer,
    production_busy,
)
from server.sports_current_statcast.mlb_v18_unattended import atomic_state, single_owner


def published_pairs(root):
    result = []
    for path in sorted((root/"published").glob("*.json")):
        pointer = json.loads(path.read_text(encoding="utf-8"))
        pair, receipt = verify_published_pointer(pointer)
        result.append((pair, pointer))
    return result


def score(root):
    from dotenv import dotenv_values
    from server.sports_current_statcast.mlb_starter_duration_paired_scoring import read_persisted_finals, score_pair
    pairs = published_pairs(root)
    # Empty/future-only input opens no outcome connection in the reader.
    started = any(utc(p["scheduledStartUtc"]) < datetime.now(timezone.utc) for p, _ in pairs)
    database_url = (dotenv_values(Path("C:/Users/james/ai-sports-predictor/.env"))["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql+psycopg2://")
                    if started else "")
    finals = read_persisted_finals([p for p, _ in pairs], database_url=database_url)
    final_ref = save("persisted-final-read.json", finals, root)
    index = {f["gameId"]: f for f in finals["records"]}
    scored, awaiting = [], []
    for pair, pointer in pairs:
        final = index.get(pair["gameId"])
        if not final or final["status"] != "FINAL":
            awaiting.append({"gameId": pair["gameId"], "commonPairId": pair["commonPairId"], "status": "AWAITING_PERSISTED_FINAL"})
            continue
        result = score_pair(pair, read(pair["population"]), {**final, "sourceRead": final_ref})
        key = root/"score-keys"/(result["scoreIdentity"]+".json")
        if key.exists():
            ref = json.loads(key.read_text(encoding="utf-8"))
            read(ref)
        else:
            ref = save("paired-game-score.json", {**result, "pair": pointer["pair"]}, root)
            atomic_state(key, ref)
        # One current result per pair; earlier corrected-final results stay immutable.
        atomic_state(root/"scores-by-pair"/(pair["commonPairId"]+".json"), ref)
        scored.append({"gameId": pair["gameId"], "commonPairId": pair["commonPairId"], "score": ref})
    return save("scoring-receipt.json", {"schemaVersion": "MLB_STARTER_DURATION_PAIRED_SCORING_RECEIPT_V1",
        "scoredAt": datetime.now(timezone.utc).isoformat(), "pairCount": len(pairs), "scoredCount": len(scored),
        "awaitingFinalCount": len(awaiting), "scored": scored, "awaiting": awaiting, "finalRead": final_ref,
        "matchedGames": len(scored), "modelFits": 0, "providerCalls": 0, "aispWrites": 0, **FLAGS}, root)


def export_exchange(root, destination):
    """Copy only this research namespace; no champion pointer or AISP access."""
    destination = destination.resolve()
    allowed = Path("C:/Users/james/asp-model-exchange/mlb-starter-duration-research-v1").resolve()
    if destination != allowed:
        raise ValueError("ONLY_THE_EXPLICITLY_AUTHORIZED_RESEARCH_EXCHANGE_NAMESPACE_IS_ALLOWED")
    current = json.loads((root/"current.json").read_text(encoding="utf-8"))
    handoff = read(current["handoff"])
    refs = {}
    quarantined_sources = {}
    # Copy reachable research JSON objects, not production files or executable code.
    def visit(value):
        if isinstance(value, dict):
            if {"path", "sha256", "bytes"} <= set(value):
                path = Path(value["path"]).resolve()
                quarantine_root = (root/"intake/prospective-only-source-quarantine").resolve()
                if path.is_relative_to(quarantine_root):
                    # These are outcome-bearing source records, not forecast
                    # payloads. Keep them exclusively in their local quarantine.
                    quarantined_sources[value["sha256"]] = {
                        "sha256": value["sha256"], "bytes": value["bytes"],
                        "reason": "PROSPECTIVE_FEATURE_CONSTRUCTION",
                        "status": "LOCAL_QUARANTINED_LINEAGE_ONLY_NOT_EXPORTED"}
                    return
                if path.is_relative_to(root.resolve()) and value["sha256"] not in refs:
                    path = verified(value)
                    target = destination/"objects/sha256"/value["sha256"]/path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = path.read_bytes()
                    if target.exists():
                        if target.read_bytes() != data:
                            raise ValueError("IMMUTABLE_EXCHANGE_COLLISION")
                    else:
                        with target.open("xb") as handle:
                            handle.write(data)
                    refs[value["sha256"]] = {**reference(target), "relativePath": target.relative_to(destination).as_posix(), "sourcePath": str(path)}
                    if path.suffix == ".json":
                        visit(json.loads(data))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(current)
    body = {"schemaVersion": "MLB_STARTER_DURATION_PAIRED_RESEARCH_V1_EXCHANGE_INDEX",
        "handoff": refs[current["handoff"]["sha256"]], "pairCount": handoff["pairCount"],
        "artifactsBySha256": refs, "publishedAt": datetime.now(timezone.utc).isoformat(),
        "quarantinedSourceLineageNotExported": quarantined_sources,
        "sourceRefsOutsideNamespace": "Lineage only; never execute or use as an unverified forecast payload",
        "consumerResolution": "Resolve research descriptors by SHA256 in artifactsBySha256; original sourcePath is provenance only",
        "importAction": "NO_FORECAST_IMPORT_WHILE_PAIR_COUNT_ZERO" if not handoff["pairCount"] else "IMPORT_BOTH_PRECOMPUTED_ARMS_RESEARCH_ONLY", **FLAGS}
    data = __import__("server.sports_current_statcast.mlb_v18_daily_slate", fromlist=["json_safe"]).json_safe(body)
    atomic_state(destination/"current.json", data)
    return reference(destination/"current.json")


def resume(declaration_ref, *, root=OUTPUT, allow_free_network=False):
    """Existing intake -> projection -> dispatcher, with independent locks.

    The normal task scheduler may call this once; it never sleeps or installs a
    collector. Acquisition has its own durable shared request/byte budget and
    protected-period guard. Missing authority stays unresolved, not cold-start.
    """
    from zoneinfo import ZoneInfo
    root = Path(root)
    with single_owner(root/"resume.lock") as owns:
        if not owns:
            return {"status": "DEFERRED_EXISTING_RESEARCH_RESUME"}
        if (root/"STOP").exists():
            return {"status": "STOP_SWITCH_ACTIVE"}
        if production_busy():
            return {"status": "DEFERRED_PRODUCTION_PUBLISHER_PRIORITY",
                "nextCheckUtc": (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        declaration = read(declaration_ref)
        current = datetime.now(timezone.utc)
        state_path = root/"readiness-state.json"
        previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        states = previous.get("games", {}) if previous.get("declarationSha256") == declaration_ref["sha256"] else {}
        eligible = [g for g in sorted(declaration["games"], key=lambda g: (g["deadlineUtc"], g["gameId"]))
            if current < utc(g["deadlineUtc"])
            and not (root/"published"/(g["gameId"]+".json")).exists()
            and not (root/"attempts"/(g["gameId"]+".json")).exists()
            and (not states.get(g["gameId"], {}).get("nextCheckUtc") or current >= utc(states[g["gameId"]]["nextCheckUtc"]))]
        intake = {"status": "NOT_DUE_OR_NO_OPEN_UNATTEMPTED_GAME", "newRequests": 0}
        projection = {"status": "NO_NEW_INTAKE_PROJECTION"}
        preparation = []
        if eligible:
            # Inspect every due matchup in declared deadline order. Source
            # intake remains explicitly scoped; unavailable earlier inputs
            # never prevent the dispatcher from trying later supported games.
            from scripts.inventory_mlb_current_slate import capture_current_slate
            day = utc(eligible[0]["scheduledStartUtc"]).astimezone(ZoneInfo("America/New_York")).date().isoformat()
            try:
                _, capture = capture_current_slate(output_root=root/"inventory", slate_date=day,
                    game_ids=[g["gameId"] for g in eligible])
                collection = json.loads(Path(capture["snapshotsPath"]).read_text(encoding="utf-8"))
                snapshots = {s["game"]["game_id"]: s for s in collection["snapshots"]}
                from scripts.acquire_mlb_starter_duration_history import PITCHERS, run_bounded_intake
                scoped_intake_done = False
                for chosen in eligible:
                    entry = {"gameId": chosen["gameId"], "deadlineUtc": chosen["deadlineUtc"]}
                    snapshot = snapshots.get(chosen["gameId"])
                    ids = [str(s["starter"].get("mlbamId")) for s in (snapshot or {}).get("sides", []) if s.get("starter", {}).get("mlbamId")]
                    if datetime.now(timezone.utc) >= utc(chosen["deadlineUtc"]):
                        entry["status"] = "TERMINAL_DEADLINE_CLOSED_NO_BACKFILL"
                    elif len(ids) != 2 or len(set(ids)) != 2:
                        entry["status"] = "PENDING_CURRENT_STARTER_IDENTITIES"
                    elif utc(snapshot["game"]["starts_at"]) != utc(chosen["scheduledStartUtc"]):
                        entry["status"] = "PENDING_CHANGED_SCHEDULE_REQUIRES_NEW_DECLARATION"
                    elif set(ids) != set(PITCHERS):
                        entry.update(status="NOT_ACQUIRED_BY_EXISTING_BOUNDED_INTAKE_SCOPE",
                            pitcherIds=ids, meaning="Existing certified inputs may still qualify in the all-game dispatcher; no implicit acquisition expansion")
                    elif scoped_intake_done:
                        entry["status"] = "SCOPED_HISTORY_ALREADY_RECHECKED_THIS_RESUME"
                    else:
                        scoped_intake_done = True
                        through = (utc(chosen["scheduledStartUtc"]).astimezone(ZoneInfo(snapshot["game"].get("timezone") or "America/New_York")).date()-timedelta(days=1)).isoformat()
                        try:
                            intake = run_bounded_intake(pitcher_ids=tuple(ids), through=through, allow_free_network=allow_free_network)
                            entry["status"] = intake.get("status", "INTAKE_RETURNED_SOURCE_EVIDENCE")
                            if intake.get("manifestRef"):
                                entry["intakeManifest"] = intake["manifestRef"]
                                try:
                                    from server.sports_current_statcast.mlb_starter_duration_history import build_compatible_projection
                                    projection = build_compatible_projection(intake["manifestRef"]["path"], as_of_utc=datetime.now(timezone.utc).isoformat())
                                except ImportError:
                                    projection = {"status": "PENDING_COMPATIBLE_PROJECTION_IMPLEMENTATION", "intakeManifest": intake["manifestRef"]}
                                except Exception as exc:
                                    projection = {"status": "COMPATIBLE_PROJECTION_UNRESOLVED", "intakeManifest": intake["manifestRef"],
                                        "errorType": type(exc).__name__, "reason": str(exc)}
                        except Exception as exc:
                            entry.update(status="INTAKE_UNRESOLVED", errorType=type(exc).__name__, reason=str(exc))
                            intake = entry
                    preparation.append(entry)
                if not scoped_intake_done:
                    intake = {"status": "NO_DUE_GAME_WITHIN_EXISTING_BOUNDED_INTAKE_SCOPE", "newRequests": 0}
            except Exception as exc:
                intake = {"status": "INTAKE_OR_PROJECTION_UNRESOLVED", "errorType": type(exc).__name__, "reason": str(exc)}
        intake_ref = save("resume-intake-receipt.json", {"checkedAt": datetime.now(timezone.utc).isoformat(),
            "declaration": declaration_ref, "intake": intake, "projection": projection, "gamePreparation": preparation,
            "protectedAccessNotExpanded": True, "numericalAttemptConsumed": False}, root)
        tick_result = tick(declaration_ref, root=root)
        exchange = {"status": "NO_CHANGED_HANDOFF"}
        if tick_result.get("handoff"):
            try:
                destination = Path("C:/Users/james/asp-model-exchange/mlb-starter-duration-research-v1")
                old = json.loads((destination/"current.json").read_text(encoding="utf-8")) if (destination/"current.json").exists() else {}
                if old.get("handoff", {}).get("sha256") != tick_result["handoff"]["sha256"]:
                    exchange = {"status": "EXPORTED", "index": export_exchange(root, destination)}
            except Exception as exc:
                exchange = {"status": "LOCAL_HANDOFF_PRESERVED_EXCHANGE_ACCESS_REQUIRED", "errorType": type(exc).__name__, "reason": str(exc),
                    "operatorCommand": ".\\.venv\\Scripts\\python.exe scripts/run_mlb_starter_duration_paired.py export"}
        try:
            scoring = score(root)
        except Exception as exc:
            scoring = {"status": "PERSISTED_FINAL_SCORING_UNRESOLVED", "errorType": type(exc).__name__, "reason": str(exc)}
        result = {"schemaVersion": "MLB_STARTER_DURATION_BOUNDED_RESUME_V1", "intakeReceipt": intake_ref,
            "tick": tick_result, "exchange": exchange, "scoring": scoring,
            "nextCheckUtc": tick_result.get("nextCheckUtc"), "schedulerInstalledByCommand": False}
        receipt = save("resume-execution-receipt.json", result, root)
        return {"receipt": receipt, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["declare", "tick", "resume", "score", "export"])
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--declaration", type=Path)
    parser.add_argument("--output-root", type=Path, default=OUTPUT)
    parser.add_argument("--allow-free-network", action="store_true",
        help="Use already authorized no-charge bounded intake; never overrides protected-date or cumulative-budget guards")
    args = parser.parse_args()
    root = args.output_root.resolve()
    if not root.is_relative_to(ROOT/"outputs/mlb-starter-duration-paired-research-v1"):
        raise ValueError("ISOLATED_RESEARCH_OUTPUT_ROOT_REQUIRED")
    if args.command == "declare":
        if not args.snapshot:
            parser.error("declare requires --snapshot (an existing current capture)")
        collection = json.loads(args.snapshot.read_text(encoding="utf-8"))
        value = declare(collection, reference(args.snapshot), root=root)
    elif args.command in ("tick", "resume"):
        if not args.declaration:
            parser.error("tick/resume requires --declaration (immutable slate authority)")
        ref = reference(args.declaration)
        if args.declaration.parent.name != ref["sha256"]:
            raise ValueError("CONTENT_ADDRESSED_DECLARATION_REQUIRED")
        value = (resume(ref, root=root, allow_free_network=args.allow_free_network)
            if args.command == "resume" else tick(ref, root=root))
    elif args.command == "score":
        value = score(root)
    else:
        value = export_exchange(root, Path("C:/Users/james/asp-model-exchange/mlb-starter-duration-research-v1"))
    print(json.dumps(value, indent=2, default=str))


if __name__ == "__main__":
    main()
