"""Prospective, identity-bound model-versus-market measurement.

The module consumes already persisted evidence. It never obtains quotes,
forecasts, or outcomes. One row is one game at one declared horizon; repeated
scheduler decisions and simulation draws are never assessment units.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Any, Mapping, Sequence

import numpy as np


SCHEMA = "MODEL_VS_MARKET_OBSERVATION_V1"
REPORT_SCHEMA = "MODEL_VS_MARKET_BENCHMARK_V1"
NO_VIG_METHOD = "PROPORTIONAL_IMPLIED_PROBABILITY_V1"
BINARY_BRIER = "SUM_OF_TWO_CLASS_SQUARED_ERRORS"
SPORTS = frozenset({"MLB", "NFL", "NBA", "CFB"})
HORIZONS = frozenset({"OPENING", "DECISION_TIME", "CLOSING", "CAPTURED_EARLY_UNCLASSIFIED"})


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _probability(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0.0 or result > 1.0:
        raise ValueError(f"{label} is not a probability")
    return result


def _odds(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 1.0:
        raise ValueError(f"{label} must be finite decimal odds above 1")
    return result


def no_vig_home_probability(home_decimal: float, away_decimal: float) -> float:
    """Frozen proportional de-vigging for one complete two-sided moneyline."""
    home = 1.0 / _odds(home_decimal, "home decimal odds")
    away = 1.0 / _odds(away_decimal, "away decimal odds")
    return home / (home + away)


def validate_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "observationId", "sport", "season", "eventId",
        "eventStartUtc", "supportCohort", "decisionStatus", "evidenceRole",
        "forecast", "market", "final",
    }
    if set(value) != required or value.get("schemaVersion") != SCHEMA:
        raise ValueError("Observation fields or schema differ")
    sport = str(value["sport"]).upper()
    if sport not in SPORTS:
        raise ValueError("Unsupported sport")
    start = _utc(value["eventStartUtc"])
    forecast = dict(value["forecast"])
    market = dict(value["market"])
    final = dict(value["final"])
    if market.get("horizon") not in HORIZONS:
        raise ValueError("Market horizon differs")
    if market.get("noVigMethod") != NO_VIG_METHOD:
        raise ValueError("No-vig method differs")
    available = _utc(forecast["availableAtUtc"])
    as_of = _utc(market["asOfUtc"])
    if not available <= as_of < start:
        raise ValueError("Forecast/market chronology differs")
    probabilities = {
        key: _probability(forecast[key], f"forecast.{key}")
        for key in ("homeWinProbability", "awayWinProbability", "tieProbability")
    }
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-12):
        raise ValueError("Forecast probability mass differs")
    if sport in {"MLB", "NBA", "CFB"} and probabilities["tieProbability"] != 0.0:
        raise ValueError(f"{sport} final tie probability must be zero")
    quotes = list(market.get("quotes") or [])
    if not quotes:
        raise ValueError("Complete two-sided moneyline quote is required")
    normalized_quotes: list[dict[str, Any]] = []
    for quote in quotes:
        if quote.get("marketType") != "FULL_GAME_MONEYLINE" or quote.get("period") != "FULL_GAME":
            raise ValueError("Market semantics differ")
        if not quote.get("provider") or not quote.get("sportsbook"):
            raise ValueError("Provider and sportsbook are required")
        legs: dict[str, dict[str, Any]] = {}
        for side in ("home", "away"):
            leg = dict(quote[side])
            observed = _utc(leg["observedAtUtc"])
            leg_available = _utc(leg["availableAsOfUtc"])
            if observed > leg_available or leg_available > as_of:
                raise ValueError("Market-leg chronology differs")
            legs[side] = {
                **leg,
                "decimalOdds": _odds(leg["decimalOdds"], f"{side} decimal odds"),
            }
        normalized_quotes.append({
            **quote,
            **legs,
            "homeNoVigProbability": no_vig_home_probability(
                legs["home"]["decimalOdds"], legs["away"]["decimalOdds"]
            ),
            "olderLegFreshnessSeconds": (as_of - min(
                _utc(legs["home"]["observedAtUtc"]),
                _utc(legs["away"]["observedAtUtc"]),
            )).total_seconds(),
        })
    final_status = str(final.get("status") or "")
    if final_status not in {"FINAL", "PENDING"}:
        raise ValueError("Final status differs")
    if final_status == "FINAL":
        if final.get("identity") is None or int(final.get("revision") or 0) < 1:
            raise ValueError("Governed final identity/revision is required")
        _utc(final["availableAtUtc"])
        for key in ("homeScore", "awayScore"):
            if isinstance(final.get(key), bool) or int(final.get(key)) < 0:
                raise ValueError("Final score differs")
    result = dict(value)
    result["sport"] = sport
    result["forecast"] = {**forecast, **probabilities}
    result["market"] = {**market, "quotes": normalized_quotes}
    return result


def _loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    bounded = np.clip(p, 1e-15, 1 - 1e-15)
    return -(y * np.log(bounded) + (1 - y) * np.log(1 - bounded))


def _brier(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    return 2.0 * np.square(p - y)


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    positive = p[y == 1]
    negative = p[y == 0]
    if not len(positive) or not len(negative):
        return None
    greater = sum(float(a > b) + 0.5 * float(a == b) for a in positive for b in negative)
    return greater / (len(positive) * len(negative))


def _calibration(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    bins = []
    ece = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        upper = lower + 0.1
        mask = (p >= lower) & (p < upper if upper < 1.0 else p <= upper)
        if not mask.any():
            continue
        observed = float(y[mask].mean())
        predicted = float(p[mask].mean())
        weight = float(mask.mean())
        ece += weight * abs(observed - predicted)
        bins.append({
            "lower": float(lower), "upper": float(upper), "games": int(mask.sum()),
            "meanProbability": predicted, "observedRate": observed, "weight": weight,
        })
    regression = {"intercept": None, "slope": None, "status": "INSUFFICIENT_GAMES_OR_CLASSES"}
    if len(y) >= 20 and len(np.unique(y)) == 2:
        x = np.column_stack([np.ones(len(p)), np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))])
        beta = np.array([0.0, 1.0])
        for _ in range(50):
            fitted = 1.0 / (1.0 + np.exp(-np.clip(x @ beta, -30, 30)))
            weights = fitted * (1 - fitted)
            hessian = x.T @ (weights[:, None] * x) + np.eye(2) * 1e-9
            step = np.linalg.solve(hessian, x.T @ (y - fitted))
            beta += step
            if float(np.max(np.abs(step))) < 1e-10:
                break
        regression = {"intercept": float(beta[0]), "slope": float(beta[1]), "status": "ESTIMATED"}
    return {"ece": float(ece), "bins": bins, **regression}


def _series_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    losses = _loss(y, p)
    briers = _brier(y, p)
    return {
        "games": len(y),
        "logLoss": float(losses.mean()),
        "brier": float(briers.mean()),
        "brierDefinition": BINARY_BRIER,
        "accuracy": float(((p >= 0.5).astype(int) == y).mean()),
        "auc": _auc(y, p),
        "calibration": _calibration(y, p),
    }


def _block_interval(values: np.ndarray, blocks: Sequence[str], *, seed: int = 260915, draws: int = 2_000) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for block, value in zip(blocks, values, strict=True):
        grouped[str(block)].append(float(value))
    keys = sorted(grouped)
    point = float(np.mean(values))
    if len(keys) < 2:
        return {"estimate": point, "lower95": None, "upper95": None, "calendarBlocks": len(keys), "status": "INSUFFICIENT_CALENDAR_BLOCKS"}
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(draws):
        sampled = rng.choice(keys, size=len(keys), replace=True)
        population = [value for key in sampled for value in grouped[str(key)]]
        estimates.append(float(np.mean(population)))
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return {"estimate": point, "lower95": float(lower), "upper95": float(upper), "calendarBlocks": len(keys), "bootstrapDraws": draws, "seed": seed, "status": "ESTIMATED"}


def fit_development_blend(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Freeze one market/model weight using authorized Development rows only."""
    rows = [validate_observation(row) for row in observations if row.get("evidenceRole") == "AUTHORIZED_DEVELOPMENT"]
    eligible = [row for row in rows if row["final"]["status"] == "FINAL" and row["final"]["homeScore"] != row["final"]["awayScore"]]
    if len(eligible) < 30 or len({row["final"]["homeScore"] > row["final"]["awayScore"] for row in eligible}) < 2:
        return {"status": "NOT_FIT_INSUFFICIENT_AUTHORIZED_DEVELOPMENT", "eligibleGames": len(eligible), "weightGrid": "MODEL_0_TO_1_STEP_0.05"}
    y, model, market = _arrays(eligible)[:3]
    candidates = []
    for weight in np.linspace(0.0, 1.0, 21):
        probability = weight * model + (1 - weight) * market
        candidates.append((float(_loss(y, probability).mean()), float(weight)))
    loss, weight = min(candidates, key=lambda item: (item[0], item[1]))
    return {"status": "FROZEN", "modelWeight": weight, "marketWeight": 1 - weight, "developmentGames": len(y), "developmentLogLoss": loss, "weightGrid": "MODEL_0_TO_1_STEP_0.05"}


def _arrays(rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    y = np.asarray([float(row["final"]["homeScore"] > row["final"]["awayScore"]) for row in rows])
    model = []
    market = []
    dates = []
    for row in rows:
        forecast = row["forecast"]
        decisive_mass = forecast["homeWinProbability"] + forecast["awayWinProbability"]
        model.append(forecast["homeWinProbability"] / decisive_mass)
        market.append(float(np.mean([quote["homeNoVigProbability"] for quote in row["market"]["quotes"]])))
        date = _utc(row["eventStartUtc"])
        iso = date.isocalendar()
        dates.append(f"{iso.year}-W{iso.week:02d}")
    return y, np.asarray(model), np.asarray(market), np.full(len(rows), 0.5), dates


def score_benchmark(
    observations: Sequence[Mapping[str, Any]], *,
    scored_at_utc: str,
    frozen_blend: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score unique, finalized, chronologically available game observations."""
    scored_at = _utc(scored_at_utc)
    rows = [validate_observation(value) for value in observations]
    identities = [(row["eventId"], row["market"]["horizon"]) for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("Repeated game/horizon observations are not independent assessment units")
    pending = [row for row in rows if row["final"]["status"] != "FINAL" or _utc(row["final"]["availableAtUtc"]) > scored_at]
    ties = [row for row in rows if row not in pending and row["final"]["homeScore"] == row["final"]["awayScore"]]
    eligible = [row for row in rows if row not in pending and row not in ties]
    by_sport = {}
    for sport in sorted(SPORTS):
        sport_rows = [row for row in eligible if row["sport"] == sport]
        if not sport_rows:
            by_sport[sport] = {"games": 0, "status": "NO_MATCHED_FINAL_OBSERVATIONS"}
            continue
        y, model, market, naive, blocks = _arrays(sport_rows)
        model_loss = _loss(y, model)
        market_loss = _loss(y, market)
        model_brier = _brier(y, model)
        market_brier = _brier(y, market)
        score = {
            "games": len(sport_rows),
            "status": "EXPLORATORY_PROSPECTIVE_ACCUMULATION",
            "model": _series_metrics(y, model),
            "market": _series_metrics(y, market),
            "naive": _series_metrics(y, naive),
            "pairedModelMinusMarket": {
                "logLoss": _block_interval(model_loss - market_loss, blocks),
                "brier": _block_interval(model_brier - market_brier, blocks),
                "direction": "NEGATIVE_FAVORS_MODEL",
            },
        }
        expected_margin = np.asarray([
            row["forecast"]["expectedHomeScore"] - row["forecast"]["expectedAwayScore"]
            for row in sport_rows
        ], dtype=float)
        expected_total = np.asarray([
            row["forecast"]["expectedHomeScore"] + row["forecast"]["expectedAwayScore"]
            for row in sport_rows
        ], dtype=float)
        actual_margin = np.asarray([row["final"]["homeScore"] - row["final"]["awayScore"] for row in sport_rows], dtype=float)
        actual_total = np.asarray([row["final"]["homeScore"] + row["final"]["awayScore"] for row in sport_rows], dtype=float)
        score["modelPointErrors"] = {
            "marginMae": float(np.mean(np.abs(expected_margin - actual_margin))),
            "totalMae": float(np.mean(np.abs(expected_total - actual_total))),
        }
        line_rows = [row for row in sport_rows if row["market"].get("homeMarginLine") is not None and row["market"].get("totalLine") is not None]
        if line_rows:
            market_margin_error = np.asarray([abs(float(row["market"]["homeMarginLine"]) - (row["final"]["homeScore"] - row["final"]["awayScore"])) for row in line_rows])
            market_total_error = np.asarray([abs(float(row["market"]["totalLine"]) - (row["final"]["homeScore"] + row["final"]["awayScore"])) for row in line_rows])
            score["marketPointErrors"] = {"games": len(line_rows), "marginMae": float(market_margin_error.mean()), "totalMae": float(market_total_error.mean())}
        else:
            score["marketPointErrors"] = {"games": 0, "marginMae": None, "totalMae": None}
        if frozen_blend and frozen_blend.get("status") == "FROZEN":
            blend = float(frozen_blend["modelWeight"]) * model + float(frozen_blend["marketWeight"]) * market
            score["frozenDevelopmentBlend"] = _series_metrics(y, blend)
            score["incrementalInformationBeyondMarket"] = {
                "status": "ASSESSED_WITH_FROZEN_DEVELOPMENT_BLEND",
                "blendMinusMarketLogLoss": float(_loss(y, blend).mean() - market_loss.mean()),
                "direction": "NEGATIVE_SUPPORTS_INCREMENTAL_MODEL_INFORMATION",
            }
        else:
            score["frozenDevelopmentBlend"] = {"status": "UNAVAILABLE_NO_FROZEN_AUTHORIZED_DEVELOPMENT_BLEND"}
            score["incrementalInformationBeyondMarket"] = {
                "status": "UNAVAILABLE_NO_FROZEN_AUTHORIZED_DEVELOPMENT_BLEND"
            }
        by_sport[sport] = score
    return {
        "schemaVersion": REPORT_SCHEMA,
        "scoredAtUtc": scored_at_utc,
        "noVigMethod": NO_VIG_METHOD,
        "naiveBaseline": "HOME_WIN_PROBABILITY_0.5",
        "assessmentUnit": "DISTINCT_GAME_AT_DECLARED_HORIZON",
        "sports": by_sport,
        "coverage": {
            "observations": len(rows), "eligibleMatchedFinals": len(eligible),
            "pendingFinals": len(pending), "realizedTiePushesExcludedFromBinaryComparison": len(ties),
            "bySport": {sport: sum(row["sport"] == sport for row in rows) for sport in sorted(SPORTS)},
            "byDecisionHorizon": {horizon: sum(row["market"]["horizon"] == horizon for row in rows) for horizon in sorted(HORIZONS)},
            "missingMarketMarginOrTotalLines": sum(
                row["market"].get("homeMarginLine") is None or row["market"].get("totalLine") is None
                for row in rows
            ),
        },
        "limitations": [
            "Simulation draws and repeated decisions are not assessment units.",
            "NFL winner comparison conditions model probability on a decisive result; full three-way mass remains preserved in each observation.",
            "A two-sided moneyline cannot supply a comparable three-outcome market Brier score for an NFL tie.",
            "Market consensus is the mean proportional no-vig home probability across complete books evaluated at the same as-of time; every leg timestamp remains retained.",
            "Opening and closing labels require actual source evidence; otherwise the capture remains unclassified.",
        ],
    }


__all__ = [
    "BINARY_BRIER", "HORIZONS", "NO_VIG_METHOD", "REPORT_SCHEMA", "SCHEMA",
    "fit_development_blend", "no_vig_home_probability", "score_benchmark", "validate_observation",
]
