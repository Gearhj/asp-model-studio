"""Declare, fit/evaluate, and publish one bounded NFL play-level research design.

Run from Model Studio with its intended virtual environment. No provider,
sealed-2025 partition, AISP persistence, legacy forecast rewrite or policy action
is reachable from this entry point. External exchange writes use the ordinary
supported Windows approval context, never an access-control workaround.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_nfl_m1.labs_simulation import (
    AUTHORITY, FAMILY as LEGACY_FAMILY, PregameClosed, file_record, immutable_json,
    pregame_clock, publish_object, registered_source_availability, utc, verify_object,
)
from server.sports_nfl_m1.play_validation import (
    PopulationAccounting, distribution_summary, historical_game_validation, representative_indices,
)
from server.sports_nfl_m1.play_engine import ENGINE_ID


FAMILY = "nfl-labs-play-level-supplements"
CONTRACT = "NFL_LABS_PLAY_LEVEL_CONTRACT_V1"
ARTIFACT = "NFL_LABS_PLAY_LEVEL_SIMULATION_V1"
ENGINE = ENGINE_ID
SEED = 930947
SCENARIO_IDS = ["BASE", "FASTER_PACE", "SLOWER_PACE", "PASS_HEAVY", "RUN_HEAVY", "AGGRESSIVE_FOURTH", "ELEVATED_TURNOVER"]
REPO = Path(__file__).resolve().parents[1]


def _read_verified(ref: dict[str, Any]) -> dict[str, Any]:
    path = Path(ref["path"])
    if file_record(path) != ref:
        raise ValueError(f"checksum or byte count mismatch: {path}")
    return json.loads(path.read_bytes())


def _assert_validation_compatibility(previous: dict[str, Any], current: dict[str, Any]) -> None:
    """Allow renderer/publication repairs, never a numerical design substitution."""
    for name in ("play_evidence.py", "play_model.py", "play_engine.py", "play_validation.py"):
        key = f"server/sports_nfl_m1/{name}"
        if previous["implementation"][key] != current["implementation"][key]:
            raise ValueError(f"numerical validation reuse cannot change {key}")
    for key in ("modelConfiguration", "scenarioDefinitions", "historicalFixture", "sourcePartitions",
                "trainingSeasons", "validationSeason", "validationModelCutoffExclusive", "finalTrainingSeasons"):
        if previous[key] != current[key]:
            raise ValueError(f"numerical validation reuse cannot change {key}")


def _verify_references(value: Any, verified: set[tuple[str, str, int]]) -> None:
    if isinstance(value, dict):
        if {"path", "sha256", "byteCount"}.issubset(value):
            reference = {key: value[key] for key in ("path", "sha256", "byteCount")}
            identity = (reference["path"], reference["sha256"], reference["byteCount"])
            if identity not in verified:
                if file_record(Path(reference["path"])) != reference:
                    raise ValueError(f"validation reuse checksum or byte count differs: {reference['path']}")
                verified.add(identity)
        for nested in value.values():
            _verify_references(nested, verified)
    elif isinstance(value, list):
        for nested in value:
            _verify_references(nested, verified)


def reuse_validation(output: Path, previous_path: Path, declaration: dict[str, Any], declaration_ref: dict[str, Any],
                     *, clock: Callable[[], datetime]) -> dict[str, Any]:
    previous_ref = file_record(previous_path)
    previous = _read_verified(previous_ref)
    if previous.get("schemaVersion") != "NFL_PLAY_LEVEL_VALIDATION_RECEIPT_V1" or previous.get("impossibleStateCount") != 0:
        raise ValueError("completed zero-impossible-state numerical validation is required for reuse")
    previous_declaration = _read_verified(previous["declaration"])
    _assert_validation_compatibility(previous_declaration, declaration)
    verified: set[tuple[str, str, int]] = set()
    _verify_references(previous, verified)
    for key in ("trainingFitReceipt", "finalFitReceipt"):
        _verify_references(_read_verified(previous[key]), verified)
    destination = output / "runs" / declaration_ref["sha256"] / "validation.json"
    if destination.exists():
        existing = json.loads(destination.read_bytes())
        if (existing.get("declaration") != declaration_ref
                or existing.get("numericalValidationReuse", {}).get("parentValidationReceipt") != previous_ref):
            raise ValueError("existing successor validation refers to another declaration or parent")
        _verify_references(existing, verified)
        return existing
    receipt = {**previous, "declaration": declaration_ref, "actualFitStartsThisInvocation": 0,
               "historicalGameSimulationsThisInvocation": 0, "deterministicReloadGameSimulationsThisInvocation": 0,
               "numericalValidationReuse": {
                   "parentValidationReceipt": previous_ref, "originalDeclaration": previous["declaration"],
                   "recordedAtUtc": utc(clock()).isoformat(),
                   "reason": "RENDERER_AND_PUBLICATION_ONLY_SUCCESSOR_NUMERICAL_MODEL_AND_EVALUATION_UNCHANGED",
                   "protectedImplementation": {key: ref for key, ref in declaration["implementation"].items()
                                               if key.endswith(("play_evidence.py", "play_model.py", "play_engine.py", "play_validation.py"))},
                   "verifiedArtifactCount": len(verified), "fitsOrStatisticalReevaluationsPerformed": 0,
                   "timestampMeaning": "Original completedUtc remains the numerical validation completion, not this reuse receipt creation."}}
    immutable_json(destination, receipt)
    print(f"reused unchanged numerical validation from {previous_ref['sha256']}; zero new fits or evaluations", flush=True)
    return receipt


def _object(root: Path, name: str, body: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return immutable_json(root / "sha256" / digest / name, body)


def _set_pointer(path: Path, body: dict[str, Any]) -> None:
    """Discovery only. Immutable artifacts and predecessor pointers are retained."""
    raw = canonical_json_bytes(body)
    if path.exists() and path.read_bytes() == raw:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def declare(output: Path, bronze: Path, *, draws: int) -> tuple[dict[str, Any], dict[str, Any]]:
    from server.sports_nfl_m1.play_model import MODEL_CONFIG
    from server.sports_nfl_m1.play_engine import SCENARIOS

    if draws != 1000:
        raise ValueError("the predeclared population is exactly 1000; change requires an explicit new declaration")
    pointer = json.loads((bronze / "current.json").read_bytes())
    manifest_path = bronze / pointer["manifestRelativePath"]
    manifest_ref = file_record(manifest_path)
    if manifest_ref["sha256"] != pointer["manifestSha256"]:
        raise ValueError("registered bronze manifest hash differs")
    manifest = json.loads(manifest_path.read_bytes())
    sources = [p for p in manifest["partitions"] if p["familyId"] == "play_by_play" and p.get("season") in range(2018, 2025)]
    if {p["season"] for p in sources} != set(range(2018, 2025)):
        raise ValueError("expected physically separated Development PBP2018--2024 partitions")
    code = {name: file_record(REPO / name) for name in (
        "server/sports_nfl_m1/play_evidence.py", "server/sports_nfl_m1/play_model.py",
        "server/sports_nfl_m1/play_engine.py", "server/sports_nfl_m1/play_geometry.py",
        "server/sports_nfl_m1/play_validation.py", "scripts/publish_nfl_play_level.py")}
    policy_path = REPO / "outputs/nfl-semantic-lab-v1/policy-supplements/sha256/ad3f1e57106f58b76b835cb7cd3912c26d357e05fd85f9495dbccd9367edd6d6/feature-treatment-policy.json"
    declaration = {
        "schemaVersion": "NFL_PLAY_LEVEL_EXECUTION_DECLARATION_V1", **AUTHORITY,
        "engineId": ENGINE, "trainingSeasons": list(range(2018, 2024)), "validationSeason": 2024,
        "validationModelCutoffExclusive": "2024-09-01", "finalTrainingSeasons": list(range(2018, 2025)),
        "sealedOotRead": False, "sourceRegistration": manifest_ref,
        "sourcePartitions": [{"season": p["season"], "fileSha256": p["fileSha256"], "relativePath": p["relativePath"],
                              "retrievedAt": p["retrievedAt"], "license": p["license"], "sourceUrl": p.get("sourceUrl")} for p in sorted(sources, key=lambda p: p["season"])],
        "semanticFeaturePolicyPredecessor": file_record(policy_path), "implementation": code,
        "contractImplementation": file_record(REPO / "shared/contracts" / f"{CONTRACT}.json"),
        "priorExecutionDispositions": [file_record(path) for path in sorted((output / "execution-dispositions").glob("*.json"))],
        "modelConfiguration": MODEL_CONFIG, "scenarioDefinitions": SCENARIOS,
        "configurationAuthority": "Fixed predeclared shrinkage, retention and scenario parameters; not empirically estimated or optimized in this assignment.",
        "historicalFixture": {"selection": "FIRST32_REG2024_GAMES_DATE_THEN_GAME_ID", "games": 32, "drawsPerGame": 200,
                              "modelAndTeamStateFrozenThrough": 2023, "targetOutcomeInputToSimulator": False},
        "currentPublication": {"season": 2026, "week": 1, "expectedEvents": 16, "drawsPerEventScenario": draws,
                               "scenarioIds": SCENARIO_IDS, "populationCount": 112, "requestedPopulationGameSimulations": 112000,
                               "representativesPerPopulation": 6, "representativeReplays": 672, "seed": SEED,
                               "commonSeedsAcrossScenarios": True, "scenarioCombinations": False},
        "fitting": {"designs": 1, "modelFits": 2, "hyperparameterSearch": False, "calibrationFit": False,
                    "frozenM1Refit": False, "driveEngineRefit": False},
        "coldStart": "Declared season-decayed league/offense/defense donor shrinkage; missing teams use the fitted league prior, never a generic median. QB, injury, weather, roster and untimed markets excluded.",
        "timing": "Actual clock before each event/scenario inference, forecast creation and publication. Past-kickoff cases are skipped, never retroactively labeled pregame.",
        "populationIdentity": "Content hash of engine/model artifact/scenario/game identity/evidence cutoff/seeds and exact parent M1 artifact; runtime timestamps do not choose numerical version.",
        "limitations": ["Retrospective chronological Development validation is not prospective source-release validation.",
                        "Historical evidence ends with2024 season; no current2026 roster/QB/injury/weather is implied.",
                        "Single-factor scenarios are sensitivity analysis, not causal or tactical predictions."],
    }
    reference = _object(output / "declarations", "declaration.json", declaration)
    print(f"immutable declaration {reference['path']} {reference['sha256']}", flush=True)
    return declaration, reference


def _fit(plays, source: dict[str, Any], declaration: dict[str, Any], declaration_ref: dict[str, Any], output: Path,
         *, end_season: int, clock: Callable[[], datetime]) -> tuple[Any, dict[str, Any], bool]:
    from server.sports_nfl_m1.play_model import fit_play_model

    fit_key = {"sourceShas": sorted(s["sha256"] for s in source["sources"]), "endSeason": end_season,
               "exclusiveCutoff": "2024-09-01" if end_season == 2023 else None,
               "configuration": declaration["modelConfiguration"],
               "implementation": {key: ref["sha256"] for key, ref in declaration["implementation"].items() if key.endswith(("play_model.py", "play_evidence.py"))}}
    fit_id = hashlib.sha256(canonical_json_bytes(fit_key)).hexdigest()
    fit_root = output / "fits" / fit_id
    receipt_path = fit_root / "fit-receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_bytes())
        if receipt["fitIdentity"] != fit_key or file_record(Path(receipt["modelArtifact"]["path"])) != receipt["modelArtifact"]:
            raise ValueError("saved fit identity/checksum differs")
        return joblib.load(receipt["modelArtifact"]["path"]), receipt, False
    started_path = fit_root / "fit-start.json"
    if started_path.exists():
        raise ValueError(f"incomplete prior fit preserved at{started_path}; no automatic retry")
    immutable_json(started_path, {"schemaVersion": "NFL_PLAY_LEVEL_FIT_START_V1", "startedUtc": utc(clock()).isoformat(),
                                 "declaration": declaration_ref, "fitIdentity": fit_key, "endSeason": end_season})
    kwargs = {"end_season": end_season}
    if end_season == 2023:
        kwargs["cutoff_date"] = "2024-09-01"
    model = fit_play_model(plays, **kwargs)
    model_path = fit_root / "model.joblib"
    with model_path.open("xb") as stream:
        joblib.dump(model, stream)
    metadata = model.metadata()
    receipt = {"schemaVersion": "NFL_PLAY_LEVEL_FIT_RECEIPT_V1", **AUTHORITY, "fitIdentity": fit_key,
               "declaration": declaration_ref, "modelArtifact": file_record(model_path), "sourceEvidence": source,
               "metadata": metadata, "trainingCutoff": str(model.training_cutoff),
               "trainingSeason": int(model.training_season), "trainingPlayCount": int(model.training_plays),
               "completedUtc": utc(clock()).isoformat(), "actualFitStarts": 1, "completedFits": 1}
    immutable_json(receipt_path, receipt)
    print(f"completed fitted donor model through{end_season}: {model.training_plays} plays", flush=True)
    return model, receipt, True


def fit_and_validate(output: Path, bronze: Path, declaration: dict[str, Any], declaration_ref: dict[str, Any], *, clock: Callable[[], datetime]) -> dict[str, Any]:
    from server.sports_nfl_m1.play_evidence import load_development_plays
    from server.sports_nfl_m1.play_model import evaluate_play_components
    from server.sports_nfl_m1.play_engine import simulate_play_game

    run_root = output / "runs" / declaration_ref["sha256"]
    validation_path = run_root / "validation.json"
    if validation_path.exists():
        receipt = json.loads(validation_path.read_bytes())
        for ref in receipt["fittedArtifacts"]:
            if file_record(Path(ref["path"])) != ref:
                raise ValueError("fitted artifact checksum differs on validation reuse")
        return receipt
    plays, source = load_development_plays(bronze)
    if not set(int(s) for s in plays["season"].unique()).issubset(set(range(2018, 2025))):
        raise ValueError("unexpected/non-Development season in loaded play evidence")
    train_model, train_receipt, first_fit = _fit(plays, source, declaration, declaration_ref, output, end_season=2023, clock=clock)
    valid = plays.loc[plays["season"].eq(2024)]
    components = evaluate_play_components(train_model, valid)
    component_ref = _object(run_root, "component-validation.json", components)
    historical = historical_game_validation(train_model, source["evaluationGames"], simulate=simulate_play_game)
    historical_ref = _object(run_root, "historical-game-validation.json", historical)
    if historical["populationAccounting"]["impossibleStateCount"]:
        raise ValueError(f"historical validation found impossible states; preserved{historical_ref['path']}")
    final_model, final_receipt, second_fit = _fit(plays, source, declaration, declaration_ref, output, end_season=2024, clock=clock)
    reloaded = joblib.load(final_receipt["modelArtifact"]["path"])
    fixture_kwargs = dict(home_team="SEA", away_team="NE", season=2026, seed=SEED, scenario="BASE", postseason=False, include_geometry=False)
    original = simulate_play_game(final_model, **fixture_kwargs)
    recovered = simulate_play_game(reloaded, **fixture_kwargs)
    original_sha = hashlib.sha256(canonical_json_bytes(original)).hexdigest()
    recovered_sha = hashlib.sha256(canonical_json_bytes(recovered)).hexdigest()
    if original_sha != recovered_sha:
        raise ValueError("full play sequence differs after frozen model reload")
    replay_ref = _object(run_root, "reload-fixture.json", {"schemaVersion": "NFL_PLAY_LEVEL_RELOAD_FIXTURE_V1",
                                                        "inputs": fixture_kwargs, "originalGameSha256": original_sha,
                                                        "reloadedGameSha256": recovered_sha, "maximumMismatch": 0,
                                                        "completePlaySequence": recovered})
    source_availability = registered_source_availability(bronze, final_receipt)
    receipt = {"schemaVersion": "NFL_PLAY_LEVEL_VALIDATION_RECEIPT_V1", **AUTHORITY, "declaration": declaration_ref,
               "completedUtc": utc(clock()).isoformat(), "sourceEvidence": source, "sourceAvailability": source_availability,
               "componentValidation": component_ref, "historicalGameValidation": historical_ref, "reloadVerification": replay_ref,
               "trainingFitReceipt": file_record(Path(train_receipt["modelArtifact"]["path"]).with_name("fit-receipt.json")),
               "finalFitReceipt": file_record(Path(final_receipt["modelArtifact"]["path"]).with_name("fit-receipt.json")),
               "fittedArtifacts": [train_receipt["modelArtifact"], final_receipt["modelArtifact"]],
               "actualFitStartsThisInvocation": int(first_fit) + int(second_fit), "completedFitArtifacts": 2,
               "historicalGameSimulations": 32*200, "deterministicReloadGameSimulations": 2,
               "impossibleStateCount": historical["populationAccounting"]["impossibleStateCount"],
               "finalModelIdentity": {"engineId": ENGINE, "engineVersion": "1.0.0", "modelArtifact": final_receipt["modelArtifact"],
                                      "trainingCutoff": final_receipt["trainingCutoff"]}}
    immutable_json(validation_path, receipt)
    return receipt


def _source_forecasts(exchange: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pointer = json.loads((exchange / LEGACY_FAMILY / "current.json").read_bytes())
    forecasts = []
    for ref in pointer["artifacts"]:
        if ref["artifactSchemaVersion"] != "NFL_LABS_SCORE_DISTRIBUTION_V1":
            continue
        original = verify_object(ref)
        # Source event IDs are canonical2026_week1 identities. No outcome read.
        pieces = str(original["eventId"]).split("_")
        if len(pieces) >= 2 and pieces[0] == "2026" and pieces[1] == "01":
            forecasts.append((original, ref))
    forecasts.sort(key=lambda pair: (pair[0]["scheduledStartUtc"], pair[0]["eventId"]))
    if len(forecasts) != 16 or len({f[0]["eventId"] for f in forecasts}) != 16:
        raise ValueError("expected16 distinct verified M1 Week1 events; no schedule fabrication")
    return forecasts


def publish(output: Path, exchange: Path, declaration: dict[str, Any], declaration_ref: dict[str, Any], validation: dict[str, Any], *, clock: Callable[[], datetime]) -> dict[str, Any]:
    from server.sports_nfl_m1.play_engine import simulate_play_game
    from server.sports_nfl_m1.play_geometry import validate_play_level_artifact

    local_contract = REPO / "shared/contracts" / f"{CONTRACT}.json"
    contract = json.loads(local_contract.read_bytes())
    contract_ref = immutable_json(exchange / "contracts" / f"{CONTRACT}.json", contract)
    final_receipt = _read_verified(validation["finalFitReceipt"])
    if file_record(Path(final_receipt["modelArtifact"]["path"])) != final_receipt["modelArtifact"]:
        raise ValueError("frozen play-model artifact checksum or byte count differs before publication")
    model = joblib.load(final_receipt["modelArtifact"]["path"])
    source = validation["sourceAvailability"]
    source_cutoff = utc(source["sourceCutoffUtc"])
    run_root = output / "runs" / declaration_ref["sha256"]
    anchor_forecasts = _source_forecasts(exchange)
    parent_before = {ref["artifact"]["path"]: ref["artifact"] for _, ref in anchor_forecasts}
    artifacts, skips, effects = [], [], []
    actual_starts = representative_replays = reused = impossible = 0
    started = utc(clock())
    invocation_id = started.strftime("%Y%m%dT%H%M%S%fZ")
    attempts_path = run_root / "invocations" / f"{invocation_id}.jsonl"
    attempts_path.parent.mkdir(parents=True, exist_ok=True)
    def event_log(event: dict[str, Any]) -> None:
        with attempts_path.open("ab") as stream:
            stream.write(canonical_json_bytes(event) + b"\n"); stream.flush()
    event_log({"event": "INVOCATION_START", "runtimeUtc": started.isoformat(), "declaredPopulationSlots": 112000})
    for original, parent in anchor_forecasts:
        base_summary = None
        for scenario in SCENARIO_IDS:
            identity = {"engine": validation["finalModelIdentity"], "eventId": original["eventId"],
                        "homeTeam": original["homeTeam"], "awayTeam": original["awayTeam"], "kickoff": original["scheduledStartUtc"],
                        "scenarioId": scenario, "scenarioDefinition": declaration["scenarioDefinitions"][scenario],
                        "draws": 1000, "seed": SEED, "sourceCutoffUtc": source["sourceCutoffUtc"],
                        "parentM1ArtifactSha256": parent["artifact"]["sha256"],
                        "engineImplementation": declaration["implementation"]["server/sports_nfl_m1/play_engine.py"]["sha256"]}
            case_sha = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
            saved_path = run_root / "population-receipts" / f"{case_sha}.json"
            if saved_path.exists():
                saved = json.loads(saved_path.read_bytes())
                record = verify_object(saved["publishedObject"])
                validate_play_level_artifact(record)
                if not (utc(record["sourceCutoffUtc"]) <= utc(record["inferenceStartedUtc"]) <= utc(record["forecastCreatedUtc"])
                        <= utc(record["publishedAtUtc"]) < utc(record["scheduledStartUtc"])):
                    raise ValueError("cached artifact was not genuinely pregame")
                artifacts.append(saved["publishedObject"]); reused += 1
                if scenario == "BASE": base_summary = record["scoreSummary"]
                effects.append({"eventId": original["eventId"], "scenarioId": scenario, "scoreSummary": record["scoreSummary"], "scenarioDelta": record["scenarioDelta"]})
                event_log({"event": "IMMUTABLE_REUSE", "eventId": original["eventId"], "scenarioId": scenario, "artifactSha256": saved["publishedObject"]["artifact"]["sha256"]})
                continue
            # Reindexing an already verified pregame object is not a new fit or
            # forecast, even after kickoff. Only genuinely new populations may
            # enter inference, and they require the live pregame clock below.
            try:
                inference_started = pregame_clock(original["scheduledStartUtc"], clock=clock, stage="EVENT_SCENARIO_INFERENCE")
                if source_cutoff > inference_started:
                    raise ValueError("registered source retrieval is after inference clock")
            except PregameClosed as exc:
                skips.append({"eventId": original["eventId"], "scenarioId": scenario, "reason": str(exc)})
                event_log({"event": "KICKOFF_SKIP", **skips[-1]})
                continue
            aliases = {"LAR": "LA", "WSH": "WAS"}
            home = aliases.get(original["homeTeam"]["abbreviation"], original["homeTeam"]["abbreviation"])
            away = aliases.get(original["awayTeam"]["abbreviation"], original["awayTeam"]["abbreviation"])
            finals = []; accounting = PopulationAccounting()
            event_log({"event": "POPULATION_START", "eventId": original["eventId"], "scenarioId": scenario, "runtimeUtc": inference_started.isoformat(), "scheduledSlots": 1000})
            for index in range(1000):
                actual_starts += 1
                try:
                    game = simulate_play_game(model, home_team=home, away_team=away, season=2026,
                                              seed=SEED+index, scenario=scenario, postseason=False, include_geometry=False)
                except Exception as exc:
                    event_log({"event": "GAME_SIMULATION_FAILED", "eventId": original["eventId"], "scenarioId": scenario,
                               "simulationIndex": index, "actualPopulationGameStartsThisInvocation": actual_starts,
                               "errorType": type(exc).__name__, "error": str(exc)})
                    raise
                accounting.add(game)
                finals.append({"simulationIndex": index, "seed": SEED+index, "homeScore": game["homeScore"], "awayScore": game["awayScore"],
                               "reachedOvertime": game["reachedOvertime"], "finalTie": game["finalTie"],
                               "playCount": len(game["plays"]), "driveCount": game["diagnostics"].get("drives"),
                               "regulationHomeScore": game.get("regulationHomeScore"), "regulationAwayScore": game.get("regulationAwayScore")})
            summary = distribution_summary(finals); counts = accounting.result()
            impossible += counts["impossibleStateCount"]
            if counts["impossibleStateCount"]:
                _object(run_root, "failed-population-accounting.json", {"identity": identity, "accounting": counts})
                raise ValueError("population contains impossible states; no publication")
            representatives = []
            for label, index in representative_indices(finals).items():
                representative_replays += 1
                game = simulate_play_game(model, home_team=home, away_team=away, season=2026,
                                          seed=SEED+index, scenario=scenario, postseason=False, include_geometry=True)
                if any(game[key] != finals[index][key] for key in ("homeScore", "awayScore", "seed", "reachedOvertime")):
                    raise ValueError("representative replay differs from its numerical population")
                representatives.append({"label": label, "simulationIndex": index, **game})
            try:
                created = pregame_clock(original["scheduledStartUtc"], clock=clock, stage="FORECAST_CREATION")
            except PregameClosed as exc:
                skips.append({"eventId": original["eventId"], "scenarioId": scenario, "reason": str(exc), "populationNotPublished": True}); continue
            if scenario == "BASE": base_summary = summary["scoreSummary"]
            if base_summary is None:
                raise ValueError("scenario comparison has no corresponding immutable BASE")
            delta = {key: summary["scoreSummary"][key]-base_summary[key] for key in base_summary}
            m1 = original["scoreSummary"]
            record = {"schemaVersion": ARTIFACT, **AUTHORITY, "sport": "NFL", "forecastId": f"asp-nfl-play-level:sha256:{case_sha}",
                      "eventId": original["eventId"], "homeTeam": original["homeTeam"], "awayTeam": original["awayTeam"],
                      "model": validation["finalModelIdentity"], "relatedM1ForecastId": original["forecastId"], "explainsM1Forecast": False,
                      "sourceForecast": parent["artifact"], "sourceM1Supplement": parent, "scheduledStartUtc": original["scheduledStartUtc"],
                      "forecastCreatedUtc": created.isoformat(), "inferenceStartedUtc": inference_started.isoformat(),
                      "sourceCutoffUtc": source["sourceCutoffUtc"], "sourceAvailability": source,
                      "inputTreatment": {"teamState": model.current_team_state(home, away, 2026),
                                         "coldStart": declaration["coldStart"],
                                         "configurationAuthority": declaration["configurationAuthority"],
                                         "currentQuarterbackInjuryWeatherRosterConsumed": False},
                      "historicalEvidenceThroughDate": final_receipt["trainingCutoff"], "historicalEvidencePrecision": "GAME_DATE_NOT_COMPLETION_OR_RELEASE_TIMESTAMP",
                      "publishedAtUtc": None, "seed": SEED, **summary, "populationFinals": finals, "simulatedGames": representatives,
                      "representativeFinals": [{key: game[key] for key in ("label", "simulationIndex", "homeScore", "awayScore", "seed")} for game in representatives],
                      "scenario": {"scenarioId": scenario, "parameters": declaration["scenarioDefinitions"][scenario],
                                   "interpretation": "SINGLE_FACTOR_SENSITIVITY_NOT_CAUSAL_OR_COACHING_PREDICTION", "modelInputChange": scenario != "BASE",
                                   "turnoverSensitivityMeaning": "ELEVATED_TURNOVER changes supported turnover-donor odds and therefore turnover risk; it is not a variance-only intervention."},
                      "scenarioDelta": delta, "m1Comparison": {"m1ScoreSummary": m1, "playEngineMinusM1": {key: summary["scoreSummary"][key]-m1[key] for key in m1},
                                                                   "interpretation": "Independent raw distributions; no forced agreement or ranking/promotion."},
                      "populationAccounting": counts, "validationReceipt": file_record(run_root / "validation.json"),
                      "declaration": declaration_ref, "contract": contract_ref,
                      "generatingLaw": {"id": ENGINE, "representation": "EMPIRICAL_HIERARCHICAL_CONDITIONAL_PLAY_STATE_TRANSITIONS", "calibration": "RAW_UNCALIBRATED", "geometry": "MODELED_VISUALIZATION_NOT_MEASURED_TRACKING"},
                      "limitations": ["Current team evidence stops with2024 season; 2025 Final OOT was not read.",
                                      "No QB/player identity, injury, weather, untimed price or current roster information is fabricated or consumed.",
                                      "Geometry is modeled visualization from supplied play-level evidence, not measured Statcast/Next Gen tracking.",
                                      "Chronological2024 conditional validation and a small frozen-pregame historical fixture do not establish current wagering calibration.",
                                      "Regular-season overtime only; supported state-engine subset and historical rules are in the contract.",
                                      "Common-seed single-factor scenarios are sensitivity analysis, not estimated causal treatment effects."],
                      "sourceRights": {"mode": "GOVERNED_LOCAL_RESEARCH_ONLY", "sourceRegistrations": declaration["sourcePartitions"], "attributionRequired": True}}
            try:
                publication = pregame_clock(original["scheduledStartUtc"], clock=clock, stage="PUBLICATION")
            except PregameClosed as exc:
                skips.append({"eventId": original["eventId"], "scenarioId": scenario, "reason": str(exc), "populationNotPublished": True}); continue
            record["publishedAtUtc"] = publication.isoformat()
            verification = validate_play_level_artifact(record)
            item = publish_object(record, exchange / FAMILY)
            recovered = verify_object(item); validate_play_level_artifact(recovered)
            saved = {"schemaVersion": "NFL_PLAY_LEVEL_POPULATION_RECEIPT_V1", "identity": identity, "publishedObject": item,
                     "actualGameSimulationStarts": 1000, "representativeReplays": 6, "verification": verification}
            immutable_json(saved_path, saved)
            artifacts.append(item); effects.append({"eventId": original["eventId"], "scenarioId": scenario, "scoreSummary": record["scoreSummary"], "scenarioDelta": delta})
            event_log({"event": "POPULATION_PUBLISHED", "eventId": original["eventId"], "scenarioId": scenario, "artifactSha256": item["artifact"]["sha256"], "runtimeUtc": publication.isoformat()})
            print(f"published play population {original['eventId']} {scenario}:1000 games,6 complete representatives", flush=True)
    for path, expected in parent_before.items():
        if file_record(Path(path)) != expected:
            raise ValueError("an immutable parent M1 artifact changed")
    completed = utc(clock())
    receipt = {"schemaVersion": "NFL_PLAY_LEVEL_HANDOFF_V1", **AUTHORITY, "engineId": ENGINE,
               "publishedAtUtc": completed.isoformat(), "declaration": declaration_ref, "contract": contract_ref,
               "validation": file_record(run_root / "validation.json"), "eventCount": len({a["eventId"] for a in artifacts}),
               "artifactCount": len(artifacts), "expectedArtifactCount": 112, "artifacts": artifacts, "skips": skips,
               "scenarioEffects": effects, "actualPopulationGameSimulationStartsThisInvocation": actual_starts,
               "actualRepresentativeReplayStartsThisInvocation": representative_replays, "reusedImmutablePopulations": reused,
               "scheduledPopulationDrawSlots": 112000, "impossibleStateCount": impossible,
               "runtimeSeconds": (completed-started).total_seconds(), "executionLog": file_record(attempts_path),
               "parentM1ArtifactsUnchanged": True, "providerCalls": 0, "aispWrites": 0, "positionWrites": 0, "sealedOotRead": False}
    handoff = _object(output, "handoff.json", receipt)
    pointer = {"schemaVersion": "NFL_LABS_PLAY_LEVEL_CURRENT_V1", **AUTHORITY, "contract": contract_ref, "handoff": handoff,
               "artifactCount": len(artifacts), "eventCount": receipt["eventCount"], "artifacts": artifacts, "publishedAtUtc": completed.isoformat()}
    _set_pointer(exchange / FAMILY / "current.json", pointer)
    _set_pointer(output / "CURRENT.json", {"status": "COMPLETE" if len(artifacts) == 112 and not skips else "PARTIAL_WITH_EXPLICIT_SKIPS", "handoff": handoff,
                                           "contract": contract_ref, "declaration": declaration_ref, "artifactCount": len(artifacts), "eventCount": receipt["eventCount"]})
    return {"handoff": handoff, "contract": contract_ref, "artifactCount": len(artifacts), "eventCount": receipt["eventCount"], "skips": skips}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=REPO / "outputs/nfl-play-level-engine-v1")
    parser.add_argument("--bronze-root", type=Path, default=Path(r"C:\Users\james\asp-data-staging\nfl\bronze-v1"))
    parser.add_argument("--exchange-root", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--stage", choices=("declare", "fit-evaluate", "publish", "all"), default="declare")
    parser.add_argument("--reuse-validation", type=Path, help="Publish-only reuse of unchanged numerical validation after a renderer/publication repair")
    args = parser.parse_args()
    if args.reuse_validation is not None and args.stage != "publish":
        raise ValueError("--reuse-validation is allowed only with --stage publish; it cannot launch fits")
    clock = lambda: datetime.now(timezone.utc)
    declaration, ref = declare(args.output_root, args.bronze_root, draws=1000)
    if args.stage == "declare": return
    if args.stage == "publish":
        if args.reuse_validation is not None:
            validation = reuse_validation(args.output_root, args.reuse_validation, declaration, ref, clock=clock)
        else:
            path = args.output_root / "runs" / ref["sha256"] / "validation.json"
            if not path.exists(): raise ValueError("matching frozen validation receipt required; publish never starts a fit")
            validation = json.loads(path.read_bytes())
    else:
        validation = fit_and_validate(args.output_root, args.bronze_root, declaration, ref, clock=clock)
    if args.stage in ("publish", "all"):
        print(json.dumps(publish(args.output_root, args.exchange_root, declaration, ref, validation, clock=clock), indent=2), flush=True)
    else:
        print(json.dumps({"declaration": ref, "validation": str(args.output_root / "runs" / ref["sha256"] / "validation.json")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
