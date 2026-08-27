"""Sport-neutral, research-only forecast exchange contracts for AISP.

The module is deliberately a pure boundary plus a caller-rooted immutable writer.  It
does not discover an exchange root, query a provider, fit or promote a model, place a
wager, or select a "latest" bundle.  A consumer must name an exact bundle SHA-256.

All four wire records are strict: unknown fields are rejected, all pricing arithmetic
is independently reconstructed, event seasons from 2025 onward are prohibited, and
every record remains research-shadow-only with execution disabled.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..audit_assurance.canonical import canonical_json_bytes
from ..sports_cockpit.path_containment import ContainmentError, contained_no_reparse


AISP_GAME_FORECAST_EXPORT_V1 = "AISP_GAME_FORECAST_EXPORT_V1"
AISP_MARKET_QUOTE_V1 = "AISP_MARKET_QUOTE_V1"
AISP_BET_CANDIDATE_V1 = "AISP_BET_CANDIDATE_V1"
AISP_DAILY_FORECAST_BUNDLE_V1 = "AISP_DAILY_FORECAST_BUNDLE_V1"
AISP_CONSUMER_IMPORT_FIXTURE_V1 = "AISP_CONSUMER_IMPORT_FIXTURE_V1"

BUNDLE_OBJECT_FAMILY = "aisp-daily-forecast-bundles"
FORECAST_ID_PREFIX = "aisp-game-forecast:sha256:"
BUNDLE_ID_PREFIX = "aisp-daily-forecast-bundle:sha256:"
FIXTURE_ID_PREFIX = "aisp-consumer-import-fixture:sha256:"
VALIDATION_INSTRUCTIONS_BYTES = b"""# AISP Daily Forecast Bundle Validation

1. Resolve only the exact `bundleLogicalUri` in `consumer-import-fixture.json`; never select a latest object.
2. SHA-256 hash `bundle.json` and require equality with `bundleSha256` and the URI address.
3. Parse all JSON with duplicate-key rejection and validate the four exact contract versions listed in the fixture.
4. Require the exact forecast, quote, and candidate counts declared by the fixture and verify every child content binding.
5. Reject unknown fields, 2025+ event data, parlays, executable records, model promotion, non-research status, or missing readiness evidence.
6. Treat this bundle as immutable research-shadow evidence only. It authorizes no wagering, provider call, model fit, or promotion.
"""
RESEARCH_STATUSES = frozenset(
    {
        "RESEARCH_SHADOW_READY",
        "RESEARCH_SHADOW_NOT_READY",
        "RESEARCH_SHADOW_UNAVAILABLE",
    }
)
MARKET_FAMILIES = (
    "FULL_GAME_MONEYLINE",
    "FIRST_FIVE_MONEYLINE",
    "RUN_LINE",
    "FULL_GAME_TOTAL",
    "FIRST_FIVE_TOTAL",
    "TEAM_TOTAL",
)
BET_STATUSES = frozenset({"NO_BET", "WATCH", "QUALIFIED_BET"})
_MONEYLINES = frozenset({"FULL_GAME_MONEYLINE", "FIRST_FIVE_MONEYLINE"})
_TOTALS = frozenset({"FULL_GAME_TOTAL", "FIRST_FIVE_TOTAL", "TEAM_TOTAL"})


class AispExportContractError(ValueError):
    """An AISP export record violated its fixed wire contract."""


@dataclass(frozen=True)
class PublishedAispBundle:
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


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AispExportContractError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise AispExportContractError(f"{name} keys must be strings")
    return value


def _exact(value: Any, expected: set[str], name: str) -> Mapping[str, Any]:
    record = _mapping(value, name)
    observed = set(record)
    if observed != expected:
        raise AispExportContractError(
            f"{name} fields differ; missing={sorted(expected-observed)}, "
            f"extra={sorted(observed-expected)}"
        )
    return record


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AispExportContractError(f"{name} must be non-empty text")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise AispExportContractError(f"{name} must be boolean")
    return value


def _integer(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AispExportContractError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise AispExportContractError(f"{name} must be >= {minimum}")
    return value


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AispExportContractError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise AispExportContractError(f"{name} must be finite")
    if minimum is not None and parsed < minimum:
        raise AispExportContractError(f"{name} must be >= {minimum}")
    return parsed


def _probability(value: Any, name: str) -> float:
    parsed = _number(value, name)
    if not 0.0 <= parsed <= 1.0:
        raise AispExportContractError(f"{name} must be in [0, 1]")
    return parsed


def _sha256(value: Any, name: str) -> str:
    parsed = _text(value, name)
    if len(parsed) != 64 or parsed != parsed.lower() or any(
        character not in "0123456789abcdef" for character in parsed
    ):
        raise AispExportContractError(f"{name} must be lowercase SHA-256 hex")
    return parsed


def _event_date(value: Any, name: str) -> str:
    raw = _text(value, name)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise AispExportContractError(f"{name} must be an ISO calendar date") from exc
    if parsed.year >= 2025:
        raise AispExportContractError(f"{name} rejects 2025+ event data")
    return parsed.isoformat()


def _utc(value: Any, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    raw = _text(value, name)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise AispExportContractError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AispExportContractError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise AispExportContractError(f"{name} must be an array")
    result = [_text(item, f"{name}[]") for item in value]
    if len(result) != len(set(result)):
        raise AispExportContractError(f"{name} must not contain duplicates")
    return result


def _status(value: Any, name: str = "status") -> str:
    parsed = _text(value, name)
    if parsed not in RESEARCH_STATUSES:
        raise AispExportContractError(f"{name} is not a research-shadow status")
    return parsed


def _explanations(value: Any, name: str = "explanations") -> list[dict[str, str]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise AispExportContractError(f"{name} must be a non-empty array")
    result: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        item = _exact(raw, {"code", "summary", "detail"}, f"{name}[{index}]")
        result.append(
            {
                "code": _text(item["code"], f"{name}[{index}].code"),
                "summary": _text(item["summary"], f"{name}[{index}].summary"),
                "detail": _text(item["detail"], f"{name}[{index}].detail"),
            }
        )
    codes = [item["code"] for item in result]
    if len(codes) != len(set(codes)):
        raise AispExportContractError(f"{name} codes must be unique")
    return result


def _readiness(value: Any, name: str = "readiness") -> dict[str, Any]:
    item = _exact(
        value,
        {"isReady", "score", "threshold", "missingInputs", "reasonCodes"},
        name,
    )
    ready = _bool(item["isReady"], f"{name}.isReady")
    score = _integer(item["score"], f"{name}.score", minimum=0)
    threshold = _integer(item["threshold"], f"{name}.threshold", minimum=1)
    if score > 100 or threshold > 100:
        raise AispExportContractError(f"{name} score and threshold must be <= 100")
    missing = _strings(item["missingInputs"], f"{name}.missingInputs")
    reasons = _strings(item["reasonCodes"], f"{name}.reasonCodes")
    computed = score >= threshold and not missing
    if ready != computed:
        raise AispExportContractError(f"{name}.isReady differs from score/missing inputs")
    if not ready and not reasons:
        raise AispExportContractError(f"{name} requires a reason when not ready")
    return {
        "isReady": ready,
        "score": score,
        "threshold": threshold,
        "missingInputs": missing,
        "reasonCodes": reasons,
    }


def _enforce_shadow_flags(record: Mapping[str, Any], name: str) -> None:
    if _bool(record["researchShadowOnly"], f"{name}.researchShadowOnly") is not True:
        raise AispExportContractError(f"{name} must remain research-shadow-only")
    if _bool(record["executionAllowed"], f"{name}.executionAllowed") is not False:
        raise AispExportContractError(f"{name} must disable execution")


def _derived_id(value: Mapping[str, Any], field: str, prefix: str) -> str:
    body = dict(_mapping(value, field))
    body.pop(field, None)
    return prefix + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def derive_game_forecast_id(value: Mapping[str, Any]) -> str:
    """Derive the immutable forecast ID from canonical wire content excluding its ID."""

    draft = dict(_mapping(value, "game forecast"))
    draft.setdefault("forecastId", "PENDING")
    normalized = _validate_game_forecast_export(draft, enforce_identity=False)
    return _derived_id(normalized, "forecastId", FORECAST_ID_PREFIX)


def derive_daily_forecast_bundle_id(value: Mapping[str, Any]) -> str:
    """Derive the logical bundle ID from canonical wire content excluding its ID."""

    draft = dict(_mapping(value, "daily forecast bundle"))
    draft.setdefault("bundleId", "PENDING")
    normalized = _validate_daily_forecast_bundle(draft, enforce_identity=False)
    return _derived_id(normalized, "bundleId", BUNDLE_ID_PREFIX)


def _team(value: Any, name: str) -> dict[str, Any]:
    item = _exact(value, {"teamId", "displayName"}, name)
    return {
        "teamId": _text(item["teamId"], f"{name}.teamId"),
        "displayName": _optional_text(item["displayName"], f"{name}.displayName"),
    }


def _engine(value: Any) -> dict[str, Any]:
    item = _exact(
        value,
        {
            "engineId",
            "engineVersion",
            "candidateId",
            "modelArtifactSha256",
            "inputDataSha256",
            "classOrder",
        },
        "engine",
    )
    classes = _strings(item["classOrder"], "engine.classOrder")
    if not classes:
        raise AispExportContractError("engine.classOrder must be non-empty")
    return {
        "engineId": _text(item["engineId"], "engine.engineId"),
        "engineVersion": _text(item["engineVersion"], "engine.engineVersion"),
        "candidateId": _text(item["candidateId"], "engine.candidateId"),
        "modelArtifactSha256": _sha256(
            item["modelArtifactSha256"], "engine.modelArtifactSha256"
        ),
        "inputDataSha256": _sha256(item["inputDataSha256"], "engine.inputDataSha256"),
        "classOrder": classes,
    }


def _simulator(value: Any) -> dict[str, Any]:
    item = _exact(
        value,
        {
            "simulatorId",
            "simulatorVersion",
            "seed",
            "simulationCount",
            "completedSimulations",
            "nonterminationCount",
            "illegalStateCount",
        },
        "simulator",
    )
    total = _integer(item["simulationCount"], "simulator.simulationCount", minimum=1)
    completed = _integer(
        item["completedSimulations"], "simulator.completedSimulations", minimum=0
    )
    nonterminated = _integer(
        item["nonterminationCount"], "simulator.nonterminationCount", minimum=0
    )
    illegal = _integer(item["illegalStateCount"], "simulator.illegalStateCount", minimum=0)
    if completed + nonterminated != total or illegal > total:
        raise AispExportContractError("simulator completion counts do not reconcile")
    return {
        "simulatorId": _text(item["simulatorId"], "simulator.simulatorId"),
        "simulatorVersion": _text(
            item["simulatorVersion"], "simulator.simulatorVersion"
        ),
        "seed": _integer(item["seed"], "simulator.seed", minimum=0),
        "simulationCount": total,
        "completedSimulations": completed,
        "nonterminationCount": nonterminated,
        "illegalStateCount": illegal,
    }


def _distribution(
    value: Any,
    *,
    name: str,
    coordinate_keys: tuple[str, ...],
    nonnegative_coordinates: bool,
) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise AispExportContractError(f"{name} must be a non-empty distribution")
    if len(value) > 10_000:
        raise AispExportContractError(f"{name} exceeds the bounded point count")
    result: list[dict[str, Any]] = []
    identities: set[tuple[int, ...]] = set()
    for index, raw in enumerate(value):
        keys = set(coordinate_keys) | {"probability"}
        item = _exact(raw, keys, f"{name}[{index}]")
        coordinates = tuple(
            _integer(
                item[key],
                f"{name}[{index}].{key}",
                minimum=0 if nonnegative_coordinates else None,
            )
            for key in coordinate_keys
        )
        if coordinates in identities:
            raise AispExportContractError(f"{name} contains a duplicate point")
        identities.add(coordinates)
        probability = _probability(item["probability"], f"{name}[{index}].probability")
        if probability <= 0.0:
            raise AispExportContractError(f"{name} must omit zero-mass points")
        result.append(
            {**dict(zip(coordinate_keys, coordinates, strict=True)), "probability": probability}
        )
    if not math.isclose(sum(item["probability"] for item in result), 1.0, abs_tol=1e-9):
        raise AispExportContractError(f"{name} probability mass must sum to one")
    return sorted(result, key=lambda item: tuple(item[key] for key in coordinate_keys))


_PERIOD_FIELDS = {
    "available",
    "missingReason",
    "completedSimulations",
    "completionRate",
    "homeWinProbability",
    "awayWinProbability",
    "tieProbability",
    "expectedHomeScore",
    "expectedAwayScore",
    "expectedTotalScore",
    "jointScoreDistribution",
    "scoreMarginDistribution",
    "totalScoreDistribution",
}


def _period(value: Any, name: str, *, maximum_simulations: int) -> dict[str, Any]:
    item = _exact(value, _PERIOD_FIELDS, name)
    available = _bool(item["available"], f"{name}.available")
    missing_reason = _optional_text(item["missingReason"], f"{name}.missingReason")
    completed = _integer(item["completedSimulations"], f"{name}.completedSimulations", minimum=0)
    rate = _probability(item["completionRate"], f"{name}.completionRate")
    if completed > maximum_simulations:
        raise AispExportContractError(f"{name}.completedSimulations exceeds simulator count")
    if available:
        if missing_reason is not None or completed <= 0 or rate <= 0.0:
            raise AispExportContractError(f"{name} availability metadata differs")
        home = _probability(item["homeWinProbability"], f"{name}.homeWinProbability")
        away = _probability(item["awayWinProbability"], f"{name}.awayWinProbability")
        tie = _probability(item["tieProbability"], f"{name}.tieProbability")
        if not math.isclose(home + away + tie, 1.0, abs_tol=1e-9):
            raise AispExportContractError(f"{name} outcome probabilities must sum to one")
        expected_home = _number(item["expectedHomeScore"], f"{name}.expectedHomeScore", minimum=0)
        expected_away = _number(item["expectedAwayScore"], f"{name}.expectedAwayScore", minimum=0)
        expected_total = _number(item["expectedTotalScore"], f"{name}.expectedTotalScore", minimum=0)
        if not math.isclose(expected_total, expected_home + expected_away, abs_tol=1e-9):
            raise AispExportContractError(f"{name} expected scores do not reconcile")
        joint = _distribution(
            item["jointScoreDistribution"],
            name=f"{name}.jointScoreDistribution",
            coordinate_keys=("awayScore", "homeScore"),
            nonnegative_coordinates=True,
        )
        margin = _distribution(
            item["scoreMarginDistribution"],
            name=f"{name}.scoreMarginDistribution",
            coordinate_keys=("homeMinusAway",),
            nonnegative_coordinates=False,
        )
        total = _distribution(
            item["totalScoreDistribution"],
            name=f"{name}.totalScoreDistribution",
            coordinate_keys=("totalScore",),
            nonnegative_coordinates=True,
        )
        joint_home = sum(row["homeScore"] * row["probability"] for row in joint)
        joint_away = sum(row["awayScore"] * row["probability"] for row in joint)
        joint_home_win = sum(
            row["probability"] for row in joint if row["homeScore"] > row["awayScore"]
        )
        joint_away_win = sum(
            row["probability"] for row in joint if row["awayScore"] > row["homeScore"]
        )
        joint_tie = 1.0 - joint_home_win - joint_away_win
        if not all(
            (
                math.isclose(joint_home, expected_home, abs_tol=1e-9),
                math.isclose(joint_away, expected_away, abs_tol=1e-9),
                math.isclose(joint_home_win, home, abs_tol=1e-9),
                math.isclose(joint_away_win, away, abs_tol=1e-9),
                math.isclose(joint_tie, tie, abs_tol=1e-9),
                math.isclose(
                    sum(row["totalScore"] * row["probability"] for row in total),
                    expected_total,
                    abs_tol=1e-9,
                ),
                math.isclose(
                    sum(row["homeMinusAway"] * row["probability"] for row in margin),
                    expected_home - expected_away,
                    abs_tol=1e-9,
                ),
            )
        ):
            raise AispExportContractError(f"{name} distributions do not reconcile")
    else:
        nullable = (
            "homeWinProbability",
            "awayWinProbability",
            "tieProbability",
            "expectedHomeScore",
            "expectedAwayScore",
            "expectedTotalScore",
        )
        if (
            missing_reason is None
            or completed != 0
            or rate != 0.0
            or any(item[key] is not None for key in nullable)
            or any(item[key] != [] for key in (
                "jointScoreDistribution", "scoreMarginDistribution", "totalScoreDistribution"
            ))
        ):
            raise AispExportContractError(f"{name} unavailable payload must be explicitly empty")
        home = away = tie = expected_home = expected_away = expected_total = None
        joint = margin = total = []
    return {
        "available": available,
        "missingReason": missing_reason,
        "completedSimulations": completed,
        "completionRate": rate,
        "homeWinProbability": home,
        "awayWinProbability": away,
        "tieProbability": tie,
        "expectedHomeScore": expected_home,
        "expectedAwayScore": expected_away,
        "expectedTotalScore": expected_total,
        "jointScoreDistribution": joint,
        "scoreMarginDistribution": margin,
        "totalScoreDistribution": total,
    }


def _uncertainty(value: Any, *, full: Mapping[str, Any], first: Mapping[str, Any]) -> dict[str, Any]:
    keys = {
        "method",
        "confidenceLevel",
        "homeWinProbabilityLower",
        "homeWinProbabilityUpper",
        "awayWinProbabilityLower",
        "awayWinProbabilityUpper",
        "firstFiveHomeWinProbabilityLower",
        "firstFiveHomeWinProbabilityUpper",
        "expectedTotalScoreStdError",
        "firstFiveExpectedTotalScoreStdError",
        "maxBatchProbabilityDelta",
    }
    item = _exact(value, keys, "uncertainty")
    result: dict[str, Any] = {
        "method": _text(item["method"], "uncertainty.method"),
        "confidenceLevel": _probability(item["confidenceLevel"], "uncertainty.confidenceLevel"),
        "homeWinProbabilityLower": _probability(
            item["homeWinProbabilityLower"], "uncertainty.homeWinProbabilityLower"
        ),
        "homeWinProbabilityUpper": _probability(
            item["homeWinProbabilityUpper"], "uncertainty.homeWinProbabilityUpper"
        ),
        "awayWinProbabilityLower": _probability(
            item["awayWinProbabilityLower"], "uncertainty.awayWinProbabilityLower"
        ),
        "awayWinProbabilityUpper": _probability(
            item["awayWinProbabilityUpper"], "uncertainty.awayWinProbabilityUpper"
        ),
        "expectedTotalScoreStdError": _number(
            item["expectedTotalScoreStdError"],
            "uncertainty.expectedTotalScoreStdError",
            minimum=0,
        ),
        "maxBatchProbabilityDelta": _number(
            item["maxBatchProbabilityDelta"],
            "uncertainty.maxBatchProbabilityDelta",
            minimum=0,
        ),
    }
    if not 0.0 < result["confidenceLevel"] < 1.0:
        raise AispExportContractError("uncertainty.confidenceLevel must be strictly between zero and one")
    if not (
        result["homeWinProbabilityLower"] <= full["homeWinProbability"] <= result["homeWinProbabilityUpper"]
        and result["awayWinProbabilityLower"] <= full["awayWinProbability"] <= result["awayWinProbabilityUpper"]
    ):
        raise AispExportContractError("uncertainty intervals must contain full-game probabilities")
    first_keys = (
        "firstFiveHomeWinProbabilityLower",
        "firstFiveHomeWinProbabilityUpper",
        "firstFiveExpectedTotalScoreStdError",
    )
    if first["available"]:
        result[first_keys[0]] = _probability(item[first_keys[0]], f"uncertainty.{first_keys[0]}")
        result[first_keys[1]] = _probability(item[first_keys[1]], f"uncertainty.{first_keys[1]}")
        result[first_keys[2]] = _number(item[first_keys[2]], f"uncertainty.{first_keys[2]}", minimum=0)
        if not result[first_keys[0]] <= first["homeWinProbability"] <= result[first_keys[1]]:
            raise AispExportContractError("uncertainty interval must contain first-five probability")
    else:
        if any(item[key] is not None for key in first_keys):
            raise AispExportContractError("first-five uncertainty must be null when first five is unavailable")
        result.update({key: None for key in first_keys})
    return result


_FORECAST_FIELDS = {
    "schemaVersion",
    "forecastId",
    "sport",
    "league",
    "eventId",
    "sourceEventId",
    "eventDate",
    "season",
    "homeTeam",
    "awayTeam",
    "scheduledStartUtc",
    "forecastCutoffUtc",
    "engine",
    "simulator",
    "fullGame",
    "firstFive",
    "uncertainty",
    "readiness",
    "explanations",
    "status",
    "researchShadowOnly",
    "executionAllowed",
    "modelPromotionAllowed",
}


def _validate_game_forecast_export(
    value: Mapping[str, Any], *, enforce_identity: bool
) -> dict[str, Any]:

    item = _exact(value, _FORECAST_FIELDS, "game forecast")
    if item["schemaVersion"] != AISP_GAME_FORECAST_EXPORT_V1:
        raise AispExportContractError("game forecast schemaVersion differs")
    _enforce_shadow_flags(item, "game forecast")
    if _bool(item["modelPromotionAllowed"], "game forecast.modelPromotionAllowed"):
        raise AispExportContractError("game forecast cannot authorize model promotion")
    event_date = _event_date(item["eventDate"], "game forecast.eventDate")
    season = _integer(item["season"], "game forecast.season", minimum=1)
    if season >= 2025 or season != date.fromisoformat(event_date).year:
        raise AispExportContractError("game forecast season differs or includes 2025+")
    home = _team(item["homeTeam"], "game forecast.homeTeam")
    away = _team(item["awayTeam"], "game forecast.awayTeam")
    if home["teamId"] == away["teamId"]:
        raise AispExportContractError("game forecast teams must differ")
    scheduled = _utc(item["scheduledStartUtc"], "game forecast.scheduledStartUtc", nullable=True)
    cutoff = _utc(item["forecastCutoffUtc"], "game forecast.forecastCutoffUtc", nullable=True)
    if scheduled is not None and _as_datetime(scheduled).year >= 2025:
        raise AispExportContractError("scheduledStartUtc rejects 2025+ event data")
    if cutoff is not None and _as_datetime(cutoff).year >= 2025:
        raise AispExportContractError("forecastCutoffUtc rejects 2025+ event data")
    if scheduled is not None and cutoff is not None and _as_datetime(cutoff) >= _as_datetime(scheduled):
        raise AispExportContractError("forecast cutoff must precede scheduled start")
    engine = _engine(item["engine"])
    simulator = _simulator(item["simulator"])
    full = _period(item["fullGame"], "fullGame", maximum_simulations=simulator["simulationCount"])
    first = _period(item["firstFive"], "firstFive", maximum_simulations=simulator["simulationCount"])
    if full["available"] and full["completedSimulations"] != simulator["completedSimulations"]:
        raise AispExportContractError("fullGame completion differs from simulator")
    uncertainty = _uncertainty(item["uncertainty"], full=full, first=first)
    readiness = _readiness(item["readiness"])
    required_missing = set()
    if scheduled is None:
        required_missing.add("SCHEDULED_START_UTC")
    if cutoff is None:
        required_missing.add("FORECAST_CUTOFF_UTC")
    if not full["available"]:
        required_missing.add("FULL_GAME_DISTRIBUTION")
    if not first["available"]:
        required_missing.add("FIRST_FIVE_DISTRIBUTION")
    if simulator["nonterminationCount"] or simulator["illegalStateCount"]:
        required_missing.add("COMPLETE_LEGAL_SIMULATION")
    if not required_missing.issubset(readiness["missingInputs"]):
        raise AispExportContractError("game forecast readiness omits known missing inputs")
    status = _status(item["status"], "game forecast.status")
    expected_status = (
        "RESEARCH_SHADOW_UNAVAILABLE"
        if not full["available"]
        else "RESEARCH_SHADOW_READY"
        if readiness["isReady"]
        else "RESEARCH_SHADOW_NOT_READY"
    )
    if status != expected_status:
        raise AispExportContractError("game forecast status differs from readiness")
    result = {
        "schemaVersion": AISP_GAME_FORECAST_EXPORT_V1,
        "forecastId": _text(item["forecastId"], "game forecast.forecastId"),
        "sport": _text(item["sport"], "game forecast.sport"),
        "league": _text(item["league"], "game forecast.league"),
        "eventId": _text(item["eventId"], "game forecast.eventId"),
        "sourceEventId": _text(item["sourceEventId"], "game forecast.sourceEventId"),
        "eventDate": event_date,
        "season": season,
        "homeTeam": home,
        "awayTeam": away,
        "scheduledStartUtc": scheduled,
        "forecastCutoffUtc": cutoff,
        "engine": engine,
        "simulator": simulator,
        "fullGame": full,
        "firstFive": first,
        "uncertainty": uncertainty,
        "readiness": readiness,
        "explanations": _explanations(item["explanations"]),
        "status": status,
        "researchShadowOnly": True,
        "executionAllowed": False,
        "modelPromotionAllowed": False,
    }
    if enforce_identity and result["forecastId"] != _derived_id(
        result, "forecastId", FORECAST_ID_PREFIX
    ):
        raise AispExportContractError("game forecast forecastId differs from canonical content")
    return result


def validate_game_forecast_export(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one exact ``AISP_GAME_FORECAST_EXPORT_V1`` record."""

    return _validate_game_forecast_export(value, enforce_identity=True)


def _american_to_decimal(value: Any, name: str) -> tuple[int, float]:
    american = _integer(value, name)
    if -100 < american < 100:
        raise AispExportContractError(f"{name} must be <= -100 or >= +100")
    decimal_odds = 1.0 + (american / 100.0 if american > 0 else 100.0 / abs(american))
    return american, decimal_odds


def _fair_american(probability: float) -> float:
    if not 0.0 < probability < 1.0:
        raise AispExportContractError("fair probability must be strictly between zero and one")
    return (
        -100.0 * probability / (1.0 - probability)
        if probability > 0.5
        else 100.0 * (1.0 - probability) / probability
    )


_OUTCOME_FIELDS = {
    "selection",
    "line",
    "americanOdds",
    "decimalOdds",
    "rawImpliedProbability",
    "breakEvenProbability",
    "noVigProbability",
    "fairDecimalOdds",
    "fairAmericanOdds",
}


def _market_outcomes(value: Any, family: str) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise AispExportContractError("market quote requires exactly two outcomes")
    expected = ("HOME", "AWAY") if family in _MONEYLINES or family == "RUN_LINE" else ("OVER", "UNDER")
    parsed: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(value):
        item = _exact(raw, _OUTCOME_FIELDS, f"market quote.outcomes[{index}]")
        selection = _text(item["selection"], f"market quote.outcomes[{index}].selection").upper()
        if selection not in expected or selection in parsed:
            raise AispExportContractError("market quote outcome selections differ")
        line = None if item["line"] is None else _number(item["line"], f"market quote.outcomes[{index}].line")
        american, calculated_decimal = _american_to_decimal(
            item["americanOdds"], f"market quote.outcomes[{index}].americanOdds"
        )
        decimal_odds = _number(item["decimalOdds"], f"market quote.outcomes[{index}].decimalOdds", minimum=1)
        raw_implied = _probability(
            item["rawImpliedProbability"],
            f"market quote.outcomes[{index}].rawImpliedProbability",
        )
        break_even = _probability(
            item["breakEvenProbability"],
            f"market quote.outcomes[{index}].breakEvenProbability",
        )
        no_vig = _probability(
            item["noVigProbability"], f"market quote.outcomes[{index}].noVigProbability"
        )
        fair_decimal = _number(
            item["fairDecimalOdds"], f"market quote.outcomes[{index}].fairDecimalOdds", minimum=1
        )
        fair_american = _number(
            item["fairAmericanOdds"], f"market quote.outcomes[{index}].fairAmericanOdds"
        )
        if not all(
            (
                math.isclose(decimal_odds, calculated_decimal, abs_tol=1e-12),
                math.isclose(raw_implied, 1.0 / calculated_decimal, abs_tol=1e-12),
                math.isclose(break_even, 1.0 / calculated_decimal, abs_tol=1e-12),
                math.isclose(break_even, raw_implied, abs_tol=1e-12),
                math.isclose(fair_decimal, 1.0 / no_vig, abs_tol=1e-12),
                math.isclose(fair_american, _fair_american(no_vig), abs_tol=1e-9),
            )
        ):
            raise AispExportContractError("market quote pricing fields do not reconcile")
        parsed[selection] = {
            "selection": selection,
            "line": line,
            "americanOdds": american,
            "decimalOdds": decimal_odds,
            "rawImpliedProbability": raw_implied,
            "breakEvenProbability": break_even,
            "noVigProbability": no_vig,
            "fairDecimalOdds": fair_decimal,
            "fairAmericanOdds": fair_american,
        }
    outcomes = [parsed[selection] for selection in expected]
    raw_total = sum(outcome["rawImpliedProbability"] for outcome in outcomes)
    if raw_total <= 0.0 or not all(
        math.isclose(outcome["noVigProbability"], outcome["rawImpliedProbability"] / raw_total, abs_tol=1e-12)
        for outcome in outcomes
    ) or not math.isclose(sum(outcome["noVigProbability"] for outcome in outcomes), 1.0, abs_tol=1e-12):
        raise AispExportContractError("market quote no-vig probabilities do not reconcile")
    lines = [outcome["line"] for outcome in outcomes]
    if family in _MONEYLINES and any(line is not None for line in lines):
        raise AispExportContractError("moneyline outcomes must not carry a line")
    if family == "RUN_LINE":
        if any(line is None for line in lines) or math.isclose(float(lines[0]), 0.0, abs_tol=1e-12) or not math.isclose(float(lines[0]) + float(lines[1]), 0.0, abs_tol=1e-12):
            raise AispExportContractError("run-line outcomes require complementary nonzero lines")
    if family in _TOTALS:
        if any(line is None for line in lines) or float(lines[0]) <= 0.0 or not math.isclose(float(lines[0]), float(lines[1]), abs_tol=1e-12):
            raise AispExportContractError("total outcomes require one shared positive line")
    return outcomes


_QUOTE_FIELDS = {
    "schemaVersion",
    "quoteId",
    "sport",
    "league",
    "eventId",
    "eventDate",
    "homeTeamId",
    "awayTeamId",
    "marketFamily",
    "subjectTeamId",
    "marketRulesId",
    "outcomes",
    "sportsbookId",
    "sourceProvider",
    "sourceQuoteId",
    "sourcePayloadSha256",
    "quoteOrigin",
    "isSynthetic",
    "capturedAtUtc",
    "ingestedAtUtc",
    "scheduledStartUtc",
    "status",
    "missingInputs",
    "isParlay",
    "researchShadowOnly",
    "executionAllowed",
}


def validate_market_quote(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one exact two-sided ``AISP_MARKET_QUOTE_V1`` record."""

    item = _exact(value, _QUOTE_FIELDS, "market quote")
    if item["schemaVersion"] != AISP_MARKET_QUOTE_V1:
        raise AispExportContractError("market quote schemaVersion differs")
    _enforce_shadow_flags(item, "market quote")
    if _bool(item["isParlay"], "market quote.isParlay"):
        raise AispExportContractError("parlay quotes are prohibited")
    event_date = _event_date(item["eventDate"], "market quote.eventDate")
    home = _text(item["homeTeamId"], "market quote.homeTeamId")
    away = _text(item["awayTeamId"], "market quote.awayTeamId")
    if home == away:
        raise AispExportContractError("market quote teams must differ")
    family = _text(item["marketFamily"], "market quote.marketFamily")
    if family not in MARKET_FAMILIES:
        raise AispExportContractError("market quote family is unsupported")
    subject = _optional_text(item["subjectTeamId"], "market quote.subjectTeamId")
    if family == "TEAM_TOTAL":
        if subject not in {home, away}:
            raise AispExportContractError("TEAM_TOTAL requires an event subjectTeamId")
    elif subject is not None:
        raise AispExportContractError("subjectTeamId is reserved for TEAM_TOTAL")
    outcomes = _market_outcomes(item["outcomes"], family)
    quote_origin = _text(item["quoteOrigin"], "market quote.quoteOrigin")
    if quote_origin not in {"OBSERVED_PROVIDER", "SYNTHETIC_FIXTURE"}:
        raise AispExportContractError("market quote quoteOrigin differs")
    is_synthetic = _bool(item["isSynthetic"], "market quote.isSynthetic")
    if is_synthetic != (quote_origin == "SYNTHETIC_FIXTURE"):
        raise AispExportContractError("market quote synthetic origin fields disagree")
    captured = _utc(item["capturedAtUtc"], "market quote.capturedAtUtc")
    ingested = _utc(item["ingestedAtUtc"], "market quote.ingestedAtUtc")
    scheduled = _utc(item["scheduledStartUtc"], "market quote.scheduledStartUtc", nullable=True)
    assert captured is not None and ingested is not None
    if _as_datetime(ingested) < _as_datetime(captured):
        raise AispExportContractError("market quote ingestion precedes capture")
    if scheduled is not None:
        if _as_datetime(scheduled).year >= 2025:
            raise AispExportContractError("market quote scheduled start rejects 2025+")
        if _as_datetime(captured) >= _as_datetime(scheduled) or _as_datetime(ingested) >= _as_datetime(scheduled):
            raise AispExportContractError("market quote must be captured and ingested before start")
    missing = _strings(item["missingInputs"], "market quote.missingInputs")
    if scheduled is None and "SCHEDULED_START_UTC" not in missing:
        raise AispExportContractError("market quote omits known scheduled-start missing input")
    status = _status(item["status"], "market quote.status")
    if status != ("RESEARCH_SHADOW_NOT_READY" if missing else "RESEARCH_SHADOW_READY"):
        raise AispExportContractError("market quote status differs from missing inputs")
    return {
        "schemaVersion": AISP_MARKET_QUOTE_V1,
        "quoteId": _text(item["quoteId"], "market quote.quoteId"),
        "sport": _text(item["sport"], "market quote.sport"),
        "league": _text(item["league"], "market quote.league"),
        "eventId": _text(item["eventId"], "market quote.eventId"),
        "eventDate": event_date,
        "homeTeamId": home,
        "awayTeamId": away,
        "marketFamily": family,
        "subjectTeamId": subject,
        "marketRulesId": _text(item["marketRulesId"], "market quote.marketRulesId"),
        "outcomes": outcomes,
        "sportsbookId": _text(item["sportsbookId"], "market quote.sportsbookId"),
        "sourceProvider": _text(item["sourceProvider"], "market quote.sourceProvider"),
        "sourceQuoteId": _text(item["sourceQuoteId"], "market quote.sourceQuoteId"),
        "sourcePayloadSha256": _sha256(item["sourcePayloadSha256"], "market quote.sourcePayloadSha256"),
        "quoteOrigin": quote_origin,
        "isSynthetic": is_synthetic,
        "capturedAtUtc": captured,
        "ingestedAtUtc": ingested,
        "scheduledStartUtc": scheduled,
        "status": status,
        "missingInputs": missing,
        "isParlay": False,
        "researchShadowOnly": True,
        "executionAllowed": False,
    }


_CANDIDATE_FIELDS = {
    "schemaVersion",
    "candidateId",
    "sport",
    "league",
    "eventId",
    "eventDate",
    "forecastId",
    "forecastContentSha256",
    "quoteId",
    "quoteContentSha256",
    "marketFamily",
    "subjectTeamId",
    "selection",
    "line",
    "modelWinProbability",
    "modelPushProbability",
    "modelProbabilityLowerBound",
    "offeredAmericanOdds",
    "offeredDecimalOdds",
    "rawImpliedProbability",
    "breakEvenProbability",
    "noVigProbability",
    "fairDecimalOdds",
    "fairAmericanOdds",
    "modelFairDecimalOdds",
    "modelFairAmericanOdds",
    "edge",
    "uncertaintyAdjustedEdge",
    "expectedValuePerUnit",
    "status",
    "reasonCodes",
    "explanations",
    "isParlay",
    "researchShadowOnly",
    "executionAllowed",
}


def validate_bet_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate pricing and research status for one ``AISP_BET_CANDIDATE_V1``."""

    item = _exact(value, _CANDIDATE_FIELDS, "bet candidate")
    if item["schemaVersion"] != AISP_BET_CANDIDATE_V1:
        raise AispExportContractError("bet candidate schemaVersion differs")
    _enforce_shadow_flags(item, "bet candidate")
    if _bool(item["isParlay"], "bet candidate.isParlay"):
        raise AispExportContractError("parlay candidates are prohibited")
    event_date = _event_date(item["eventDate"], "bet candidate.eventDate")
    family = _text(item["marketFamily"], "bet candidate.marketFamily")
    if family not in MARKET_FAMILIES:
        raise AispExportContractError("bet candidate family is unsupported")
    subject = _optional_text(item["subjectTeamId"], "bet candidate.subjectTeamId")
    if (family == "TEAM_TOTAL") != (subject is not None):
        raise AispExportContractError("bet candidate TEAM_TOTAL subject differs")
    selection = _text(item["selection"], "bet candidate.selection").upper()
    expected = {"HOME", "AWAY"} if family in _MONEYLINES or family == "RUN_LINE" else {"OVER", "UNDER"}
    if selection not in expected:
        raise AispExportContractError("bet candidate selection differs from market family")
    line = None if item["line"] is None else _number(item["line"], "bet candidate.line")
    if family in _MONEYLINES and line is not None:
        raise AispExportContractError("moneyline candidate cannot carry a line")
    if family not in _MONEYLINES and line is None:
        raise AispExportContractError("line/total candidate requires a line")
    american, calculated_decimal = _american_to_decimal(item["offeredAmericanOdds"], "bet candidate.offeredAmericanOdds")
    decimal_odds = _number(item["offeredDecimalOdds"], "bet candidate.offeredDecimalOdds", minimum=1)
    raw = _probability(item["rawImpliedProbability"], "bet candidate.rawImpliedProbability")
    break_even = _probability(
        item["breakEvenProbability"], "bet candidate.breakEvenProbability"
    )
    no_vig = _probability(item["noVigProbability"], "bet candidate.noVigProbability")
    fair_decimal = _number(item["fairDecimalOdds"], "bet candidate.fairDecimalOdds", minimum=1)
    fair_american = _number(item["fairAmericanOdds"], "bet candidate.fairAmericanOdds")
    win = _probability(item["modelWinProbability"], "bet candidate.modelWinProbability")
    push = _probability(item["modelPushProbability"], "bet candidate.modelPushProbability")
    lower = _probability(item["modelProbabilityLowerBound"], "bet candidate.modelProbabilityLowerBound")
    if win + push > 1.0 or lower > win:
        raise AispExportContractError("bet candidate model probability mass differs")
    resolved_mass = 1.0 - push
    if win <= 0.0 or resolved_mass <= 0.0:
        raise AispExportContractError("bet candidate model fair odds require resolved win mass")
    conditional_model_win = win / resolved_mass
    if not 0.0 < conditional_model_win < 1.0:
        raise AispExportContractError("bet candidate model fair probability must be interior")
    model_fair_decimal = _number(
        item["modelFairDecimalOdds"], "bet candidate.modelFairDecimalOdds", minimum=1
    )
    model_fair_american = _number(
        item["modelFairAmericanOdds"], "bet candidate.modelFairAmericanOdds"
    )
    edge = _number(item["edge"], "bet candidate.edge")
    uncertainty_edge = _number(item["uncertaintyAdjustedEdge"], "bet candidate.uncertaintyAdjustedEdge")
    expected_value = _number(item["expectedValuePerUnit"], "bet candidate.expectedValuePerUnit")
    calculated_ev = win * (decimal_odds - 1.0) - (1.0 - win - push)
    if not all(
        (
            math.isclose(decimal_odds, calculated_decimal, abs_tol=1e-12),
            math.isclose(raw, 1.0 / decimal_odds, abs_tol=1e-12),
            math.isclose(break_even, 1.0 / decimal_odds, abs_tol=1e-12),
            math.isclose(break_even, raw, abs_tol=1e-12),
            math.isclose(fair_decimal, 1.0 / no_vig, abs_tol=1e-12),
            math.isclose(fair_american, _fair_american(no_vig), abs_tol=1e-9),
            math.isclose(model_fair_decimal, 1.0 / conditional_model_win, abs_tol=1e-12),
            math.isclose(model_fair_american, _fair_american(conditional_model_win), abs_tol=1e-9),
            math.isclose(edge, win - no_vig, abs_tol=1e-12),
            math.isclose(uncertainty_edge, lower - no_vig, abs_tol=1e-12),
            math.isclose(expected_value, calculated_ev, abs_tol=1e-12),
        )
    ):
        raise AispExportContractError("bet candidate pricing/edge/EV fields do not reconcile")
    candidate_status = _text(item["status"], "bet candidate.status")
    if candidate_status not in BET_STATUSES:
        raise AispExportContractError("bet candidate status differs")
    reasons = _strings(item["reasonCodes"], "bet candidate.reasonCodes")
    if candidate_status != "QUALIFIED_BET" and not reasons:
        raise AispExportContractError("non-qualified bet candidate requires a reason")
    return {
        "schemaVersion": AISP_BET_CANDIDATE_V1,
        "candidateId": _text(item["candidateId"], "bet candidate.candidateId"),
        "sport": _text(item["sport"], "bet candidate.sport"),
        "league": _text(item["league"], "bet candidate.league"),
        "eventId": _text(item["eventId"], "bet candidate.eventId"),
        "eventDate": event_date,
        "forecastId": _text(item["forecastId"], "bet candidate.forecastId"),
        "forecastContentSha256": _sha256(item["forecastContentSha256"], "bet candidate.forecastContentSha256"),
        "quoteId": _text(item["quoteId"], "bet candidate.quoteId"),
        "quoteContentSha256": _sha256(item["quoteContentSha256"], "bet candidate.quoteContentSha256"),
        "marketFamily": family,
        "subjectTeamId": subject,
        "selection": selection,
        "line": line,
        "modelWinProbability": win,
        "modelPushProbability": push,
        "modelProbabilityLowerBound": lower,
        "offeredAmericanOdds": american,
        "offeredDecimalOdds": decimal_odds,
        "rawImpliedProbability": raw,
        "breakEvenProbability": break_even,
        "noVigProbability": no_vig,
        "fairDecimalOdds": fair_decimal,
        "fairAmericanOdds": fair_american,
        "modelFairDecimalOdds": model_fair_decimal,
        "modelFairAmericanOdds": model_fair_american,
        "edge": edge,
        "uncertaintyAdjustedEdge": uncertainty_edge,
        "expectedValuePerUnit": expected_value,
        "status": candidate_status,
        "reasonCodes": reasons,
        "explanations": _explanations(item["explanations"]),
        "isParlay": False,
        "researchShadowOnly": True,
        "executionAllowed": False,
    }


def record_content_sha256(value: Mapping[str, Any]) -> str:
    """Hash one already-normalized wire record with the shared canonical JSON codec."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


_BUNDLE_FIELDS = {
    "schemaVersion",
    "bundleId",
    "sport",
    "league",
    "slateDate",
    "generatedAtUtc",
    "forecastCutoffUtc",
    "status",
    "readiness",
    "forecasts",
    "marketQuotes",
    "betCandidates",
    "explanations",
    "researchShadowOnly",
    "executionAllowed",
    "modelPromotionAllowed",
    "parlaysAllowed",
}


def _records(value: Any, name: str, validator: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise AispExportContractError(f"{name} must be an array")
    return [validator(item) for item in value]


def _validate_daily_forecast_bundle(
    value: Mapping[str, Any], *, enforce_identity: bool
) -> dict[str, Any]:

    item = _exact(value, _BUNDLE_FIELDS, "daily forecast bundle")
    if item["schemaVersion"] != AISP_DAILY_FORECAST_BUNDLE_V1:
        raise AispExportContractError("daily forecast bundle schemaVersion differs")
    _enforce_shadow_flags(item, "daily forecast bundle")
    if _bool(item["modelPromotionAllowed"], "daily forecast bundle.modelPromotionAllowed"):
        raise AispExportContractError("daily forecast bundle cannot authorize model promotion")
    if _bool(item["parlaysAllowed"], "daily forecast bundle.parlaysAllowed"):
        raise AispExportContractError("daily forecast bundle must prohibit parlays")
    sport = _text(item["sport"], "daily forecast bundle.sport")
    league = _text(item["league"], "daily forecast bundle.league")
    slate = _event_date(item["slateDate"], "daily forecast bundle.slateDate")
    generated = _utc(item["generatedAtUtc"], "daily forecast bundle.generatedAtUtc")
    cutoff = _utc(item["forecastCutoffUtc"], "daily forecast bundle.forecastCutoffUtc", nullable=True)
    assert generated is not None
    if cutoff is not None:
        if _as_datetime(cutoff).year >= 2025:
            raise AispExportContractError("daily forecast cutoff rejects 2025+ event data")
        if _as_datetime(generated) < _as_datetime(cutoff):
            raise AispExportContractError("bundle generation precedes its forecast cutoff")
    forecasts = _records(item["forecasts"], "daily forecast bundle.forecasts", validate_game_forecast_export)
    quotes = _records(item["marketQuotes"], "daily forecast bundle.marketQuotes", validate_market_quote)
    candidates = _records(item["betCandidates"], "daily forecast bundle.betCandidates", validate_bet_candidate)
    for name, records, identity in (
        ("forecasts", forecasts, "forecastId"),
        ("marketQuotes", quotes, "quoteId"),
        ("betCandidates", candidates, "candidateId"),
    ):
        values = [record[identity] for record in records]
        if len(values) != len(set(values)):
            raise AispExportContractError(f"daily forecast bundle {name} identities are duplicated")
    children = [*forecasts, *quotes, *candidates]
    if any(record["sport"] != sport or record["league"] != league or record["eventDate"] != slate for record in children):
        raise AispExportContractError("daily forecast bundle child scope differs")
    forecast_by_id = {record["forecastId"]: record for record in forecasts}
    quote_by_id = {record["quoteId"]: record for record in quotes}
    for candidate in candidates:
        forecast = forecast_by_id.get(candidate["forecastId"])
        quote = quote_by_id.get(candidate["quoteId"])
        if forecast is None or quote is None:
            raise AispExportContractError("bet candidate parent is absent from daily bundle")
        if (
            candidate["forecastContentSha256"] != record_content_sha256(forecast)
            or candidate["quoteContentSha256"] != record_content_sha256(quote)
            or candidate["eventId"] != forecast["eventId"]
            or candidate["eventId"] != quote["eventId"]
            or candidate["marketFamily"] != quote["marketFamily"]
            or candidate["subjectTeamId"] != quote["subjectTeamId"]
        ):
            raise AispExportContractError("bet candidate parent binding differs")
        quoted = {outcome["selection"]: outcome for outcome in quote["outcomes"]}.get(candidate["selection"])
        if quoted is None or any(
            not math.isclose(float(candidate[key]), float(quoted[source]), abs_tol=1e-12)
            for key, source in (
                ("offeredDecimalOdds", "decimalOdds"),
                ("rawImpliedProbability", "rawImpliedProbability"),
                ("breakEvenProbability", "breakEvenProbability"),
                ("noVigProbability", "noVigProbability"),
                ("fairDecimalOdds", "fairDecimalOdds"),
                ("fairAmericanOdds", "fairAmericanOdds"),
            )
        ) or candidate["offeredAmericanOdds"] != quoted["americanOdds"] or candidate["line"] != quoted["line"]:
            raise AispExportContractError("bet candidate does not bind the exact quoted outcome")
    readiness = _readiness(item["readiness"], "daily forecast bundle.readiness")
    required_missing = set()
    if cutoff is None:
        required_missing.add("FORECAST_CUTOFF_UTC")
    if not forecasts:
        required_missing.add("GAME_FORECASTS")
    if any(record["status"] != "RESEARCH_SHADOW_READY" for record in forecasts + quotes):
        required_missing.add("READY_CHILD_RECORDS")
    if not required_missing.issubset(readiness["missingInputs"]):
        raise AispExportContractError("daily forecast bundle omits known missing inputs")
    status = _status(item["status"], "daily forecast bundle.status")
    expected_status = (
        "RESEARCH_SHADOW_UNAVAILABLE"
        if not forecasts
        else "RESEARCH_SHADOW_READY"
        if readiness["isReady"]
        else "RESEARCH_SHADOW_NOT_READY"
    )
    if status != expected_status:
        raise AispExportContractError("daily forecast bundle status differs from readiness")
    result = {
        "schemaVersion": AISP_DAILY_FORECAST_BUNDLE_V1,
        "bundleId": _text(item["bundleId"], "daily forecast bundle.bundleId"),
        "sport": sport,
        "league": league,
        "slateDate": slate,
        "generatedAtUtc": generated,
        "forecastCutoffUtc": cutoff,
        "status": status,
        "readiness": readiness,
        "forecasts": forecasts,
        "marketQuotes": quotes,
        "betCandidates": candidates,
        "explanations": _explanations(item["explanations"]),
        "researchShadowOnly": True,
        "executionAllowed": False,
        "modelPromotionAllowed": False,
        "parlaysAllowed": False,
    }
    if enforce_identity and result["bundleId"] != _derived_id(
        result, "bundleId", BUNDLE_ID_PREFIX
    ):
        raise AispExportContractError("daily forecast bundleId differs from canonical content")
    return result


def validate_daily_forecast_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete, cross-bound ``AISP_DAILY_FORECAST_BUNDLE_V1``."""

    return _validate_daily_forecast_bundle(value, enforce_identity=True)


_FIXTURE_FIELDS = {
    "schemaVersion",
    "fixtureId",
    "bundleSha256",
    "bundleLogicalUri",
    "expectedContractVersions",
    "expectedRecordCounts",
    "validationInstructionsSha256",
    "researchShadowOnly",
    "executionAllowed",
}
_FIXTURE_CONTRACT_FIELDS = {
    "gameForecast",
    "marketQuote",
    "betCandidate",
    "dailyForecastBundle",
}
_FIXTURE_COUNT_FIELDS = {"forecasts", "marketQuotes", "betCandidates"}


def _consumer_import_fixture(
    bundle: Mapping[str, Any], bundle_sha256: str
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schemaVersion": AISP_CONSUMER_IMPORT_FIXTURE_V1,
        "bundleSha256": bundle_sha256,
        "bundleLogicalUri": (
            f"asp-model-exchange://{BUNDLE_OBJECT_FAMILY}/sha256/"
            f"{bundle_sha256}/bundle.json"
        ),
        "expectedContractVersions": {
            "gameForecast": AISP_GAME_FORECAST_EXPORT_V1,
            "marketQuote": AISP_MARKET_QUOTE_V1,
            "betCandidate": AISP_BET_CANDIDATE_V1,
            "dailyForecastBundle": AISP_DAILY_FORECAST_BUNDLE_V1,
        },
        "expectedRecordCounts": {
            "forecasts": len(bundle["forecasts"]),
            "marketQuotes": len(bundle["marketQuotes"]),
            "betCandidates": len(bundle["betCandidates"]),
        },
        "validationInstructionsSha256": hashlib.sha256(
            VALIDATION_INSTRUCTIONS_BYTES
        ).hexdigest(),
        "researchShadowOnly": True,
        "executionAllowed": False,
    }
    body["fixtureId"] = _derived_id(body, "fixtureId", FIXTURE_ID_PREFIX)
    return body


def _validate_consumer_import_fixture(
    value: Mapping[str, Any],
    *,
    bundle: Mapping[str, Any],
    bundle_sha256: str,
) -> dict[str, Any]:
    item = _exact(value, _FIXTURE_FIELDS, "consumer import fixture")
    if item["schemaVersion"] != AISP_CONSUMER_IMPORT_FIXTURE_V1:
        raise AispExportContractError("consumer import fixture schemaVersion differs")
    _enforce_shadow_flags(item, "consumer import fixture")
    contracts = _exact(
        item["expectedContractVersions"],
        _FIXTURE_CONTRACT_FIELDS,
        "consumer import fixture.expectedContractVersions",
    )
    counts = _exact(
        item["expectedRecordCounts"],
        _FIXTURE_COUNT_FIELDS,
        "consumer import fixture.expectedRecordCounts",
    )
    normalized = {
        "schemaVersion": AISP_CONSUMER_IMPORT_FIXTURE_V1,
        "fixtureId": _text(item["fixtureId"], "consumer import fixture.fixtureId"),
        "bundleSha256": _sha256(
            item["bundleSha256"], "consumer import fixture.bundleSha256"
        ),
        "bundleLogicalUri": _text(
            item["bundleLogicalUri"], "consumer import fixture.bundleLogicalUri"
        ),
        "expectedContractVersions": {
            key: _text(contracts[key], f"consumer import fixture contracts.{key}")
            for key in sorted(_FIXTURE_CONTRACT_FIELDS)
        },
        "expectedRecordCounts": {
            key: _integer(
                counts[key], f"consumer import fixture counts.{key}", minimum=0
            )
            for key in sorted(_FIXTURE_COUNT_FIELDS)
        },
        "validationInstructionsSha256": _sha256(
            item["validationInstructionsSha256"],
            "consumer import fixture.validationInstructionsSha256",
        ),
        "researchShadowOnly": True,
        "executionAllowed": False,
    }
    expected = _consumer_import_fixture(bundle, bundle_sha256)
    if normalized != expected:
        raise AispExportContractError("consumer import fixture differs from bundle authority")
    if normalized["fixtureId"] != _derived_id(
        normalized, "fixtureId", FIXTURE_ID_PREFIX
    ):
        raise AispExportContractError("consumer import fixture identity differs")
    return normalized


def _strict_json(payload: bytes, name: str) -> Any:
    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AispExportContractError(f"{name} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        return json.loads(payload, object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AispExportContractError(f"{name} JSON is invalid") from exc


def _external_root(value: Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise AispExportContractError("external bundle root must be caller-supplied and absolute")
    try:
        root = contained_no_reparse(root, [root])
    except ContainmentError as exc:
        raise AispExportContractError("external bundle root is not safe") from exc
    if not root.is_dir():
        raise AispExportContractError("caller-supplied external bundle root must already exist")
    return root


def _bundle_path(root: Path, bundle_sha256: str) -> Path:
    try:
        return contained_no_reparse(
            root / BUNDLE_OBJECT_FAMILY / "sha256" / bundle_sha256 / "bundle.json",
            [root],
        )
    except ContainmentError as exc:
        raise AispExportContractError("bundle path is not safely contained") from exc


def verify_daily_forecast_bundle(
    external_root: Path,
    bundle_sha256: str,
) -> PublishedAispBundle:
    """Rehash, canonicalize, and fully revalidate one exact addressed bundle."""

    root = _external_root(external_root)
    digest = _sha256(bundle_sha256, "bundle_sha256")
    path = _bundle_path(root, digest)
    object_dir = path.parent
    expected_inventory = {
        "bundle.json",
        "consumer-import-fixture.json",
        "VALIDATION.md",
    }
    if (
        not object_dir.is_dir()
        or path.is_symlink()
        or set(child.name for child in object_dir.iterdir()) != expected_inventory
    ):
        raise AispExportContractError("bundle object inventory differs")
    try:
        fixture_path = contained_no_reparse(
            object_dir / "consumer-import-fixture.json", [root]
        )
        validation_path = contained_no_reparse(object_dir / "VALIDATION.md", [root])
    except ContainmentError as exc:
        raise AispExportContractError("bundle child path is not safely contained") from exc
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise AispExportContractError("bundle bytes differ from their content address")
    raw = _strict_json(payload, "bundle")
    record = validate_daily_forecast_bundle(raw)
    if canonical_json_bytes(record) != payload:
        raise AispExportContractError("bundle bytes are not canonical validated JSON")
    validation_payload = validation_path.read_bytes()
    if validation_payload != VALIDATION_INSTRUCTIONS_BYTES:
        raise AispExportContractError("validation instructions bytes differ")
    validation_sha = hashlib.sha256(validation_payload).hexdigest()
    fixture_payload = fixture_path.read_bytes()
    fixture_raw = _strict_json(fixture_payload, "consumer import fixture")
    fixture = _validate_consumer_import_fixture(
        fixture_raw, bundle=record, bundle_sha256=digest
    )
    if canonical_json_bytes(fixture) != fixture_payload:
        raise AispExportContractError("consumer import fixture is not canonical JSON")
    fixture_sha = hashlib.sha256(fixture_payload).hexdigest()
    if fixture["validationInstructionsSha256"] != validation_sha:
        raise AispExportContractError("validation instructions hash differs from fixture")
    return PublishedAispBundle(
        external_root=root,
        bundle_sha256=digest,
        bundle_path=path,
        consumer_fixture_path=fixture_path,
        validation_instructions_path=validation_path,
        byte_count=len(payload),
        consumer_fixture_sha256=fixture_sha,
        validation_instructions_sha256=validation_sha,
        created=False,
        record=MappingProxyType(record),
    )


def write_daily_forecast_bundle(
    external_root: Path,
    value: Mapping[str, Any],
) -> PublishedAispBundle:
    """Atomically publish one immutable bundle beneath an explicit external root."""

    root = _external_root(external_root)
    record = validate_daily_forecast_bundle(value)
    payload = canonical_json_bytes(record)
    digest = hashlib.sha256(payload).hexdigest()
    fixture_payload = canonical_json_bytes(_consumer_import_fixture(record, digest))
    path = _bundle_path(root, digest)
    object_root = path.parent.parent
    object_root.mkdir(parents=True, exist_ok=True)
    try:
        contained_no_reparse(object_root, [root])
    except ContainmentError as exc:
        raise AispExportContractError("bundle object root is not safely contained") from exc
    if path.parent.exists():
        verified = verify_daily_forecast_bundle(root, digest)
        return PublishedAispBundle(
            **{**verified.__dict__, "created": False}
        )
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=object_root))
    created = False
    try:
        children = {
            "bundle.json": payload,
            "consumer-import-fixture.json": fixture_payload,
            "VALIDATION.md": VALIDATION_INSTRUCTIONS_BYTES,
        }
        for name, child_payload in children.items():
            staging_file = contained_no_reparse(staging / name, [object_root])
            with staging_file.open("xb") as stream:
                stream.write(child_payload)
                stream.flush()
                os.fsync(stream.fileno())
        try:
            os.replace(staging, path.parent)
            created = True
        except OSError:
            if not path.parent.exists():
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    verified = verify_daily_forecast_bundle(root, digest)
    return PublishedAispBundle(
        **{**verified.__dict__, "created": created}
    )


__all__ = [
    "AISP_BET_CANDIDATE_V1",
    "AISP_CONSUMER_IMPORT_FIXTURE_V1",
    "AISP_DAILY_FORECAST_BUNDLE_V1",
    "AISP_GAME_FORECAST_EXPORT_V1",
    "AISP_MARKET_QUOTE_V1",
    "AispExportContractError",
    "BET_STATUSES",
    "BUNDLE_ID_PREFIX",
    "BUNDLE_OBJECT_FAMILY",
    "FIXTURE_ID_PREFIX",
    "FORECAST_ID_PREFIX",
    "MARKET_FAMILIES",
    "PublishedAispBundle",
    "RESEARCH_STATUSES",
    "VALIDATION_INSTRUCTIONS_BYTES",
    "derive_daily_forecast_bundle_id",
    "derive_game_forecast_id",
    "record_content_sha256",
    "validate_bet_candidate",
    "validate_daily_forecast_bundle",
    "validate_game_forecast_export",
    "validate_market_quote",
    "verify_daily_forecast_bundle",
    "write_daily_forecast_bundle",
]
