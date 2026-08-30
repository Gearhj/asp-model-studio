"""Strict sport-neutral forecast exchange for prospective NFL research shadows.

This is a new wire contract in the existing ``sports_gold`` exchange channel.
The historical ``AISP_DAILY_FORECAST_BUNDLE_V1`` contract is intentionally not
changed: it continues to reject 2025+ events.  This module carries only
content-addressed, non-promoted and non-executable research forecasts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..audit_assurance.canonical import canonical_json_bytes
from ..sports_cockpit.path_containment import ContainmentError, contained_no_reparse


ASP_SPORTS_FORECAST_EXCHANGE_V1 = "ASP_SPORTS_FORECAST_EXCHANGE_V1"
ASP_SPORTS_GAME_FORECAST_V1 = "ASP_SPORTS_GAME_FORECAST_V1"
ASP_SPORTS_FORECAST_IMPORT_FIXTURE_V1 = "ASP_SPORTS_FORECAST_IMPORT_FIXTURE_V1"
ASP_NFL_2026_RESEARCH_SHADOW_INDEX_V1 = "ASP_NFL_2026_RESEARCH_SHADOW_INDEX_V1"
BUNDLE_OBJECT_FAMILY = "aisp-daily-forecast-bundles"
NFL_2026_RESEARCH_SHADOW_INDEX_NAME = "nfl-2026-research-shadow-index.json"
FORECAST_ID_PREFIX = "asp-sports-game-forecast:sha256:"
BUNDLE_ID_PREFIX = "asp-sports-forecast-exchange:sha256:"
FIXTURE_ID_PREFIX = "asp-sports-forecast-import-fixture:sha256:"
SNAPSHOT_TYPES = frozenset({"EARLY", "CURRENT", "FINAL_PREGAME"})
PINNED_NFL_M1_MANIFEST_SHA256 = "ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9"
PINNED_NFL_M1_BINARY_SHA256 = "7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd"
PINNED_NFL_FOUNDATION_SHA256 = "f3e142f05bf9f503168b256db4e05d83c373e94425e1c3147d0817fdf37f3bbb"

VALIDATION_INSTRUCTIONS_BYTES = b"""# ASP Sports Forecast Exchange V1 validation

1. Resolve only the exact bundleLogicalUri named by the import fixture.
2. Hash canonical bundle.json bytes and require the URI, fixture, and directory address to agree.
3. Reject duplicate JSON keys, unknown fields, invalid distributions, or invalid child content IDs.
4. Require NFL, 2026, RESEARCH_SHADOW, NOT_PROMOTED, and executionAllowed=false.
5. Verify exact canonical event/team IDs, pre-kickoff cutoffs, model manifest/binary hashes, and feature-vector hash.
6. This evidence authorizes no provider call, wager, model promotion, or official-bankroll mutation.
"""


class SportsForecastExchangeError(ValueError):
    """The prospective research-shadow wire contract failed closed."""


@dataclass(frozen=True)
class PublishedSportsForecastBundle:
    external_root: Path
    bundle_sha256: str
    bundle_path: Path
    consumer_fixture_path: Path
    validation_instructions_path: Path
    byte_count: int
    consumer_fixture_sha256: str
    validation_instructions_sha256: str
    created: bool
    record: Mapping[str, Any]


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise SportsForecastExchangeError(f"{label} must be an object")
    observed = set(value)
    if observed != fields:
        raise SportsForecastExchangeError(
            f"{label} fields differ; missing={sorted(fields-observed)}, extra={sorted(observed-fields)}"
        )
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SportsForecastExchangeError(f"{label} must be non-empty text")
    return value.strip()


def _sha(value: Any, label: str) -> str:
    result = _text(value, label)
    if len(result) != 64 or result != result.lower() or any(c not in "0123456789abcdef" for c in result):
        raise SportsForecastExchangeError(f"{label} must be lowercase SHA-256")
    return result


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SportsForecastExchangeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise SportsForecastExchangeError(f"{label} is outside its finite range")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SportsForecastExchangeError(f"{label} must be an integer >= {minimum}")
    return value


def _probability(value: Any, label: str) -> float:
    result = _number(value, label)
    if not 0.0 <= result <= 1.0:
        raise SportsForecastExchangeError(f"{label} must be in [0,1]")
    return result


def _utc(value: Any, label: str) -> str:
    raw = _text(value, label).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SportsForecastExchangeError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SportsForecastExchangeError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _day(value: Any, label: str) -> str:
    try:
        parsed = date.fromisoformat(_text(value, label))
    except ValueError as exc:
        raise SportsForecastExchangeError(f"{label} must be an ISO date") from exc
    # The 2026 NFL regular season legitimately extends into January 2027.
    if parsed < date(2026, 1, 1) or parsed > date(2027, 2, 28):
        raise SportsForecastExchangeError(f"{label} is outside the 2026 NFL season horizon")
    return parsed.isoformat()


def _derived_id(value: Mapping[str, Any], field: str, prefix: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return prefix + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _distribution(
    value: Any, label: str, coordinates: tuple[str, ...], *, nonnegative: bool
) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > 10_000:
        raise SportsForecastExchangeError(f"{label} must be a bounded non-empty distribution")
    result: list[dict[str, Any]] = []
    identities: set[tuple[int, ...]] = set()
    for index, raw in enumerate(value):
        item = _exact(raw, set(coordinates) | {"probability"}, f"{label}[{index}]")
        point = tuple(_integer(item[name], f"{label}[{index}].{name}", minimum=0 if nonnegative else -200) for name in coordinates)
        if point in identities:
            raise SportsForecastExchangeError(f"{label} contains a duplicate point")
        identities.add(point)
        probability = _probability(item["probability"], f"{label}[{index}].probability")
        if probability <= 0.0:
            raise SportsForecastExchangeError(f"{label} must omit zero mass")
        result.append({**dict(zip(coordinates, point, strict=True)), "probability": probability})
    if not math.isclose(sum(row["probability"] for row in result), 1.0, abs_tol=1e-9):
        raise SportsForecastExchangeError(f"{label} mass must sum to one")
    return sorted(result, key=lambda row: tuple(row[name] for name in coordinates))


_FORECAST_FIELDS = {
    "schemaVersion", "forecastId", "snapshotType", "sport", "league", "season",
    "seasonType", "week", "scheduleAsOfUtc", "availableAsOfUtc", "snapshotVersion",
    "eventDate", "eventId", "sourceEventId", "scheduledStartUtc", "forecastCutoffUtc",
    "sourceCutoffUtc", "homeTeam", "awayTeam", "engine", "features", "readiness", "status",
    "promotionStatus", "executionStatus",
    "researchShadowOnly", "modelPromotionAllowed", "executionAllowed", "expectedHomeScore",
    "expectedAwayScore", "homeWinProbability", "awayWinProbability", "tieProbability",
    "jointScoreDistribution", "scoreMarginDistribution", "totalScoreDistribution",
    "spreadCoverProbabilities", "overUnderProbabilities", "mostLikelyScores",
    "predictionInterval", "uncertainty", "simulator",
}


def _team(value: Any, label: str) -> dict[str, str]:
    item = _exact(
        value,
        {"teamId", "sourceTeamId", "displayName", "source", "abbreviation", "identitySha256"},
        label,
    )
    result = {
        name: _text(item[name], f"{label}.{name}")
        for name in ("teamId", "sourceTeamId", "displayName", "source", "abbreviation")
    }
    result["identitySha256"] = _sha(item["identitySha256"], f"{label}.identitySha256")
    identity = {name: result[name] for name in ("abbreviation", "source", "sourceTeamId", "teamId")}
    if result["identitySha256"] != hashlib.sha256(canonical_json_bytes(identity)).hexdigest():
        raise SportsForecastExchangeError(f"{label}.identitySha256 differs")
    return result


def _validate_forecast(value: Mapping[str, Any], *, enforce_identity: bool) -> dict[str, Any]:
    item = _exact(value, _FORECAST_FIELDS, "sports game forecast")
    if item["schemaVersion"] != ASP_SPORTS_GAME_FORECAST_V1:
        raise SportsForecastExchangeError("forecast schemaVersion differs")
    snapshot = _text(item["snapshotType"], "snapshotType")
    if snapshot not in SNAPSHOT_TYPES:
        raise SportsForecastExchangeError("snapshotType differs")
    if item["sport"] != "NFL" or item["league"] != "NFL" or item["season"] != 2026:
        raise SportsForecastExchangeError("forecast sport/league/season differs")
    season_type = _text(item["seasonType"], "seasonType")
    if season_type not in {"REG", "POST"}:
        raise SportsForecastExchangeError("seasonType differs")
    week = _integer(item["week"], "week", minimum=1)
    scheduled = _utc(item["scheduledStartUtc"], "scheduledStartUtc")
    cutoff = _utc(item["forecastCutoffUtc"], "forecastCutoffUtc")
    source_cutoff = _utc(item["sourceCutoffUtc"], "sourceCutoffUtc")
    schedule_as_of = _utc(item["scheduleAsOfUtc"], "scheduleAsOfUtc")
    available_as_of = _utc(item["availableAsOfUtc"], "availableAsOfUtc")
    ordered_times = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (schedule_as_of, source_cutoff, cutoff, available_as_of, scheduled)]
    if not all(left <= right for left, right in zip(ordered_times, ordered_times[1:])) or ordered_times[-2] >= ordered_times[-1]:
        raise SportsForecastExchangeError("schedule/source/forecast/availability/kickoff ordering differs")
    if snapshot == "FINAL_PREGAME" and (
        datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        - datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    ).total_seconds() < 900:
        raise SportsForecastExchangeError("FINAL_PREGAME violates the 15-minute cutoff")
    engine = _exact(item["engine"], {
        "engineId", "engineVersion", "modelManifestSha256", "modelBinarySha256",
        "candidateId", "featureTier", "trainingCutoff", "trainingDatasetVersion",
        "trainingDatasetManifestSha256", "featureContractSha256", "producerRevision",
    }, "engine")
    normalized_engine = {
        "engineId": _text(engine["engineId"], "engine.engineId"),
        "engineVersion": _text(engine["engineVersion"], "engine.engineVersion"),
        "modelManifestSha256": _sha(engine["modelManifestSha256"], "engine.modelManifestSha256"),
        "modelBinarySha256": _sha(engine["modelBinarySha256"], "engine.modelBinarySha256"),
        "candidateId": _text(engine["candidateId"], "engine.candidateId"),
        "featureTier": _text(engine["featureTier"], "engine.featureTier"),
        "trainingCutoff": _text(engine["trainingCutoff"], "engine.trainingCutoff"),
        "trainingDatasetVersion": _text(engine["trainingDatasetVersion"], "engine.trainingDatasetVersion"),
        "trainingDatasetManifestSha256": _sha(engine["trainingDatasetManifestSha256"], "engine.trainingDatasetManifestSha256"),
        "featureContractSha256": _sha(engine["featureContractSha256"], "engine.featureContractSha256"),
        "producerRevision": _text(engine["producerRevision"], "engine.producerRevision"),
    }
    if normalized_engine["engineId"] != "NFL_M1_XGBOOST" or normalized_engine["featureTier"] != "LONG_HISTORY_CORE" or normalized_engine["trainingCutoff"] != "2026-02-08":
        raise SportsForecastExchangeError("frozen NFL M1 engine contract differs")
    if (
        normalized_engine["modelManifestSha256"] != PINNED_NFL_M1_MANIFEST_SHA256
        or normalized_engine["modelBinarySha256"] != PINNED_NFL_M1_BINARY_SHA256
        or normalized_engine["trainingDatasetManifestSha256"] != PINNED_NFL_FOUNDATION_SHA256
    ):
        raise SportsForecastExchangeError("pinned NFL M1 artifact/foundation identity differs")
    readiness = _exact(item["readiness"], {"isReady", "score", "threshold", "missingInputs", "reasonCodes"}, "readiness")
    if not isinstance(readiness["isReady"], bool) or not isinstance(readiness["missingInputs"], list) or not isinstance(readiness["reasonCodes"], list):
        raise SportsForecastExchangeError("readiness fields differ")
    normalized_readiness = {
        "isReady": readiness["isReady"],
        "score": _integer(readiness["score"], "readiness.score"),
        "threshold": _integer(readiness["threshold"], "readiness.threshold"),
        "missingInputs": [_text(x, "readiness.missingInputs[]") for x in readiness["missingInputs"]],
        "reasonCodes": [_text(x, "readiness.reasonCodes[]") for x in readiness["reasonCodes"]],
    }
    if normalized_readiness["score"] > 100 or normalized_readiness["threshold"] > 100 or normalized_readiness["isReady"] != (normalized_readiness["score"] >= normalized_readiness["threshold"]):
        raise SportsForecastExchangeError("readiness score/status differs")
    features = _exact(item["features"], {"featureCount", "featureVectorSha256", "missingFeatureCount", "missingFeatures", "missingReasons", "readiness"}, "features")
    if not isinstance(features["missingFeatures"], list) or not isinstance(features["missingReasons"], Mapping):
        raise SportsForecastExchangeError("features missingness fields differ")
    normalized_features = {
        "featureCount": _integer(features["featureCount"], "features.featureCount", minimum=1),
        "featureVectorSha256": _sha(features["featureVectorSha256"], "features.featureVectorSha256"),
        "missingFeatureCount": _integer(features["missingFeatureCount"], "features.missingFeatureCount"),
        "missingFeatures": [_text(x, "features.missingFeatures[]") for x in features["missingFeatures"]],
        "missingReasons": {
            _text(name, "features.missingReasons key"): _text(reason, "features.missingReasons value")
            for name, reason in features["missingReasons"].items()
        },
        "readiness": normalized_readiness,
    }
    if normalized_features["featureCount"] != 197 or normalized_features["missingFeatureCount"] != len(normalized_features["missingFeatures"]) or set(normalized_features["missingReasons"]) != set(normalized_features["missingFeatures"]) or features["readiness"] != normalized_readiness:
        raise SportsForecastExchangeError("features contract/readiness differs")
    joint = _distribution(item["jointScoreDistribution"], "jointScoreDistribution", ("homeScore", "awayScore"), nonnegative=True)
    margin = _distribution(item["scoreMarginDistribution"], "scoreMarginDistribution", ("homeMinusAway",), nonnegative=False)
    total = _distribution(item["totalScoreDistribution"], "totalScoreDistribution", ("totalScore",), nonnegative=True)
    expected_home = _number(item["expectedHomeScore"], "expectedHomeScore", minimum=0)
    expected_away = _number(item["expectedAwayScore"], "expectedAwayScore", minimum=0)
    home_win = _probability(item["homeWinProbability"], "homeWinProbability")
    away_win = _probability(item["awayWinProbability"], "awayWinProbability")
    tie = _probability(item["tieProbability"], "tieProbability")
    if not math.isclose(home_win + away_win + tie, 1.0, abs_tol=1e-9):
        raise SportsForecastExchangeError("win/tie probabilities do not reconcile")
    if not all((
        math.isclose(sum(x["homeScore"]*x["probability"] for x in joint), expected_home, abs_tol=1e-9),
        math.isclose(sum(x["awayScore"]*x["probability"] for x in joint), expected_away, abs_tol=1e-9),
        math.isclose(sum(x["probability"] for x in joint if x["homeScore"] > x["awayScore"]), home_win, abs_tol=1e-9),
        math.isclose(sum(x["probability"] for x in joint if x["awayScore"] > x["homeScore"]), away_win, abs_tol=1e-9),
    )):
        raise SportsForecastExchangeError("joint distribution does not reconcile")
    joint_margin: dict[int, float] = {}
    joint_total: dict[int, float] = {}
    for row in joint:
        difference = row["homeScore"] - row["awayScore"]
        total_points = row["homeScore"] + row["awayScore"]
        joint_margin[difference] = joint_margin.get(difference, 0.0) + row["probability"]
        joint_total[total_points] = joint_total.get(total_points, 0.0) + row["probability"]
    if (
        set(joint_margin) != {row["homeMinusAway"] for row in margin}
        or any(not math.isclose(joint_margin[row["homeMinusAway"]], row["probability"], abs_tol=1e-9) for row in margin)
    ):
        raise SportsForecastExchangeError("margin distribution differs from joint PMF")
    if (
        set(joint_total) != {row["totalScore"] for row in total}
        or any(not math.isclose(joint_total[row["totalScore"]], row["probability"], abs_tol=1e-9) for row in total)
    ):
        raise SportsForecastExchangeError("total distribution differs from joint PMF")
    def line_rows(raw: Any, *, spread: bool) -> list[dict[str, float]]:
        if not isinstance(raw, list) or not raw:
            raise SportsForecastExchangeError("line probabilities must be non-empty")
        names = ({"line", "homeCoverProbability", "awayCoverProbability", "pushProbability"} if spread else {"line", "overProbability", "underProbability", "pushProbability"})
        rows = []
        for idx, value in enumerate(raw):
            row = _exact(value, names, f"lineProbabilities[{idx}]")
            normalized = {"line": _number(row["line"], "line")}
            for name in names - {"line"}:
                normalized[name] = _probability(row[name], name)
            if not math.isclose(sum(normalized[name] for name in names - {"line"}), 1.0, abs_tol=1e-9):
                raise SportsForecastExchangeError("line probabilities do not reconcile")
            line = normalized["line"]
            if spread:
                expected = {
                    "homeCoverProbability": sum(probability for difference, probability in joint_margin.items() if difference + line > 0),
                    "awayCoverProbability": sum(probability for difference, probability in joint_margin.items() if difference + line < 0),
                    "pushProbability": sum(probability for difference, probability in joint_margin.items() if difference + line == 0),
                }
            else:
                expected = {
                    "overProbability": sum(probability for points, probability in joint_total.items() if points - line > 0),
                    "underProbability": sum(probability for points, probability in joint_total.items() if points - line < 0),
                    "pushProbability": sum(probability for points, probability in joint_total.items() if points - line == 0),
                }
            if any(not math.isclose(normalized[name], probability, abs_tol=1e-9) for name, probability in expected.items()):
                raise SportsForecastExchangeError("line probabilities differ from joint PMF")
            rows.append(normalized)
        return sorted(rows, key=lambda row: row["line"])
    most = []
    if not isinstance(item["mostLikelyScores"], list) or not item["mostLikelyScores"]:
        raise SportsForecastExchangeError("mostLikelyScores must be non-empty")
    for index, raw in enumerate(item["mostLikelyScores"]):
        row = _exact(raw, {"homeScore", "awayScore", "probability"}, f"mostLikelyScores[{index}]")
        most.append({"homeScore": _integer(row["homeScore"], "homeScore"), "awayScore": _integer(row["awayScore"], "awayScore"), "probability": _probability(row["probability"], "probability")})
    expected_most = sorted(joint, key=lambda row: (-row["probability"], row["homeScore"], row["awayScore"]))[: len(most)]
    if most != expected_most or len(most) != min(5, len(joint)):
        raise SportsForecastExchangeError("mostLikelyScores differs from top joint cells")
    interval = _exact(item["predictionInterval"], {"confidenceLevel", "homeScoreLower", "homeScoreUpper", "awayScoreLower", "awayScoreUpper", "totalLower", "totalUpper", "marginLower", "marginUpper"}, "predictionInterval")
    normalized_interval = {name: _probability(interval[name], name) if name == "confidenceLevel" else _number(interval[name], name) for name in interval}
    for lower, upper in (("homeScoreLower","homeScoreUpper"),("awayScoreLower","awayScoreUpper"),("totalLower","totalUpper"),("marginLower","marginUpper")):
        if normalized_interval[lower] > normalized_interval[upper]:
            raise SportsForecastExchangeError("prediction interval bounds differ")
    if any(normalized_interval[name] < 0.0 for name in ("homeScoreLower", "homeScoreUpper", "awayScoreLower", "awayScoreUpper", "totalLower", "totalUpper")):
        raise SportsForecastExchangeError("score/total prediction intervals must be nonnegative")
    uncertainty = _exact(item["uncertainty"], {"method", "confidenceLevel", "homeWinProbabilityLower", "homeWinProbabilityUpper", "expectedTotalScoreStdError", "maxBatchProbabilityDelta"}, "uncertainty")
    normalized_uncertainty = {"method": _text(uncertainty["method"], "uncertainty.method"), "confidenceLevel": _probability(uncertainty["confidenceLevel"], "uncertainty.confidenceLevel"), "homeWinProbabilityLower": _probability(uncertainty["homeWinProbabilityLower"], "uncertainty.homeWinProbabilityLower"), "homeWinProbabilityUpper": _probability(uncertainty["homeWinProbabilityUpper"], "uncertainty.homeWinProbabilityUpper"), "expectedTotalScoreStdError": _number(uncertainty["expectedTotalScoreStdError"], "uncertainty.expectedTotalScoreStdError", minimum=0), "maxBatchProbabilityDelta": _number(uncertainty["maxBatchProbabilityDelta"], "uncertainty.maxBatchProbabilityDelta", minimum=0)}
    if normalized_uncertainty["homeWinProbabilityLower"] > normalized_uncertainty["homeWinProbabilityUpper"]:
        raise SportsForecastExchangeError("uncertainty interval ordering differs")
    simulator = _exact(item["simulator"], {"simulatorId", "simulatorVersion", "seed", "simulationCount", "completedSimulations"}, "simulator")
    normalized_simulator = {"simulatorId": _text(simulator["simulatorId"], "simulator.simulatorId"), "simulatorVersion": _text(simulator["simulatorVersion"], "simulator.simulatorVersion"), "seed": _integer(simulator["seed"], "simulator.seed"), "simulationCount": _integer(simulator["simulationCount"], "simulator.simulationCount", minimum=1), "completedSimulations": _integer(simulator["completedSimulations"], "simulator.completedSimulations", minimum=1)}
    if normalized_simulator["simulationCount"] != normalized_simulator["completedSimulations"]:
        raise SportsForecastExchangeError("simulation counts differ")
    result = {
        "schemaVersion": ASP_SPORTS_GAME_FORECAST_V1,
        "forecastId": _text(item["forecastId"], "forecastId"), "snapshotType": snapshot,
        "sport": "NFL", "league": "NFL", "season": 2026, "seasonType": season_type, "week": week,
        "scheduleAsOfUtc": schedule_as_of, "availableAsOfUtc": available_as_of,
        "snapshotVersion": _integer(item["snapshotVersion"], "snapshotVersion", minimum=1),
        "eventDate": _day(item["eventDate"], "eventDate"), "eventId": _text(item["eventId"], "eventId"), "sourceEventId": _text(item["sourceEventId"], "sourceEventId"),
        "scheduledStartUtc": scheduled, "forecastCutoffUtc": cutoff, "sourceCutoffUtc": source_cutoff,
        "homeTeam": _team(item["homeTeam"], "homeTeam"), "awayTeam": _team(item["awayTeam"], "awayTeam"), "engine": normalized_engine, "features": normalized_features,
        "readiness": normalized_readiness, "status": _text(item["status"], "status"),
        "promotionStatus": _text(item["promotionStatus"], "promotionStatus"), "executionStatus": _text(item["executionStatus"], "executionStatus"),
        "researchShadowOnly": item["researchShadowOnly"], "modelPromotionAllowed": item["modelPromotionAllowed"], "executionAllowed": item["executionAllowed"],
        "expectedHomeScore": expected_home, "expectedAwayScore": expected_away,
        "homeWinProbability": home_win, "awayWinProbability": away_win, "tieProbability": tie,
        "jointScoreDistribution": joint, "scoreMarginDistribution": margin, "totalScoreDistribution": total,
        "spreadCoverProbabilities": line_rows(item["spreadCoverProbabilities"], spread=True), "overUnderProbabilities": line_rows(item["overUnderProbabilities"], spread=False),
        "mostLikelyScores": most, "predictionInterval": normalized_interval, "uncertainty": normalized_uncertainty, "simulator": normalized_simulator,
    }
    if result["status"] != "RESEARCH_SHADOW" or result["promotionStatus"] != "NOT_PROMOTED" or result["executionStatus"] != "NOT_EXECUTABLE" or result["researchShadowOnly"] is not True or result["modelPromotionAllowed"] is not False or result["executionAllowed"] is not False:
        raise SportsForecastExchangeError("forecast research-shadow disposition differs")
    if enforce_identity and result["forecastId"] != _derived_id(result, "forecastId", FORECAST_ID_PREFIX):
        raise SportsForecastExchangeError("forecastId differs from canonical content")
    return result


def derive_sports_game_forecast_id(value: Mapping[str, Any]) -> str:
    draft = dict(value); draft.setdefault("forecastId", "PENDING")
    return _derived_id(_validate_forecast(draft, enforce_identity=False), "forecastId", FORECAST_ID_PREFIX)


def validate_sports_game_forecast(value: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_forecast(value, enforce_identity=True)


_BUNDLE_FIELDS = {"schemaVersion", "bundleId", "sport", "league", "season", "slateDate", "generatedAtUtc", "status", "researchShadowOnly", "modelPromotionAllowed", "executionAllowed", "parlaysAllowed", "forecasts"}


def _validate_bundle(value: Mapping[str, Any], *, enforce_identity: bool) -> dict[str, Any]:
    item = _exact(value, _BUNDLE_FIELDS, "sports forecast bundle")
    if item["schemaVersion"] != ASP_SPORTS_FORECAST_EXCHANGE_V1 or item["sport"] != "NFL" or item["league"] != "NFL" or item["season"] != 2026:
        raise SportsForecastExchangeError("bundle identity differs")
    if not isinstance(item["forecasts"], list) or not item["forecasts"]:
        raise SportsForecastExchangeError("bundle forecasts must be non-empty")
    forecasts = [validate_sports_game_forecast(child) for child in item["forecasts"]]
    ids = [child["forecastId"] for child in forecasts]
    logical = [(child["eventId"], child["snapshotType"]) for child in forecasts]
    if len(ids) != len(set(ids)) or len(logical) != len(set(logical)):
        raise SportsForecastExchangeError("bundle contains duplicate forecasts")
    result = {"schemaVersion": ASP_SPORTS_FORECAST_EXCHANGE_V1, "bundleId": _text(item["bundleId"], "bundleId"), "sport": "NFL", "league": "NFL", "season": 2026, "slateDate": _day(item["slateDate"], "slateDate"), "generatedAtUtc": _utc(item["generatedAtUtc"], "generatedAtUtc"), "status": _text(item["status"], "status"), "researchShadowOnly": item["researchShadowOnly"], "modelPromotionAllowed": item["modelPromotionAllowed"], "executionAllowed": item["executionAllowed"], "parlaysAllowed": item["parlaysAllowed"], "forecasts": sorted(forecasts, key=lambda child: (child["scheduledStartUtc"], child["eventId"], child["snapshotType"]))}
    if result["status"] != "RESEARCH_SHADOW" or result["researchShadowOnly"] is not True or result["modelPromotionAllowed"] is not False or result["executionAllowed"] is not False or result["parlaysAllowed"] is not False:
        raise SportsForecastExchangeError("bundle research-shadow disposition differs")
    if any(child["eventDate"] != result["slateDate"] for child in forecasts):
        raise SportsForecastExchangeError("bundle may contain only one slate date")
    if enforce_identity and result["bundleId"] != _derived_id(result, "bundleId", BUNDLE_ID_PREFIX):
        raise SportsForecastExchangeError("bundleId differs from canonical content")
    return result


def derive_sports_forecast_bundle_id(value: Mapping[str, Any]) -> str:
    draft = dict(value); draft.setdefault("bundleId", "PENDING")
    return _derived_id(_validate_bundle(draft, enforce_identity=False), "bundleId", BUNDLE_ID_PREFIX)


def validate_sports_forecast_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_bundle(value, enforce_identity=True)


def _fixture(bundle: Mapping[str, Any], sha: str) -> dict[str, Any]:
    result = {"schemaVersion": ASP_SPORTS_FORECAST_IMPORT_FIXTURE_V1, "bundleLogicalUri": f"asp-model-exchange://{BUNDLE_OBJECT_FAMILY}/sha256/{sha}/bundle.json", "bundleSha256": sha, "fixtureId": "PENDING", "researchShadowOnly": True, "executionAllowed": False, "expectedContractVersions": {"sportsForecastExchange": ASP_SPORTS_FORECAST_EXCHANGE_V1, "sportsGameForecast": ASP_SPORTS_GAME_FORECAST_V1}, "expectedRecordCounts": {"forecasts": len(bundle["forecasts"])}, "validationInstructionsSha256": hashlib.sha256(VALIDATION_INSTRUCTIONS_BYTES).hexdigest()}
    result["fixtureId"] = _derived_id(result, "fixtureId", FIXTURE_ID_PREFIX)
    return result


def _strict_json(payload: bytes, label: str) -> Any:
    def pairs(values: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in values:
            if key in result: raise SportsForecastExchangeError(f"{label} contains duplicate keys")
            result[key] = value
        return result
    try: return json.loads(payload, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise SportsForecastExchangeError(f"{label} JSON is invalid") from exc


def _root(value: Path) -> Path:
    root = Path(value)
    if not root.is_absolute() or not root.is_dir(): raise SportsForecastExchangeError("caller-supplied exchange root must be an existing absolute directory")
    try: return contained_no_reparse(root, [root])
    except ContainmentError as exc: raise SportsForecastExchangeError("exchange root is unsafe") from exc


def verify_sports_forecast_bundle(external_root: Path, bundle_sha256: str) -> PublishedSportsForecastBundle:
    root = _root(external_root); digest = _sha(bundle_sha256, "bundle_sha256")
    try: path = contained_no_reparse(root / BUNDLE_OBJECT_FAMILY / "sha256" / digest / "bundle.json", [root])
    except ContainmentError as exc: raise SportsForecastExchangeError("bundle path is unsafe") from exc
    object_dir = path.parent
    if not object_dir.is_dir() or path.is_symlink() or {p.name for p in object_dir.iterdir()} != {"bundle.json", "consumer-import-fixture.json", "VALIDATION.md"}: raise SportsForecastExchangeError("bundle inventory differs")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest: raise SportsForecastExchangeError("bundle content address differs")
    record = validate_sports_forecast_bundle(_strict_json(payload, "bundle"))
    if canonical_json_bytes(record) != payload: raise SportsForecastExchangeError("bundle is not canonical JSON")
    validation_path = object_dir / "VALIDATION.md"; fixture_path = object_dir / "consumer-import-fixture.json"
    validation_payload = validation_path.read_bytes()
    if validation_payload != VALIDATION_INSTRUCTIONS_BYTES: raise SportsForecastExchangeError("validation instructions differ")
    fixture_payload = fixture_path.read_bytes(); fixture = _strict_json(fixture_payload, "fixture"); expected = _fixture(record, digest)
    if fixture != expected or canonical_json_bytes(expected) != fixture_payload: raise SportsForecastExchangeError("consumer fixture differs")
    return PublishedSportsForecastBundle(root, digest, path, fixture_path, validation_path, len(payload), hashlib.sha256(fixture_payload).hexdigest(), hashlib.sha256(validation_payload).hexdigest(), False, MappingProxyType(record))


def write_sports_forecast_bundle(external_root: Path, value: Mapping[str, Any]) -> PublishedSportsForecastBundle:
    root = _root(external_root); record = validate_sports_forecast_bundle(value); payload = canonical_json_bytes(record); digest = hashlib.sha256(payload).hexdigest()
    parent = root / BUNDLE_OBJECT_FAMILY / "sha256"; parent.mkdir(parents=True, exist_ok=True); final = parent / digest
    if final.exists():
        verified = verify_sports_forecast_bundle(root, digest); return PublishedSportsForecastBundle(**{**verified.__dict__, "created": False})
    staging = parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        for name, child in {"bundle.json": payload, "consumer-import-fixture.json": canonical_json_bytes(_fixture(record, digest)), "VALIDATION.md": VALIDATION_INSTRUCTIONS_BYTES}.items():
            with (staging / name).open("xb") as stream: stream.write(child); stream.flush(); os.fsync(stream.fileno())
        try: os.replace(staging, final)
        except OSError:
            if not final.exists(): raise
    finally:
        if staging.exists(): shutil.rmtree(staging)
    verified = verify_sports_forecast_bundle(root, digest); return PublishedSportsForecastBundle(**{**verified.__dict__, "created": True})


_NFL_INDEX_FIELDS = {
    "schemaVersion", "sport", "league", "season", "status", "researchShadowOnly",
    "bundleContractVersion", "forecastContractVersion", "modelManifestSha256",
    "modelBinarySha256", "featureContractSha256", "updatedAtUtc", "bundleCount",
    "bundleSha256s", "bundleListSha256",
}


def _validate_nfl_2026_locator(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the mutable locator; listed immutable bundles remain authority."""

    item = _exact(value, _NFL_INDEX_FIELDS, "NFL 2026 research-shadow locator")
    if (
        item["schemaVersion"] != ASP_NFL_2026_RESEARCH_SHADOW_INDEX_V1
        or item["sport"] != "NFL"
        or item["league"] != "NFL"
        or item["season"] != 2026
        or item["status"] != "RESEARCH_SHADOW"
        or item["researchShadowOnly"] is not True
        or item["bundleContractVersion"] != ASP_SPORTS_FORECAST_EXCHANGE_V1
        or item["forecastContractVersion"] != ASP_SPORTS_GAME_FORECAST_V1
    ):
        raise SportsForecastExchangeError("NFL 2026 locator identity/disposition differs")
    if not isinstance(item["bundleSha256s"], list) or not item["bundleSha256s"]:
        raise SportsForecastExchangeError("NFL 2026 locator bundle list must be non-empty")
    bundle_shas = [_sha(value, "bundleSha256s[]") for value in item["bundleSha256s"]]
    if bundle_shas != sorted(set(bundle_shas)):
        raise SportsForecastExchangeError("NFL 2026 locator bundle list must be sorted and unique")
    if _integer(item["bundleCount"], "bundleCount", minimum=1) != len(bundle_shas):
        raise SportsForecastExchangeError("NFL 2026 locator bundle count differs")
    list_sha = hashlib.sha256(canonical_json_bytes(bundle_shas)).hexdigest()
    if _sha(item["bundleListSha256"], "bundleListSha256") != list_sha:
        raise SportsForecastExchangeError("NFL 2026 locator bundle-list hash differs")
    model_manifest = _sha(item["modelManifestSha256"], "modelManifestSha256")
    model_binary = _sha(item["modelBinarySha256"], "modelBinarySha256")
    if model_manifest != PINNED_NFL_M1_MANIFEST_SHA256 or model_binary != PINNED_NFL_M1_BINARY_SHA256:
        raise SportsForecastExchangeError("NFL 2026 locator pinned model identity differs")
    return {
        "schemaVersion": ASP_NFL_2026_RESEARCH_SHADOW_INDEX_V1,
        "sport": "NFL", "league": "NFL", "season": 2026,
        "status": "RESEARCH_SHADOW", "researchShadowOnly": True,
        "bundleContractVersion": ASP_SPORTS_FORECAST_EXCHANGE_V1,
        "forecastContractVersion": ASP_SPORTS_GAME_FORECAST_V1,
        "modelManifestSha256": model_manifest,
        "modelBinarySha256": model_binary,
        "featureContractSha256": _sha(item["featureContractSha256"], "featureContractSha256"),
        "updatedAtUtc": _utc(item["updatedAtUtc"], "updatedAtUtc"),
        "bundleCount": len(bundle_shas),
        "bundleSha256s": bundle_shas,
        "bundleListSha256": list_sha,
    }


def verify_nfl_2026_research_shadow_locator(external_root: Path) -> Mapping[str, Any]:
    """Read the locator and independently verify every immutable object it names."""

    root = _root(external_root)
    family = root / BUNDLE_OBJECT_FAMILY
    try:
        family = contained_no_reparse(family, [root])
    except ContainmentError as exc:
        raise SportsForecastExchangeError("NFL 2026 locator family path is unsafe") from exc
    path = family / NFL_2026_RESEARCH_SHADOW_INDEX_NAME
    if not path.is_file() or path.is_symlink():
        raise SportsForecastExchangeError("NFL 2026 locator is absent or unsafe")
    payload = path.read_bytes()
    record = _validate_nfl_2026_locator(_strict_json(payload, "NFL 2026 locator"))
    if payload != canonical_json_bytes(record):
        raise SportsForecastExchangeError("NFL 2026 locator is not canonical JSON")
    for digest in record["bundleSha256s"]:
        verified = verify_sports_forecast_bundle(root, digest)
        if verified.record["sport"] != "NFL" or verified.record["season"] != 2026:
            raise SportsForecastExchangeError("NFL 2026 locator named a non-NFL/2026 bundle")
    return MappingProxyType(record)


def write_nfl_2026_research_shadow_locator(
    external_root: Path,
    *,
    bundle_sha256s: Sequence[str],
    feature_contract_sha256: str,
    updated_at_utc: str,
) -> Mapping[str, Any]:
    """Atomically replace only the locator after every listed object verifies."""

    root = _root(external_root)
    bundle_shas = sorted({_sha(value, "bundle_sha256s[]") for value in bundle_sha256s})
    if not bundle_shas:
        raise SportsForecastExchangeError("cannot publish an empty NFL 2026 locator")
    for digest in bundle_shas:
        verify_sports_forecast_bundle(root, digest)
    record = _validate_nfl_2026_locator({
        "schemaVersion": ASP_NFL_2026_RESEARCH_SHADOW_INDEX_V1,
        "sport": "NFL", "league": "NFL", "season": 2026,
        "status": "RESEARCH_SHADOW", "researchShadowOnly": True,
        "bundleContractVersion": ASP_SPORTS_FORECAST_EXCHANGE_V1,
        "forecastContractVersion": ASP_SPORTS_GAME_FORECAST_V1,
        "modelManifestSha256": PINNED_NFL_M1_MANIFEST_SHA256,
        "modelBinarySha256": PINNED_NFL_M1_BINARY_SHA256,
        "featureContractSha256": feature_contract_sha256,
        "updatedAtUtc": updated_at_utc,
        "bundleCount": len(bundle_shas),
        "bundleSha256s": bundle_shas,
        "bundleListSha256": hashlib.sha256(canonical_json_bytes(bundle_shas)).hexdigest(),
    })
    family = root / BUNDLE_OBJECT_FAMILY
    family.mkdir(parents=True, exist_ok=True)
    try:
        family = contained_no_reparse(family, [root])
    except ContainmentError as exc:
        raise SportsForecastExchangeError("NFL 2026 locator family path is unsafe") from exc
    path = family / NFL_2026_RESEARCH_SHADOW_INDEX_NAME
    if path.exists() and (not path.is_file() or path.is_symlink()):
        raise SportsForecastExchangeError("NFL 2026 locator target is unsafe")
    temporary = family / f".{NFL_2026_RESEARCH_SHADOW_INDEX_NAME}.{uuid.uuid4().hex}.tmp"
    payload = canonical_json_bytes(record)
    try:
        with temporary.open("xb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()
    return verify_nfl_2026_research_shadow_locator(root)


__all__ = ["ASP_SPORTS_FORECAST_EXCHANGE_V1", "ASP_SPORTS_GAME_FORECAST_V1", "ASP_SPORTS_FORECAST_IMPORT_FIXTURE_V1", "ASP_NFL_2026_RESEARCH_SHADOW_INDEX_V1", "BUNDLE_OBJECT_FAMILY", "NFL_2026_RESEARCH_SHADOW_INDEX_NAME", "SportsForecastExchangeError", "PublishedSportsForecastBundle", "derive_sports_game_forecast_id", "derive_sports_forecast_bundle_id", "validate_sports_game_forecast", "validate_sports_forecast_bundle", "verify_sports_forecast_bundle", "write_sports_forecast_bundle", "verify_nfl_2026_research_shadow_locator", "write_nfl_2026_research_shadow_locator"]
