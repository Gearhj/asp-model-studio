"""Build the immutable MLB roster-freshness operational handoff.

The builder consumes only retained pregame evidence and operational receipts.  It
does not query outcomes, acquire provider data, or run a forecast.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_shared.content_addressed_package import (
    IDENTITY_ALGORITHM,
    canonical_identity_bytes,
    member_records,
    package_content_sha256,
    verify_package_directory,
)
from server.sports_current_statcast.mlb_v18_unattended import roster_readiness


PREDECESSOR = ROOT / "outputs/mlb-v18-delivery-timing-audit-v1/sha256/ced67bf4b4a0a4447a67b34f56934729452848f8efc4c1730f7c555fd7b7f972"
NEXT_INVENTORY = ROOT / "outputs/mlb-roster-freshness-repair-v1/preflight-inventory/sha256/f08accd7f14acb40a6f0f028087fcf5b25171a6b399951e8fdd8d0b6d8bb1cde/current-slate-input-inventory.json"
ATL_CHC_SNAPSHOT = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/inventory/sha256/8d85be52ae6b544d6ece4c85b27c7b5b00581759f6819b2d2f75a2f4b5addfaa/current-game-pregame-snapshots.json"
OLD_CUBS_SOURCE = Path("C:/Users/james/ai-sports-predictor/data/raw/mlb_stats_api/2026/09/13/100104_004003_5aef70e607.json")
OUTPUT = ROOT / "outputs/mlb-roster-freshness-repair-v1"


def raw_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def age_hours(at: datetime, evidence: datetime) -> float:
    return round((at - evidence).total_seconds() / 3600, 6)


def roster_map(next_inventory: dict) -> dict[str, datetime]:
    values: dict[str, datetime] = {}
    for game in next_inventory["games"]:
        for row in game.get("currentRoster", []):
            team = row.get("team_code")
            stamp = row.get("observed_at")
            if not team or not stamp:
                continue
            parsed = dt(stamp)
            if team in values and values[team] != parsed:
                # A team's retained roster batch must be internally coherent.
                raise ValueError(f"multiple roster clocks for {team}")
            values[team] = parsed
    return values


def september_14_rows(audit: dict, rosters: dict[str, datetime]) -> list[dict]:
    rows = []
    for game in audit["mlbGames"]:
        start = dt(game["scheduledStart"]["utc"])
        sides = {team: rosters[team] for team in (game["awayTeam"], game["homeTeam"])}
        limiting_team = min(sides, key=sides.get)
        limiting = sides[limiting_team]
        published = game.get("forecastId") is not None
        rows.append({
            "game": f"{game['awayTeam']}@{game['homeTeam']}",
            "mlbamGamePk": game["providerGameId"],
            "canonicalGameId": game["canonicalGameId"],
            "scheduledStartUtc": start.isoformat(),
            "rosterEvidenceUtc": {key: value.isoformat() for key, value in sides.items()},
            "limitingTeam": limiting_team,
            "limitingEvidenceAgeHours": {
                "T_minus_60": age_hours(start - timedelta(minutes=60), limiting),
                "T_minus_45": age_hours(start - timedelta(minutes=45), limiting),
                "T_minus_15_consumer_cutoff": age_hours(start - timedelta(minutes=15), limiting),
            },
            "thresholdHours": 30,
            "refreshAttempt": (
                "AISP daily-pipeline 2026-09-14T10:00:00.016607Z; CHC team-stats request "
                "timed out before its roster request, so CHC roster endpoint was not invoked"
                if limiting_team == "CHC" else
                "AISP daily-pipeline 2026-09-14T10:00:00.016607Z captured both teams' active rosters"
            ),
            "rosterAcceptedAtConsumerCutoff": age_hours(start - timedelta(minutes=15), limiting) <= 30,
            "forecastOutcome": (
                "INPUTS_PENDING_DEADLINE_MISSED_NO_FORECAST" if not published else
                f"PUBLISHED_AND_IMPORT_CONFIRMED:{game['forecastId']}"
            ),
        })
    return rows


def next_slate_rows(next_inventory: dict) -> list[dict]:
    rows = []
    for snapshot in next_inventory["games"]:
        snapshot = {**snapshot, "capturedAt": next_inventory["capturedAtUtc"]}
        game = snapshot["game"]
        sides = {side["side"]: side["team"]["abbreviation"] for side in snapshot["sides"]}
        readiness = roster_readiness(snapshot)
        rows.append({
            "game": f"{sides['AWAY']}@{sides['HOME']}",
            "mlbamGamePk": game["source_game_id"],
            "canonicalGameId": game["game_id"],
            "scheduledStartUtc": dt(game["starts_at"]).isoformat(),
            "rosterReadiness": readiness,
            "otherCurrentBlockers": snapshot.get("currentParticipantGateReasons", []),
        })
    return rows


def markdown(report: dict) -> str:
    lines = [
        "# CLAUDE_HANDOFF — MLB roster freshness repair",
        "",
        f"Published: {report['createdAtUtc']}",
        "",
        "Classification: producer deployment update and consumer source-owner change request.",
        "",
        "ATL@CHC missed because the September 14 AISP daily source job timed out on the Cubs "
        "team-stat request. Team-stat, roster, and bullpen work shared one team-level try block, "
        "so the Cubs roster endpoint was never called. The last roster remained the September 13 "
        "capture and crossed the 30-hour gate before T-60. Starters and both confirmed lineups were "
        "available before T-15; no forecast was created or published.",
        "",
        "The Model Studio visibility and immutable-forecast metadata repair is committed and built, "
        "but it is not active. Windows denied administrator-required re-registration of the existing "
        "S4U task. The existing 4757da task and manifest remain paired, and the consumer-engaged STOP "
        "sentinel remains in place because the successor has not passed a natural S4U invocation.",
        "",
        "Claude action: change the existing AISP source owner so an unrelated team-stat failure cannot "
        "suppress roster acquisition. The existing availability poll should make a deduplicated, bounded "
        "active-roster refresh for only teams whose roster will exceed 30 hours by T-15: one attempt by "
        "T-60 and at most one retry before T-45. Retain raw bytes and the existing ingestion lineage. "
        "Do not create a scheduler or weaken the freshness gate.",
        "",
        "Administrator action: re-register the same task against the immutable 0a2fb828 deployment, "
        "then allow one natural S4U invocation to succeed before removing the STOP sentinel.",
        "",
        "```powershell",
        ".\\scripts\\install_mlb_v18_unattended.ps1 -Mode Install "
        "-CodeRoot .\\.deployments\\mlb-v18-unattended\\0a2fb8282d68d1a06ac478e5cf3e3442dafe09d8",
        "```",
        "",
        "Read `roster-freshness-repair.json` for all ten September 14 ages, the 15-game next-slate "
        "inventory, source receipts, readiness enum contract, and physical evidence bindings.",
        "",
        "Package identity uses `ASP_FILENAME_TO_SHA256_MAP_CANONICAL_JSON_UTF8_V1`: normalized POSIX "
        "member filenames map to raw-byte SHA-256 values, encoded as canonical UTF-8 JSON with "
        "ensure_ascii=false, allow_nan=false, sorted keys, and compact separators. Member sizes, the "
        "manifest, receipt, and identity field itself are excluded. The old ced67 package reproduces.",
        "",
        "Publication does not establish AISP acknowledgement or activate either requested change.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at-utc", required=True)
    args = parser.parse_args()
    created = dt(args.created_at_utc).isoformat()

    audit = json.loads((PREDECESSOR / "timing-audit.json").read_text(encoding="utf-8"))
    next_inventory = json.loads(NEXT_INVENTORY.read_text(encoding="utf-8"))
    rosters = roster_map(next_inventory)
    sep14 = september_14_rows(audit, rosters)
    atl_snapshot_collection = json.loads(ATL_CHC_SNAPSHOT.read_text(encoding="utf-8"))
    atl_snapshot = next(s for s in atl_snapshot_collection["snapshots"]
                        if s["game"]["source_game_id"] == "824629")

    predecessor_verification = verify_package_directory(PREDECESSOR)
    old_identity_doc = {
        row["path"]: row["sha256"] for row in predecessor_verification["members"]
    }
    algorithm_receipt = {
        "schemaVersion": "ASP_PACKAGE_IDENTITY_ALGORITHM_RECEIPT_V1",
        "createdAtUtc": created,
        "identityAlgorithm": IDENTITY_ALGORITHM,
        "contract": {
            "identityDocument": "mapping of normalized POSIX member filename to lowercase physical SHA-256",
            "includesFilenames": True,
            "includesMemberHashes": True,
            "includesByteCounts": False,
            "includesManifest": False,
            "includesPublicationReceipt": False,
            "excludesOwnIdentityField": True,
            "canonicalJson": {"ensure_ascii": False, "allow_nan": False, "sort_keys": True,
                              "separators": [",", ":"]},
            "encoding": "UTF-8",
            "newlineNormalization": False,
            "pathRules": "relative normalized POSIX; no backslashes, absolute paths, empty, dot, or dot-dot segments",
        },
        "predecessor": {
            "path": str(PREDECESSOR),
            "identityDocument": old_identity_doc,
            "canonicalIdentityBytesUtf8": canonical_identity_bytes(old_identity_doc).decode("utf-8"),
            "claimedAndReproducedPackageContentSha256": predecessor_verification["packageContentSha256"],
            "manifestPhysicalSha256": predecessor_verification["manifestPhysicalSha256"],
            "qualifiedConsumerAcknowledgementPreserved": True,
        },
        "verifier": {
            "command": ".venv\\Scripts\\python.exe scripts\\verify_content_addressed_package.py <package-directory>",
            "source": "server/sports_shared/content_addressed_package.py",
            "checks": ["raw member byte hashes", "member byte counts", "reproduced package identity",
                       "directory leaf address", "normalized paths", "tamper rejection"],
        },
    }

    atl_roster = next(row for row in atl_snapshot["currentRoster"]
                      if row["team_code"] == "CHC" and row["position"] in {"P", "SP", "RP"})
    evidence_time = dt(atl_roster["observed_at"])
    report = {
        "schemaVersion": "ASP_MLB_ROSTER_FRESHNESS_REPAIR_V1",
        "createdAtUtc": created,
        "outcomesAccessed": False,
        "conclusion": {
            "rootCause": "Cubs team-stat ConnectTimeout prevented the sequential Cubs roster request inside AISP daily-pipeline; no later owner refreshed rosters",
            "atlChcAffected": True,
            "otherSeptember14GamesAffected": False,
            "modelStudioRepairActive": False,
            "sourceOwnerRepairActive": False,
            "blockedBy": ["Windows S4U task registration requires administrator access",
                          "consumer-owned AISP source owner still needs the isolated/bounded roster retry"],
        },
        "atlChc": {
            "game": "ATL@CHC", "mlbamGamePk": "824629",
            "canonicalGameId": "c8c53420-99ff-4ec3-ba81-f9019b34aa0d",
            "scheduledStartUtc": "2026-09-14T23:40:00+00:00",
            "consumerDecisionCutoffUtc": "2026-09-14T23:25:00+00:00",
            "producerResearchCutoffUtc": "2026-09-14T23:35:00+00:00",
            "disposition": ["INPUTS_PENDING", "DEADLINE_MISSED"],
            "forecast": None, "decision": None,
            "rosterEvidence": {
                "source": "MLB_STATS_API", "sourceMode": "LIVE", "team": "CHC",
                "mlbamTeamId": "112", "season": 2026,
                "endpoint": "/api/v1/teams/112/roster?rosterType=active&date=2026-09-13&hydrate=person",
                "retainedUpstreamArtifact": str(OLD_CUBS_SOURCE),
                "retainedUpstreamBytes": len(OLD_CUBS_SOURCE.read_bytes()),
                "retainedUpstreamPhysicalSha256": sha(OLD_CUBS_SOURCE),
                "wrapperMetadataChecksum": "e54ec95f6c8ba724f1332b8766951eb44b0f0cf2c1a9a6b7cdbc8933334e1efc",
                "sourcePublicationOrUpdateTime": None,
                "sourcePublicationClockQualification": "provider response supplied no publication/update timestamp",
                "acquiredAtUtc": "2026-09-13T10:01:04.004003+00:00",
                "availabilityTimeUsedByGateUtc": evidence_time.isoformat(),
                "pitcherRows": len([r for r in atl_snapshot["currentRoster"]
                                     if r["team_code"] == "CHC" and r["position"] in {"P", "SP", "RP"}]),
                "thresholdHours": 30,
                "firstStaleAtUtc": (evidence_time + timedelta(hours=30)).isoformat(),
                "agesHours": {"T_minus_60": age_hours(dt("2026-09-14T22:40:00Z"), evidence_time),
                               "T_minus_45": age_hours(dt("2026-09-14T22:55:00Z"), evidence_time),
                               "T_minus_15": age_hours(dt("2026-09-14T23:25:00Z"), evidence_time)},
            },
            "refreshHistory": [
                {"atUtc": "2026-09-13T10:01:04.004003+00:00", "owner": "AISP daily-pipeline",
                 "endpointAttempted": True, "result": "SUCCESS_RETAINED_28_ACTIVE_ROSTER_ROWS"},
                {"startedAtUtc": "2026-09-14T10:00:00.016607+00:00",
                 "completedAtUtc": "2026-09-14T10:01:21.340759+00:00",
                 "owner": "AISP daily-pipeline", "jobId": "07b5f791-9846-4a32-bea9-86b8d63ef35b",
                 "ingestionRunId": "99515dec-5af7-43cf-9200-2953e38aa116",
                 "teamStatsEndpointAttempted": True, "rosterEndpointAttempted": False,
                 "result": "JOB_SUCCEEDED_WITH_WARNING_CHICAGO_CUBS_CONNECT_TIMEOUT"},
            ],
            "modelStudioRosterRechecksUtc": ["2026-09-14T20:42:27Z", "2026-09-14T21:17:24Z",
                "2026-09-14T21:52:27Z", "2026-09-14T22:17:25Z", "2026-09-14T22:37:29Z",
                "2026-09-14T22:57:27Z", "2026-09-14T23:05:53Z", "2026-09-14T23:12:26Z",
                "2026-09-14T23:22:26Z"],
            "modelStudioRecheckSemantics": "read-only database preflight; providerCalls=0; not a roster refresh owner",
            "aispAvailabilityPoll": "ran about every two minutes for schedule/starters/lineups; it does not refresh active rosters",
            "evidenceLayersAtFinalPreflight": {
                "probableStarters": "BOTH_PRESENT; observed 2026-09-14T23:15:36.222787Z",
                "confirmedLineups": "BOTH_CONFIRMED_ORDERED_NINE; observed 2026-09-14T23:17:36.714166Z",
                "activePitchingRosters": "ATL_FRESH; CHC_STALE_BLOCKING",
                "bullpenAvailability": "no separate bullpen observations; anonymous active-roster pool gate blocked",
                "forecastCreation": "NONE", "forecastPublication": "NONE",
            },
        },
        "september14Comparison": sep14,
        "september14Summary": {
            "games": 10, "acceptedRosterEvidence": 9, "rejectedRosterEvidence": 1,
            "publishedAndImported": 9, "missed": 1,
            "largestOtherT15AgeHours": max(row["limitingEvidenceAgeHours"]["T_minus_15_consumer_cutoff"]
                                            for row in sep14 if row["game"] != "ATL@CHC"),
            "interpretation": "ATL@CHC was isolated; the other nine games had more than 14.5 hours of freshness headroom at T-15",
        },
        "nextSlate": {
            "inventoryCapturedAtUtc": dt(next_inventory["capturedAtUtc"]).isoformat(),
            "inventoryPhysical": {"path": str(NEXT_INVENTORY), "bytes": len(NEXT_INVENTORY.read_bytes()),
                                  "sha256": sha(NEXT_INVENTORY)},
            "games": next_slate_rows(next_inventory),
            "summary": "15 games. All lineups were pending at this early capture; TOR@TEX also lacked starter identities. Several rosters would exceed 30 hours by T-15, but the existing 06:00 EDT daily owner is scheduled before every T-45 target. A single-team failure can still recreate the miss until the source-owner retry is changed.",
        },
        "repair": {
            "implementationCommit": "0a2fb8282d68d1a06ac478e5cf3e3442dafe09d8",
            "immutableDeployment": str(ROOT / ".deployments/mlb-v18-unattended/0a2fb8282d68d1a06ac478e5cf3e3442dafe09d8"),
            "behavior": ["seven explicit roster readiness states", "age and projected-cutoff age",
                         "source owner, endpoint, next refresh, last result", "concise blocking message",
                         "forecastCreatedAt copied from the immutable forecast rather than restamped"],
            "gateChanged": False, "modelChanged": False, "forecastArtifactsChanged": False,
            "deploymentAttempt": {"status": "WINDOWS_ACCESS_DENIED", "successorActive": False,
                                  "existingTaskAndManifestPreserved": True},
            "consumerSourceOwnerChangeRequest": {
                "owner": "existing AISP asp-availability-poll/daily-pipeline architecture",
                "change": "isolate roster acquisition from team-stat failure and trigger deduplicated refresh for rosters projected stale by T-15",
                "attemptPolicy": "one attempt by T-60; at most one retry before T-45 per at-risk team/date",
                "maximumProviderCalls": "2 per at-risk team/date; shared across games",
                "estimatedMaximumBytes": "about 110 KB per at-risk team based on the retained 55,313-byte Cubs response",
                "provider": "free MLB Stats API", "incrementalCostUsd": 0,
            },
        },
        "readinessContract": {"states": ["ROSTER_FRESH_NOW", "ROSTER_WILL_EXPIRE_BEFORE_DECISION",
            "ROSTER_REFRESH_SCHEDULED", "ROSTER_REFRESH_ATTEMPTED_NO_NEW_EVIDENCE",
            "ROSTER_SOURCE_FAILED", "ROSTER_MISSING", "ROSTER_STALE_BLOCKING"],
            "fields": ["evidenceTimestamp", "currentAgeHours", "projectedAgeAtConsumerCutoffHours",
                       "thresholdHours", "nextRefreshTimeUtc", "sourceOwner", "lastRefreshResult", "userMessage"]},
        "timingOwner": {
            "taskName": "ASP MLB V18 Research Publisher", "taskCount": 1, "logonType": "S4U",
            "cadenceMinutes": 5, "stateAtCapture": "Ready",
            "capturedAtUtc": "2026-09-15T02:02:40.9663818+00:00",
            "lastRunUtc": "2026-09-15T02:02:02+00:00", "lastTaskResult": 0,
            "installedDeployment": "4757da061139e6196450bd43653ee1ecc850ba58",
            "taskAndManifestMatch": True,
            "firstNaturalS4uInvocation": {"atUtc": "2026-09-15T01:37:37.9267531+00:00",
                "codeValidated": True, "networkAccess": "schedule request succeeded",
                "databaseAccess": "pregame snapshots captured", "result": "FAILED_KEYERROR_forecastCreatedAt"},
            "laterNaturalInvocation": {"atUtc": "2026-09-15T01:47:41.8965438+00:00", "result": "EXIT_0"},
            "killSwitch": {"present": True, "owner": "AISP consumer session",
                           "reason": "4757da natural runs hit forecastCreatedAt KeyError",
                           "latestObservedInvocation": "STOPPED_WITHOUT_PYTHON_AT_2026-09-15T01:52:35.6328695Z"},
            "t60AndT45ContractPresent": True, "olderDeploymentExecuting": False,
        },
        "providerUsageThisAssignment": {"calls": 0, "responseBytes": 0, "costUsd": 0},
        "packageIdentityAlgorithmReceipt": "package-identity-algorithm-receipt.json",
        "verification": {
            "focusedTests": "12 passed",
            "checks": ["exact evidence age", "projected cutoff age", "UTC/EDT conversion",
                       "stale rejection", "unchanged stale evidence not restamped", "refresh scheduling",
                       "owner uniqueness", "natural S4U evidence", "digest reproduction",
                       "cross-platform canonical bytes", "tamper rejection"],
            "predecessorCed67Reproduced": True, "mlbOutcomesRead": False,
        },
        "consumerAcknowledgement": None,
    }

    staging = OUTPUT / "package-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    (staging / "roster-freshness-repair.json").write_bytes(raw_json(report))
    (staging / "package-identity-algorithm-receipt.json").write_bytes(raw_json(algorithm_receipt))
    (staging / "CLAUDE_HANDOFF.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    names = ["CLAUDE_HANDOFF.md", "package-identity-algorithm-receipt.json", "roster-freshness-repair.json"]
    files = member_records(staging, names)
    identity = package_content_sha256({row["path"]: row["sha256"] for row in files})
    manifest = {"schemaVersion": "ASP_MLB_ROSTER_FRESHNESS_REPAIR_PACKAGE_V1",
                "createdAtUtc": created, "identityAlgorithm": IDENTITY_ALGORITHM,
                "packageContentSha256": identity, "predecessorPackageContentSha256":
                predecessor_verification["packageContentSha256"], "files": files}
    (staging / "package-manifest.json").write_bytes(raw_json(manifest))
    destination = OUTPUT / "sha256" / identity
    if destination.exists():
        for path in staging.iterdir():
            retained = destination / path.name
            if not retained.is_file() or retained.read_bytes() != path.read_bytes():
                raise ValueError(f"IMMUTABLE_PACKAGE_CONFLICT: {retained}")
        shutil.rmtree(staging)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(destination))
    verification = verify_package_directory(destination)
    print(json.dumps({"path": str(destination), "verification": verification}, indent=2))


if __name__ == "__main__":
    main()
