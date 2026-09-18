"""Pure NBA Gen1 production forecast assembly and accounting.

Ridge point means, Elo winner probabilities, and paired-residual draws are
separate channels.  This module never fits a model, acquires data, publishes,
or assigns wagering authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

from .joint_residual import DRAW_COUNT, ENGINE, MASTER_SEED, totals_query


SCHEMA = "NBA_GEN1_PRODUCTION_FORECAST_V1"
CONFIGURATION = "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1"


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_bytes(value)
    return hashlib.sha256(raw).hexdigest()


def _pmf(values: np.ndarray) -> list[dict[str, Any]]:
    unique, counts = np.unique(values.astype(np.int64), return_counts=True)
    if int(counts.sum()) != len(values):
        raise AssertionError("PMF count mismatch")
    return [{"value": int(v), "count": int(c), "probability": float(c / len(values))}
            for v, c in zip(unique, counts)]


def _interval(values: np.ndarray, level: int) -> dict[str, Any]:
    alpha = (1 - level / 100) / 2
    lo, hi = np.quantile(values, [alpha, 1 - alpha], method="inverted_cdf")
    return {"level": level / 100, "lower": int(lo), "upper": int(hi),
            "method": "central equal-tail inverted_cdf",
            "units": "points including overtime"}


def summarize_population(draws: np.ndarray) -> dict[str, Any]:
    x = np.asarray(draws)
    if (x.shape != (DRAW_COUNT, 2) or not np.isfinite(x).all()
            or (x < 0).any() or (x != np.floor(x)).any()
            or (x[:, 0] == x[:, 1]).any()):
        raise ValueError("Exactly 10,000 complete nonnegative untied HOME/AWAY integer draws required")
    home, away = x[:, 0].astype(np.int64), x[:, 1].astype(np.int64)
    total, margin = home + away, home - away
    p_home = float((margin > 0).mean())
    mean_total = float(total.mean())
    return {
        "drawCount": DRAW_COUNT,
        "scoreUnits": "points including overtime",
        "probabilityUnits": "fractions from 0 to 1",
        "expectedScores": {"home": float(home.mean()), "away": float(away.mean()),
                           "total": mean_total, "homeMargin": float(margin.mean())},
        "winnerProbabilities": {"home": p_home, "away": 1 - p_home, "tie": 0.0,
            "homeMcse": float(math.sqrt(p_home * (1 - p_home) / DRAW_COUNT)),
            "awayMcse": float(math.sqrt(p_home * (1 - p_home) / DRAW_COUNT))},
        "pmfs": {"home": _pmf(home), "away": _pmf(away),
                 "total": _pmf(total), "margin": _pmf(margin)},
        "intervals": {name: [_interval(values, level) for level in (50, 80, 90)]
                      for name, values in (("home", home), ("away", away),
                                           ("total", total), ("margin", margin))},
        "illustrativeTotals": [totals_query(x, float(round(mean_total))),
                               totals_query(x, float(math.floor(mean_total) + .5))],
    }


def assemble_forecast(*, point_forecast: dict[str, Any], draws: np.ndarray,
                      created_at_utc: str, effective_at_utc: str,
                      handoff: dict[str, Any], bindings: dict[str, Any],
                      population: dict[str, Any]) -> dict[str, Any]:
    if point_forecast.get("configurationIdentity") != CONFIGURATION:
        raise ValueError("Wrong point/Elo configuration")
    if point_forecast["game"]["status"] != "SCHEDULED":
        raise ValueError("Only scheduled prospective games are supported")
    joint = summarize_population(draws)
    elo = point_forecast["winnerProbabilities"]
    if abs(float(elo["home"]) + float(elo["away"]) + float(elo["tie"]) - 1) > 1e-12:
        raise ValueError("Elo probability mass mismatch")
    body = {
        "schema": SCHEMA,
        "forecastHorizon": "PREGAME_PRODUCTION_BASELINE",
        "configurationIdentity": CONFIGURATION,
        "distributionConfigurationIdentity": ENGINE,
        "createdAtUtc": created_at_utc,
        "publishedAtUtc": None,
        "prospectiveEffectiveAtUtc": effective_at_utc,
        "sourceCutoffUtc": point_forecast["sourceCutoffUtc"],
        "game": point_forecast["game"],
        "ridgePointExpectations": point_forecast["pointExpectations"],
        "eloWinnerProbabilities": elo,
        "jointSimulation": joint,
        "population": population,
        "channelSemantics": "Ridge supplies point expectations; chronological Elo supplies the controlling winner probabilities; paired OOF residual draws supply score distributions. These channels are separately estimated.",
        "closeScoreChallenger": {"enabled": False, "disposition": "TESTED_AND_REJECTED"},
        "bindings": {**bindings, "productionHandoff": handoff},
        "monitoring": {"firstReviewCompletedGames": 50, "calibrationAndDistributionReviewCompletedGames": 100,
            "metrics": ["home/away score MAE", "margin MAE", "total MAE", "winner log loss",
                        "binary Brier", "joint energy score", "home/away/total/margin CRPS",
                        "one-point-finish frequency", "regulation versus overtime performance"]},
        "limitations": [
            "Score and Elo channels are separately estimated",
            "Historical simulated one-point finishes were 7.78% versus 4.01% observed",
            "The close-score correction was tested and rejected",
            "Overtime games remain materially harder",
            "No player, lineup, injury, projected-minutes, referee or travel inputs",
            "No profitability claim has been established",
        ],
        "authority": {"productionBaseline": True, "prospectiveOnly": True,
            "requiresConsumerPin": True, "wageringAuthority": False,
            "decisionAuthority": False, "positionAuthority": False,
            "modelPromotionAuthority": False},
    }
    identity = digest(body)
    body["forecastId"] = f"nba-production:{identity}"
    return body


def verify_forecast(forecast: dict[str, Any], draws: np.ndarray) -> None:
    if forecast.get("schema") != SCHEMA or forecast.get("configurationIdentity") != CONFIGURATION:
        raise ValueError("Wrong production forecast identity")
    if forecast.get("distributionConfigurationIdentity") != ENGINE:
        raise ValueError("Wrong joint distribution identity")
    expected = summarize_population(draws)
    if forecast.get("jointSimulation") != expected:
        raise ValueError("Forecast summary does not reproduce population")
    game = forecast["game"]
    if game["home_team_id"] == game["away_team_id"]:
        raise ValueError("Invalid orientation")
    if forecast["population"]["drawCount"] != DRAW_COUNT:
        raise ValueError("Population denominator mismatch")
    if forecast["closeScoreChallenger"]["enabled"] is not False:
        raise ValueError("Close-score challenger must remain disabled")

