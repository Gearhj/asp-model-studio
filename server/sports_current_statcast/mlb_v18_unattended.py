"""One bounded event-aware V18 tick; scheduled by Windows, never by Codex.

Schedule discovery is public metadata only. Pregame evidence comes from the
existing local AISP source observations via read-only capture. Frozen V18 owns
all inference. This module never writes AISP or reads an evaluation partition.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from .mlb_v18_current_slate import reference, write_object, utc
from .mlb_v18_current_publication import OUTPUT as PUBLICATIONS, current_handoff, current_import_receipt
from .mlb_v18_daily_slate import collect_slate_forecasts, json_safe, RESEARCH_FLAGS

CODE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = Path(os.environ.get("ASP_V18_REPOSITORY_ROOT", CODE_ROOT))
STATE_ROOT = REPOSITORY / ".runtime/mlb-v18-unattended"
OUTPUT = REPOSITORY / "outputs/mlb-v18-unattended-v1"
EASTERN = ZoneInfo("America/New_York")

# AISP's decision clock is independent from the producer's T-5 research
# publication safety cutoff.  The consumer evaluates FINAL_PREGAME from T-30
# through T-15 on five-minute import and freeze cadences.  The producer starts
# its fast checks at T-60 so newly eligible lineups are acted on promptly and
# records every one of these clocks in its tick evidence.
AISP_FINAL_PREGAME_WINDOW_OPENS_MINUTES = 30
AISP_DECISION_CUTOFF_MINUTES = 15
AISP_IMPORT_CADENCE_MINUTES = 5
AISP_EVALUATION_CADENCE_MINUTES = 5
PRODUCER_RESEARCH_CUTOFF_MINUTES = 5
PRODUCER_FAST_CHECK_WINDOW_MINUTES = 60
# T-45 leaves the observed roughly fifteen-minute multi-game producer runtime,
# one import tick, one evaluation tick, and one owner-tick reserve before T-15.
CONSUMER_READY_TARGET_MINUTES = 45
ACTIVE_PITCHING_ROSTER_MAX_AGE_HOURS = 30
# Windows' five-minute trigger can arrive fractionally before a next-tick time
# recorded from the previous run.  Without a small allowance, a sub-second
# difference suppresses that invocation and stretches the effective cadence to
# ten minutes.  This is dispatcher tolerance only; game/checkpoint cutoffs stay
# exact.
DISPATCH_EARLY_TOLERANCE_SECONDS = 2


def encode(value):
    return json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def atomic_state(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(encode(value))
    os.replace(temporary, path)


@contextmanager
def single_owner(path):
    """OS-held byte lock releases on exit/crash; no stale PID ownership guessing."""
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def checkpoint(game, previous, now):
    """Frozen scheduling policy, not a model or betting-policy change."""
    start = utc(game["scheduledStartUtc"])
    minutes = (start - now).total_seconds() / 60
    status = str(game.get("status", "")).lower()
    clocks = {
        "consumerDecisionCutoffUtc": (
            start - timedelta(minutes=AISP_DECISION_CUTOFF_MINUTES)
        ).isoformat(),
        "consumerFinalPregameWindowOpensUtc": (
            start - timedelta(minutes=AISP_FINAL_PREGAME_WINDOW_OPENS_MINUTES)
        ).isoformat(),
        "consumerReadyTargetUtc": (
            start - timedelta(minutes=CONSUMER_READY_TARGET_MINUTES)
        ).isoformat(),
        "producerResearchPublicationCutoffUtc": (
            start - timedelta(minutes=PRODUCER_RESEARCH_CUTOFF_MINUTES)
        ).isoformat(),
    }
    if minutes <= 0 or status == "live" or any(word in status for word in ("in progress", "final", "completed", "game over")):
        return {"due": False, "reason": "ALREADY_STARTED_OR_CLOSED", "closed": True, **clocks}
    if any(word in status for word in ("postpon", "cancel", "suspend")):
        return {"due": False, "reason": "POSTPONED_CANCELED_OR_SUSPENDED", "closed": True, **clocks}
    if minutes <= PRODUCER_RESEARCH_CUTOFF_MINUTES:
        return {"due": False, "reason": "FINAL_PUBLICATION_SAFETY_CUTOFF_T_MINUS_5", "closed": False,
                "consumerDecisionEligible": False, **clocks}
    if minutes > 24 * 60:
        return {"due": False, "reason": "FUTURE_GAME_BEYOND_24H_CAPTURE_WINDOW", "closed": False, **clocks}
    cooldown = previous.get("retryAfterUtc")
    if cooldown:
        if now < utc(cooldown):
            return {"due": False, "reason": "BOUNDED_FAILURE_COOLDOWN", "closed": False,
                    "consumerDecisionEligible": minutes > AISP_DECISION_CUTOFF_MINUTES, **clocks}
        return {"due": True, "reason": "BOUNDED_FAILURE_RETRY_DUE", "closed": False,
                "intervalMinutes": retry_delay_minutes(game, int(previous.get("consecutiveFailures") or 1), now),
                "consumerDecisionEligible": minutes > AISP_DECISION_CUTOFF_MINUTES, **clocks}
    # Morning/long-lead capture once, then increasingly frequent checks.  T-60
    # through first pitch uses the five-minute owner cadence; the former
    # 15-minute interval could first notice eligible evidence too late for a
    # T-15 consumer decision even while remaining valid for T-5 research use.
    interval = (360 if minutes > 360 else 60 if minutes > 180 else
                30 if minutes > 90 else 15 if minutes > PRODUCER_FAST_CHECK_WINDOW_MINUTES else 5)
    latest = previous.get("checkedAt")
    due = latest is None or now >= utc(latest) + timedelta(minutes=interval)
    return {"due": due, "reason": "PREGAME_SOURCE_CHECKPOINT" if due else "CHECKPOINT_NOT_DUE",
            "closed": False, "intervalMinutes": interval,
            "consumerDecisionEligible": minutes > AISP_DECISION_CUTOFF_MINUTES, **clocks}


def retry_delay_minutes(game, failures, now):
    """Retry quickly while a consumer-eligible publication is still possible."""
    start = utc(game["scheduledStartUtc"])
    consumer_cutoff = start - timedelta(minutes=AISP_DECISION_CUTOFF_MINUTES)
    if now < consumer_cutoff:
        return 5
    return 60 if failures >= 2 else 15


def local_game_map(start, through):
    """Schedule/identity only; no outcomes, market data or AISP mutation."""
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    uri = make_url(dotenv_values(Path("C:/Users/james/ai-sports-predictor/.env"))["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql+psycopg2://"))
    if uri.host not in {"localhost", "127.0.0.1"}:
        raise ValueError("Only local read-only AISP identity reconciliation is authorized")
    engine = create_engine(uri)
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if conn.execute(text("SHOW transaction_read_only")).scalar() != "on":
                raise ValueError("AISP read-only transaction was not confirmed")
            rows = list(conn.execute(text("""select g.id::text game_id, em.external_id source_game_id,
                g.starts_at,g.status,
                (select emt.external_id from game_teams gt join external_id_mappings emt
                 on emt.entity_id=gt.team_id and emt.entity_type='team' and emt.source='MLB_STATS_API'
                 where gt.game_id=g.id and gt.is_home=true) home_mlbam_id,
                (select emt.external_id from game_teams gt join external_id_mappings emt
                 on emt.entity_id=gt.team_id and emt.entity_type='team' and emt.source='MLB_STATS_API'
                 where gt.game_id=g.id and gt.is_home=false) away_mlbam_id
                from games g join leagues l on l.id=g.league_id
                join external_id_mappings em on em.entity_id=g.id and em.entity_type='game'
                and em.source='MLB_STATS_API' where l.code='MLB' and g.starts_at>=:start
                and g.starts_at<:through order by g.starts_at,g.id"""), {"start": start, "through": through}).mappings())
            tx.rollback()
    finally:
        engine.dispose()
    mapped = {}
    for row in rows:
        source_id = str(row["source_game_id"])
        if source_id in mapped and mapped[source_id]["game_id"] != row["game_id"]:
            raise ValueError("AMBIGUOUS_CANONICAL_GAME_IDENTITY")
        mapped[source_id] = dict(row)
    return mapped


def discover(now, *, allow_free_network, root=OUTPUT, request_telemetry=None):
    from .mlb_v18_current_sources import acquire_schedule_identity_projection, schedule_identity_rows
    today = now.astimezone(EASTERN).date()
    through = today + timedelta(days=7)
    receipt = acquire_schedule_identity_projection(start=today.isoformat(), through=through.isoformat(),
        allow_free_network=allow_free_network, output_root=PUBLICATIONS / "sources", request_telemetry=request_telemetry)
    if not allow_free_network:
        return {"plan": receipt, "games": []}
    source_rows = schedule_identity_rows(receipt)
    start_clock = datetime.combine(today, datetime.min.time(), EASTERN)
    mapping = local_game_map(start_clock, start_clock + timedelta(days=8))
    dates = sorted({row["gameDate"] for row in source_rows if row["gameDate"] >= today.isoformat()})
    selected_dates = ([today.isoformat()] + [day for day in dates if day > today.isoformat()][:1])
    games = []
    for row in source_rows:
        if row["gameDate"] not in selected_dates:
            continue
        match = mapping.get(str(row["mlbamGamePk"]))
        games.append({**row, "gameId": match["game_id"] if match else f"UNMAPPED_MLBAM:{row['mlbamGamePk']}",
                      "canonicalIdentityResolved": bool(match), "localSchedule": json_safe(match),
                      "scheduleTimeMismatch": bool(match and utc(match["starts_at"]) != utc(row["scheduledStartUtc"])),
                      "teamIdentityMismatch": bool(match and any(str(match.get(local)) != str(row.get(source))
                          for local, source in (("home_mlbam_id", "homeTeamMlbamId"), ("away_mlbam_id", "awayTeamMlbamId"))))})
    # A local event omitted by this provider response is not silently discarded.
    provider_ids = {str(row["mlbamGamePk"]) for row in source_rows}
    for key, row in mapping.items():
        day = row["starts_at"].astimezone(EASTERN).date().isoformat()
        if key not in provider_ids and day in selected_dates:
            games.append({"gameId": row["game_id"], "mlbamGamePk": int(key), "gameDate": day,
                          "scheduledStartUtc": row["starts_at"].isoformat(), "status": row["status"],
                          "canonicalIdentityResolved": True, "providerScheduleMissing": True})
    return {"games": games, "slateDates": selected_dates, "sourceReceipt": receipt,
            "providerCalls": 1, "costUsd": 0}


def latest_attempt():
    paths = list((PUBLICATIONS / "sources/objects/sha256").glob("*.acquisition-attempt.json"))
    if not paths:
        return None, None
    items = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]
    return max(items, key=lambda item: item[1]["completedAt"])


def refresh_history(now, state, *, allow_free_network, logs):
    path, body = latest_attempt()
    yesterday = (now.astimezone(EASTERN).date() - timedelta(days=1)).isoformat()
    # Reuse the existing same-day successful capture. First-day setup is not a
    # reason to repeat all completed source requests or advance their clocks.
    if body and body.get("sourceCatalogComplete") and not body.get("failures") and body.get("requestedDates", [None])[-1] == yesterday and utc(body["completedAt"]).astimezone(EASTERN).date() == now.astimezone(EASTERN).date():
        return path, {"status": "UNCHANGED_COMPLETE_HISTORY_REUSED", "providerCalls": 0}
    if not allow_free_network:
        raise ValueError("FREE_HISTORY_REFRESH_NOT_AUTHORIZED")
    command = [sys.executable, str(CODE_ROOT / "scripts/acquire_mlb_v18_current_sources.py"),
        "--start", "2026-08-14", "--current-pregame-source-exception", "--allow-free-network",
        "--correction-days", "3", "--reuse-schedule-projection"]
    completed = subprocess.run(command, cwd=CODE_ROOT, capture_output=True, text=True, timeout=1200)
    logs.append({"stage": "historyRefresh", "returnCode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
    path, body = latest_attempt()
    if body:
        logs.append({"stage": "historyRequestAccounting", "sourceAttempt": reference(path),
                     "requestTelemetry": body.get("requestTelemetry"),
                     "historicalReceiptHasExactTelemetry": "requestTelemetry" in body})
    if completed.returncode or not body or not body.get("sourceCatalogComplete") or body.get("failures"):
        raise ValueError("CURRENT_HISTORY_REFRESH_INCOMPLETE_SEE_PERSISTED_STAGE_LOG")
    return path, {"status": "BOUNDED_HISTORY_REFRESH_COMPLETED", "requestTelemetry": body.get("requestTelemetry"),
                  "sourceAttempt": reference(path)}


def _next_daily_roster_refresh(after):
    local = utc(after).astimezone(EASTERN)
    candidate = local.replace(hour=6, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def roster_readiness(snapshot):
    """Explain roster age and its owner without changing the frozen V18 gate."""
    captured = utc(snapshot["capturedAt"])
    start = utc(snapshot["game"]["starts_at"])
    decision_cutoff = start - timedelta(minutes=AISP_DECISION_CUTOFF_MINUTES)
    ready_target = start - timedelta(minutes=CONSUMER_READY_TARGET_MINUTES)
    threshold = timedelta(hours=ACTIVE_PITCHING_ROSTER_MAX_AGE_HOURS)
    owner = snapshot.get("rosterRefreshOwner") or {}
    runs = owner.get("latestIngestionRuns") or []
    last_run = runs[0] if runs else None
    owner_runs = owner.get("latestOwnerRuns") or []
    last_owner_run = owner_runs[0] if owner_runs else None
    attempted_teams = set(owner.get("latestOwnerTargetTeams") or [])
    next_refresh = _next_daily_roster_refresh(captured)
    results = []
    for side in snapshot["sides"]:
        team = side["team"]
        roster = [r for r in snapshot.get("currentRoster", [])
                  if r.get("team_id") == team["uuid"] and r.get("active_roster") is True
                  and r.get("position") in {"P", "SP", "RP"}]
        evidence_times = [utc(r["observed_at"]) for r in roster if r.get("observed_at")]
        evidence = min(evidence_times) if len(evidence_times) == len(roster) and roster else None
        if evidence is None:
            current_state = "ROSTER_MISSING"
        elif captured - evidence > threshold:
            current_state = "ROSTER_STALE_BLOCKING"
        elif decision_cutoff - evidence > threshold:
            current_state = "ROSTER_WILL_EXPIRE_BEFORE_DECISION"
        else:
            current_state = "ROSTER_FRESH_NOW"
        states = [current_state]

        last_result = None
        if last_run:
            warnings = [str(item) for item in (last_run.get("warnings") or [])]
            team_warnings = [item for item in warnings
                             if team.get("name") and item.startswith(team["name"] + ":")]
            completed = utc(last_run["completed_at"]) if last_run.get("completed_at") else None
            owner_started = (utc(last_owner_run["started_at"])
                             if last_owner_run and last_owner_run.get("started_at") else None)
            owner_completed = (utc(last_owner_run["completed_at"])
                               if last_owner_run and last_owner_run.get("completed_at") else completed)
            if team_warnings:
                states.insert(0, "ROSTER_SOURCE_FAILED")
                last_result = {"status": "ROSTER_SOURCE_FAILED",
                               "completedAt": completed.isoformat() if completed else None,
                               "detail": team_warnings[0], "runId": last_run.get("id")}
            elif (team.get("abbreviation") in attempted_teams and owner_completed
                  and (evidence is None or owner_completed > evidence) and not (
                      evidence and owner_started and owner_started <= evidence <= owner_completed)):
                states.insert(0, "ROSTER_REFRESH_ATTEMPTED_NO_NEW_EVIDENCE")
                last_result = {"status": "ROSTER_REFRESH_ATTEMPTED_NO_NEW_EVIDENCE",
                               "completedAt": owner_completed.isoformat(),
                               "runId": last_owner_run.get("id") if last_owner_run else last_run.get("id")}
            else:
                last_result = {"status": "COMPLETED",
                               "completedAt": completed.isoformat() if completed else None,
                               "runId": last_run.get("id")}
        if next_refresh <= ready_target:
            states.append("ROSTER_REFRESH_SCHEDULED")
        user_message = None
        if current_state != "ROSTER_FRESH_NOW":
            age = (f"Last verified {(captured-evidence).total_seconds()/3600:.1f} hours ago; "
                   if evidence else "No verified roster is available; ")
            user_message = ("Forecast waiting for current pitching-roster evidence. " + age
                            + f"required maximum is {ACTIVE_PITCHING_ROSTER_MAX_AGE_HOURS} hours.")
        results.append({
            "side": side["side"], "teamId": team["uuid"], "team": team.get("abbreviation"),
            "states": states, "evidenceTimestamp": evidence.isoformat() if evidence else None,
            "currentAgeHours": (captured-evidence).total_seconds()/3600 if evidence else None,
            "projectedAgeAtConsumerCutoffHours": (
                decision_cutoff-evidence).total_seconds()/3600 if evidence else None,
            "thresholdHours": ACTIVE_PITCHING_ROSTER_MAX_AGE_HOURS,
            "consumerDecisionCutoffUtc": decision_cutoff.isoformat(),
            "consumerReadyTargetUtc": ready_target.isoformat(),
            "nextRefreshTimeUtc": next_refresh.isoformat(),
            "refreshNeededByUtc": (
                start-timedelta(minutes=PRODUCER_FAST_CHECK_WINDOW_MINUTES)).isoformat(),
            "source": owner.get("provider", "MLB_STATS_API"),
            "sourceEndpoint": owner.get("endpoint", "/api/v1/teams/{mlbamTeamId}/roster"),
            "sourceOwner": owner.get("owner", "AISP_ASP_DAILY_PIPELINE"),
            "lastRefreshResult": last_result, "userMessage": user_message,
        })
    return results


def participant_readiness(snapshot):
    """Source-age gates, not changes to V18 treatment or AISP readiness scoring.

    AISP persists a new observation even for unchanged successful lineup polls.
    Within four hours it polls every two minutes and verifies starters within ten;
    thirty minutes therefore permits transient delays without calling old rows fresh.
    Daily 06:00 active-roster capture has a six-hour grace (30-hour maximum age).
    """
    cutoff = utc(snapshot["capturedAt"])
    start = utc(snapshot["game"]["starts_at"])
    max_age = timedelta(minutes=30) if start-cutoff <= timedelta(hours=4) else timedelta(hours=24)
    reasons = []
    if cutoff + timedelta(minutes=5) >= start:
        reasons.append("FINAL_PUBLICATION_SAFETY_CUTOFF_T_MINUS_5")
    for side in snapshot["sides"]:
        label = side["side"]
        starter, lineup = side.get("starter", {}), side.get("lineupAuthority", {})
        if not starter.get("mlbamId"):
            reasons.append(label + "_STARTER_IDENTITY_UNAVAILABLE")
        entries = side.get("lineup", [])
        if lineup.get("status") != "CONFIRMED" or len(entries) != 9 or [int(p.get("batting_order", 0)) for p in entries] != list(range(1, 10)):
            reasons.append(label + "_CONFIRMED_ORDERED_NINE_PLAYER_LINEUP_UNAVAILABLE")
        for name, evidence in (("STARTER", starter), ("LINEUP", lineup)):
            clocks = [evidence.get(key) for key in ("observedAt", "availableAsOf", "ingestedAt")]
            if any(clock is None for clock in clocks):
                reasons.append(label + "_" + name + "_SOURCE_CLOCK_UNAVAILABLE")
            elif max(utc(clock) for clock in clocks) > cutoff:
                reasons.append(label + "_" + name + "_SOURCE_CLOCK_AFTER_CAPTURE")
            elif cutoff - utc(evidence["observedAt"]) > max_age:
                reasons.append(label + "_" + name + "_SOURCE_OBSERVATION_STALE")
        roster = [r for r in snapshot.get("currentRoster", []) if r.get("team_id") == side["team"]["uuid"]
                  and r.get("active_roster") is True and r.get("position") in {"P", "SP", "RP"}]
        if not roster or any(not r.get("observed_at") or cutoff-utc(r["observed_at"]) >
                             timedelta(hours=ACTIVE_PITCHING_ROSTER_MAX_AGE_HOURS) for r in roster):
            reasons.append(label + "_ACTIVE_PITCHING_ROSTER_ABSENT_OR_OLDER_THAN_30H")
    return reasons


def preflight_participants(due, report, state, now, *, request_telemetry=None):
    """Cheap live source capture defers expensive history/model work until ready."""
    from scripts.inventory_mlb_current_slate import capture_current_slate
    eligible = {}
    missing_identities = set()
    for day, ids in due.items():
        _, descriptor = capture_current_slate(output_root=PUBLICATIONS / "inventory", slate_date=day, game_ids=ids)
        collection = json.loads(Path(descriptor["snapshotsPath"]).read_text(encoding="utf-8"))
        snapshots = {s["game"]["game_id"]: s for s in collection["snapshots"]}
        for row in report["games"]:
            if row["gameId"] not in ids:
                continue
            snapshot = snapshots.get(row["gameId"])
            roster_status = roster_readiness(snapshot) if snapshot else []
            reasons = participant_readiness(snapshot) if snapshot else ["CLOSED_OR_DISAPPEARED_BEFORE_LIVE_CAPTURE"]
            row["rosterReadiness"] = roster_status
            row["sourcePreflight"] = {"capture": descriptor, "reasons": reasons,
                                      "rosterReadiness": roster_status}
            if reasons:
                row.update(status="SKIPPED", reason=reasons[0], blockers=[{"reason": r} for r in reasons])
                state["games"][row["gameId"]] = {"checkedAt": now.isoformat(), "status": "SKIPPED"}
            else:
                eligible.setdefault(day, []).append(row["gameId"])
                for side in snapshot["sides"]:
                    starter = side["starter"]
                    if starter.get("throws") not in {"L", "R"} and starter.get("mlbamId"):
                        missing_identities.add(str(starter["mlbamId"]))
                    for entry in side["lineup"]:
                        if entry.get("bats") not in {"L", "R", "S"} and entry.get("mlbam"):
                            missing_identities.add(str(entry["mlbam"]))
    if missing_identities:
        from .mlb_v18_current_identity import acquire_current_identity, load_current_identity_evidence
        cached = {str(item["mlbamId"]) for item in load_current_identity_evidence(as_of_utc=now)}
        requests = sorted(missing_identities-cached)
        report["identityRefresh"] = {"alreadyCachedIds": sorted(missing_identities & cached), "requests": [],
                                     "deferredIds": requests[4:], "maximumRequestsPerTick": 4}
        for identifier in requests[:4]:
            previous = state.setdefault("identities", {}).get(identifier)
            if previous and now < utc(previous):
                report["identityRefresh"]["requests"].append({"mlbamId": identifier, "status": "FAILURE_COOLDOWN"})
                continue
            try:
                result = acquire_current_identity(identifier, allow_free_network=True,
                    eligible_current_ids=missing_identities, request_telemetry=request_telemetry)
                report["identityRefresh"]["requests"].append({"mlbamId": identifier, "status": "CAPTURED", "receipt": result["receipt"]})
            except Exception as error:
                state["identities"][identifier] = (now+timedelta(hours=1)).isoformat()
                report["identityRefresh"]["requests"].append({"mlbamId": identifier, "status": "FAILED", "reason": str(error)})
    return eligible


def assemble_handoffs(report, *, publish_exchange=False):
    from datetime import date
    from .mlb_v18_forecast_clock import resolve_forecast_created_at_v1
    report["slates"] = []
    for day in report["discovery"]["slateDates"]:
        games = [row for row in report["games"] if row["gameDate"] == day]
        forecasts = collect_slate_forecasts(PUBLICATIONS, date.fromisoformat(day))
        published = {row["gameId"]: row for row in forecasts}
        for row in games:
            if row["gameId"] in published:
                row["attemptStatus"] = row["status"]
                row["status"] = "PUBLISHED_BEFORE_FIRST_PITCH"
                row["forecast"] = published[row["gameId"]]
                decision_cutoff = (
                    utc(row["scheduledStartUtc"])
                    - timedelta(minutes=AISP_DECISION_CUTOFF_MINUTES)
                )
                creation_clock = resolve_forecast_created_at_v1(
                    row["forecast"], output_root=PUBLICATIONS
                )
                forecast_created = utc(creation_clock["forecastCreatedAt"])
                eligible = forecast_created <= decision_cutoff
                row["consumerDecisionEligibility"] = {
                    "eligible": eligible,
                    "consumerDecisionCutoffUtc": decision_cutoff.isoformat(),
                    "forecastCreatedAt": forecast_created.isoformat(),
                    "reason": (
                        "FORECAST_CLOCK_ON_OR_BEFORE_CONSUMER_DEADLINE"
                        if eligible else
                        "FORECAST_CLOCK_AFTER_CONSUMER_DEADLINE_RESEARCH_ONLY"
                    ),
                    "creationClockResolution": creation_clock,
                }
        handoff = current_handoff(PUBLICATIONS, date.fromisoformat(day), forecasts, games=games)
        receipt = current_import_receipt(PUBLICATIONS, date.fromisoformat(day), forecasts, games, handoff)
        slate = {"slateDate": day, "gamesDiscovered": len(games), "publishedGames": len(published),
                 "gamesSkipped": sum(row["gameId"] not in published for row in games),
                 "handoff": handoff, "importReceipt": receipt}
        if publish_exchange:
            from .mlb_v18_exchange import export_current_handoff
            slate["exchange"] = export_current_handoff(handoff, receipt, publish=True)
        report["slates"].append(slate)


def execute_tick(*, allow_free_network=True, now=None, state_root=STATE_ROOT, output_root=OUTPUT, run_now=False, publish_exchange=False):
    now = now or datetime.now(timezone.utc)
    from .mlb_v18_current_sources import SourceRequestTelemetry
    request_telemetry = SourceRequestTelemetry()
    state_path = Path(state_root) / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"games": {}}
    report = {"schemaVersion": "MLB_V18_UNATTENDED_TICK_V1", "startedAt": now.isoformat(),
              "owner": os.environ.get("MLB_V18_UNATTENDED_OWNER", "MANUAL_BOUNDED_VERIFICATION"),
              "deploymentManifest": os.environ.get("MLB_V18_DEPLOYMENT_MANIFEST"),
              "deploymentIdentity": {
                  "commit": os.environ.get("MLB_V18_DEPLOYED_COMMIT"),
                  "manifestSha256": os.environ.get("MLB_V18_DEPLOYMENT_MANIFEST_SHA256"),
              },
              "timingContract": {
                  "producerChecksBeginMinutesBeforeStart": PRODUCER_FAST_CHECK_WINDOW_MINUTES,
                  "producerDeliveryTargetMinutesBeforeStart": CONSUMER_READY_TARGET_MINUTES,
                  "consumerFinalPregameWindowOpensMinutesBeforeStart": AISP_FINAL_PREGAME_WINDOW_OPENS_MINUTES,
                  "consumerDecisionCutoffMinutesBeforeStart": AISP_DECISION_CUTOFF_MINUTES,
                  "producerResearchPublicationCutoffMinutesBeforeStart": PRODUCER_RESEARCH_CUTOFF_MINUTES,
                  "consumerImportCadenceMinutes": AISP_IMPORT_CADENCE_MINUTES,
                  "consumerEvaluationCadenceMinutes": AISP_EVALUATION_CADENCE_MINUTES,
                  "dispatcherEarlyToleranceSeconds": DISPATCH_EARLY_TOLERANCE_SECONDS,
                  "deadlineTypesRemainIndependent": True,
              },
              "games": [], "stageLogs": [], "providerRequests": [],
              "modelFits": 0, "aispWrites": 0, "sealedEvaluationPayloadReads": 0, "costUsd": 0, **RESEARCH_FLAGS}
    stop = Path(state_root) / "STOP"
    if stop.exists():
        report["status"] = "KILL_SWITCH_ACTIVE"
    elif not allow_free_network:
        report["status"] = "NO_NETWORK_AUTHORITY_NO_EXECUTION"
    elif (not run_now and state.get("nextTickUtc")
          and now + timedelta(seconds=DISPATCH_EARLY_TOLERANCE_SECONDS) < utc(state["nextTickUtc"])):
        report["status"] = "NOT_DUE_NO_PROVIDER_OR_MODEL_ACTIVITY"
    else:
        try:
            discovery = discover(now, allow_free_network=allow_free_network, root=Path(output_root), request_telemetry=request_telemetry)
            report["discovery"] = discovery
            report["providerRequests"].append({"family": "SCHEDULE_IDENTITIES_ONLY", "count": discovery.get("providerCalls", 0), "costUsd": 0})
            due = {}
            for game in discovery["games"]:
                prior = state["games"].get(game["gameId"], {})
                decision = checkpoint(game, prior, now)
                if not game["canonicalIdentityResolved"]:
                    decision.update(due=False, reason="CANONICAL_EVENT_NOT_REGISTERED_IN_LOCAL_IDENTITY_SOURCE")
                if game.get("providerScheduleMissing"):
                    decision.update(due=False, reason="PROVIDER_SCHEDULE_EVENT_NOT_CONFIRMED")
                if game.get("scheduleTimeMismatch"):
                    decision.update(due=False, reason="LOCAL_PROVIDER_START_TIME_MISMATCH")
                if game.get("teamIdentityMismatch"):
                    decision.update(due=False, reason="LOCAL_PROVIDER_TEAM_IDENTITY_MISMATCH")
                row = {**game, "checkpoint": decision, "status": "SKIPPED", "reason": decision["reason"]}
                report["games"].append(row)
                if decision["due"]:
                    due.setdefault(game["gameDate"], []).append(game["gameId"])
            if due and not stop.exists():
                due = preflight_participants(due, report, state, now, request_telemetry=request_telemetry)
            if due and not stop.exists():
                attempt, history = refresh_history(now, state, allow_free_network=allow_free_network, logs=report["stageLogs"])
                report["history"] = history
                from scripts.run_mlb_v18_current_state import run
                for slate_date, game_ids in due.items():
                    if stop.exists():
                        raise ValueError("KILL_SWITCH_ACTIVE_BEFORE_INFERENCE")
                    result = run(SimpleNamespace(source_attempt=attempt, inventory=None, output_root=PUBLICATIONS,
                        slate_date=slate_date, game_ids=game_ids, require_fresh_participants=True))
                    by_id = {row["gameId"]: row for row in result["games"]}
                    for row in report["games"]:
                        if row["gameId"] not in game_ids:
                            continue
                        detail = by_id.get(row["gameId"], {"status": "SKIPPED", "reason": "CLOSED_OR_DISAPPEARED_BEFORE_LIVE_CAPTURE"})
                        row["publication"] = detail
                        row["status"] = detail["status"]
                        row["reason"] = detail.get("reason") or detail.get("error") or "; ".join(str(b.get("reason", b)) for b in detail.get("blockers", []))
                        row["newInference"] = bool(detail.get("newInference"))
                        previous = state["games"].get(row["gameId"], {})
                        failures = previous.get("consecutiveFailures", 0) + 1 if detail["status"] == "FAILED" else 0
                        state["games"][row["gameId"]] = {"checkedAt": datetime.now(timezone.utc).isoformat(),
                            "consecutiveFailures": failures,
                            "retryAfterUtc": (now + timedelta(minutes=retry_delay_minutes(row, failures, now))).isoformat() if failures else None,
                            "status": row["status"]}
            report["status"] = "BOUNDED_TICK_COMPLETED"
            active = any(not row["checkpoint"]["closed"] and utc(row["scheduledStartUtc"]) - now <= timedelta(hours=6) for row in report["games"])
            state["nextTickUtc"] = (now + timedelta(minutes=5 if active else 60)).isoformat()
            state["lastSuccessfulTick"] = now.isoformat()
        except Exception as error:
            report.update(status="FAILED_BOUNDED_TICK", errorType=type(error).__name__, error=str(error))
            for row in report["games"]:
                if row.get("checkpoint", {}).get("due") and "publication" not in row and not row.get("sourcePreflight", {}).get("reasons"):
                    row.update(status="FAILED", reason="SOURCE_OR_PUBLICATION_STAGE_FAILED: " + str(error))
                    previous = state["games"].get(row["gameId"], {})
                    failures = previous.get("consecutiveFailures", 0) + 1
                    state["games"][row["gameId"]] = {"checkedAt": now.isoformat(), "consecutiveFailures": failures,
                        "retryAfterUtc": (now + timedelta(minutes=retry_delay_minutes(row, failures, now))).isoformat(), "status": "FAILED"}
            # Discovery can fail before any game rows exist.  An empty report
            # therefore cannot prove that no consumer deadline is open.  Keep
            # the existing five-minute owner cadence after any bounded failure;
            # the next successful discovery will restore event-aware cadence.
            state["nextTickUtc"] = (now + timedelta(minutes=5)).isoformat()
        # Failed source refresh cannot erase already-published games or omit the
        # remaining discovered slate from its immutable accounting.
        if "discovery" in report:
            try:
                assemble_handoffs(report, publish_exchange=publish_exchange)
            except Exception as error:
                report.update(status="FAILED_BOUNDED_TICK", handoffErrorType=type(error).__name__, handoffError=str(error))
                state["nextTickUtc"] = (now + timedelta(minutes=5)).isoformat()
    report["requestTelemetry"] = request_telemetry.snapshot()
    report["completedAt"] = datetime.now(timezone.utc).isoformat()
    receipt, _ = write_object(Path(output_root), "tick.json", report)
    state["latestReceipt"] = receipt
    atomic_state(state_path, state)
    return {**report, "receipt": receipt}
