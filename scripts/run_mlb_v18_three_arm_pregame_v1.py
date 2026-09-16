"""Declare and locally freeze one bounded three-arm pregame cohort.

No acquisition, outcomes, scheduler, exchange or AISP writes. Ordinary publisher
objects supply the unchanged baseline. Unsupported arms explicitly reuse it.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np
from threadpoolctl import threadpool_limits
from server.sports_current_statcast import mlb_v18_daily_slate as daily
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_unattended import atomic_state, single_owner
from server.sports_datasets.consumer import canonical_json_bytes
from run_mlb_v18_transition_shrinkage_v1 import load_baseline, compact, utc

OUT = ROOT / "outputs/mlb-v18-three-arm-pregame-comparison-v1"
SCHEMA = "MLB_V18_THREE_ARM_PREGAME_V1"
ARMS = ("V18_BASE", "V18_SURVIVAL_ONLY", "V18_TRANSITION_ONLY")
SURVIVAL_SHA = "f64f82b4fadf35acd3418bc298548c48bb73cf624fe8c70ba01a87c33e8d2370"
TRANSITION_SHA = "8c91d687c95ff81ad11efa7a5e718aa5bbfeb0aa97cc05795bd26e3954939640"
SURVIVAL_PATH = ROOT / f"outputs/mlb-starter-survival-hierarchical-pa-v1/duration-study/objects/sha256/{SURVIVAL_SHA}/fitted-hazard.joblib"
TRANSITION_PATH = ROOT / f"outputs/mlb-v18-transition-shrinkage-v1/components/sha256/{TRANSITION_SHA}/transition.json"
PRODUCER_LOCK = ROOT / ".runtime/mlb-v18-unattended/producer.lock"
FIELDS = ("homeRuns", "awayRuns", "innings", "paCounts")
FLAGS = {"researchShadowOnly": True, "candidateAuthority": False,
         "executionAllowedInAISP": False, "executionAllowedInAisp": False,
         "wageringAuthority": False, "modelActivationAllowed": False,
         "promotionStatus": "NOT_PROMOTED", "calibrationEnabled": False}
SHARED_CODE = ("server/sports_current_statcast/mlb_starter_duration_paired_simulation.py",
               "server/sports_current_statcast/mlb_starter_duration_paired_publication.py",
               "server/sports_current_statcast/mlb_starter_duration_current_inputs.py",
               "server/sports_current_statcast/mlb_v18_prospective_transform.py")


def now():
    return datetime.now(timezone.utc)


def ref(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def read(descriptor):
    if ref(descriptor["path"]) != {k: descriptor[k] for k in ("path", "sha256", "bytes")}:
        raise ValueError("IMMUTABLE_INPUT_CHECKSUM_MISMATCH")
    return json.loads(Path(descriptor["path"]).read_text(encoding="utf-8"))


def put(name, payload, output=OUT):
    data = payload if isinstance(payload, bytes) else canonical_json_bytes(daily.json_safe(payload))
    digest = hashlib.sha256(data).hexdigest()
    path = output / "objects/sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("IMMUTABLE_OUTPUT_COLLISION")
    else:
        with path.open("xb") as stream:
            stream.write(data)
    return ref(path)


def select_members(slate, slate_date, declared_at):
    """Schedule identities only; a closed opportunity cannot become prospective."""
    games, excluded = [], []
    source_rows = (slate.get("discovery") or {}).get("games", [])
    if not source_rows:
        raise ValueError("RETAINED_PUBLISHER_DISCOVERY_GAMES_REQUIRED")
    for row in source_rows:
        start = utc(row["scheduledStartUtc"])
        day = row.get("gameDate") or start.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if day != slate_date:
            continue
        game_id = str(row["gameId"])
        source_id = str(row.get("mlbamGamePk") or row.get("sourceGameId") or "")
        deadline = start - timedelta(minutes=15)
        local = row.get("localSchedule") or {}
        source_status = str(row.get("status", "")).upper().replace("-", " ")
        local_status = str(local.get("status", "")).upper()
        reason = None
        if (not source_id or not all(final_oot_eligible_key_mask([game_id, source_id]))
                or "2026-08-14" <= day <= "2026-08-27" or game_id.startswith("UNMAPPED_")):
            reason = "IDENTITY_OR_QUARANTINE_INELIGIBLE"
        elif (row.get("canonicalIdentityResolved") is not True
              or row.get("scheduleTimeMismatch") or row.get("teamIdentityMismatch")
              or local.get("game_id") != game_id or str(local.get("source_game_id")) != source_id
              or utc(local["starts_at"]) != start
              or str(local.get("home_mlbam_id")) != str(row.get("homeTeamMlbamId"))
              or str(local.get("away_mlbam_id")) != str(row.get("awayTeamMlbamId"))):
            reason = "SCHEDULE_IDENTITY_TIME_OR_TEAM_MISMATCH"
        elif source_status not in ("SCHEDULED", "PRE GAME", "WARMUP", "PREVIEW") or local_status != "SCHEDULED":
            reason = "SOURCE_OR_LOCAL_STATUS_NOT_PREGAME"
        elif declared_at >= deadline:
            reason = "DEADLINE_CLOSED_AT_DECLARATION"
        item = {"gameId": game_id, "sourceGameId": source_id,
                "homeTeamMlbamId": row.get("homeTeamMlbamId"), "awayTeamMlbamId": row.get("awayTeamMlbamId"),
                "scheduledStartUtc": start.isoformat(), "deadlineUtc": deadline.isoformat()}
        (excluded if reason else games).append({**item, **({"reason": reason} if reason else {})})
    if len({g["gameId"] for g in games}) != len(games) or len({g["sourceGameId"] for g in games}) != len(games):
        raise ValueError("DUPLICATE_SLATE_IDENTITY")
    return sorted(games, key=lambda g: (g["scheduledStartUtc"], g["gameId"])), excluded


def declare(slate_path, slate_date, output=OUT):
    stamp = now()
    slate_ref = ref(slate_path)
    slate = read(slate_ref)
    games, excluded = select_members(slate, slate_date, stamp)
    if not games:
        raise ValueError("NO_UNEXPIRED_PREGAME_SLATE_MEMBERS")
    if ref(SURVIVAL_PATH)["sha256"] != SURVIVAL_SHA or ref(TRANSITION_PATH)["sha256"] != TRANSITION_SHA:
        raise ValueError("FROZEN_COMPONENT_IDENTITY_CHANGED")
    declaration = {"schemaVersion": SCHEMA + "_DECLARATION", "declaredAtUtc": stamp.isoformat(),
        "slateDate": slate_date, "scheduleEvidence": slate_ref, "games": games,
        "excludedAtDeclaration": excluded, "stopAfterUtc": max(g["deadlineUtc"] for g in games),
        "arms": list(ARMS), "simulationCountPerArm": daily.SIMULATION_COUNT, "masterSeed": daily.MASTER_SEED,
        "paModelSha256": daily.PA_MODEL_SHA256, "treatmentManifestSha256": daily.TREATMENT_MANIFEST_SHA256,
        "baselineTransitionSha256": daily.TRANSITION_MODEL_SHA256,
        "baselineParentBundleSha256": daily.PARENT_BUNDLE_SHA256,
        "sharedExecutionCode": [ref(ROOT / name) for name in SHARED_CODE],
        "components": {ARMS[1]: ref(SURVIVAL_PATH), ARMS[2]: ref(TRANSITION_PATH)},
        "transitionProtocol": ref(ROOT / "outputs/mlb-v18-transition-shrinkage-v1/protocol.json"),
        "transitionConfiguration": {"priorStrength": 20.0, "legalFloor": 1e-6, "trainingSeasons": [2023, 2024, 2025]},
        "inclusionRule": "Fixed remaining slate identities; require existing verified genuinely eligible ordinary V18 object, identical schedule/participants and all immutable source bindings; publication accounting is reconciled separately, with no readiness forcing or acquisition.",
        "baselineRule": "Bind the newest compatible ordinary forecast at the first numerical attempt; reuse its exact5000draws and preserve all original clocks. No later baseline substitution.",
        "historyCutoffRule": "Evaluate certified duration history at the original baseline snapshot cutoff, never at a later component execution time.",
        "comparisonRule": "Only both-supported games permit direct survival-vs-transition assessment. Individual supported pairs remain separate; identical fallback is operational coverage, never a component trial.",
        "stoppingRule": "At most one numerical attempt per game; no games added and no extension beyond the last original deadline. One manual bounded run handles at most one game by default; never schedules itself.",
        "metrics": ["winnerLogLoss", "winnerBrier", "homeRuns", "awayRuns", "totalRuns", "homeMargin", "empiricalDistributionScores"],
        "componentMetrics": "Starter BF/exposure and transition sequence measures only when governed assessment evidence exists; absence does not block whole-game scoring.",
        "historicalTrainingChronologyCertified": False, "outcomeAccess": False,
        "baselineSource": "WINDOWS_OWNED_ORDINARY_V18_PUBLISHER", "publicationOwner": "EXISTING_RESEARCH_EXCHANGE_PATH_ONLY",
        "producerLock": str(PRODUCER_LOCK), "driver": ref(__file__), **FLAGS}
    descriptor = put("declaration.json", declaration, output)
    pointer = output / "declaration-current.json"
    if pointer.exists() and read(json.loads(pointer.read_text(encoding="utf-8")))["slateDate"] == slate_date:
        raise ValueError("EXISTING_SLATE_DECLARATION_MUST_BE_REUSED")
    atomic_state(pointer, descriptor)
    return descriptor


def load_declaration(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    descriptor = data if {"path", "sha256", "bytes"} <= data.keys() else ref(path)
    declared = read(descriptor)
    if (declared["schemaVersion"] != SCHEMA + "_DECLARATION" or declared["arms"] != list(ARMS)
            or declared["simulationCountPerArm"] != 5000 or declared["masterSeed"] != daily.MASTER_SEED
            or declared["paModelSha256"] != daily.PA_MODEL_SHA256
            or declared["treatmentManifestSha256"] != daily.TREATMENT_MANIFEST_SHA256
            or declared["baselineTransitionSha256"] != daily.TRANSITION_MODEL_SHA256
            or declared["baselineParentBundleSha256"] != daily.PARENT_BUNDLE_SHA256
            or declared["sharedExecutionCode"] != [ref(ROOT / name) for name in SHARED_CODE]
            or declared["driver"] != ref(__file__)
            or declared["components"][ARMS[1]]["sha256"] != SURVIVAL_SHA
            or declared["components"][ARMS[2]]["sha256"] != TRANSITION_SHA):
        raise ValueError("DECLARATION_CONFIGURATION_MISMATCH")
    return descriptor, declared


def state_root(output, declaration_ref):
    return output / "cohorts" / declaration_ref["sha256"]


def baseline_candidates(declaration):
    """Read forecast identity metadata only. Never inspect game outcomes."""
    from server.sports_current_statcast.mlb_v18_daily_slate import collect_slate_forecasts
    from datetime import date
    rows = collect_slate_forecasts(ROOT / "outputs/mlb-v18-current-state-pipeline-v1", date.fromisoformat(declaration["slateDate"]))
    return {row["gameId"]: row for row in rows}


def plan(declaration_ref, declaration, output=OUT):
    candidates = baseline_candidates(declaration)
    states = state_root(output, declaration_ref)
    records = []
    for game in declaration["games"]:
        finished = states / "frozen" / (game["gameId"] + ".json")
        attempt = states / "attempts" / (game["gameId"] + ".json")
        if finished.exists():
            descriptor = json.loads(finished.read_text(encoding="utf-8"))
            frozen = read(descriptor)
            records.append({**game, "status": "LOCALLY_FROZEN_AWAITING_EXCHANGE", "result": descriptor,
                            "arms": frozen["arms"], "commonSupported": frozen["commonSupported"]})
            continue
        candidate = candidates.get(game["gameId"])
        status = ("ATTEMPT_ALREADY_CONSUMED" if attempt.exists() else
                  "DEADLINE_CLOSED_NO_BACKFILL" if now() >= utc(game["deadlineUtc"]) else
                  "BASELINE_OBJECT_AVAILABLE" if candidate else "WAITING_FOR_ORDINARY_PUBLISHER")
        records.append({**game, "status": status, "baselineObjectSha256": candidate.get("objectSha256") if candidate else None})
    frozen = [r for r in records if "arms" in r]
    return {"schemaVersion": SCHEMA + "_STATUS", "generatedAtUtc": now().isoformat(), "declaration": declaration_ref,
        "slateDate": declaration["slateDate"], "records": records,
        "counts": {"declared": len(records), "locallyFrozen": len(frozen), "published": 0, "importConfirmed": 0,
          "baselineReady": sum(r["status"] == "BASELINE_OBJECT_AVAILABLE" for r in records),
          "survivalSupported": sum(r["arms"][ARMS[1]]["status"] == "APPLIED" for r in frozen),
          "transitionSupported": sum(r["arms"][ARMS[2]]["status"] == "APPLIED" for r in frozen),
          "commonSupported": sum(r["commonSupported"] for r in frozen),
          "fallbackArms": sum(r["arms"][a]["status"] == "BASELINE_FALLBACK" for r in frozen for a in ARMS[1:]),
          "blockedOrPending": len(records) - len(frozen)},
        "publicationAccounting": "External publication/import receipts are owned by the existing exchange workflow; local freeze alone is not publication.", **FLAGS}


def verify_member(bundle, game, declaration, timestamp):
    forecast, snapshot, execution = bundle["forecast"], bundle["snapshot"], bundle["execution"]
    if (forecast["gameId"] != game["gameId"] or str(forecast["sourceGameId"]) != game["sourceGameId"]
            or utc(forecast["scheduledStart"]) != utc(game["scheduledStartUtc"])
            or utc(snapshot["game"]["starts_at"]) != utc(game["scheduledStartUtc"])):
        raise ValueError("DECLARED_GAME_OR_KICKOFF_DIFFERS")
    if timestamp >= utc(game["deadlineUtc"]):
        raise ValueError("THREE_ARM_PREGAME_CUTOFF_CLOSED")
    if not utc(declaration["declaredAtUtc"]) < utc(game["deadlineUtc"]):
        raise ValueError("DECLARATION_AFTER_CUTOFF")
    if execution["sourceCutoff"] != forecast["sourceCutoff"]:
        raise ValueError("BASELINE_SOURCE_CUTOFF_DIFFERS")
    crosswalk = {str(row["team_id"]): str(row["mlbam_id"]) for row in snapshot["teamIdentityCrosswalk"]}
    for side in ("HOME", "AWAY"):
        if crosswalk.get(forecast["teams"][side]["uuid"]) != str(game[side.lower() + "TeamMlbamId"]):
            raise ValueError("DECLARED_TEAM_IDENTITY_DIFFERS")
    established_id = "mlb-v18-daily-" + bundle["objectSha256"]
    if any(forecast.get(key) not in (None, established_id) for key in ("forecastId", "forecast_id")):
        raise ValueError("BASELINE_FORECAST_ID_DIFFERS_FROM_ESTABLISHED_CONTRACT")


def applied(population, metadata):
    return {"status": "APPLIED", "actualConfiguration": metadata["configuration"],
            "fallbackReason": None, "componentTrial": True, "summary": compact(population), **metadata}


def fallback(base, reason):
    return {"status": "BASELINE_FALLBACK", "actualConfiguration": ARMS[0],
            "fallbackReason": reason, "componentTrial": False, "summary": compact(base)}


def shared_provider(engine, bundle):
    """Existing live provider with the original authenticated evidence cutoff."""
    import pandas as pd
    from server.sports_current_statcast.mlb_starter_duration_paired_publication import _validate_eligible_inputs
    from server.sports_current_statcast.mlb_v18_current_publication import current_template
    from server.sports_current_statcast.mlb_v18_prospective_transform import ProspectiveFrameAuthority, wrap_prospective_pipeline
    from server.sports_current_statcast.mlb_v18_whole_game_challenger import V18StateProbabilityProvider
    forecast, snapshot, execution = (bundle[k] for k in ("forecast", "snapshot", "execution"))
    feature_ref = execution["featureSnapshot"]
    composition = read(feature_ref)["composition"]
    _validate_eligible_inputs(snapshot, composition)
    cutoff = execution["sourceCutoff"]
    if (cutoff != forecast["sourceCutoff"] or cutoff != composition["sourceCutoff"]
            or execution["providerInputs"] != composition["providerInputs"]
            or not composition["canSimulate"] or composition["blockers"]):
        raise ValueError("ORIGINAL_PREGAME_INPUT_BINDINGS_DIFFER")
    source_clock = cutoff["evidenceAvailableAt"] if isinstance(cutoff, dict) else cutoff
    if not utc(source_clock) <= utc(snapshot["capturedAt"]) <= utc(forecast["forecastCreatedAt"]):
        raise ValueError("ORIGINAL_SOURCE_CUTOFF_CLOCK_DIFFERS")
    raw = pd.DataFrame(composition["rows"], columns=engine.contract["rawFeatureColumns"])
    authority = ProspectiveFrameAuthority(event_id=snapshot["game"]["game_id"], game_date=str(raw.game_date.iloc[0])[:10],
        evidence_cutoff_utc=source_clock, kickoff_utc=snapshot["game"]["starts_at"],
        snapshot_sha256=feature_ref["sha256"], authorized_at_utc=now().isoformat(),
        venue_timezone=composition.get("venueTimezone") or composition["event"]["venueTimezone"])
    authority.validate()
    pipeline = wrap_prospective_pipeline(engine.pipeline, authority)
    actual = np.concatenate([pipeline.predict_proba(raw.iloc[[i]]) for i in range(len(raw))])
    expected = np.asarray(execution["initialPaProbabilities"])
    if actual.shape != (18, 8) or not np.array_equal(actual, expected):
        raise ValueError("ORIGINAL_INITIAL_PA_PROBABILITIES_DIFFER")
    inputs = execution["providerInputs"]
    provider = V18StateProbabilityProvider(pipeline, away_batters=inputs["awayBatters"], home_batters=inputs["homeBatters"],
        away_starter=inputs["awayStarter"], home_starter=inputs["homeStarter"], away_bullpen=inputs["awayBullpen"],
        home_bullpen=inputs["homeBullpen"], temperature=None, template_composer=current_template)
    return provider, {"initialProbabilityRows": 18, "mismatches": 0, "fits": 0,
                      "authorityEvidenceCutoffUtc": source_clock, "sourceCutoff": cutoff}


def execute_game(bundle, game, declaration, deadline):
    from server.sports_current_statcast.mlb_starter_duration_paired_publication import load_duration_model
    from server.sports_current_statcast.mlb_starter_duration_current_inputs import build_current_duration_inputs
    from server.sports_current_statcast.mlb_starter_duration_paired_simulation import (
        _duration_lookup, simulate_research_arm, REFERENCE, CHALLENGER, verify_frozen_mechanics)
    from server.sports_current_statcast.mlb_v18_current_publication import CurrentV18Engine
    from server.sports_phase5.hierarchical_transition import HierarchicalTransitionModel
    forecast, snapshot, execution = (bundle[k] for k in ("forecast", "snapshot", "execution"))
    verify_member(bundle, game, declaration, now())
    base = bundle["baseline"]
    populations = {arm: base for arm in ARMS}
    arms = {ARMS[0]: {"status": "BASELINE_REUSED", "actualConfiguration": ARMS[0],
                     "componentTrial": False, "summary": compact(base)}}
    metadata = {"frozenMechanics": verify_frozen_mechanics(), "paReload": None, "durationInputs": None}
    try:
        engine = CurrentV18Engine()
        provider, reload = shared_provider(engine, bundle)
        metadata["paReload"] = reload
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        for arm in ARMS[1:]:
            arms[arm] = fallback(base, "SHARED_PA_INPUT_UNSUPPORTED: " + str(exc))
        return populations, arms, metadata
    kwargs = {"game_id": forecast["gameId"], "provider": provider, "n_sims": 5000,
              "master_seed": daily.MASTER_SEED, "regulation": int(snapshot["game"].get("scheduled_innings") or 9),
              "trace_count": 0, "deadline_utc": deadline}
    # Each named component has an independent support/fallback boundary.
    for arm in ARMS[1:]:
        try:
            if now() >= deadline:
                raise ValueError("BOUNDED_EXECUTION_RESOURCE_DEADLINE_REACHED")
            if arm == ARMS[1]:
                duration = build_current_duration_inputs(snapshot, as_of_utc=snapshot["capturedAt"])
                metadata["durationInputs"] = duration
                if duration["status"] != "SUPPORTED":
                    raise ValueError("DURATION_HISTORY_UNSUPPORTED: " + json.dumps(duration["missingReasons"], sort_keys=True))
                if ref(declaration["components"][arm]["path"]) != declaration["components"][arm]:
                    raise ValueError("DECLARED_SURVIVAL_ARTIFACT_CHANGED")
                model, identity = load_duration_model()
                lookup, inference = _duration_lookup(model, duration["home"], duration["away"])
                population = simulate_research_arm(**kwargs, transition_model=engine.transition, arm=CHALLENGER, duration_lookup=lookup)
                detail = {"configuration": arm, "component": declaration["components"][arm], "durationInference": inference}
            else:
                payload = read(declaration["components"][arm])
                component = HierarchicalTransitionModel.from_dict(payload)
                if component.prior_strength != 20.0 or component.legal_floor != 1e-6 or component.seasons != (2023, 2024, 2025):
                    raise ValueError("DECLARED_TRANSITION_CONFIGURATION_CHANGED")
                population = simulate_research_arm(**kwargs, transition_model=component, arm=REFERENCE)
                detail = {"configuration": arm, "component": declaration["components"][arm]}
            if len(population["homeRuns"]) != 5000 or population["illegalStateCount"] or population["nonterminationCount"]:
                raise ValueError("INVALID_COMPONENT_POPULATION")
            populations[arm], arms[arm] = population, applied(population, detail)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            populations[arm], arms[arm] = base, fallback(base, f"{type(exc).__name__}: {exc}")
    return populations, arms, metadata


def retain(bundle, game, declaration_ref, declaration, populations, arms, metadata, begun, output=OUT):
    if now() >= utc(game["deadlineUtc"]):
        raise ValueError("COMPARISON_PERSISTENCE_DEADLINE_CLOSED")
    arrays = {f"{arm}_{field}": np.asarray(populations[arm][field], dtype="<i8") for arm in ARMS for field in FIELDS}
    if any(a.shape != (5000,) or (a < 0).any() for a in arrays.values()):
        raise ValueError("RETAINED_POPULATION_SHAPE_OR_RANGE_DIFFERS")
    for arm in ARMS[1:]:
        if arms[arm]["status"] == "BASELINE_FALLBACK" and any(
                not np.array_equal(arrays[f"{arm}_{field}"], arrays[f"{ARMS[0]}_{field}"]) for field in FIELDS):
            raise ValueError("FALLBACK_IS_NOT_IDENTICAL_BASELINE")
    # Retain component exposure arrays when present; never invent baseline BF.
    for arm in ARMS:
        for field in ("homeStarterBf", "awayStarterBf", "homeStarterOuts", "awayStarterOuts", "homeRelieverBf", "awayRelieverBf"):
            if field in populations[arm]:
                arrays[f"{arm}_{field}"] = np.asarray(populations[arm][field], dtype="<i8")
    stream = io.BytesIO(); np.savez_compressed(stream, **arrays)
    population_ref = put("three-arm-populations.npz", stream.getvalue(), output)
    forecast = bundle["forecast"]
    result = {"schemaVersion": SCHEMA + "_RESULT", "declaration": declaration_ref,
        "gameId": game["gameId"], "sourceGameId": game["sourceGameId"], "teams": forecast["teams"],
        "slateDate": declaration["slateDate"], "sourceForecastObjectSha256": bundle["objectSha256"],
        "baselineForecastId": "mlb-v18-daily-" + bundle["objectSha256"],
        "baselineForecast": ref(bundle["directory"] / "forecast.json"), "baselineManifest": bundle["manifest"],
        "pregameEvidence": ref(bundle["directory"] / "pregame-evidence.json"),
        "executionInputs": ref(bundle["directory"] / "execution-inputs.json"), "featureSnapshot": bundle["execution"]["featureSnapshot"],
        "sourceCutoff": forecast["sourceCutoff"], "baselineForecastCreatedAtUtc": forecast["forecastCreatedAt"],
        "scheduledStartUtc": game["scheduledStartUtc"], "deadlineUtc": game["deadlineUtc"],
        "executionStartedAtUtc": begun.isoformat(), "frozenAtUtc": now().isoformat(),
        "classification": "PROSPECTIVE_PREGAME_RESEARCH_LOCAL_FREEZE", "publicationStatus": "NOT_EXPORTED",
        "simulationCountPerConfiguration": 5000, "masterSeed": daily.MASTER_SEED, "population": population_ref,
        "arms": arms, "commonSupported": all(arms[a]["status"] == "APPLIED" for a in ARMS[1:]),
        "pairedMonteCarloCoupling": "Same immutable game ID, master seed, PA/TRANSITION/HOOK SeedSequence child streams, fixed draw index by PA step; diverging paths are retained.",
        "baselineReproduction": "Original compatible draw arrays reused byte-for-value; no baseline replay. Frozen simulator source checksum and shared initial PA probabilities verified.",
        "metadata": metadata, "driver": ref(__file__), "outcomeRead": False, **FLAGS}
    descriptor = put("three-arm-result.json", result, output)
    if now() >= utc(game["deadlineUtc"]):
        raise ValueError("COMPARISON_RECORD_PERSISTED_AFTER_DEADLINE")
    atomic_state(state_root(output, declaration_ref) / "frozen" / (game["gameId"] + ".json"), descriptor)
    return descriptor


def run(declaration_ref, declaration, max_games=1, wall_seconds=600, output=OUT):
    if not 1 <= max_games <= len(declaration["games"]) or not 30 <= wall_seconds <= 1200:
        raise ValueError("BOUNDED_RUN_REQUIRES_1_TO_DECLARED_GAMES_AND_30_TO_1200_SECONDS")
    begun, completed = now(), []
    wall_deadline = begun + timedelta(seconds=wall_seconds)
    with single_owner(PRODUCER_LOCK) as owned:
        if not owned:
            return {"status": "DEFERRED_ORDINARY_PUBLISHER_LOCK_BUSY", "newSimulations": 0, **FLAGS}
        status = plan(declaration_ref, declaration, output)
        for row in status["records"]:
            if len(completed) >= max_games or now() >= wall_deadline:
                break
            if row["status"] != "BASELINE_OBJECT_AVAILABLE":
                continue
            bundle = load_baseline(row["baselineObjectSha256"])
            verify_member(bundle, row, declaration, now())
            attempt = state_root(output, declaration_ref) / "attempts" / (row["gameId"] + ".json")
            attempt.parent.mkdir(parents=True, exist_ok=True)
            with attempt.open("x", encoding="utf-8") as stream:
                json.dump({"startedAtUtc": now().isoformat(), "declaration": declaration_ref,
                           "baselineObjectSha256": bundle["objectSha256"], "numericalAttemptLimit": 1}, stream)
            game_begun = now()
            try:
                with threadpool_limits(limits=4):
                    populations, arms, metadata = execute_game(bundle, row, declaration, min(wall_deadline, utc(row["deadlineUtc"])))
                result = retain(bundle, row, declaration_ref, declaration, populations, arms, metadata, game_begun, output)
                completed.append(result)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                failure = put("blocked-attempt.json", {"gameId": row["gameId"], "sourceForecastObjectSha256": bundle["objectSha256"],
                    "blockedAtUtc": now().isoformat(), "reason": f"{type(exc).__name__}: {exc}", "prospectiveForecastFrozen": False, **FLAGS}, output)
                atomic_state(state_root(output, declaration_ref) / "blocked" / (row["gameId"] + ".json"), failure)
                completed.append(failure)
    status = plan(declaration_ref, declaration, output)
    status["thisRunResults"] = completed
    descriptor = put("status.json", status, output)
    atomic_state(output / "current.json", descriptor)
    return {"status": descriptor, "counts": status["counts"]}


def self_check():
    # Focused new boundary checks; no model load, provider call or simulation.
    clock = utc("2026-09-12T20:00:00Z")
    def row(game_id, source_id, start="2026-09-12T22:00:00Z", status="Pre-Game"):
        return {"gameId": game_id, "mlbamGamePk": source_id, "gameDate": "2026-09-12", "scheduledStartUtc": start,
                "status": status, "canonicalIdentityResolved": True, "homeTeamMlbamId": 111, "awayTeamMlbamId": 118,
                "localSchedule": {"game_id": game_id, "source_game_id": str(source_id), "starts_at": start,
                                  "status": "SCHEDULED", "home_mlbam_id": "111", "away_mlbam_id": "118"}}
    mismatch = row("mismatch", 824718); mismatch["teamIdentityMismatch"] = True
    slate = {"discovery": {"games": [row("future", 824712), row("expired", 824713, "2026-09-12T20:00:00Z"),
        row("protected", 823343), row("live", 824716, status="In Progress"), mismatch]}}
    selected, excluded = select_members(slate, "2026-09-12", clock)
    assert [r["gameId"] for r in selected] == ["future"] and len(excluded) == 4
    assert selected[0]["deadlineUtc"] == "2026-09-12T21:45:00+00:00"
    b = {"homeRuns": np.array([1, 2]), "awayRuns": np.array([0, 3]), "illegalStateCount": 0, "nonterminationCount": 0}
    f = fallback(b, "MISSING_HISTORY")
    t = applied(b, {"configuration": ARMS[2]})
    assert f["componentTrial"] is False and f["actualConfiguration"] == ARMS[0]
    assert t["componentTrial"] is True and t["actualConfiguration"] == ARMS[2]
    assert list(ARMS) == ["V18_BASE", "V18_SURVIVAL_ONLY", "V18_TRANSITION_ONLY"]
    return {"status": "PASS", "checks": ["quarantine_before_membership", "expired_opportunities_excluded", "15_minute_cutoff", "live_status_rejected_despite_future_time", "team_mismatch_rejected", "independent_supported_and_fallback_arms", "exact_three_configurations"], "newSimulations": 0, "modelLoads": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    declare_parser = sub.add_parser("declare")
    declare_parser.add_argument("--slate-receipt", type=Path, required=True)
    declare_parser.add_argument("--slate-date", required=True)
    for command in ("plan", "run"):
        p = sub.add_parser(command)
        p.add_argument("--declaration", type=Path, default=OUT / "declaration-current.json")
        if command == "run":
            p.add_argument("--max-games", type=int, default=1)
            p.add_argument("--wall-seconds", type=int, default=600)
    sub.add_parser("self-check")
    args = parser.parse_args()
    if args.command == "declare": result = declare(args.slate_receipt, args.slate_date)
    elif args.command == "self-check": result = self_check()
    else:
        descriptor, declared = load_declaration(args.declaration)
        result = plan(descriptor, declared) if args.command == "plan" else run(descriptor, declared, args.max_games, args.wall_seconds)
    print(json.dumps(daily.json_safe(result), indent=2, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
