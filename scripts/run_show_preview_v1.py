"""Bounded manual/deployment hook: prepare, publish, or verify exact preview reuse.

No scheduler is registered. The existing owner may invoke this at 15:15 ET,
after identity/source preparation at 15:00; all new publications stop at16:00.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_shared.show_preview import (NY, TREE, canonical, checked_file, clocks, consumer_validator,
    digest, immutable, iso, physical, publish, utc, verify_package)
from server.sports_shared.show_preview_sources import nfl_source, cfb_source

OUT = ROOT / "outputs/multisport-show-preview-producer-v1"
EXCHANGE = Path(r"C:\Users\james\asp-model-exchange")


def prepare(out, context_path, source_exchange, slate_date=None):
    started = time.perf_counter()
    context = json.loads(context_path.read_bytes())
    now = datetime.now(timezone.utc)
    index_path = source_exchange / "aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json"
    raw = index_path.read_bytes()
    immutable(out / "source-index-snapshots" / (digest(raw)+".json"), raw)
    index = json.loads(raw)
    candidates = {}
    for address in index["currentBundleSha256s"]:
        path = index_path.parent / "sha256" / address / "bundle.json"
        bundle = json.loads(path.read_bytes())
        if digest(path.read_bytes()) != address:
            raise ValueError("NFL bundle address mismatch")
        for f in bundle["forecasts"]:
            slate = utc(f["scheduledStartUtc"]).astimezone(NY).date().isoformat()
            if (f["season"] != 2026 or utc(f["scheduledStartUtc"]) <= now
                    or utc(f["scheduledStartUtc"]) >= utc(context["through_utc"])
                    or (slate_date and slate != slate_date)):
                continue
            key = f["eventId"]
            rank = (utc(f["availableAsOfUtc"]), f["snapshotVersion"], {"EARLY": 0, "CURRENT": 1, "FINAL_PREGAME": 2}[f["snapshotType"]])
            if key not in candidates or rank > candidates[key][0]:
                candidates[key] = (rank, path, f)
    sources, inventory = [], []
    for _, path, f in sorted(candidates.values(), key=lambda r: (r[2]["scheduledStartUtc"], r[2]["eventId"])):
        source = nfl_source(path, f["forecastId"], context)
        sources.append(source)
        inventory.append({"sport": "NFL", "game": source["game"], "source_forecast_id": source["source_forecast_id"],
                          "status": "SUPPORTED_EXACT_REUSE", "preview_deadline_utc": clocks(source["game"]["slate_date"])["publish_by_utc"]})
    pointer = source_exchange / "cfb-gen1-research-v1/current-v1/current.json"
    # This locator is preserved; select the immutable package named by the
    # completed delivery receipt, not any unpromoted challenger directory.
    delivery = json.loads((ROOT / "outputs/cfb-gen1-current-v1/delivery-index.json").read_bytes())
    source = cfb_source(delivery["exchangePackage"], context)
    if not slate_date or source["game"]["slate_date"] == slate_date:
        sources.append(source)
        inventory.append({"sport": "CFB", "game": source["game"], "source_forecast_id": source["source_forecast_id"],
                          "status": "SUPPORTED_EXACT_REUSE_CANONICAL_BINDING_PENDING" if source["game"]["canonical_game_id"] is None else "SUPPORTED_EXACT_REUSE",
                          "preview_deadline_utc": clocks(source["game"]["slate_date"])["publish_by_utc"]})
    games = {}
    for row in context["rows"]:
        day = utc(row["starts_at"]).astimezone(NY).date().isoformat()
        if row["league"] not in ("MLB", "NBA") or (slate_date and day != slate_date):
            continue
        gid = row["canonical_game_id"]
        game = games.setdefault(gid, {"sport": row["league"], "canonical_game_id": gid, "slate_date": day,
                                     "kickoff_utc": row["starts_at"], "preview_deadline_utc": clocks(day)["publish_by_utc"]})
        game["home" if row["is_home"] else "away"] = row["abbreviation"]
    for g in games.values():
        g["status"] = "MLB_PREVIEW_CONFIGURATION_NOT_ADMITTED" if g["sport"] == "MLB" else "ELIGIBLE_NBA_SOURCE_NOT_REGISTERED"
        g["deadline_status"] = "MISSED_BEFORE_ASSIGNMENT_IMPLEMENTATION" if now > utc(g["preview_deadline_utc"]) else "OPEN"
        g["team_evidence"] = {side: {"starter_status": "UNKNOWN", "lineup_status": "UNKNOWN",
                                    "missing_evidence": ["NO_ADMITTED_PREVIEW_INPUT_BINDING"], "fallback_rule": "NONE"}
                              for side in ("away", "home")}
        inventory.append(g)
    if not any(r["league"] == "NBA" for r in context["rows"]):
        inventory.append({"sport": "NBA", "status": "NO_ELIGIBLE_SLATE_IN_CAPTURED_WINDOW",
                          "window_end_utc": context["through_utc"], "existing_BOS_DET_rewrapped": False})
    value = {"schema_version": "ASP_SHOW_PREVIEW_SOURCE_PLAN_V1", "created_utc": iso(now),
             "context": physical(context_path), "consumer_validator": context["consumer_validator"],
             "scope": "Existing NFL Week 2 and CFB source publications; no outcomes, model loading or acquisition.",
             "sources": sources, "inventory": inventory, "automatic_activation": False,
             "prepare_seconds": time.perf_counter()-started, "provider_calls": 0, "provider_bytes": 0, "aisp_writes": 0}
    path = out / "plans" / "sha256" / (digest(canonical(value))+".json")
    immutable(path, canonical(value))
    if not (out / "initial-plan.json").exists():
        immutable(out / "initial-plan.json", canonical(value))
        immutable(out / "preview-artifact-index.json", canonical({"schema": "ASP_SHOW_PREVIEW_LOCAL_INDEX_V1", "plan": physical(path), "inventory": inventory}))
    print(json.dumps({"plan": physical(path), "supported_sources": len(sources), "inventory_rows": len(inventory),
                      "prepare_seconds": value["prepare_seconds"]}, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("prepare", "publish", "verify"))
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--context", type=Path, default=OUT / "context/context.json")
    p.add_argument("--plan", type=Path, default=OUT / "initial-plan.json")
    p.add_argument("--exchange-root", type=Path, default=EXCHANGE)
    p.add_argument("--slate-date", help="Optional exact Eastern game date; existing daily owner uses tomorrow.")
    args = p.parse_args()
    if args.mode == "prepare":
        prepare(args.out, args.context, args.exchange_root, args.slate_date)
        return
    plan = json.loads(args.plan.read_bytes())
    pin = plan["consumer_validator"]
    validator = consumer_validator(pin["path"], pin["sha256"])
    if args.mode == "publish":
        sources = [s for s in plan["sources"] if not args.slate_date or s["game"]["slate_date"] == args.slate_date]
        result = publish(sources, args.exchange_root, validator)
        raw = canonical(result)
        path = args.out / "publication-runs/sha256" / (digest(raw)+".json")
        immutable(path, raw)
        print(json.dumps({"receipt": physical(path), "discovery": result["discovery"],
                          "produced_derivatives": sum(r["disposition"] == "PUBLISHED" for r in result["results"]),
                          "reused_previews": sum(r["disposition"] == "REUSED_BYTE_IDENTICAL" for r in result["results"]),
                          "models_executed": 0, "new_simulations": 0}, indent=2))
    else:
        root = args.exchange_root / TREE
        discovery = json.loads((root / "discovery.json").read_bytes())
        for item in discovery["packages"]:
            verify_package(root / item["package_path"], validator)
        print(json.dumps({"verified_packages": len(discovery["packages"]), "original_sources_byte_identical": True,
                          "consumer_validator": pin, "discovery": physical(root / "discovery.json")}, indent=2))


if __name__ == "__main__":
    main()
