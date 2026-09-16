"""Build the 2026-09-15 operational evidence ledger without model execution."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_shared.paper_research_eligibility import canonical_json_bytes, immutable_bytes, physical


NY = ZoneInfo("America/New_York")
MLB_TICK = ROOT / "outputs/mlb-v18-unattended-v1/objects/sha256/1437d29da113892da66d0aba62adc8dd99b7cd940f8bc47704896076a376119b/tick.json"
MLB_SNAPSHOT = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/inventory/sha256/797fe51368170fb7880d9eb1f10599676b77bb6e6743654a41231e2bd7b76770/current-game-pregame-snapshots.json"
NFL_INDEX = Path(r"C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\nfl-2026-research-shadow-index.json")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: object) -> dict:
    return immutable_bytes(path, canonical_json_bytes(value))


def build_mlb(generated: str) -> dict:
    tick = json.loads(MLB_TICK.read_bytes())
    snapshot_doc = json.loads(MLB_SNAPSHOT.read_bytes())
    snapshots = {item["game"]["source_game_id"]: item for item in snapshot_doc["snapshots"]}
    games = []
    for discovered in tick["discovery"]["games"]:
        if discovered["gameDate"] != "2026-09-15":
            continue
        source_id = str(discovered["mlbamGamePk"])
        snapshot = snapshots[source_id]
        start = parse(discovered["scheduledStartUtc"])
        sides = {side["side"]: side for side in snapshot["sides"]}
        side_status = {}
        blockers = []
        for role in ("AWAY", "HOME"):
            side = sides[role]
            starter = side.get("starter") or {}
            lineup = side["lineupAuthority"]
            team = side["team"]["abbreviation"]
            roster_rows = [r for r in snapshot["currentRoster"] if r["team_code"] == team and r["position"] == "P"]
            roster_clock = max((r["available_as_of"] for r in roster_rows), default=None)
            if not starter.get("mlbamId"):
                blockers.append(f"{role}_STARTER_IDENTITY_UNAVAILABLE")
            if not lineup["isComplete"]:
                blockers.append(f"{role}_CONFIRMED_LINEUP_UNAVAILABLE")
            if not roster_rows:
                blockers.append(f"{role}_ACTIVE_PITCHING_ROSTER_UNAVAILABLE")
            side_status[role.lower()] = {
                "team": team,
                "starter": {
                    "name": starter.get("name"), "mlbamId": starter.get("mlbamId"),
                    "state": starter.get("confirmationState", "UNKNOWN"),
                    "sourceClock": starter.get("availableAsOf"),
                },
                "lineup": {
                    "status": lineup["status"], "isComplete": lineup["isComplete"],
                    "sourceClock": lineup.get("availableAsOf"),
                },
                "activePitchingRoster": {
                    "status": "FRESH" if roster_rows else "UNAVAILABLE",
                    "pitcherCount": len(roster_rows), "sourceClock": roster_clock,
                },
            }
        games.append({
            "canonicalGameId": discovered["canonicalGameId"],
            "internalGameId": discovered["gameId"],
            "mlbamGamePk": discovered["mlbamGamePk"],
            "orientation": f"{side_status['away']['team']}@{side_status['home']['team']}",
            "scheduledStartUtc": iso(start),
            "scheduledStartEdt": start.astimezone(NY).isoformat(),
            "timing": {
                "t60CheckUtc": iso(start - timedelta(minutes=60)),
                "t45DeliveryTargetUtc": iso(start - timedelta(minutes=45)),
                "t30ConsumerWindowUtc": iso(start - timedelta(minutes=30)),
                "t15DecisionCutoffUtc": iso(start - timedelta(minutes=15)),
                "t5ResearchCutoffUtc": iso(start - timedelta(minutes=5)),
            },
            "sides": side_status,
            "forecastStatus": "PENDING_INPUTS",
            "publicationStatus": "ACCOUNTING_ONLY_NOT_A_FORECAST",
            "aispImportAcknowledgement": "NOT_ESTABLISHED",
            "blockers": blockers,
        })
    slate = next(item for item in tick["slates"] if item["slateDate"] == "2026-09-15")
    return {
        "schemaVersion": "ASP_MLB_V18_READINESS_LEDGER_20260915_V1",
        "generatedAtUtc": generated,
        "sourceReceipt": physical(MLB_TICK),
        "snapshotEvidence": physical(MLB_SNAPSHOT),
        "owner": "ASP MLB V18 Research Publisher / windows-task-scheduler",
        "timingContract": tick["timingContract"],
        "counts": {"games": len(games), "forecastProduced": 0, "forecastReused": 0, "forecastPublished": 0, "importConfirmed": 0},
        "exchangeAccountingPackage": slate["exchange"],
        "games": games,
    }


def build_nfl(generated: str) -> dict:
    index = json.loads(NFL_INDEX.read_bytes())
    root = NFL_INDEX.parent
    revisions = []
    for address in index["currentBundleSha256s"]:
        path = root / "sha256" / address / "bundle.json"
        bundle = json.loads(path.read_bytes())
        for forecast in bundle["forecasts"]:
            if forecast.get("week") != 2:
                continue
            revisions.append({
                "eventId": forecast["eventId"],
                "orientation": f"{forecast['awayTeam']['abbreviation']}@{forecast['homeTeam']['abbreviation']}",
                "scheduledStartUtc": forecast["scheduledStartUtc"],
                "snapshotType": forecast["snapshotType"],
                "snapshotVersion": forecast["snapshotVersion"],
                "forecastId": forecast["forecastId"],
                "sourceCutoffUtc": forecast["sourceCutoffUtc"],
                "forecastCutoffUtc": forecast["forecastCutoffUtc"],
                "availableAsOfUtc": forecast["availableAsOfUtc"],
                "bundleGeneratedAtUtc": bundle["generatedAtUtc"],
                "probabilities": {"awayWin": forecast["awayWinProbability"], "homeWin": forecast["homeWinProbability"], "tie": forecast["tieProbability"]},
                "expectedScores": {"away": forecast["expectedAwayScore"], "home": forecast["expectedHomeScore"]},
                "engine": forecast["engine"],
                "simulator": forecast["simulator"],
                "features": forecast["features"],
                "marketReference": None,
                "bundleAddress": address,
                "bundle": physical(path),
            })
    rank = {"EARLY": 1, "CURRENT": 2, "FINAL_PREGAME": 3}
    effective = []
    for event_id in sorted({item["eventId"] for item in revisions}):
        candidates = [item for item in revisions if item["eventId"] == event_id]
        chosen = max(candidates, key=lambda item: (rank.get(item["snapshotType"], 0), item["snapshotVersion"], item["availableAsOfUtc"]))
        kickoff = parse(chosen["scheduledStartUtc"])
        chosen = {**chosen,
            "finalPregameExpected": True,
            "consumerWindow": {"opensUtc": iso(kickoff - timedelta(minutes=30)), "decisionCutoffUtc": iso(kickoff - timedelta(minutes=15))},
            "paperPolicyEligibility": "NOT_COVERED_BY_EXISTING_DEN_AT_KC_GAME_SPECIFIC_AUTHORIZATION",
            "storedMarketReferenceDisposition": "UNAVAILABLE; modeled query grids are not sportsbook quotes",
        }
        effective.append(chosen)
    return {
        "schemaVersion": "ASP_NFL_WEEK2_PRODUCER_READINESS_20260915_V1",
        "generatedAtUtc": generated,
        "index": physical(NFL_INDEX),
        "indexUpdatedAtUtc": index["updatedAtUtc"],
        "modelIdentity": {
            "engineId": "NFL_M1_XGBOOST", "engineVersion": "NFL_M1_2026_RESEARCH_SHADOW_V1",
            "modelBinarySha256": index["modelBinarySha256"], "modelManifestSha256": index["modelManifestSha256"],
            "featureContractSha256": index["featureContractSha256"],
        },
        "jointDrawCount": 10000,
        "probabilitySemantics": "away/home/tie are mutually exclusive full-game outcomes; tie is genuine simulated final-game tie mass",
        "revisionCount": len(revisions),
        "effectiveGameCount": len(effective),
        "effectiveForecasts": effective,
        "allWeek2Revisions": sorted(revisions, key=lambda item: (item["scheduledStartUtc"], item["snapshotType"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-utc", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/four-sport-operational-handoff-20260915-v1"))
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    mlb = build_mlb(args.generated_utc)
    nfl = build_nfl(args.generated_utc)
    refs = {
        "mlb": write_json(args.output_root / "mlb-september-15-readiness.json", mlb),
        "nfl": write_json(args.output_root / "nfl-week-2-readiness.json", nfl),
    }
    run = {"schemaVersion": "ASP_FOUR_SPORT_OPERATIONAL_EVIDENCE_RUN_V1", "generatedAtUtc": args.generated_utc, "artifacts": refs}
    print(json.dumps({**run, "run": write_json(args.output_root / "run.json", run)}, indent=2))


if __name__ == "__main__":
    main()
