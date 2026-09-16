from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .pipeline import SIMULATION_COUNT, frequency_rows, simulate_paired_residuals


MIN_CHALLENGER_DONORS = 500
INSUFFICIENT_CURRENT_GAMES = 2


def _stat_value(team: dict[str, Any], category: str) -> float:
    for item in team.get("stats") or []:
        if item.get("category") == category:
            raw = item.get("stat")
            if raw is None:
                raw = item.get("value")
            try:
                return float(str(raw).replace(",", ""))
            except (TypeError, ValueError):
                return float("nan")
    return float("nan")


def cfbd_2026_games(
    schedule: list[dict[str, Any]],
    team_games: list[dict[str, Any]],
) -> pd.DataFrame:
    """Adapt retained CFBD responses to the frozen Gen 1 game contract."""
    boxes: dict[tuple[int, int], dict[str, float]] = {}
    for game in team_games:
        game_id = int(game["id"])
        for team in game.get("teams") or []:
            team_id = int(team["teamId"])
            boxes[(game_id, team_id)] = {
                "total_yards": _stat_value(team, "totalYards"),
                "turnovers": _stat_value(team, "turnovers"),
            }

    rows: list[dict[str, Any]] = []
    for game in schedule:
        game_id = int(game["id"])
        home_id = int(game["homeId"])
        away_id = int(game["awayId"])
        completed = bool(game.get("completed"))
        home_score = pd.to_numeric(game.get("homePoints"), errors="coerce")
        away_score = pd.to_numeric(game.get("awayPoints"), errors="coerce")
        score_supported = completed and pd.notna(home_score) and pd.notna(away_score)
        home_fbs = str(game.get("homeClassification") or "").casefold() == "fbs"
        away_fbs = str(game.get("awayClassification") or "").casefold() == "fbs"
        season_type = 2 if str(game.get("seasonType") or "").casefold() == "regular" else 3
        home_lines = game.get("homeLineScores") or []
        away_lines = game.get("awayLineScores") or []
        period_supported = score_supported and bool(home_lines) and bool(away_lines)
        period_reconciles = (
            period_supported
            and sum(x for x in home_lines if x is not None) == home_score
            and sum(x for x in away_lines if x is not None) == away_score
        )
        home_box = boxes.get((game_id, home_id), {})
        away_box = boxes.get((game_id, away_id), {})
        both_boxes = (game_id, home_id) in boxes and (game_id, away_id) in boxes
        tied = score_supported and home_score == away_score
        identity_supported = home_id > 0 and away_id > 0 and home_id != away_id
        scope_primary = identity_supported and home_fbs and away_fbs and season_type == 2 and int(game["week"]) <= 14
        rows.append({
            "game_id": game_id,
            "season": int(game["season"]),
            "week": int(game["week"]),
            "season_type": season_type,
            "game_date": game["startDate"],
            "neutral_site": bool(game.get("neutralSite")),
            "conference_competition": bool(game.get("conferenceGame")),
            "home_id": home_id,
            "away_id": away_id,
            "home_team": game["homeTeam"],
            "away_team": game["awayTeam"],
            "home_score": float(home_score) if score_supported else np.nan,
            "away_score": float(away_score) if score_supported else np.nan,
            "status": "STATUS_FINAL" if completed else "STATUS_SCHEDULED",
            "scheduled_at": pd.Timestamp(game["startDate"]),
            "is_final": completed,
            "score_supported": score_supported,
            "home_margin": float(home_score-away_score) if score_supported else np.nan,
            "total_points": float(home_score+away_score) if score_supported else np.nan,
            "home_win": float(home_score > away_score) if score_supported else np.nan,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_is_fbs": home_fbs,
            "away_is_fbs": away_fbs,
            "home_classification": game.get("homeClassification"),
            "away_classification": game.get("awayClassification"),
            "home_conference_name": game.get("homeConference"),
            "away_conference_name": game.get("awayConference"),
            "home_total_yards": home_box.get("total_yards", np.nan),
            "home_turnovers": home_box.get("turnovers", np.nan),
            "away_total_yards": away_box.get("total_yards", np.nan),
            "away_turnovers": away_box.get("turnovers", np.nan),
            "both_box_rows": both_boxes,
            "home_period_count": len(home_lines) if home_lines else np.nan,
            "away_period_count": len(away_lines) if away_lines else np.nan,
            "home_period_score_sum": float(sum(x for x in home_lines if x is not None)) if home_lines else np.nan,
            "away_period_score_sum": float(sum(x for x in away_lines if x is not None)) if away_lines else np.nan,
            "period_supported": period_supported,
            "period_reconciles": period_reconciles,
            "overtime": max(len(home_lines), len(away_lines)) > 4,
            "identity_supported": identity_supported,
            "both_fbs": home_fbs and away_fbs,
            "either_exhibition": False,
            "tied_final": tied,
            "late_regular_unclassified": score_supported and season_type == 2 and int(game["week"]) > 14,
            "postseason": season_type == 3,
            "primary": score_supported and scope_primary and not tied,
            "scope_primary": scope_primary,
            "context_eligible": score_supported and identity_supported and not tied,
            "role": "prospective_current",
            "cfbd_home_pregame_elo": game.get("homePregameElo"),
            "cfbd_away_pregame_elo": game.get("awayPregameElo"),
        })
    frame = pd.DataFrame(rows).sort_values(["scheduled_at", "game_id"]).reset_index(drop=True)
    if frame["game_id"].duplicated().any():
        raise ValueError("duplicate CFBD source game IDs")
    return frame


def uncertainty_support(row: pd.Series) -> str:
    early = min(int(row["home_current_season_games"]), int(row["away_current_season_games"])) < INSUFFICIENT_CURRENT_GAMES
    gap = bool(row["home_long_gap"]) or bool(row["away_long_gap"])
    if early and gap:
        return "EARLY_SEASON_AND_EXTENDED_GAP"
    if early:
        return "EARLY_SEASON"
    if gap:
        return "EXTENDED_GAP"
    return "ORDINARY"


def tagged_uncertainty_donors(predictions: pd.DataFrame) -> pd.DataFrame:
    result = predictions.copy()
    result["uncertainty_support"] = result.apply(uncertainty_support, axis=1)
    return result


def simulate_uncertainty_challenger(
    target: pd.Series,
    predictions: pd.DataFrame,
    model: str,
    draw_count: int = SIMULATION_COUNT,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    earlier = predictions[predictions["scheduled_at"] < target["scheduled_at"]].copy()
    baseline, baseline_accounting = simulate_paired_residuals(target, earlier, model, draw_count=draw_count)
    support = uncertainty_support(target)
    if support == "ORDINARY":
        return baseline, baseline.copy(), {
            "support": support,
            "applied": False,
            "disposition": "EXACT_BASELINE_ORDINARY",
            "candidateDonorCount": 0,
            "baseline": baseline_accounting,
            "candidate": baseline_accounting,
        }
    tagged = tagged_uncertainty_donors(earlier)
    donors = tagged[tagged["uncertainty_support"] != "ORDINARY"].copy()
    if len(donors) < MIN_CHALLENGER_DONORS:
        return baseline, baseline.copy(), {
            "support": support,
            "applied": False,
            "disposition": "EXACT_BASELINE_INSUFFICIENT_DONORS",
            "candidateDonorCount": int(len(donors)),
            "minimumDonors": MIN_CHALLENGER_DONORS,
            "baseline": baseline_accounting,
            "candidate": baseline_accounting,
        }
    home_pred = f"{model}_pred_home"
    away_pred = f"{model}_pred_away"
    home_residual = donors["home_score"] - donors[home_pred]
    away_residual = donors["away_score"] - donors[away_pred]
    home_mean = float(home_residual.mean())
    away_mean = float(away_residual.mean())
    donors[home_pred] = donors[home_pred] + home_mean
    donors[away_pred] = donors[away_pred] + away_mean
    candidate, candidate_accounting = simulate_paired_residuals(target, donors, model, draw_count=draw_count)
    return baseline, candidate, {
        "support": support,
        "applied": True,
        "disposition": "CENTERED_EARLY_OR_GAP_RESIDUALS",
        "candidateDonorCount": int(len(donors)),
        "minimumDonors": MIN_CHALLENGER_DONORS,
        "homeResidualMeanRemoved": home_mean,
        "awayResidualMeanRemoved": away_mean,
        "centeredHomeResidualMean": float((donors["home_score"]-donors[home_pred]).mean()),
        "centeredAwayResidualMean": float((donors["away_score"]-donors[away_pred]).mean()),
        "baseline": baseline_accounting,
        "candidate": candidate_accounting,
    }


def totals_probabilities(draws: pd.DataFrame, line: float) -> dict[str, float | int]:
    total = draws["total"].to_numpy()
    over = float(np.mean(total > line))
    push = float(np.mean(total == line))
    under = float(np.mean(total < line))
    return {"line": float(line), "over": over, "push": push, "under": under, "drawCount": int(len(total))}


def interval_table(draws: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in ("away_score", "home_score", "total", "home_margin"):
        for level in (50, 80, 90):
            alpha = (100-level)/200
            low, high = np.quantile(draws[metric], [alpha, 1-alpha])
            rows.append({"metric": metric, "level": level, "lower": float(low), "upper": float(high)})
    return rows


def population_tables(game_id: int, draws: pd.DataFrame) -> pd.DataFrame:
    return frequency_rows(game_id, draws)
