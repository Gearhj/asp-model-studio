"""Separate, deadline-bound research publication; reads the live producer only.

This module never collects source data, fits a model, or writes AISP. A complete
existing V18 current-input object and certified duration inputs are mandatory.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from . import mlb_v18_daily_slate as daily
from .mlb_v18_current_publication import CurrentV18Engine, OUTPUT as LIVE, _validate_eligible_inputs, _verified_forecast, current_template
from .mlb_v18_current_slate import ROOT, reference, utc, write_object
from .mlb_v18_prospective_transform import ProspectiveFrameAuthority, wrap_prospective_pipeline
from .mlb_v18_whole_game_challenger import V18StateProbabilityProvider
from .mlb_v18_unattended import atomic_state, single_owner

OUTPUT = ROOT / "outputs/mlb-starter-duration-paired-research-v1"
SCHEMA = "MLB_STARTER_DURATION_PAIRED_RESEARCH_V1"
FLAGS = {"researchShadowOnly": True, "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
         "wageringAuthority": False, "executionAllowedInAISP": False}
RESULT = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/duration-study/objects/sha256/af2e6aca3f83a2e4312b555502b2cf598d0939941f7473c03226318d30f6ff84/duration-results.json"
DECLARED_HGB_SHA = "f64f82b4fadf35acd3418bc298548c48bb73cf624fe8c70ba01a87c33e8d2370"
READINESS_COOLDOWN_SECONDS = 300


def verified(ref):
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("MODEL_STUDIO_ARTIFACT_PATH_REQUIRED")
    if reference(path) != {k: ref[k] for k in ("path", "sha256", "bytes")}:
        raise ValueError("RESEARCH_ARTIFACT_CHECKSUM_MISMATCH")
    return path


def read(ref):
    return json.loads(verified(ref).read_text(encoding="utf-8"))


def save(name, value, root=OUTPUT):
    return write_object(root, name, daily.json_safe(value))[0]


def verify_published_pointer(pointer, expected_game_id=None):
    pair, receipt = read(pointer["pair"]), read(pointer["publicationReceipt"])
    population = read(pair["population"])
    inputs, declaration = read(pair["inputs"]), read(pair["declaration"])
    game = next((g for g in declaration["games"] if g["gameId"] == pair["gameId"]), None)
    if (not game or (expected_game_id and pair["gameId"] != expected_game_id)
            or pair["schemaVersion"] != SCHEMA or receipt["pair"] != pointer["pair"]
            or receipt["population"] != pair["population"] or pair["gameId"] != receipt["gameId"]
            or population["gameId"] != pair["gameId"] or inputs["gameId"] != pair["gameId"]
            or utc(pair["scheduledStartUtc"]) != utc(game["scheduledStartUtc"])
            or utc(pair["deadlineUtc"]) != utc(game["deadlineUtc"])
            or utc(receipt["deadlineUtc"]) != utc(game["deadlineUtc"])
            or not utc(pair["forecastCreatedAt"]) <= utc(pair["frozenAt"]) <= utc(receipt["publishedAt"]) < utc(pair["deadlineUtc"])):
        raise ValueError("PAIR_PUBLICATION_TIMING_OR_LINEAGE_INVALID")
    for key in ("reference", "challenger"):
        arm = population[key]
        if len(arm["homeRuns"]) != declaration["simulationsPerArm"] or len(arm["awayRuns"]) != declaration["simulationsPerArm"]:
            raise ValueError("PAIR_POPULATION_COUNT_MISMATCH")
    if any(pair.get(key) != value for key, value in FLAGS.items()):
        raise ValueError("PAIR_RESEARCH_AUTHORITY_MISMATCH")
    return pair, receipt


def now():
    return datetime.now(timezone.utc)


def require_deadline(game, current=None):
    current = current or now()
    deadline, start = utc(game["deadlineUtc"]), utc(game["scheduledStartUtc"])
    if deadline != start - timedelta(minutes=5):
        raise ValueError("DECLARED_DEADLINE_DOES_NOT_MATCH_START")
    if current >= deadline:
        raise ValueError("PREGAME_DEADLINE_CLOSED_NO_BACKFILL")


def participant_identity(snapshot):
    return {s["side"]: {"teamId": s["team"]["uuid"], "starterMlbamId": str(s["starter"].get("mlbamId")),
            "lineup": [str(p["mlbam"]) for p in s["lineup"]]} for s in snapshot["sides"]}


def declare(snapshot_collection, capture_ref, *, root=OUTPUT):
    """Freeze one date/identity slate, not an outcome-selected sample."""
    games = []
    for snapshot in snapshot_collection["snapshots"]:
        start = utc(snapshot["game"]["starts_at"])
        games.append({"gameId": snapshot["game"]["game_id"], "sourceGameId": snapshot["game"].get("source_game_id"),
            "scheduledStartUtc": start.isoformat(), "deadlineUtc": (start-timedelta(minutes=5)).isoformat(),
            "teams": {s["side"]: s["team"] for s in snapshot["sides"]}})
    if not games or len(games) > 15:
        raise ValueError("PILOT_REQUIRES_ONE_BOUNDED_SLATE_OF_AT_MOST_15_GAMES")
    declaration = {"schemaVersion": SCHEMA+"_DECLARATION", "declaredAt": now().isoformat(), "initialCapture": capture_ref,
        "games": sorted(games, key=lambda g: (g["scheduledStartUtc"], g["gameId"])),
        "reference": "FROZEN_V18_EXISTING_HOOK", "challenger": "SAME_V18_SELECTED_FROZEN_HGB_REMOVAL_ONLY",
        "hgbArtifactSha256": DECLARED_HGB_SHA, "previousSelectionEvidence": reference(RESULT),
        "simulationsPerArm": daily.SIMULATION_COUNT, "masterSeed": daily.MASTER_SEED,
        "mechanicsDrawsPerArm": 64, "mechanicsRepeats": 2, "maxInferenceAttemptsPerGame": 1,
        "maxTickWallSeconds": 1200, "nativeWorkers": 4, "successfulPairLimitPerGame": 1,
        "eligibleInputChoice": "FIRST_COMPLETE_VERIFIED_CURRENT_PRODUCER_INPUT_AND_CERTIFIED_START_HISTORY_BEFORE_DEADLINE",
        "unchangedSharedComponents": ["V18_PA_FOLD5", "TRANSITION_FOLD4", "CALIBRATION", "ORDERED_CONFIRMED_LINEUPS", "ANONYMOUS_RELIEF_STAFF_MIXTURE", "SCORING_RULES"],
        "sourceCollectors": 0, "modelFits": 0, "historicalPARepairRequiredForThisProspectiveComparison": False,
        "finalsScoring": "SAVED_PAIRS_ONLY_LATEST_PERSISTED_FINAL_REVISION_ONE_GAME_PER_PAIR",
        "stopSwitch": str(Path(root)/"STOP"), "automaticNumericalRetries": 0, **FLAGS}
    return save("declaration.json", declaration, root)


def load_duration_model(*, before_inference=None):
    if reference(RESULT)["sha256"] != RESULT.parent.name:
        raise ValueError("ORIGINAL_DURATION_RESULT_CHANGED")
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    item = next(m for m in result["models"] if m["model"] == "HGB_PREGAME")
    if item["artifact"]["sha256"] != DECLARED_HGB_SHA:
        raise ValueError("SELECTED_HGB_IDENTITY_CHANGED")
    model = joblib.load(verified(item["artifact"]))
    fixture = pd.read_parquet(verified(item["fixture"]))
    expected = pd.read_parquet(verified(item["expected"])).to_numpy()
    if before_inference is not None:
        before_inference()
    actual = model.predict_proba(fixture)
    if not np.array_equal(expected, actual):
        raise ValueError("SELECTED_HGB_RELOAD_MISMATCH")
    return model, {**item, "actualReload": {"rows": len(fixture), "probabilities": actual.size, "mismatches": 0, "fits": 0}}


def build_provider(engine, snapshot, composition, feature_ref, execution):
    _validate_eligible_inputs(snapshot, composition)
    feature = read(feature_ref)
    if feature["composition"] != composition or not composition["canSimulate"] or composition["blockers"]:
        raise ValueError("VERIFIED_COMPLETE_V18_COMPOSITION_REQUIRED")
    raw = pd.DataFrame(composition["rows"], columns=engine.contract["rawFeatureColumns"])
    auth = ProspectiveFrameAuthority(event_id=snapshot["game"]["game_id"], game_date=str(raw.game_date.iloc[0])[:10],
        evidence_cutoff_utc=snapshot["capturedAt"], kickoff_utc=snapshot["game"]["starts_at"],
        snapshot_sha256=feature_ref["sha256"], authorized_at_utc=now().isoformat(),
        venue_timezone=composition.get("venueTimezone") or composition["event"]["venueTimezone"])
    pipeline = wrap_prospective_pipeline(engine.pipeline, auth)
    actual = np.concatenate([pipeline.predict_proba(raw.iloc[[i]]) for i in range(len(raw))])
    expected = np.asarray(execution["initialPaProbabilities"])
    if not np.array_equal(actual, expected) or actual.shape != (len(raw), 8):
        raise ValueError("FROZEN_V18_CURRENT_INITIAL_INFERENCE_RELOAD_MISMATCH")
    inputs = execution["providerInputs"]
    if inputs != composition["providerInputs"]:
        raise ValueError("PROVIDER_INPUT_COMPOSITION_MISMATCH")
    provider = V18StateProbabilityProvider(pipeline, away_batters=inputs["awayBatters"], home_batters=inputs["homeBatters"],
        away_starter=inputs["awayStarter"], home_starter=inputs["homeStarter"], away_bullpen=inputs["awayBullpen"],
        home_bullpen=inputs["homeBullpen"], temperature=None, template_composer=current_template)
    return provider, {"rows": len(raw), "rawFeatures": 246, "treatedFeatures": 273, "classes": 8, "mismatches": 0, "fits": 0}


def production_busy():
    """Probe/release the producer lock without changing its bytes or ownership."""
    import msvcrt
    lock = ROOT / ".runtime/mlb-v18-unattended/producer.lock"
    if not lock.exists():
        return False
    try:
        with lock.open("r+b") as handle:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except PermissionError:
        return True
    return False


def find_producer_objects(declaration):
    selected = {}
    ids = {g["gameId"] for g in declaration["games"]}
    for path in (LIVE / "objects/sha256").glob("*/forecast.json"):
        forecast = json.loads(path.read_text(encoding="utf-8"))
        if forecast.get("gameId") not in ids:
            continue
        manifest = json.loads(path.with_name("manifest.json").read_text(encoding="utf-8"))
        pointer = {"relativePath": path.parent.relative_to(LIVE).as_posix(), "objectSha256": manifest["objectSha256"]}
        directory, forecast = _verified_forecast(LIVE, pointer)
        event = forecast["gameId"]
        if event not in selected or utc(forecast["forecastCreatedAt"]) > utc(selected[event][1]["forecastCreatedAt"]):
            selected[event] = (directory, forecast, pointer)
    return selected


def publish_pair(game, current, producer, duration_inputs, declaration_ref, *, root=OUTPUT, tick_deadline_utc=None):
    from .mlb_starter_duration_paired_simulation import simulate_paired_game
    declaration = read(declaration_ref)
    require_deadline(game)
    directory, old_forecast, pointer = producer
    snapshot = json.loads((directory/"pregame-evidence.json").read_text(encoding="utf-8"))
    execution = json.loads((directory/"execution-inputs.json").read_text(encoding="utf-8"))
    if (participant_identity(snapshot) != participant_identity(current)
            or utc(current["game"]["starts_at"]) != utc(game["scheduledStartUtc"])
            or utc(snapshot["game"]["starts_at"]) != utc(game["scheduledStartUtc"])):
        raise ValueError("CURRENT_PARTICIPANTS_OR_START_DIFFER_FROM_COMPLETE_PRODUCER_INPUT")
    if duration_inputs["status"] != "SUPPORTED":
        raise ValueError("CERTIFIED_CURRENT_DURATION_INPUTS_REQUIRED")
    feature_ref = execution["featureSnapshot"]
    composition = read(feature_ref)["composition"]
    input_ref = save("paired-inputs.json", {"schemaVersion": SCHEMA+"_INPUTS", "gameId": game["gameId"],
        "v18SourceObject": pointer, "featureSnapshot": feature_ref, "pregameEvidence": snapshot,
        "currentIdentityCapture": current, "durationInputs": duration_inputs,
        "sourceCutoff": old_forecast["sourceCutoff"], "capturedAt": current["capturedAt"],
        "originalForecastCreatedAt": old_forecast["forecastCreatedAt"], **FLAGS}, root)
    pair_key = daily.sha_json({"declaration": declaration_ref["sha256"], "gameId": game["gameId"], "inputSha256": input_ref["sha256"]})
    execution_deadline = min(utc(game["deadlineUtc"]), utc(tick_deadline_utc)) if tick_deadline_utc else utc(game["deadlineUtc"])

    def reserve_numerical_attempt():
        # The callback runs after model/fixture authentication, immediately
        # before the first actual predict_proba. Readiness/preflight failures
        # therefore never consume the one permitted numerical attempt.
        require_deadline(game)
        if now() >= execution_deadline:
            raise ValueError("BOUNDED_TICK_RESOURCE_DEADLINE_REACHED")
        if production_busy():
            raise ValueError("DEFERRED_PRODUCTION_PUBLISHER_PRIORITY")
        attempt = Path(root)/"attempts"/(game["gameId"]+".json")
        attempt.parent.mkdir(parents=True, exist_ok=True)
        try:
            with attempt.open("x", encoding="utf-8") as handle:
                json.dump({"gameId": game["gameId"], "startedAt": now().isoformat(), "declaration": declaration_ref,
                    "firstNumericalOperation": "FROZEN_HGB_RELOAD_PREDICT_PROBA", "inputSha256": input_ref["sha256"]}, handle)
        except FileExistsError as exc:
            raise ValueError("DECLARED_INFERENCE_ATTEMPT_LIMIT_REACHED") from exc

    with threadpool_limits(limits=declaration["nativeWorkers"]):
        duration_model, duration_identity = load_duration_model(before_inference=reserve_numerical_attempt)
        engine = CurrentV18Engine()
        provider, pa_reload = build_provider(engine, snapshot, composition, feature_ref, execution)
        kwargs = dict(game_id=game["gameId"], provider=provider, transition_model=engine.transition, duration_model=duration_model,
            home_duration_inputs=duration_inputs["home"], away_duration_inputs=duration_inputs["away"],
            master_seed=declaration["masterSeed"], regulation=int(snapshot["game"].get("scheduled_innings") or 9),
            trace_count=1, deadline_utc=execution_deadline.isoformat())
        first = simulate_paired_game(**kwargs, n_sims=declaration["mechanicsDrawsPerArm"])
        repeated = simulate_paired_game(**kwargs, n_sims=declaration["mechanicsDrawsPerArm"])
        for arm in ("reference", "challenger"):
            for field in ("homeRuns", "awayRuns", "innings", "paCounts"):
                if not np.array_equal(first[arm][field], repeated[arm][field]):
                    raise ValueError("WITHIN_ARM_MECHANICS_REPRODUCTION_MISMATCH")
        require_deadline(game)
        run_started = now()
        population = simulate_paired_game(**kwargs, n_sims=declaration["simulationsPerArm"])
        run_completed = now()
        for field in ("homeRuns", "awayRuns", "innings", "paCounts"):
            if not np.array_equal(population["reference"][field], execution["population"][field]):
                raise ValueError("EXISTING_PRODUCER_REFERENCE_POPULATION_CHANGED")
    require_deadline(game)
    population_ref = save("paired-populations.json", population, root)
    from .mlb_starter_duration_paired_simulation import __file__ as simulation_path
    pair = {"schemaVersion": SCHEMA, "commonPairId": "mlb-duration-pair-"+pair_key[:24], "gameId": game["gameId"],
        "teams": game["teams"], "sourceGameId": game["sourceGameId"], "scheduledStartUtc": game["scheduledStartUtc"],
        "deadlineUtc": game["deadlineUtc"], "declaration": declaration_ref, "inputs": input_ref,
        "sourceCutoff": old_forecast["sourceCutoff"], "evidenceAvailableAt": duration_inputs.get("evidenceCutoff"),
        "inputCapturedAt": current["capturedAt"], "forecastStartedAt": run_started.isoformat(),
        "forecastCreatedAt": run_completed.isoformat(), "frozenAt": now().isoformat(),
        "arms": {"reference": "FROZEN_V18_EXISTING_HOOK", "challenger": "FROZEN_V18_SELECTED_HGB_HOOK"},
        "population": population_ref, "modelIdentity": engine.model_identity, "durationModel": duration_identity,
        "masterSeed": declaration["masterSeed"], "simulationsPerArm": declaration["simulationsPerArm"],
        "verification": {"paReload": pa_reload, "mechanicsRepeatability": True, "referenceMatchesExisting5000Exactly": True},
        "executionResourceDeadlineUtc": execution_deadline.isoformat(),
        "implementation": reference(simulation_path),
        "limitations": ["Anonymous relief-staff mixture is shared, not observed bullpen availability", "Frozen V18 historical validation hold is not certified by this prospective experiment", "No named reliever substitutions or bench model", "BF-only component law differs from this full-game rollout"],
        "evaluationStatus": "AWAITING_PERSISTED_FINAL", "modelFits": 0, "providerCalls": 0, **FLAGS}
    pair_ref = save("paired-forecast.json", pair, root)
    # A pair does not become discoverable unless both artifacts are frozen in time.
    require_deadline(game)
    saved = now().isoformat()
    receipt = save("pair-publication-receipt.json", {"pair": pair_ref, "population": population_ref,
        "gameId": game["gameId"], "publishedAt": saved, "deadlineUtc": game["deadlineUtc"], **FLAGS}, root)
    require_deadline(game)
    atomic_state(Path(root)/"published"/(game["gameId"]+".json"), {"pair": pair_ref, "publicationReceipt": receipt})
    return {"gameId": game["gameId"], "status": "PAIRED_FORECAST_PUBLISHED", "pair": pair_ref, "publicationReceipt": receipt}


def _unique_reasons(reasons):
    """Keep structured per-player explanations, deduplicating by JSON content."""
    result, seen = [], set()
    for reason in reasons:
        identity = daily.sha_json(reason)
        if identity not in seen:
            seen.add(identity)
            result.append(reason)
    return result


def _pending(game, reasons, *, checked_at, **evidence):
    return {"gameId": game["gameId"], "status": "PENDING_INPUTS", "terminal": False,
        "scheduledStartUtc": game["scheduledStartUtc"], "deadlineUtc": game["deadlineUtc"],
        "checkedAt": checked_at.isoformat(), "nextCheckUtc": min(checked_at+timedelta(seconds=READINESS_COOLDOWN_SECONDS), utc(game["deadlineUtc"])).isoformat(),
        "reasons": _unique_reasons(reasons), "numericalAttemptConsumed": False, **evidence}


def _terminal(game, reason, *, checked_at, numerical_attempt=False, **evidence):
    return {"gameId": game["gameId"], "status": "TERMINAL_SKIPPED", "terminal": True,
        "scheduledStartUtc": game["scheduledStartUtc"], "deadlineUtc": game["deadlineUtc"],
        "checkedAt": checked_at.isoformat(), "nextCheckUtc": None, "reasons": [reason],
        "numericalAttemptConsumed": numerical_attempt, **evidence}


def tick(declaration_ref, *, root=OUTPUT):
    from scripts.inventory_mlb_current_slate import capture_current_slate
    from .mlb_starter_duration_current_inputs import build_current_duration_inputs
    root = Path(root)
    with single_owner(root/"research.lock") as owns:
        if not owns:
            return {"status": "RESEARCH_EXECUTION_ALREADY_ACTIVE"}
        if (root/"STOP").exists():
            return {"status": "STOP_SWITCH_ACTIVE"}
        declaration = read(declaration_ref)
        tick_started = now()
        tick_deadline = tick_started+timedelta(seconds=declaration["maxTickWallSeconds"])
        state_path = root/"readiness-state.json"
        previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        previous_rows = previous.get("games", {}) if previous.get("declarationSha256") == declaration_ref["sha256"] else {}
        rows, due = {}, []
        for game in sorted(declaration["games"], key=lambda g: (g["deadlineUtc"], g["gameId"])):
            event = game["gameId"]
            pointer = root/"published"/(event+".json")
            if pointer.exists():
                saved = json.loads(pointer.read_text(encoding="utf-8"))
                verify_published_pointer(saved, expected_game_id=event)
                rows[event] = {"gameId": event, "status": "EXACT_PAIR_REUSED", **saved}
                continue
            if tick_started >= utc(game["deadlineUtc"]):
                rows[event] = _terminal(game, "PREGAME_DEADLINE_CLOSED_NO_BACKFILL", checked_at=tick_started,
                    numerical_attempt=(root/"attempts"/(event+".json")).exists())
            elif (root/"attempts"/(event+".json")).exists():
                rows[event] = _terminal(game, "DECLARED_INFERENCE_ATTEMPT_LIMIT_REACHED", checked_at=tick_started, numerical_attempt=True)
            elif previous_rows.get(event, {}).get("nextCheckUtc") and utc(previous_rows[event]["nextCheckUtc"]) > tick_started:
                # Keep the actual earlier check and evidence clocks. A new
                # dispatcher receipt is not a new source observation.
                rows[event] = {**previous_rows[event], "cooldownActive": True}
            else:
                due.append(game)
        capture, collection, snapshots, inventory_rows, producers = None, None, {}, {}, {}
        if due and production_busy():
            for game in due:
                rows[game["gameId"]] = _pending(game, ["DEFERRED_PRODUCTION_PUBLISHER_PRIORITY"], checked_at=now())
            due = []
        if due:
            day = utc(due[0]["scheduledStartUtc"]).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date().isoformat()
            try:
                inventory, capture = capture_current_slate(output_root=root/"inventory", slate_date=day,
                    game_ids=[g["gameId"] for g in due])
                collection = json.loads(Path(capture["snapshotsPath"]).read_text(encoding="utf-8"))
                snapshots = {s["game"]["game_id"]: s for s in collection["snapshots"]}
                inventory_rows = {g["game"]["game_id"]: g for g in inventory["games"]}
                producers = find_producer_objects(declaration)
            except Exception as exc:
                for game in due:
                    rows[game["gameId"]] = (_terminal(game, "PREGAME_DEADLINE_CLOSED_NO_BACKFILL", checked_at=now())
                        if now() >= utc(game["deadlineUtc"]) else _pending(game, [str(exc)], checked_at=now(), errorType=type(exc).__name__))
                due = []
        for game in due:
            event = game["gameId"]
            row = _pending(game, [], checked_at=now())
            try:
                require_deadline(game)
                if now() >= tick_deadline or (root/"STOP").exists():
                    raise ValueError("BOUNDED_TICK_STOP_OR_RESOURCE_LIMIT")
                if event not in snapshots:
                    raise ValueError("CURRENT_SCHEDULE_OR_SNAPSHOT_UNAVAILABLE")
                snapshot = snapshots[event]
                inputs = build_current_duration_inputs(snapshot, as_of_utc=collection["capturedAt"])
                row["durationInputEvidence"] = save("duration-input-readiness.json", inputs, root)
                reasons = list(inventory_rows.get(event, {}).get("currentParticipantGateReasons") or [])
                if inputs["status"] != "SUPPORTED":
                    reasons += list(inputs.get("missingReasons") or ["CERTIFIED_START_HISTORY_UNAVAILABLE"])
                if event not in producers:
                    reasons.append("COMPLETE_CURRENT_V18_PRODUCER_OBJECT_UNAVAILABLE")
                if reasons:
                    row["reasons"] = _unique_reasons(reasons)
                else:
                    if production_busy():
                        raise ValueError("DEFERRED_PRODUCTION_PUBLISHER_PRIORITY")
                    if (root/"attempts"/(event+".json")).exists():
                        raise ValueError("DECLARED_INFERENCE_ATTEMPT_LIMIT_REACHED")
                    row = publish_pair(game, snapshot, producers[event], inputs, declaration_ref,
                        root=root, tick_deadline_utc=tick_deadline.isoformat())
            except Exception as exc:
                attempt_used = (root/"attempts"/(event+".json")).exists()
                evidence = {k: row[k] for k in ("durationInputEvidence",) if k in row}
                evidence["errorType"] = type(exc).__name__
                if now() >= utc(game["deadlineUtc"]) or attempt_used:
                    row = _terminal(game, "PREGAME_DEADLINE_CLOSED_NO_BACKFILL" if now() >= utc(game["deadlineUtc"]) else str(exc),
                        checked_at=now(), numerical_attempt=attempt_used, **evidence)
                else:
                    row = _pending(game, [str(exc)], checked_at=now(), **evidence)
            rows[event] = row
        for game in declaration["games"]:
            event = game["gameId"]
            if rows[event].get("status") == "PENDING_INPUTS" and now() >= utc(game["deadlineUtc"]):
                rows[event] = _terminal(game, "PREGAME_DEADLINE_CLOSED_NO_BACKFILL", checked_at=now())
        row_list = [rows[g["gameId"]] for g in sorted(declaration["games"], key=lambda g: (g["deadlineUtc"], g["gameId"]))]
        pending = [r for r in row_list if r.get("status") == "PENDING_INPUTS"]
        next_check = min((r["nextCheckUtc"] for r in pending), default=None)
        handoff = {"schemaVersion": SCHEMA+"_HANDOFF", "generatedAt": now().isoformat(), "declaration": declaration_ref,
            "currentCapture": capture, "games": row_list, "pairCount": sum("pair" in r for r in row_list),
            "pendingCount": len(pending), "terminalSkippedCount": sum(r.get("terminal", False) for r in row_list),
            "skippedCount": sum(r.get("terminal", False) for r in row_list), "nextCheckUtc": next_check,
            "readinessPolicy": {"schemaVersion": "MLB_DURATION_READINESS_RECHECK_V1", "cooldownSeconds": READINESS_COOLDOWN_SECONDS,
                "readinessChecksConsumeNumericalAttempts": False, "deadlineClosedIsTerminal": True},
            "sourceCalls": 0, "aispWrites": 0, "fits": 0,
            "consumerRules": ["Import precomputed pairs only", "Verify hashes/bytes and both-arm pregame publication receipt", "One matched event per commonPairId", "Do not alter champion, policy, positions or settlements"], **FLAGS}
        ref = save("aisp-paired-handoff.json", handoff, root)
        atomic_state(state_path, {"declarationSha256": declaration_ref["sha256"], "games": rows,
            "lastTickAt": handoff["generatedAt"], "nextCheckUtc": next_check})
        atomic_state(root/"current.json", {"handoff": ref, "pairCount": handoff["pairCount"], "pendingCount": len(pending),
            "terminalSkippedCount": handoff["terminalSkippedCount"], "nextCheckUtc": next_check,
            "generatedAt": handoff["generatedAt"], **FLAGS})
        return {"handoff": ref, "games": row_list, "pairCount": handoff["pairCount"],
            "pendingCount": len(pending), "skippedCount": handoff["skippedCount"],
            "terminalSkippedCount": handoff["terminalSkippedCount"], "nextCheckUtc": next_check}
