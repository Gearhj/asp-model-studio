"""Publish the bounded 2026-09-15 producer-to-consumer operational handoff."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_shared.paper_research_eligibility import (
    canonical_json_bytes, immutable_bytes, immutable_json, package_address, physical,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--published-utc", required=True)
    parser.add_argument("--exchange-root", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/four-sport-operational-handoff-20260915-v1"))
    args = parser.parse_args()
    eligibility_run = json.loads(Path("outputs/multisport-paper-eligibility-20260915-v1/run.json").read_bytes())
    by_sport = {item["sport"]: item for item in eligibility_run["receipts"]}
    references = {
        "mlbReadiness": physical(args.output_root / "mlb-september-15-readiness.json"),
        "nflWeek2Readiness": physical(args.output_root / "nfl-week-2-readiness.json"),
        "rosterChangeRequest": physical(args.output_root / "roster-orchestration-repair/change-request.json"),
        "rosterPatch": physical(args.output_root / "roster-orchestration-repair/aisp-independent-roster-refresh.patch"),
        "nbaEligibilityManifest": by_sport["NBA"]["manifest"],
        "nbaEligibilitySupplement": by_sport["NBA"]["supplement"],
        "nbaClaudeHandoff": by_sport["NBA"]["exchangeHandoff"],
        "cfbEligibilityManifest": by_sport["CFB"]["manifest"],
        "cfbEligibilitySupplement": by_sport["CFB"]["supplement"],
        "cfbClaudeHandoff": by_sport["CFB"]["exchangeHandoff"],
    }
    doc = {
        "schemaVersion": "ASP_FOUR_SPORT_OPERATIONAL_HANDOFF_20260915_V1",
        "kind": "DELIVERY_STATUS_AND_CONSUMER_CHANGE_REQUEST",
        "publishedAtUtc": args.published_utc,
        "section1Recovery": {
            "status": "COMPLETED_BEFORE_THIS_HANDOFF_AND_NOT_REPEATED",
            "deploymentCommit": "77d39e1ae08e05be82e19bdb0bab21999fba1d3b",
            "manifestSha256": "8bf005eeff64388cefa356e55815c4f24f938a22d66a27339b074cb79e7d3a6e",
            "naturalTick": "BOUNDED_TICK_COMPLETED",
            "pythonExitCode": 0,
            "stopTouchedByThisHandoff": False,
        },
        "mlb": {
            "gameCount": 15, "forecastProduced": 0, "forecastReused": 0,
            "forecastPublished": 0, "importConfirmed": 0,
            "status": "ALL_NOT_YET_T60; CONFIRMED_LINEUPS_PENDING; BOS@TEX ALSO_HOME_STARTER_PENDING",
            "ownerAction": "NO_MANUAL_INVOCATION; ALLOW EXISTING S4U OWNER TO RUN",
        },
        "nfl": {
            "week2Games": 16, "retainedRevisions": 32, "jointDrawCountEach": 10000,
            "model": "NFL_M1_XGBOOST/NFL_M1_2026_RESEARCH_SHADOW_V1",
            "tieMeaning": "EQUAL_RETAINED_FINAL_SCORE_DRAWS; NOT_OTHER",
            "storedSportsbookReferenceLines": 0,
            "existingPaperPolicyEligibleGames": 0,
            "nextWindow": {"event": "DET@BUF", "opensUtc": "2026-09-17T23:45:00Z", "decisionCutoffUtc": "2026-09-18T00:00:00Z", "kickoffUtc": "2026-09-18T00:15:00Z"},
        },
        "nba": {"eligibilityPackage": by_sport["NBA"], "forecastRegenerated": False},
        "cfb": {"eligibilityPackage": by_sport["CFB"], "forecastRegenerated": False},
        "consumerActions": [
            "Register ASP_NBA_PAPER_RESEARCH_ELIGIBILITY_V1 and ASP_CFB_PAPER_RESEARCH_ELIGIBILITY_V1 in AISP's generic supplement verifier by sport; it currently admits only the NFL version and discovers only nfl-labs-supplements.",
            "Import the exact content-addressed NBA and CFB directories with byte, event, engine, forecast, model, policy and configuration checks; return immutable import/activation/display receipts.",
            "Apply the bounded refresh_mlb_data patch in the consumer-owned AISP repository, add native per-family structured request receipts, run the retained ConnectTimeout case, and return its deployment/test receipt.",
        ],
        "accounting": {"modelExecutions": 0, "newForecasts": 0, "providerRequests": 0, "aispWrites": 0},
        "references": references,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    local_doc = immutable_json(args.output_root / "operational-handoff.json", doc)
    md = "\n".join([
        "# CLAUDE_HANDOFF — four-sport operational delivery", "",
        "This is a delivery-status update plus two bounded consumer change requests. It does not activate a policy or modify AISP.", "",
        f"Operational handoff JSON: `{local_doc['path']}`; SHA-256 `{local_doc['sha256']}` ({local_doc['bytes']} bytes).",
        f"NBA eligibility: `{by_sport['NBA']['exchangeDirectory']}`; address `{by_sport['NBA']['supplementAddress']}`.",
        f"CFB eligibility: `{by_sport['CFB']['exchangeDirectory']}`; address `{by_sport['CFB']['supplementAddress']}`.",
        "MLB: all 15 games were before T-60 at the recorded inventory; lineups were pending and BOS–TEX also lacked the home starter. Use the existing S4U owner; no manual run occurred.",
        "NFL: the ledger contains all 16 effective Week 2 IDs, clocks and probabilities. Tie means equal modeled final scores. No stored sportsbook reference was found, and the DEN–KC authorization does not extend to Week 2.",
        "Consumer work: admit the two sport-specific eligibility versions through the existing byte/binding verifier and apply the exact independent-roster refresh patch. Return separate import, activation, display and roster-deployment receipts.",
        "", "No provider call, model execution, forecast regeneration or AISP write was performed for this handoff.", "",
    ]).encode("utf-8")
    md_ref = immutable_bytes(args.output_root / "CLAUDE_HANDOFF.md", md)
    manifest_identity = {
        "schemaVersion": "ASP_OPERATIONAL_HANDOFF_MANIFEST_V1",
        "kind": doc["kind"],
        "artifacts": [
            {"file": "operational-handoff.json", "sha256": local_doc["sha256"], "bytes": local_doc["bytes"]},
            {"file": "CLAUDE_HANDOFF.md", "sha256": md_ref["sha256"], "bytes": md_ref["bytes"]},
        ],
    }
    address = package_address(manifest_identity)
    manifest = {**manifest_identity, "packageSha256": address}
    destination = args.exchange_root / "model-studio-operational-handoffs/sha256" / address
    immutable_bytes(destination / "operational-handoff.json", (args.output_root / "operational-handoff.json").read_bytes())
    immutable_bytes(destination / "CLAUDE_HANDOFF.md", md)
    immutable_json(destination / "manifest.json", manifest)
    receipt = {
        "schemaVersion": "ASP_OPERATIONAL_HANDOFF_DELIVERY_V1", "packageAddress": address,
        "directory": str(destination.resolve()), "publicationUtc": args.published_utc,
        "manifest": physical(destination / "manifest.json"),
        "handoff": physical(destination / "operational-handoff.json"),
        "claudeHandoff": physical(destination / "CLAUDE_HANDOFF.md"),
        "consumerAcknowledgement": "NOT_ESTABLISHED",
    }
    immutable_json(args.output_root / "publication-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
