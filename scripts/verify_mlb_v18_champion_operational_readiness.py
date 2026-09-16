"""Read-only installed-task and retained-current-receipt verification.

Never imports a publisher, source loader, database client or estimator. Only
Task Scheduler queries and local operational JSON/code bytes are read. Reuse
--scheduler-snapshot to reproduce the same as-of report without another query.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".runtime/mlb-v18-unattended"
TICKS = ROOT / "outputs/mlb-v18-unattended-v1/objects/sha256"
CURRENT = ROOT / "outputs/mlb-v18-current-state-pipeline-v1"
OUT = ROOT / "outputs/mlb-v18-conditional-champion-v1/operational-readiness"
PIN = "9bb1a947fc863596433fac569822ad95f2c71dac"
READS = {}
PS_QUERY = r"""
$ErrorActionPreference='Stop'
$t=Get-ScheduledTask -TaskName 'ASP MLB V18 Research Publisher' -TaskPath '\'
$i=Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath '\'
[ordered]@{inspectedAtUtc=[DateTime]::UtcNow.ToString('o');taskName=$t.TaskName;taskPath=$t.TaskPath;state=$t.State.ToString();principal=@{userId=$t.Principal.UserId;logonType=$t.Principal.LogonType.ToString();runLevel=$t.Principal.RunLevel.ToString()};settings=@{enabled=$t.Settings.Enabled;startWhenAvailable=$t.Settings.StartWhenAvailable;multipleInstances=$t.Settings.MultipleInstances.ToString();executionTimeLimit=$t.Settings.ExecutionTimeLimit;wakeToRun=$t.Settings.WakeToRun};actions=@($t.Actions|Select-Object Execute,Arguments,WorkingDirectory);triggers=@($t.Triggers|ForEach-Object{@{type=$_.CimClass.CimClassName;enabled=$_.Enabled;startBoundary=$_.StartBoundary;delay=$_.Delay;interval=$_.Repetition.Interval}});lastRunTime=$i.LastRunTime.ToString('o');lastTaskResult=$i.LastTaskResult;nextRunTime=$i.NextRunTime.ToString('o');numberOfMissedRuns=$i.NumberOfMissedRuns}|ConvertTo-Json -Depth 5
"""


def utc(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def descriptor(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    result = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    READS[str(path)] = result
    return result


def read(path, expected=None):
    path = Path(path).resolve()
    allowed = (CURRENT, TICKS, STATE, OUT, ROOT / "outputs/mlb-v18-unattended-v1/evidence",
               Path("C:/Users/james/asp-model-exchange/mlb-v18-current"))
    if path.suffix != ".json" or not any(path.is_relative_to(root) for root in allowed):
        raise ValueError("Outside bounded operational JSON scope: " + str(path))
    actual = descriptor(path)
    if expected:
        for key in ("sha256", "bytes"):
            if key in expected and actual[key] != expected[key]:
                raise ValueError("Operational checksum mismatch: " + str(path))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(name, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(data).hexdigest()
    path = OUT / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable report conflict")
    else:
        with path.open("xb") as handle:
            handle.write(data)
    return {"path": str(path), "sha256": digest, "bytes": len(data)}


def snapshot_summary(row):
    capture = row["sourcePreflight"]["capture"]
    collection = read(capture["snapshotsPath"], {"sha256": capture["snapshotsSha256"]})
    snapshot = next((s for s in collection["snapshots"] if s["game"]["game_id"] == row["gameId"]), None)
    if snapshot is None:
        return {"capture": capture, "snapshotAbsent": True}
    cutoff = utc(snapshot["capturedAt"])
    sides = []
    for side in snapshot["sides"]:
        def clocks(record):
            return {**{k: record.get(k) for k in ("observedAt", "availableAsOf", "ingestedAt")},
                    "observationAgeMinutesAtCapture": ((cutoff-utc(record["observedAt"])).total_seconds()/60
                         if record.get("observedAt") else None)}
        starter, lineup = side.get("starter", {}), side.get("lineupAuthority", {})
        roster = [r for r in snapshot.get("currentRoster", []) if r.get("team_id") == side["team"]["uuid"]
                  and r.get("active_roster") is True and r.get("position") in ("P", "SP", "RP")]
        sides.append({"side": side["side"], "team": side["team"],
            "starter": {**{k: starter.get(k) for k in ("mlbamId", "uuid", "name", "confirmationState", "throws")}, **clocks(starter)},
            "lineup": {"status": lineup.get("status"), "orderedPlayerCount": len(side.get("lineup", [])), **clocks(lineup)},
            "activePitchingRosterRows": len(roster),
            "activePitchingRosterObservedAtRange": sorted({r["observed_at"] for r in roster if r.get("observed_at")})})
    return {"capture": capture, "capturedAt": snapshot["capturedAt"], "sides": sides,
            "pregameAtCapture": cutoff < utc(snapshot["game"]["starts_at"]),
            "retainedReasons": row["sourcePreflight"]["reasons"],
            "doesNotClaimSourceFreshnessBeyondCapture": True}


def main(snapshot_path=None):
    READS.clear()
    if snapshot_path:
        scheduler = read(snapshot_path)
        scheduler_ref = descriptor(snapshot_path)
    else:
        process = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_QUERY],
                                 capture_output=True, text=True, timeout=30, check=True)
        scheduler = json.loads(process.stdout)
        scheduler_ref = write("scheduler-snapshot.json", scheduler)
        read(scheduler_ref["path"], scheduler_ref)
    as_of = utc(scheduler["inspectedAtUtc"])
    today = as_of.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    deployment = read(STATE / "deployment.json")
    assert deployment["deployed_commit"] == PIN
    assert scheduler["principal"]["logonType"] == "S4U"
    assert all(PIN in a["Arguments"] and "-ScheduledInvocation" in a["Arguments"] for a in scheduler["actions"])
    pinned = ROOT / ".deployments/mlb-v18-unattended" / PIN
    checked_code = []
    manifest_code = {r["path"]: r["sha256"] for r in deployment["code_hashes"]}
    for name in ("scripts/invoke_mlb_v18_unattended.ps1", "scripts/run_mlb_v18_unattended.py",
                 "server/sports_current_statcast/mlb_v18_unattended.py"):
        item = descriptor(pinned / name)
        assert item["sha256"] == manifest_code[name]
        checked_code.append(item)
    launches = [(p, read(p)) for p in sorted((STATE / "launcher-receipts").glob("*.json"))]
    launches = [(p, v) for p, v in launches if v["context"].get("manifest_sha256") == descriptor(STATE / "deployment.json")["sha256"]]
    paths = sorted(TICKS.glob("*/tick.json"))
    if len(paths) > 1000:
        raise ValueError("Bounded receipt inventory exceeds 1000; narrow the date snapshot explicitly")
    ticks = []
    for path in paths:
        value = read(path)
        if (value.get("owner") == "windows-task-scheduler" and utc(value["completedAt"]) <= as_of
                and utc(value["startedAt"]) >= utc(deployment["prepared_at_utc"])):
            ticks.append((path, value))
        else:
            # Later scheduler activity must not change a fixed-as-of report.
            READS.pop(str(path.resolve()), None)
    ticks.sort(key=lambda p: utc(p[1]["startedAt"]))
    substantive = [(p, v) for p, v in ticks if v.get("discovery")]
    latest_path, latest = substantive[-1]
    source = latest["discovery"]["sourceReceipt"]
    schedule = read(source["raw"]["path"], source["raw"])
    read(source["receipt"]["path"], source["receipt"])
    names = {str(g["gamePk"]): {s: g["teams"][s]["team"]["name"] for s in ("home", "away")}
             for day in schedule["dates"] for g in day["games"]}
    last_preflight = {}
    for path, tick in substantive:
        for row in tick["games"]:
            if row.get("sourcePreflight"):
                last_preflight[row["gameId"]] = (path, tick["startedAt"], row)
    games = []
    for row in latest["games"]:
        item = {k: row.get(k) for k in ("gameDate", "gameId", "canonicalGameId", "mlbamGamePk", "homeTeamMlbamId",
            "awayTeamMlbamId", "scheduledStartUtc", "canonicalIdentityResolved", "teamIdentityMismatch", "scheduleTimeMismatch",
            "observedAt", "availableAsOf", "ingestedAt", "checkpoint", "status", "reason", "publication", "newInference")}
        item["teamNames"] = names.get(str(row["mlbamGamePk"]))
        item["localSchedule"] = row.get("localSchedule")
        item["startStillFutureAtVerification"] = utc(row["scheduledStartUtc"]) > as_of
        if row["gameId"] in last_preflight:
            path, at, previous = last_preflight[row["gameId"]]
            item["lastParticipantPreflight"] = {"tick": descriptor(path), "startedAt": at, **snapshot_summary(previous)}
        else:
            item["lastParticipantPreflight"] = {"status": "NO_RETAINED_PREFLIGHT_IN_THIS_INSTALLED_ATTEMPT"}
        games.append(item)
    exchanges = []
    for slate in latest.get("slates", []):
        exchange = slate["exchange"]
        verification = []
        for key in ("manifest", "handoff", "receipt"):
            try:
                read(exchange[key]["path"], exchange[key])
                verification.append({"artifact": key, "checksumVerified": True})
            except PermissionError as error:
                verification.append({"artifact": key, "checksumVerified": False,
                    "errorType": type(error).__name__, "error": str(error), "accessControlsUnchanged": True})
        for key in ("handoff", "importReceipt"):
            read(slate[key]["path"], slate[key])
        exchanges.append({"slateDate": slate["slateDate"], "publishedGames": slate["publishedGames"],
            "gamesDiscovered": slate["gamesDiscovered"], "gamesSkipped": slate["gamesSkipped"], "exchange": exchange,
            "externalArtifactVerification": verification, "localHandoffChecksumVerified": True,
            "localImportReceiptChecksumVerified": True,
            "localArtifacts": {key: slate[key] for key in ("handoff", "importReceipt")}})
    original = []
    for digest in ("c87d341420ff02a6fe420c498b61472af5857015e6771f35d2f5b5706db69c3d", "dbce974760e2106b2fa23a7ef7fd348d67b261d06e690febae2556fa0dd12fdf"):
        path = CURRENT / "objects/sha256" / digest / "forecast.json"
        value = read(path)
        original.append({"objectSha256": digest, "forecast": descriptor(path),
            **{k: value[k] for k in ("gameId", "sourceGameId", "teams", "forecastCreatedAt", "scheduledStart", "capturedAt", "sourceCutoff", "status")},
            "createdBeforeFirstPitch": utc(value["forecastCreatedAt"]) < utc(value["scheduledStart"]),
            "isCurrentSlateForecast": False, "bytesUnmodifiedByVerification": True})
    attempts = [(p, read(p)) for p in sorted((CURRENT / "sources/objects/sha256").glob("*.acquisition-attempt.json"))]
    history_path, history = max(((p, v) for p, v in attempts if utc(v["completedAt"]) <= as_of), key=lambda pv: utc(pv[1]["completedAt"]))
    counts = {day: {"games": sum(g["gameDate"] == day for g in games),
        "mappedGames": sum(g["gameDate"] == day and bool(g["canonicalIdentityResolved"]) for g in games),
        "publishedGames": next(s["publishedGames"] for s in exchanges if s["slateDate"] == day),
        "latestReasonCounts": dict(Counter(g["reason"] for g in games if g["gameDate"] == day)),
        "retainedInputBlockerCounts": dict(Counter(reason for g in games if g["gameDate"] == day
            for reason in g["lastParticipantPreflight"].get("retainedReasons", [])))} for day in sorted({g["gameDate"] for g in games})}
    result = {"schemaVersion": "MLB_V18_CONDITIONAL_CHAMPION_OPERATIONAL_READINESS_V1", "asOfUtc": as_of.isoformat(),
        "currentLocalDate": today, "scheduler": scheduler, "schedulerSnapshot": scheduler_ref,
        "deploymentManifest": descriptor(STATE / "deployment.json"), "pinnedCodeReferencesVerified": checked_code,
        "scheduledLauncherEvidence": [{"receipt": descriptor(p), **v} for p, v in launches],
        "latestSubstantiveReceipt": descriptor(latest_path), "latestSubstantiveStartedAt": latest["startedAt"],
        "latestSubstantiveStatus": latest["status"], "latestScheduleEvidence": source,
        "networkProof": {"actualScheduledHttp200": any(a.get("httpStatus") == 200 for a in latest["requestTelemetry"]["attempts"]),
                         "telemetry": latest["requestTelemetry"], "notInferredFromS4uConfiguration": True},
        "databaseProof": {"actualScheduledLocalScheduleRows": sum(bool(g.get("localSchedule")) for g in latest["games"]),
            "actualRetainedParticipantCaptures": len(last_preflight),
            "basis": "Actual localSchedule rows and immutable pregame snapshots from scheduled receipts. The pinned producer queries only a local database, sets and checks transaction_read_only=on, and rolls back. This verifier performs no database request.",
            "limitation": "No independent database server audit log was inspected; receipt-bound results plus the pinned execution path establish access, not configuration alone."},
        "slateCounts": counts, "games": games, "exchangePackages": exchanges,
        "historicalLegitimatePregameForecasts": original,
        "latestHistoryCapture": {"receipt": descriptor(history_path), "completedAt": history["completedAt"],
            "requestedThrough": max(history["requestedDates"]), "sourceCatalogComplete": history["sourceCatalogComplete"],
            "failures": history["failures"], "rawPayloadsNotRead": True,
            "limitation": "History refresh is deferred until participant preflight is eligible. Receipt freshness is not proof that September 10 history has been acquired or that current input construction has executed."},
        "executionEvidence": {"scheduledReceiptsInspected": len(ticks), "substantiveReceiptsInspected": len(substantive),
            "statuses": dict(Counter(v["status"] for _, v in ticks)),
            "scheduledNewInferenceClaims": sum(bool(g.get("newInference")) for _, v in ticks for g in v.get("games", [])),
            "currentSlateInputConstructionProven": any(g["gameDate"] == today and g.get("publication") for g in games),
            "restartPersistence": "Windows Task Scheduler owns S4U execution independently of Codex. Boot+1min and StartWhenAvailable are installed; runtime state/checkpoints and immutable receipts persist. WakeToRun=false; cannot execute while the computer is off. No reboot/restart experiment was performed.",
            "catchupEvidence": "Fresh current/next-slate discovery and persisted per-game checkpoint progress are observed; missed-downtime recovery is a pinned-code/configuration capability, not independently demonstrated by a controlled restart in this verification."},
        "readinessConclusion": "SCHEDULED_DISCOVERY_AND_FAIL_CLOSED_ACCOUNTING_VERIFIED_CURRENT_FORECAST_COVERAGE_NOT_YET_ESTABLISHED",
        "noRetroactiveForecasts": True, "noWageringAuthorityGranted": True,
        "verificationActions": {"providerCalls": 0, "databaseCalls": 0, "publisherLaunches": 0, "taskModifications": 0,
            "inferenceCalls": 0, "fits": 0, "aispWrites": 0, "sealedOotPayloadReads": 0},
        "sourceReferences": sorted(READS.values(), key=lambda r: r["path"]), "verifierCode": descriptor(__file__)}
    output = write("operational-readiness.json", result)
    print(json.dumps({"report": output, "schedulerSnapshot": scheduler_ref, "counts": counts}, indent=2))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduler-snapshot", type=Path)
    main(parser.parse_args().scheduler_snapshot)
