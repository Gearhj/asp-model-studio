"""Outcome-blind retained-metadata inventory for the starter/hierarchy study.

No source PA files, outcomes, fitted objects or simulator execution are used.
An optional explicit read-only AISP query captures identity/activation metadata.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/game-eligibility"
CURRENT = ROOT / "outputs/mlb-v18-current-state-pipeline-v1"
DAILY = ROOT / "outputs/mlb-v18-daily-slate"
PARENT = ROOT / "outputs/mlb-v18-whole-game-challenger/sha256/a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27"
CHAMPION = ROOT / "outputs/mlb-v18-conditional-champion-v1"
START, END = "2026-08-28", "2026-09-10"
SCHEDULE_RECEIPT = CURRENT / "sources/objects/sha256/3ddda19404ae4f0f70eef4c757c0429487e961e2785f8ba3c79f4c71e1fcbb74.receipt.json"
REFS = {}


def ref(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    value = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    REFS[str(path)] = value
    return value


def read(path, expected=None):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT) or path.suffix != ".json":
        raise ValueError("Only local Model Studio metadata JSON is permitted")
    actual = ref(path)
    if expected:
        for key in ("sha256", "bytes"):
            if key in expected and actual[key] != expected[key]:
                raise ValueError("Metadata checksum mismatch: " + str(path))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def utc(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def write(name, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(data).hexdigest()
    path = OUT / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data
    else:
        with path.open("xb") as handle:
            handle.write(data)
    return {"path": str(path), "sha256": digest, "bytes": len(data)}


def aisp_metadata():
    # No scores, outcomes, decisions, positions, metrics or payload JSON queried.
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    uri = make_url(dotenv_values(Path("C:/Users/james/ai-sports-predictor/.env"))["DATABASE_URL"]
                   .replace("postgresql+psycopg://", "postgresql+psycopg2://"))
    if uri.host not in ("localhost", "127.0.0.1"):
        raise ValueError("Only configured local AISP database is allowed")
    queries = {
        "databaseIdentity": "select current_database() database_name,inet_server_port() server_port",
        "activationTables": "select table_name from information_schema.tables where table_schema='public' and (table_name like '%champion%' or table_name like '%activation%' or table_name like '%model_era%') order by table_name",
        "v18RegisteredModelMetadata": "select id,name,version,status,artifact_uri,artifact_checksum,created_at,promotion_decision,promotion_reason from model_versions where name ilike '%V18%' order by created_at",
        "mlbExperimentMetadata": "select id,name,version,sport,is_active,controlling_engine,created_at,started_at,recommendation_policy_version,staking_policy_version,code_identity from shadow_experiments where sport='MLB' or name ilike '%V18%' order by created_at",
        "gameIdentityMetadata": """select g.id::text game_id,em.external_id source_game_id,g.starts_at,g.status
            from games g join leagues l on l.id=g.league_id join external_id_mappings em
            on em.entity_id=g.id and em.entity_type='game' and em.source='MLB_STATS_API'
            where l.code='MLB' and g.starts_at>=:start and g.starts_at<:end order by g.starts_at,g.id""",
    }
    engine = create_engine(uri)
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            conn.execute(text("SET TRANSACTION READ ONLY"))
            assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
            captured = datetime.now(timezone.utc).isoformat()
            values = {name: [dict(row) for row in conn.execute(text(sql),
                {"start": "2026-08-28T00:00:00-04:00", "end": "2026-09-11T00:00:00-04:00"}).mappings()]
                for name, sql in queries.items()}
            tx.rollback()
    finally:
        engine.dispose()
    return json.loads(json.dumps({"schemaVersion": "AISP_MLB_IDENTITY_ACTIVATION_READ_ONLY_V1",
        "capturedAt": captured, "configuredConnectionOnly": True, "transactionReadOnlyConfirmed": True,
        "queries": queries, "results": values, "aispWrites": 0, "outcomesRead": 0,
        "limitation": "Configured local source database; no independent frontend-serving database assertion or pending Claude work inferred."}, default=str))


def main(args):
    REFS.clear()
    rule = {"schemaVersion": "MLB_DURATION_RECENT_GAME_ELIGIBILITY_RULE_V1", "window": [START, END],
        "cohortSelection": "Every regular-season schedule-listed game by official date, regardless of result. Preserve canceled/postponed/mismatched identities separately.",
        "currentSourcePotential": "Exact original frozen V18 object plus capturedAt <= original forecastCreatedAt < scheduledStart, same canonical event, original current-state source-contract evidence. This is only a source eligibility screen, not certification of fitted historical information timing.",
        "legacyEvidence": "Preserve older projected-lineup and carried-forward-template forecasts separately; no silent upgrade to current complete-source authority. A retained publication receipt may bound creation time when forecastCreatedAt is absent, but capture time alone does not prove publication.",
        "reconstruction": "No later captured participants, actual pitching changes or outcomes may be borrowed as pregame evidence. Missing historical pregame records stay missing.",
        "modelTimingGate": "PENDING_SEPARATE_FROZEN_ESTIMATOR_PREPROCESSOR_CALIBRATION_AND_HISTORY_AVAILABILITY_AUTHORITY",
        "simulationSelection": "No simulation cohort is authorized by this inventory. Only after source and model timing gates, select earliest date/ID up to25 games without outcomes.",
        "outcomesReadBeforeDeclaration": 0}
    rule_ref = write("eligibility-rule.json", rule)
    if args.aisp_snapshot:
        database = read(args.aisp_snapshot)
        db_ref = ref(args.aisp_snapshot)
    elif args.read_aisp:
        database = aisp_metadata()
        db_ref = write("aisp-activation-identity-snapshot.json", database)
        read(db_ref["path"], db_ref)
    else:
        database, db_ref = None, None
    registry = read(CHAMPION / "registration/sha256/abe96ab97b3ea3215cc4c0656085a806123840968a1645a259adef002e2b11b8/registration-receipt.json")
    champion_handoff = read(CHAMPION / "aisp-handoff/sha256/a3d6ea3fdb9ddecc42e7b5ecac975d0d132931c0ca7bfc0938bdcef205f2d300/champion-handoff.json")
    receipt = read(SCHEDULE_RECEIPT)
    assert receipt["family"] == "SCHEDULE_IDENTITIES_ONLY"
    assert receipt["sealedDateScope"] == "SCHEDULE_IDENTITY_METADATA_ONLY_NO_OUTCOME_PA_LINEUP_INNINGS_PAYLOAD"
    schedule = read(receipt["raw"]["path"], receipt["raw"])
    # This independent schedule-only projection has no scores/PA/innings/lineups,
    # including outside this date window. No mixed feature/evaluation file opens.
    games = [{"gameDate": day["date"], "mlbamGamePk": g["gamePk"], "scheduledStartUtc": g["gameDate"],
              "homeTeam": g["teams"]["home"]["team"], "awayTeam": g["teams"]["away"]["team"],
              "scheduleStatus": g["status"], "gameNumber": g.get("gameNumber"), "doubleHeader": g.get("doubleHeader")}
             for day in schedule["dates"] if START <= day["date"] <= END for g in day["games"]]
    assert len({g["mlbamGamePk"] for g in games}) == len(games)
    mapping = {}
    if database:
        for row in database["results"]["gameIdentityMetadata"]:
            mapping.setdefault(str(row["source_game_id"]), []).append(row)
    # Retained publication timestamps, never filesystem modification times.
    creation_bounds, prior_skips = {}, {}
    for path in sorted((DAILY / "slates/2026-09-08/sha256").glob("*/slate-result.json")):
        body = read(path)
        for row in body.get("games", []):
            if row.get("objectSha256") and body.get("generatedAt"):
                creation_bounds.setdefault(row["objectSha256"], []).append({"at": body["generatedAt"], "receipt": ref(path)})
            elif row.get("status") in ("SKIPPED", "FAILED"):
                prior_skips.setdefault(row["gameId"], []).append({"status": row["status"], "reason": row.get("reason"), "receipt": ref(path)})
    forecasts = {}
    for root, category in ((DAILY, "LEGACY_PROJECTED_LINEUP_AND_CARRIED_FORWARD_CONTEXT"), (CURRENT, "CURRENT_STATE_SOURCE_PATH")):
        for path in sorted((root / "objects/sha256").glob("*/forecast.json")):
            value = read(path)
            if not START <= str(value["scheduledStart"])[:10] <= END:
                REFS.pop(str(path.resolve()), None)
                continue
            manifest = read(path.parent / "manifest.json")
            child = next(r for r in manifest["artifacts"] if r["relativePath"] == "forecast.json")
            read(path, child)
            captured, start = utc(value["capturedAt"]), utc(value["scheduledStart"])
            created = value.get("forecastCreatedAt")
            bounds = sorted(creation_bounds.get(path.parent.name, []), key=lambda r: utc(r["at"]))
            published_pregame = utc(created) < start if created else bool(bounds and utc(bounds[0]["at"]) < start)
            item = {"forecast": ref(path), "objectSha256": path.parent.name, "gameId": value["gameId"],
                "sourceGameId": value.get("sourceGameId"), "evidenceCategory": category,
                "capturedAt": value["capturedAt"], "scheduledStart": value["scheduledStart"],
                "originalForecastCreatedAt": created, "earliestRetainedPublicationUpperBound": bounds[0] if bounds else None,
                "pregameCapture": captured < start, "pregamePublicationEstablished": published_pregame,
                "knownLimitations": value.get("knownLimitations", []),
                "lineupAuthorities": value.get("lineupAuthorities"),
                "frozenParentAuthority": value.get("parentAuthority"),
                "potentialCurrentSourceComparison": bool(category == "CURRENT_STATE_SOURCE_PATH" and created and captured <= utc(created) < start),
                "modelTimingEligibility": "PENDING_SEPARATE_AUTHORITY", "eligibleForFourArmSimulationNow": False}
            forecasts.setdefault(str(value.get("sourceGameId")), []).append(item)
    original = read(PARENT / "prospective-forecast.json")
    original_snapshot = read(PARENT / "aisp-pregame-snapshot.json")
    original_key = str(original_snapshot["game"]["source_game_id"])
    forecasts.setdefault(original_key, []).append({"forecast": ref(PARENT / "prospective-forecast.json"),
        "gameId": original["gameId"], "sourceGameId": original_key, "capturedAt": original["capturedAt"],
        "scheduledStart": original["scheduledStart"], "pregameCapture": utc(original["capturedAt"]) < utc(original["scheduledStart"]),
        "originalForecastCreatedAt": None, "pregamePublicationEstablished": False,
        "evidenceCategory": "ORIGINAL_PROJECTED_PRIOR_LINEUP_DEMONSTRATOR",
        "lineupAuthorities": {r["side"]: r["lineupAuthority"] for r in original_snapshot["sides"]},
        "potentialCurrentSourceComparison": False, "modelTimingEligibility": "PENDING_SEPARATE_AUTHORITY",
        "eligibleForFourArmSimulationNow": False})
    current_attempts = {}
    for path in sorted((CURRENT / "objects/sha256").glob("*/complete-run.json")):
        body = read(path)
        capture = body.get("capturedAt")
        if not capture or not START <= str(capture)[:10] <= END:
            REFS.pop(str(path.resolve()), None)
            continue
        for row in body.get("games", []):
            current_attempts.setdefault(row["gameId"], []).append({"receipt": ref(path), "capturedAt": capture,
                "status": row.get("status"), "reason": row.get("reason"), "blockers": row.get("blockers", []),
                "coverage": row.get("coverage"), "objectSha256": row.get("objectSha256")})
    for game in games:
        key = str(game["mlbamGamePk"])
        game["localIdentityMatches"] = mapping.get(key, [])
        game["canonicalAispEventId"] = mapping[key][0]["game_id"] if len(mapping.get(key, [])) == 1 else None
        game["identityStatus"] = "EXACT_LOCAL_MAP" if len(mapping.get(key, [])) == 1 else "MISSING_OR_AMBIGUOUS_LOCAL_MAP"
        game["localScheduleTimeMatches"] = (utc(mapping[key][0]["starts_at"]) == utc(game["scheduledStartUtc"])) if len(mapping.get(key, [])) == 1 else None
        game["forecastEvidence"] = forecasts.get(key, [])
        game["forecastScheduleTimeMatches"] = all(utc(f["scheduledStart"]) == utc(game["scheduledStartUtc"]) for f in game["forecastEvidence"]) if game["forecastEvidence"] else None
        game["historicalPublisherSkips"] = prior_skips.get(game["canonicalAispEventId"], [])
        game["retainedCurrentSourceAttempts"] = sorted(current_attempts.get(game["canonicalAispEventId"], []), key=lambda r: utc(r["capturedAt"]))
        game["classification"] = ("CURRENT_SOURCE_PREGAME_FORECAST_MODEL_TIMING_GATE_PENDING" if any(f["potentialCurrentSourceComparison"] for f in game["forecastEvidence"])
            else "LEGACY_PREGAME_EVIDENCE_NOT_CURRENT_SOURCE_EQUIVALENT" if game["forecastEvidence"] else "NO_RETAINED_V18_PREGAME_FORECAST_OR_COMPLETE_INPUT_AUTHORITY")
        game["exactMissingDependency"] = ("Separate fitted-information timing authority and frozen common four-arm input/reliever contract" if game["classification"].startswith("CURRENT")
            else "Separate validation of legacy projected-lineup/template contract; no current-source-equivalent input construction proved" if game["forecastEvidence"]
            else "Retained pregame V18 execution inputs with original availability clocks and exact event/player identities; a current historical source download cannot replace the missing pregame vintage")
        game["selectedForSimulation"] = False
    mechanism_code = ROOT / "server/sports_current_statcast/mlb_v18_whole_game_challenger.py"
    mechanism = {"callable": "server.sports_current_statcast.mlb_v18_whole_game_challenger.starter_removal_probability",
        "code": ref(mechanism_code), "fitted": False,
        "linearPredictor": "-5.25 + .58*max(inning-3,0) + .16*max(BF-23+4,0) + .48*runs_while_starter_active + .82*max(BF//9+1-1,0)",
        "link": "sigmoid; zero below9BF; cap0.95", "pregameExpectedBfDefault": 23.0,
        "inputsActuallyConsumed": ["inning", "starter BF", "simulated runs while starter active", "BF//9+1"],
        "inputsNotConsumed": ["actual or simulated pitch count", "elapsed clock", "recent workload/rest", "injury/pitch limit", "bullpen availability", "manager identity"],
        "decisionClock": "Before the next PA while game and starter remain active, including after inning transitions; removal consumes no PA. Inning is an integer game-state field, not decimal pitching innings.",
        "runAttributionLimitation": "Runs scored while starter state is active, not official earned runs or complete inherited-runner responsibility.",
        "earlyExits": "Existing policy forces zero removal probability before9BF; short starts remain eligible in duration research rather than being silently excluded.",
        "endGame": "active=~terminal gates removal; terminal state set after walkoff/completed regulation/extra inning, so no later hook; loop bounded at200PA.",
        "starterReentry": "starter_active flags only change true to false; source pool selection excludes the starter identity.",
        "relieverContract": "TEAM_BULLPEN latent state; uniformly average frozen PA probabilities over the supplied nonempty pregame staff templates. No named reliever selection, stint duration, exhaustion or availability claim.",
        "relieverAvailability": "UNKNOWN_NOT_ALL_RELIEVERS_ASSERTED_AVAILABLE",
        "integrationHook": "Existing simulator has no removal callback. A separate research-only simulator adapter can preserve PA RNG, transitions, lineup, source staff mixture and terminal/reentry guards while accepting a frozen hazard callable. Do not monkeypatch or modify the pinned/frozen producer.",
        "researchDeployableCovariates": ["inning", "starter BF", "starter pitching outs tracked from legal transitions", "simulated starter-state runs", "current score/base/out state", "lineup position", "TTO", "supported immutable pregame fields"],
        "cannotGenerate": ["cumulative pitch count", "actual elapsed time", "reliever-specific availability"],
        "simulationExecutions": 0}
    activation_evidence = bool(database and (database["results"]["activationTables"]
        or database["results"]["v18RegisteredModelMetadata"]
        or any("V18" in str(r.get("name", "")) or "V18" in str(r.get("controlling_engine", ""))
               for r in database["results"]["mlbExperimentMetadata"])))
    model_studio = {"registered": True, "registrationReceipt": registry,
        "aispHandoffPerformedInAisp": champion_handoff["activation"]["performedInAisp"],
        "plannedEffectiveAt": champion_handoff["modelEra"]["effectiveAtUtc"],
        "actualAispActivation": ("ACTIVATION_METADATA_PRESENT_REQUIRES_EFFECTIVE_AUTHORITY_VERIFICATION" if activation_evidence else
            "NOT_EVIDENCED_IN_CONFIGURED_LOCAL_DATABASE_OR_HANDOFF" if database else "NOT_INDEPENDENTLY_QUERIED"),
        "basis": ("Inspect the captured activation metadata before asserting an effective transition." if activation_evidence else
            "No V18 experiment/model-version or champion/activation/model-era table in read-only snapshot; existing V2.1 controlling_engine remains AISP_BASELINE. Existing V18 shadow import is not primary champion activation."),
        "aispSnapshot": db_ref}
    report = {"schemaVersion": "MLB_STARTER_DURATION_RECENT_WINDOW_ACCOUNTING_V1", "eligibilityRule": rule_ref,
        "window": [START, END], "scheduleReceipt": ref(SCHEDULE_RECEIPT), "scheduleObservedAt": receipt["observedAt"],
        "scheduleVintage": "Retrospectively captured schedule-only metadata; not original historical schedule/publication availability.",
        "scheduleCompletenessLimitation": "All189 entries in the retained projection are FINAL at capture. Original canceled/removed or rescheduled schedule vintages are not independently reconstructed; do not infer no earlier schedule changes from this later projection.",
        "scheduledGames": len(games), "countsByDate": dict(sorted(Counter(g["gameDate"] for g in games).items())),
        "classifications": dict(Counter(g["classification"] for g in games)), "games": games,
        "storedForecastObjects": sum(len(g["forecastEvidence"]) for g in games),
        "gamesWithPregamePublicationEvidence": sum(any(f["pregamePublicationEstablished"] for f in g["forecastEvidence"]) for g in games),
        "potentialCurrentSourceGames": sum(any(f["potentialCurrentSourceComparison"] for f in g["forecastEvidence"]) for g in games),
        "selectedSimulationGames": 0, "championState": model_studio, "existingMechanism": mechanism,
        "verification": {"scheduleIdsUnique": True, "forecastsAndManifestChecksumsVerified": True,
            "providerCalls": 0, "fits": 0, "inferenceCalls": 0, "gameSimulations": 0, "aispWrites": 0,
            "outcomesRead": 0, "sealedOotPayloadReads": 0, "pinnedPublisherChanges": 0},
        "sourceReferences": sorted(REFS.values(), key=lambda r:r["path"]), "script": ref(__file__)}
    output = write("game-eligibility.json", report)
    print(json.dumps({"report": output, "aispSnapshot": db_ref, "scheduledGames": len(games),
        "classifications": report["classifications"], "potentialCurrentSourceGames": report["potentialCurrentSourceGames"]}, indent=2))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--read-aisp", action="store_true")
    group.add_argument("--aisp-snapshot", type=Path)
    main(parser.parse_args())
