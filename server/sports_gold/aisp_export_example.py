"""Verified Phase 7B6 -> AISP historical research-shadow example bridge.

The bridge consumes one exact content-addressed Phase 7B6 study, selects the
chronologically earliest final-holdout game with paired Direct/E10 simulations, and
publishes two AISP forecasts in one immutable daily bundle.  It never discovers an
exchange root, exports a physical producer path, creates a quote, or invents the
missing historical scheduled-start/forecast-cutoff timestamps.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..sports_cockpit.path_containment import ContainmentError, contained_no_reparse
from .aisp_export_contracts import (
    AISP_DAILY_FORECAST_BUNDLE_V1,
    AISP_GAME_FORECAST_EXPORT_V1,
    BUNDLE_OBJECT_FAMILY,
    PublishedAispBundle,
    derive_daily_forecast_bundle_id,
    derive_game_forecast_id,
    validate_daily_forecast_bundle,
    validate_game_forecast_export,
    write_daily_forecast_bundle,
)


SOURCE_MANIFEST_SCHEMA = "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_MANIFEST_V1"
SOURCE_RESULT_SCHEMA = "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_RESULT_V1"
SOURCE_GAME_RESULT_SCHEMA = "MLB_GOLD_GAME_SIMULATION_RESULT_V1"
SOURCE_STATUS = "AISP_GAME_FORECAST_EXPORT_MVP_COMPLETE"
SOURCE_CANDIDATES = ("DIRECT_GOLD", "E10")


class AispExportExampleError(RuntimeError):
    """The source study or derived example violated its bounded authority."""


@dataclass(frozen=True)
class VerifiedPhase7B6Study:
    request_sha256: str
    manifest_sha256: str
    artifact_sha256: Mapping[str, str]
    request: Mapping[str, Any]
    results: Mapping[str, Any]
    game_records: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class AispExportExamplePublication:
    source_study_sha256: str
    source_manifest_sha256: str
    selected_event_id: str
    selected_event_date: str
    forecast_ids: tuple[str, str]
    bundle_id: str
    bundle_sha256: str
    bundle_logical_uri: str
    consumer_fixture_sha256: str
    publication: PublishedAispBundle


def _strict_json(payload: bytes, name: str) -> Any:
    def pairs(values: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise AispExportExampleError(f"{name} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        return json.loads(payload, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AispExportExampleError(f"{name} JSON is invalid") from exc


def _source_canonical_json_bytes(value: Any) -> bytes:
    """Match the Phase 7B6 producer's SPORTS canonical JSON codec exactly."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AispExportExampleError("Phase 7B6 value is not canonical JSON") from exc


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AispExportExampleError(f"{name} must be non-empty text")
    return value.strip()


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AispExportExampleError(f"{name} must be an integer >= {minimum}")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AispExportExampleError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise AispExportExampleError(f"{name} must be finite")
    return parsed


def _sha256(value: Any, name: str) -> str:
    parsed = _text(value, name)
    if len(parsed) != 64 or parsed != parsed.lower() or any(
        character not in "0123456789abcdef" for character in parsed
    ):
        raise AispExportExampleError(f"{name} must be lowercase SHA-256 hex")
    return parsed


def _safe_root(value: Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise AispExportExampleError("Phase 7B6 study root must be absolute")
    try:
        root = contained_no_reparse(root, [root])
    except ContainmentError as exc:
        raise AispExportExampleError("Phase 7B6 study root is unsafe") from exc
    if not root.is_dir():
        raise AispExportExampleError("Phase 7B6 study root is missing")
    return root


def _child(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or not relative or ".." in rel.parts:
        raise AispExportExampleError("Phase 7B6 artifact path is unsafe")
    try:
        path = contained_no_reparse(root / rel, [root])
    except ContainmentError as exc:
        raise AispExportExampleError("Phase 7B6 artifact path is unsafe") from exc
    if not path.is_file():
        raise AispExportExampleError(f"Phase 7B6 artifact is missing: {relative}")
    return path


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _verify_source_record(record: Mapping[str, Any]) -> None:
    required = {
        "schemaVersion",
        "cohortId",
        "candidateId",
        "canonicalGameId",
        "predictionGameId",
        "awayTeamId",
        "homeTeamId",
        "gameDate",
        "season",
        "nSimulations",
        "classOrder",
        "homeWinProbability",
        "awayWinProbability",
        "expectedHomeRuns",
        "expectedAwayRuns",
        "expectedTotalRuns",
        "jointScoreDistribution",
        "runDifferenceDistribution",
        "totalRunsDistribution",
        "runUncertainty",
        "firstFive",
        "simulationStability",
        "nonterminated",
        "illegalStates",
    }
    if not isinstance(record, Mapping) or not required.issubset(record):
        raise AispExportExampleError("Phase 7B6 game-result schema is incomplete")
    if record["schemaVersion"] != SOURCE_GAME_RESULT_SCHEMA:
        raise AispExportExampleError("Phase 7B6 game-result schemaVersion differs")
    try:
        game_date = date.fromisoformat(_text(record["gameDate"], "gameDate"))
    except ValueError as exc:
        raise AispExportExampleError("Phase 7B6 game date is invalid") from exc
    season = _integer(record["season"], "season", minimum=1)
    if game_date.year >= 2025 or season >= 2025 or season != game_date.year:
        raise AispExportExampleError("Phase 7B6 example rejects 2025+ event data")
    if _integer(record["nSimulations"], "nSimulations", minimum=1) <= 0:
        raise AispExportExampleError("Phase 7B6 simulation count differs")
    if _integer(record["nonterminated"], "nonterminated") != 0 or _integer(
        record["illegalStates"], "illegalStates"
    ) != 0:
        raise AispExportExampleError("Phase 7B6 example requires complete legal simulations")
    classes = record["classOrder"]
    if (
        not isinstance(classes, list)
        or not classes
        or len(classes) != len(set(map(str, classes)))
    ):
        raise AispExportExampleError("Phase 7B6 class order differs")
    if record["cohortId"] == "HOLDOUT" and record["candidateId"] not in SOURCE_CANDIDATES:
        raise AispExportExampleError("Phase 7B6 holdout candidate differs")


def verify_phase7b6_export_source(study_root: Path) -> VerifiedPhase7B6Study:
    """Independently verify one addressed Phase 7B6 study and its result ledger."""

    root = _safe_root(study_root)
    manifest_path = _child(root, "manifest.json")
    manifest_payload = manifest_path.read_bytes()
    manifest = _strict_json(manifest_payload, "Phase 7B6 manifest")
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "schemaVersion",
        "request",
        "requestSha256",
        "resultsSha256",
        "artifacts",
    }:
        raise AispExportExampleError("Phase 7B6 manifest fields differ")
    if manifest["schemaVersion"] != SOURCE_MANIFEST_SCHEMA:
        raise AispExportExampleError("Phase 7B6 manifest schemaVersion differs")
    request = manifest["request"]
    if not isinstance(request, Mapping):
        raise AispExportExampleError("Phase 7B6 request is missing")
    request_sha = hashlib.sha256(_source_canonical_json_bytes(request)).hexdigest()
    if manifest["requestSha256"] != request_sha or root.name != request_sha:
        raise AispExportExampleError("Phase 7B6 request content address differs")
    if _source_canonical_json_bytes(manifest) != manifest_payload:
        raise AispExportExampleError("Phase 7B6 manifest is not canonical JSON")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, Mapping) or not {
        "results.json",
        "game-results.jsonl",
    }.issubset(artifacts):
        raise AispExportExampleError("Phase 7B6 required artifact inventory is missing")
    actual = {
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != set(artifacts):
        raise AispExportExampleError("Phase 7B6 artifact inventory differs")
    artifact_hashes: dict[str, str] = {}
    for relative, raw_evidence in artifacts.items():
        if not isinstance(raw_evidence, Mapping) or set(raw_evidence) != {"bytes", "sha256"}:
            raise AispExportExampleError("Phase 7B6 artifact evidence fields differ")
        path = _child(root, str(relative))
        size, digest = _hash_file(path)
        if size != _integer(raw_evidence["bytes"], "artifact bytes") or digest != _sha256(
            raw_evidence["sha256"], "artifact sha256"
        ):
            raise AispExportExampleError(f"Phase 7B6 artifact bytes differ: {relative}")
        artifact_hashes[str(relative)] = digest
    results_payload = _child(root, "results.json").read_bytes()
    results = _strict_json(results_payload, "Phase 7B6 results")
    if not isinstance(results, Mapping) or _source_canonical_json_bytes(results) != results_payload:
        raise AispExportExampleError("Phase 7B6 results are not canonical JSON")
    if hashlib.sha256(results_payload).hexdigest() != _sha256(
        manifest["resultsSha256"], "resultsSha256"
    ):
        raise AispExportExampleError("Phase 7B6 results identity differs")
    if (
        results.get("schemaVersion") != SOURCE_RESULT_SCHEMA
        or results.get("status") != SOURCE_STATUS
        or results.get("requestSha256") != request_sha
        or results.get("uses2025Or2026") is not False
        or results.get("paModelsFit") != 0
        or results.get("modelsPromoted") != 0
    ):
        raise AispExportExampleError("Phase 7B6 result authority/status differs")
    benchmark = results.get("sportsbookBenchmark")
    if (
        not isinstance(benchmark, Mapping)
        or benchmark.get("status") != "HISTORICAL_ODDS_INSUFFICIENT"
        or benchmark.get("coveredGames") != 0
        or benchmark.get("reason")
        != "NO_GOVERNED_PERSISTED_HISTORICAL_SPORTSBOOK_QUOTES"
    ):
        raise AispExportExampleError("Phase 7B6 historical-odds boundary differs")
    inventory = results.get("candidateInventory")
    if not isinstance(inventory, Mapping) or inventory.get("HOLDOUT") != list(
        SOURCE_CANDIDATES
    ):
        raise AispExportExampleError("Phase 7B6 holdout candidate inventory differs")
    ledger_payload = _child(root, "game-results.jsonl").read_bytes()
    lines = ledger_payload.splitlines()
    if not lines:
        raise AispExportExampleError("Phase 7B6 game-result ledger is empty")
    records: list[Mapping[str, Any]] = []
    for index, line in enumerate(lines):
        record = _strict_json(line, f"Phase 7B6 game-results line {index + 1}")
        if not isinstance(record, Mapping) or _source_canonical_json_bytes(record) != line:
            raise AispExportExampleError("Phase 7B6 game-result line is not canonical JSON")
        _verify_source_record(record)
        records.append(record)
    expected_count = results.get("population", {}).get("candidateGameResultCount")
    if expected_count != len(records):
        raise AispExportExampleError("Phase 7B6 game-result count differs")
    return VerifiedPhase7B6Study(
        request_sha256=request_sha,
        manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
        artifact_sha256=artifact_hashes,
        request=request,
        results=results,
        game_records=tuple(records),
    )


def _paired_earliest_holdout(
    records: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    by_game: dict[str, dict[str, Mapping[str, Any]]] = {}
    for record in records:
        if record.get("cohortId") != "HOLDOUT" or record.get("candidateId") not in SOURCE_CANDIDATES:
            continue
        game_id = _text(record.get("canonicalGameId"), "canonicalGameId")
        candidate = str(record["candidateId"])
        if candidate in by_game.setdefault(game_id, {}):
            raise AispExportExampleError("Phase 7B6 paired holdout result is duplicated")
        by_game[game_id][candidate] = record
    paired = [
        values
        for values in by_game.values()
        if set(values) == set(SOURCE_CANDIDATES)
    ]
    if not paired:
        raise AispExportExampleError("Phase 7B6 has no paired Direct/E10 holdout game")
    selected = min(
        paired,
        key=lambda values: (
            str(values["DIRECT_GOLD"]["gameDate"]),
            str(values["DIRECT_GOLD"]["canonicalGameId"]),
        ),
    )
    direct, e10 = selected["DIRECT_GOLD"], selected["E10"]
    same_fields = (
        "canonicalGameId",
        "predictionGameId",
        "awayTeamId",
        "homeTeamId",
        "gameDate",
        "season",
        "nSimulations",
        "classOrder",
    )
    if any(direct[field] != e10[field] for field in same_fields):
        raise AispExportExampleError("Phase 7B6 paired holdout identities differ")
    return direct, e10


def _distribution(
    value: Any,
    *,
    source_keys: tuple[str, ...],
    target_keys: tuple[str, ...],
    simulations: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise AispExportExampleError("Phase 7B6 source distribution is empty")
    result: list[dict[str, Any]] = []
    count_sum = 0
    for raw in value:
        if not isinstance(raw, Mapping) or not set(source_keys).issubset(raw) or not {
            "count",
            "probability",
        }.issubset(raw):
            raise AispExportExampleError("Phase 7B6 source distribution point differs")
        count = _integer(raw["count"], "distribution count", minimum=1)
        probability = _finite(raw["probability"], "distribution probability")
        if not math.isclose(probability, count / simulations, abs_tol=1e-12):
            raise AispExportExampleError("Phase 7B6 distribution count/probability differs")
        coordinates = {
            target: _integer(raw[source], f"distribution {source}", minimum=0)
            if source != "homeMinusAway"
            else int(raw[source])
            for source, target in zip(source_keys, target_keys, strict=True)
        }
        if source_keys == ("homeMinusAway",) and (
            isinstance(raw["homeMinusAway"], bool)
            or not isinstance(raw["homeMinusAway"], int)
        ):
            raise AispExportExampleError("run-difference coordinate must be integer")
        result.append({**coordinates, "probability": probability})
        count_sum += count
    if count_sum != simulations:
        raise AispExportExampleError("Phase 7B6 distribution counts do not reconcile")
    return result


def _period(record: Mapping[str, Any], *, first_five: bool) -> dict[str, Any]:
    simulations = _integer(record["nSimulations"], "nSimulations", minimum=1)
    source = record["firstFive"] if first_five else record
    if not isinstance(source, Mapping):
        raise AispExportExampleError("Phase 7B6 period result is missing")
    completed = (
        _integer(source["completedSimulations"], "first-five completions")
        if first_five
        else simulations - _integer(record["nonterminated"], "nonterminated")
    )
    completion_rate = (
        _finite(source["completionRate"], "first-five completion rate")
        if first_five
        else completed / simulations
    )
    if completed != simulations or not math.isclose(completion_rate, 1.0, abs_tol=1e-12):
        raise AispExportExampleError("Phase 7B6 example requires complete period simulations")
    home = _finite(source["homeWinProbability"], "homeWinProbability")
    away = _finite(source["awayWinProbability"], "awayWinProbability")
    tie = _finite(source.get("tieProbability", 1.0 - home - away), "tieProbability")
    if abs(tie) <= 1e-12:
        tie = 0.0
    return {
        "available": True,
        "missingReason": None,
        "completedSimulations": completed,
        "completionRate": completion_rate,
        "homeWinProbability": home,
        "awayWinProbability": away,
        "tieProbability": tie,
        "expectedHomeScore": _finite(source["expectedHomeRuns"], "expectedHomeRuns"),
        "expectedAwayScore": _finite(source["expectedAwayRuns"], "expectedAwayRuns"),
        "expectedTotalScore": _finite(source["expectedTotalRuns"], "expectedTotalRuns"),
        "jointScoreDistribution": _distribution(
            source["jointScoreDistribution"],
            source_keys=("awayRuns", "homeRuns"),
            target_keys=("awayScore", "homeScore"),
            simulations=completed,
        ),
        "scoreMarginDistribution": _distribution(
            source["runDifferenceDistribution"],
            source_keys=("homeMinusAway",),
            target_keys=("homeMinusAway",),
            simulations=completed,
        ),
        "totalScoreDistribution": _distribution(
            source["totalRunsDistribution"],
            source_keys=("totalRuns",),
            target_keys=("totalScore",),
            simulations=completed,
        ),
    }


def _probability_interval(probability: float, simulations: int) -> tuple[float, float]:
    radius = 1.96 * math.sqrt(probability * (1.0 - probability) / simulations)
    return max(0.0, probability - radius), min(1.0, probability + radius)


def _uncertainty(
    record: Mapping[str, Any], full: Mapping[str, Any], first: Mapping[str, Any]
) -> dict[str, Any]:
    simulations = int(full["completedSimulations"])
    home_lower, home_upper = _probability_interval(
        float(full["homeWinProbability"]), simulations
    )
    away_lower, away_upper = _probability_interval(
        float(full["awayWinProbability"]), simulations
    )
    first_lower, first_upper = _probability_interval(
        float(first["homeWinProbability"]), int(first["completedSimulations"])
    )
    try:
        total_sd = _finite(
            record["runUncertainty"]["totalRuns"]["standardDeviation"],
            "total-run standard deviation",
        )
        first_sd = _finite(
            record["firstFive"]["runUncertainty"]["totalRuns"]["standardDeviation"],
            "first-five total-run standard deviation",
        )
        max_delta = _finite(
            record["simulationStability"]["maximumAbsoluteDriftVsFinal"][
                "homeWinProbability"
            ],
            "maximum batch probability delta",
        )
    except (KeyError, TypeError) as exc:
        raise AispExportExampleError("Phase 7B6 uncertainty evidence is missing") from exc
    return {
        "method": "MONTE_CARLO_NORMAL_95_WITH_PREFIX_STABILITY",
        "confidenceLevel": 0.95,
        "homeWinProbabilityLower": home_lower,
        "homeWinProbabilityUpper": home_upper,
        "awayWinProbabilityLower": away_lower,
        "awayWinProbabilityUpper": away_upper,
        "firstFiveHomeWinProbabilityLower": first_lower,
        "firstFiveHomeWinProbabilityUpper": first_upper,
        "expectedTotalScoreStdError": total_sd / math.sqrt(simulations),
        "firstFiveExpectedTotalScoreStdError": first_sd
        / math.sqrt(int(first["completedSimulations"])),
        "maxBatchProbabilityDelta": max_delta,
    }


def _model_sha(results: Mapping[str, Any], candidate: str) -> str:
    try:
        evidence = results["frozenModelEvidence"]["HOLDOUT"]
        raw = evidence["direct" if candidate == "DIRECT_GOLD" else "e10"]["sha256"]
    except (KeyError, TypeError) as exc:
        raise AispExportExampleError("Phase 7B6 frozen holdout model evidence is missing") from exc
    return _sha256(raw, f"{candidate} model sha256")


def _forecast(
    source: Mapping[str, Any], study: VerifiedPhase7B6Study
) -> dict[str, Any]:
    candidate = str(source["candidateId"])
    full = _period(source, first_five=False)
    first = _period(source, first_five=True)
    request = study.request
    try:
        simulation = request["simulation"]
        master_seed = _integer(simulation["masterSeed"], "simulation master seed")
        request_simulations = _integer(
            simulation["simulationsPerGame"], "simulations per game", minimum=1
        )
        request_classes = list(request["classOrder"])
    except (KeyError, TypeError) as exc:
        raise AispExportExampleError("Phase 7B6 request simulation authority is missing") from exc
    if request_simulations != source["nSimulations"] or request_classes != source["classOrder"]:
        raise AispExportExampleError("Phase 7B6 request/game simulation authority differs")
    record: dict[str, Any] = {
        "schemaVersion": AISP_GAME_FORECAST_EXPORT_V1,
        "forecastId": "PENDING",
        "sport": "BASEBALL",
        "league": "MLB",
        "eventId": str(source["canonicalGameId"]),
        "sourceEventId": str(source["predictionGameId"]),
        "eventDate": str(source["gameDate"]),
        "season": int(source["season"]),
        "homeTeam": {"teamId": str(source["homeTeamId"]), "displayName": None},
        "awayTeam": {"teamId": str(source["awayTeamId"]), "displayName": None},
        "scheduledStartUtc": None,
        "forecastCutoffUtc": None,
        "engine": {
            "engineId": candidate,
            "engineVersion": "PHASE_7B6_FROZEN_HOLDOUT",
            "candidateId": candidate,
            "modelArtifactSha256": _model_sha(study.results, candidate),
            "inputDataSha256": study.request_sha256,
            "classOrder": request_classes,
        },
        "simulator": {
            "simulatorId": "MLB_WHOLE_GAME_MONTE_CARLO",
            "simulatorVersion": "MLB_WHOLE_GAME_MONTE_CARLO_V1",
            "seed": master_seed,
            "simulationCount": int(source["nSimulations"]),
            "completedSimulations": int(source["nSimulations"]),
            "nonterminationCount": int(source["nonterminated"]),
            "illegalStateCount": int(source["illegalStates"]),
        },
        "fullGame": full,
        "firstFive": first,
        "uncertainty": _uncertainty(source, full, first),
        "readiness": {
            "isReady": False,
            "score": 80,
            "threshold": 85,
            "missingInputs": ["SCHEDULED_START_UTC", "FORECAST_CUTOFF_UTC"],
            "reasonCodes": ["HISTORICAL_TIMESTAMP_AUTHORITY_UNAVAILABLE"],
        },
        "explanations": [
            {
                "code": "HISTORICAL_RESEARCH_SHADOW",
                "summary": f"{candidate} frozen holdout simulation",
                "detail": (
                    "The source has gameDate but no governed scheduled-start or "
                    "forecast-cutoff timestamp; it is not ready for prospective use."
                ),
            },
            {
                "code": "NO_MODEL_PROMOTION",
                "summary": "No model promotion authority",
                "detail": "This record exports immutable research evidence only.",
            },
        ],
        "status": "RESEARCH_SHADOW_NOT_READY",
        "researchShadowOnly": True,
        "executionAllowed": False,
        "modelPromotionAllowed": False,
    }
    record["forecastId"] = derive_game_forecast_id(record)
    return validate_game_forecast_export(record)


def _bundle(
    forecasts: Sequence[Mapping[str, Any]], *, generated_at_utc: str
) -> dict[str, Any]:
    if len(forecasts) != 2 or {item["engine"]["candidateId"] for item in forecasts} != set(
        SOURCE_CANDIDATES
    ):
        raise AispExportExampleError("AISP example requires paired Direct/E10 forecasts")
    event_dates = {str(item["eventDate"]) for item in forecasts}
    if len(event_dates) != 1:
        raise AispExportExampleError("AISP example forecast dates differ")
    record: dict[str, Any] = {
        "schemaVersion": AISP_DAILY_FORECAST_BUNDLE_V1,
        "bundleId": "PENDING",
        "sport": "BASEBALL",
        "league": "MLB",
        "slateDate": next(iter(event_dates)),
        "generatedAtUtc": generated_at_utc,
        "forecastCutoffUtc": None,
        "status": "RESEARCH_SHADOW_NOT_READY",
        "readiness": {
            "isReady": False,
            "score": 0,
            "threshold": 85,
            "missingInputs": [
                "FORECAST_CUTOFF_UTC",
                "READY_CHILD_RECORDS",
                "HISTORICAL_ODDS_INSUFFICIENT",
            ],
            "reasonCodes": [
                "HISTORICAL_TIMESTAMP_AUTHORITY_UNAVAILABLE",
                "HISTORICAL_ODDS_INSUFFICIENT",
            ],
        },
        "forecasts": list(forecasts),
        "marketQuotes": [],
        "betCandidates": [],
        "explanations": [
            {
                "code": "HISTORICAL_ODDS_INSUFFICIENT",
                "summary": "No governed historical sportsbook quotes",
                "detail": (
                    "The verified Phase 7B6 source reports zero covered games; no "
                    "quote, edge, EV, candidate, stake, or ROI is exported."
                ),
            },
            {
                "code": "PAIRED_ENGINE_EXAMPLE",
                "summary": "Direct and E10 research forecasts",
                "detail": "Both engines remain unpromoted research-shadow evidence.",
            },
        ],
        "researchShadowOnly": True,
        "executionAllowed": False,
        "modelPromotionAllowed": False,
        "parlaysAllowed": False,
    }
    record["bundleId"] = derive_daily_forecast_bundle_id(record)
    return validate_daily_forecast_bundle(record)


def publish_aisp_export_example(
    *, study_root: Path, exchange_root: Path
) -> AispExportExamplePublication:
    """Verify, derive, and publish the single bounded AISP consumer example."""

    study = verify_phase7b6_export_source(study_root)
    direct, e10 = _paired_earliest_holdout(study.game_records)
    forecasts = (_forecast(direct, study), _forecast(e10, study))
    generated = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    bundle = _bundle(forecasts, generated_at_utc=generated)
    publication = write_daily_forecast_bundle(Path(exchange_root), bundle)
    logical_uri = (
        f"asp-model-exchange://{BUNDLE_OBJECT_FAMILY}/sha256/"
        f"{publication.bundle_sha256}/bundle.json"
    )
    return AispExportExamplePublication(
        source_study_sha256=study.request_sha256,
        source_manifest_sha256=study.manifest_sha256,
        selected_event_id=str(direct["canonicalGameId"]),
        selected_event_date=str(direct["gameDate"]),
        forecast_ids=(forecasts[0]["forecastId"], forecasts[1]["forecastId"]),
        bundle_id=bundle["bundleId"],
        bundle_sha256=publication.bundle_sha256,
        bundle_logical_uri=logical_uri,
        consumer_fixture_sha256=publication.consumer_fixture_sha256,
        publication=publication,
    )


__all__ = [
    "AispExportExampleError",
    "AispExportExamplePublication",
    "SOURCE_CANDIDATES",
    "VerifiedPhase7B6Study",
    "publish_aisp_export_example",
    "verify_phase7b6_export_source",
]
